"""Test Rocket League Native Companion Client."""
from __future__ import annotations

import json
import socket
import threading
import time
from typing import Generator

import pytest

from coach_app.companion import (
    RocketLeagueCompanion,
    CompanionConnectionError,
    CompanionProtocolError,
    ConfigurationDiagnostics,
    SETUP_INSTRUCTIONS,
    diagnose_configuration,
    resolve_spectator_shortcut,
    validate_native_command,
)


class MockRocketLeagueServer:
    """Mock TCP/WebSocket server simulating Rocket League Stats API on loopback."""

    def __init__(self, port: int = 0):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.bind(("127.0.0.1", port))
        self.port = self.server_sock.getsockname()[1]
        self.server_sock.listen(1)
        self.running = True
        self.received_commands = []
        self.elapsed = 0.0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while self.running:
            try:
                self.server_sock.settimeout(0.2)
                conn, _ = self.server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with conn:
                conn.settimeout(0.5)
                buffer = ""
                while self.running:
                    try:
                        data = conn.recv(1024).decode("utf-8")
                        if not data:
                            break
                        buffer += data
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            payload = json.loads(line)
                            self.received_commands.append(payload)
                            cmd = payload.get("Command")
                            
                            # Echo official Response
                            response = {
                                "Response": cmd,
                                "Success": True,
                                "Data": {"Acknowledged": True},
                            }
                            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))

                            # Also stream async PlaybackState update
                            if "TimeSeconds" in payload.get("Data", {}):
                                self.elapsed = payload["Data"]["TimeSeconds"]
                            if "bPaused" in payload.get("Data", {}):
                                self.paused = payload["Data"]["bPaused"]
                            if "Speed" in payload.get("Data", {}):
                                self.speed = payload["Data"]["Speed"]

                            # Official UpdateState payload nests replay clock
                            # under Game.Elapsed; Game.TimeSeconds is countdown.
                            state_data = {
                                "Game": {
                                    "bReplay": True,
                                    "Elapsed": self.elapsed,
                                    "TimeSeconds": 180,
                                    "bMatchPaused": getattr(self, "paused", False),
                                    "bPaused": getattr(self, "paused", False),
                                    "GameSpeed": getattr(self, "speed", 1.0),
                                    "Speed": getattr(self, "speed", 1.0),
                                },
                            }
                            state_event = {
                                "Event": "UpdateState",
                                "Data": state_data,
                            }
                            conn.sendall((json.dumps(state_event) + "\n").encode("utf-8"))
                    except (socket.timeout, OSError):
                        break

    def stop(self):
        self.running = False
        try:
            self.server_sock.close()
        except OSError:
            pass


def test_companion_offline_detection():
    # Choose a high random port that is definitely not listening
    companion = RocketLeagueCompanion(host="127.0.0.1", tcp_port=59998, ws_port=59999, probe_timeout=0.1)
    status = companion.get_status()
    assert not status.available
    assert not status.connected
    assert "Stats API is not confirmed available" in status.instructions


def test_companion_mock_server_interaction():
    server = MockRocketLeagueServer()
    try:
        companion = RocketLeagueCompanion(
            host="127.0.0.1",
            tcp_port=server.port,
            ws_port=server.port + 1,
            probe_timeout=0.5,
            command_timeout=1.0,
            enabled=True,
        )
        assert companion.connect(server.port)
        assert companion.is_connected()

        # 1. Test LoadReplay
        res_load = companion.load_replay("23A661D44DBC5964B0718DBC5F956A33.replay")
        assert res_load["Command"] == "LoadReplay"

        # 2. Test SeekReplay
        res_seek = companion.seek_replay(15.25)
        assert res_seek["Command"] == "SeekReplay"

        # 3. Test ChangePOV with official Focus schema
        res_pov = companion.change_pov(focus="1", perspective="PlayerView")
        assert res_pov["Command"] == "ChangePOV"

        # 4. Test SetGameSpeed and SetMatchPaused
        companion.set_game_speed(0.5)
        companion.set_match_paused(True)
        companion.set_hud_visibility(False)

        # Allow background reader thread to ingest responses
        time.sleep(0.1)

        # Verify command payloads sent over wire
        cmds = [c["Command"] for c in server.received_commands]
        assert "LoadReplay" in cmds
        assert "SeekReplay" in cmds
        assert "ChangePOV" in cmds
        assert "SetGameSpeed" in cmds
        assert "SetMatchPaused" in cmds
        assert "SetHUDVisibility" in cmds
        assert next(c for c in server.received_commands if c["Command"] == "LoadReplay")["Data"] == {
            "FileName": "23A661D44DBC5964B0718DBC5F956A33.replay"
        }
        assert next(c for c in server.received_commands if c["Command"] == "SetMatchPaused")["Data"] == {"bPaused": True}
        assert next(c for c in server.received_commands if c["Command"] == "SetHUDVisibility")["Data"] == {"bVisible": False}

        # Verify ChangePOV schema conforms to official Focus requirement
        pov_cmd = next(c for c in server.received_commands if c["Command"] == "ChangePOV")
        assert pov_cmd["Data"] == {"Focus": "1", "Perspective": "PlayerView"}

        # 5. Test Playback Observation and Drift Measurement
        state = companion.observe_playback_state()
        assert state["reported_time_seconds"] == 15.25
        drift = companion.measure_drift(expected_time_s=15.0)
        assert drift == 0.25

        companion.disconnect()
        assert not companion.is_connected()
    finally:
        server.stop()


def test_companion_protocol_validation():
    companion = RocketLeagueCompanion()
    with pytest.raises(CompanionProtocolError):
        companion.load_replay("")

    with pytest.raises(CompanionProtocolError):
        companion.change_pov("")



def test_native_command_schema_rejects_undocumented_fields_before_network():
    from math import nan, inf

    good = {
        "LoadReplay": {"FileName": "Stadium_P_2026-06-05_18-42"},
        "SeekReplay": {"TimeSeconds": 0.0},
        "ChangePOV": {"Focus": "2", "Perspective": "PlayerView"},
        "SetMatchPaused": {"bPaused": True},
        "SetHUDVisibility": {"bVisible": False},
        "SetGameSpeed": {"Speed": 1.5},
    }
    for command, payload in good.items():
        assert validate_native_command(command, payload) == payload
    bad = [
        ("LoadReplay", {"Replay": "foo.replay"}),
        ("LoadReplay", {"FileName": "foo", "Path": "bar"}),
        ("ChangePOV", {"Focus": "Plormby", "Target": "Ball"}),
        ("ChangePOV", {"Focus": "1", "Target": "Ball"}),
        ("ChangePOV", {"Focus": "Player"}),
        ("ChangePOV", {"Perspective": "NOPE"}),
        ("SeekReplay", {"TimeSeconds": nan}),
        ("SeekReplay", {"TimeSeconds": inf}),
        ("SeekReplay", {"Frame": -1}),
        ("SetGameSpeed", {"Speed": -2}),
        ("SetMatchPaused", {"Paused": True}),
        ("SetHUDVisibility", {"Visible": True}),
        ("GetStatus", {}),
        ("ArbitraryCommand", {"Anything": 1}),
    ]
    for command, payload in bad:
        with pytest.raises(CompanionProtocolError):
            validate_native_command(command, payload)
    # No player-name substitution or fabricated guessing of spectator IDs.
    c = RocketLeagueCompanion()
    with pytest.raises(CompanionProtocolError):
        c.change_pov("Plormby")
    with pytest.raises(CompanionProtocolError):
        c.change_pov("1", "car_cam")
    with pytest.raises(CompanionProtocolError):
        c.seek_replay(float("nan"))
    with pytest.raises(CompanionProtocolError):
        c.set_game_speed(float("inf"))


def test_native_api_status_probe_does_not_open_a_game_command_session():
    server = MockRocketLeagueServer()
    try:
        c = RocketLeagueCompanion(
            tcp_port=server.port, ws_port=server.port + 1,
            probe_timeout=0.1,
        )
        before = len(server.received_commands)
        status = c.get_status()
        assert status.available
        assert not status.connected
        assert status.transport == "none"
        assert c._reader_thread is None
        assert len(server.received_commands) == before
        # A bare TCP socket on the WS port cannot speak WebSocket frames.
        ws_only = RocketLeagueCompanion(
            tcp_port=server.port + 1, ws_port=server.port, probe_timeout=0.1
        )
        assert not ws_only.connect(server.port)
        assert not ws_only.is_connected()
        assert ws_only.get_status().available
    finally:
        server.stop()


def test_replay_elapsed_zero_is_preserved_and_not_confused_with_match_countdown():
    c = RocketLeagueCompanion()
    c._process_inbound_line(json.dumps({
        "Event": "UpdateState",
        "Data": {"Game": {"bReplay": True, "Elapsed": 0.0,
                          "TimeSeconds": 240}},
    }))
    assert c.observe_playback_state()["reported_time_seconds"] == 0.0
    c._process_inbound_line(json.dumps({
        "Event": "UpdateState",
        "Data": {"Game": {"bReplay": True, "Elapsed": 12.75,
                          "TimeSeconds": 227}},
    }))
    assert c.observe_playback_state()["reported_time_seconds"] == 12.75
    assert c.measure_drift(13.0) == -0.25


def test_diagnose_configuration_custom_dir(tmp_path):
    doc_cfg = tmp_path / "Documents" / "My Games" / "Rocket League" / "TAGame" / "Config"
    doc_cfg.mkdir(parents=True)
    ini_file = doc_cfg / "TAStatsAPI.ini"
    ini_file.write_text("[TAGame.MatchStatsExporter_TA]\nPort=49123\nWebPort=49124\nPacketSendRate=30\n", encoding="utf-8")

    diag = diagnose_configuration(custom_documents_dir=str(tmp_path / "Documents" / "My Games" / "Rocket League"))
    assert diag.status == "CONFIGURED_ENABLED"
    assert diag.effective_packet_send_rate == 30
    assert diag.documents_packet_send_rate == 30
    assert diag.tcp_port == 49123
    assert "Documents: 30" in diag.instructions


def test_diagnose_configuration_muted_dir(tmp_path):
    doc_cfg = tmp_path / "Documents" / "My Games" / "Rocket League" / "TAGame" / "Config"
    doc_cfg.mkdir(parents=True)
    ini_file = doc_cfg / "TAStatsAPI.ini"
    ini_file.write_text("[TAGame.MatchStatsExporter_TA]\nPort=49123\nWebPort=49124\nPacketSendRate=0\n", encoding="utf-8")

    diag = diagnose_configuration(custom_documents_dir=str(tmp_path / "Documents" / "My Games" / "Rocket League"))
    assert diag.status == "CONFIGURED_MUTED"
    assert diag.effective_packet_send_rate == 0
    assert "PacketSendRate is 0" in diag.instructions
    assert "TAStatsAPI.ini" in diag.instructions


def test_diagnose_configuration_not_found(tmp_path):
    empty_dir = tmp_path / "Empty"
    empty_dir.mkdir()
    diag = diagnose_configuration(custom_documents_dir=str(empty_dir), custom_install_dir=str(empty_dir))
    assert diag.status == "NOT_FOUND"
    assert diag.effective_packet_send_rate is None
    assert "Stats API is not confirmed available" in diag.instructions


def test_diagnose_configuration_real_environment():
    diag = diagnose_configuration()
    # Portable check: on machines without Rocket League (such as CI runners), skip gracefully
    if not diag.documents_ini_path and not diag.install_ini_path:
        pytest.skip("Rocket League configuration not detected on this machine (portable CI environment).")
    assert diag.status in ("CONFIGURED_MUTED", "CONFIGURED_ENABLED")
    if diag.documents_ini_path:
        assert diag.documents_ini_path.endswith("TAStatsAPI.ini")
    if diag.install_ini_path:
        assert diag.install_ini_path.endswith("DefaultStatsAPI.ini")
    assert diag.tcp_port == 49123
    assert diag.web_port == 49124


def test_resolve_spectator_shortcut():
    players = [
        {"PrimaryId": "Steam_001", "Name": "Musty", "Shortcut": "1", "TeamNum": 0},
        {"PrimaryId": "Steam_002", "Name": "Ament", "Shortcut": "2", "TeamNum": 0},
        {"PrimaryId": "Epic_003", "Name": "Squishy", "Shortcut": "5", "TeamNum": 1},
        {"PrimaryId": "Epic_004", "Name": "GarrettG", "Shortcut": "6", "TeamNum": 1},
        {"PrimaryId": "Bot_005", "Name": "NoShortcutBot", "TeamNum": 0},
    ]

    # 1. Ball
    assert resolve_spectator_shortcut(players, "Ball") == "Ball"
    assert resolve_spectator_shortcut(players, "ball") == "Ball"

    # 2. Direct integers and numeric strings
    assert resolve_spectator_shortcut(players, 1) == "1"
    assert resolve_spectator_shortcut(players, 8) == "8"
    assert resolve_spectator_shortcut(players, "3") == "3"
    with pytest.raises(CompanionProtocolError):
        resolve_spectator_shortcut(players, 0)
    with pytest.raises(CompanionProtocolError):
        resolve_spectator_shortcut(players, 9)
    with pytest.raises(CompanionProtocolError):
        resolve_spectator_shortcut(players, "9")

    # 3. Resolve by name with official Shortcut field
    assert resolve_spectator_shortcut(players, "Musty") == "1"
    assert resolve_spectator_shortcut(players, "musty") == "1"
    assert resolve_spectator_shortcut(players, "Ament") == "2"

    # 4. Resolve by PrimaryId
    assert resolve_spectator_shortcut(players, "Steam_002") == "2"
    assert resolve_spectator_shortcut(players, "steam_002") == "2"

    # 5. Resolve Orange team player with official Shortcut
    assert resolve_spectator_shortcut(players, "Squishy") == "5"
    assert resolve_spectator_shortcut(players, "GarrettG") == "6"

    # 6. Refuse to guess shortcuts when Shortcut telemetry is missing
    with pytest.raises(CompanionProtocolError) as exc_info:
        resolve_spectator_shortcut(players, "NoShortcutBot")
    assert "does not have an official 'Shortcut'" in str(exc_info.value)
    assert "must not be guessed from arbitrary roster ordering" in str(exc_info.value)

    # 7. Unmatched player
    with pytest.raises(CompanionProtocolError) as exc_info:
        resolve_spectator_shortcut(players, "NonExistentPlayer")
    assert "not found" in str(exc_info.value)

    # 8. Ambiguous player
    duplicate_players = [
        {"PrimaryId": "1", "Name": "Clone", "Shortcut": "1", "TeamNum": 0},
        {"PrimaryId": "2", "Name": "Clone", "Shortcut": "5", "TeamNum": 1},
    ]
    with pytest.raises(CompanionProtocolError) as exc_info:
        resolve_spectator_shortcut(duplicate_players, "Clone")
    assert "Ambiguous" in str(exc_info.value)


def test_dual_clock_telemetry_observation():
    c = RocketLeagueCompanion(enabled=True)
    c._process_inbound_line(json.dumps({
        "Event": "UpdateState",
        "Data": {
            "Game": {
                "bReplay": True,
                "Elapsed": 45.5,
                "SecondsRemaining": 254.5,
                "bMatchPaused": False,
                "Speed": 1.0,
            }
        },
    }))
    obs = c.observe_playback_state()
    assert obs["is_replay"] is True
    assert obs["replay_elapsed_seconds"] == 45.5
    assert obs["match_clock_seconds_remaining"] == 254.5
    assert obs["reported_time_seconds"] == 45.5
    assert obs["is_paused"] is False
    assert obs["game_speed"] == 1.0

    # Drift is measured against replay_elapsed_seconds, not match_clock_seconds_remaining
    assert c.measure_drift(45.0) == 0.5


def test_companion_opt_in_workflow():
    c = RocketLeagueCompanion(enabled=False, require_opt_in=True)
    with pytest.raises(CompanionProtocolError) as exc_info:
        c.send_command("SetGameSpeed", {"Speed": 1.0})
    assert "Native game commands are disabled" in str(exc_info.value)

    c.enable_commands(True)
    assert c.commands_enabled is True


def test_companion_replay_path_validation():
    c = RocketLeagueCompanion(enabled=True)

    # Path traversal rejected
    with pytest.raises(CompanionProtocolError):
        validate_native_command("LoadReplay", {"Path": "../secret/demo.replay"})
    with pytest.raises(CompanionProtocolError):
        validate_native_command("LoadReplay", {"FileName": "../demo.replay"})
    with pytest.raises(CompanionProtocolError):
        validate_native_command("LoadReplay", {"FileName": "folder/demo.replay"})

    # Non .replay extension rejected
    with pytest.raises(CompanionProtocolError):
        validate_native_command("LoadReplay", {"Path": "C:/Windows/notepad.exe"})

    # Valid paths accepted
    res_path = validate_native_command("LoadReplay", {"Path": "D:/MyGames/test.replay"})
    assert res_path == {"Path": "D:/MyGames/test.replay"}

    res_fn = validate_native_command("LoadReplay", {"FileName": "028EA2CD420A3913ACA4CDBC149F9EA5.replay"})
    assert res_fn == {"FileName": "028EA2CD420A3913ACA4CDBC149F9EA5.replay"}


def test_full_companion_simulated_acceptance_roundtrip():
    """Step C Full Simulated Round-Trip: 7 core native replay operations with state verification."""
    server = MockRocketLeagueServer()
    try:
        companion = RocketLeagueCompanion(
            host="127.0.0.1",
            tcp_port=server.port,
            ws_port=server.port + 1,
            probe_timeout=0.5,
            command_timeout=1.0,
            enabled=True,
            require_opt_in=True,
        )
        assert companion.connect(server.port)
        assert companion.is_connected()

        report = companion.verify_native_replay_acceptance("028EA2CD420A3913ACA4CDBC149F9EA5.replay", timeout=2.0)
        assert report["all_passed"] is True
        assert report["failed_step"] is None
        assert len(report["steps"]) == 7
        assert all(s["status"] == "PASS" for s in report["steps"])
        assert report["drift_seconds"] == 0.0

        companion.disconnect()
        assert not companion.is_connected()
    finally:
        server.stop()


def test_companion_acceptance_reports_fail_on_unconfirmed_state():
    """Verify acceptance sequence halts and reports FAIL when a state change is unconfirmed."""
    class StubUncooperativeServer:
        def __init__(self):
            self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_sock.bind(("127.0.0.1", 0))
            self.port = self.server_sock.getsockname()[1]
            self.server_sock.listen(1)
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

        def _run(self):
            while self.running:
                try:
                    self.server_sock.settimeout(0.2)
                    conn, _ = self.server_sock.accept()
                except (socket.timeout, OSError):
                    continue
                with conn:
                    # Echo response, but NEVER transition to bReplay=True
                    conn.settimeout(0.5)
                    while self.running:
                        try:
                            data = conn.recv(1024)
                            if not data:
                                break
                            # Stream non-replay state
                            evt = {"Event": "UpdateState", "Data": {"Game": {"bReplay": False, "Elapsed": 0.0}}}
                            conn.sendall((json.dumps(evt) + "\n").encode("utf-8"))
                        except (socket.timeout, OSError):
                            break

        def stop(self):
            self.running = False
            try:
                self.server_sock.close()
            except OSError:
                pass

    server = StubUncooperativeServer()
    try:
        companion = RocketLeagueCompanion(
            host="127.0.0.1",
            tcp_port=server.port,
            ws_port=server.port + 1,
            probe_timeout=0.2,
            command_timeout=0.5,
            enabled=True,
        )
        assert companion.connect(server.port)
        # Should timeout waiting for is_replay=True and report FAIL on Step 1
        report = companion.verify_native_replay_acceptance("test.replay", timeout=0.3)
        assert report["all_passed"] is False
        assert report["failed_step"] == 1
        assert report["steps"][0]["status"] == "FAIL"
        assert "did not report is_replay=True" in report["steps"][0]["reason"]
        companion.disconnect()
    finally:
        server.stop()


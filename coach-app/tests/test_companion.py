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
                            # Official UpdateState payload nests replay clock
                            # under Game.Elapsed; Game.TimeSeconds is countdown.
                            state_data = {
                                "Game": {
                                    "bReplay": True,
                                    "Elapsed": self.elapsed,
                                    "TimeSeconds": 180,
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
    assert "PacketSendRate=30" in diag.instructions


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
    # On this local development workstation, Rocket League configuration is verified present
    assert diag.status in ("CONFIGURED_MUTED", "CONFIGURED_ENABLED")
    assert diag.documents_ini_path is not None
    assert diag.documents_ini_path.endswith("TAStatsAPI.ini")
    assert diag.install_ini_path is not None
    assert diag.install_ini_path.endswith("DefaultStatsAPI.ini")
    assert diag.tcp_port == 49123
    assert diag.web_port == 49124


def test_resolve_spectator_shortcut():
    players = [
        {"Id": "Steam_001", "Name": "Musty", "Team": 0},
        {"Id": "Steam_002", "Name": "Ament", "Team": 0},
        {"Id": "Epic_003", "Name": "Squishy", "Team": 1},
        {"Id": "Epic_004", "Name": "GarrettG", "Team": 1, "SpectatorShortcut": "6"},
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

    # 3. Resolve by name (case-insensitive)
    assert resolve_spectator_shortcut(players, "Musty") == "1"
    assert resolve_spectator_shortcut(players, "musty") == "1"
    assert resolve_spectator_shortcut(players, "Ament") == "2"

    # 4. Resolve by ID
    assert resolve_spectator_shortcut(players, "Steam_002") == "2"
    assert resolve_spectator_shortcut(players, "steam_002") == "2"

    # 5. Resolve Orange team (team 1 inferred index = 5)
    assert resolve_spectator_shortcut(players, "Squishy") == "5"

    # 6. Resolve Orange team (explicit shortcut = 6)
    assert resolve_spectator_shortcut(players, "GarrettG") == "6"

    # 7. Unmatched player
    with pytest.raises(CompanionProtocolError) as exc_info:
        resolve_spectator_shortcut(players, "NonExistentPlayer")
    assert "not found" in str(exc_info.value)

    # 8. Ambiguous player
    duplicate_players = [
        {"Id": "1", "Name": "Clone", "Team": 0},
        {"Id": "2", "Name": "Clone", "Team": 1},
    ]
    with pytest.raises(CompanionProtocolError) as exc_info:
        resolve_spectator_shortcut(duplicate_players, "Clone")
    assert "Ambiguous" in str(exc_info.value)


def test_dual_clock_telemetry_observation():
    c = RocketLeagueCompanion()
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
    c = RocketLeagueCompanion()

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
    """Step C Full Simulated Round-Trip: 7 core native replay operations against mock server."""
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

        players = [
            {"Id": "Steam_001", "Name": "Musty", "Team": 0},
            {"Id": "Steam_002", "Name": "Ament", "Team": 0},
            {"Id": "Epic_003", "Name": "Squishy", "Team": 1},
        ]

        # 1. Load a real replay by name
        res_load = companion.load_replay("028EA2CD420A3913ACA4CDBC149F9EA5.replay")
        assert res_load["Status"] == "Sent"

        # 2. Seek to a chosen moment
        res_seek = companion.seek_replay(32.5)
        assert res_seek["Status"] == "Sent"

        # 3. Select a specific player & change POV
        res_pov1 = companion.change_pov_to_player(players, "Musty", perspective="PlayerView")
        assert res_pov1["Status"] == "Sent"

        # 4. Switch to alternative perspective (Fly)
        res_pov2 = companion.change_pov(perspective="Fly")
        assert res_pov2["Status"] == "Sent"

        # 5. Pause and resume
        companion.set_match_paused(True)
        companion.set_match_paused(False)

        # 6. Change playback speed
        companion.set_game_speed(0.5)

        # Allow inbound loop to process server replies
        time.sleep(0.1)

        # 7. Verify reported state, time alignment and focus
        state = companion.observe_playback_state()
        assert state["connected"] is True
        assert state["reported_time_seconds"] == 32.5
        assert companion.measure_drift(32.5) == 0.0

        companion.disconnect()
        assert not companion.is_connected()
    finally:
        server.stop()


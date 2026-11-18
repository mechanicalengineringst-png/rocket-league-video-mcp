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
    SETUP_INSTRUCTIONS,
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

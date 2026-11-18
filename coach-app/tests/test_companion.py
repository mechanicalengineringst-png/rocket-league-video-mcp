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
                            state_data = {
                                "IsPaused": False,
                                "GameSpeed": 1.0,
                            }
                            if "TimeSeconds" in payload.get("Data", {}):
                                state_data["TimeSeconds"] = payload["Data"]["TimeSeconds"]
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
    assert "Rocket League Native Stats API is offline" in status.instructions


def test_companion_mock_server_interaction():
    server = MockRocketLeagueServer()
    try:
        companion = RocketLeagueCompanion(
            host="127.0.0.1",
            tcp_port=server.port,
            ws_port=server.port,
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
        res_pov = companion.change_pov(focus="Plormby", target="Ball")
        assert res_pov["Command"] == "ChangePOV"

        # 4. Test SetGameSpeed and SetMatchPaused
        companion.set_game_speed(0.5)
        companion.set_match_paused(True)

        # Allow background reader thread to ingest responses
        time.sleep(0.1)

        # Verify command payloads sent over wire
        cmds = [c["Command"] for c in server.received_commands]
        assert "LoadReplay" in cmds
        assert "SeekReplay" in cmds
        assert "ChangePOV" in cmds
        assert "SetGameSpeed" in cmds
        assert "SetMatchPaused" in cmds

        # Verify ChangePOV schema conforms to official Focus requirement
        pov_cmd = next(c for c in server.received_commands if c["Command"] == "ChangePOV")
        assert pov_cmd["Data"]["Focus"] == "Plormby"
        assert pov_cmd["Data"]["Target"] == "Ball"

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

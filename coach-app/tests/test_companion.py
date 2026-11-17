"""Unit and integration tests for Rocket League Native Game Companion.

Tests strict conformance to official TAGame.MatchStatsExporter_TA protocol:
- Outbound schema: {"Command": "<CommandName>", "Data": { ... }}
- Strict PascalCase command names and data arguments
- Rejection of invalid snake_case keys or malformed framing
- Multiplexing of asynchronous event streaming alongside command responses
- Non-verification of real-game state when offline or simulated
"""

from __future__ import annotations

import json
import socket
import threading
import time
import pytest

from coach_app.companion import (
    RocketLeagueCompanion,
    CompanionConnectionError,
    CompanionProtocolError,
    SETUP_INSTRUCTIONS,
)

OFFICIAL_COMMAND_SCHEMA = {
    "SeekReplay": ["TimeSeconds"],
    "LoadReplay": ["Replay"],
    "ChangePOV": ["Target"],
    "SetGameSpeed": ["Speed"],
    "SetMatchPaused": ["Paused"],
    "SetHUDVisibility": ["Visible"],
    "GetStatus": [],
}


class StrictOfficialRocketLeagueServer:
    """Mock TCP server emulating official TAGame.MatchStatsExporter_TA.

    Strictly rejects:
    - Missing 'Command' or 'Data' keys
    - Snake_case command names (e.g. 'seek_replay')
    - Snake_case parameter keys (e.g. 'time_seconds')
    - Non-PascalCase payloads
    """

    def __init__(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.bind(("127.0.0.1", 0))
        self.host, self.port = self.server_sock.getsockname()
        self.server_sock.listen(1)
        self.running = True
        self.received_commands = []
        self.rejected_commands = []
        self.active_conn = None
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

            self.active_conn = conn
            with conn:
                conn.settimeout(1.0)
                buffer = ""
                while self.running:
                    try:
                        chunk = conn.recv(1024).decode("utf-8")
                        if not chunk:
                            break
                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            self._handle_request(conn, line)
                    except (socket.timeout, OSError):
                        break
            self.active_conn = None

    def _handle_request(self, conn: socket.socket, raw_line: str):
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            conn.sendall(b'{"Response":"Error","Success":false,"Error":"InvalidJSON"}\n')
            return

        # 1. Strict validation of top-level keys
        if "Command" not in payload or "Data" not in payload:
            self.rejected_commands.append(payload)
            conn.sendall(b'{"Response":"Error","Success":false,"Error":"MissingCommandOrDataKey"}\n')
            return

        cmd = payload["Command"]
        data = payload["Data"]

        # 2. Strict rejection of unknown / snake_case commands
        if cmd not in OFFICIAL_COMMAND_SCHEMA:
            self.rejected_commands.append(payload)
            conn.sendall((json.dumps({"Response": cmd, "Success": False, "Error": f"UnknownCommand:{cmd}"}) + "\n").encode())
            return

        # 3. Strict rejection of invalid / snake_case data keys
        expected_keys = OFFICIAL_COMMAND_SCHEMA[cmd]
        for key in expected_keys:
            if key not in data:
                self.rejected_commands.append(payload)
                conn.sendall((json.dumps({"Response": cmd, "Success": False, "Error": f"MissingParam:{key}"}) + "\n").encode())
                return

        # Check for forbidden snake_case keys
        for key in data.keys():
            if "_" in key or key.islower():
                self.rejected_commands.append(payload)
                conn.sendall((json.dumps({"Response": cmd, "Success": False, "Error": f"IllegalSnakeCaseKey:{key}"}) + "\n").encode())
                return

        self.received_commands.append(payload)

        # 4. Inject an asynchronous event right before response to test stream multiplexing
        async_event = {
            "Event": "UpdateState",
            "Data": {"GameClock": 298.5, "TimeSeconds": data.get("TimeSeconds", 12.0), "Paused": False}
        }
        conn.sendall((json.dumps(async_event) + "\n").encode())

        # 5. Send command response conforming to official protocol
        response = {
            "Response": cmd,
            "Success": True,
            "Data": {"Echo": cmd, "Result": "Accepted"}
        }
        conn.sendall((json.dumps(response) + "\n").encode())

    def close(self):
        self.running = False
        try:
            self.server_sock.close()
        except Exception:
            pass
        self.thread.join(timeout=1.0)


def test_offline_companion_reports_unverified_and_instructions():
    """Verify companion discloses offline status, unverified state, and setup guide."""
    companion = RocketLeagueCompanion(host="127.0.0.1", port=59998, connect_timeout=0.1)
    status = companion.get_status()

    assert status["connected"] is False
    assert status["status"] == "offline"
    assert status["real_game_verified"] is False
    assert status["live_replay_verified"] is False
    assert "TAStatsAPI.ini" in status["instructions"]
    assert "-statsapi" in status["instructions"]
    assert "Real-game integration is NOT verified" in status["instructions"]

    with pytest.raises(CompanionConnectionError):
        companion.send_command("SeekReplay", {"TimeSeconds": 10.0})


def test_strict_official_protocol_and_async_multiplexing():
    """Verify client sends exact PascalCase commands and safely handles async events."""
    server = StrictOfficialRocketLeagueServer()
    received_events = []

    try:
        companion = RocketLeagueCompanion(
            host=server.host,
            port=server.port,
            connect_timeout=1.0,
            command_timeout=2.0,
        )
        companion.register_event_listener(lambda ev: received_events.append(ev))

        # 1. Connect and verify GetStatus
        status = companion.get_status()
        assert status["connected"] is True
        assert status["status"] == "online"

        # 2. Test official Replay Controls
        load_res = companion.load_replay("23A661D44DBC5964B0718DBC5F956A33.replay")
        assert load_res["Response"] == "LoadReplay"
        assert load_res["Success"] is True

        seek_res = companion.seek_replay(45.67)
        assert seek_res["Response"] == "SeekReplay"
        assert seek_res["Success"] is True

        pov_res = companion.change_pov("Plormby")
        assert pov_res["Response"] == "ChangePOV"
        assert pov_res["Success"] is True

        speed_res = companion.set_game_speed(0.5)
        assert speed_res["Response"] == "SetGameSpeed"
        assert speed_res["Success"] is True

        pause_res = companion.set_match_paused(True)
        assert pause_res["Response"] == "SetMatchPaused"
        assert pause_res["Success"] is True

        hud_res = companion.set_hud_visibility(False)
        assert hud_res["Response"] == "SetHUDVisibility"
        assert hud_res["Success"] is True

        # 3. Verify server received strict PascalCase payloads
        assert len(server.rejected_commands) == 0
        assert len(server.received_commands) == 7

        assert server.received_commands[0] == {"Command": "GetStatus", "Data": {}}
        assert server.received_commands[1] == {"Command": "LoadReplay", "Data": {"Replay": "23A661D44DBC5964B0718DBC5F956A33.replay"}}
        assert server.received_commands[2] == {"Command": "SeekReplay", "Data": {"TimeSeconds": 45.67}}
        assert server.received_commands[3] == {"Command": "ChangePOV", "Data": {"Target": "Plormby"}}
        assert server.received_commands[4] == {"Command": "SetGameSpeed", "Data": {"Speed": 0.5}}
        assert server.received_commands[5] == {"Command": "SetMatchPaused", "Data": {"Paused": True}}
        assert server.received_commands[6] == {"Command": "SetHUDVisibility", "Data": {"Visible": False}}

        # 4. Verify async events were multiplexed and received safely by listener
        assert len(received_events) >= 6
        assert all(ev.get("Event") == "UpdateState" for ev in received_events)
        assert companion._latest_state.get("GameClock") == 298.5

        companion.disconnect()
        assert not companion.is_connected()
    finally:
        server.close()


def test_strict_server_rejects_snake_case_and_malformed_commands():
    """Verify mock server rejects any legacy snake_case payloads."""
    server = StrictOfficialRocketLeagueServer()
    try:
        # Connect raw socket to send non-conforming messages
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((server.host, server.port))

        # 1. Send legacy snake_case command: {"action": "seek_replay", "params": {"time_seconds": 10.0}}
        sock.sendall(b'{"action": "seek_replay", "params": {"time_seconds": 10.0}}\n')
        res1 = json.loads(sock.recv(1024).decode())
        assert res1["Success"] is False
        assert "MissingCommandOrDataKey" in res1["Error"]

        # 2. Send snake_case Command name: {"Command": "seek_replay", "Data": {"TimeSeconds": 10.0}}
        sock.sendall(b'{"Command": "seek_replay", "Data": {"TimeSeconds": 10.0}}\n')
        res2 = json.loads(sock.recv(1024).decode())
        assert res2["Success"] is False
        assert "UnknownCommand:seek_replay" in res2["Error"]

        # 3. Send snake_case parameter: {"Command": "SeekReplay", "Data": {"time_seconds": 10.0}}
        sock.sendall(b'{"Command": "SeekReplay", "Data": {"time_seconds": 10.0}}\n')
        res3 = json.loads(sock.recv(1024).decode())
        assert res3["Success"] is False
        assert "MissingParam:TimeSeconds" in res3["Error"]

        assert len(server.rejected_commands) == 3
        sock.close()
    finally:
        server.close()


def test_companion_protocol_error_on_empty_arguments():
    """Verify client rejects missing required arguments before transmitting."""
    companion = RocketLeagueCompanion(host="127.0.0.1", port=59997)
    with pytest.raises(CompanionProtocolError):
        companion.load_replay("")
    with pytest.raises(CompanionProtocolError):
        companion.change_pov("")

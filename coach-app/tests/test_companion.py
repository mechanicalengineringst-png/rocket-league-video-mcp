"""Unit and integration tests for Rocket League Native Game Companion."""

from __future__ import annotations

import json
import socket
import threading
import time
import pytest

from coach_app.companion import (
    RocketLeagueCompanion,
    CompanionConnectionError,
    SETUP_INSTRUCTIONS,
)


def test_offline_companion_graceful_handling():
    """Verify companion handles offline port without crashing or hanging."""
    # Use an unallocated high port
    companion = RocketLeagueCompanion(host="127.0.0.1", port=59999, timeout=0.1)
    assert not companion.is_connected()
    
    status = companion.get_status()
    assert status["connected"] is False
    assert status["status"] == "offline"
    assert "TAStatsAPI" in status["message"]
    assert "TAGame.MatchStatsExporter_TA" in status["instructions"]
    assert companion.get_status()["instructions"] == SETUP_INSTRUCTIONS

    with pytest.raises(CompanionConnectionError) as exc_info:
        companion.send_raw_command("status")
    assert "offline" in str(exc_info.value).lower()


class MockRocketLeagueServer:
    """Mock TCP server emulating TAGame.MatchStatsExporter_TA on TCP."""

    def __init__(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.bind(("127.0.0.1", 0))
        self.host, self.port = self.server_sock.getsockname()
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
                            self.received_commands.append(line)
                            # Generate response
                            try:
                                parsed = json.loads(line)
                                action = parsed.get("action")
                                resp = {"status": "success", "echo_action": action, "time": 12.34}
                            except Exception:
                                resp = {"status": "ok", "raw": line}
                            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
                    except (socket.timeout, OSError):
                        break

    def close(self):
        self.running = False
        try:
            self.server_sock.close()
        except Exception:
            pass
        self.thread.join(timeout=1.0)


def test_companion_controls_with_mock_server():
    """Verify companion command framing and responses against an active server."""
    server = MockRocketLeagueServer()
    try:
        companion = RocketLeagueCompanion(host=server.host, port=server.port, timeout=1.0)
        
        # 1. Connect and verify status
        status = companion.get_status()
        assert status["connected"] is True
        assert status["status"] == "online"
        assert status["game_state"]["status"] == "success"
        assert status["game_state"]["echo_action"] == "status"

        # 2. Replay control commands
        load_res = companion.load_replay("23A661D44DBC5964B0718DBC5F956A33.replay")
        assert load_res["echo_action"] == "load_replay"

        seek_res = companion.seek_replay(45.67)
        assert seek_res["echo_action"] == "seek_replay"

        pov_res = companion.change_pov("Plormby")
        assert pov_res["echo_action"] == "change_pov"

        speed_res = companion.set_game_speed(0.5)
        assert speed_res["echo_action"] == "set_game_speed"

        pause_res = companion.set_match_paused(True)
        assert pause_res["echo_action"] == "set_match_paused"

        hud_res = companion.set_hud_visibility(False)
        assert hud_res["echo_action"] == "set_hud_visibility"

        # 3. Verify received command payloads on server
        assert len(server.received_commands) == 7
        cmds = [json.loads(c) for c in server.received_commands]
        assert cmds[0]["action"] == "status"
        assert cmds[1]["action"] == "load_replay"
        assert cmds[1]["params"]["replay"] == "23A661D44DBC5964B0718DBC5F956A33.replay"
        assert cmds[2]["action"] == "seek_replay"
        assert cmds[2]["params"]["time_seconds"] == 45.67
        assert cmds[3]["action"] == "change_pov"
        assert cmds[3]["params"]["target"] == "Plormby"
        assert cmds[4]["action"] == "set_game_speed"
        assert cmds[4]["params"]["speed"] == 0.5
        assert cmds[5]["action"] == "set_match_paused"
        assert cmds[5]["params"]["paused"] is True
        assert cmds[6]["action"] == "set_hud_visibility"
        assert cmds[6]["params"]["visible"] is False

        # 4. Clean disconnect
        companion.disconnect()
        assert not companion.is_connected()
    finally:
        server.close()

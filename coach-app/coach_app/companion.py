"""Rocket League Native Game Companion Client.

Interfaces with Rocket League's native MatchStatsExporter_TA interface
(configured via TAStatsAPI.ini on TCP port 49123 / WebSocket 49124).
Provides real-time replay synchronization, POV switching, and playback control
when the native game client is running locally.

When the native client is offline, graceful fallbacks and clear setup
instructions are provided.
"""

from __future__ import annotations

import json
import logging
import socket
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 49123
DEFAULT_TIMEOUT = 1.5

SETUP_INSTRUCTIONS = (
    "Rocket League Native Stats & Control API is offline or not configured.\n"
    "To enable native replay synchronization:\n"
    "1. Locate your Rocket League configuration directory (typically:\n"
    "   Documents\\My Games\\Rocket League\\TAGame\\Config\\TAStatsAPI.ini)\n"
    "2. Add or verify the following configuration block:\n"
    "   [TAGame.MatchStatsExporter_TA]\n"
    "   bEnableMatchStatsExporter=True\n"
    "   ServerPort=49123\n"
    "   WebSocketPort=49124\n"
    "3. Start Rocket League and load a replay or match.\n"
    "4. Re-check companion status."
)


class CompanionConnectionError(Exception):
    """Raised when communication with Rocket League native port fails."""


class RocketLeagueCompanion:
    """Client for controlling Rocket League native replay playback via TCP 49123."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None

    def is_connected(self) -> bool:
        """Check if socket connection is alive."""
        if self._sock is None:
            return False
        try:
            # Poll socket with zero timeout to detect closed remote end
            self._sock.setblocking(False)
            data = self._sock.recv(16, socket.MSG_PEEK)
            self._sock.settimeout(self.timeout)
            return True
        except BlockingIOError:
            self._sock.settimeout(self.timeout)
            return True
        except Exception:
            self.disconnect()
            return False

    def connect(self) -> bool:
        """Attempt to connect to the native game client port."""
        if self._sock:
            self.disconnect()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
            self._sock = sock
            return True
        except (ConnectionRefusedError, socket.timeout, OSError) as err:
            logger.debug("Failed to connect to Rocket League companion at %s:%s: %s", self.host, self.port, err)
            self._sock = None
            return False

    def disconnect(self) -> None:
        """Close connection cleanly."""
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            finally:
                self._sock = None

    def send_raw_command(self, command: str) -> str:
        """Send a newline-delimited command and read response."""
        if not self._sock and not self.connect():
            raise CompanionConnectionError(
                f"Cannot connect to Rocket League at {self.host}:{self.port}. Game appears offline."
            )
        assert self._sock is not None
        try:
            payload = (command.strip() + "\n").encode("utf-8")
            self._sock.sendall(payload)
            response_bytes = self._sock.recv(4096)
            if not response_bytes:
                self.disconnect()
                raise CompanionConnectionError("Connection closed by Rocket League host.")
            return response_bytes.decode("utf-8", errors="replace").strip()
        except (socket.timeout, OSError) as err:
            self.disconnect()
            raise CompanionConnectionError(f"Socket error communicating with Rocket League: {err}") from err

    def send_json_command(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a JSON structured command and parse JSON response."""
        msg = {"action": action, "params": params or {}}
        cmd_str = json.dumps(msg)
        raw_res = self.send_raw_command(cmd_str)
        try:
            return json.loads(raw_res)
        except json.JSONDecodeError:
            return {"status": "ok", "raw_response": raw_res}

    # High-level replay control interface
    def load_replay(self, replay_id_or_path: str) -> Dict[str, Any]:
        """Ask Rocket League to load a specific replay."""
        return self.send_json_command("load_replay", {"replay": replay_id_or_path})

    def seek_replay(self, seconds: float) -> Dict[str, Any]:
        """Seek native replay playback to target timestamp in seconds."""
        return self.send_json_command("seek_replay", {"time_seconds": round(max(0.0, float(seconds)), 2)})

    def change_pov(self, target_player_or_mode: str) -> Dict[str, Any]:
        """Change camera POV to specific player name/id or camera mode."""
        return self.send_json_command("change_pov", {"target": target_player_or_mode})

    def set_game_speed(self, multiplier: float) -> Dict[str, Any]:
        """Set replay playback speed multiplier (e.g. 0.25, 0.5, 1.0, 2.0)."""
        clamped = max(0.1, min(5.0, float(multiplier)))
        return self.send_json_command("set_game_speed", {"speed": clamped})

    def set_match_paused(self, paused: bool) -> Dict[str, Any]:
        """Pause or unpause native playback."""
        return self.send_json_command("set_match_paused", {"paused": bool(paused)})

    def set_hud_visibility(self, visible: bool) -> Dict[str, Any]:
        """Toggle native game HUD visibility for clean capture."""
        return self.send_json_command("set_hud_visibility", {"visible": bool(visible)})

    def get_status(self) -> Dict[str, Any]:
        """Query connection and game status."""
        connected = self.connect()
        if not connected:
            return {
                "connected": False,
                "status": "offline",
                "host": self.host,
                "port": self.port,
                "message": "Rocket League native game client is offline or TAStatsAPI is disabled.",
                "instructions": SETUP_INSTRUCTIONS,
            }
        try:
            res = self.send_json_command("status")
            return {
                "connected": True,
                "status": "online",
                "host": self.host,
                "port": self.port,
                "game_state": res,
            }
        except Exception as err:
            return {
                "connected": False,
                "status": "error",
                "host": self.host,
                "port": self.port,
                "error": str(err),
                "instructions": SETUP_INSTRUCTIONS,
            }

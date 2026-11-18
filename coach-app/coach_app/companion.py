"""Rocket League Native Game Companion Client & Prototype Bridge.

Official developer API reference:
https://www.rocketleague.com/developer/stats-api

Connection Architecture:
- Implemented command transport: loopback TCP on port 49123.
- WebSocket port 49124 is *probe-only*, until a real WebSocket handshake
  and framed-client implementation has been tested against Rocket League.
- Protocol Wire Format for TCP: newline-delimited UTF-8 JSON.
- Command Schema:
  {
      "Command": "<CommandName>",
      "Data": { ... }
  }
- Official commands are validated against the public API:
  - LoadReplay: FileName or Path
  - SeekReplay: TimeSeconds or Frame
  - ChangePOV: Focus ("Ball" or numeric spectator shortcut) and/or Perspective
  - SetGameSpeed: Speed
  - SetMatchPaused: bPaused
  - SetHUDVisibility: bVisible

Safety & Sandbox Boundaries:
- Read-only probing and socket transport only.
- Does NOT alter game files, registry, firewall, or running processes.
- Does NOT claim to deliver video frames (requires external window capture).
"""

from __future__ import annotations

import collections
import json
import logging
import math
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 49123
DEFAULT_WS_PORT = 49124
DEFAULT_PROBE_TIMEOUT = 0.5
DEFAULT_COMMAND_TIMEOUT = 2.0

SETUP_INSTRUCTIONS = (
    "The local Rocket League Stats API is not confirmed available.\n"
    "To enable it manually, before starting the game:\n"
    "1. In Rocket League's installation directory, open "
    "TAGame\\Config\\TAStatsAPI.ini "
    "(or DefaultStatsAPI.ini if the first file doesn't exist).\n"
    "2. Under [TAGame.MatchStatsExporter_TA], configure:\n"
    "   PacketSendRate=30\n"
    "   Port=49123\n"
    "   WebPort=49124\n"
    "3. Restart Rocket League, then use the local status probe again.\n"
    "Changes to the INI while the game is running require restart. "
    "Replay Lab never modifies your game configuration automatically.\n"
    "An open port alone does not prove the listening process is Rocket League."
)


class CompanionConnectionError(Exception):
    """Raised when communication with Rocket League native port fails."""


class CompanionProtocolError(ValueError):
    """Raised when an invalid command or parameter structure is supplied."""


_POV_PERSPECTIVES = frozenset({
    "Fly", "SoftAttach", "HardAttach", "PlayerView",
    "AutoCam", "Camera_Director",
})
_COMMAND_FIELDS = {
    "LoadReplay": frozenset({"FileName", "Path"}),
    "SeekReplay": frozenset({"Frame", "TimeSeconds"}),
    "ChangePOV": frozenset({"Focus", "Perspective"}),
    "SetGameSpeed": frozenset({"Speed"}),
    "SetHUDVisibility": frozenset({"bVisible"}),
    "SetMatchPaused": frozenset({"bPaused"}),
}


def validate_native_command(command: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Fail closed against undocumented native-game commands and fields.

    Follow the published Psyonix Stats API, not a mock server's permissive
    acceptance of arbitrary JSON. Return a copy to avoid caller mutation.
    """
    if command not in _COMMAND_FIELDS:
        raise CompanionProtocolError("Unsupported native replay command.")
    if not isinstance(data, dict) or not data or not set(data).issubset(_COMMAND_FIELDS[command]):
        raise CompanionProtocolError("Unknown or missing native command fields.")
    if command in ("LoadReplay", "SeekReplay"):
        if len(data) != 1:
            raise CompanionProtocolError("Supply exactly one replay selector.")
    if command == "LoadReplay":
        value = next(iter(data.values()))
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise CompanionProtocolError("Replay file name or path must be a bounded string.")
    if command == "SeekReplay":
        if "Frame" in data:
            if type(data["Frame"]) is not int or data["Frame"] < 0:
                raise CompanionProtocolError("Replay frame must be a nonnegative integer.")
        else:
            value = data["TimeSeconds"]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise CompanionProtocolError("Replay time must be finite and nonnegative.")
    if command == "ChangePOV":
        focus = data.get("Focus")
        if focus is not None and not (
            isinstance(focus, str) and
            (focus == "Ball" or (focus.isascii() and focus.isdigit()))
        ):
            raise CompanionProtocolError(
                "Focus must be 'Ball' or a numeric spectator shortcut string."
            )
        perspective = data.get("Perspective")
        if perspective is not None and perspective not in _POV_PERSPECTIVES:
            raise CompanionProtocolError("Unknown spectator Perspective.")
        if focus is None and perspective is None:
            raise CompanionProtocolError("ChangePOV needs Focus or Perspective.")
    if command == "SetGameSpeed":
        speed = data.get("Speed")
        if type(speed) not in (float, int) or not math.isfinite(speed) or not 0 <= speed <= 8:
            raise CompanionProtocolError("Replay speed must be finite and between 0 and 8.")
    if command in ("SetHUDVisibility", "SetMatchPaused"):
        key = "bVisible" if command == "SetHUDVisibility" else "bPaused"
        if type(data.get(key)) is not bool:
            raise CompanionProtocolError(f"{key} must be a boolean.")
    return dict(data)


@dataclass
class CompanionStatus:
    available: bool
    connected: bool
    transport: str  # "none", "tcp", "websocket"
    host: str
    port: int
    game_state: Dict[str, Any] = field(default_factory=dict)
    reported_playback_time: Optional[float] = None
    drift_seconds: Optional[float] = None
    recent_events_count: int = 0
    instructions: str = ""


class RocketLeagueCompanion:
    """Safe, testable client for controlling Rocket League native replay playback."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        tcp_port: int = DEFAULT_TCP_PORT,
        ws_port: int = DEFAULT_WS_PORT,
        probe_timeout: float = DEFAULT_PROBE_TIMEOUT,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
    ):
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise CompanionProtocolError("Native companion must stay on local loopback.")
        self.host = host
        self.tcp_port = tcp_port
        self.ws_port = ws_port
        self.probe_timeout = probe_timeout
        self.command_timeout = command_timeout

        self._sock: Optional[socket.socket] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
        self._send_lock = threading.Lock()
        self._active_port = tcp_port

        # State management
        self._latest_state: Dict[str, Any] = {}
        self._event_history: collections.deque = collections.deque(maxlen=200)
        self._pending_responses: Dict[str, threading.Event] = {}
        self._response_payloads: Dict[str, Dict[str, Any]] = {}
        self._event_callbacks: List[Callable[[Dict[str, Any]], None]] = []

    def probe_port(self, port: int) -> bool:
        """Non-blocking TCP socket check without altering system configuration."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(self.probe_timeout)
                res = s.connect_ex((self.host, port))
                return res == 0
        except Exception:
            return False

    def detect_api_availability(self) -> Dict[str, Any]:
        """Detect whether the native Rocket League API is listening on TCP or WebSocket ports."""
        tcp_open = self.probe_port(self.tcp_port)
        ws_open = self.probe_port(self.ws_port)

        available = tcp_open or ws_open
        recommended_port = self.tcp_port if tcp_open else (self.ws_port if ws_open else self.tcp_port)

        return {
            "available": available,
            "tcp_port_49123_open": tcp_open,
            "websocket_port_49124_open": ws_open,
            "recommended_port": recommended_port,
            "host": self.host,
            "message": "Port listening; Rocket League not authenticated" if available else "API offline",
            "instructions": "" if available else SETUP_INSTRUCTIONS,
        }

    def is_connected(self) -> bool:
        return self._sock is not None and self._running

    def connect(self, port: Optional[int] = None) -> bool:
        """Connect to the native Rocket League interface safely."""
        if self.is_connected():
            return True

        self.disconnect()
        target_port = port or self.tcp_port
        # A TCP connection to WebPort is not a WebSocket session. Do not claim
        # that TCP JSON commands on 49124 are a working WebSocket transport.
        if target_port == self.ws_port and self.ws_port != self.tcp_port:
            logger.info("WebSocket command transport is not implemented.")
            return False
        if target_port != self.tcp_port:
            raise CompanionProtocolError("Unsupported native companion port.")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.probe_timeout)
            sock.connect((self.host, target_port))
            sock.settimeout(0.5)
            self._sock = sock
            self._active_port = target_port
            self._running = True

            self._reader_thread = threading.Thread(
                target=self._socket_reader_loop,
                daemon=True,
                name="RocketLeagueCompanionReader",
            )
            self._reader_thread.start()
            logger.info("Connected to Rocket League native API on %s:%s", self.host, target_port)
            return True
        except (OSError, socket.error) as err:
            logger.debug("Could not connect to Rocket League on %s:%s: %s", self.host, target_port, err)
            self.disconnect()
            return False

    def disconnect(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

        if self._reader_thread and self._reader_thread.is_alive():
            if threading.current_thread() != self._reader_thread:
                self._reader_thread.join(timeout=0.5)
        self._reader_thread = None

    def _socket_reader_loop(self) -> None:
        """Background thread multiplexing inbound responses and async events."""
        buffer = ""
        while self._running and self._sock:
            try:
                chunk = self._sock.recv(4096).decode("utf-8", errors="replace")
                if not chunk:
                    break
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        self._process_inbound_line(line)
            except socket.timeout:
                continue
            except OSError:
                break
        self._running = False

    def _process_inbound_line(self, line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return

        self._event_history.append(payload)

        # Handle explicit command response
        if "Response" in payload:
            cmd = payload["Response"]
            if cmd in self._pending_responses:
                self._response_payloads[cmd] = payload
                self._pending_responses[cmd].set()

        # Handle asynchronous match/state updates
        if payload.get("Event") in ("UpdateState", "GameState", "PlaybackState"):
            data = payload.get("Data", {})
            self._latest_state.update(data)

        # Dispatch registered listener callbacks
        for cb in list(self._event_callbacks):
            try:
                cb(payload)
            except Exception as e:
                logger.warning("Event callback error: %s", e)

    def send_command(
        self,
        command: str,
        data: Optional[Dict[str, Any]] = None,
        wait_response: bool = False,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Send strict PascalCase command conforming to official stats API schema."""
        data = validate_native_command(command, data if data is not None else {})
        if not self.is_connected():
            connected = self.connect()
            if not connected:
                raise CompanionConnectionError(
                    f"Rocket League native API is not connected on {self.host}:{self._active_port}."
                )

        cmd_timeout = timeout or self.command_timeout
        payload = {
            "Command": command,
            "Data": data or {},
        }
        wire_bytes = (json.dumps(payload) + "\n").encode("utf-8")

        response_event: Optional[threading.Event] = None
        if wait_response:
            response_event = threading.Event()
            self._pending_responses[command] = response_event
            self._response_payloads.pop(command, None)

        try:
            with self._send_lock:
                self._sock.sendall(wire_bytes)
        except OSError as err:
            self.disconnect()
            raise CompanionConnectionError(f"Failed to transmit to Rocket League: {err}") from err

        if not wait_response or not response_event:
            return {"Command": command, "Status": "Sent", "Data": data or {}}

        finished = response_event.wait(timeout=cmd_timeout)
        self._pending_responses.pop(command, None)

        if not finished:
            return {
                "Command": command,
                "Status": "AwaitingStateUpdate",
                "TimeoutSeconds": cmd_timeout,
                "LatestState": self._latest_state,
            }

        return self._response_payloads.get(command, {"Command": command, "Status": "Success"})

    # --- Official Documented Commands ---

    def load_replay(self, replay_id_or_path: str) -> Dict[str, Any]:
        """Load by FileName (saved game history) or Path (absolute/local path)."""
        if not isinstance(replay_id_or_path, str) or not replay_id_or_path.strip():
            raise CompanionProtocolError("Replay identifier or path is required.")
        name = replay_id_or_path.strip()
        field = "Path" if "/" in name or "\\" in name else "FileName"
        return self.send_command("LoadReplay", {field: name})

    def seek_replay(self, seconds: float) -> Dict[str, Any]:
        """Seek replay to specified timestamp: {"Command": "SeekReplay", "Data": {"TimeSeconds": ...}}"""
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise CompanionProtocolError("Replay time must be finite and nonnegative.")
        return self.send_command("SeekReplay", {"TimeSeconds": round(seconds, 3)})

    def change_pov(self, focus: Optional[str] = None,
                   perspective: Optional[str] = None) -> Dict[str, Any]:
        """Switch by numeric spectator shortcut or ball; optionally select camera."""
        data: Dict[str, Any] = {}
        if focus is not None:
            data["Focus"] = focus
        if perspective is not None:
            data["Perspective"] = perspective
        return self.send_command("ChangePOV", data)

    def set_game_speed(self, multiplier: float) -> Dict[str, Any]:
        """Change playback rate: {"Command": "SetGameSpeed", "Data": {"Speed": ...}}"""
        return self.send_command("SetGameSpeed", {"Speed": multiplier})

    def set_match_paused(self, paused: bool) -> Dict[str, Any]:
        """Pause or unpause replay: {"Command": "SetMatchPaused", "Data": {"Paused": ...}}"""
        return self.send_command("SetMatchPaused", {"bPaused": paused})

    def set_hud_visibility(self, visible: bool) -> Dict[str, Any]:
        """Toggle native HUD visibility: {"Command": "SetHUDVisibility", "Data": {"Visible": ...}}"""
        return self.send_command("SetHUDVisibility", {"bVisible": visible})

    def observe_playback_state(self) -> Dict[str, Any]:
        """Retrieve current observed game state and clock."""
        game = self._latest_state.get("Game", {})
        game = game if isinstance(game, dict) else {}
        elapsed = game.get("Elapsed") if game.get("bReplay") else None
        return {
            "connected": self.is_connected(),
            "latest_state": self._latest_state,
            "reported_time_seconds": elapsed,
            "is_paused": None,
            "game_speed": None,
        }

    def measure_drift(self, expected_time_s: float) -> Optional[float]:
        """Calculate time drift between expected client time and game reported playback time."""
        state = self.observe_playback_state()
        reported = state.get("reported_time_seconds")
        if reported is None:
            return None
        return round(float(reported) - float(expected_time_s), 4)

    def get_status(self) -> CompanionStatus:
        """Port probe only: never open a persistent command socket on GET.

        A listening port may belong to another program; success is not a
        Rocket League handshake, and WebPort availability isn't WS support.
        """
        probe = self.detect_api_availability()
        return CompanionStatus(
            available=probe["available"],
            connected=False,
            transport="none",
            host=self.host,
            port=probe["recommended_port"],
            instructions=(
                "Port(s) listening, but no authenticated Rocket League command "
                "session has been established. TCP 49123 is the implemented "
                "command transport; WebSocket 49124 is probe-only."
                if probe["available"] else SETUP_INSTRUCTIONS
            ),
        )

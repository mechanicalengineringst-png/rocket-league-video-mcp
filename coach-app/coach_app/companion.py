"""Rocket League Native Game Companion Client & Prototype Bridge.

Official developer API reference:
https://www.rocketleague.com/developer/stats-api

Connection Architecture:
- Primary WebSocket Interface: ws://127.0.0.1:49124
- Secondary Raw TCP Interface: 127.0.0.1:49123
- Protocol Wire Format: UTF-8 JSON.
- Command Schema:
  {
      "Command": "<CommandName>",
      "Data": { ... }
  }
- Official PascalCase commands & schemas:
  - "LoadReplay": {"Replay": "<str>"}
  - "SeekReplay": {"TimeSeconds": <float>}
  - "ChangePOV": {"Focus": "<str>", "Target": "<Optional[str]>"}
    (Focus specifies player identifier or perspective: "Player", "Ball", "Fly")
  - "SetGameSpeed": {"Speed": <float>}
  - "SetMatchPaused": {"Paused": <bool>}
  - "SetHUDVisibility": {"Visible": <bool>}
  - "GetStatus": {}

Safety & Sandbox Boundaries:
- Read-only probing and socket transport only.
- Does NOT alter game files, registry, firewall, or running processes.
- Does NOT claim to deliver video frames (requires external window capture).
"""

from __future__ import annotations

import collections
import json
import logging
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
    "Rocket League Native Stats API is offline or not enabled.\n"
    "To configure and enable native replay synchronization manually:\n"
    "1. Locate your Rocket League configuration folder:\n"
    "   %USERPROFILE%\\Documents\\My Games\\Rocket League\\TAGame\\Config\\TAStatsAPI.ini\n"
    "2. Add or verify the following configuration section:\n"
    "   [TAGame.MatchStatsExporter_TA]\n"
    "   bEnableMatchStatsExporter=True\n"
    "   ServerPort=49123\n"
    "   WebSocketPort=49124\n"
    "   RecordAllEvents=True\n"
    "3. Add the launch argument in Steam or Epic Games Store:\n"
    "   -statsapi\n"
    "4. Launch Rocket League, load a match or replay, and re-check companion status.\n"
    "Note: Replay Lab does not modify your game configuration or install software automatically."
)


class CompanionConnectionError(Exception):
    """Raised when communication with Rocket League native port fails."""


class CompanionProtocolError(ValueError):
    """Raised when an invalid command or parameter structure is supplied."""


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
        recommended_port = self.ws_port if ws_open else (self.tcp_port if tcp_open else self.ws_port)

        return {
            "available": available,
            "tcp_port_49123_open": tcp_open,
            "websocket_port_49124_open": ws_open,
            "recommended_port": recommended_port,
            "host": self.host,
            "message": "API online" if available else "API offline",
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
        """Ask Rocket League to load a saved replay: {"Command": "LoadReplay", "Data": {"Replay": ...}}"""
        if not replay_id_or_path:
            raise CompanionProtocolError("Replay identifier or path is required.")
        return self.send_command("LoadReplay", {"Replay": str(replay_id_or_path)})

    def seek_replay(self, seconds: float) -> Dict[str, Any]:
        """Seek replay to specified timestamp: {"Command": "SeekReplay", "Data": {"TimeSeconds": ...}}"""
        t = round(max(0.0, float(seconds)), 3)
        return self.send_command("SeekReplay", {"TimeSeconds": t})

    def change_pov(self, focus: str, target: Optional[str] = None) -> Dict[str, Any]:
        """Switch spectator POV using official Focus schema: {"Command": "ChangePOV", "Data": {"Focus": ...}}"""
        if not focus:
            raise CompanionProtocolError("Focus identifier or perspective is required (e.g. player id, 'Ball', 'Fly').")
        data: Dict[str, Any] = {"Focus": str(focus)}
        if target:
            data["Target"] = str(target)
        return self.send_command("ChangePOV", data)

    def set_game_speed(self, multiplier: float) -> Dict[str, Any]:
        """Change playback rate: {"Command": "SetGameSpeed", "Data": {"Speed": ...}}"""
        speed = max(0.1, min(5.0, float(multiplier)))
        return self.send_command("SetGameSpeed", {"Speed": speed})

    def set_match_paused(self, paused: bool) -> Dict[str, Any]:
        """Pause or unpause replay: {"Command": "SetMatchPaused", "Data": {"Paused": ...}}"""
        return self.send_command("SetMatchPaused", {"Paused": bool(paused)})

    def set_hud_visibility(self, visible: bool) -> Dict[str, Any]:
        """Toggle native HUD visibility: {"Command": "SetHUDVisibility", "Data": {"Visible": ...}}"""
        return self.send_command("SetHUDVisibility", {"Visible": bool(visible)})

    def observe_playback_state(self) -> Dict[str, Any]:
        """Retrieve current observed game state and clock."""
        return {
            "connected": self.is_connected(),
            "latest_state": self._latest_state,
            "reported_time_seconds": self._latest_state.get("TimeSeconds") or self._latest_state.get("CurrentTime"),
            "is_paused": self._latest_state.get("IsPaused", False),
            "game_speed": self._latest_state.get("GameSpeed", 1.0),
        }

    def measure_drift(self, expected_time_s: float) -> Optional[float]:
        """Calculate time drift between expected client time and game reported playback time."""
        state = self.observe_playback_state()
        reported = state.get("reported_time_seconds")
        if reported is None:
            return None
        return round(float(reported) - float(expected_time_s), 4)

    def get_status(self) -> CompanionStatus:
        """Report connection state, API availability, and drift without mutating configuration."""
        probe = self.detect_api_availability()
        connected = self.is_connected()
        if not connected and probe["available"]:
            connected = self.connect(probe["recommended_port"])

        playback = self.observe_playback_state() if connected else {}
        return CompanionStatus(
            available=probe["available"],
            connected=connected,
            transport="tcp" if connected and self._active_port == self.tcp_port else (
                "websocket" if connected else "none"
            ),
            host=self.host,
            port=self._active_port if connected else probe["recommended_port"],
            game_state=self._latest_state,
            reported_playback_time=playback.get("reported_time_seconds"),
            recent_events_count=len(self._event_history),
            instructions="" if probe["available"] else SETUP_INSTRUCTIONS,
        )

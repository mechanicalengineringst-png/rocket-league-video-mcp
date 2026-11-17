"""Rocket League Native Game Companion Client.

Interfaces with Rocket League's official MatchStatsExporter_TA interface
(configured via TAStatsAPI.ini on TCP port 49123 / WebSocket 49124).
Provides real-time replay synchronization, POV switching, and playback control.

Official Protocol Specification:
- Wire format: Newline-delimited UTF-8 JSON.
- Outbound command schema:
    {
        "Command": "<CommandName>",
        "Data": { ... }
    }
  Commands and Data field keys use strict PascalCase:
    - "SeekReplay" with Data: {"TimeSeconds": <float>}
    - "LoadReplay" with Data: {"Replay": <str>}
    - "ChangePOV" with Data: {"Target": <str>}
    - "SetGameSpeed" with Data: {"Speed": <float>}
    - "SetMatchPaused" with Data: {"Paused": <bool>}
    - "SetHUDVisibility" with Data: {"Visible": <bool>}
    - "GetStatus" with Data: {}

- Inbound messages:
  The native game client asynchronously streams event messages over the connection:
    - Events: {"Event": "<EventName>", "Data": { ... }}
    - Responses: {"Response": "<CommandName>", "Success": <bool>, "Data": { ... }}
    - State updates: {"Event": "UpdateState", "Data": { ... }}

Because the server emits asynchronous event notifications, commands cannot safely
rely on a single immediate blocking socket read. This client runs a background
reader loop to multiplex incoming asynchronous events, state broadcasts, and command
responses safely without desynchronizing the transport.
"""

from __future__ import annotations

import collections
import json
import logging
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 49123
DEFAULT_CONNECT_TIMEOUT = 1.5
DEFAULT_COMMAND_TIMEOUT = 2.0

SETUP_INSTRUCTIONS = (
    "Rocket League Native Stats & Control API is offline or not enabled.\n"
    "To configure and enable native replay synchronization:\n"
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
    "Note: Real-game integration is NOT verified until an active Rocket League client\n"
    "successfully reports live state on this port."
)


class CompanionConnectionError(Exception):
    """Raised when communication with Rocket League native port fails."""


class CompanionProtocolError(ValueError):
    """Raised when an invalid command or parameter structure is supplied."""


class RocketLeagueCompanion:
    """Client for controlling Rocket League native replay playback via official Stats API."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
    ):
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout

        self._sock: Optional[socket.socket] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
        self._send_lock = threading.Lock()

        # State management
        self._latest_state: Dict[str, Any] = {}
        self._event_history: collections.deque = collections.deque(maxlen=200)
        self._pending_responses: Dict[str, threading.Event] = {}
        self._response_payloads: Dict[str, Dict[str, Any]] = {}
        self._event_callbacks: List[Callable[[Dict[str, Any]], None]] = []

        # Real-game verification tracking
        self._real_game_verified = False
        self._live_replay_verified = False

    def is_connected(self) -> bool:
        """Check if connection and reader thread are active."""
        return self._sock is not None and self._running

    def connect(self) -> bool:
        """Connect to the native Rocket League Stats API port."""
        if self.is_connected():
            return True

        self.disconnect()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.connect_timeout)
            sock.connect((self.host, self.port))
            # Switch socket to non-blocking timeout for the reader thread
            sock.settimeout(0.5)
            self._sock = sock
            self._running = True

            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name="RocketLeagueCompanionReader",
                daemon=True,
            )
            self._reader_thread.start()
            return True
        except (ConnectionRefusedError, socket.timeout, OSError) as err:
            logger.debug("Cannot connect to Rocket League at %s:%s: %s", self.host, self.port, err)
            self.disconnect()
            return False

    def disconnect(self) -> None:
        """Close socket and terminate background reader cleanly."""
        self._running = False
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        if self._reader_thread and self._reader_thread.is_alive():
            if threading.current_thread() != self._reader_thread:
                self._reader_thread.join(timeout=1.0)
            self._reader_thread = None

        # Reset real-game runtime status on disconnect
        self._real_game_verified = False
        self._live_replay_verified = False

    def register_event_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for incoming asynchronous event messages."""
        self._event_callbacks.append(callback)

    def _reader_loop(self) -> None:
        """Continuously read, frame, and dispatch incoming messages from the socket."""
        buffer = ""
        while self._running and self._sock:
            try:
                chunk = self._sock.recv(4096).decode("utf-8", errors="replace")
                if not chunk:
                    # Remote closed connection
                    break
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    self._process_inbound_message(line)
            except socket.timeout:
                continue
            except OSError:
                break

        self._running = False

    def _process_inbound_message(self, raw_line: str) -> None:
        """Parse and route inbound JSON messages."""
        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError:
            logger.warning("Received non-JSON payload from Rocket League: %s", raw_line[:120])
            return

        if not isinstance(msg, dict):
            return

        # Check for asynchronous Event message
        event_name = msg.get("Event")
        if event_name:
            event_data = msg.get("Data", {})
            self._event_history.append(msg)
            if event_name == "UpdateState":
                self._latest_state.update(event_data)
                # Check for authentic real-game state markers
                if event_data.get("GameTime") is not None or event_data.get("Ball") is not None:
                    self._real_game_verified = True
            for cb in self._event_callbacks:
                try:
                    cb(msg)
                except Exception as e:
                    logger.exception("Error in event callback: %s", e)
            return

        # Check for Command Response message
        response_cmd = msg.get("Response")
        if response_cmd:
            self._response_payloads[response_cmd] = msg
            ev = self._pending_responses.get(response_cmd)
            if ev:
                ev.set()
            return

        # Fallback / generic status dictionary
        if "Status" in msg:
            # Wake up any waiting command that does not have a specific Response key
            for cmd_name, ev in list(self._pending_responses.items()):
                self._response_payloads[cmd_name] = msg
                ev.set()
            self._latest_state.update(msg)

    def send_command(
        self,
        command: str,
        data: Optional[Dict[str, Any]] = None,
        wait_response: bool = True,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Send a strict PascalCase command conforming to Rocket League official Stats API.

        Schema:
            {"Command": "<CommandName>", "Data": { ... }}
        """
        if not self.is_connected() and not self.connect():
            raise CompanionConnectionError(
                f"Cannot connect to Rocket League at {self.host}:{self.port}. Game appears offline."
            )

        assert self._sock is not None
        cmd_timeout = timeout or self.command_timeout

        # Build official PascalCase payload
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
            raise CompanionConnectionError(f"Failed to send command to Rocket League: {err}") from err

        if not wait_response or not response_event:
            return {"Command": command, "Status": "Sent"}

        # Wait safely for matching response without blocking socket reads
        finished = response_event.wait(timeout=cmd_timeout)
        self._pending_responses.pop(command, None)

        if not finished:
            # Some versions of the game stream UpdateState rather than explicit command acks
            return {
                "Command": command,
                "Status": "AwaitingStateUpdate",
                "TimeoutSeconds": cmd_timeout,
                "LatestState": self._latest_state,
            }

        return self._response_payloads.get(command, {"Command": command, "Status": "Success"})

    # --- High-Level Replay Controls (Strict Official Schema) ---

    def load_replay(self, replay_id_or_path: str) -> Dict[str, Any]:
        """Ask Rocket League to load a replay: {"Command": "LoadReplay", "Data": {"Replay": ...}}"""
        if not replay_id_or_path:
            raise CompanionProtocolError("Replay identifier or path is required for LoadReplay.")
        return self.send_command("LoadReplay", {"Replay": str(replay_id_or_path)})

    def seek_replay(self, seconds: float) -> Dict[str, Any]:
        """Seek native replay playback: {"Command": "SeekReplay", "Data": {"TimeSeconds": ...}}"""
        t = round(max(0.0, float(seconds)), 2)
        return self.send_command("SeekReplay", {"TimeSeconds": t})

    def change_pov(self, target: str) -> Dict[str, Any]:
        """Change camera POV: {"Command": "ChangePOV", "Data": {"Target": ...}}"""
        if not target:
            raise CompanionProtocolError("Target player name or ID is required for ChangePOV.")
        return self.send_command("ChangePOV", {"Target": str(target)})

    def set_game_speed(self, multiplier: float) -> Dict[str, Any]:
        """Set replay playback speed: {"Command": "SetGameSpeed", "Data": {"Speed": ...}}"""
        clamped = max(0.1, min(5.0, float(multiplier)))
        return self.send_command("SetGameSpeed", {"Speed": clamped})

    def set_match_paused(self, paused: bool) -> Dict[str, Any]:
        """Pause or unpause playback: {"Command": "SetMatchPaused", "Data": {"Paused": ...}}"""
        return self.send_command("SetMatchPaused", {"Paused": bool(paused)})

    def set_hud_visibility(self, visible: bool) -> Dict[str, Any]:
        """Toggle native HUD: {"Command": "SetHUDVisibility", "Data": {"Visible": ...}}"""
        return self.send_command("SetHUDVisibility", {"Visible": bool(visible)})

    def get_status(self) -> Dict[str, Any]:
        """Query connection state and game status.

        Explicitly discloses whether live real-game integration has been verified.
        """
        connected = self.connect()
        if not connected:
            return {
                "connected": False,
                "status": "offline",
                "host": self.host,
                "port": self.port,
                "real_game_verified": False,
                "live_replay_verified": False,
                "message": "Rocket League native game client is offline or TAStatsAPI is not listening.",
                "instructions": SETUP_INSTRUCTIONS,
            }

        try:
            # Query official status
            res = self.send_command("GetStatus", {}, wait_response=True, timeout=1.0)
            return {
                "connected": True,
                "status": "online",
                "host": self.host,
                "port": self.port,
                "real_game_verified": self._real_game_verified,
                "live_replay_verified": self._live_replay_verified,
                "game_state": self._latest_state or res,
                "recent_event_count": len(self._event_history),
            }
        except Exception as err:
            return {
                "connected": False,
                "status": "error",
                "host": self.host,
                "port": self.port,
                "real_game_verified": False,
                "live_replay_verified": False,
                "error": str(err),
                "instructions": SETUP_INSTRUCTIONS,
            }

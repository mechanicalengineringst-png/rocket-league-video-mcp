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

Dual-Clock Architecture:
- Replay Timeline Clock: Game.Elapsed (float seconds). Monotonic elapsed time from
  replay start (0.0s) through full match duration, including goals, kickoffs, and overtimes.
  This aligns with Replay Lab's internal frame timeline.
- Match Countdown Clock: Game.SecondsRemaining or Game.TimeSeconds (regulation 300s down to 0,
  pauses during goals, counts up from 0 in overtime). This is game-clock only and cannot be
  used for replay seek drift.

Safety & Sandbox Boundaries:
- Read-only probing and socket transport only.
- Does NOT alter game files, registry, firewall, or running processes.
- Does NOT claim to deliver video frames (requires external window capture).
- Opt-in command execution: controlled by REPLAY_LAB_ENABLE_NATIVE_COMMANDS env flag.
"""

from __future__ import annotations

import collections
import configparser
import glob
import json
import logging
import math
import os
import pathlib
from pathlib import Path
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 49123
DEFAULT_WS_PORT = 49124
DEFAULT_PROBE_TIMEOUT = 0.5
DEFAULT_COMMAND_TIMEOUT = 2.0

SETUP_INSTRUCTIONS = (
    "The local Rocket League Stats API is not confirmed available.\n"
    "To enable it manually, before starting the game:\n"
    "1. In Rocket League's configuration directory, open "
    "TAGame\\Config\\TAStatsAPI.ini (or DefaultStatsAPI.ini in the install dir).\n"
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


# --- Configuration Discovery and Diagnostics ---

@dataclass
class ConfigurationDiagnostics:
    """Read-only diagnostics of the local Rocket League Stats API INI configuration."""
    status: str  # "CONFIGURED_ENABLED", "CONFIGURED_MUTED", "NOT_FOUND"
    documents_ini_path: Optional[str] = None
    install_ini_path: Optional[str] = None
    documents_packet_send_rate: Optional[int] = None
    install_packet_send_rate: Optional[int] = None
    effective_packet_send_rate: Optional[int] = None
    tcp_port: int = DEFAULT_TCP_PORT
    web_port: int = DEFAULT_WS_PORT
    instructions: str = ""
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "documents_ini_path": self.documents_ini_path,
            "install_ini_path": self.install_ini_path,
            "documents_packet_send_rate": self.documents_packet_send_rate,
            "install_packet_send_rate": self.install_packet_send_rate,
            "effective_packet_send_rate": self.effective_packet_send_rate,
            "tcp_port": self.tcp_port,
            "web_port": self.web_port,
            "instructions": self.instructions,
            "notes": list(self.notes),
        }


def find_rocket_league_documents_dir(override: Optional[str] = None) -> Optional[Path]:
    """Locate Rocket League's user documents folder containing TAStatsAPI.ini.
    
    Resolves Windows Known Folder CSIDL_PERSONAL / FOLDERID_Documents first,
    accounting for user profile drive relocations (e.g. D:\\Users\\...\\Documents).
    """
    if override:
        p = Path(override)
        if (p / "TAGame" / "Config" / "TAStatsAPI.ini").is_file():
            return p
        if (p / "TAStatsAPI.ini").is_file():
            return p.parent.parent.parent if p.name == "TAStatsAPI.ini" else p
        return p if p.is_dir() else None

    env_override = os.getenv("ROCKET_LEAGUE_DOCUMENTS_DIR")
    if env_override:
        p = Path(env_override)
        if p.exists():
            return p

    candidates: List[Path] = []

    # Windows Known Folder CSIDL_PERSONAL (5)
    if sys.platform == "win32":
        try:
            import ctypes.wintypes
            CSIDL_PERSONAL = 5
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, 0, buf)
            if buf.value:
                candidates.append(Path(buf.value) / "My Games" / "Rocket League")
        except Exception:
            pass

    # Standard user profile fallbacks
    candidates.append(Path.home() / "Documents" / "My Games" / "Rocket League")
    userprofile = os.getenv("USERPROFILE")
    if userprofile:
        candidates.append(Path(userprofile) / "Documents" / "My Games" / "Rocket League")

    for cand in candidates:
        if (cand / "TAGame" / "Config" / "TAStatsAPI.ini").is_file():
            return cand
        if cand.is_dir():
            return cand

    return None


def find_rocket_league_install_dir(override: Optional[str] = None) -> Optional[Path]:
    """Locate Rocket League's game installation folder containing DefaultStatsAPI.ini.
    
    Checks Epic Games Launcher manifests, Steam default paths, and common directories.
    """
    if override:
        p = Path(override)
        if (p / "TAGame" / "Config" / "DefaultStatsAPI.ini").is_file():
            return p
        if (p / "DefaultStatsAPI.ini").is_file():
            return p.parent.parent.parent if p.name == "DefaultStatsAPI.ini" else p
        return p if p.is_dir() else None

    env_override = os.getenv("ROCKET_LEAGUE_INSTALL_PATH")
    if env_override:
        p = Path(env_override)
        if p.exists():
            return p

    # 1. Epic Games Launcher Manifests
    if sys.platform == "win32":
        manifest_pattern = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests\*.item"
        for mf in glob.glob(manifest_pattern):
            try:
                with open(mf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    app_name = str(data.get("AppName", "")).lower()
                    loc = str(data.get("InstallLocation", ""))
                    if ("sugar" in app_name or "rocketleague" in app_name or "rocketleague" in loc.lower()) and loc:
                        p = Path(loc)
                        if (p / "TAGame" / "Config" / "DefaultStatsAPI.ini").is_file():
                            return p
            except Exception:
                pass

    # 2. Common install locations
    common_roots = [
        r"C:\Program Files\Epic Games\rocketleague",
        r"C:\Program Files (x86)\Steam\steamapps\common\rocketleague",
        r"D:\SteamLibrary\steamapps\common\rocketleague",
        r"D:\Epic Games\rocketleague",
    ]
    for root in common_roots:
        p = Path(root)
        if (p / "TAGame" / "Config" / "DefaultStatsAPI.ini").is_file():
            return p

    return None


def _parse_stats_ini(ini_path: Path) -> Optional[Dict[str, int]]:
    """Safely parse [TAGame.MatchStatsExporter_TA] from an INI file."""
    if not ini_path.is_file():
        return None
    cp = configparser.ConfigParser(strict=False)
    try:
        with open(ini_path, "r", encoding="utf-8", errors="replace") as f:
            cp.read_file(f)
        sec = "TAGame.MatchStatsExporter_TA"
        if sec in cp:
            return {
                "Port": cp[sec].getint("Port", DEFAULT_TCP_PORT),
                "WebPort": cp[sec].getint("WebPort", DEFAULT_WS_PORT),
                "PacketSendRate": cp[sec].getint("PacketSendRate", 0),
            }
    except Exception as err:
        logger.debug("Failed parsing %s: %s", ini_path, err)
    return None


def diagnose_configuration(
    custom_documents_dir: Optional[str] = None,
    custom_install_dir: Optional[str] = None,
) -> ConfigurationDiagnostics:
    """Perform safe, read-only inspection of installed Rocket League Stats API configuration.
    
    Explains the Unreal Engine 3 configuration layer:
    - DefaultStatsAPI.ini in game install folder sets base engine defaults.
    - TAStatsAPI.ini in user Documents folder overrides defaults at game launch.
    - Setting PacketSendRate=0 mutes telemetry packets (dormant).
    - Setting PacketSendRate=30 in TAStatsAPI.ini enables telemetry without admin rights.
    """
    notes: List[str] = []
    doc_dir = find_rocket_league_documents_dir(custom_documents_dir)
    install_dir = find_rocket_league_install_dir(custom_install_dir)

    doc_ini: Optional[Path] = None
    if doc_dir:
        candidate = doc_dir / "TAGame" / "Config" / "TAStatsAPI.ini"
        if candidate.is_file():
            doc_ini = candidate
        elif (doc_dir / "TAStatsAPI.ini").is_file():
            doc_ini = doc_dir / "TAStatsAPI.ini"

    install_ini: Optional[Path] = None
    if install_dir:
        candidate = install_dir / "TAGame" / "Config" / "DefaultStatsAPI.ini"
        if candidate.is_file():
            install_ini = candidate
        elif (install_dir / "DefaultStatsAPI.ini").is_file():
            install_ini = install_dir / "DefaultStatsAPI.ini"

    doc_parsed = _parse_stats_ini(doc_ini) if doc_ini else None
    install_parsed = _parse_stats_ini(install_ini) if install_ini else None

    doc_rate = doc_parsed["PacketSendRate"] if doc_parsed else None
    install_rate = install_parsed["PacketSendRate"] if install_parsed else None

    # UE3 precedence: user documents overlay overrides install default
    effective_rate = doc_rate if doc_rate is not None else install_rate

    tcp_port = DEFAULT_TCP_PORT
    web_port = DEFAULT_WS_PORT
    if doc_parsed:
        tcp_port = doc_parsed.get("Port", DEFAULT_TCP_PORT)
        web_port = doc_parsed.get("WebPort", DEFAULT_WS_PORT)
    elif install_parsed:
        tcp_port = install_parsed.get("Port", DEFAULT_TCP_PORT)
        web_port = install_parsed.get("WebPort", DEFAULT_WS_PORT)

    if doc_ini:
        notes.append(f"User documents INI found at: {doc_ini}")
    if install_ini:
        notes.append(f"Game install INI found at: {install_ini}")

    if effective_rate is not None:
        if effective_rate > 0:
            status = "CONFIGURED_ENABLED"
            instructions = (
                f"Rocket League Stats API is configured with PacketSendRate={effective_rate}. "
                f"Ensure Rocket League is launched to accept connections on port {tcp_port}."
            )
            notes.append("Telemetry transmission is enabled.")
        else:
            status = "CONFIGURED_MUTED"
            target_file = str(doc_ini or install_ini)
            instructions = (
                f"The Rocket League Stats API configuration is present, but PacketSendRate is 0 (muted).\n"
                f"To enable live telemetry and companion control:\n"
                f"1. Open '{target_file}' in a text editor.\n"
                f"2. Under [TAGame.MatchStatsExporter_TA], set PacketSendRate=30\n"
                f"3. Save the file and restart Rocket League."
            )
            notes.append("PacketSendRate is 0; the Stats API exporter thread is muted.")
    else:
        status = "NOT_FOUND"
        instructions = SETUP_INSTRUCTIONS
        notes.append("No Rocket League Stats API configuration files were detected.")

    return ConfigurationDiagnostics(
        status=status,
        documents_ini_path=str(doc_ini) if doc_ini else None,
        install_ini_path=str(install_ini) if install_ini else None,
        documents_packet_send_rate=doc_rate,
        install_packet_send_rate=install_rate,
        effective_packet_send_rate=effective_rate,
        tcp_port=tcp_port,
        web_port=web_port,
        instructions=instructions,
        notes=notes,
    )


# --- Spectator Shortcut Resolution ---

def resolve_spectator_shortcut(
    players: Sequence[Dict[str, Any]],
    target: Union[str, int],
) -> str:
    """Resolve a target player name, ID, or index to an official spectator shortcut ("1"-"8") or "Ball".
    
    Psyonix ChangePOV requires Focus to be "Ball" or a numeric spectator shortcut string ("1"-"8").
    In Rocket League:
    - "1"-"4" correspond to Team 0 (Blue) roster order.
    - "5"-"8" correspond to Team 1 (Orange) roster order.
    - Real Stats API telemetry can supply explicit "SpectatorShortcut".
    
    Raises CompanionProtocolError if target cannot be resolved or is ambiguous.
    """
    if isinstance(target, str) and target.strip().lower() == "ball":
        return "Ball"

    if isinstance(target, int):
        if 1 <= target <= 8:
            return str(target)
        raise CompanionProtocolError(f"Spectator shortcut integer must be between 1 and 8 (got {target}).")

    if not isinstance(target, str) or not target.strip():
        raise CompanionProtocolError("Target player identifier must be a non-empty string.")

    target_clean = target.strip()

    # If already a valid shortcut string "1" through "8"
    if target_clean.isdigit():
        val = int(target_clean)
        if 1 <= val <= 8:
            return str(val)
        raise CompanionProtocolError(f"Spectator shortcut string must be between 1 and 8 (got {target_clean}).")

    target_lower = target_clean.lower()
    matches: List[Dict[str, Any]] = []

    for p in players:
        p_id = str(p.get("Id") or p.get("PrimaryId") or p.get("UniqueId") or p.get("OnlineID") or "").strip().lower()
        p_name = str(p.get("Name") or p.get("name") or "").strip().lower()
        if target_lower in (p_id, p_name):
            matches.append(p)

    if len(matches) > 1:
        raise CompanionProtocolError(f"Ambiguous player '{target_clean}': multiple players match identifier.")

    if not matches:
        raise CompanionProtocolError(f"Player '{target_clean}' not found in player roster.")

    matched = matches[0]

    # If player payload already has an explicit SpectatorShortcut
    if "SpectatorShortcut" in matched:
        sc = str(matched["SpectatorShortcut"]).strip()
        if sc.isdigit() and 1 <= int(sc) <= 8:
            return sc

    # Infer shortcut from team affiliation and roster order
    # Team 0 (Blue) -> 1, 2, 3, 4; Team 1 (Orange) -> 5, 6, 7, 8
    team0 = [p for p in players if p.get("Team", p.get("team", 0)) == 0]
    team1 = [p for p in players if p.get("Team", p.get("team", 0)) == 1]

    if matched in team0:
        idx = team0.index(matched)
        if idx < 4:
            return str(idx + 1)
    elif matched in team1:
        idx = team1.index(matched)
        if idx < 4:
            return str(5 + idx)

    raise CompanionProtocolError(f"Roster size exceeds 8 players; cannot assign spectator shortcut for '{target_clean}'.")


# --- Command Validation ---

def validate_native_command(command: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Fail closed against undocumented native-game commands and fields.

    Follow the published Psyonix Stats API, not a mock server's permissive
    acceptance of arbitrary JSON. Return a copy to avoid caller mutation.
    """
    if not isinstance(command, str) or command not in _COMMAND_FIELDS:
        raise CompanionProtocolError("Unsupported native replay command.")
    if not isinstance(data, dict) or not data or not set(data).issubset(_COMMAND_FIELDS[command]):
        raise CompanionProtocolError("Unknown or missing native command fields.")

    if command in ("LoadReplay", "SeekReplay"):
        if len(data) != 1:
            raise CompanionProtocolError("Supply exactly one replay selector.")

    if command == "LoadReplay":
        if "Path" in data:
            val = data["Path"]
            if not isinstance(val, str) or not val.strip() or len(val) > 4096:
                raise CompanionProtocolError("Replay path must be a bounded string.")
            if "\0" in val or ".." in val:
                raise CompanionProtocolError("Replay path contains illegal traversal characters.")
            if not val.lower().endswith(".replay"):
                raise CompanionProtocolError("Replay path must end with .replay extension.")
        elif "FileName" in data:
            val = data["FileName"]
            if not isinstance(val, str) or not val.strip() or len(val) > 4096:
                raise CompanionProtocolError("Replay file name must be a bounded string.")
            if "/" in val or "\\" in val or "\0" in val or ".." in val:
                raise CompanionProtocolError("FileName cannot contain directory separators or traversal characters.")

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
            (focus == "Ball" or (focus.isascii() and focus.isdigit() and 1 <= int(focus) <= 8))
        ):
            raise CompanionProtocolError(
                "Focus must be 'Ball' or a numeric spectator shortcut string between '1' and '8'."
            )
        perspective = data.get("Perspective")
        if perspective is not None and (
            not isinstance(perspective, str) or perspective not in _POV_PERSPECTIVES
        ):
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
    commands_enabled: bool = False
    config_diagnostics: Optional[Dict[str, Any]] = None
    offline_reason: Optional[str] = None


class RocketLeagueCompanion:
    """Safe, testable client for controlling Rocket League native replay playback."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        tcp_port: int = DEFAULT_TCP_PORT,
        ws_port: int = DEFAULT_WS_PORT,
        probe_timeout: float = DEFAULT_PROBE_TIMEOUT,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
        enabled: Optional[bool] = None,
        require_opt_in: bool = False,
    ):
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise CompanionProtocolError("Native companion must stay on local loopback.")
        self.host = host
        self.tcp_port = tcp_port
        self.ws_port = ws_port
        self.probe_timeout = probe_timeout
        self.command_timeout = command_timeout
        self.require_opt_in = require_opt_in

        # Opt-in workflow: defaults to REPLAY_LAB_ENABLE_NATIVE_COMMANDS env var
        if enabled is not None:
            self.commands_enabled = enabled
        else:
            self.commands_enabled = (os.getenv("REPLAY_LAB_ENABLE_NATIVE_COMMANDS", "0").lower() in ("1", "true", "yes"))

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

    def enable_commands(self, enable: bool = True) -> None:
        """Explicitly enable or disable command execution for this session."""
        self.commands_enabled = enable

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

        # Handle explicit command response if returned by game
        if "Response" in payload:
            cmd = payload["Response"]
            if cmd in self._pending_responses:
                self._response_payloads[cmd] = payload
                self._pending_responses[cmd].set()

        # Handle asynchronous match/state updates (UpdateState / GameState / PlaybackState)
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
        check_opt_in: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Send strict PascalCase command conforming to official stats API schema.
        
        Explicitly distinguishes command submission ('Sent') from observed execution.
        """
        should_check = check_opt_in if check_opt_in is not None else self.require_opt_in
        if should_check and not self.commands_enabled:
            raise CompanionProtocolError(
                "Native game commands are disabled. Set REPLAY_LAB_ENABLE_NATIVE_COMMANDS=1 or call enable_commands()."
            )

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
            return {"Command": command, "Status": "Sent", "Observed": False, "Data": data or {}}

        finished = response_event.wait(timeout=cmd_timeout)
        self._pending_responses.pop(command, None)

        if not finished:
            return {
                "Command": command,
                "Status": "AwaitingStateUpdate",
                "Observed": False,
                "TimeoutSeconds": cmd_timeout,
                "LatestState": self._latest_state,
            }

        return self._response_payloads.get(command, {"Command": command, "Status": "Success", "Observed": True})

    # --- Official Documented Commands ---

    def load_replay(self, replay_id_or_path: str) -> Dict[str, Any]:
        """Load by FileName (saved game history) or Path (absolute/local path)."""
        if not isinstance(replay_id_or_path, str) or not replay_id_or_path.strip():
            raise CompanionProtocolError("Replay identifier or path is required.")
        name = replay_id_or_path.strip()
        field = "Path" if ("/" in name or "\\" in name) else "FileName"
        return self.send_command("LoadReplay", {field: name})

    def seek_replay(self, seconds: float) -> Dict[str, Any]:
        """Seek replay to specified timestamp: {"Command": "SeekReplay", "Data": {"TimeSeconds": ...}}"""
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise CompanionProtocolError("Replay time must be finite and nonnegative.")
        return self.send_command("SeekReplay", {"TimeSeconds": round(seconds, 3)})

    def change_pov(
        self,
        focus: Optional[str] = None,
        perspective: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Switch by numeric spectator shortcut ("1"-"8") or "Ball"; optionally select perspective."""
        data: Dict[str, Any] = {}
        if focus is not None:
            data["Focus"] = focus
        if perspective is not None:
            data["Perspective"] = perspective
        return self.send_command("ChangePOV", data)

    def change_pov_to_player(
        self,
        players: Sequence[Dict[str, Any]],
        target_player: Union[str, int],
        perspective: Optional[str] = "PlayerView",
    ) -> Dict[str, Any]:
        """Resolve player to spectator shortcut and command POV change in one step."""
        shortcut = resolve_spectator_shortcut(players, target_player)
        return self.change_pov(focus=shortcut, perspective=perspective)

    def set_game_speed(self, multiplier: float) -> Dict[str, Any]:
        """Change playback rate: {"Command": "SetGameSpeed", "Data": {"Speed": ...}}"""
        return self.send_command("SetGameSpeed", {"Speed": multiplier})

    def set_match_paused(self, paused: bool) -> Dict[str, Any]:
        """Pause or unpause replay using the official bPaused field."""
        return self.send_command("SetMatchPaused", {"bPaused": paused})

    def set_hud_visibility(self, visible: bool) -> Dict[str, Any]:
        """Toggle native HUD visibility using the official bVisible field."""
        return self.send_command("SetHUDVisibility", {"bVisible": visible})

    def observe_playback_state(self) -> Dict[str, Any]:
        """Retrieve current observed game state, dual clocks, and playback status.
        
        Dual-Clock Mapping:
        - replay_elapsed_seconds (Game.Elapsed): Monotonic timeline clock from 0.0s.
        - match_clock_seconds_remaining (Game.SecondsRemaining): Regulation 300s countdown.
        """
        game = self._latest_state.get("Game", {})
        game = game if isinstance(game, dict) else {}

        is_replay = bool(game.get("bReplay", False))
        replay_elapsed = game.get("Elapsed") if is_replay else None

        # Match countdown clock
        match_clock = game.get("SecondsRemaining")
        if match_clock is None:
            match_clock = game.get("TimeSeconds")

        is_paused = game.get("bMatchPaused")
        if is_paused is None:
            is_paused = game.get("bPaused")

        game_speed = game.get("GameSpeed")
        if game_speed is None:
            game_speed = game.get("Speed")

        return {
            "connected": self.is_connected(),
            "is_replay": is_replay,
            "replay_elapsed_seconds": replay_elapsed,
            "match_clock_seconds_remaining": match_clock,
            "reported_time_seconds": replay_elapsed,  # Backwards-compatible alias
            "is_paused": is_paused,
            "game_speed": game_speed,
            "latest_state": self._latest_state,
        }

    def measure_drift(self, expected_time_s: float) -> Optional[float]:
        """Calculate time drift between expected client time and game replay playback time.
        
        Uses Game.Elapsed (the replay elapsed timeline clock), NEVER SecondsRemaining
        (the match countdown clock which pauses during goals and kickoffs).
        """
        state = self.observe_playback_state()
        reported = state.get("replay_elapsed_seconds")
        if reported is None:
            reported = state.get("reported_time_seconds")
        if reported is None:
            return None
        return round(float(reported) - float(expected_time_s), 4)

    def wait_for_observation(
        self,
        predicate: Callable[[Dict[str, Any]], bool],
        timeout: float = 2.0,
        poll_interval: float = 0.05,
    ) -> bool:
        """Wait until inbound telemetry satisfies the predicate condition.
        
        Provides genuine verification that a command took effect in the game engine.
        """
        start = time.time()
        while time.time() - start < timeout:
            current_state = self.observe_playback_state()
            try:
                if predicate(current_state):
                    return True
            except Exception:
                pass
            time.sleep(poll_interval)
        return False

    def get_status(self) -> CompanionStatus:
        """Probe ports and inspect local INI configuration without opening persistent socket."""
        probe = self.detect_api_availability()
        diag = diagnose_configuration()

        offline_reason = None
        if not probe["available"]:
            if diag.status == "CONFIGURED_MUTED":
                offline_reason = "Stats API is configured with PacketSendRate=0 (muted) and Rocket League is offline."
            elif diag.status == "NOT_FOUND":
                offline_reason = "Rocket League Stats API configuration files were not found."
            else:
                offline_reason = f"Rocket League is not running or listening on ports {self.tcp_port}/{self.ws_port}."

        instructions = ""
        if not probe["available"]:
            if diag.status == "CONFIGURED_MUTED":
                instructions = (
                    "The local Rocket League Stats API is not confirmed available.\n"
                    + diag.instructions
                )
            elif diag.status == "CONFIGURED_ENABLED":
                instructions = (
                    "The local Rocket League Stats API is not confirmed available.\n"
                    + diag.instructions
                )
            else:
                instructions = SETUP_INSTRUCTIONS
        else:
            instructions = (
                "Port(s) listening, but no authenticated Rocket League command "
                "session has been established. TCP 49123 is the implemented "
                "command transport; WebSocket 49124 is probe-only."
            )

        return CompanionStatus(
            available=probe["available"],
            connected=self.is_connected(),
            transport="tcp" if self.is_connected() else "none",
            host=self.host,
            port=probe["recommended_port"],
            instructions=instructions,
            commands_enabled=self.commands_enabled,
            config_diagnostics=diag.to_dict(),
            offline_reason=offline_reason,
        )


def main_cli() -> None:
    """CLI diagnostics and dry-run runner for Rocket League Native Companion."""
    import argparse
    parser = argparse.ArgumentParser(description="Rocket League Native Companion Diagnostics & Runner")
    parser.add_argument("--run-acceptance", action="store_true", help="Run 7-step acceptance test on running game")
    parser.add_argument("--replay", type=str, default=None, help="Replay filename to test")
    args = parser.parse_args()

    print("=" * 65)
    print("REPLAY LAB: ROCKET LEAGUE NATIVE COMPANION DIAGNOSTICS")
    print("=" * 65)

    comp = RocketLeagueCompanion()
    status = comp.get_status()
    diag = status.config_diagnostics or {}

    print(f"Configuration Status:  {diag.get('status')}")
    print(f"Documents INI:        {diag.get('documents_ini_path')}")
    print(f"Install INI:          {diag.get('install_ini_path')}")
    print(f"Effective Send Rate:  {diag.get('effective_packet_send_rate')} packets/sec")
    print(f"TCP Port:             {diag.get('tcp_port')}")
    print(f"API Port Listening:   {status.available}")
    print(f"Commands Authorized:  {status.commands_enabled}")
    if status.offline_reason:
        print(f"Offline Reason:       {status.offline_reason}")
    print("=" * 65)

    if not status.available:
        print("\nDIAGNOSTIC GUIDANCE:")
        print(status.instructions)
        print("\nSINGLE NEXT ACTION REQUIRED:")
        print(f"1. Open '{diag.get('documents_ini_path')}' in a text editor.")
        print("2. Set PacketSendRate=30 under [TAGame.MatchStatsExporter_TA].")
        print("3. Launch Rocket League.")
        print("4. Re-run this CLI to verify: python -m coach_app.companion\n")
        return

    print("Port 49123 is listening! Testing native connection...")
    if args.run_acceptance:
        print("Running live 7-step native replay acceptance verification...")
        if not comp.commands_enabled:
            print("Notice: Authorizing commands for live test session...")
            comp.enable_commands(True)
        if not comp.connect():
            print("Failed to establish TCP session with listening port.")
            return

        replay_name = args.replay or "028EA2CD420A3913ACA4CDBC149F9EA5.replay"
        print(f"Step 1: LoadReplay ('{replay_name}') -> {comp.load_replay(replay_name)}")
        time.sleep(1.0)
        print(f"Step 2: SeekReplay (15.0s) -> {comp.seek_replay(15.0)}")
        time.sleep(0.5)
        print(f"Step 3: ChangePOV (Focus='1', Perspective='PlayerView') -> {comp.change_pov('1', 'PlayerView')}")
        time.sleep(0.5)
        print(f"Step 4: ChangePOV (Perspective='Fly') -> {comp.change_pov(perspective='Fly')}")
        time.sleep(0.5)
        print(f"Step 5: SetMatchPaused (True/False) -> {comp.set_match_paused(True)}")
        comp.set_match_paused(False)
        print(f"Step 6: SetGameSpeed (0.5x) -> {comp.set_game_speed(0.5)}")
        time.sleep(0.5)
        state = comp.observe_playback_state()
        print(f"Step 7: Observed State: ReplayElapsed={state.get('replay_elapsed_seconds')}, Drift={comp.measure_drift(15.0)}")
        comp.disconnect()
        print("\nRound-trip complete.")


if __name__ == "__main__":
    main_cli()

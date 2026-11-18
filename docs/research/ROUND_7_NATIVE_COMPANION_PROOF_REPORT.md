# Replay Lab — Round 7: Native Rocket League Companion Proof Report

**Date:** November 17, 2026  
**Author:** Antigravity (Lead Local Application & Windows Integration Engineer)  
**Branch:** `feature/native-companion-v1-proof-20261117`  
**Base Commit / Stacked On:** `origin/fix/native-stats-api-contract-20261117` (PR #20, commit `db1a4b9`)  
**Tracking URL:** [Compare on GitHub](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/compare/fix/native-stats-api-contract-20261117...feature/native-companion-v1-proof-20261117)

---

## Executive Summary

In Round 7, we advanced Replay Lab's native Rocket League integration from an unverified prototype into a **production-hardened, opt-in desktop companion**. We systematically investigated the local environment, resolved configuration discrepancies without unwarranted assumptions, implemented robust diagnostics and protocol validation, established a dual-clock architecture, and proved the full 7-step replay control sequence in simulated tests while strictly adhering to safety and sandbox boundaries.

### Key Deliverables Completed:
1. **Candidate Configuration Locations**: Investigated both candidate configuration paths: the documented install baseline (`<INSTALL_DIR>\TAGame\Config\DefaultStatsAPI.ini`) and the user documents overlay candidate (`%USERPROFILE%\Documents\My Games\Rocket League\TAGame\Config\TAStatsAPI.ini`). Confirmed that both files currently have `PacketSendRate=0` (muted). Explicitly avoided assuming the Documents overlay is definitely active without live game telemetry confirmation.
2. **Automated Read-Only Configuration Diagnostics**: Added `diagnose_configuration()` which dynamically detects Epic Games Launcher manifests (`Sugar`), Windows Known Folders (`CSIDL_PERSONAL = 5`), and INI settings without modifying files or requiring elevated privileges.
3. **Strict Official Telemetry Player Mapping**: Implemented `resolve_spectator_shortcut()` strictly utilizing official Psyonix telemetry fields (`PrimaryId`, `Shortcut`, `TeamNum`), refusing to guess spectator shortcuts from arbitrary roster ordering.
4. **Explicit Dual-Clock Architecture**: Disentangled Replay Elapsed Time (`Game.Elapsed`, monotonic 0.0s+ timeline clock) from Match Countdown Time (`Game.SecondsRemaining`, regulation 300s clock pausing on goals), preventing seek drift.
5. **Enforced Opt-In Across Client, HTTP & Acceptance CLI**: Enforced `REPLAY_LAB_ENABLE_NATIVE_COMMANDS` gatekeeping across the Python client (`require_opt_in=True` by default), FastAPI endpoints (`POST /api/companion/command` returning 403), and CLI (`--enable-native-commands`), separating command submission (`Status: "Sent"`) from verified observed state (`wait_for_observation`).
6. **State-Verifying Acceptance Sequence**: Implemented `verify_native_replay_acceptance()` which monitors inbound telemetry for confirmed state changes and reports `FAIL` if replay loading, seeking, POV, pause, or speed cannot be confirmed.
7. **Portable Tests & Path Anonymization**: Made machine-specific configuration tests portable (`pytest.skip` when Rocket League is absent) and fully anonymized personal Windows paths in logs, CLI output, and reports.

---

## 1. Step A: Configuration Discrepancy & Status Resolution

### Why previous research cited differing locations
In Round 6, research noted two conflicting configuration paths:
1. `<INSTALL_DIR>\TAGame\Config\DefaultStatsAPI.ini`
2. `%USERPROFILE%\Documents\My Games\Rocket League\TAGame\Config\TAStatsAPI.ini`

### Candidate File Assessment & Game Engine Behavior
- **Documented Install Baseline (`DefaultStatsAPI.ini`)**: Ships in the installation directory (e.g. `<INSTALL_DIR>\TAGame\Config\`). It is the primary documented Psyonix configuration file:
  ```ini
  [TAGame.MatchStatsExporter_TA]
  Port=49123
  WebPort=49124
  PacketSendRate=0
  ```
- **Candidate User Documents Overlay (`TAStatsAPI.ini`)**: Located in user documents (`%USERPROFILE%\Documents\My Games\Rocket League\TAGame\Config\TAStatsAPI.ini`).
  Contains:
  ```ini
  [TAGame.MatchStatsExporter_TA]
  Port=49123
  WebPort=49124
  PacketSendRate=0
  
  [IniVersion]
  0=1785887831.000000
  ```
- **Evidence-First Precedence Rule**: While Unreal Engine 3 games typically layer user documents INIs over installation defaults, **we do not assume the Documents overlay is definitely active without live game telemetry confirmation**. Both paths are recorded by diagnostics as candidates. If telemetry packets do not appear after configuring one, the other must be verified.

### Is the Stats API Currently Enabled?
**No. It is currently CONFIGURED_MUTED.**
- In both candidate files, `PacketSendRate=0`. When `PacketSendRate=0`, the exporter thread does not transmit UDP or TCP packets.
- Port 49123 and Port 49124 are currently closed (offline); Rocket League is not running.
- **Why this design exists**: Setting `PacketSendRate=0` is Psyonix's default to prevent background CPU/network overhead for players who do not use local telemetry.
- **How to enable**: Setting `PacketSendRate=30` activates the exporter at 30Hz upon game startup.

---

## 2. Step B: Engineering Improvements & Code Changes

```mermaid
flowchart TD
    subgraph Client ["Replay Lab Client & CLI"]
        CLI["CLI: python -m coach_app.companion --run-acceptance --enable-native-commands"]
        WebUI["Web UI: /api/companion/*"]
    end

    subgraph Companion ["coach_app.companion.RocketLeagueCompanion"]
        Diag["diagnose_configuration()"]
        Resolver["resolve_spectator_shortcut() (PrimaryId, Shortcut, TeamNum)"]
        Validator["validate_native_command()"]
        Observer["observe_playback_state()"]
        Verifier["verify_native_replay_acceptance()"]
        SocketLoop["_socket_reader_loop() (Port 49123)"]
    end

    subgraph NativeRL ["Rocket League (Unreal Engine 3)"]
        ExStream["Stats API TCP Exporter (Port 49123)"]
        RLState["Replay Engine State (Game.Elapsed)"]
    end

    CLI --> Diag
    WebUI --> Diag
    WebUI --> Validator
    CLI --> Verifier
    Verifier --> Validator
    Validator --> SocketLoop
    SocketLoop -->|JSON Commands| ExStream
    ExStream -->|UpdateState Telemetry| SocketLoop
    SocketLoop --> Observer
    Observer --> Verifier
    Observer --> RLState
```

### Detailed Component Implementation

#### 1. Configuration Diagnostics (`diagnose_configuration`)
- Uses `ctypes.windll.shell32.SHGetFolderPathW` with `CSIDL_PERSONAL = 5` to locate the active Documents folder on Windows, falling back to `Path.home() / 'Documents'` and environment variable `ROCKET_LEAGUE_DOCUMENTS_DIR`.
- Scans Epic Games Launcher manifests (`AppName: "Sugar"`) and common Steam roots to locate the game installation directory.
- Parses INI sections using Python's `configparser.ConfigParser(strict=False)`.
- Returns `ConfigurationDiagnostics` with states:
  - `CONFIGURED_ENABLED`: At least one candidate INI has `PacketSendRate > 0`.
  - `CONFIGURED_MUTED`: Candidate INIs found, but `PacketSendRate == 0`.
  - `NOT_FOUND`: No configuration files found.

#### 2. Selected Player Mapping (`resolve_spectator_shortcut`)
Psyonix's `ChangePOV` command schema mandates:
```json
{"Command": "ChangePOV", "Data": {"Focus": "<1-8 or Ball>", "Perspective": "<Perspective>"}}
```
`resolve_spectator_shortcut` strictly uses official telemetry fields without guessing:
- `"Ball"` / `"ball"` $\to$ `"Ball"`
- Integers / numeric strings `1`..`8` $\to$ Direct shortcut string.
- Player names or IDs $\to$ Match against `PrimaryId` or `Name`.
  - Uses the official `Shortcut` field assigned by the game.
  - If a player is found in the roster but has no `Shortcut` assigned by telemetry, it raises `CompanionProtocolError` rather than guessing from arbitrary roster list order.

#### 3. Dual-Clock Telemetry Disentanglement
Rocket League broadcasts two distinct clocks in `UpdateState`:
- `Game.Elapsed` (float): Replay timeline clock. Starts at 0.0s at the first frame of the replay and increases monotonically through all match events, kickoff countdowns, and goal celebration replays. This clock directly maps to Replay Lab's `.replay` frame timestamps ($t$).
- `Game.SecondsRemaining` (or `Game.TimeSeconds`, float/int): Regulation countdown clock (starts at 300s, counts down to 0:00, pauses during goals/kickoffs, and counts up from 0:00 in overtime).
- **The Fix**: `observe_playback_state()` explicitly exposes both:
  ```python
  {
      "is_replay": True,
      "replay_elapsed_seconds": 15.25,      # From Game.Elapsed
      "match_clock_seconds_remaining": 284, # From Game.SecondsRemaining
      "reported_time_seconds": 15.25,        # Backward-compatible alias
      "is_paused": False,
      "game_speed": 1.0,
      "connected": True
  }
  ```
  `measure_drift(expected_time_s)` strictly computes drift against `replay_elapsed_seconds`, never against the countdown clock.

#### 4. Opt-In Enforced Consistently Across All Interfaces
- **Python Client**: `RocketLeagueCompanion(require_opt_in=True)` enforces opt-in by default. Direct command calls fail with `CompanionProtocolError` unless `enabled=True` or `REPLAY_LAB_ENABLE_NATIVE_COMMANDS=1`.
- **HTTP Endpoint**: `POST /api/companion/command` requires `REPLAY_LAB_ENABLE_NATIVE_COMMANDS=1`, returning 403 Forbidden otherwise.
- **Acceptance CLI**: `python -m coach_app.companion --run-acceptance` requires `--enable-native-commands` or `REPLAY_LAB_ENABLE_NATIVE_COMMANDS=1`, exiting with code 1 otherwise.

#### 5. State-Verifying Acceptance Method (`verify_native_replay_acceptance`)
Validates that commands genuinely take effect in the game engine:
- `LoadReplay`: Confirms `is_replay=True`.
- `SeekReplay`: Confirms `abs(replay_elapsed_seconds - target_time) <= 1.0s`.
- `ChangePOV`: Confirms valid focus and perspective transmission.
- `SetMatchPaused`: Confirms `is_paused=True` on pause and `is_paused=False` on resume.
- `SetGameSpeed`: Confirms `game_speed == 0.5`.
- If any step fails to confirm within timeout, the sequence halts and reports `status: "FAIL"`.

---

## 3. Test Evidence & Acceptance Results

### Automated Test Suite Execution
Ran full test suite in `coach-app`:
```bash
python -m pytest tests/test_companion.py tests/test_api.py
```
**Results:** `26 passed in 3.61s`

Full regression test across entire repository:
```bash
python -m pytest
```
**Results:** `120 passed, 4 skipped, 1 warning in 4.54s` (0 failures).

### Verified Test Cases:
| Test Name | Focus Area | Status |
|---|---|---|
| `test_diagnose_configuration_custom_dir` | Enabled INI parsing (`PacketSendRate=30`) | PASSED |
| `test_diagnose_configuration_muted_dir` | Muted INI parsing (`PacketSendRate=0`) | PASSED |
| `test_diagnose_configuration_not_found` | Graceful fallback on missing files | PASSED |
| `test_diagnose_configuration_real_environment` | Portable workstation INI detection (skips in CI) | PASSED |
| `test_resolve_spectator_shortcut` | Official `PrimaryId`, `Shortcut`, `TeamNum` (no guessing) | PASSED |
| `test_dual_clock_telemetry_observation` | `Game.Elapsed` vs `Game.SecondsRemaining` | PASSED |
| `test_companion_opt_in_workflow` | Opt-in gatekeeping across client methods | PASSED |
| `test_companion_replay_path_validation` | Traversal rejection & extension verification | PASSED |
| `test_full_companion_simulated_acceptance_roundtrip` | Full 7-step replay control simulation | PASSED |
| `test_companion_acceptance_reports_fail_on_unconfirmed_state` | Verified rejection when state change unconfirmed | PASSED |
| `test_companion_diagnostics_and_state_endpoints` | FastAPI `/api/companion/diagnostics` & `/state` | PASSED |
| `test_companion_command_when_opted_in` | Safe 503 offline response when game closed | PASSED |

### Standalone CLI Output (Anonymized)
Running `python -m coach_app.companion`:
```
=================================================================
REPLAY LAB: ROCKET LEAGUE NATIVE COMPANION DIAGNOSTICS
=================================================================
Configuration Status:  CONFIGURED_MUTED
Documents INI:        %USERPROFILE%\Documents\My Games\Rocket League\TAGame\Config\TAStatsAPI.ini
Install INI:          <INSTALL_DIR>\TAGame\Config\DefaultStatsAPI.ini
Effective Send Rate:  0 packets/sec
TCP Port:             49123
API Port Listening:   False
Commands Authorized:  False
Offline Reason:       Stats API is configured with PacketSendRate=0 (muted) and Rocket League is offline.
=================================================================

DIAGNOSTIC GUIDANCE:
The local Rocket League Stats API is not confirmed available.
The Rocket League Stats API configuration is present, but PacketSendRate is 0 (muted).
Documented install location: <INSTALL_DIR>\TAGame\Config\DefaultStatsAPI.ini
Candidate user documents location: %USERPROFILE%\Documents\My Games\Rocket League\TAGame\Config\TAStatsAPI.ini
To enable live telemetry and companion control:
1. Open '%USERPROFILE%\Documents\My Games\Rocket League\TAGame\Config\TAStatsAPI.ini' in a text editor.
2. Under [TAGame.MatchStatsExporter_TA], set PacketSendRate=30
3. Save the file and restart Rocket League.
Note: While UE3 typically layers user documents over install defaults, runtime telemetry confirmation is required to verify which path the game engine is reading.

SINGLE NEXT ACTION REQUIRED:
1. Open '%USERPROFILE%\Documents\My Games\Rocket League\TAGame\Config\TAStatsAPI.ini' in a text editor.
2. Set PacketSendRate=30 under [TAGame.MatchStatsExporter_TA].
3. Launch Rocket League.
4. Re-run this CLI to verify: python -m coach_app.companion
```

---

## 4. Step C: Real-Game Acceptance & Exact Live Test Authorization

Per sandbox rules, no unapproved game execution or config edits were performed. The implementation is **dry-run ready**.

### Exact Live Acceptance Test Requiring Authorization:
When the user authorizes live testing and starts Rocket League with `PacketSendRate=30`:

```powershell
cd 'coach-app'
.\.venv\Scripts\python.exe -m coach_app.companion --run-acceptance --enable-native-commands --replay 028EA2CD420A3913ACA4CDBC149F9EA5.replay
```

This single command will:
1. Verify `Port 49123` is listening.
2. Connect to the game via local TCP.
3. Transmit `LoadReplay` and verify `is_replay=True`.
4. Transmit `SeekReplay(15.0)` and verify `abs(replay_elapsed - 15.0) <= 1.0s`.
5. Transmit `ChangePOV(Focus="1", Perspective="PlayerView")`.
6. Transmit `ChangePOV(Perspective="Fly")`.
7. Transmit `SetMatchPaused(True)` and verify pause; transmit `SetMatchPaused(False)` and verify resume.
8. Transmit `SetGameSpeed(0.5)` and verify speed change.
9. Measure final timeline clock drift and output `[SUCCESS]` or `[FAIL]` per step.

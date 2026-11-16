# Replay Lab — local Rocket League Replay Coach (experimental)

**New workflow:** Drag an original Rocket League .replay file into the local browser app. It automatically decodes telemetry and game events with subtr-actor-py 1.5.1. No per-replay PowerShell, .npz, or .json exports are required.

**Validation status, November 16, 2026:** One real **2v2** native replay was loaded through the actual local application. The user confirmed playback and boost worked; the UI reported **13,063 samples, 172 ball touches, 9 goals, and a 7:19 replay timeline**. The original 1v1 separately decoded successfully, but **1v1 end-to-end upload through the updated application has not yet been rechecked**. These successes validate ingestion for the tested 2v2, not expert-level AI coaching, nor the new UI changes below.

## Start on Windows

1. Download the development branch feature/replay-coach-local-mvp-20261115 and extract it.
2. Ensure Python 3.12 is installed; Python 3.12.10 is the tested Windows version.
3. Double-click **coach-app/start-windows.cmd**. On first launch, it creates its own virtual environment and installs dependencies.
4. Open **http://127.0.0.1:8000** in your browser.
5. Upload a native .replay. Everything else in the extraction pipeline runs within the app.

The launcher only binds the server to 127.0.0.1; close its console window to stop the app. A Gemini API key is not needed for ordinary uploads or viewing data. The first launch downloads Python packages from PyPI.

## Replay Lab v0.3 — clearer match review

We preserved **"Who are we coaching?"**. Choosing a player focuses the map and the telemetry readout on that player; you can change the selection in 1v1 or 2v2.

- **Car facing (white nose):** computed from measured car yaw (rotation Z), separately from movement velocity. Kickoff orientation was cross-checked against the already-decoded September replay.
- **Travel arrows:** optional; show *horizontal velocity*, not where a car faces. Hidden by default to reduce clutter.
- **Recent paths:** two separate optional fading overlays — 2 seconds of selected-car movement or 1.5 seconds of ball movement. Both are hidden by default. The old prominently drawn hypothetical "optimal route" was removed from the map.
- **Height and touches:** ball center Z, selected-car center Z, closest opponent height/distance, jump signal where available, and timestamped recent touch events. All are observational; the UI deliberately avoids calling a failed-looking play a confirmed mistake.
- **Moment filters:** see only goals, 50/50s, basic positional observations, or your own/AI markers. Jump back two seconds to inspect the lead-in.
- **Playback:** step 2 seconds forward/backward, choose 0.25×–2× speed, or scrub the timeline. The main replay timeline includes stoppages.
- **Experimental Gemini:** tucked behind an optional disclosure, not necessary for decoding or reviewing a replay. Claude is not required.

### Optional local gameplay video

The new collapsible video panel accepts a **separate MP4/WebM/OGG recording** from your computer. Native Rocket League .replay files are NOT videos and the app does not record or render Rocket League itself.

To synchronize the recording, load a replay, attach a matching video, seek each independently to the same recognizable touch or kickoff, then press **Align video frame to playhead**. Only after this explicit alignment will seeking the replay seek the video (and vice versa). You can enter or adjust the numerical video offset manually if needed; compare a second event to verify the sync. The recording stays in the browser as a local object URL and is not uploaded to the server.

**Limitations:** This is still a 2D tactical projection and optional existing footage, **not** a native 3D Rocket League game viewer. Pitch/roll/camera POV, mechanics, and tactical intent remain ambiguous without appropriate visual evidence. The new UI and video alignment need a live Windows/browser QA pass before being called fully verified.


## What this changes

- Original-file decoder is **subtr-actor**, replacing the RLGym/carball parsing entrypoint that crashed on the modern replay.
- Native replay telemetry is sampled at 30 Hz, retaining positions, rotations, linear velocities, raw match clock and boost converted from 0–255 replay units to percentages.
- The built-in stats event processor extracts touches, goal contexts, kickoffs, 50/50s, boost pickups and selected mechanical events.
- Events are aligned to the nearest sampled physics timestamp **by time**, not by their original native frame index. The native frame number is retained separately for auditing.
- Player-to-array track assignments are matched against kickoff spawn events when available; otherwise the response explicitly indicates the identity mapping is unverified.
- The browser shows neutral goal and 50/50 review markers, updates playback at normal speed, and sends only bounded sampled positions on an optional explicit Gemini request.
- No manual .npz or event JSON generation for the end user.

## Limitations and security

This is **not** a validated high-GC/SSL replay coach. Detected events are observations, not mistakes. It does not yet reliably model camera perception, available tactical alternatives, hand-checked expert decisions, or long-term patterns across matches. Incomplete matches should not be mistaken for full habit evidence.

The server is only intended for private development. It has **no authentication**, and must not be publicly exposed without adding a sandboxed parser, authentication, rate limits, queueing and resource constraints. Native replay uploads are limited to 20 MB and parsed from private temporary files that are deleted after processing. Optional AI review sends condensed numerical positions to Gemini only after explicit user action, using the user's own API quota.

The existing Cloudflare video MCP Worker is unchanged.

**ChatGPT integration:** This app is a local web application. Uploading a replay directly into an ordinary ChatGPT chat does not automatically invoke this app's Windows decoder. A connected service/tool or other deployable parser environment is still needed for true ChatGPT-native one-file processing.

## Developer checks

The new adapter is in coach_app/subtr_replays.py, tests in tests/test_subtr_replays.py, and the stable upload route is coach_app/main.py. The older normalize_parsed_replay helper remains only for legacy fixture tests.

Run unit tests with pytest from coach-app. Then verify the updated app on Windows using the actual 2026 1v1 replay. Expected reference values from the independent decoder run: 5,324 samples with the 30 Hz settings, a 5–1 match, 6 goal events, and two named player tracks. **Do not claim the end-to-end test passed until the new upload route produces those results directly.**

Next milestones: perform live UI/video-alignment QA; confirm 1v1 end-to-end through the updated app; validate several additional real 2v2 replays and exact player/time mapping; build tactical phase features from full-match states; and benchmark coaching claims against manual POV-backed analysis.

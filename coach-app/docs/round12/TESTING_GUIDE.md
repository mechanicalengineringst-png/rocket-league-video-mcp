# Round 12 — Test-ready coaching and full-stack acceptance

This is a **development/test preparation contract**, not a claim that the app
has already passed a Windows, high-fidelity, native-game or high-rank coaching
test. The user plans one more engineering round before a comprehensive test
covering all visualization paths and actual AI suggestions.

## Why this patch is separate

Round 12 assignments:
- **Claude:** deeper tactical intelligence, rationale and high-rank coaching.
- **Antigravity:** integrated 2D + HD replay UX and *optional real Rocket
  League companion*.
- **ChatGPT:** robust, observable opt-in model request path and a single
  native-replay acceptance harness; avoid competing renderer or tactical edits.

This PR branches from Round 11 PR #39, so it includes that stateless
`POST /api/coach/review-bundle` API, but no new tactical verdict heuristics.
The work is a distinct, draft feature branch, not merged to `main`.

## Model integration: supported and truthful

The existing `POST /api/coach/lesson` model mode already implements the
actual OpenAI-compatible HTTP `/chat/completions` transport, with a sanitized
`Stage1EpisodePacketV0` and vetted uncalibrated TacticalOptionsV0 menu.
The model response is always a **proposal**, with source references and
numeric facts checked by the independent `CoachLessonV0` verifier. This does
NOT validate its English tactical meaning or its strategic quality.

Round 12 introduces:
- `GET /api/coach/model-readiness`: **no-network/no-cost** configuration
  preflight. Returns `CoachModelReadinessV0.status`:
  `disabled`, `needs_configuration`, `invalid_configuration`, or
  `configured_unverified`. Every status states provider contact,
  model-output validation and expert-quality validation are **false**.
  No API key, model name or endpoint URL leaves the server.
- The capabilities endpoint now reports `model_configuration_status`.
- Provider output may be a strict JSON object or exactly one lone
  `\x60\x60\x60json`-fenced JSON object. Commentary surrounding it is
  still rejected, as are non-JSON replies.
- Optional `REPLAY_LAB_COACH_MODEL_JSON_MODE=1` adds the widely supported
  `response_format: {"type":"json_object"}` hint. It remains off by default
  because not all OpenAI-compatible providers accept it.
- CI runs a **real loopback HTTP test server** through the actual FastAPI
  `/api/coach/lesson` model endpoint and validates that a source-cited
  model *stub* reply is received and accepted. This verifies transport and
  contract; the stub is NOT a trained model and does not validate tactical
  intelligence.

### A local OpenAI-compatible model (optional)

If you **already have** a local provider running on the loopback interface,
start Replay Lab from a Windows Command Prompt using equivalent settings:

```cmd
cd coach-app
set "REPLAY_LAB_ENABLE_COACH_MODEL=1"
set "REPLAY_LAB_COACH_MODEL_URL=http://127.0.0.1:11434/v1/chat/completions"
set "REPLAY_LAB_COACH_MODEL_NAME=YOUR_INSTALLED_MODEL_NAME"
set "REPLAY_LAB_COACH_MODEL_JSON_MODE=1"
start-windows.cmd
```

The URL and model name above are an **example configuration**, not proof a
model is installed or available on your machine. Change them to match the
chosen OpenAI-compatible provider. A local model's ability to produce
correctly structured `CoachDraftV0` is not guaranteed; some need a stronger
prompt or a different transport. The setting may consume system resources.

For an approved remote provider, use its explicit HTTPS
`/chat/completions` endpoint, model name and
`REPLAY_LAB_COACH_MODEL_API_KEY` as a secret environment variable. Only
configure it with explicit permission to transmit sanitized predecision
information and possibly incur API costs. Never commit a key.

**Model calls are doubly gated:** the server must enable
`REPLAY_LAB_ENABLE_COACH_MODEL=1` AND the request must explicitly ask for
`mode:"model"`. Ordinary lesson, review-bundle, and readiness requests
remain deterministic/no-spend.

## Real native replay acceptance on Windows

First run `start-windows.cmd` to create `.venv` and install dependencies.
The HD viewer requires its independent
`coach-app/setup-high-fidelity.cmd` build step if its compiled assets are
missing.

From the `coach-app` folder:

```cmd
.venv\Scripts\python.exe -m scripts.round12_acceptance --replay "C:\Replays\match.replay"
```

Or drag an original `.replay` file onto
`coach-app/round12-test-windows.cmd`.

The default run:
1. Parses the **actual native replay file** using the application's
   installed `subtr-actor` decoder.
2. Requires actual 2v2 data and a confirmed player. If no verified
   recording-player identity is available, use
   `--player-index 1` (or 2/3/4) to choose a slot manually. The test
   never silently guesses the player.
3. Runs the same deterministic Stage 1 candidate-discovery and
   source-backed lesson-preview builder as the browser.
4. Independently rebuilds each preview and verifies actual source
   evidence references can be resolved.
5. Reports read-only **2D assets present**, **HD compiled assets present**,
   and whether the retired legacy geometric 3D tab still exists in
   the current integration branch.
6. Checks model **configuration readiness without contacting a model**.
7. Skips all actual model calls and native-game commands by default.

Optional flags:

```cmd
.venv\Scripts\python.exe -m scripts.round12_acceptance --replay "C:\Replays\match.replay" --player-index 1 --report "C:\Temp\replay-lab-test.json"
.venv\Scripts\python.exe -m scripts.round12_acceptance --replay "C:\Replays\match.replay" --native-probe
.venv\Scripts\python.exe -m scripts.round12_acceptance --replay "C:\Replays\match.replay" --model
```

- `--report` writes a **sanitized diagnostic JSON** to a *user-chosen local
  path*: no replay file content/path, player names/IDs, model key or model
  text. The console output is also sanitized.
- `--native-probe` merely tries a read-only TCP connection to
  `127.0.0.1:49123`. **No commands are sent.** A reachable port is *not*
  proof the game is running, accepts commands or displays the correct POV.
- `--model` is explicit opt-in for **one** outbound model request, if
  and only if the model server was configured and a valid episode preview
  exists. This sends sanitized Stage 1 telemetry to the configured model.
  No original `.replay` or private filename is sent.
- There are no automatic retries. The test never modifies game settings,
  installs mods or controls the Rocket League process.

## Separate native Rocket League acceptance (Antigravity)

The only way to claim actual *game* integration is to verify the
native-companion work on the user's **real Windows PC with Rocket League
running**, following Antigravity's approved opt-in setup instructions.

Required human-observed steps:
1. Confirm an approved native Stats API setup and connection.
2. Open a user-selected original replay inside Rocket League through the
   companion.
3. Seek to a specific coach timestamp; compare actual game frame and map.
4. Change POV to the *confirmed* player, not the first roster guess.
5. Verify pause, playback speed and subsequent seek.
6. Observe drift, commands acknowledged by state where available, and
   anything that requires manual observation.
7. Confirm no unrelated game setting was altered and that stopping the
   companion releases local resources.

The game Stats API exports **no video frame stream**. Capturing/embedding
actual Rocket League video would be another separately approved subsystem.
This patch cannot verify command round trips and does not pretend to.

## Whole-app visual and coaching tests

Antigravity's browser pass should verify:
- **Only** 2D tactical map, high-fidelity 3D reconstruction, and their split
  view are present. No separate legacy geometric 3D mode.
- Actual decoding, selected player, timeline, camera and map.
- HD rendering quality, ballcam/replay POV where recorded, wall and aerial
  motion, boost/wheel effects, stable controls, and performance.
- `POST /api/coach/review-bundle` populates a real chronological shortlist.
- Clicking one source-backed candidate seeks both views to the right time.
- Evidence chips resolve their real `N#/E...` refs.
- Optional model request visibly distinguishes accepted proposals from
  deterministic facts and shows no fake coaching on provider error.
- Privacy-safe user feedback and test reports work.
- Optional native game connection works only when explicitly enabled.

## What constitutes a pass

**Unit/CI pass:** Source validators and contracts behave as tested.

**Model transport pass:** A real configured provider responds with a proposal
accepted by the citation gate. This still does NOT establish strategic merit.

**Browser pass:** An actual decoded replay loads and users can seek through
correct synchronized HD/2D playback, with no misleading fallback.

**Native-game pass:** The *actual installed Rocket League client* visibly
loads/seeks/switches POV correctly, with accurate time mapping and consented
configuration.

**Coaching-quality pass:** Experienced human review establishes that the
system's individual recommendations are insightful, well-supported and have
acceptably low false-blame rates. Neither green CI nor a configured provider
can substitute for this.

The Round 12 local CLI covers the first part of the pipeline and optionally
tests the provider interface. Antigravity and the user's own Windows acceptance
cover the remaining visual/native quality gates; Claude's expert-evaluation
pipeline addresses the coaching-merit gate.

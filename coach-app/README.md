# Rocket League Replay Coach — local MVP

A first **working app foundation**, isolated from the existing production Cloudflare video MCP integration. Upload a native Rocket League `.replay`, scrub real car/ball positions on a top-down pitch, inspect conservative review candidates, and compare the real trajectory with an **illustrative** goal-side support route. You can optionally ask Gemini to critique compact positional data. No video upload and no Google API quota are needed for ordinary replay viewing.

> **Status:** experimental. Tested with synthetic parsed replay fixtures, **not** yet verified end-to-end with a current real `.replay` in this environment. Findings are review prompts, not validated expert-level coaching, and dashed routes are illustrative, not simulated alternatives.

## Run locally (Windows)

1. Install Python 3.11+ if necessary, then open PowerShell in the `coach-app` folder.
2. Run:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python -m uvicorn coach_app.main:app --reload
   ```
3. Open `http://127.0.0.1:8000`. Press **Load demo** to try the interactive field, or drop in a native `.replay` file.

The parser uses RLGym Tools' `ParsedReplay.load`, which wraps the bundled `carball` decoder and produces player/ball position tables. The first native upload can require a few seconds while the replay is decoded.

**Optional Gemini:** Set the `GEMINI_API_KEY` environment variable **on the local server** before starting the app. Then use **Ask Gemini** inside the app, which sends time-sampled positional data (no raw replay file or account credential) to the Gemini API. Every click consumes API quota. The existing Cloudflare key is intentionally not copied into this app and the existing MCP Worker is unchanged.

## Security/privacy boundaries

- Native replay uploads are bounded at 20 MB and processed in a temporary folder that is removed after parsing.
- **Local-first**: parsed data is delivered back to your browser; no database or cloud replay retention in this MVP.
- The first-party `/api` endpoints have **no authentication**. This app must only bind to `127.0.0.1` for private development. **Do not publicly deploy the FastAPI server** without authentication, rate limits, CSRF/origin checks, upload hardening, and a bounded background job queue.
- Names/IDs in user replays may be present in positional JSON. Only click **Ask Gemini** if comfortable sending that data to Google's API.
- RLGym `carball` parsing is currently executed as a subprocess with its own runtime dependencies; treat uploaded files as untrusted, and sandbox parsers before making this public.

## Architecture

- `coach_app/replays.py` — native `.replay` → compact, time-sampled JSON. No AI cost.
- `coach_app/coaching.py` — low-confidence pattern flags and an illustrative offset/goal-side reference point. No AI cost.
- `coach_app/main.py` — local HTTP API and optional single-call Gemini position analysis.
- `coach_app/static/` — responsive interactive field SVG, replay timeline, actual trail, suggested route, observations.
- `tests/` — parser-normalization and conservative-coaching tests.

## Next milestones

1. Validate parser output against several real current-generation 2v2 replays. Fix any carball-version or metadata mismatches.
2. Add reliable map orientation, boost pad coordinates/pathfinding, teammate recovery context, and score/game-clock alignment.
3. Create a controlled evaluation set of expert-annotated decisions; score false positives, confidence calibration, and whether proposed routes are realistic.
4. Add signed-in accounts, R2 replay storage (opt-in), a background parse worker/container, per-user quotas and persistent findings. Keep raw replays private.
5. Add 3D/replay playback and optional video sync for fine mechanical review. Only add Claude or more models if evaluation shows independent review improves accuracy.

Reuse `rl-web`/`boxcars` for a browser-side WASM parser if avoiding a server becomes a priority; the current first cut is Python because RLGym Tools already provides extracted position columns. See [RLGym Tools](https://rlgym.org/RLGym%20Tools/introduction/) and [boxcars](https://github.com/nickbabcock/boxcars).

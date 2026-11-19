# Replay Lab Round 14 — integrated Windows owner acceptance

**Target:** [Draft integration PR #61](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/61), branch `integration/round14-final-owner-test-20261119`. This inherits the HD/coaching/V1/V2 owner-test baseline [PR #58](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/58), adds [ChatGPT's decision-time uncertainty panel #59](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/59), and [Claude's independent next-touch/danger-head attribution #60](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/60). **Do not switch to `main` or treat this as released.** Antigravity's separate Round 14 browser work is NOT yet included. The combined SHA must pass its own CI and real Windows owner review.

## Start the exact integrated build

From Windows Command Prompt at the **repository root**:

```cmd
git fetch origin
git switch integration/round14-final-owner-test-20261119
coach-app\start-windows.cmd
```

If this branch has not been checked out locally, use:

```cmd
git switch -c integration/round14-final-owner-test-20261119 --track origin/integration/round14-final-owner-test-20261119
```

The updated launcher requires **Python 3.12, Node.js 22+, npm**, installs Python dependencies, ensures HD node dependencies exist, and **rebuilds the current branch's HD bundle on EVERY start**, preventing stale assets left over from an older feature branch. It stops with a clear error if HD cannot build; it does not pretend a broken 3D renderer passed. Open `http://127.0.0.1:8000` only after the launcher prints its start message.

A real Rocket League `.replay` is uploaded to the **local FastAPI** `/api/replays` backend and parsed there with subtr-actor. The embedded HD player uses its own browser replay pipeline. A `.replay` is NOT video; native Rocket League is optional.

## One-replay automated backend acceptance

The command-line check routes one real decoded 2v2 through production local APIs: capabilities, model readiness, automatic shortlist, exact lesson parity, evidence lookup, pre-decision scene relations, manual-style episode and situation-aware report. It does **not** send native game commands or call a model without explicit `--model`:

```cmd
coach-app\round13-test-windows.cmd "C:\path\to\match.replay" 1
```

Replace `1` with the 1–4 **confirmed decoded roster slot**. Omit it only if the recording-player mapping is verified. The output intentionally includes **only statuses and counts**, not private player names, original paths or raw match frames. `api_structural_pass` does **not** establish accurate tactical coaching or working browser visuals.

## Strict browser interaction test (real replay required)

Antigravity's historical browser smoke script is preserved, but a NEW stricter test now refuses silent success when a report, manual review, blind completion or geometry request fails. In a **second Windows Command Prompt**, leave the Replay Lab server running in the first prompt, then use:

```cmd
set "REPLAY_LAB_REPLAY_PATH=C:\path\to\your_real_2v2_match.replay"
cd coach-app\high-fidelity
npm run test:owner-e2e
```

The script requires locally installed Chrome, Playwright and a **real replay path**. It verifies actual UI interactions, completed report cards, manual selection, blind Stage A/B and JSON export, model readiness/no-spend consent, spatial API, HD canvas existence and a bounded HD/map timestamp alignment. It does **not** infer coaching correctness, pixel-perfect textures or actual external-LLM performance from these checks. The screenshot `round13_strict_owner_local.png` remains on your PC and is not automatically uploaded. A missing replay is a hard failure, never replaced by a demo.

Any failed assertion is useful: preserve the error and replay-relative timestamp for the next iteration. You can override the local server address with `REPLAY_LAB_URL` and the local screenshot path with `REPLAY_LAB_SCREENSHOT`.

## Multiple replays — useful habits, not one-match anecdotes

The V2 browser panel intentionally evaluates **only the selected match**; it cannot establish reliable player habits from that match alone. Claude's separate command-line V2 report can combine multiple genuine 2v2 replays for the same player. From the project root on Windows:

```cmd
cd coach-app
.venv\Scripts\python.exe scripts\coach_replays_v2.py "C:\replays\match1.replay" "C:\replays\match2.replay" "C:\replays\match3.replay" "C:\replays\match4.replay" "C:\replays\match5.replay" --player "YOUR_EXACT_REPLAY_NAME" --md "v2_multi_match_report.md"
```

First run the script on one replay **without** `--player` if the exact decoded name is uncertain. Use at least five replays for a first look, but the code may still abstain on individual habits needing more samples. Keep the Markdown report and raw replay files **on your PC**. The percentiles describe a 15-match unknown-rank public reference, never GC2 correctness or a demonstrated mistake.

## Strict V2 browser acceptance

The `npm run test:owner-e2e` script now explicitly calls the **real** `/api/coach/coaching-report-v2` route and waits for the completed V2 sections, inspectable actual findings, and closed Stage B outcome drawers. A missing V2 server response is a failing test, not a silent fallback to V1. The real full-replay V2 statistical analysis may take over a minute. The browser test performs no external LLM calls and cannot establish expert tactical quality.

## Adversarial evidence tests

GitHub CI includes `test_round13_outcome_firewall.py`, which rewrites future events, ball/car trajectories, and misleading replay titles/scores at three decision cutoffs while requiring **identical** model-safe Stage 1 packets, local geometry and deterministic lesson judgments. This is a synthetic leak regression, not proof that every real model response is tactically correct.

## Round 14 live tactical challenge

Use `coach-app/docs/round14/OWNER_20_MIN_TACTICAL_AUDIT.md` for Gemini's **six hypothetical situation flips**, the quick V1-versus-V2 comparison, and exact fields to record when a claim is wrong. In the V2 Turning Points panel, look for **restraint/tradeoff/supports/hurts/negligible model-head readings**. They show separate next-touch versus predicted goal-danger score changes and are **not** causal or quality labels. Click **Challenge this reading** for uncertainty and source premises. If the old "your movement lowered the model score" appears instead, you are on an outdated branch/bundle.

## Manual owner test: mandatory functions

1. **Load and identify:** Upload one genuine ranked 2v2 `.replay`, confirm the player in **Who are we coaching?**, match duration and ball/teammate tracks. An identity warning must not be ignored.
2. **Render and navigate:** Test **HD + Map**, **HD 3D**, and **Tactical 2D** modes. Inspect authentic cars/wheels, stadium, ball movement, kickoff/demolition teleport boundaries, wall/aerial sequences, camera switching, boost and frame stepping. Check jump backward and forward; compare to the native Rocket League replay when possible.
3. **Moment discovery:** Select an actual coaching episode from **Coaching Review Moments**. The **Decision Lens** should show recorded `t0` conditions, not a declared mistake. Use **Decision t0**, **−3s Approach**, **Loop 5s scene** and **Reveal actual +2s**. Before reveal, actual future results must not be visible; after reveal they should be explicitly identified as *recorded* follow-through.
4. **Experimental situation report:** Open **Experimental situation-aware 2v2 report** and press **Analyze this match locally (experimental)**. Expect a completion status stating the number of source-checked findings and withheld/invalid findings; zero is a legitimate abstention and should be recorded as such. Review alternatives and assumptions; **What you did & recorded outcome** must initially be closed for each finding. These are local heuristic hypotheses, NOT external model-generated coaching.
4a. **Claude V2 experimental report:** Open **Round 13 V2 — Habits & turning points**. Press **Analyze this match with V2 (experimental)**. Expect three separate sections: descriptive habits (explicitly marked insufficient for rank-based inference from one match), retrospective team-control turning points including gains and losses, and decision-time observations with alternatives. Inspect the **Stage B: recorded action and later outcome** drawers: they must start closed, and old R12 mistake language must not appear as a verdict. Click a turning-point timestamp and verify the HD/2D clocks jump to it. V2 is NOT an external language model; its learned statistical control model is local and was trained on unknown-rank replays.
5. **Unflagged moment:** Move the replay slider to an interesting moment **with at least seven seconds of prior recorded history**. Open Decision Lens, click **Pin current frame**, then **Review this overlooked moment (local)**. Verify the status actually says **Manual source-backed episode created** and that the episode becomes selectable. A disabled button or a refusal is not a pass.
6. **Blind evaluation:** Select a source-backed *primary* decision, open **Blind Decision Review**, select prior outcome exposure, press **Start predecision review**, and confirm the AI and future controls disappear. Choose your action, teammate cover and confidence, click **Lock my predecision judgment**, and only THEN **Reveal actual recorded follow-through**. Separately rate the decision, execution and optional AI. Press **Save this review locally**; verify `1 completed`, then **Export session evaluation JSON**.
7. **Measured geometry:** With an eligible primary coaching decision selected, open **AI coaching proposals → Measured scene relationships**, click **Inspect source-backed geometry**. It must show local predecision measurements or a truthful reason for abstention, not a simulated outcome.
8. **Real AI model readiness:** Open **AI coaching proposals**, click **Check model configuration**. With no configured provider, the panel correctly says disabled/incomplete and will NOT generate actual model advice. Checking a consent box does not conjure a model. If a model is configured and separately approved, authorize ONE request and require an actual `model_proposal` with source-checked claims or an explicit failed/withheld result. Export local AI feedback. A mock transport test or no-spend readiness check is NOT real LLM acceptance.
9. **Round 13 HD features:** Optional 3D tactical overlays must start off, procedural audio muted; verify both opt-in controls. Check Broadcast Director/TV camera, normal car and ball cameras, 0.1× speed and frame stepping. Neither overlay nor audio should be forced during tactical analysis.
10. **Cross-view synchronization:** Seek to decision `t0`, kickoffs and goals, checking map clock and embedded HD clock on both **forward and backward seeks**. Compare the action frame to the timestamp, not merely a nonzero HD clock.
11. **Optional native game companion:** Only with explicit owner opt-in and a configured Stats API. A successful localhost port probe does NOT confirm that Rocket League loaded/seeks/changes POV. Native game video is not supplied to the standalone viewer.

## Optional ACTUAL source-backed LLM coaching configuration

The current model path is `GET /api/coach/model-readiness` and explicit `POST /api/coach/lesson` with `mode: "model"`, **not** `/api/model-coaching/config` and **not** a mere `GEMINI_API_KEY` check. The older optional Gemini game review route is a different legacy workflow.

There is no bundled model. To use an already installed and approved local OpenAI-compatible chat-completions provider, set these in the SAME Windows Command Prompt from which you start the app (example endpoint only):

```cmd
set "REPLAY_LAB_ENABLE_COACH_MODEL=1"
set "REPLAY_LAB_COACH_MODEL_URL=http://127.0.0.1:11434/v1/chat/completions"
set "REPLAY_LAB_COACH_MODEL_NAME=YOUR_ACTUALLY_INSTALLED_MODEL"
coach-app\start-windows.cmd
```

You must independently run the corresponding model service, verify its endpoint and installed name, and confirm it supports the strict `CoachDraftV0` JSON response. A remote HTTPS-compatible service additionally requires `REPLAY_LAB_COACH_MODEL_API_KEY` set **privately in the environment**; do not paste it in chat, browser, GitHub or any test report. Remote calls can cost money and transmit sanitized decision evidence to the approved provider. The model UI separately asks for **consent once per call**. Source validation is necessary, not sufficient for expert tactical correctness.

See `coach-app/docs/round12b/ACTUAL_MODEL_COACHING_UI.md` for existing validated provider contract and limitations.

## Strict test standards and discrepancy capture

The earlier Antigravity Round 13 browser script genuinely exercised several local UI journeys and captured a screenshot, but its report/manual/blind/AI steps sometimes only logged a status without asserting full success. It does **not** prove genuine model inference. Use strict browser checks plus this real Windows walkthrough before declaring acceptance. Human review is required.

For every failed or unfairly criticized moment record **replay-relative t0**, selected player, what the viewer showed, what the app claimed, why it is factually/tactically wrong, and an alternative defensible play. Keep private replay files and account IDs **local**; use the anonymized feedback JSON exports. Inspect at least one good aggressive play, one good defensive delay, one questionable challenge, and one meaningful moment the automatic detector missed.

Do not merge into `main` until the **exact final combined commit** has all three GitHub workflows green, one real Windows replay passes the key end-to-end gates, and optional model/native-game features are honestly reported as working or unverified. Claude's completed Round 13 V2 branch is present in PR #58. Re-run all checks on the **exact latest PR #58 commit** after any additional browser edits, then perform the Windows owner test.

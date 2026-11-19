# Replay Lab Round 13 — unified Windows owner acceptance

**Target:** [Draft integration PR #55](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/55), branch `integration/round13-complete-owner-test-20261118`. Based on Antigravity [PR #53](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/53) and ChatGPT [PR #54](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/54). **Do not use `main` or claim this is released.** Claude's ongoing tactical branch is NOT included until independently reviewed.

## Start the exact integrated build

From Windows Command Prompt at the **repository root**:

```cmd
git fetch origin
git switch integration/round13-complete-owner-test-20261118
coach-app\start-windows.cmd
```

If this branch has not been checked out locally, use:

```cmd
git switch -c integration/round13-complete-owner-test-20261118 --track origin/integration/round13-complete-owner-test-20261118
```

The updated launcher requires **Python 3.12, Node.js 22+, npm**, installs Python dependencies, ensures HD node dependencies exist, and **rebuilds the current branch's HD bundle on EVERY start**, preventing stale assets left over from an older feature branch. It stops with a clear error if HD cannot build; it does not pretend a broken 3D renderer passed. Open `http://127.0.0.1:8000` only after the launcher prints its start message.

A real Rocket League `.replay` is uploaded to the **local FastAPI** `/api/replays` backend and parsed there with subtr-actor. The embedded HD player uses its own browser replay pipeline. A `.replay` is NOT video; native Rocket League is optional.

## One-replay automated backend acceptance

The command-line check routes one real decoded 2v2 through production local APIs: capabilities, model readiness, automatic shortlist, exact lesson parity, evidence lookup, pre-decision scene relations, manual-style episode and situation-aware report. It does **not** send native game commands or call a model without explicit `--model`:

```cmd
coach-app\round13-test-windows.cmd "C:\path\to\match.replay" 1
```

Replace `1` with the 1–4 **confirmed decoded roster slot**. Omit it only if the recording-player mapping is verified. The output intentionally includes **only statuses and counts**, not private player names, original paths or raw match frames. `api_structural_pass` does **not** establish accurate tactical coaching or working browser visuals.

## Manual owner test: mandatory functions

1. **Load and identify:** Upload one genuine ranked 2v2 `.replay`, confirm the player in **Who are we coaching?**, match duration and ball/teammate tracks. An identity warning must not be ignored.
2. **Render and navigate:** Test **HD + Map**, **HD 3D**, and **Tactical 2D** modes. Inspect authentic cars/wheels, stadium, ball movement, kickoff/demolition teleport boundaries, wall/aerial sequences, camera switching, boost and frame stepping. Check jump backward and forward; compare to the native Rocket League replay when possible.
3. **Moment discovery:** Select an actual coaching episode from **Coaching Review Moments**. The **Decision Lens** should show recorded `t0` conditions, not a declared mistake. Use **Decision t0**, **−3s Approach**, **Loop 5s scene** and **Reveal actual +2s**. Before reveal, actual future results must not be visible; after reveal they should be explicitly identified as *recorded* follow-through.
4. **Experimental situation report:** Open **Experimental situation-aware 2v2 report** and press **Analyze this match locally (experimental)**. Expect a completion status stating the number of source-checked findings and withheld/invalid findings; zero is a legitimate abstention and should be recorded as such. Review alternatives and assumptions; **What you did & recorded outcome** must initially be closed for each finding. These are local heuristic hypotheses, NOT external model-generated coaching.
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

Do not merge into `main` until the **exact final combined commit** has all three GitHub workflows green, one real Windows replay passes the key end-to-end gates, and optional model/native-game features are honestly reported as working or unverified. After Claude's new branch arrives, integrate it deliberately and **re-run all checks**.

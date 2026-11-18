# Round 12 Antigravity handoff — integration review and native/HD acceptance gates

**Status:** 18 November 2026. This is an independently inspected handoff and
test-readiness improvement, not an Antigravity-authored engineering report or
proof of verified native Rocket League control.

## Source and branch graph

- Antigravity pushed `feature/round12-hd-replay-native-companion-coaching-20261118`,
  original delivery head `21dda2c`. Reviewed as **draft PR #43**, stacked on
  Round 11 ChatGPT review-bundle PR #39 (`b2d0e66`).
- This additive follow-up branch
  `feature/round12-native-load-hd-acceptance-gates-20261118`
  is stacked on Antigravity's `21dda2c` to avoid rewriting its working
  frontend while it is being reviewed.
- **Not integrated:** ChatGPT model-readiness/real-provider acceptance PR #41,
  independent HD camera/tire shader fix PR #42, Claude Round 11 tactical
  falsification PR #40 and Claude's pending Round 12 tactical output.
- Canonical decisions and full agent handoff live in
  `docs/replay-lab-project-compass.md` on the separate documentation PR #25.
  All PRs remain drafts. There is **no permission to merge to main**.

## Verified from current source versus agent-reported

| Feature | Actual evidence | Do not claim |
|---|---|---|
| 2D + HD + split mode | HTML tabs, a same-origin HD iframe and bridge code are present. Basic geometric 3D elements removed from active HTML. | That every real replay already renders with correct 3D cameras, car models and materials |
| Deterministic source-backed coaching | Browser client calls `/api/coach/review-bundle` after verified player selection and can display real `CoachLessonV0` previews; synthetic fallback is not used for failures. | That the highlighted moments are validated mistakes or expert tactical recommendations |
| Browser automation | Antigravity reports an E2E pass using a private genuine 2v2 fixture. Script asserts page, iframe element, map element, upload, selected player, review moments, feedback and seek button. PNG `round12_live_coaching_browser_verified.png` is in the branch. | That original E2E asserted successful HD WebGL canvas, nonfallback stadium GLB assets, correct pixel rendering, or native game control |
| Model | PR #39 provides deterministic backend lessons; optional model code exists elsewhere in the coach lineage. | That a real LLM is configured or produced a useful coaching recommendation in this Round 12 browser test |
| Native game | New `GET /api/companion/status` checks loopback ports; `POST /api/companion/command` is server gated by `REPLAY_LAB_ENABLE_NATIVE_COMMANDS=1` and validates supported commands. | That an open port authenticates Rocket League, that commands were executed, or that the game window has been captured/streamed |
| Test suite | Antigravity reports **387 passed, 4 skipped** in local pytest and **18 passed** in Node. | Those exact counts as independently rerun GitHub CI evidence until an exact-head workflow exists |

The user requires complete *test readiness* rather than overclaiming a
production build. The screenshot alone is not enough to prove HD 3D scene
correctness. Missing `coach-app/coach_app/static/hd-player` is expected in
source: it is locally compiled from the pinned npm package, not committed.

## Specific gaps fixed in this follow-up

1. **Actual native Replay Load control.** Antigravity's initial UI could
   seek a replay already open in the game, but offered no `LoadReplay`
   action. We added a bounded, manually typed **game-local** replay filename
   or path and an explicit Load Replay button. A browser `File` input does
   not supply a trustworthy filesystem path; we never silently infer it
   from the replay name or upload the original bytes into the game.
2. **Match confirmation.** Sending `LoadReplay` returns **transmitted**,
   not **game accepted**. It always clears manual match confirmation.
   The separate `Seek Game to Playhead` button requires a real local
   replay, explicit browser opt-in, an observed TCP command port and a
   human-confirmed identical replay open in Rocket League. Every new
   browser replay invalidates that match confirmation.
3. **TCP versus WebSocket ports.** Official TCP port 49123 is the only
   implemented command transport; WebSocket port 49124 is currently
   probe-only. `CompanionStatus` reports them separately and explicitly
   marks game identity/control as **unverified**. A WebSocket-only port
   does not activate command buttons.
4. **Privacy.** Native command results are no longer logged to the browser
   console with their user-supplied replay path. UI status is deliberately
   limited to transmitted/failed and never includes the path. A previously
   hard-coded private Steam ID in the replay integration test is replaced
   with selection from the decoded roster.
5. **No false-positive HD E2E.** The Playwright test now requires a
   visible actual WebGL canvas inside the iframe, the HD viewer's loaded
   nonfallback multi-mesh stadium status, and a nonzero embedded HD clock
   after a coaching seek. A missing local HD build or a setup-placeholder
   iframe will **fail** rather than yield a misleading screenshot pass.

These are code/testing improvements. No real Windows Rocket League client
was controlled, no config file was edited, and no model provider was billed
by this branch.

## Test and setup checklist — next user Windows acceptance

### Standalone 2D/HD

1. Install/build the pinned local HD player via
   `coach-app/setup-high-fidelity.cmd` after confirming Node 22+.
2. Run `coach-app/start-windows.cmd` (Python 3.12 local app), open
   `http://127.0.0.1:8000`, and upload a real user-owned 2v2 `.replay`.
3. Choose the **actual** coached player. Ensure candidate highlights are
   real source-checked observations, not fixture demos.
4. Switch HD / 2D / HD+Map and confirm same player at same timestamp.
5. Check pitch/roll, wall/aerial contact, goal reset, demolition/respawn,
   Ball Cam switches, smooth chase angle, vehicle texture/wheels and
   tire/boost trails. Record exact replay-local times privately.
6. Click review lead, jump to decision, inspect evidence, submit honest
   feedback and export private local test report.

For full browser E2E, run the local server at the test's configured port
**8085** and provide the private source fixture at
`coach-app/fixtures/replays/real_match_2v2.replay` **locally**. The fixture is
not committed; code-hosted CI may skip that real replay test. Run
`node high-fidelity/test/browser-round12-e2e.mjs` from `coach-app` after
installing dependencies, Chrome/Playwright and the HD bundle. The strict test
will fail if HD assets or WebGL setup are missing.

### Optional native installed Rocket League

1. Native commands are **off by default**. The user decides whether to
   enable the server-side environment opt-in before launching the local app:
   `REPLAY_LAB_ENABLE_NATIVE_COMMANDS=1`. The browser checkbox is a second,
   separate opt-in. Do not edit game INI or run any commands automatically.
2. Independently configure the game-side official Stats API only with
   explicit permission and inspect its actual version-specific instructions.
3. Probe loopback TCP 49123. A port seen is **not** an authenticated game.
   WebSocket 49124 alone cannot carry current command JSON.
4. Explicitly enter the replay **filename known to Rocket League** or a
   **local absolute file path accessible to the game process**, and click
   **Load Replay in Rocket League**. Do not assume the browser-uploaded
   file name resolves to the game-visible path.
5. Observe the actual running Rocket League window. Only after confirming
   the identical replay is active, tick the **same replay confirmed** box.
6. Seek to a known ball touch/goal from Replay Lab. Compare the **actual
   native game playhead** and chosen player POV. Repeat at early and late
   match timestamps, record drift and any execution failures.
7. Native LoadReplay/SeekReplay command transmission alone is
   **insufficient for acceptance**. Player-camera native POV, speed and
   pause require separate observed/verified tests; the API does not
   transport video into the browser.

### AI coaching — still separate

- Integrate PR #41's model readiness and explicit `mode:"model"` logic
  before claiming a real-provider demonstration. Its localhost stub
  verified the HTTP contract, not real AI tactical quality.
- Await Claude's Round 12 tactical improvements; don't silently turn
  uncalibrated V1 judgment into validated advice.
- For human coaching assessment, test good decisions, poor decisions with
  good outcomes, alternative challenge/shadow cases, and cases where
  teammate coverage is unknowable. Record false blame and actionable value.

## Privacy/security

- Local loopback app has no user authentication; **do not expose it to a
  public network, reverse proxy or internet tunnel**.
- The user-uploaded real `.replay`, local replay filename/path and
  screenshot footage should stay on the user's machine unless the owner
  explicitly authorizes sharing. No account IDs, raw replay bytes,
  personal player names, or provider secrets in new public docs.
- The existing public screenshot and older fixture-name references should
  be reviewed before any public release for player identity leakage.
- The local test report should avoid reuploading identities by default.
- Nothing here establishes high-rank strategic coaching merit.

**Next owner-approved phase:** one more major development/integration round
after current Round 12, then full user-side tests of all visualization
paths, native-game control and actual coaching suggestions.

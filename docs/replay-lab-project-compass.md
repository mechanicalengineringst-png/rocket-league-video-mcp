# Replay Lab — Project Compass (read first)

## CURRENT OPERATIONAL HANDOFF — 18 November 2026 / Round 12B

**READ THIS SECTION FIRST; older entries below are historical and may
contradict the current code.** GitHub PR heads and exact CI checks outrank
status summaries. This is a user-approved design/engineering handoff, not a
claim that the product has passed real-browser, real-game, or expert testing.

### Binding owner decisions

- **Primary product:** excellent, substantive, situation-specific Rocket
  League **2v2 coaching**, eventually useful to experienced GC/SSL players.
  Deep alternatives, first/second-man tradeoffs, possession, pressure,
  boost/recovery, teammate coverage and uncertainty matter. Positive plays
  matter as much as mistakes. Winning/losing a challenge is NOT proof the
  choice was good/bad. User's illustrative hard benchmark is a challenge
  near an opponent's backboard: consider follow-up possession after winning
  the contest, exposing teammate to a 1v2, opponent outplay options, recovery
  and shadow/delay tradeoffs. Do not fabricate a specific replay finding.
- **AI style:** strong coaching **recommendations**, not a chat-first product.
  A conversational LLM interface is optional. Several highly useful,
  falsifiable lessons beat dozens of generic flags. Use deterministic
  source evidence + conditionally justified model proposals; require expert
  feedback before calling the recommendations accurate.
- **Three user-facing replay modes only:** high-fidelity standalone Rocket
  League recreation; small 2D tactical pitch; synchronized HD+2D split view.
  The basic geometric 3D mode is **retired** (do not preserve as an option or
  split-view fallback). PR #24 contains the earlier actual HD-first UI; the
  Antigravity PR #43 removed it from the active coaching UI. PR #47
  now integrates PR #41 model transport/readiness into that frontend.
  PR #42 camera/trails remain separate pending Antigravity's HD improvements.
- **Develop BOTH visual backends:** (1) standalone, independent HD WebGL/WASM
  renderer with native-replay camera states where available and (2) optional
  native installed Rocket League replay companion via documented Stats API.
  The latter is NOT a video stream from the API. Game-process integration,
  configuration and capture must be tested only with owner's explicit
  permission. The HD viewer must work without installing/running the game.
- **Development/test cadence:** finish the current Round 12, allow **one
  additional development/integration round**, then user tests all components:
  actual ranked replays, HD/2D/split, native game loading/seek/player POV,
  real opt-in model suggestions, false blame, visuals and usability. Capture
  feedback as structured cases; targeted refinements follow actual evidence.
- **Collaboration:** Claude leads tactical backend, Antigravity leads
  frontend/HD/native companion, ChatGPT leads API/model transport, safety,
  integration review and independent HD QA. Gemini paused due to usage and
  not required for this round. Each agent makes a separate draft PR and
  shares exact SHA/test output; **NO unreviewed merges to main**.

### Current integration graph and verified statuses

1. [PR #35](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/35)
   Round 9 coaching UI + verified backend, baseline for the latest coach
   lineage. UI has fixture demos; source-backed production behavior needs
   browser acceptance.
2. [PR #38](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/38)
   combines ChatGPT observational episode discovery and Claude's opt-in
   TacticalDecisionStateV1 on PR #35; head `97eba07`, 352 passed/4 skipped,
   all 3 workflows green. V1 tactical merit is NOT expert-validated.
3. [PR #39](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/39)
   one-call stateless `/api/coach/review-bundle`: actual source-backed
   candidate shortlist + <=4 lesson previews, no LLM, no fake fallback.
   Head `b2d0e66`, 369 passed/4 skipped, 3 workflows green.
4. [PR #41](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/41)
   **earlier ChatGPT coaching/testing branch**, stacked on #39.
   `/api/coach/model-readiness` no-network provider preflight,
   `round12-test-windows.cmd`, `scripts/round12_acceptance.py`,
   opt-in **one** sanitized real-model request, read-only native TCP port
   probe and privacy-safe diagnostics. Tested local HTTP provider stub,
   **NOT a real trained model or GC coaching quality**. Head `1152a5d`,
   **392 passed/4 skipped**, all 3 workflows green. The API, provider
   transport, Windows acceptance runner and tests have now been carried
   into integrated UI PR #47, so don't independently reapply PR #41
   over newer frontend code.
5. [PR #40](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/40)
   **Claude independent Round 11 tactical/evaluation branch** from #38,
   head `f05f73e`, 3 workflows green. Falsified a fixed 0.55 s V1 reach
   margin; introduced condition-based `ActionRationaleV0`, a blind expert
   study harness and unknown-aware options. **No real human expert ratings**.
   Claude's **draft Round 12 PR #45** is now published separately with
   `CoachingReportV1` (situation-aware two-stage coaching, experimental
   opt-in). Its draft currently says that cohort evaluation is still
   running; do not assume expert-validated coaching or merge it early.
6. [PR #24](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/24)
   is the **separate HD-first 2D + standalone 3D + split UI** lineage.
   Its viewer uses `@rlrml/player`, `@rlrml/subtr-actor`, Three.js,
   WebAssembly, camera polishing/switch telemetry and reversible FX.
   **This frontend is NOT yet merged with #41's coaching stack.**
7. [PR #42](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/42)
   is ChatGPT's **separate Round 12 HD camera QA patch stacked on #24**.
   Indexes recorded Ball/Car Cam, rear view and other camera events once
   with O(log n) seeks instead of per-frame rescans, adds large-history
   tests. **Also fixes an upstream-confirmed SupersonicTrailV2 shader
   mismatch**: the previous soft trail patch targeted textured ribbons,
   while actual tires use an untextured shader; added reversible soft-edge
   shading and tests of the actual shader shape. User-reported issues and
   visual QA matrix:
   `coach-app/high-fidelity/docs/ROUND12_CAMERA_AND_VISUAL_ACCEPTANCE.md`.
   **Actual real-replay shader/visual comparison remains unverified.**
   Do not overwrite Antigravity's working frontend; cherry-pick selectively.
8. [PR #43](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/43)
   **Antigravity's delivered Round 12 unified frontend**, original head
   `21dda2c`, stacked on #39. Removes geometric 3D from the active view;
   supports HD/2D/split (default), `CoachReviewBundleV0` source-backed
   review leads, coaching navigation, tester feedback/export and opt-in
   local native game command backend. Original GitHub general CI, Replay
   Coach MVP and Replay Viewer 3D checks passed. Antigravity reports
   local real-2v2 Playwright upload/review/feedback/screenshot, but the
   original E2E asserts an iframe's **presence**, not its loaded WebGL
   canvas or correct stadium/vehicle. No running-game native commands or
   real AI provider coaching verified. The referenced original Round 12
   Engineering Report was not in the delivered GitHub tree.
9. [PR #44](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/44)
   ChatGPT's **additive native-game and HD acceptance hardening patch**
   stacked on Antigravity #43, not `main`. Adds game-local
   `LoadReplay` UI with user-supplied file name/path, explicit same-match
   confirmation before Seek, accurate TCP-command vs probe-only WebSocket
   port readiness, privacy-safe command status, and removes hard-coded
   player ID from a public test. New E2E requires a **real loaded HD
   WebGL canvas + stadium meshes + nonzero synchronized time**, not a
   mere iframe DOM node. Integration review and honest acceptance matrix:
   `coach-app/docs/round12/INTEGRATION_REVIEW_AND_NATIVE_HD_TEST_GATES.md`
   on #44. **Exact head `2f051ff`: 380 passed / 13 skipped in Replay
   Coach MVP, general CI and Replay Viewer 3D passed.** The higher skipped
   count reflects absent private native replay fixture paths in CI;
   GitHub green does NOT mean browser-HD or live-game acceptance.
10. [PR #46](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/46)
   **ChatGPT's substantive Round 12 Decision Lens V0 workspace**, stacked
   on #44 (#43 -> #44 -> #46), exact head `4d83862`. Uses an
   independently tested decision-time **floor sample (<=t0)** to show
   recorded focus/teammate/opponent/ball positions, horizontal distances,
   boost, ball Z and speed; one-click predecision approach and **bounded
   5-second HD+2D loop**; separately reveals **actual** postdecision
   car/ball trails/ghosts, with no invented alternative or gameplay grade.
   Selecting a source-backed coaching node pins t0; manual pin is supported.
   **CI VERIFIED:** 381 passed/13 skipped Python tests; **19/19 Node
   camera/geometry/Decision Lens tests**; all three GitHub workflows green.
   Enhanced Playwright HD+2D real replay checks exist but **not run on an
   owner Windows replay here**; no native game acceptance. Full docs:
   `coach-app/docs/round12/DECISION_LENS_V0.md` on PR #46.
   This is actual user-facing UX, not proof of high-rank coaching quality.
11. [PR #47](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/47)
   **ChatGPT's substantial Round 12B actual AI-model coaching UI**, head
   `09d6044e`, stacked on #46 (#43 -> #44 -> #46 -> #47).
   Fixed a previously broken one-call review-bundle-to-episode mapping:
   each lesson now carries EXACT audited
   `decision_times`, `episode_start_s`, and `primary_t0`, rather
   than the invalid outer review-bundle request. Users can now select a
   real primary decision, check local model configuration, explicitly
   authorize ONE model request, see only accepted source-cited
   `model_proposal` statements, inspect original sources locally,
   rate useful/incorrect/missing-context, and export feedback locally.
   No conversational chatbot, no automatic spend or fabricated fallback.
   Merges all compatible provider readiness/JSON parsing, Windows
   native-replay test runner and real local HTTP model-stub checks
   previously in #41. **Exact head verified:** **405 Python passed /
   13 skipped**, **25/25 Node viewer/Decision Lens/model-UI tests**,
   all 3 GitHub workflows green. No real paid/local trained provider
   tested; source checks DO NOT verify strategic quality. Docs:
   `coach-app/docs/round12b/ACTUAL_MODEL_COACHING_UI.md`
   on #47. Keep this coaching UI branch as frontend baseline when
   Antigravity advances HD on its separate branch.
12. [PR #48](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/48)
   **ChatGPT's Round 12C actual missed-moment coaching feature**, stacked
   on #47 (#43 -> #44 -> #46 -> #47 -> #48). Adds a
   **Review this overlooked moment (local)** action in Decision Lens:
   user explicitly pins any real 2v2 moment, the browser constructs
   a verified 5–20s predecision 3-node EpisodeEvidenceV0 request from
   actual <=t0 recorded samples (200ms freshness; never invented
   touches/choices), and the existing local /api/coach/lesson constructs
   a deterministic source-backed review episode. That episode is
   **OWNER-SELECTED / NOT A CONFIRMED MISTAKE** and remains distinct
   from the automated shortlist even if asynchronous discovery arrives.
   The user can THEN separately authorize an opt-in model proposal from
   PR #47, enabling actual testing of **missed situations** rather than
   merely rating what the detector chose. No automatic provider call.
   Report exports now distinguish manually selected vs automatically
   discovered review moments without calling the former confirmed
   detector errors. New JS, HTTP and Stage1 future-leakage regressions.
   Technical specs and honest acceptance tests:
   `coach-app/docs/round12c/MANUAL_MISSED_MOMENT_REVIEW.md`.
   **CI VERIFIED on exact head `9c9fb628`: 409 Python tests passed /
   13 skipped, 32/32 JavaScript viewer/Decision Lens/model/manual-review
   tests, and all 3 GitHub workflows successful.** Missing private replay
   fixtures explain some skips; no actual ranked replay/live native
   game or real AI provider has been accepted.
13. [PR #49](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/49)
   **ChatGPT's Round 12D grounded spatial intelligence**, stacked
   on #48 (#43 -> #44 -> #46 -> #47 -> #48 -> #49). Based on Gemini's
   Nov 18 independent research, adds `RelationalInvariantsV0`
   from strictly predecision `Stage1EpisodePacketV0`: source-linked
   blue/orange **goalward longitudinal ordering**, 2D ball/player
   distances, teammate separation and nose-to-ball angle. Each metric
   uses original N#/E. evidence, has explicit caveats and abstains
   on missing/stale data. **Not** possession, safety, turn feasibility,
   inferred good/bad choice or counterfactual outcome. Adds a **free
   local** `POST /api/coach/scene-relations` API and an on-demand
   measured-relations inspector inside the existing model coaching
   panel with original evidence clickthrough. Model prompts now also
   receive `scene_relations` generated from the same audited Stage1
   packet, with explicit constraints not to quote derived numbers
   unsupported by the original typed predicate verifier. No additional
   provider call, cost, raw replay upload or experimental V1 input.
   New Python spatial polarity/future-leakage/API tests, HTTP model
   transport contract check and JS no-cost/stale-player tests.
   **CI VERIFIED on exact head `4093fafa`: 417 Python passed /
   13 skipped / 1 warning, 34/34 JavaScript tests and all three GitHub
   workflows green.** No actual trained-provider or owner-replay
   strategic merit verification.
   `coach-app/docs/round12d/RELATIONAL_INVARIANTS_V0.md` on PR #49.
   Gemini's full recovery-debt/2-ply numeric thresholds and native PLL
   claims are **research hypotheses not yet API/physics validated**;
   Claude/Antigravity must not adopt them as verified verdicts or
   game commands without evidence and real-game QA.
14. [PR #50](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/50)
   **ChatGPT's substantive Round 12E independent blind two-stage
   human review workflow**, stacked on #49 (#43 -> #44 -> #46 ->
   #47 -> #48 -> #49 -> #50), head `d13da11c`.
   The user selects an actual primary replay episode, self-reports
   prior outcome exposure, then starts Stage A: HD+2D parent timeline
   capped at t0, future reveal/loop buttons and normal coaching/AI
   panels temporarily hidden, existing AI results masked and any
   additional model call blocked. User must lock **intended action,
   teammate-coverage interpretation, confidence and optional rationale**
   BEFORE Stage B unlocks. Stage B explicitly reveals the RECORDED
   outcome and separately collects **decision merit, mechanical execution
   and AI recommendation quality** (including false criticism).
   No action forecasts or implicit model calls. Completed/in-progress
   locked trials export as anonymized local
   `ReplayLabBlindReviewReportV0` JSON: match indices only, no replay
   names, player IDs, raw frames, model prompts or credentials.
   Unlocked unfinished attempts excluded. Tool is an **in-app controlled
   viewing aid**, NOT proof that the reviewer never saw the play before,
   or that an external native Rocket League window was hidden.
   **CI VERIFIED on exact head `d13da11c`: 418 Python passed /
   13 skipped / 1 warning; 44/44 JavaScript tests including actual
   model-result masking and playback-state integration; all three
   GitHub workflows passed.** Real private ranked replay, real model
   inference, HD render QA and native Rocket League remain unverified.
   Source: `coach-app/docs/round12e/BLIND_TWO_STAGE_EVAL.md`
   on PR #50. Gemini has been tasked with **24 hypothetical
   adversarial 2v2 cases and at least 8 context-flip pairs** with a
   blind-scoring rubric; Gemini output is pending, not merged code.
15. [PR #45](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/45)
   **Claude's Round 12 tactical intelligence PR**, head `619914f`,
   stacked on Claude's earlier #40. Introduces an experimental,
   opt-in situation-aware `CoachingReportV1` with two-stage findings.
   Claude's PR body states its real replay cohort evaluation is still
   in progress, so its integration and empirical merit are **pending**.
   Do not confuse this tactic backend branch with the HD UI branch.
16. [PR #28](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/28)
   Earlier native Stats API companion, independently drafted. Real
   Rocket League loading/seek/POV/pause/speed **NOT verified in a live
   running game**. Antigravity #43 provides another implementation;
   reconcile after source review and real game acceptance. A listening
   port is not game authentication; actual Windows game testing requires
   owner's explicit permission.
17. [PR #25](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/25)
   is this canonical project compass. It remains a separate docs-only
   draft; future sessions should read the linked branch version rather than
   assume this file is already on `main`.

### Real HD viewer defects reported by the owner — still require fresh QA

- **Camera:** low, tire-level chase/POV; odd roll/jitter, sometimes wrong
  player-follow; perceived permanent Ball Cam ON; want recorded Car/Ball Cam
  toggles, distinct free/orbit, stable aerial/wall/backboard framing.
- **Rendering:** blue block-style vehicle, asset/decals and low-quality
  textures, blocky tire/supersonic/boost trails, wheel-ground contact,
  demolition/goal/respawn transitions; missing or confusing boost display.
- **UX:** prior 2D clutter/trails/rings/TOUCH labels and too many generic
  findings; compact 2D boost/position map and **actual HD** for mechanics.
- **Status:** PR #24 includes partial camera, quality and UI changes. PR #42
  makes camera-state lookup cheaper/deterministic and corrects the actual
  untextured tire-ribbon shader path previously ignored by the Soft setting.
  Neither green JS tests nor a built Vite bundle prove the underlying 3D
  visuals are fixed.
  Capture actual before/after real-replay screenshots/short clips, report
  defects and preserve footage privately. **Do not claim pixel-native
  camera fidelity when analog inputs are unavailable.**

### Immediate next integration/test plan (one more round before owner testing)

1. Antigravity's Round 12 work is published as PR #43. Review its
   native / HD QA follow-up PR #44, verify CI, and preserve the real
   native replay load and strict WebGL/asset readiness tests.
2. Review Claude's larger Round 12 backend and integrate only supported
   tactical contracts; V1 unvalidated grading stays opt-in.
3. Build the final unified **draft integration branch** from #50,
   which now contains #43, #44, #46, #47, #48, #49 and compatible model
   acceptance from #41. Preserve the blind review parent timeline
   cutoff, masking of any preexisting AI result and separate Stage
   A/B export, manual overlooked moments, model one-call consent and
   RelationalInvariantsV0. Integrate Claude's tactical #45 after
   evaluation and Antigravity's HD/native improvements (including
   safe camera/trail fixes from #42). Do not revert newer app.js,
   model-coaching.js, coaching-experience.js or the HD clock guard to
   older ancestors. No `main` merge.
4. Browser-test on an actual **native .replay file**: replay/player
   confirmation, 2D, actual HD geometry/textures/camera/boost/trails,
   split sync, source-backed shortlist, lesson->seek, evidence, model
   opt-in and saved feedback. Fixtures are demonstration-only.
5. Separately test optional native Rocket League control **with explicit
   owner opt-in** on Windows: actual replay load, seek, matching player POV,
   pause/speed, telemetry/state confirmations and any manual-only steps.
6. Prepare 3–5 of the user's ranked 2v2 replays for substantive assessment:
   a few deep positive/negative/ambiguous cases and source citations,
   measured false blame, usefulness and unknowns. Do NOT infer tactical
   quality from green CI, unknown-rank public replay correlations or a
   mocked model server.
7. Update this section and the PR comments after **every material branch
   handoff, integration, failure or human decision**. Public GitHub should
   contain only non-private decision records and code, no raw replay data,
   secrets or user identifying local paths. The detailed older history
   continues below.

---

**Historical status snapshot: 17 November 2026 (see current operational handoff above).** **Source of truth for product direction and active work.** Keep this file short and updated after material decisions, tests, and PR changes. It is **not** a transcript archive; exact GitHub code/CI is the authority for implementation claims.

**Detailed historical record:** [Google Drive master handoff](https://docs.google.com/document/d/12OuLwWCDxprVzGSnQVWJ6vvIQ_SujJAOqNn3_FBF-Q0/edit). The older [AI team onboarding](AI_TEAM_ONBOARDING.md) is historical and no longer current. **All new ChatGPT/Claude/Antigravity sessions must read this compass, then check current PR heads, before proposing work.**

**Round 6 multi-agent strategic meeting (Gemini + Claude + Antigravity + ChatGPT):** [Read the synthesized findings, corrected overclaims, and proposed 12-case/native-API evidence gates](REPLAY_LAB_ROUND6_CROSS_AGENT_STRATEGY_REVIEW.md). This memo is PRELIMINARY, not permission to modify the game, train models, upload replays or merge code. Antigravity's docs-only native architecture report is linked there.

**Round 6 independent research (ChatGPT, research-only):** [Initial architecture/evidence report](REPLAY_LAB_ROUND6_INDEPENDENT_RESEARCH.md) and [Deep-dive addendum: replicar v2, human observability, existing viewer options, high-rank data and models](REPLAY_LAB_ROUND6_DEEP_DIVE_ADDENDUM.md). Findings requiring other-agent review: selected-moment Gemini prompt presently samples the whole match rather than its named decision window; a published curated 2v2 replay dataset reports 49,658 matches (actual file quality and rights unverified); existing possession/xG/goal-hazard code might help with grounded tactical features; run small expert-blinded side-by-side tests BEFORE investing in local LLM training. **No architecture chosen or code implemented by this report.**

## Round 7 — live agent handoff (17–18 November 2026)

- **Claude completed a focused DecisionEvidenceV0** on [PR #22](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/22), commit `5dc35d1`. Module: `coach-app/coach_app/decision_evidence.py`; handoff: `coach-app/docs/round5/05_DECISION_EVIDENCE_V0.md`. Contains t0 state, sample-age/provenance flags, reachability, role/cover estimates, pre-t0 context, stable E./C./U. evidence refs and a *separate* retrospective R. block. Claude reports **204 passed, 4 skipped**, and 636/636 predecision evidence records invariant to deleting future frames on its 15-replay unknown-rank cohort. Reported by Claude; no expert tactical-merit validation.
- **ChatGPT completed a narrowly scoped selected-time evidence fix** in [draft PR #26](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/26), stacked on PR #24, head `f42d0fb`. The previous optional Gemini review prompt falsely described a ±3s selected window while sending a stride across the *whole match*. This draft now sends only observed samples from [t0−3s,t0], includes the most recent sample, abstains when no sampled frame falls within 150ms of selected t0, retains anonymized aliases and adds mocked-payload and future-invariance tests. **CI checkpoint:** Replay Coach MVP, Replay Viewer 3D, and general CI GitHub checks passed for PR #26; HD browser preview was still running at this checkpoint. No manual Windows gameplay test or expert tactical-validity test. Legacy endpoint remains one-hypothesis prototype, not new tool-using reasoning architecture.
- **Antigravity's native Stats API PR #20 is not live verified** in the current GitHub record; Round 6 native integration research is in [its docs-only branch](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/blob/docs/native-game-integration-and-visualization-architecture-20261117/docs/research/NATIVE_GAME_INTEGRATION_AND_VISUALIZATION_ARCHITECTURE.md). Configuration/permission and actual Windows game tests are still needed. No assumption that a closed-game port probe or syntax test counts as real replay control.
- **Gemini's Round 7 specification has been delivered** as an owner-provided Markdown attachment (design only, NOT GitHub code), proposing episode reasoning, two-stage pre-/post-decision separation, cited claims, synthetic examples and expert review. **Reviewed against Claude's actual PR #22 implementation** in [Round 7 integration gate](REPLAY_LAB_ROUND7_EVIDENCE_REASONER_INTEGRATION_GATE.md). **Adopt temporal firewall and typed claims; defer unverified numerical EV/minimax simulators, presumed player camera/audio, rank-conditioned success probabilities and model-training claims.** Do not pass Claude's entire decision object to Stage 1: it contains a separate `retrospective` block. No paid Gemini requests made here, no integrated episode-level coaching, no merge to `main`.

- **ChatGPT implemented a separate Stage 1 evidence firewall draft** in [PR #27](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/27), stacked directly on Claude PR #22: `coach-app/coach_app/stage1_packet.py` and `tests/test_stage1_packet.py`. It explicitly whitelists pre-t0 E./C. evidence, U. unknowns, anonymous slots, and context; it excludes retrospective action/goals, selection provenance and any unapproved fields, rejects future stamps and unsafe IDs, and makes **no model calls**. **GitHub Replay Coach MVP tests and Replay Viewer 3D checks passed; general CI still running at this checkpoint. No validated tactical verdicts.** Detailed integration decision: [Round 7 gate](REPLAY_LAB_ROUND7_EVIDENCE_REASONER_INTEGRATION_GATE.md).

**Immediate integration dependency:** consume Claude's actual `DecisionEvidenceV0` contract rather than reimplementing states; use a causal/pre-t0 packet for judgments; keep retrospective action/outcome isolated. Future tool-calling Gemini must be compared with the deterministic baseline under independent high-rank review and respect the owner's opt-in for replay data uploads and billing. Fixing PR #26 only makes the old endpoint honest, NOT expert-validated. Do not duplicate #22 or merge conflicting UI branches.

## Round 7 — Antigravity native companion handoff / review

### Native-companion correction checkpoint (18 November 2026 UTC)

- Antigravity pushed correction commit [`44d5241`](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/commit/44d5241eb80257426c709e695d05a08bbeec88d5) to [draft PR #28](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/28). Confirmed from source: Python client now defaults to `require_opt_in=True`, acceptance CLI requires explicit permission flag/environment variable, spectator selection no longer guesses from roster order, real-environment tests skip off Windows/Rocket League, report paths anonymized, and live acceptance has state checks for loading, seeking, pausing and speed. Antigravity reports **120 passed, 4 skipped**. GitHub **Replay Coach MVP, Replay Viewer 3D, CI passed** on this SHA; HD preview still running at checkpoint. **No actual running-game test.**
- Review comment on PR #28 (GitHub comment `6970492814`) identifies *remaining inaccuracies* before calling the full seven steps "observed/verified": POV steps 3–4 only assert **transmission** (official `Game.Target.Shortcut` can verify focused player); the published Stats API `UpdateState.Game` does **not document** `GameSpeed` or `bPaused` telemetry, which automated checks 5–6 assume; step 7 passes even with null elapsed/drift; offline `--run-acceptance` returns exit zero; INI diagnostic labels a rate "effective" without proven precedence; duplicate `anonymize_display_path()`. Recommend source-backed observation or explicit **manual/unverified** status, and avoid false "all seven verified" success. Real test remains subject to owner's permission; no settings changes here.
- Official source: https://www.rocketleague.com/developer/stats-api (install-directory config instructions; `UpdateState.Game.Target` and `Elapsed`; command shapes).



- Antigravity pushed two commits (`7978dc1`, `bd62742`) to `feature/native-companion-v1-proof-20261117`, stacked on PR #20. A 300-line report is at `docs/research/ROUND_7_NATIVE_COMPANION_PROOF_REPORT.md` on that branch. Its local tests were **reported** as 119 passed, 4 skipped, including 7-step *mock-server* replay acceptance. **No live game commands or native video capture were tested.**
- We opened [draft PR #28](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/28) for source-backed review, NOT merge. Before live testing, address: (1) Python companion default `require_opt_in=False` allows command send unless caller explicitly requires the flag; CLI `--run-acceptance` self-enables, (2) player mapping assumes `SpectatorShortcut`/`Team` and list order but official telemetry fields are **`Shortcut` and `TeamNum`**, (3) CLI prints completion without asserting real observed replay/POV/pause/speed, (4) official INI edit location is within the game install directory, while the report asserts a separate Documents overlay without live confirmation, (5) workstation-specific test and personally identifying paths in a public report, (6) unmeasured capture latency/GPU/privacy claims. Full review and source links are in PR #28.
- **Immediate next action:** ask Antigravity for a *small* correction pass (no more broad research). Then, and only after owner permission, verify the real Rocket League game Stats API with an actual replay file. Keep video capture separately gated. Antigravity's live-client status is `NOT VERIFIED`.

## Round 8 — parallel work assignments and first claim verifier (18 November 2026 UTC)

**Goal:** one coherent 5–20-second *Proof of Coach* case assembled from genuine predecision evidence, with multiple plausible options, explicit uncertainties, an optional postdecision comparison, and expert evaluation. This is an engineering milestone, **not evidence that elite coaching works yet**.

- **Claude** — assigned small `EpisodeEvidenceV0` assembler stacked on PR #22: manually chosen 5–20s window, 2–3 `DecisionEvidenceV0` nodes with separate t_i cutoffs, stable source IDs, source-backed boost/spacing/cover changes and hypotheses about earlier contributing decisions. No causal regret EV, training, or new UI. Deliver branch/PR and tests. *Assignment sent to user; code not confirmed yet.*
- **Gemini** — assigned implementation-ready **12-case blind expert benchmark** using actual available replay features (no invented EV labels), two-phase human review form, JSONL manifest/rubric, example and adversarial outcomes. Respect PR #16, distinct from commitment-timing labels. No repo write access, API/model spend or raw user replay uploads. *Assignment sent to user; design not confirmed yet.*
- **ChatGPT** — [draft PR #29](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/29) stacked on Stage 1 firewall PR #27: `coach-app/coach_app/claim_verifier.py` and `tests/test_claim_verifier.py` validate cited E./C. source facts, U. unknowns, typed nested scalar predicates, source timestamp boundaries, and false numeric claims. Outputs `rejected`, `structured_fact_verified` (only numeric/direct structured assertions), or `needs_semantic_review` (all free-text claims). **It explicitly NEVER certifies unreviewed natural-language semantic claims or strategic merit.** Latest code SHA `a3169fb` (17 test functions) passed **Replay Coach MVP, Replay Viewer 3D and general CI**; a docs-only handoff commit `379d31e` followed. [Exact verifier contract](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/blob/feature/round8-claim-verifier-v0-20261118/coach-app/docs/round8/CLAIM_VERIFIER_V0.md). No model calls.
- **Antigravity** — focus exclusively on small live-companion fixes documented in [draft PR #28](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/28): default/CLI command opt-in, exact official player `PrimaryId`/`Shortcut` mapping, *observed* real-game acceptance assertions, confirm config precedence, portable tests and public-report privacy. **No game configuration edits without permission.** Live game still unverified.

**Integration graph:** Claude PR #22 → ChatGPT Stage 1 packet PR #27 → ChatGPT claim verifier PR #29; Claude episode assembler branches directly from #22 and will require explicit later rebase/integration. Antigravity PR #28 is stacked on PR #20 but unrelated to these tactical branches. ChatGPT PR #26 fixes legacy Gemini review in a different viewer branch; avoid cherry-picking or merging entire unrelated chains. Gemini produces evaluation spec only. **No merges into main.** When reviewing any PR, verify CI on its exact SHA, not only its ancestor.

## Round 8 — Gemini expert-evaluation proposal RECEIVED (18 November 2026 UTC)

Gemini delivered `replay_lab_round8_evaluation_package.md` as a 495-line **RL-EvalPilot-12** design with 12 tactical cases, predecision acceptable-action sets, outcome/false-blame traps, a proposed two-stage human review, blinded A/B grading, JSONL examples, per-claim error categories, and follow-up questions. **This is a research/design artifact, NOT code, a validated public-replay cohort, or completed expert ratings.** Gemini correctly disclosed no direct repo access.

**Critical source-verified integration decisions** in [Round 8 Evaluation Package Review](REPLAY_LAB_ROUND8_GEMINI_EVAL_PACKAGE_REVIEW.md):
1. B01–B05 bucket definitions often select on **post-t0** goals, misses, 50/50 outcomes; use in coordinator-only adversarial stress sampling, NEVER as Stage 1 features; preserve a separately tagged outcome-blind reference sample and PR #16's existing independently-sampled controls. Do not claim representative false-blame rates from these 12 cases.
2. Gemini's Phase 1 asks about the focal player's *actual* observed action while hiding future frames; that classification belongs to Claude's separate `retrospective` block. First freeze the acceptable action set at t0; afterward judge the observed action in a separately labeled step.
3. PR #16's existing tactical `review.html` is **a standalone JSON packet interface with no embedded replay viewer, server-signed lock or cryptographic freeze**. The commitment-timing `commitment_review.html` is a separate 40-clip study. PR #27 is a model data serializer, not a video scrubber. Gemini's new proposed endpoints/UI are unimplemented.
4. Existing `subtr_replays.py` emits resampled 30Hz rows and normalized boost 0–100, not validated `boxcars.stale_ticks` age data; Claude's booster/state caveats stand. Gemini's `automated_selector_predicates` includes future outcome metadata in its synthetic manifest; never forward it to a Stage 1 model or the deterministic baseline.
5. PR #16's strict `pre_decision_evidence` and four-way verdict schema are **not compatible by default** with Gemini's proposed multi-action/nine-dimension schema. Implement an explicit mapping/validation layer, not a blind copy. Rubric D1–D8 plus separate D9 follow-up. ChatGPT claim verifier PR #29 checks typed facts, NOT semantic truth of free text.

**Next focused engineering step**: small strict adapter from Claude PR #22's DecisionEvidenceV0, through Stage 1 PR #27, into PR #16's actual evidence packets, preserving time provenance or abstaining when it cannot be established. Then revise the pilot reviewer forms/manifest and test on synthetic cases before curating real clips. Antigravity native companion PR #28 remains independent; user consent required for cloud calls, public-replay downloads and live-game config changes. No LLM benchmark run, expert ratings, or 12 confirmed cases yet.

## Round 8 — Claude EPISODE DELIVERED and first cross-agent integration (18 November 2026 UTC)

- **Claude's episode builder is implemented:** [PR #22](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/22), commit `1897569`, adds `coach_app/episode_evidence.py`, 10 synthetic tests, example, documented contract and real-replay batch. **215 passed, 4 skipped** reported; GitHub tests, check and camera-and-geometry all passed on exact SHA. On **15 rank-unverified replays**, 625 fixed-offset 2–4-node episodes had byte-identical `stage1_view` after deleting post-primary data; labels/episode windows were **NOT expert-selected**. A role-gap inf−inf NaN is now an explicit unknown. Outputs include node-local evidence, typed D. changes, T. timeline, U./UD. unknowns, H. hypothetical earlier contributors and separate R. retrospective outcomes.
- **Integration branch opened:** [draft PR #30](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/30) is stacked directly on Claude's current PR #22. It combines PR #27's predecision sanitizer and PR #29's typed claim verifier into one Git history without overwriting other agents' branches. New `coach_app/episode_stage1.py` and `tests/test_episode_stage1.py` produce `Stage1EpisodePacketV0`: each of Claude's decision nodes goes through the **strict** `build_stage1_packet` at its own time cutoff, and audited typed D./T./H. metadata is filtered to known-time, anonymized references. This blocks arbitrary `label`, `selection`, `source`, free-form notes/questions and all Stage 2 outcomes. **Important:** Claude's internal `stage1_view()` removes retrospective data but is NOT a safe prompt payload by itself; use PR #30's stricter builder for AI. Change arithmetic is **not** independently recomputed; model claims and tactics are not verified by source references alone. [Integration contract](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/blob/integration/round8-episode-coach-contract-20261118/coach-app/docs/round8/EPISODE_STAGE1_INTEGRATION.md).
- **Current test checkpoint:** PR #30's first full CI run exposed repeated `U.frame` references inside a real abstention case (original episode builder duplicates them for multiple missing inputs). Integration code now deduplicates *only* unknown IDs without inventing evidence. Exact post-fix SHA `c66a6ea` **passed all three GitHub Actions checks**: coaching tests (**258 passed, 4 skipped**), general CI, and camera-and-geometry. No live-game or expert tactical evaluation was performed.
- **Antigravity:** The native companion head remains `44d5241` on [PR #28](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/28); the latest message repeats the previously reviewed correction. Real game acceptance still unverified, with feedback on POV transmission-vs-observation, undocumented pause/speed telemetry, final clock, offline success exit and config precedence. No game/config changes were made.
- **Next integration milestones:** (1) pass full PR #30 CI and review packet provenance against live parsing; (2) strict adapter to PR #16's blind human-review case rows **without fabricating finalized_through_s**; (3) deterministic fixed-packet vs optionally approved LLM coaching A/B with human review of actual selected 2v2 episodes; (4) separate consented live native replay proof when Antigravity meets review gates. No code merged to main, no benchmark expert ratings, no paid model calls or native commands.
 
## Round 9 — actual CoachLessonV0 backend implementation (18 November 2026 UTC)

**Implementation, not another research round.** [Draft PR #31](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/31) is stacked on the green [PR #30](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/30) integrated episode branch, separate from Claude's developing TacticalOptionsV0 and Antigravity's frontend. Exact [backend + API contract](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/blob/feature/round9-coach-orchestrator-20261118/coach-app/docs/round9/COACH_BACKEND_V0.md).

- `coach_app/coach_lesson.py`: constructs `CoachLessonV0` from Claude episodes through the strict `Stage1EpisodePacketV0`; local deterministic observation baseline (boost and evidence links, **NO tactical verdict**). Accepts opt-in `CoachDraftV0` candidates with explicit `N#/E.`, `N#/C.`, `N#/U.`, D./T./H./UD. source checks; rejects fabricated numbers, future decisions, retrospective refs and certain-causation claims on hypotheses. Model prose that survives numeric checks remains marked `needs_semantic_review`, **not expert-verified**. Earlier contributing choices remain unverified questions.
- `coach_app/coach_model.py`: provider-independent OpenAI-compatible `/chat/completions` transport with both **per-request** `mode=model` and **server** `REPLAY_LAB_ENABLE_COACH_MODEL=1` required; explicit server URL/name/key; local HTTP allowed only for loopback; no raw replay, source/selection metadata or postdecision results sent; no paid API calls performed in development.
- `coach_app/coach_api.py`: `GET /api/coach/capabilities`; `POST /api/coach/lesson`; `POST /api/coach/evidence` (safe inspected source values behind N./D./T./H./U. citations, rejects R. retrospective); `POST /api/coach/followup` (local evidence-navigation only, **not** LLM dialogue). These accept a bounded four-player decoded replay, 2–4 manual decision times in a 5–20-second window; returned `CoachLessonV0` drives Antigravity UI directly. `main.py` only registers this separate router and leaves legacy endpoints intact.
- 26 new synthetic/adversarial test functions cover numeric/citation failures, impossible certainty, future invariance, source inspection, model opt-in and sanitized transport, request limits and same-origin browser protection. **Initial CI exposed a shared test-fixture side effect** (roster mutated across tests), fixed by deep-copying each API fixture (commit `912d524`). **Exact PR #31 head `f017ef66` PASSED all three GitHub workflows:** full coaching suite **284 passed, 4 skipped**, general CI passed, Replay Viewer 3D passed. This proves software behavior in synthetic tests, NOT tactical expert quality or a live/model game test.
- **Explicitly NOT DONE:** actual expert-grade AI judgment, Claude TacticalOptionsV0 integration, calibrated reachability alternatives, model-backed multi-turn followups, automatic episode selection, semantic review of English claims, complete frontend, live game control or real reviewer scoring. These are later Round 9 gates; user need not choose a paid provider now.

## Round 9 — Claude tactical delivered, coaching integrated, Antigravity frontend receipt (18 November 2026 UTC)

- Claude **TacticalOptionsV0** is delivered in [draft PR #32](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/32), SHA `2a38959`, from PR #30. Nine 2v2 action families have separate physical feasibility, tactical stance, limiting/supporting claims, teammate dependence, unobservables and earlier-contributor hypotheses; policy bands are **uncalibrated** and do not identify a single best move. Claude reports 271 passed/4 skipped, green GitHub CI, and 625 public rank-unverified 2v2 episode cases; 0/8185 source-claim failures and 127/127 future truncation invariance. **These are integrity/model timing checks, not expert tactical verdicts.**
- ChatGPT combined Claude PR #32 and earlier CoachLessonV0 PR #31 into [draft integration PR #33](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/33), stacked on #31, with two-parent merge retaining both PR ancestors. New `tactical_coach_adapter.py` verifies the tactical menu's underlying source claims using each Stage 1 node and marks all stances **uncalibrated hypotheses**. `CoachLessonV0.tactical_options` now contains the menu; opted-in OpenAI-compatible model prompts receive the strict Stage1 episode AND vetted tactical context, and optional `tactical_claim_ids` must match known same-node underlying sources. Negative control, aggression, uncertainty, future rewrite and fake tactical ID tests added. **Exact code SHA `bb45c22`: 307 passed, 4 skipped, general CI and viewer geometry both GREEN.** Documentation-only SHA `ea66407` followed with independent workflow checks. [Integrated API/front-end contract](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/blob/integration/round9-coach-tactical-20261118/coach-app/docs/round9/INTEGRATED_COACH_TACTICAL_V0.md). No paid models, live game commands or expert judgment.
- Antigravity reported Round 9 UI completed locally at `feature/round9-coaching-experience-20261118` commit `d8700a1`, including 3 fixture episodes, multi-node viewer, source inspector, retrospective toggle, synchronized 2D/3D, local Q&A, screenshots and 263 passed/4 skipped in its environment. **IMPORTANT:** At review, this branch/commit were **NOT PRESENT** in the connected GitHub repo's branch list, pull requests or commit lookup. The named detailed report, screenshot and spec were not available as current conversation attachments/Library results. Do not claim code inspection, remote CI or browser verification independently. Antigravity must **push and open a draft PR** before our team can inspect/rebase/test against PR #33.
- **UI integrity gate:** fixture demo is not a real replay analysis; clicking on "verified" source chips must call `POST /api/coach/evidence` on genuine backend records, not a local mock object. Model-generated coaching is opt-in; `POST /api/coach/followup` is currently a deterministic source navigator, **not** conversational LLM intelligence. An HTML reveal toggle alone does not enforce a trusted Stage 2 research freeze. The real backend returns only Stage 1 and no authentic Stage 2 reveal API yet. Label these limitations honestly.
- **Next:** Push/review actual Antigravity frontend; reconcile its local `COACHING_EXPERIENCE_API_SPEC.md` with our [actual backend contract](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/blob/feature/round9-coach-orchestrator-20261118/coach-app/docs/round9/COACH_BACKEND_V0.md) and PR #33; run one browser with a real decoded `.replay`, not just fixture scenarios, then independent blind reviewer validation. Native companion PR #28 is separate and has no consented live game test.

## 1. Mission: build an exceptional coach, not a replay viewer

Player uploads a **native Rocket League \`.replay\` file**, selects who is being coached, and receives a **few insightful, evidence-grounded, high-skill lessons** about decisions they would not necessarily notice themselves. Show both **excellent** and **questionable** decisions, explain strategic tradeoffs and *feasible alternatives*, allow follow-up questions, and identify meaningful trends across matches.

**Quality bar:** eventually useful to experienced GC/SSL players; not claimed today. Reject simplistic rules ("two teammates near each other = mistake", "lost a 50/50 = bad", "always cover first"). Multiple aggressive or defensive playstyles can be valid. A good decision can fail and a poor decision can succeed. Distinguish observed facts, prediction, hypothetical alternatives, actual post-decision outcome, intent, and uncertain claims.

**Owner's example of required depth (illustration, NOT a measured replay finding):** when challenging an opponent controlling their own backboard, consider their available outplay, teammate's possible 1v2 exposure, boost and recovery cost, whether even a won 50/50 gives valuable possession, opponent's second-man position, and whether shadowing/rotating before contesting would preserve better pressure. Don't just flag a "50/50".

## 2. Visual interfaces serve the coach

- **2D:** clean, small tactical overview with ball, players, nose orientation, optional boost pads and contextual coach alternatives. No permanent paths, ball-height dashed ring, TOUCH callouts, big selected-player halo, pad pickup counts, duplicate clock or debug disclaimer. Selected player marked subtly; individual player boost readable and **unknown != zero**.
- **3D:** actual replay-like view of height, mechanics, touches and cameras. The old geometric renderer was rejected; prioritize usable elevated chase camera and authentic playback.
- **Desktop today:** evaluate **optional official Rocket League Stats API companion** to control the *real native game replay* where installed, while the local coach and 2D map stay in our app. It is not a direct browser renderer; don't assume native game video can be embedded.
- **Standalone/mobile later:** our independent HD 3D renderer remains **mandatory** for phone/offline viewing when the game cannot run. Launching Rocket League is **never required** to use the coach. Native and standalone modes are alternative visual backends, not competing products.

## 3. Coaching design: proposed target, NOT yet deployed

\`.replay\` -> reliable typed telemetry with source times and unknowns -> meaningful decision candidates and t0 commitment -> kinematic/physics feasibility and several tactical choices -> evidence packet and context -> **Gemini API as tool-using reasoning/tutoring layer** (or alternative measured model) -> claim verification / expert calibration -> concise lesson and replay seek -> eventual cross-match profile.

The coach should explore the full strategic situation: possession, challenge timing, first/second man, support, rotations, likely ball destinations, boost economy, pressure, recovery, risks and alternatives. Every model claim must cite source evidence or be visibly marked hypothetical; never use frames after t0 as information known at the decision. Retrospective labels and outcomes are separate. The user must be able to challenge the conclusion.

**Current reality:** today's \`/api/ai-review\` sends a small selection of numeric telemetry to Gemini and requests at most one cautious hypothesis. It is **not** this expert coaching architecture. Claude's evidence-bound Q&A is mostly deterministic and not a live tool-using Gemini tutor. We have **not** trained or validated a full local tactical model. Earlier small-data ML/retrieval experiments did not justify one. Do not confuse separate \`src/\` Cloudflare/YouTube Gemini MCP with the \`coach-app/\` replay coach.

## 4. Current engineering branches — all separate, draft, unmerged

| Work | GitHub | Verified capability and caveat |
| --- | --- | --- |
| Advanced tactical coach | [PR #22](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/22), stacked on [#21](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/21) | Decoder case analysis, new reachability (touch-bound violations 27.6% -> 5.7% within same 15 replays), shadow/challenge candidates, tactical interpretations and provisional player patterns. **No expert validation.** Unknown/finite boost, missing telemetry, temporal Q&A safety still need fixes; benchmark tuning lacks independent held-out replay set. |
| Evaluating coaching | [PR #16](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/16) | Blind timing study and **separate** expert tactical-merit review, match-clustered paired comparisons, packet freshness and fake-video checks. **No real expert ratings yet.** Timing labels cannot validate tactical wisdom. |
| Viewer improvements | [PR #23](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/23) | Camera/visual/sync changes; its claimed clip exporter is a **single dummy WebM frame**, not gameplay footage. "200x full replay loader" claim does not follow from first-player-only precomputed binary test. |
| User-driven decluttering | [PR #24](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/24), stacked on #23 | HD-first split/map, fewer overlays, player boost bars, experimental higher chase camera. **Needs Windows visual testing and HD rebuild**; advanced coach not integrated. |
| Native Rocket League link | [PR #20](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/20) | **Previously investigated and partly implemented** official Stats API command/protocol repair. This is **NOT a new discovery**. Must verify game-side commands, local configuration, seek/POV/pause/speed, actual round-trip behavior and time alignment on user's PC. Unverified until that test passes. |

Repo: https://github.com/mechanicalengineringst-png/rocket-league-video-mcp . The separate \`src/\` Cloudflare MCP is **not** the local replay coach. Do not treat GitHub green CI, research documents, or synthetic tests as proof of product-quality visual fidelity or GC/SSL coaching.

## 5. What we do next (priority order)

**P0 — One complete coaching vertical slice:** On one genuine 2v2 replay, integrate advanced backend + a genuinely capable Gemini reasoning/tool workflow + actual usable 3D/native playback + small 2D. Produce **1–3 falsifiable, high-value coaching cases**, including a hard backboard/challenge-type decision; present evidence, alternative, uncertainty and a follow-up explanation. Owner must judge whether it teaches something new. Avoid auto-generated dozens of shallow flags.

**P0 in parallel — Native game control proof:** On the user's Windows game installation (only with user permission and manual opt-in setup), test official Stats API from replay loading through seeking, player POV, pause/speed and measured time sync. Existing PR #20 and official API docs are the starting point, **not something to rediscover**. Fall back to standalone HD, never require game launch.

**P1 — Trust calibration:** Fix reachability/Q&A data-contract gaps; obtain actual video clips, not placeholder WebMs; do separate commitment **timing** and blind tactical **merit** reviews with experienced players, tune on training matches and evaluate on **different complete replays**. Track false criticism of sound decisions, unsupported claims, usefulness and abstentions.

**P2 — Accessibility:** Keep improving independent replay fidelity for eventual mobile, local-first replay library, long-term habits and optional cloud reasoning. Do not let mobile or cosmetic work block the coaching prototype.

## 6. Anti-amnesia / agent operating rules

1. **Before every work round:** read this file, verify live GitHub branches/PRs/tests, and read the latest relevant decision notes. Do not call a previously discussed approach a new discovery.
2. **After significant work:** update this document's current state, PR/commit references, explicit known defects, new decisions and next handoff. Keep the detailed evidence in PRs and longer Google Drive archive.
3. **Human decisions are binding:** user priorities and rejected UI elements trump preserving AI-generated features. Do not silently reintroduce them. Explicitly flag if goals appear contradictory or a tradeoff needs the owner's choice.
4. **Distinguish statuses:** proposed / implemented / CI-tested / browser-observed / real-game-verified / expert-validated. Passing CI doesn't move a feature through all statuses.
5. **Security:** this repository is public. Store **summaries, decisions, URLs and non-sensitive evidence**, NOT conversation dumps containing personal information, raw replay identities, secrets, API keys, tokens or local file paths. GitHub is the **operational handoff**; Google Drive is the deep historical record.
6. **Branch safety:** no unreviewed merges into \`main\`; agents work on independent branches/PRs. If this compass changes, make the change visible in a docs PR and call it out to the other models.

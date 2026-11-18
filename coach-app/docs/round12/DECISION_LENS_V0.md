# Decision Lens V0 — recorded evidence workspace (Round 12)

## Product problem solved

The prior source-backed coaching UI could show a decision's time and seek both
the tactical map and standalone HD player, but it gave the tester no efficient
way to repeatedly inspect the *same* setup, compare spatial relationships at
the decision, and observe what actually happened next. That prevented useful
calibration of coaching suggestions such as challenge versus shadow, teammate
coverage, and whether a win led to useful continued possession.

The new **Decision Lens** is a **working interactive replay feature** placed
between the shared playback bar and the coaching cards. It is not a new AI
heuristic or a proposed physics simulation; its geometry, samples, markers,
numbers, and trails are derived from the exact decoded replay already in the
browser. It works with the real HD+2D split, HD-only, and 2D-only modes.

## What the user can do

- A real source-backed coaching node automatically **pins the precise t0**,
  opens the panel, and shows **recorded t0 positions** on the 2D pitch.
  Clicking a different episode or N1/N2/N3 node moves the pin. The user
  may also **Pin current frame** manually after selecting a confirmed
  player, even if the coach abstained on that moment.
- See simple measurements **at the actual decision time**: focal-to-ball
  horizontal distance, focal-to-teammate separation, nearest observed
  opponent-to-ball distance, focal boost, ball height and focal speed. The
  map draws distinct colored t0 rings for focus, teammate, opponents, ball.
  No spatial relation is described as a mistake or optimal tactic.
- **Approach** seeks to a bounded predecision interval (normally t0−3s).
  **Decision t0** seeks to the pinned instant.
- **Loop scene** plays from t0−3s through t0+2s, wrapping safely at the
  bounded end. Crucially, it uses the **one parent replay clock**, so both
  tactical map and independently loaded high-fidelity iframe follow the
  same input time, and any aligned local video continues to use the same
  existing sync path. This does not auto-control the native game companion.
- **Reveal actual +2s** explicitly uncovers separately recorded future
  positions, plus a sampled **real observed path** for the focal car and
  ball; it adds an actual change in focus-to-ball distance. Those are
  *post-decision observations*, **not feasible simulated alternatives**.
  Hide immediately removes the later ghosts and metric.
- **Clear Lens** removes pinned observations, and loading another match or
  switching the focal player invalidates old pins. Manual timeline
  scrubbing leaves the scene loop instead of silently jumping back.

All controls handle clipped windows near replay start/end honestly: no
fabricated t−3 or t+2 samples; labels reflect their actual durations.

## Technical contract and temporal boundary

Source: `coach-app/coach_app/static/decision-lens.js`.
No external dependencies or network calls, CommonJS support for Node tests.

`ReplayLabDecisionLens.buildWindow(replay, playerId, t0, beforeS=3, afterS=2)`

returns `ReplayDecisionLensV0`, containing:
- `t0, start, end`: clipped boundaries on the existing replay.
- `anchor`: **floor frame** with `frame.t <= t0`, max sample age
  **200ms**. Does not use a future frame to fill missing decision evidence.
  Observations are labeled and cannot produce tactical grades.
- `after` and `recordedAfterTrace`: kept logically separate; only the
  user-initiated Reveal draws them or adds after metrics. This local visual
  state is **never supplied to the Stage 1 model packet**.
- `source`: distinguishes `recorded_replay_telemetry` from an explicit
  `synthetic` demonstration.
- `predictionsMade: false`; `coachingGradeAssigned: false`.

All distances are **horizontal Rocket League world units** (not
time-to-ball or reachability), and speed is the magnitude of a recorded
3D velocity vector. Approximate distances are displayed in rounded units
rather than misleading precise figures.

Missing players, demolished cars, missing vectors, or a stale 200ms+ sample
produce **unknowns** or abstention, never guessed positions.
`anchor.complete` requires both opponents, focal car, teammate and ball.
Two live cameras or player intent cannot be reconstructed by this API.

`ReplayLabDecisionLens.loopNext(current, delta, speed, window)` is a pure
bounded wrapping time function. The already-existing shared
`playTick -> chooseTime -> announceReplaySync` bridge transports that
clock to the independent HD iframe.

`CoachingExperienceController.syncReplayToNode` emits
`replay-lab:coaching-moment` (t0/nodeId/episodeId only; simulated marker).
The app listens and pins the fresh sampled state. It does not alter
`CoachLessonV0`, `CoachReviewBundleV0`, `ActionRationaleV0` or
Claude's pending `CoachingReportV1`.

## Why this is an improvement

It converts source-backed coaching from a static card plus timestamp into an
**experimental review workspace**. In a difficult backboard situation, for
example, the user can see the exact spacing at t0, repeatedly play the three
seconds of preparation into the challenge, then *explicitly* inspect the
recorded result. That supports personal assessment of possible teammate
exposure, actual boost expenditures, and the quality of the recommendation.
It **does not automatically assert why the choice was good or bad**.

## Verification

- New `high-fidelity/test/decision-lens.test.mjs` covers prior-only
  snapshots, rewriting future frames without changing any t0 context,
  source trace correctness, missing/stale/demolished telemetry, clipped
  windows, no mutation, bounded looping and explicit no-prediction fields.
- `tests/test_ui_contract.py` checks real HTML controls, temporal
  isolation and the coaching-node hook.
- The existing `browser-round12-e2e.mjs` was enhanced to click through
  t0 metrics, future reveal, map actual ghost markers and replay looping.
  It also retains PR #44's requirement of a **real loaded HD WebGL canvas**,
  not an iframe-only smoke check.

**This is not a human visual acceptance, source-telemetry validity proof or
native Rocket League command test.** The browser test must actually run
with an owner-authorized native 2v2 replay fixture, a working local HD
asset bundle, Chrome and a local app. GitHub CI may skip fixture-driven
cases because those replay files are not in public source.

## Branch and merge constraints

- Branch `feature/round12-decision-lens-interactive-review-20261118`
  stacked on PR #44 (itself stacked on Antigravity's PR #43).
- Independent of Claude's tactical PR #45; changes only
  `coach_app/static`, the controller's selected-node **event**, related
  browser QA and documentation/tests.
- No unrequested merge into `main`, game config change, paid model
  request, private replay upload or new server-side state.
- The next authorized unified development round should reconcile this
  feature with independent model test PR #41 and HD camera/trails PR #42.
  It can consume future `CoachingReportV1` node timestamps without
  altering the evidence model, once the frontend knows their contract.

## Real user test script

1. Launch the integrated Windows app and compile the pinned HD player.
2. Upload a genuine 2v2 replay; confirm the correct player.
3. Click a real coaching node. Check that the Decision Lens opens with
   t0 positions and approximate, source-backed metric cards.
4. Choose **Loop scene**, watch HD/2D times and car/ball motion through
   the decision. Pause, switch back to the decision, adjust view mode.
5. **Reveal actual follow-through**: confirm extra orange dashed markers
   and recorded tracks are visible, compare to native replay.
6. Change player and replay: ensure all pins/ghosts are cleared.
7. Near kickoff/end and a demolished vehicle, confirm clipped time
   bounds, missing data indicators and no invented positions.
8. Rate the *actual coaching advice* as useful, wrong or lacking
   context, and export the private test report. This feature is a lens
   for judging advice, not a new unverified coaching grade.

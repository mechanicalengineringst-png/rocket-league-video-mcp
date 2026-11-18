# Round 12C: Review moments the automatic coach missed

**User-facing improvement.** Automatic discovery should not be a gatekeeper
for what the player can study. The Decision Lens now includes
**Review this overlooked moment (local)**. This lets the player identify
their own interesting situation, build a verified source-backed local
coaching episode, inspect evidence, and *optionally* use the separately
consented AI coaching request already provided in PR #47.

This is actual feature code: \`static/manual-review.js\`, corresponding
Decision Lens UI, \`app.js\` integration, and automatic/manual episode
preservation in \`coaching-experience.js\`. The coach's claim of *having
missed something* is the human's hypothesis, not an externally validated
mistake label or a new detection metric.

## Workflow

1. Load an actual decoded 2v2 replay. Confirm the player being reviewed.
2. Seek in HD+Map, HD-only, or 2D and click **Pin current frame** in the
   Decision Lens. A 2D overlay and scene looping still work as before.
3. Click **Review this overlooked moment (local)**. This sends exactly
   one deterministic \`/api/coach/lesson\` request to the local server.
   It does **not** contact any AI provider or spend model credits.
4. The backend rebuilds a true
   \`EpisodeEvidenceV0 → Stage1EpisodePacketV0 → CoachLessonV0\`, then
   returns source-supported observations/uncertainty. The resulting
   selectable review card is labeled
   **YOU SELECTED THIS MOMENT / ... NOT A DETECTED MISTAKE**.
   It is independent of the auto shortlist and is preserved when late
   discovery results arrive.
5. To test AI on the selected manual episode, open the separate
   **AI coaching proposals** panel, explicitly authorize *one* model
   request, then click Generate. The same exact audited episode timestamps
   and evidence citations are reused. Any provider cost/privacy
   authorization belongs to that second, separate action.
6. Use model ratings and local JSON export to record missed opportunities
   and unhelpful coaching in the upcoming real-ranked-replay test.

**No auto-generated recommendation is treated as expert-validated merely
because the user selected its timestamp.** Selected context nodes are
neutral time samples, not established player choices or counterfactuals.

## Exact evidence and temporal contract

Pure \`ReplayLabManualReview.buildManualRequest(replay, playerId, pinnedT0)\`
requires:
- One genuine non-synthetic four-player 2v2 replay with two players/team,
  unique valid player IDs, and explicit confirmation of the focal player
  by the caller.
- At least five seconds of recorded **predecision** history. If the player
  selects a moment too close to kickoff/start, the feature abstains rather
  than inventing earlier frames.
- A focal player and ball with finite X/Y/Z, not demolished at all three
  sampled anchor points. Bad/missing focal samples yield no review.
- A recent actual frame **at or before** each target time (maximum sample
  age 200ms). All three selected source frames are predecision, bounded,
  unique and strictly ordered. The original decoded replay is untouched.
- A window beginning up to seven seconds earlier (never less than five
  seconds) with two earlier *observational context* timestamps followed
  by the pinned primary time. Those times are not asserted causal choices.
- The final \`primary_t0\` uses the genuine recorded frame's time
  normalized to the backend's millisecond convention. The backend
  independently checks all window, identity and temporal rules.

Server returns a deterministic \`CoachLessonV0\` only if its real
\`mode:deterministic_baseline\`, \`stage:predecision\`, primary \`N3\`,
exact timestamp/start, and explicit no-future/no-expert-validation
fields all agree. Otherwise no manual episode is accepted.

**Falsification rule:** changing frames and game events **after** primary t0
cannot affect its Stage 1 evidence commitment or deterministic lesson.
This is tested through the actual local FastAPI endpoint, not merely
by inspecting JavaScript.

## Race and state handling

- The owner selects the moment explicitly. Local review never auto-starts.
- A request is invalidated if the replay/player/pin changes; its stale
  response cannot become advice about another match.
- The original automatic shortlist remains. A late
  \`CoachReviewBundleV0\` response can add auto episodes without
  destroying manual episodes or stealing a currently pinned scene.
- The same manual moment has a stable, independent \`manual-\` episode ID
  instead of colliding with an automatically detected source case.
- Selecting a manual episode automatically opens the existing Decision
  Lens at its source timestamp, with the same sync on HD/2D.
- Separate AI consent remains required. A manually analyzed source-only
  episode is not a model-generated tactical grade.

## Verification

New executable Node suite:
\`high-fidelity/test/manual-review.test.mjs\`

Includes: exact historical sampling, future rewrites not changing the
review request, kickoff/sparse/missing/demolished replay abstention, no
backend call on mount, explicit one local deterministic request, stale
response rejection, invalid server result fail-closed, auto-pinned cases
not treated as user-selected, and unconfirmed player blocking.

New FastAPI integration tests:
\`tests/test_round12c_manual_moment.py\`

Include real \`CoachLessonV0\` construction from selected
timestamps, evidence reference lookup, and the same Stage 1 hash for
replays with completely different actual future events.

Python static UI contracts and the GitHub viewer CI workflow exercise
the new UI controls and JS code. These tests are engineering evidence,
**not human validation that a manually selected play was strategically
important**. They use synthetic fixtures, not the user's personal replays.

## Agent ownership and next integration

- **This branch** is stacked on PR #47, so it already includes the
  unified Antigravity frontend, manual native LoadReplay gates, Decision
  Lens, and actual model-coaching UI/model-readiness/Windows test kit.
- Claude's experimental \`CoachingReportV1\` (PR #45) remains on a
  separate tactical branch and is not imported as validated insight.
- Antigravity works on independent HD camera/vehicle/stadium/assets/native
  control in a separate branch. During the authorized next integration
  round, preserve the **manual review flow and automatic/manual episode
  coexistence** while reconciling any \`app.js\` or UI conflicts.
- Do not silently fall back to fixture episodes, invent earlier decision
  causation or call an external provider automatically.
- No merge into \`main\`; no paid model calls or live Rocket League
  commands in this implementation.

## Owner acceptance test

In a real ranked replay, intentionally choose a meaningful moment the
automatic shortlist did not highlight. Pin it, click local manual review,
then select the resulting episode. Confirm 2D and HD seek to the pinned
time and the evidence citations resolve. Try a moment before five seconds
of recorded history, a demolished frame and another player: they must
abstain or make an independent correctly scoped review. Finally,
explicitly consent to model coaching on the manual episode and rate
whether the advice truly improves on the deterministic observations.

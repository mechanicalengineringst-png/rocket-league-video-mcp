# Round 12D: Grounded pre-decision spatial relationships for coaching

## Purpose

Gemini's November 18 Round 12B architecture blueprint correctly identified
a specific weakness: a language model can cite source coordinates correctly
yet reverse who is goal-side or confuse car direction, distance and
possession. Its stronger two-ply "self-induced 1v2 exposure" recommendation
was not calibrated, however: a single airborne square-root recovery formula,
fixed turning penalties and rebound-point guesses do not justify a
\`TRAP_REACHABLE_BUT_NEGATIVE\` label.

This work provides the safe prerequisite, **RelationalInvariantsV0**:
small, reproducible, original-source-linked coordinate relationships at
each pre-decision node. It neither predicts a ball bounce nor chooses
a best play.

## User-facing feature

The existing AI coaching panel has a new optional collapsed section,
**Measured scene relationships (free, local, not coaching verdicts)**.
Selecting a source-backed real decision and pressing
**Inspect source-backed geometry** calls
\`POST /api/coach/scene-relations\` with \`mode:deterministic\`.
No model provider is contacted or charged. The panel displays
player/ball goalward ordering, planar distances, teammate spacing and
nose-to-ball angles, plus clickable original N#/E. telemetry source refs.
Missing source values become explicit unavailable metrics. This works
even when model use is disabled.

The same audited geometry is separately supplied as
\`scene_relations\` to the *existing* opt-in model request in
\`coach_model.propose_coach_draft\` after building the same
Stage1EpisodePacketV0. It is a third, bounded data field alongside
\`stage1_episode\` and \`tactical_options\`, not an independent
caller-supplied LLM message. It is always **predecision, source-linked,
not calibrated, and non-authoritative**. Neither the model's outbound
request privacy profile nor its one-call user consent changes.

## Source and derivation contract

Source:
- Only \`build_stage1_episode_packet(episode)\`, built with each node's
  own t_i cutoff and strict evidence whitelisting.
- For direct positions: \`N#/E.{role}.position\`,
  \`N#/E.ball.position\`; for nose orientation:
  \`N#/E.{role}.forward\`. Anonymous roles:
  focus, teammate, opponent_1, opponent_2.
- Requires a direct observation, a finite triple, matching recorded
  source timestamp at/before the node t_i, and
  \`replay_sample\` provenance. If a source carries
  \`stale_possible\`, the associated geometry *abstains*.
- Blue own goal = -Y; orange own goal = +Y. The
  \`longitudinal_goal_side_of_ball\` relation is **Y-coordinate ordering**
  (goalward/upfield/level). It does not establish a playable lane,
  actual defensive safety, a save, possession or "last man".
- \`planar_ball_distance\`, \`teammate_planar_separation\`,
  \`teammate_lateral_separation\` are Euclidean 2D geometry in
  unreal units; never intercept times or recoverability scores.
- \`nose_to_ball_angle\` is an XY-plane angle between the car's
  recorded *forward* vector and the direction toward the ball.
  It is **not** the player's camera, awareness, input, current
  air-turn feasibility or intention. A near-vertical forward vector
  or coincident ball position makes the angle unavailable.
- Metrics have \`source_refs\` pointing only to original N#/E...
  source IDs, status \`direct_coordinate_geometry_not_calibrated_tactics\`
  and an explicit caveat. Missing values have reasons, never 0
  substitutes. No game usernames, filenames, raw event text or
  player keys are emitted.
- Bounded to at most 22 metrics per node and 2–4 nodes.

The optional model prompt explicitly says it may use these *relationships*
to avoid reversing directions, but **may not quote the newly derived numeric
values as independently verified facts**: the existing claim verifier
only validates typed numeric predicates against the original Stage1 node
evidence. Model tactical quality remains \`needs_semantic_review\`;
no claim becomes expert validated by citing a geometry source.

## Why not implement Gemini's full 2-ply recovery debt as a verdict yet?

Gemini's proposed \`InteractionLookaheadV0\` assumes fixed turning
penalties, airborne fall time from square-root gravity alone, a single
rebound/spill point and a fixed 1.2s isolation threshold. In actual
Rocket League, boost trajectories, wall/contact dynamics, jump/flip
resources, landing orientations, corners and opponent choice can make
those estimates wrong. Earlier Round 11 evaluation also falsified
confident "robustly defensible" arrival-order categories.

The next iteration should fit **ranges** against actual replays and expert
falsification, not introduce hardcoded \`HIGH_VALUE\` or
\`TRAP_REACHABLE_BUT_NEGATIVE\` verdicts. Claude's independently
experimental \`CoachingReportV1\` must remain gated until the evaluation
supports it. We are not implementing a physics simulator or inventing
counterfactual trajectories here.

## Test coverage / falsification

New \`tests/test_relational_invariants.py\` covers:
- Blue and orange goal-side polarity (symmetry under team inversion);
- own/opponent longitudinal position, spacing, and nose-to-ball angle;
- stale source abstention and vertical-axis undefined angles;
- per-node time independence (N1 cannot use N2's values);
- invalid schema and future source timestamps being withheld;
- a real \`EpisodeEvidenceV0 → Stage1EpisodePacketV0\` transformation
  where rewriting every post-t0 frame/goal leaves geometry identical;
- real FastAPI local \`/api/coach/scene-relations\` with an optional
  provider disabled (HTTP 200), and rejected mode=model/experimental V1.

Updated \`test_round12_model_acceptance.py\` verifies the actual HTTP
model-transport stub receives \`scene_relations\` with original
N#/E. refs and no future, even though no real trained provider is called.
Updated Node VM tests in \`model-coaching-ui.test.mjs\` exercise zero-model
local inspection, source citation rendering, and stale responses after a
player change. Static UI contract checks preserve source-linked status.

These are **structural and mathematical engineering tests only**.
They do not establish what a GC2/SSL player should do.

## Integration for other agents

**Branch lineage:** #43 (Antigravity unified HD) → #44 (native safeguards)
→ #46 (Decision Lens) → #47 (actual opt-in model UI) → #48 (manual
missed-moment review) → this PR #49.

- **Claude** owns experimental tactical merit and prospective
  interaction-lookahead analysis. Do not treat these geometry outputs
  as validated recommendation labels, or sneak post-t0 outcomes into
  Stage1.
- **Antigravity** owns HD vehicle/camera/effects/native Game Stats API.
  The optional scene inspector is in the model-coaching panel and does
  not change HD bridge protocols. Preserve it when reconciling frontend.
- **ChatGPT** owns this read-only source-backed geometry, model prompt
  boundary and exact request schemas.
- **Gemini** independently audits proposals. Its earlier repository
  access disclosure said it did not inspect the source; this change is
  mapped to actual inspected modules and tested in the GitHub repository.

No \`main\` merge without owner approval. No user-uploaded replay is
required in CI; all fixtures are synthetic. Actual Windows replay,
native Rocket League, provider correctness and tactical merit remain
future hands-on acceptance steps.

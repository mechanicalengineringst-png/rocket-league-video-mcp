# Contextual review v1 - implementation and QA

**Status: experimental and not expert validated.** This is not a tactical correctness oracle, trained agent, camera-vision model or alternate-outcome simulator.

## What actually analyzes a Rocket League replay

1. Local `subtr-actor-py==1.5.1` decodes the native `.replay` to 30Hz ball/car state (positions, boost, rotation/forward, velocities) and timestamped events.
2. The old UI generated broad proximity and low-boost observations, and separately listed *all* 50/50 and goal events; those remain only in the **event browser**, not the coaching shortlist.
3. `coach_app.contextual_review.build_contextual_reviews` now derives a **maximum of four** opt-in-style contextual review leads per player with conservative conditions. No Gemini call or API quota is required.
4. The optional Gemini button analyzes **one user-selected six-second telemetry window** rather than sparsely summarizing the entire match. It receives only pseudonymized player aliases and positional/kinematic text (no raw replay file, gameplay video, player names, or platform IDs), and can return an empty list.

## First local situation classes (not proven mistakes)

- `shot_window`: a selected-player touch in a reasonable attacking lane, car facing goal, near-ground ball, visible keeper near goal with <=15 boost and <=350 uu/s horizontal velocity, with no second defender near the direct lane. Question: could a rapid shot have been feasible? NOT 'you should have scored'.
- `second_man_support`: teammate touch, focus player close and shallow, opponent pressure near ball, teammate remains near ball briefly. Anchored at the later decision point so no future confirmation is presented as known at the original touch. Question: would a deeper or wider recovery lane withstand a dunk? Close support can be correct.
- `defensive_pressure`: opponent touch while focus is near goal with <=12 boost, ball headed toward goal, a teammate upfield and opponents close. Question: was an earlier pad route feasible? Does not prove boost mismanagement.

The final list is ranked, limited to two of each class, and suppresses leads less than nine seconds apart. Identity mapping flagged uncertain, missing velocities/forward state, unsupported replay sources, absent native touches or ambiguous states cause an empty shortlist.

## Testing

Locally verified the standalone new module against 13 synthetic scenario/negative controls with pytest (all passed). The tests are committed as `tests/test_contextual_review.py`; the API integration regression is in `tests/test_api.py`, and the anonymization regression is in `tests/test_coaching.py`. Those full-repository tests and live UI have **not** been run in the user's Windows checkout yet.

Suggested QA from the `coach-app` directory:

```cmd
python -m pytest tests/test_contextual_review.py tests/test_api.py tests/test_coaching.py -q
```

Use two or more real `.replay` files. Switch coached player, select each review, inspect the playback 2-3 seconds before the timestamp and compare the numbers with actual viewer state. Verify that even 40 ordinary 50/50 events yield zero default coaching leads and that no view toggles / event history regress. Use a saved replay with uncertain player mapping; the engine should abstain rather than guess. No branch merges until manual findings are reviewed by the player or an expert.

## Known scientific and engineering limits

- The rules encode *possible useful questions*, not calibrated probabilities, causal claims or personalized mechanics.
- Replay event labels and timestamp alignment remain unvalidated against a wide hand-labeled real corpus; some parser events are still experimental.
- A close support car, low-boost keeper or low-boost defense is not automatically a tactical mistake.
- The current display has a separate accuracy problem: custom 3D cameras and geometry are not yet sufficiently faithful for judging flip timing, exact contact points or first-touch mechanics.
- The next valuable experiment is Claude's kickoff role labeling and masked expert review, followed by a few hand-confirmed contextual examples, not increasing the number of review flags.
- Some later events can be retrospectively classified. Do not feed those labels into pre-decision models or backdate observations; integrate the timestamp-aware evidence contract after agreement on its schema.

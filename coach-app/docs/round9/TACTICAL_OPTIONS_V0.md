# TacticalOptionsV0: decision-time options with evidence (Round 9)

`coach_app/tactical_options.py` takes a `Stage1EpisodePacketV0` and returns, for one decision node, the action families that were physically available, the evidence that supports and limits each, team context, unknowns and earlier-contributor hypotheses.

```python
analyze_tactical_options(stage1_episode_packet, *, focus_node_id=None) -> dict
```

The default node is the primary one. Input with any retrospective material raises `TacticalOptionsError`. The module never sees what the player chose or what happened. It never picks a single best option. It produces no expected values, probabilities, opponent intentions or execution rates.

## Representation: time relations, versioned in `POLICY`

All interactions are differences between kinematic lower bounds from `reachability`, read from the node's `E.reach.*` and `E.cover.teammate`:

| Quantity | Definition | Bands (`tactical-options-policy/0.1`, uncalibrated) |
|---|---|---|
| contest window | focus earliest touch − nearest opponent's | ≤ −0.15 s focus first · \|w\| ≤ 0.30 s even (genuine fifty-fifty) · ≤ 1.0 s late but close · else late |
| possession window | the same, sign flipped | focus first by ≥ 0.30 s → controlled touch available |
| spill support | second opponent − nearest opponent | ≤ 0.60 s: a loose ball is contested |
| cover margin | teammate goal-side time − nearest opponent's touch | ≤ 1.0 s: covered |
| immediate threat | nearest opponent touch ≤ 0.6 s, with the ball in or moving toward the own half | |

**Held-out check of the contest band.** In the real-replay demonstration below, the focus player made the next touch at different rates depending on the band. The next touch comes from the retrospective section and is used only to score the representation, never as input.

## Real-replay demonstration (`scripts/demo_tactical_options.py`)

The demonstration used 625 episodes from the 15 public 2v2 replays, all of unknown rank. Each episode has nodes at t−8, t−4 and t around a first-defender candidate t, so the moments are fixed offsets, not tactically chosen.

- **Claims check.** The existing `claim_verifier` rejected **0 of 8,185** claims. Every one passed the structural checks; all still need semantic review.
- **Truncation.** In **127 of 127** sampled episodes, deleting every frame and event after t gave an identical output.
- **Status.** 455 ok and 170 partial: teammate cover was unknown in 170, and an opponent's reach in 21.
- **Defensible options per episode.** 3 (70), 4 (63), 5 (258), 6 (209), 7 (25). The layer works as a menu with limits, not a judge. On these moments it rarely narrows below three options, so expert ratings are needed before any stance is shown as advice.
- **Held-out check of the contest band.** The next touch comes from the retrospective section and is used only for scoring:

| Band | Episodes | Focus player made the next touch |
|---|---|---|
| focus first | 29 | 97% |
| even | 184 | 42% |
| late but close | 369 | 22% |

  No "late" band appears, because the candidate rule only selects defenders within 1 s of the carrier.
- **Example.** One anonymised real output is in `tactical_options_real_example.json`. Full counts are in `tactical_options_real_replays.json`.

## Output schema (for ChatGPT's orchestrator)

```text
schema "TacticalOptionsV0", policy {...thresholds, version, note}, node_id, t0, information_cutoff_s, is_primary,
status ok|partial|abstain, abstain_reasons[str], uses_retrospective false, picks_single_best false,
state {carrier_slot, carrier_t, second_opponent_slot, second_opponent_t, focus_t, teammate_t, cover_t,
       contest_window_s, contest_band, spill_support_s, cover_margin_s, covered, second_opponent_close,
       immediate_threat, ball_rel_y, ball_to_own_goal_uu, ball_speed_toward_own_goal, focus_goal_side,
       teammate_goal_side, teammate_deeper_than_focus, focus_boost, low_boost, focus_on_ground,
       possession_available, teammate_can_play, claims{name: claim_id}}     # null = unknown
threats {immediate_threat, carrier_slot, second_opponent_close}
teammate_support {covered, teammate_deeper_than_focus, teammate_can_play, team_context_claims[], attribution}
options[] {action, physically_feasible yes|no|unknown, feasibility_claims[], supporting_claims[],
           limiting_claims[], severe_limit_claims[], strategic_stance, depends_on_teammate,
           defensive_risk elevated|not_elevated|unknown, team_context_claims[], depends_on_unobservable[]}
defensible_options[action], multiple_defensible
earlier_contributors[] {hypothesis_id, earlier_node, kind, observed_changes[{change_id, value, unit, known_at_s}],
                        evidence_refs, bears_on_actions[], status "hypothesis_unverified", would_need}
claims[]   claim_verifier records: {claim_id "N<k>.c<n>", epistemic_type, temporal_scope "PRE_DECISION",
           cited_evidence_ids (node-local), text, predicate_checks?}
unknown_claims[claim_id], unknowns[], not_observable[], layers{...}
```

- **Actions:** `immediate_challenge`, `controlled_fifty_fifty`, `fake_challenge`, `shadow_delay`, `goal_side_hold`, `rotate_through_small_pads`, `controlled_touch`, `clear_or_pass_to_space`, `yield_to_teammate`.
- **Stance rule:**
  - `not_available` if the action isn't physically feasible; `not_assessable` if feasibility is unknown.
  - `questionable` when there is a severe limit and fewer supports than limits.
  - `defensible` when there are supports and no severe limit.
  - `defensible_with_conditions` otherwise.

  Several defensible options are normal and are reported as such.
- **Using it in the orchestrator:**
  1. Verify `claims` with `claim_verifier.verify_stage1_claims(node_packet, claims)`. Every number in a claim's text has a matching predicate, so structural checks pass. Meaning still needs semantic review, as the verifier says.
  2. Explain options by citing claim ids.
  3. Present `earlier_contributors` as questions.
  4. In Stage 2, after Stage 1 is frozen, compare the retrospective observed action with `options` and `defensible_options`.

## Limitations

- **Thresholds and stances are hypotheses.** No expert has rated them, and the action list isn't exhaustive.
- **Feasibility rests on Round 5 reachability.** Lower bounds; walls abstain; landing and brake-turn models are weak; nothing tested on high-rank replays.
- **No outcome model.** The model has no contact geometry or ball destination per action, so "clear or pass to space" says nothing about where the ball would go. It has no pressure model beyond timing either.
- **Fake challenges.** These need the carrier's read, which is unobservable.
- **Unobservables.** Camera awareness, intent, comms, flip availability and spin are listed per action under `depends_on_unobservable` and are never asserted.

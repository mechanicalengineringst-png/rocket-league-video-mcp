# DecisionEvidenceV0: the pre-commitment evidence record (Round 7)

`coach_app/decision_evidence.py` → `build_decision_evidence(payload, t0, focus_id, *, context_s=3.0, selection=None) -> dict`.

The record **reuses Round 5 code**: `reachability.estimate_reach` for the four cars, `strategic_state.build_state` (run on a sanitised single-frame copy) for roles, race margin and cover, and `choices.classify_choice` for the retrospective action. It adds **no judgement**: no verdicts, probabilities or outcome predictions.

## Shape (what an integration layer or Gemini consumes)

```text
{
  "schema": "DecisionEvidenceV0", "t0", "frame_time_s", "lookback_s"?, "status": "ok|partial|abstain",
  "focus_slot": "focus", "slots": {"focus"|"teammate"|"opponent_1"|"opponent_2": {"team"}},
  "selection": {"rule", "values"},            # why this t0 was chosen (e.g. defender-candidate/0.1)
  "source": {...}, "rules": [...], "not_observable": [...],
  "evidence": [ {"id", "kind": "observation|derived|context_event", "value", "unit",
                 "source_time_s" (<= t0), "provenance": [...], "note"?} ],
  "unknowns": [ {"id": "U....", "what", "why"} ],
  "context":  {"window_s", "from_s", "event_ids": ["C.touch.1", ...], "excluded"},
  "retrospective": {"kind": "retrospective", "warning",
                    "observed_action": {"id": "R.observed_action", "label", "basis", "finalized_through_s"},
                    "next_touch": {"id": "R.next_touch", ...}, "goal_within_5s": {"id": "R.goal_within_5s", ...}}
}
```

## Evidence ids

Ids are deterministic paths and stay stable for the same replay, t0 and player:

- **Observed and derived state:** `E.ball.position|velocity|state_age`; `E.<slot>.position|velocity|forward|boost|jump_active|state_age`; `E.reach.<slot>`; `E.roles.own|opponents`; `E.race.margin`; `E.cover.teammate`.
- **Context:** `C.<event>.<n>` (touch, boost pickup, demolition, bump, numbered in time order inside the window) and `C.boost_change.<slot>`.
- **Unknowns:** `U.<...>`.
- **Retrospective:** `R.<...>`.

`resolve(record, id)` returns the item behind an id. `check_citations(record, ids)` rejects ids that don't exist, `U.` ids and `R.` ids used as decision-time support.

## Information rules (enforced and tested)

- **Pre-decision data only.** Frames and events at or before t0 only. Touch kind and strength, whiff, shadow and 50/50 labels are decided from later frames, so they are excluded from context.
- **Freshness.** A state unchanged for more than 0.1 s gets `stale_possible`. Boost always carries `freshness_unverified`.
- **Unknowns.** Missing, non-finite or out-of-arena coordinates, a demolished car, or out-of-range boost become `U.` items. They are never filled with zero or a guess, and every derived field depending on them becomes unknown too.
- **Boost.** 0 is a finite fact (empty). Unknown boost gives reachability both bounds.
- **Roles.** First and second come from earliest feasible touch. They are labelled `estimate`, or `ambiguous` when the gap is under 0.25 s, never stated as fact.

## Results

- **Tests.** `tests/test_decision_evidence.py` has 11 synthetic tests:
  - future rewrite and deletion;
  - unknown, zero and out-of-range boost;
  - NaN and out-of-arena coordinates;
  - no frame near t0;
  - stale state;
  - stable, resolving ids;
  - citation rejection;
  - no merit fields.
- **Real replays.** `scripts/check_decision_evidence.py` ran over all 636 first-defender candidates from 15 real replays, deleting every frame and event after t0:
  - **636 of 636 pre-decision parts were identical.**
  - Unknowns: teammate cover 156 (teammate airborne, on a wall or without heading), opponent reach 21, opponent car state 6.
  - 40 of 3,174 car positions were flagged `stale_possible`.
- **Example.** One anonymised record is in `results/decision_evidence_example.json`.

## Remaining unobservable or uncertain

- **Not in the replay at all:** what each player could see, inputs and intent, comms, ball spin, and whether a flip was available.
- **Not exposed by the parser:**
  - exact boost between replicated updates;
  - raw packet update ages (we can't prove a sample is fresh, only flag repeats);
  - parser-level resampling behaviour. This is evidenced as sample-and-hold, but not proven from raw packets; replicar's update-age columns could prove it.
- **Feasibility bounds are not tactical judgements.** Reachability and cover inherit Round 5's limits: walls abstain, the landing and brake-turn models are weak, and nothing has been tested on high-rank replays.

## What the episode-level consequence evaluator still needs

1. **Episode segmentation.** Possession sequences of 5–20 s with the decisive moment marked, so one t0 record becomes one step of an episode.
2. **`consequences(action)`.** For 2–4 feasible actions: outcome cones from contact geometry, and next-controlled-touch reachability per branch for all four cars.
3. **Pressure and recovery quantities.** The carrier's time to a controlled touch with and without the challenger; boost-to-recover-goal-side.
4. **Raw update ages.** Freshness from packet times (replicar or the decoder) to replace the repeat heuristic.
5. **Claim-level entailment.** The next validator must check that each explanation sentence's claim matches the cited item's value, not only that the id exists.
6. **Expert tactical-merit labels.** Separate from the 40-clip timing study, so any interpretation built on this record can be calibrated.

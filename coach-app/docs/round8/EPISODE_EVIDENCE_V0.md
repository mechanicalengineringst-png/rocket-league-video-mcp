# EpisodeEvidenceV0: a chronological episode of decision records (Round 8)

`coach_app/episode_evidence.py` composes 2–4 unchanged `DecisionEvidenceV0` records from one manually selected 5–20 s window. It makes no judgement, has no probabilities, values or regret, and simulates no opponent choices.

## API

```python
build_episode_evidence(replay, focus_id, decision_times, episode_start_s, primary_t0, *, label=None) -> dict
stage1_view(episode) -> dict      # the episode without "retrospective": all a Stage 1 reasoner may see
all_ids(episode) -> list[str]     # every addressable id (unique by construction; tested)
resolve(episode, gid) -> dict|None  # N<k>/E.., N<k>/C.., D.., T.., H.. ; unknown and R. ids -> None
```

`EpisodeError` is raised when:
- the request has fewer than 2 or more than 4 decision times;
- `primary_t0` is not the latest decision time;
- the window is outside 5–20 s;
- the focus player is unknown.

## Record

```text
schema "EpisodeEvidenceV0", episode_id (hash of replay title, focus, window, times; no platform ids),
status ok|partial|abstain, slots, window {start_s, end_s, length_s, selection, stage1_horizon_s = primary_t0},
nodes[]     {node_id N1.., t0, is_primary, status, information_cutoff_s = t0,
             snapshot = the DecisionEvidenceV0 record WITHOUT its retrospective (ids unchanged)},
relations[] {from, to, "precedes", gap_s},
changes[]   {id D.<Ni-Nj>.<field>, value, unit, refs [N<k>/E...], known_at_s = later node's t0, note},
timeline[]  {id T.<type>.<n>, type, t, slots, provenance}   (touch, boost pickup, demolition, bump in the window,
                                                             later-frame attributes excluded)
unknowns[]  node unknowns as N<k>/U..., plus UD.<pair>.<field> {what, why, refs} for changes that cannot be computed,
possible_earlier_contributors[]  {id H.<n>, earlier_node, concerns_node, question, evidence_refs,
                                   status "hypothesis_unverified", not_established},
retrospective {stage 2, warning, nodes {N<k>: observed action, next touch, goal, with ids N<k>/R...}}
```

## How the information rules are enforced

- **Node cutoff.** Each node's snapshot is built from the replay with every frame and event after that node's t0 deleted. Only the retrospective block is built from the full replay.
- **Changes.** Change summaries compare snapshots: boost, displacement, up-field advance, team spacing, role estimate, earliest feasible touch and teammate cover. Each is marked `known_at_s` = the later node. If either end is unknown, it becomes `UD.` with the `U.` refs that blocked it.
- **Contributor prompts.** These are neutral questions raised by coarse, stated triggers:
  - focus boost falling by 30 or more between nodes;
  - focus advancing up-field by 1,500 uu or more;
  - the estimated first player changing;
  - teammate cover time growing by more than 0.5 s;
  - a bump or demolition involving the focus team.

  Each cites the ids that raised it and states that causation is not established.

## Results

- **Tests.** `tests/test_episode_evidence.py` has 10 synthetic tests:
  - stable episode and node order, including when the times arrive unsorted;
  - refused invalid requests;
  - per-node cutoffs;
  - future rewrites that leave `stage1_view` identical;
  - rewriting after N1 that changes N2 but not N1;
  - unknown boost and NaN positions staying unknown;
  - a missing decision frame giving `partial`, or `abstain` when it is the primary node's;
  - outcomes confined to `retrospective`;
  - hypotheses that are neutral and resolve to real evidence;
  - unique ids, with node-local ids preserved.
- **Real replays.** `scripts/check_episode_evidence.py` built 625 episodes from the 15 real replays. Nodes were at fixed offsets t−8, t−4 and t for each first-defender candidate t, so the episodes are not tactically chosen.
  - **625 of 625** stage-1 views were identical after deleting every frame and event past the primary t0. Every record had unique ids and was valid JSON.
  - 23,522 change items; 2,728 changes left unknown (`UD.`); 1,372 hypothesis prompts.
  - Results are in `episode_evidence_check.json`.
- **Bug found and fixed in `DecisionEvidenceV0`.** When both players on a team were out of the 4 s reach horizon, the role gap was inf − inf = NaN, which isn't valid JSON. It is now an unknown (`U.roles.<team>`), with a regression test. The contract is otherwise unchanged.
- **Example.** A synthetic episode is in `episode_evidence_example.json`. Blue One pushes up-field, spending 40 boost; Orange counters; the primary node is at 10 s.
- **PR #27 compatibility.** ChatGPT's unmodified `build_stage1_packet` (#27 head `fd3331e`) accepted each node `snapshot` of the example as is.

## For ChatGPT's reasoning integration

- **Stage 1 input.** Use `stage1_view(episode)`, or apply `build_stage1_packet(node["snapshot"])` per node and add the episode's `relations`, `changes`, `timeline`, `unknowns` and `possible_earlier_contributors`.
- **Citations.** Cite node facts as `N<k>/<local id>` and episode facts by their `D.`, `T.` and `H.` ids. `UD.` and `U.` ids are caveats.
- **Retrospective.** `retrospective` (with `N<k>/R.` ids) is Stage 2 only, after Stage 1 is frozen.
- **Hypotheses.** `H.` items are questions to test, never conclusions. A Stage 1 answer must not upgrade one to a cause.

## Not built (out of scope here)

- Automatic window and decision selection.
- Possession segmentation.
- Outcome branches per action, pressure and recovery quantities, and raw update ages.

`DecisionEvidenceV0` limits carry over: vision, inputs, comms, spin and flip availability are unobservable, and wall cars abstain on reachability.

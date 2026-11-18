# First-defender candidate manifest: contract for the 40-clip commitment study

**Producer:** `coach_app.choices` (Claude, PR #22). **Consumers:** `evaluation/commitment_review.py` (ChatGPT, PR #16) and the clip exporter (Antigravity).

## Why this exists

The study's 15/15/10 strata need **shadow** and **unclear** clips. Until now, no pipeline produced them without hand-picking: challenge cases exist only because a 50/50 happened later. This detector picks moments by a rule evaluated **at t0 only**. All three outcomes (challenge, shadow, other) come out of the same rule.

## Eligibility rule `defender-candidate/0.1` (t0 frame only)

A player P is a candidate at t0 when all of these hold:

1. All 4 cars are present, P is on the ground, and it is not a kickoff setup.
2. An opponent's earliest feasible touch (reachability lower bound) is **≤ 0.5 s**: someone is about to play the ball.
3. P's own earliest feasible touch is **≤ carrier + 1.0 s**: P could genuinely contest.
4. P is the first defender of their team: P's earliest touch is ≤ the teammate's.
5. The ball is in P's half or midfield: **y ≤ +1500** in P's team frame.
6. P is **goal-side**: P's y is ≥ 200 uu nearer the own goal than the ball.
7. Debounce: at most one candidate per player per 3.0 s. Only earlier candidates are consulted.

The scan steps every 0.1 s. t0 is the exact time used for the frame lookup.

**Invariant:** deleting every frame after t0 gives the same candidate with identical eligibility values. This is tested in `tests/test_defender_choices.py` and checked on all real candidates by `scripts/benchmark_choices.py`.

## Retrospective choice (`observed_action`, finalized at t0 + 1.5 s)

| Label | Rule over (t0, t0 + 1.5 s] |
|---|---|
| challenge | P touches the ball (decoder `touch`), or comes within 260 uu of it |
| shadow | No touch; P goal-side in ≥ 80% of frames; distance 500–2500 uu at the end |
| retreat | No touch; P goal-side; moved > 800 uu toward own goal; > 2500 uu from the ball at the end |
| boost | No touch; P gains ≥ 20 boost while staying > 800 uu from the ball |
| unclear | Anything else, a reset or goal inside the window, or the car missing for > 30% of frames |

`detector_choice` in the manifest maps these as follows: challenge → `challenge`, shadow → `shadow`, everything else → `unclear`. The finer label stays in the private sidecar.

## Rows (exactly PR #16's `validate_manifest` fields)

```json
{"case_id": "dc-<12 hex>", "replay_group": "match-<8 hex>", "detector_choice": "challenge|shadow|unclear",
 "source_t0_s": 123.4, "clip_start_s": 119.9, "clip_end_s": 125.9, "clip_file": "dc-<12 hex>.mp4",
 "focus_hint": "Follow the marked blue car"}
```

- **case_id** is a hash of match, player and t0. It contains no platform ID or name.
- **clip_start_s** = t0 − lead-in. The lead-in is deterministic per case, uniform in **2.5–4.5 s**, which satisfies #16's anti-anchoring check (spread ≥ 0.75 s, at least 4 quarter-second buckets).
- **clip_end_s** = t0 + 2.5 s, capped at 0.5 s before the next goal. Cases where a goal follows within 1 s of t0 are dropped, so no outcome is shown.
- **focus_hint** follows #16's fixed vocabulary.

The private sidecar (`PRIVATE_candidate_provenance.json`, never committed) holds, per case:
- player id;
- rule version, eligibility values and `eligibility_frames_used_through_s`;
- fine choice label, its basis and `choice_finalized_through_s`;
- clip lead-in.

## What the exporter must do (Antigravity)

For each row, render `[clip_start_s, clip_end_s]` of the source replay to `clip_file`:
- Mark the focus car with an outline or marker only.
- No player names, scoreboard, boost meters of other players, or goal or replay banners.
- Ball cam off, a fixed camera behind the focus car, the same for every clip.

Do not re-time clips. The lead-in jitter is part of the blinding.

## Generate

From `coach-app/`:

```
python scripts/benchmark_choices.py CACHE_DIR docs/round5/results/choices_benchmark.json PRIVATE_OUT_DIR
```

`CACHE_DIR` holds parsed replays (`scripts/benchmark_reachability.py` writes them). `PRIVATE_OUT_DIR/PRIVATE_candidate_manifest.json` is the manifest. Keep it out of git.

# Round 5, checkpoint 3: strategic state, actual choices, one interpretation

## A better representation: time, not distance (`strategic_state.py`)

The state at t0 is expressed in **seconds** from the reachability engine:

- **Team race margin:** the fastest opponent's earliest touch minus the fastest teammate's, with a pessimistic-to-optimistic range.
- **First and second player by feasible touch time**, not by field position.
- **Teammate cover:** zero if the teammate is already between the ball and the own net. Otherwise, the time to get there.
- **Boost per car**, with unknowns listed.

**Why it's more informative, measured on 15 real 2v2 replays:** at 2,663 live moments, the score predicted which team touches the ball next (within 3 s, held out). The time margin had an **AUC of 0.815**; the distance margin had **0.746**. Same moments, same t0 frame, no fitted parameters.

## Shadow / non-challenge candidates and actual choices (`choices.py`)

The independently specified rule is in [MANIFEST_CONTRACT.md](MANIFEST_CONTRACT.md). It flags a goal-side first defender who could contest an opponent about to touch the ball. The rule reads only the t0 frame; what the player did next is a separate retrospective label.

| On 15 real replays | Result |
|---|---|
| Candidates | 643 |
| Retrospective choices | challenge 365 · shadow 143 · retreat 10 · boost 9 · unclear 116 |
| Agreement with the decoder's own `shadow_defense` events (an independent classifier) | 49% of our shadows have one (70 of 143), vs 10% of our challenges (37 of 365) |
| Manifest rows / matches | 636 / 15 (challenge 361, shadow 142, unclear 133) |
| **PR #16's unmodified `validate_manifest` + `prepare_packets` (head `1cad293`)** | **Accepted all 636; built the 40-clip pilot at 15/15/10 across 15 matches** |
| Frames after t0 deleted, eligibility and state re-decided | **643 of 643 identical** |

## Tactical reasoning on the new engine

- **Shots, challenges and last-man readings use kinematic times.** All arrival times in `tactical_analysis.py` now come from `reachability.py`. A defender whose time is unknown (airborne, on a wall, no heading) makes the net "unclear", never "open". Challenge abstentions rose from 10 to 46, because wall cars are no longer guessed.
- **New first-defender reading** (`defender_decisions.py`) on the candidates above. It has three separate layers: what was *feasible* at t0, what the player *chose* (retrospective), and what *happened* (never used). It uses two factors in time, contest-in-time and teammate-can-cover, and one stated principle. That principle is written into every interpretation as a hypothesis, not a rule. It explicitly rewards **high-value restraint**: holding back when a challenge would be late or uncovered.

| First-defender reading (639 real moments\*) | Count |
|---|---|
| Shadow or retreat when late or uncovered → reinforce | 114 |
| Challenge in time with cover → reinforce | 103 |
| Challenge with part of the support missing → tradeoff | 108 |
| Shadow when a covered 50/50 was available → tradeoff | 4 |
| Late, uncovered challenge → risk_hypothesis | 60 |
| Unknowns → abstain | 124 |
| Boost/unclear → describe only | 126 |

\*From the audit run before a fix that rounds the scan time once, so the recorded t0 is exactly the frame-lookup time. The fix added 4 candidates (643). An earlier run without it matched 617 of 639 under truncation; the 22 mismatches were half-millisecond rounding cases.

| Existing decision cases (1,012) | Before (Round 4) | Now |
|---|---|---|
| Challenge: reinforce / tradeoff / risk / abstain | 139 / 249 / 8 / 10 | 122 / 233 / 5 / 46 |

**Truncation invariance on real data:** with every frame after t0 deleted, 251 of 251 sampled decision-case readings and 639 of 639 first-defender readings were identical.

## One interpretation per moment (`coaching_view.py`)

- **What the player sees.** `/api/decision-cases {"analyze": true}` now returns a single `coaching` block. It contains a display stance (support, neutral, concern, disputed, abstain or describe), the three layers, the unknowns, and a `baselines.rule_v1` entry flagged `shown_to_player: false`.
- **Which system leads.** The t0 reading is primary. When an explicit rule verdict opposes it, the moment is `disputed`: no verdict is shown, and it is flagged for expert rating. A one-step difference shows the cautious stance.
- **What the real-data audit found.** After Round 4, the rule system **never takes an explicit position on real cases**. All 1,012 cases got non-committal labels. Treating those as "neutral votes" would have silently hidden every reading. That was the first policy, and the audit showed it, so non-committal labels now count as *no opinion*. The rule verdict is a preserved baseline, not a second opinion. The disagreement path is covered by synthetic tests, but on these replays no real case ever reached it.

## Limitations

- **The decision table is a hypothesis about one principle.** Expert ratings may say that, at high rank, more uncovered challenges are correct (pressure styles).
- **The cut-offs are not calibrated.** The contest window (0.3 s), the cover window (1.0 s) and the goal-side point are the two thresholds and one geometric choice to fit from #16 ratings.
- **The choice classifier is rule-based and unvalidated.** "Unclear" (117) is common, and fakes are not detected.
- **The data has not changed.** These are the same 15 public test replays, of unknown rank.

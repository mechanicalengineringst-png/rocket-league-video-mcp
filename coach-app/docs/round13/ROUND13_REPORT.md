# Round 13: does our tactical architecture know what matters? (research, code, results, unknowns)

Branch `feature/round13-tactical-intelligence-innovation-20261118`, from PR #52 `cfc5b2a`. Draft PR: see the PR body.
All data is the cached public cohort: **15 two-versus-two replays of unknown rank (about 96 minutes)**. No expert labels exist.
Nothing in this document is evidence of tactical accuracy at Grand Champion level. Every claim below is a measurement
on that cohort or a test result. Each is labelled as **[research]**, **[code]**, **[result]** or **[unknown]**.

## 0. What we learned, in one paragraph

The Round 10–12 engine is built on one quantity: who can touch the ball first. On held-out matches, that quantity
predicts the next touch reasonably well (AUC 0.78). It predicts defensive danger in the next 5 s almost not at all:
AUC 0.55 once the ball is away from our goal.

The full decision-time state does far better: 0.83–0.86 for the next touch and 0.87–0.88 for danger. The extra
information is mostly where the ball is going and where the *second* players are. That is exactly what the ledger
under-reads.

Three things I expected to help failed when tested:
- a physics counterfactual simulator;
- field-control maps used as predictive features;
- scenario retrieval on this data.

The cohort also gives no measurable support for single-moment "questionable" verdicts. The teammate-cover estimate
survives as a genuinely discriminating signal. Habit rates, the owner's preferred unit, are mostly *unreliable
within one match*: they need several matches before they describe a player.

So the coaching architecture changes order: habits measured across many matches with a reliability gate, then
turning points (sequence level), then single decisions as decision-time reads with no mistake labels.

---

## 1. Architecture comparison [research + result]

| Approach | What it can contribute | What we found on the cohort | Decision |
|---|---|---|---|
| **Condition ledger** (R11–R12) | Explainable reasons/defeaters; honest uncertainty; abstention | Its inputs (reach, boost, goal-side, cover) predict the next touch (AUC 0.81) but not danger (0.75). Several premises fail falsification (§3). | Keep as the *explanation* layer for single decisions, with the r13 adjustments; stop issuing mistake labels from it |
| **Scenario retrieval** (kNN over situations) | "In situations like this, players did X"; intuitive examples | Below logistic regression on every target (next touch 0.80 vs 0.83, danger 0.88 vs 0.90). It also only reflects what unknown-rank players did, not what is right. | Not used. Worth revisiting **only** with a large high-rank corpus |
| **Physics counterfactuals** (simulate action families) | "What if you had shadowed instead?" without outcomes | The family simulator is *worse* than constant velocity at the 0.5 s pre-contact horizon (216 vs 184 uu median error). The value ordering it feeds preferred challenging in 90% of the cases where the ledger preferred holding. | **Failed hypothesis.** Code kept for research; not used for any judgment |
| **Learned value estimation** (future control) | Measures what matters for the next seconds; ranks states; finds turning points | Validated on held-out matches: next touch AUC 0.82, danger AUC 0.89 (logistic); GBM 0.86 / 0.92 | Adopted for **ranking and attribution only**; never shown as a probability |
| **Observational action value** (commit vs hold, adjusted, placebo-controlled) | Data-based test of whether a choice changes the next seconds | No adjusted difference in 5 s danger (−0.002, 95% CI −0.013..0.009). Goals against within 10 s +0.026, but the placebo control (+0.008, and 0.027 in the "hold over challenge" subgroup) shows comparable confounding. | Used as **evidence against** single-moment criticism. Not a coaching signal |
| **Model-based LLM reasoning** | Wording, prioritisation, cue phrasing | Not re-tested this round (no paid calls). The R12 contract keeps it to rewriting validated text. | Unchanged, optional |
| **Expert-derived principles** | Encodes what GC/SSL players know | None available. Every threshold is still a heuristic. | The missing ingredient. §7 lists the exact expert study |
| **Hybrid adopted (V2)** | Habits (rates) + learned control timeline (sequences) + ledger (explanation) + physical context (aerial/wall) | See §5 | Implemented as `CoachingReportV2` (experimental, opt-in) |

## 2. What predicts the next seconds? [result]

`scripts/future_control_study.py`; data from `scripts/build_state_dataset.py`. There are 17,344 rows (every 0.5 s,
both team perspectives, dead balls excluded). Evaluation is leave-one-match-out, 15 folds. Files:
`docs/round13/future_control_study.json` and `..._danger_from_outside.json`.

| Model | Next touch (AUC / log loss) | Danger 5 s, ball ≥ 3000 uu from our goal (AUC) | Goal against 10 s (AUC) |
|---|---|---|---|
| Base rate | 0.50 / 0.693 | 0.46 | 0.40 |
| **Physics: first-arrival margin only** (R10–R12 core) | 0.78 / 0.582 | **0.55** | 0.51 |
| All reach features | 0.80 / 0.548 | 0.58 | 0.51 |
| "Ledger-like": reach + boost + goal-side + recovery debt | 0.81 / 0.540 | 0.75 | 0.65 |
| Logistic, all features (shipped as FutureControlModel V0) | 0.83 / 0.511 | 0.87 | 0.68 |
| GBM, all features (research only) | **0.86** / 0.465 | **0.88** | **0.71** |
| Scenario retrieval (kNN, k=50) | 0.80 / 0.553 | 0.84 | 0.66 |

- **The ledger is nearly blind to defensive danger.** For danger the GBM's gain importance is ball 71%, players 21%, reach 5%. For goals against it is players 52%. The top player features are the *second* players' depth relative to the ball and their boost (`opp2_y_rel_ball`, `own2_y_rel_ball`, `own2_boost`, `opp2_boost`). Second-man positioning and boost matter more for conceding than first-to-ball.
- **Field control adds almost nothing as a predictor.** Removing it from the GBM changes next-touch log loss by 0.002. My hypothesis that control maps are a missing signal is **falsified** for prediction. They remain useful for *explaining* a position in physical terms.
- **The learned model is well calibrated** on held-out matches (reliability bins within ±0.03).
- Caveats: consecutive rows are correlated, the cohort is small, and its rank is unknown.

## 3. Falsifying Round 10–12 assumptions [result]

`scripts/falsify_round13.py` → `docs/round13/falsification_study.json`.

| Assumption | Test | Result | Verdict |
|---|---|---|---|
| Reach `t_min` is a **lower bound** | At 0.5–2.0 s before 4,300+ real touches, was the toucher's `t_min` ≤ the time they actually took? | Ground touches broke the bound in 11% (0.5 s lead), 8%, 18% and 24% (2.0 s lead) of cases; by more than 0.3 s in up to 9%. Airborne touches: 4–6%. | **Partly falsified.** Players are often faster than modelled (flips, boost, wavedash). "The opponent cannot get there" is unsafe at longer leads |
| Arrival model on real motion | Is each car's actual position 1 s / 2 s later reachable in that time? | Too slow in 13% / 15% of cases; by more than 0.3 s in 4% / 9% | Acceptable for region shares; not for tight single claims |
| Opponent intent from closing speed (R12 "not committing") | Does the nearest opponent touch next within 1.5 s? | Reach time is the better predictor (AUC 0.86 vs closing 0.72). At reach < 0.5 s, a slow-closing opponent **still touched next 46% of the time** (67% when closing fast). | **Falsified at close range.** The r13 ledger downgrades it to within-error there (§4) |
| Teammate cover estimate + 1.0 s window | Did the teammate actually meet the same goal-side test within carrier time + 1.0 s? | Holds: 94%. Within error: 44%. Fails: 19% (346 / 165 / 103 first-defender situations). Timing error median −0.19 s (IQR −0.69..+0.82). After an opponent touch in our half the ball reached our goal zone in a median 0.74 s (p75 1.64 s). | **Survives.** It discriminates strongly. 38% of first-defender moments are "unknown" (teammate airborne etc.), an honest but large abstention |
| Observed-action labels | Stability when the window changes; agreement with the independent Round 5 classifier | 94.5% same family at 2.0/2.5/3.0 s; 83% agreement with Round 5 when both label; 18% unlabelled | **Reasonably stable.** The biggest disagreement is touch vs shadow (192 cases) |
| "Questionable" means a worse decision | (a) value-model regret by verdict; (b) adjusted commit-vs-hold effect by ledger verdict | (a) Median regret is 0 for every verdict; the counterfactual value can't separate them. (b) In "hold over challenge" situations, committing went with +0.039 goals against in 10 s, but the placebo showed +0.027 there. | **Not supported.** "Questionable" is a rule opinion with no measured consequence in this cohort. V2 removes the label |

## 4. What the code does now [code]

New modules (`coach-app/coach_app/`):
- `field_control.py`: vectorised per-car arrival times over a 256 uu grid. It is fitted to `reachability.ground_time` with held-out median error 0.16 s and p90 0.97 s (`docs/round13/field_control_calibration.json`). It gives team control by region and recovery debt, at 0.7 ms per frame.
- `state_features.py`: team-mirrored decision-time features in four groups (ball, reach, players, control). Mirror invariance is tested.
- `value_model.py` with `models/future_control_v0.json`: a numpy-only logistic FutureControlModel V0 (next touch, danger). Its held-out metrics are stored inside the model file.
- `counterfactual.py`: pre-contact action-family simulation. Experimental; **failed validation**, used by no judgment.
- `control_timeline.py`:
  - the learned control score every 0.5 s;
  - turning points, the largest 2 s changes in both directions;
  - leave-one-player-out attribution of each change;
  - dead balls are excluded.
- `habit_profile.py` with `models/habit_reference_v0.json`: ten whole-match habit rates with examples, reference percentiles and a **reliability gate** (a standout is flagged only with enough matches).
- `coach_report_v2.py`, `coach_report_v2_render.py`: CoachingReportV2.
- `situation_rationale.analyze_situation(..., ledger="r13")`: Round 13 adjustments that only move statuses toward uncertainty. The R12 default is unchanged and tested.

Interfaces:
- `POST /api/coach/coaching-report-v2`: a separate route with capability flags (`coaching_report_v2*`); opt-in, local, no model.
- `scripts/coach_replays_v2.py A.replay B.replay ... --player NAME --md out.md`: one player across many local replays.

Research scripts: `build_state_dataset.py`, `future_control_study.py`, `train_value_model.py`, `calibrate_field_control.py`, `falsify_round13.py`, `counterfactual_study.py`, `action_value_study.py`, `habit_reliability.py`, `benchmark_round13.py`.

Tests: `tests/test_round13.py` (16 new) plus every existing test. Full suite: see the PR body for the exact run.

## 5. CoachingReportV2 vs Round 12 [code + result]

What changed for a player reading the report:
1. **Habits first.** Ten rates, each with its number of instances, a reference percentile and example times, for example "last back with under 20 boost" or "you and your teammate both within 1500 uu of the ball". A standout is flagged only when enough matches back it.
2. **Turning points.** The largest changes in the team's expected control, gains as well as losses. Each shows how much *your movement* accounts for it, plus the decision-time read of your last decision before the first touch. Aerial/wall cases show physical commitment context: recovery debt and own-goal-zone control.
3. **Single decisions.** The R12 Stage A ledger with r13 adjustments. Stage B says "matched the rule read", "defensible if" or "went against the rule read (unconfirmed: review, not a mistake)", never "questionable".
4. **Evidence-status table** in every report: what is validated, downgraded or failed.

**Benchmark on the cohort** (`scripts/benchmark_round13.py` → `docs/round13/benchmark_v2_vs_v1.json`; 60 player-match reports):

| Measure | R12 (V1) | R13 (V2) |
|---|---|---|
| Single-decision findings (same ranking) | 360 | 360 |
| Retrospective "questionable / risky / debatable" | 49 | 0 (47 "went against the rule read, unconfirmed") |
| Habit standouts flagged from a single match | n/a | **0** (174 would have been flagged without the reliability gate) |
| Turning points | n/a | 240: **120 gains / 120 losses** |
| Turning points linked to a decision-time read | n/a | 213 (77 of them aerial/wall, all with physical commitment context); 27 had no prior decision situation |
| Attribution stability when the 2 s window shifts by 0.5 s | n/a | Pearson 0.70; same sign 85% |
| Stage A identical when the replay is cut at t0 | 180/180 (R12) | 120/120 |
| r13 ledger adjustments among selected findings | n/a | **0** (the close-range intent case is rare among top-ranked moments) |
| Player names or IDs in output | 0 | 0 |
| Mean runtime per player-match | 27 s | 51 s |

**What this shows honestly:**
- V2 does not make single-decision reads more accurate. It removes unsupported mistake labels and adds two layers the data supports better: whole-match habits (gated by reliability) and sequence-level turning points (balanced between gains and losses, and moderately stable).
- The r13 ledger change is real but rarely reaches the selected findings.
- Aerial and wall play sits behind about a third of the turning points the focus player most affected, which is where the missing mechanics hurt most.

An anonymised real-replay example: `docs/round13/EXAMPLE_V2_REAL.md`.

## 6. Failed or weakened hypotheses [result]

1. *Field-control maps are a missing predictive signal.* No: about 0 gain beyond positions.
2. *A physics simulator can compare action families before contact.* No: worse than constant velocity, and the value ordering always favours moving toward the ball.
3. *Scenario retrieval can stand in for a coach on this data.* No: weaker than logistic, and it reflects unknown-rank behaviour.
4. *Closing speed reveals opponent intent.* Not at close range.
5. *Reach `t_min` is a safe lower bound.* Not at 1.5–2 s leads on the ground.
6. *R12 "questionable" verdicts point to worse decisions.* Not measurable in this cohort.
7. *One match is enough to describe a player's habits.* No for most metrics (split-half Spearman −0.21..0.45). The exceptions are "both near the ball" (about 2 matches needed), "last back with low boost" and "first-defender commit when the teammate is not back" (about 3 each).

## 7. What still needs human expert validation [unknown]

These are things the code cannot settle; each names the check that would.

1. **The ledger's rules**: run the blind two-stage merit study (R11–R12 harness). It needs GC+ raters on the first-defender strata first, then on the new classes.
2. **Turning-point attribution**: is "your movement lowered control" the thing a coach would point at? Show 20 turning points to an expert alongside the clip.
3. **Habit meaning**: whether a high "both near the ball" rate is a problem depends on team style and rank. It needs reference data at the owner's rank (his own matches and teammates') instead of an unknown-rank cohort.
4. **Rank calibration of every threshold**: low boost 20/30, cover window 1.0 s, room 2500 uu, pressure 0.8 s.
5. **Aerial, wall, backboard, flip-reset and 50/50 mechanics**: we still model none of them, only their positional context.
6. **Teammate intent and communication, and opponent adaptation within and across series**: not measured this round.

## 8. How the owner can test this on ranked replays

```
cd coach-app
python scripts/coach_replays_v2.py "C:\replays\*.replay" --player YOURNAME --md v2_report.md
```

Combine 5 or more of your own matches; habits only become meaningful then. For each turning point and decision read,
note: right moment? right attribution? would you act on it? The R12 single-match report
(`scripts/coach_replay.py`) remains available for comparison.

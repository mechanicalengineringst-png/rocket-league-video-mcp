# Round 12: from defensive ledger to situation-aware coaching findings

Branch `feature/round12-coaching-intelligence-20261118`, draft PR #45, based on the PR #40 head (`f05f73e`).
Everything new is **experimental, opt-in and not expert-validated**. Default APIs are unchanged, and V1 stays off by default.

## 1. What was wrong with the previous architecture (Phase 1)

Reviewing Rounds 7–11 against the questions in the assignment turned up six structural problems:

1. **One decision type for everything.** ActionRationaleV0 and TacticalOptionsV0 judge every moment with first-defender vocabulary: challenge, 50/50, shadow, hold and so on. The review-bundle selector picks moments by observational salience (the largest state change). On the cohort, **438 of 480** old candidates were not first-defender moments by our own t0 classifier. Possession, second-man play and recovery were being judged with the wrong question.
2. **Capability was treated as intent.** "The opponent could touch first at 0.27 s" was read as "the opponent is going for it". In real replays this produced false criticism: a player challenged a ball that the opponent with a faster earliest-touch time was driving away from.
3. **No value of the ball after a contact.** We knew who could arrive first, not what a contact achieves. I built and calibrated a contact model (below). The honest result: the outgoing direction is predictable after the fact, but **who gets the next ball cannot be predicted better than the base rate**. That is now a named, unobservable assumption rather than a hidden simulation.
4. **No boost or route model.** "Low boost" was a single threshold. There was no comparison of the direct route, small pads and a big-pad detour, and no check on pad availability.
5. **Outputs were not coaching.** CoachLessonV0 returns verified observations ("Recorded focus boost was 98.4") and an `undetermined` grade. There is no interpretation, no comparison of alternatives and no takeaway, by design and for good safety reasons. The safety machinery was right; what it lacked was a reasoning layer that turns the evidence into specific, checkable advice.
6. **Selection was not tied to teachability.** Salience meant "something changed", not "a decision fell on you, the options differed, and we can measure what decided it".

What I kept, because it held up: decision-time integrity (t0 truncation), evidence ids and the claim verifier, the Round 11 margin band (0.30–0.55 s, so order inside it becomes `within_error`) and the condition/reason/defeater ledger. The ledger's structure is sound; it needed the right conditions per situation.

## 2. Architecture (Phases 2–5)

```
replay ─► situations.discover_situations      t0-frame classifier, 7 classes, dead-ball/kickoff excluded
        ─► (per situation) prefix(replay, t0)  frames/events ≤ t0 only
        ─► episode_evidence ► Stage 1 packet   (Round 7–8, unchanged)
        ─► situation_rationale.analyze_situation
              base conditions (Round 11, margin band) + class-specific conditions + Q.* derived quantities
              class-specific actions: reasons / defeaters / decisive information
        ─► moment_ranking.rank                 t0-only salience: responsibility, teachability, sufficiency,
                                               recurrence; one finding per pattern first; never outcomes
        ─► coaching_findings.build_stage_a     situation, readings with numbers, interpretation, options with
                                               gains/preserves/sacrifices/risks, assumptions, takeaway
        ─► validation                          claim_verifier on every claim + every number traced to E./Q.
        ─► coaching_findings.build_stage_b     (separate) observed action, verdict vs t0 ledger, outcome shown
        ─► patterns                            observed actions vs ledger across the match (no outcomes)
        ─► reasoner_contract (optional)        model rewrites Stage A / B; fail-closed validator; opt-in transport
```

**Situation classes** (`situations.py`): `first_defender`, `possession`, `offensive_first_man`, `second_man_support`, `loose_ball`, `recovery_and_boost`, and `aerial_or_wall`. The last is observation-only: about half of decoder touches in the cohort are airborne and we do not model aerial or wall mechanics.

**New conditions** (`situation_rationale.py`), each computed from t0 data, with derived quantities that list their inputs and formula:

| Class | New conditions |
|---|---|
| Possession | pressure time (nearest opponent's earliest touch); shooting range; shot lane (9 lines and the defender's margin to the line); teammate forward option; play uncovered if lost |
| Recovery | direct time to the goal-side point; big-pad detour extra time (pad availability from pickups ≤ t0 with 10 s / 4 s respawn); available small pads in a 700 uu corridor; threat now |
| Second man | double-commit risk (closing speed and order); whether *you* could cover if your teammate is beaten; a boost route that still reaches goal-side in time; opponents far |
| First defender, loose ball, offensive first man | opponent intent: the nearest opponent's closing speed on the ball, kept separate from their capability |

**New actions:** possession has keep and build, shoot, pass/centre, push forward, clear, and wait. Recovery has return direct, small-pad route, and big-boost detour. Second man has support behind, support close, boost while the teammate plays, and challenge as well. A challenge also gains a reason, "the opponent could get there first but is not driving at it; with cover, take it."

**Findings** (`coaching_findings.py`). Each finding has these parts:
- the situation and why it matters;
- decision context, as second-person readings with numbers;
- an interpretation: what the evidence supports and what it argues against, with the specific failing premise, plus what would change the read;
- options, each with gains, preserves, sacrifices and risks. A fragment is shown only when its condition holds, and is marked "possible" when the condition is uncertain;
- decisive and unobservable assumptions, phrased as questions;
- a takeaway: a cue built from the conditions that decided this situation, contrasted with an alternative that was not on.

Kinds: `clear_read`, `several_defensible`, `leaning_with_uncertainty`, `hard_to_judge` and `observation_only`.

**Stage B** is retrospective and kept separate. It contains:
- a heuristic label of what the player did in the next 2.5 s;
- a verdict against the t0 ledger, using family status: `sound`, `defensible_if`, `risky`, `questionable` (only for clear reads), `debatable` or `unclear`;
- the outcome (touch sequence and any goal within 5 s). The outcome is shown but never used. Where it matters, the text says so: "The goal that followed does not make the choice wrong" or "It worked out this time, but…".

**Reasoning model (Phase 4).** The model only rewrites a validated Stage A finding. It may reword, prioritise and turn the read into a memorable cue. It may not add facts. The validator rejects:
- any number not in the finding's table;
- probability or likelihood language;
- outcome references or "you chose…" in Stage A;
- mechanics not in the input;
- unknown condition ids.

Stage B additionally rejects grading by outcome and contradicting the deterministic verdict. On any rejection the deterministic text is kept and the reasons are returned. No transport is built in (opt-in). All model tests are mocked, which is **not** evidence of live quality.

## 3. Contact model (Phase 1 evidence)

`scripts/calibrate_contact_model.py` uses decoder touches, split by match hash into fit and held-out sets.

| Measure | Result |
|---|---|
| Ground contact `dv = k·max(closing, 300)` along the car-to-ball line | k = 1.155 |
| Held-out outgoing-direction error (median / p75) | **9.4° / 41.4°** |
| Baselines (median error) | centre line 46.4°; car velocity 25.2° |
| Next-ball race (who touches next) | 0.833 when decided, below always-opponents at 0.851 |
| Destination zone after 1 s | 0.524, the same as the car-velocity baseline |
| Airborne share of candidate touches | 49% |

The direction model is validated; the race and the zone predictions are not. Findings therefore use neither, and the contact outcome stays an explicit unobservable premise. A side observation, which needs validation at known rank: after a strong ground touch, the next touch by another player was an opponent's about 85% of the time in this cohort. That suggests a challenge's value is mostly denial and positioning, not possession.

## 4. Evaluation (Phase 6)

All numbers are from `scripts/evaluate_round12.py` on the cached public cohort: **15 replays, 60 player reports (every player), unknown rank, no human labels**. This is a falsification and consistency harness, not an accuracy benchmark (`docs/round12/evaluation_round12.json`).

| Measure | Result |
|---|---|
| Situations analysed (all players, all matches) | 6969: aerial_or_wall 1959, second_man_support 1670, first_defender 995, offensive_first_man 795, recovery_and_boost 713, loose_ball 591, possession 246 |
| Aerial/wall moments, observation-only (never judged) | 1959 |
| Findings selected (at most 6 per report) | 360: first_defender 120, second_man_support 118, possession 73, offensive_first_man 26, loose_ball 18, recovery_and_boost 5 |
| Finding kinds | clear_read 180, several_defensible 174, leaning_with_uncertainty 6 |
| Findings presenting two or more defensible option families | 174 |
| Findings naming a decisive unknown | 126 |
| Claims rejected by the verifier / numbers not traceable to evidence | 0 / 0 |
| Takeaways containing measured numbers | 350 of 360 |
| Generic phrases ("rotate back", "save boost", "don't double commit", "challenge earlier", ...) | 0 |
| Stage A identical when the replay is cut at t0 / when the future is rewritten (ball mirrored, fake goal) | 180/180 and 180/180 |
| Player names or IDs in report JSON | 0 leaks |
| Retrospective verdicts | sound 219, questionable 43, unclear 36, not_assessed 35, defensible_if 21, risky 4, debatable 2 |
| Match tendencies reported (≥3 matching instances) | 28 |
| Mean time per report | 21.5 s (two-core container) |

**Outcome independence.** Verdicts never read the outcome; the table checks that this holds in practice:

| Verdict | Goal against within 5 s | Opponent took the next touch |
|---|---|---|
| sound | 11/219 | 74/219 |
| questionable | 3/43 | 24/43 |
| defensible_if | 2/21 | 11/21 |

Goals against follow "sound" and "questionable" verdicts at similar low rates. Many sound decisions are followed by conceded goals, and they stay sound. "Questionable" verdicts are followed by an opponent's next touch more often than "sound" ones. That is weak, confounded evidence that the ledger tracks something real; for example, a challenge produces a contact by definition. It is not validation.

**Threshold sensitivity** (each threshold scaled by 0.7 and 1.3; share of 185 ledgers on 5 matches whose supported/refuted sets change):

| Threshold | Value | ×0.7 | ×1.3 |
|---|---|---|---|
| possession: pressure time | 0.8 | 2 | 2 |
| recovery: acceptable detour | 0.8 | 1 | 0 |
| low boost (situation classes) | 30.0 | 0 | 5 |
| small-pad corridor | 700.0 | 1 | 1 |
| opponent closing speed = committing | 500.0 | 0 | 2 |
| boost for recovery | 25.0 | 5 | 4 |
| room to delay | 2500.0 | 4 | 8 |
| cover window | 1.0 | 19 | 20 |

Most thresholds move at most 8 of 185 ledgers. The exception is the **cover window** inherited from V0/V1 (1.0 s), which moves about 10%. It is the single most consequential hand-set number, and the first one an expert study should calibrate.

**Audits that changed the code during the round.** Reading cohort outputs turned up three sources of false criticism, each fixed and covered by a test:
1. Picking up pads while shadowing was labelled "rotating away" (8 of 48 "questionable" verdicts in the first run).
2. Taking small pads on the way back was refuted unless low on boost.
3. A second man's follow-up after the teammate's touch was labelled a double commit (15 of 37 reported tendencies in the second run).

The tables above are from the final code, except as noted below.

**Merit-study extension.** `scripts/merit_study.py prepare` now labels every sampled case with `situation_rationale_v1` alongside the Round 11 systems. On the 45-case pilot sample (first-defender strata, 9 actions each, 405 labels), the label counts are:

| System | acceptable | poor | abstain |
|---|---|---|---|
| ActionRationaleV0 | 168 | 177 | 60 |
| SituationRationaleV1 | 206 | 193 | 6 |
| TacticalDecisionStateV1 | 213 | 8 | 184 |

The new system is **much more decisive**: it withholds only when no action is established or ruled out. Whether that decisiveness is right or premature is exactly what the blind expert study must decide. Until then, treat "poor"/"questionable" as hypotheses to show an expert, not verdicts.

**After the cohort run** (same code otherwise):
- the shooting-range condition was simplified to distance from the goal centre (4500 uu, the same value the observed-shot label uses). The earlier version also required a minimum up-field position, which produced a misleading reading ("4341 uu ... out of range");
- two readings were reworded.

Only possession findings can differ from the table above. Every check (tests, number tracing, verifier) was re-run on the final code.

## 5. Comparison with the previous system

Same 60 player reports, same replays.

| | Round 9–11 default (EpisodeCandidatesV0 + CoachLessonV0 + ActionRationaleV0) | Round 12 CoachingReportV1 (experimental) |
|---|---|---|
| Moment selection | largest observed state change (480 candidates) | decision situations by class, ranked by responsibility, teachability, sufficiency and recurrence |
| Candidates that are first-defender moments (the only vocabulary the old ledger has) | 42 of 480; 174 match no decision situation and 155 are aerial/wall | each finding uses its class's vocabulary; aerial/wall is observation-only |
| Output | verified observations plus an undetermined grade (480 of 480); takeaways: 0 | interpretation, 6.2 options on average with gains/preserves/sacrifices/risks, decisive assumptions, a takeaway with measured numbers (350 of 360) |
| Opponent intent vs capability | not distinguished | separate condition (closing speed) |
| Boost and route | one threshold | direct vs small pads vs big pad, with pad availability |
| Second man | "yield to teammate" only | cover-if-beaten, double-commit risk, boost route that keeps cover |
| Retrospective | rationale only, no action comparison | observed action vs t0 ledger; outcome shown, never used |
| Safety properties | verifier, t0 firewall | the same, plus number tracing and prefix/future invariance on real data (180 checks) |

What the old system did better: it never criticised anything, because it never judged. The new system issues "questionable" retrospective verdicts (43 of 360 findings). Each is backed by a stated failing premise, but none has been checked by an expert. That is the main new risk, and the reason the output stays experimental.

## 6. What real data does and does not support

**Supported (measured on public replays of unknown rank):**
- stage separation: prefix and future-rewrite invariance;
- claim validity and number tracing;
- coverage of situation classes;
- the contact-direction model;
- the base rate of opponents taking the next ball;
- how sensitive conditions are to each threshold.

**Not supported by any data we have:**
- whether the ledger's statuses match what strong players would judge (no expert labels yet);
- whether the takeaways help a player improve;
- every threshold's tactical value: pressure 0.8 s, detour 0.8 s, low boost 30/25, room to delay 2500 uu, closing 500 uu/s, cover window 1.0 s, 700 uu pad corridor. These are documented coaching heuristics. Values within the band around each are marked uncertain, and the sensitivity table shows how much hinges on them;
- the observed-action labels (movement heuristics, not intent);
- anything aerial, wall or ceiling;
- teammate intent and communication, and camera awareness.

## 7. Weaknesses and the human validation still needed

1. **No expert labels.** Every status in the ledger is a rule, not a validated judgment. The blind two-stage merit study from Round 11 now includes `situation_rationale_v1` as a system (`scripts/merit_study.py prepare`). It needs GC+ raters on the first-defender strata, then on the new classes; the study packets need extending beyond first-defender actions.
2. **First-defender challenge criticism dominates the "questionable" verdicts.** These rest on reachability lower bounds, the 1.0 s cover window and the closing-speed intent proxy. They are the first thing to show an expert.
3. **Observed-action labels are heuristics.** A 2.5 s window, touches, distance to the ball, goal-side share and pickups. A fake challenge looks like a shadow; a whiff looks like a challenge. Mislabels turn into wrong verdicts. Needed: an expert relabel of about 100 actions.
4. **Possession is thin.** The vocabulary is keep / shoot / pass / push / clear / wait. There is no dribble-vs-flick, no wall carry and no touch quality. The shot lane is a straight-line, 2500 uu/s geometry.
5. **Second-man "several defensible" findings are frequent.** Support close vs support deep is usually distinguishable only by distance and depth, which the ledger does not grade. That is honest but low-value. A depth/space model (where the next ball is likely to go) is the missing piece, and the contact study shows we cannot yet predict it.
6. **Aerial, wall, ceiling and backboard play are unmodelled.** About 45% of situations (and about half of touches) get observations only.
7. **Teammate intent and communication, camera awareness, the opponent's read of a fake, flip availability:** unobservable by construction and named as such.
8. **Runtime** is about 30 s per player per match on two cores. Fine for a local report, slow for an interactive request.
9. **Public cohort of unknown rank.** Nothing here says how the system behaves on the user's own ranked replays. That is the next phase.

## 8. Integration

See `docs/round12/INTEGRATION.md` for exact steps for ChatGPT (bundle flag, capability flags, `complete_json` transport for `run_reasoner_async`) and for Antigravity (finding cards, Stage B collapsed by default, evidence drawer, patterns panel). This branch merges cleanly with PR #41 (and so with #39). On the merged tree: **480 passed, 4 skipped** (merged with PR #41 head `1152a5d`).

## 9. Highest-risk assumptions

1. **Lower-bound reachability as "who gets there first".** Arrival intervals and the 0.30–0.55 s band decide most first-defender statuses. If real arrival times at high rank are systematically earlier (better recoveries, flip resets), "you were second to the ball" claims will be wrong in the direction of over-criticising challenges.
2. **The 1.0 s cover window.** It is the most sensitive threshold (about 10% of ledgers move at ±30%). It decides "your teammate could cover" and so whether aggression is supported.
3. **Closing speed as intent.** A defender driving away can be baiting; one closing fast can be faking. A wrong intent read flips challenge support.
4. **Observed-action labels.** Stage B verdicts are only as good as the label of what the player did.
5. **Contact outcome treated as unknowable.** The calibration shows we cannot predict the next ball, so findings never claim a challenge "wins possession". If experts judge challenges mainly by contact angle, our findings will look shallow there.
6. **Thresholds without a known-rank cohort.** Low boost 30/25, pressure 0.8 s, room 2500 uu. They change few ledgers at ±30%, but none is calibrated at the user's rank.

## 10. Testing on your own ranked replays (next phase)

Everything runs locally: no upload and no model call.

```
cd coach-app
python scripts/coach_replay.py "C:\path\to\MATCH.replay"                          # lists the four players
python scripts/coach_replay.py "C:\path\to\MATCH.replay" --player YOURNAME --md report.md --json report.json
```

Most valuable feedback per finding, in this order:
1. Is the situation described correctly? Check the decision-context readings: arrival times, cover and boost.
2. Is a "questionable" or "risky" verdict fair? If not, which premise is wrong?
3. Was the observed-action label right?
4. Is the takeaway something you would act on?

Note the match time (`F# - m:ss`) with each comment. Disagreements on items 1 and 3 point to measurement bugs; disagreements on item 2 point to the rules or thresholds. Section 9 lists which assumptions to suspect first.

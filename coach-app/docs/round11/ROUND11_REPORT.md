# Round 11: falsifying V1, conditional rationales, and a blind expert merit study

**Bottom line.**
- **V1 should not become the default.** Two of its foundations failed real-data checks: the 0.55 s ordering margin is unstable, and its arrival "intervals" aren't arrival intervals.
- **This round replaces stance grades with an explicit condition ledger** (`ActionRationaleV0`). It explains why several actions can be reasonable and what information would change that.
- **It adds a two-stage blind expert study** (`TacticalMeritStudyV0`). That study, not more replay proxies, decides which categories survive.

All real-data figures come from the same 15 public, unknown-rank 2v2 replays. No expert labels exist yet.

## Phase A: attacking V1 (`scripts/falsify_decision_state_v1.py` → `v1_falsification.json`)

| Assumption | Test | Finding | Consequence |
|---|---|---|---|
| The 0.55 s ordering margin generalizes | Leave-one-match-out fit on "raced" pairs (both cars touched within 3 s); match bootstrap (300 resamples) | Every LOO fold picks **0.30 s**. The bootstrap ranges 0.10–0.65 s (mode 0.30; 0.55 in only 13/300). Per-match accuracy at 0.55 ranges 0.86–1.00 | 0.55 was an artifact of one 10/5 split. The margin is an unstable band, not a constant |
| `[t_min, t_max]` is an arrival interval | 4,689 car-to-touch rows | 47% of intervals have zero width. The actual touch falls before t_min 6.7%, inside 47.9% and **after t_max 45.4%** of the time | V1's "pessimistic bound" is not an uncertainty interval for arrival; comparing t_max values has no calibrated meaning |
| Branch labels are predictive | At V1 decision nodes: who touched first, focus or carrier, within 3 s | "carrier first": carrier 151, focus **40**, neither 19 (n=210). "ambiguous": carrier 202, focus 160, neither 32 | The label `only_if_execution_fails` is wrong in about 1 in 5 cases with no execution failure. Rename it "not favoured by timing" |
| "Robustly defensible" means safe | Round 10 regain proxy | Opponents regained after 23% of "robust" challenges, no lower than other stances | Robust never meant safe. Contact angle and destination aren't modelled |
| Arrival times capture the situation | Inspection | Possession vs a loose ball, pressure on a controlling carrier, and teammate responsibility collapse into one number | Distinguish them as separate conditions (below) |
| Nine actions cover high-rank decisions | Inspection | Missing: bumps and demos, aerial or backboard reads, boost denial, wall play, passes and infields, second-man support position, kickoff variants | Listed as `unmodelled_alternatives`; "refuted" never means "mistake" |
| Restraint and off-ball movement get credit | Inspection | V1 affirms delay only as the complement of a bad commit; off-ball support has no positive reason | Explicit positive reasons for delay, hold, yield and support |

**Counterexamples to keep as tests:**
- A level contest with no cover. The angle of contact decides whether challenging is reasonable, and it is unobservable.
- A focus player who is clearly first, while the loose ball favours their second player. Winning the touch does not make challenging safe.
- A margin-sensitive teammate order, which flips between 0.30 s and 0.55 s.

## Phase B: architectures compared

| Architecture | Strength | Weakness | Decision |
|---|---|---|---|
| 1. Conservative capability and uncertainty gates | Abstains instead of guessing | Alone it only removes output; it explains nothing | **Implemented inside 2**: margin-band sensitivity and a judgment gate |
| 2. Condition ledger: assumption-based rationales per action, with decisive-information search | Explains *why several actions can be reasonable* and *what would change the view*; separates measured, within-error, unknown and unobservable | Reasons and defeaters are hand-written hypotheses; no outcome model | **Implemented** (`ActionRationaleV0`) |
| 3. Expert annotation and disagreement system | The only route to real quality evidence | Needs raters' time | **Implemented** as protocol and code (`TacticalMeritStudyV0`); no labels created |
| 4. Retrieval memory of annotated situations | Grounds explanations in rated precedent | Useless until item 3 produces annotations | Deferred until the first study |
| 5. More thresholds or stances on V1 | Cheap | Repeats Round 10's failure | Rejected |

### `ActionRationaleV0` (`coach_app/action_rationale.py`)

- **Conditions.** Fifteen, each evaluated as `holds`, `fails`, `within_error`, `unknown` or `unobservable`:
  - arrival order, contest level, teammate cover, loose-ball race, teammate first or deeper;
  - goal-side, grounded, boost for recovery, room to delay;
  - carrier in control (a heuristic, labelled as such);
  - four unobservables: contact direction, teammate's rotation intent, flip availability, camera awareness.
- **Margin band.** Ordering conditions are evaluated at both ends of the 0.30–0.55 s band. A status that differs between them becomes `within_error`.
- **Reasons and defeaters.** Each action has *reasons* (sets of conditions that justify it) and *defeaters*. Status:
  - `supported`: a reason is established by evidence;
  - `conditional`: a reason rests on named uncertain premises;
  - `contested`: a reason may hold, but a defeater is established;
  - `refuted`: every modelled reason fails. That is not "mistake".
- **Decisive information.** Each uncertain condition is set true, then false. The ones that change some action's status are returned, with how they could be resolved: a better physics model or expert review, the missing telemetry, or the player's own account.
- **Judgment gate.** Withheld when nothing is established either way, or when arrival order is unknown.
- **No outcome input, no probability.** `enumerate_condition_worlds` lists, unweighted, which actions each combination of premises would support.

**Example (synthetic).** In a level contest with no cover, challenging is *contested*. It can be right only if the contact goes away from their second player, which no replay shows. Shadowing and holding are *supported*. The decisive information is the contact direction.

### `TacticalMeritStudyV0` (`coach_app/merit_study.py`, `scripts/merit_study.py`)

This is separate from PR #16's timing study.

- **Stage A (blind).** The clip ends at t0, with a marked car, a jittered 3–5 s lead-in and no names.
  - The rater gives good, acceptable, poor or cannot_judge for every action, plus a confidence, a preferred action, an off-menu action and the missing information that would change their view.
  - Responses mentioning the outcome, actual action or system are rejected.
- **Lock.** Responses are canonicalised and hashed with SHA-256. Stage B cannot be built without a matching lock.
- **Stage B (reveal).** The full clip, the actual action (labelled as coming from the retrospective classifier) and the outcome. The rater re-rates the actual action and says whether the outcome looked consistent, lucky, unlucky or unclear, and whether their view changed.
- **Strata.** Pre-registered:
  - withheld, risky aggression, covered aggression, intelligent restraint;
  - possession, recovery, off-ball defence, strong positive.
  - Sampling uses the retrospective choice only to stratify, and spreads cases across matches.
- **Consensus.** "Acceptable" or "poor" only when at least 2 raters judged the item and none disagreed in direction. Otherwise *contested* or *insufficient*. These are reported and never scored as system errors.
- **Metrics, per system and per stratum:**
  - false-blame rate (system says poor, experts say acceptable), with a case-bootstrap 95% CI;
  - missed-problem rate, also with a CI;
  - positive recognition;
  - coverage and accuracy when judging;
  - Cohen's kappa against consensus;
  - abstention quality: do abstentions fall on items experts also find hard?
  - inter-rater Krippendorff α;
  - the cannot-judge share;
  - a Stage B hindsight check: do changed ratings follow the outcome?
- **Systems compared in one study:**
  - `action_rationale_v0`, plus a stricter evidence-only reading that counts only `supported` as acceptable;
  - `decision_state_v1`;
  - `tactical_options_v0`.

## Recommendation on V1 categories (until the study reports)

| V1 element | Recommendation |
|---|---|
| `robustly_defensible` | **Rename** "no exposure found in the modelled branches". Never show it as safe or robust |
| `defensible_gamble` | **Gate**: show only with its unobservable premise named. Prefer the rationale's `contested` |
| `defensible_tradeoff` | Keep, with the named cost |
| `questionable` | **Gate**: show only when it survives the whole margin band, which is equivalent to the rationale's `refuted`. Word it "the modelled reasons for this action don't hold here" |
| Branch reachability `only_if_execution_fails` | **Rename** "not favoured by timing" |
| 0.55 s margin | Treat as the band 0.30–0.55 s. V1's default is unchanged for compatibility but flagged unstable |
| `t_max` in order comparisons | Remove at the next version: it is not an arrival bound |
| V1 as default | **No.** Keep it opt-in, as in PR #38 |

## Integration with PR #38

- **Additive and opt-in.** `ActionRationaleV0` takes the same `Stage1EpisodePacketV0` that #38's adapter already builds. It can be exposed like V1: opt-in, deterministic, with no model transport.
- **Verifiable claims.** Its claims are in `claim_verifier` format and pass on the fixtures and on real replays.
- **V1 change.** The only change to `decision_state_v1.py` is a context-local `margin_override()` for sensitivity analysis. Default behaviour is identical, and all V1 tests pass.
- **Merit study.** `merit_study.py` is independent of #38's review-bundle endpoint and the renderer. Its exporter rows match the commitment-study clip conventions, except that Stage A clips end at t0.

## Commands (from `coach-app/`)

```
python scripts/falsify_decision_state_v1.py CACHE_DIR PRIVATE_MANIFEST_DIR docs/round11/v1_falsification.json
python scripts/merit_study.py prepare CACHE_DIR PRIVATE_MANIFEST_DIR STUDY_DIR [--per-stratum 6]
python scripts/merit_study.py lock   STUDY_DIR stage_a_responses.json
python scripts/merit_study.py reveal STUDY_DIR stage_a_responses.json
python scripts/merit_study.py score  STUDY_DIR stage_a_responses.json [stage_b_responses.json]
```

`CACHE_DIR` holds parsed replays; `PRIVATE_MANIFEST_DIR` comes from `scripts/benchmark_choices.py`.

## Real-replay pilot of the rationale and the study preparation

From `scripts/merit_study.py prepare` on 625 first-defender episodes (`rationale_real_replay_summary.json`):

- **Engineering checks.**
  - The existing claim verifier rejected **0 of 8,164** claims.
  - **127/127** sampled rationales were identical after deleting every frame and event past t0.
  - Judgment was withheld in **21** episodes, where arrival order was unknown.
- **Reasonable choices per judged episode.** Each episode has 1–7 supported or conditional actions; the mode is 5 (125 episodes). The coach is not reduced to one "right answer". It now says *which premise* each choice rests on.
- **Most decisive information,** meaning the conditions whose resolution would change some action's status:

| Condition | Episodes |
|---|---|
| Focus player first (within error) | 394 |
| Carrier first | 296 |
| Teammate first | 206 |
| Teammate covers | 204 |
| Contact direction (unobservable) | 180 |

  Arrival order inside the model's error, and the unobservable contact angle, are what most often stand between the coach and a judgment.
- **Challenges.**
  - Challenging is supported by evidence in 106 episodes, conditional in 252, contested in 36 and refuted in 210.
  - Of the 252 conditional ones, many rest on the contact direction, which no replay shows.
- **Pilot sample.** The sample spreads cases across matches:

| Stratum | Available | Sampled |
|---|---|---|
| Risky aggression | 136 | 6 |
| Covered aggression | 124 | 6 |
| Off-ball defence | 83 | 6 |
| Intelligent restraint | 82 | 6 |
| Recovery | 65 | 6 |
| Withheld | 21 | 6 |
| Other | 111 | 6 |
| Strong positive | 3 | 3 |
| Possession | **0** | 0 |

  Possession is empty because the candidate rule selects defensive moments. Stage A packets carry no stratum, system, case id or retrospective field (checked).
- **No expert has rated anything.** The pilot packets and the private map stay out of git.

## Remaining weaknesses

- **The rationales are hypotheses.** Reasons and defeaters are hand-written, so a high-rank coach may reject some. That is exactly what the study is built to show.
- **The candidate rule only finds defensive moments.** Possession and offensive strata will be thin or empty until ChatGPT's episode discovery supplies other moments.
- **The carrier-control heuristic is unvalidated.**
- **The study needs real raters.** Ideally 2–3 experienced players and at least 6 cases per stratum. With about 50 cases, the confidence intervals will be wide; the first study is a pilot.
- **The actual-action label is a retrospective classifier**, shown to raters as such.

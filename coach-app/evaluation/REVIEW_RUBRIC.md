# Blind review rubric — Replay Lab coaching experiment

**Purpose:** Determine whether a coaching finding is defensible and useful for high-level 2v2 players. This is not a generic quality rating of the replay and not a judgment from whether the team subsequently scored.

## Stage 1 — judge the player's decision, not its outcome

Reviewers see anonymized pre-decision evidence and, where a replay viewer is available, the game state and camera history **only through t0**. The reviewer should not see the model's prediction, native post-hoc event labels, opponent's subsequent shot, goal, score change, or end result. Do not infer intent with certainty.

Use exactly one of four labels:

| Verdict | Interpretation |
|---|---|
| **sound** | Reasonable in context, even if execution later fails or an opponent makes an excellent play. |
| **risk** | A materially questionable decision **given information available by t0**; the concern is specific and supportable, not merely a bad eventual outcome. |
| **tradeoff** | Multiple defensible choices exist. Which is preferable depends on valid style, teammate behavior, execution capability, or uncertain information. |
| **indeterminate** | Critical facts are missing, the decision time is not established, evidence is contradictory, or the situation is beyond the reviewer's reliable judgment. |

Ask yourself: what was the player trying to protect or gain? What information existed at the commitment point? Could a human at this skill level actually execute the proposed alternative? Is the choice robust to plausible opponent reactions?

Examples to discuss, **not pre-labeled ground truth**:
- A second man cheating behind kickoff may enable immediate control or concede defensive depth. The resulting pinch alone does not settle whether the choice was good.
- A player approaching a 50/50 may deliberately block toward a teammate. Losing the ball outright does not prove the chosen challenge was poor.
- A last defender with little boost might have been forced into an early challenge, especially if the opponent already controls the ball.
- A teammate deeper on the field is NOT necessarily covering net; examine heading, velocity, distance, boost, recovery and potential contest.
- A strong touch or recovery should be recognized even if the system was initially searching for mistakes.

Label decisions independently. A reviewer is free to abstain through **indeterminate** rather than invent an optimal play. Disagreements between two reviewers remain disagreements; no majority is fabricated.

## Stage 2 — judge model outputs (still blind to model identity)

Only after Stage 1 labels have been finalized should reviewers open anonymous coaching-output packets. Each output references a Stage 1 case by its anonymous case_ref.

Report:

- **factual_errors** (nonnegative integer): claims directly contradicted by observed pre-t0 evidence.
- **unsupported_claims** (nonnegative integer): claims not warranted by available evidence, including unsupported predictions about an opponent, proven feasibility, or player's intent. Even a coincidentally true claim is unsupported if the evidence cannot establish it.
- **useful** (boolean): is the overall feedback specific, actionable, fair and appropriately uncertain? Generic advice to 'rotate better' is not useful without a concrete mechanism and defensible alternative.

A finding that wrongly declares a deliberate successful 50/50 a mistake is a serious false criticism. A model that abstains appropriately is preferable to fabricated confidence, but a model that never offers coaching should not rank as more useful solely on precision.

Only accept evidence citations which refer to actual pre-t0 evidence in the packet. A citation's presence does not make the natural language claim true.

## Stage 3 — score without cherry-picking

The coordinator restores IDs with the **private** mapping after ratings are frozen, then scores every candidate system on the identical case cohort. Report selective agreement together with full-cohort submission/answer coverage, risk precision, risk recall, false-blame-on-sound, abstention rates, and human-rated usefulness.

The pilot should contain diverse examples across kickoff, first man, second man, last man, successful play and unclear play, sourced from at least three distinct 2v2 replays. If a case is not covered by the current extractor, it may be curated manually with explicit provenance; never invent ground-truth labels.

Match-separated validation is required for any trained model. Two reviewers who agree are still not infallible; invite high-level independent adjudication when feasible. Do not use this small pilot to claim a measured global coaching accuracy rate.

## Evidence integrity and privacy

The upstream exporter must supply true event and finalization timestamps. If a native retrospective event classification is only known after t0, it must not appear as an observed decision-time fact even if the event was anchored earlier by the parser. Missing values are unknown, not zero or proof of inaction.

Remove real player names, account IDs, replay filenames, and identifiable free-text before packaging. The packet generator catches common platform-id patterns but cannot know every nickname.

Keep the private mapping, review submissions, and outcome-bearing replay references outside public repository history. Only commit anonymized test fixtures and aggregate scores after reviewing them for identifiers.

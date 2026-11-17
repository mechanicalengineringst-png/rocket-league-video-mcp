# Replay Lab: blind tactical coaching evaluation

This is a **model-agnostic, independent evaluation prototype**. It does not change the existing Replay Lab API, HD viewer, decoder or any production coaching behavior. It deliberately lives in its own isolated draft branch.

## Why

A model returning 213 candidate decisions or sounding convincing is not evidence of expert-useful coaching. Compare every new approach — simple rules, small state-value models, retrieved high-rank cases, multimodal models, local LLMs, cloud LLMs or RL-derived policies — on the **same frozen, pre-decision-only cases** and obtain blind human judgments.

The first evaluation cohort should contain **40–60 diverse, real, anonymized 2v2 cases** from at least 3 matches, including kickoff support, 50/50s, last-man defense, good plays, misleading negatives, and unclear decisions. These numbers are a pilot, not a statistically validated performance target.

## Independent roles

- **Antigravity:** Own verified replay extraction, a safe server-side rich-event route and a causal DecisionCase export. Preserve original timestamps and finalization times; do not invent them. Never mix post-outcome information into an ex-ante view.
- **Claude:** Own alternative tactical intelligence prototypes: state-value/possession/goal threat, supervised human-action imitation, expert-case retrieval, and data-feasibility experiments. Implement candidates on Claude's own branch; supply predictions in the evaluation schema.
- **Gemini:** No access to the user's GitHub workspace. Independently discover new algorithms, pretrained models, licenses, public research and benchmark pitfalls; provide grounded references and experiment recommendations for the user to forward. Do not claim to have read or edited the private/connected repository.
- **ChatGPT:** Own this evaluation contract, blind human review protocol and independent critical review. Do not merge or replace other agents' branches.

Each party is explicitly allowed to challenge or **recommend replacing the entire current tactical-analysis architecture**, but replacement must be earned by reproducible evidence. Avoid costly training/downloads without a pilot that discriminates it from simpler baselines.

## Trial protocol

1. Freeze anonymized cases with t0 and only evidence whose event_time_s <= finalized_through_s <= t0. Never include later goal/50 outcome or decoder labels whose finalization occurs after t0.
2. Two independent human reviewers judge each real play, preferably seeing the pre-decision scene/clip before the outcome. Allowed labels: sound, risk, tradeoff, indeterminate. Disagreement is **not** a consensus.
3. Run different systems on the **same** frozen data, blind to outcomes and reviewer labels. Outputs are sound, risk, tradeoff or abstain, with cited predecision evidence keys. Separate human review can then score each output's factual errors, unsupported claims and usefulness while the model's name is hidden.
4. Report warning precision against consensus risky plays, accusations refuted by sound consensus, abstentions, coverage, label disagreement, invalid citations and human usefulness. An evidence ID validates a key reference, **not** the truth of the model's language.
5. Only after labels and model outputs are frozen may reviewers inspect the later outcome. A lucky outcome must not become proof of a good choice.

## Input formats

From `coach-app/`, invoke `python -m evaluation.score --cases path/to/cases.json --predictions path/to/predictions.json --reviews path/to/reviews.json --quality-reviews path/to/quality.json --output path/to/results.json`. Optional quality-reviews and output flags can be omitted. JSON arrays or JSONL are accepted.

A **case**:
```json
{"case_id":"match-a-0358","replay_group":"anonymous-match-a","mode":"2v2","situation_type":"first_man_challenge","t0":35.88,"pre_decision_evidence":[{"key":"second_man_depth","claim":"Teammate is positioned 1800 units behind; coverage not established","event_time_s":35.85,"finalized_through_s":35.85,"source":"replay","source_quality":"high"}]}
```

A **system prediction**:
```json
{"case_id":"match-a-0358","system_id":"experimental-ml-v1","assessment":"abstain","cited_evidence":[],"advice":"Depth alone does not verify coverage."}
```

Independent **human decision reviews** (2 reviewers per case):
```json
[{"case_id":"match-a-0358","rater_id":"reviewer-a","verdict":"tradeoff"},{"case_id":"match-a-0358","rater_id":"reviewer-b","verdict":"indeterminate"}]
```

Optional **output-quality review**:
```json
{"case_id":"match-a-0358","system_id":"experimental-ml-v1","rater_id":"reviewer-a","factual_errors":0,"unsupported_claims":0,"useful":true}
```

The current experimental `DecisionCase.to_llm_payload()` does not expose individual `finalized_through_s` fields; the eventual adapter must access trusted Evidence objects server-side. The evaluator intentionally rejects arbitrary extra case fields such as future outcome information.

## Run tests

```bash
cd coach-app
pytest -q tests/test_blind_coaching_benchmark.py
python -m evaluation.score --cases cases.json --predictions predictions.json --reviews human_reviews.json
```

The evaluation package itself uses only Python's standard library. These tests use pytest, already present in the coaching project's existing test environment.

## Limits

- This tool validates causal **timestamps** on submitted claims, not the upstream native event's true semantic provenance. Bad upstream labels can still be stamped at t0 incorrectly; extraction needs an independent provenance audit.
- It performs an explicit regex check for common platform identifiers; proper anonymization of player nicknames, replay titles and arbitrary account identifiers is the producer's responsibility.
- A two-reviewer agreement is a useful provisional reference, not tactical ground truth; seek expert input and monitor reviewer disagreement.
- The tool scores predictions only on cases where systems actually supplied predictions; compare missing-case counts and abstentions to avoid optimizing for silence.
- No local GPU tests, real replay fixture replays, model training or paid API calls have been run by this independent evaluation branch.

## Blinded human-review workflow (new)

The evaluator can score raw human judgments, but reviewers must not see model
names, real case identifiers, or the eventual result of a play. Use the
additional stdlib-only packet generator for blind review:

1. Run from coach-app:
   python -m evaluation.prepare make --cases cases.json --predictions predictions.json --output-dir local_review --seed 20261117
2. Send local_review/decision_packets.json to two independent reviewers FIRST.
   Freeze or stop the replay at decision time; do not reveal the goal or 50/50 outcome.
3. After decision verdicts are frozen, send quality_packets.json, containing
   outputs in randomized order with anonymous model IDs. It uses case_ref to
   link back to an anonymous decision case.
4. NEVER commit or distribute PRIVATE_DO_NOT_COMMIT_mapping.json. It connects
   anonymous C00001 and Q00001 review IDs back to source cases and systems.
5. Reviewers submit independent records with review_id and rater_id:
   decision: {"review_id":"C00001","rater_id":"human-1","verdict":"tradeoff"}
   quality: {"review_id":"Q00001","rater_id":"human-1","factual_errors":0,"unsupported_claims":0,"useful":true}
6. Map these frozen labels back to score-compatible IDs locally:
   python -m evaluation.prepare resolve --kind decision --submissions decision_answers.json --mapping local_review/PRIVATE_DO_NOT_COMMIT_mapping.json --output decision_reviews_resolved.json
   python -m evaluation.prepare resolve --kind quality --submissions quality_answers.json --mapping local_review/PRIVATE_DO_NOT_COMMIT_mapping.json --output quality_reviews_resolved.json
7. Score:
   python -m evaluation.score --cases cases.json --predictions predictions.json --reviews decision_reviews_resolved.json --quality-reviews quality_reviews_resolved.json --output results.json

Quality reviews are optional. Both source evidence and the original case
identifiers MUST already be anonymized before producing packets: platform-ID
pattern checks are not a complete privacy guarantee for free-text nicknames.
Blinding is a scientific workflow, not cryptographic protection.

## Model-data splits that avoid obvious replay leakage

Do not randomly split nearby frames into training and evaluation: states from
the same replay overlap heavily. Every case intended for model training
must carry a stable anonymized replay_group. Create match-disjoint folds:

    python -m evaluation.splits --cases cases.json --folds 3 --seed 20261117 --output match_folds.json

Every match is held out in its entirety in one evaluation fold, and the other
matches form the training set. This does not ensure different players across
matches; audit player/session identity separately when that becomes possible.

## Compare all candidate models on the same frozen cohort

New metrics in evaluation.score:
- full_cohort_submission_rate — fraction of source cases receiving any output.
- consensus_answer_coverage — fraction of reviewed consensus cases the system
  answered without abstaining.
- consensus_full_cohort_agreement — fraction of ALL consensus cases answered
  correctly, penalizing missing responses and abstention through coverage.
- risk_warning_precision — supported risky-play flags among flags issued.
- risk_warning_recall_on_consensus_risks — what share of consensus risky plays
  were actually flagged (unanswered or abstained risky cases count as missed).
- false_blame_rate_on_consensus_sound — what share of consensus sound plays
  were wrongly labeled risky.
- per_situation — count-level diagnostic to reveal which play categories
  each model does or does not handle.

A model that answers one easy case correctly can achieve 100% selective
precision; look at submission/answer coverage and missed risks before
concluding it is superior.

The system tests software behavior on synthetic fixtures. Real expertise
still requires independent reviewers, real 2v2 situations, provenance checks
and explicit validation. Citation keys do not prove the truth of what a model
says, and timestamps do not prove native event labels were available at t0.

## Separate probability-forecast experiment (not a coaching verdict)

Claude's experimental value models can forecast whether a team will score or
concede during a fixed future window. Evaluate those probability forecasts
after they are frozen, **without providing outcome labels to the model input**:

    python -m evaluation.forecast --cases cases.json --forecasts forecasts.json --outcomes heldout_outcomes.json --horizon 5 --output calibration.json

Predictions are a JSON list of:
    {"case_id":"case-a","system_id":"value-model-v1","horizon_s":5,"p_score":0.2,"p_concede":0.4}

In a SEPARATE, never model-visible file, store observed labels:
    {"case_id":"case-a","horizon_s":5,"observed_through_s":40.0,"scored_within_horizon":false,"conceded_within_horizon":true}

The observed_through_s timestamp must cover the full t0 + horizon interval.
If the replay ends before that, the case is **censored** and excluded rather
than falsely counted as a safe negative. Output includes per-task Brier score,
log loss, five calibration bins, missing predictions and coverage.

The evaluation_prevalence_reference_brier uses the EVALUATION sample's known
base rate, so it is only an optimistic diagnostic reference. For a real model
comparison, also use an independently estimated baseline from training matches,
with the same grouped folds and identical heldout cases. A predictive model
should not be trained on outcomes from the match it is evaluated on.

**Crucial:** forecasting that a goal is likely does not establish which
human decision was correct. A high-quality tactical critic needs separate
action-conditioned or expert-grounded validation, plus human review.

## Standalone offline blind-review page (no installation)

Use **coach-app/evaluation/review.html** as a dependency-free local reviewer
interface. It loads its companion JavaScript file **review_state.js** from
the same folder; copy BOTH files together if distributing a review kit.

1. The coordinator first runs:
   python -m evaluation.prepare make --cases cases.json --predictions predictions.json --output-dir local_review
2. Supply reviewers ONLY these anonymized files (as separate stages):
   decision_packets.json first, then quality_packets.json once their decision
   judgments are finalized. **Never share the private mapping or outcome file.**
3. A reviewer opens review.html in a modern browser (double-click; no server,
   no account, no external assets or network traffic). Enter an arbitrary
   reviewer code such as reviewer-a, load decisions and choose one of four
   labels per case. Optionally enter reasoning notes.
4. Click Finalize & export once all Stage 1 cases are rated. This saves a
   private JSON file and locks the first-stage labels in that browser session.
   The Stage 2 file picker unlocks only afterward.
5. Load quality_packets.json, compare each anonymous model output against
   the corresponding blinded case evidence, and record factual-error count,
   unsupported-claim count and whether it is useful. Save each rating and
   export when complete.
6. Send the two exported JSON files privately to the coordinator. The
   coordinator runs evaluation.prepare resolve using the mapping on their
   own machine, then evaluation.score to compare systems.

The interface can Save draft and Import saved decisions/ratings to resume a
review. It does not persist information to any network or browser storage,
so a browser refresh loses unsaved progress. When resuming from a decision
draft, finalize the restored decisions again before viewing outputs. Reviewer
notes can be stored in exported submissions for later qualitative audit,
but scoring ignores notes.

**Important limitations:** this standalone page displays **textual
pre-decision evidence**. It does not render a camera replay or enforce stopping
a separately opened replay viewer at t0. Reviewer-provided decisions cannot
replace physically verified video/telemetry or high-rank expert adjudication.
A timestamped claim may still be semantically post-hoc if the exporter gave
it an incorrect finalized_through_s. Independently audit the source data.
Real nicknames and player identities must already be scrubbed by the producer.

A smoke test runs the review-state contract with Node when available and checks
that review.html remains a standalone, offline, staged reviewer page:
    python -m pytest tests/test_blind_review_ui.py -q

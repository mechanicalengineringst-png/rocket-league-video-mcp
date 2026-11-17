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

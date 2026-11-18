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

### Try the offline review page without real replay data

To test the controls before Antigravity supplies actual anonymized cases,
open **evaluation/review.html** locally and enter a reviewer code. Load:
- Stage 1: evaluation/demo/decision_packets.demo.json
- Stage 2 (after exporting Stage 1): evaluation/demo/quality_packets.demo.json

These are intentionally **synthetic** example situations and fake coaching
outputs, NOT real Rocket League measurements, expert labels or validated
model results. One quality sample is intentionally overconfident so reviewers
can practice identifying unsupported claims.

The packet generator now rejects conspicuous model-name self-references
(such as a model signing an output with its provider name or system ID).
This is not perfect de-identification; manually inspect model outputs for
other wording that could reveal identity before distributing them.

## Coverage-first 60-case pilot: detector cases AND independent controls

A pilot consisting entirely of detected kickoffs, 50/50s and defensive-role
events can measure the quality of a chosen critique but **cannot measure
moments the detector missed**. Do not assume 50 cases from a single replay
are an independent or representative tactical benchmark.

New helper `evaluation.pilot` selects a fixed 60-case candidate cohort, by
default **20 each** of `kickoff_support`, `first_man_challenge` and
`last_man_defense`. It requires **10 detector-selected and 10
independently time-sampled moments per category** and **at least three complete
replay groups**, with a default 5-second within-match separation across all
selected cases. If any stratum is absent, it stops with an explicit error
instead of silently substituting more easy detected examples.

Data producers must separately supply:
- **cases.json**: all anonymized, timestamped candidate cases in the standard
  PR #16 `pre_decision_evidence` schema, with distinct `replay_group` IDs;
- **selection_manifest.json**: a **private, coordinator-only** JSON array of
  `{"case_id":"case-a","origin":"detector"}` and
  `{"case_id":"case-b","origin":"independent_time_sample"}` entries.

An **independent_time_sample** must be drawn from eligible live-play moments
before the detector or future-outcome labels are examined; manually classifying
the moment's situation from its available pre-t0 game state is acceptable if
the labeling is independently audited. Relabeling an event picked by the same
detector as `independent_time_sample` would invalidate this evaluation.

Run from `coach-app/` (assuming a sufficiently broad pool exists):

    python -m evaluation.pilot --cases cases.json --manifest selection_manifest.json --predictions predictions.json --per-situation 20 --min-replays 3 --min-gap 5 --output private_pilot_selection.json --selected-cases pilot_cases.json --selected-predictions pilot_predictions.json
    python -m evaluation.prepare make --cases pilot_cases.json --predictions pilot_predictions.json --output-dir private_review_packets

Use only `private_review_packets/decision_packets.json` during Stage 1 and
only reveal the separate anonymous quality packets **after** initial human
decision verdicts are frozen. Never reveal `selection_manifest.json`,
`private_pilot_selection.json`, original player IDs, or future outcomes to
Stage 1 reviewers. The shortlist manifest is not a replacement for human
validation; false negatives and unlabelled valid plays must be counted.

**Known limitations:** the selector only validates supplied provenance labels,
not the actual method of independent time sampling. It guarantees neither
representative gameplay coverage nor true statistical independence; subjects
may recur across matches. Real validation should report detector recall on
an independent annotated time-sampled reference, false criticisms of sound
plays, good-play recognition, reviewer disagreement and held-out model
performance. A pilot with 60 labels is intentionally exploratory.


## NEW: 40-clip commitment-timing review (before tactical-quality scoring)

Claude's timing research found that our detected \`t0\` may occur after a player
committed. Human reviewers must establish **whether commitment is observable,
which action was taken, and a plausible commitment interval** before we ask
the later 60-case panel whether that action was strategically sound.

Separate implementation:
- \`evaluation/commitment_review.py\` — prepare 40 anonymized video packets,
  select 20 overlapping clips for a genuinely independent second reviewer,
  and calculate interval/timing/choice agreement from private mappings.
- \`evaluation/commitment_review.html\` and \`commitment_review_core.js\` —
  offline annotation page with local videos, fine seek controls, interval
  marks, observed choice, confidence, an explicit unobservable option, reviewer
  notes and local JSON export/import. No server, account, browser storage or
  paid AI service is needed.
- \`tests/test_commitment_review.py\` and
  \`tests/test_commitment_review_ui.py\` — synthetic protocol and Node/browser
  contract checks. These verify software logic, **not** actual Rocket League
  commitment correctness, true 60fps seek precision or accessibility across
  all browsers.

### Required source clips (produced elsewhere)

Antigravity's/native export or a separate trusted video pipeline needs to
provide enough cropped MP4/WebM moments from **at least three competitive
2v2 matches**, with an anonymized visual cue identifying the target car.
Each clip should show the movement before and shortly after candidate
commitment, without revealing the later goal, winner banners, match outcome,
usernames, other personal identifiers, or the original detector label. Video
frames may be inspected in retrospect for **timing annotation only**; this
does not authorize showing later behavior in predecision coaching.

The private candidate manifest is a JSON array with **exactly** these fields
per row:

\`\`\`json
{
  "case_id": "anonymized-match-one-candidate-1",
  "replay_group": "anonymous-match-one",
  "detector_choice": "challenge",
  "source_t0_s": 35.88,
  "clip_start_s": 32.88,
  "clip_end_s": 37.38,
  "clip_file": "local-private-clip-1.mp4",
  "focus_hint": "Follow the outlined blue car"
}
\`\`\`

The visible review packet has **no** \`source_t0_s\`, \`detector_choice\`,
\`replay_group\` or original filename. Video files get renamed to anonymous
\`T00001.mp4\` etc. Source filenames and timestamps are stored **only** in
\`PRIVATE_DO_NOT_COMMIT_commitment_mapping.json\`. A person may still
recognize a particular match from its visuals: manually scrub source clips.

From \`coach-app/\`:

\`\`\`bash
python -m evaluation.commitment_review prepare \
  --manifest private_manifest.json \
  --clips-dir private_clip_files \
  --output-dir evaluation/local_commitment_review
\`\`\`

This deliberately refuses insufficient data, including fewer than three
matches, not enough detector-choice strata (15 challenge / 15 shadow / 10
unclear), and within-match duplicated moments less than 5s apart. These
strata are **detector claims**, not human truth, and the sample is NOT
randomly representative of gameplay. The original video export is the
upstream responsibility; the preparation script cannot synthesize videos.
Source clips must vary their pre-t0 lead-in by detector stratum. A fixed
clip offset allows reviewers to infer t0 even without an explicit marker;
prepare refuses a selected stratum with almost constant offsets. This
is a validation guard, NOT a jittering video exporter. Time metadata must
match the actual rendered video, and clips should end near the reviewed
commitment rather than showing goals/outcomes (at most 3.5s after t0).
Only neutral hints such as "Follow the outlined blue car" are accepted;
never mention challenger/shadower, roles, names, or detector verdicts.

**Blocking source dependency:** the 15 shadow cases cannot be filled
from future 50/50 challenge detections or manually guessed labels. There
is no independently pre-registered shadow-candidate exporter in this PR.
Create and audit that upstream exporter before running the 40-clip pilot;
this coordinator intentionally does not fabricate a shadow source.

### Human review workflow

1. Give Reviewer A \`primary_packets.json\` and the 40 renamed video files.
   Give Reviewer B the separate \`secondary_packets.json\` and its 20
   overlapping video files. Never give either the private mapping.
2. Open \`evaluation/commitment_review.html\` by double-clicking it in a
   modern browser. The companion \`commitment_review_core.js\` must be
   in the same folder. Load packet JSON; select the relevant anonymous
   MP4/WebM clips (multiple selection).
3. Reviewer chooses observed choice — challenge, shadow, fake, other or
   unclear — then marks **earliest and latest plausible reversible-choice
   bounds** from video times. If not reliably visible, choose
   **Not reliably observable** rather than forcing a number. Save a note
   describing what prevented reliable timing.
4. Export a draft JSON periodically. The browser doesn't remember work
   on reload, but saved reviewer JSON can be imported to resume. Export
   final JSON only after all assigned cases have a recorded review.
5. Coordinator runs:
   \`\`\`bash
   python -m evaluation.commitment_review analyze \
     --private-map evaluation/local_commitment_review/PRIVATE_DO_NOT_COMMIT_commitment_mapping.json \
     --primary primary_rater_final.json \
     --secondary secondary_rater_final.json \
     --output PRIVATE_commitment_results.json
   \`\`\`
   The output is a **private study report**: two-reviewer choice agreement,
   interval endpoint agreement within 0.3s, the proportion deemed unobservable,
   median time gap from detector \`t0\` to Reviewer A's last reversible moment,
   and detector-vs-human choice agreement where both are readable.

For the predefined 20 overlapping clips, Claude proposed treating >=14/20
endpoint agreements within 0.3s as encouraging evidence that commitment
timing can be annotated. A median detector lead >=0.5s suggests t0 is late; <=-0.5s suggests
that t0 is early. Consistency requires |median lead| <0.25s AND at least
70% of observed cases individually within 0.25s; mixed early/late errors
must not cancel in the median. Intermediate cases are inconclusive. **Do not turn these pilot cutoffs into
claims of validated physical irreversibility or tactical quality.**

Known limitations:
- The video export can still include future/outcome cues; the local review
  interface cannot prove blinding.
- The clip may not expose all physical alternatives, player inputs or mental
  intent. Recorded movement and the true decision are different.
- The latest plausible point is a human judgment, not a formal collision
  or reachability guarantee; a jumping car may still steer.
- Camera quality, playback resolution and video timing affect raters.
- The comparison excludes \`unclear\` detector cases from readable-choice
  agreement and reports the denominator, rather than quietly claiming
  the model labeled every case.
- Reviewer comparison reports are private and match-correlated; the
  second rater's 20 overlapping clips are not another 20 independent matches.
- Run the broader 60-case tactical-quality study **after** timing/provenance
  issues have been resolved. Don't merge research modules into live coaching
  without expert review.

## Round 5: Paired, replay-grouped comparison before claiming a coaching improvement

Use the same frozen independently reviewed cases and two actual candidate-system
prediction exports. Do not let a model with one cherry-picked correct answer
appear stronger than a system that attempts every difficult case.

From coach-app:

```bash
python -m evaluation.paired_compare \
  --cases local_review/cases.json \
  --predictions local_review/predictions.json \
  --reviews local_review/resolved.json \
  --system-a baseline-rules \
  --system-b candidate-model \
  --bootstrap-samples 2000 \
  --output PRIVATE_paired_comparison.json
```

The tool reuses the strict predecision evidence, review and prediction
validators from evaluation.score, then compares *both* systems on the exact same
two-reviewer consensus cases. Expert-disputed, indeterminate or unreviewed
moments are reported separately, never promoted into ground truth.

Four distinct metrics are reported:
- grounded_correct: correct expert-consensus label WITH citations referencing
  keys available at t0; missing/abstained/uncited outputs count as zero.
- grounded_coverage: fraction of reviewed cases receiving any citation-valid
  non-abstaining assessment (not a semantic correctness guarantee).
- false_blame_on_sound: risk accusations on moments expert reviewers marked
  sound, even when those accusations have no valid citations.
- unsupported_attempt: an attempted non-abstaining output with absent, unknown
  or duplicated evidence citations.

For each metric, read the case-weighted rate and the equal-match-weighted rate.
A replay with 50 highly correlated moments must not silently outweigh a replay
with five. A deterministic cluster bootstrap resamples whole match groups,
never individual frames, to provide an *exploratory* 95% interval for the
equal-match difference (first system minus second). An interval is omitted
rather than invented if fewer than three match groups contain eligible cases.
No p-value, population generalization, expert truth or automatic architecture
winner is asserted. Interpretation still requires matching comparable player
skill, mode, source quality, and reliable human judgments.

The standard benchmark evaluation.score remains the canonical raw scorer.
paired_compare is independent of all live coaching endpoints and does not call
or train any AI model. It is a measurement tool, not evidence that either
current system is high-rank accurate. Before publishing comparisons, audit the
cohort provenance, independent selection rates and every source-video clip.


## Round 5: Packet freshness / resampled-actor provenance audit

The existing coach_app/subtr_replays.py calls subtr_actor.get_ndarray_with_info_from_replay_filepath with fps=FPS and packages its output into one ROW timestamp for all actors. The row timestamp is NOT proof that every car/ball received a fresh native network update at that instant. An actor can be carried forward, resampled, missing, or legitimately stationary. The current normalized payload does not preserve a distinct last native actor update timestamp for each actor. This is separate from Claude PR #21's future-frame leakage check.

A read-only diagnostic, requiring no parser/GPU/model dependencies:

    # Run from coach-app, keep private source JSON and the audit private.
    python -m evaluation.packet_freshness --replay-json private_local/decoded_2v2.json --cases private_local/decision_cases.json --output private_local/packet_freshness_audit.json

Case inputs support {case_id,t0,focus_player_id} or Claude-style {decision_case_id,decision_time_s,focus_player:{id}} or blinded benchmark case rows without a focus ID. In the latter case all rostered players plus the ball are audited; no focus is guessed.

For each requested t0 it chooses only the latest OUTPUT frame at or before t0 (default maximum lookback 0.15 seconds). It reports selected-frame age, missing/demolished/incomplete states, and consecutive identical resampled-value runs. Identical runs are NOT stale-packet evidence: stationary game actors can remain unchanged.

Every result currently says native_packet_freshness: unverifiable. An experimental nativeUpdateTimeS optional field from any future decoder is reported only as an UNVERIFIED hint, never a certificate; impossible post-row/post-t0 time hints are rejected. This project currently has no authoritative source-time extractor. Never promote inferred visual states to coaching facts on this evidence alone.

NEXT: Independently implement and audit a raw native-actor-update source-time collector. Measure real replay per-actor update intervals, match them to dense ndarray samples, and quantify uncertainty around the exact decision times. Only then add a calibrated production coaching freshness policy. The current auditor changes no replay data or live coaching, does not call a model, and makes no unsupported native freshness claims.

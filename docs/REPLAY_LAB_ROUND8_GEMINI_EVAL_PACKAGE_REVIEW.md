# Replay Lab — Round 8 Gemini Evaluation Package: Critical Integration Review

**Checkpoint:** 18 Nov 2026 UTC. **Status: design review, not implemented benchmark or expert-grade proof.**

The owner supplied Gemini's 495-line `replay_lab_round8_evaluation_package.md` in ChatGPT. Its proposed name is **RL-EvalPilot-12**. This memo reconciles that design with **real GitHub implementation** and establishes the safe next engineering boundary. Gemini explicitly disclosed it could not inspect the private repo. The original attachment remains the research proposal; the decisions here are canonical until revised.

## Decision summary

**Adopt with corrections.** Keep: ~12-case diagnostic pilot; strong vs misleading-outcome examples; explicit defense of well-judged aggression; expert selection of **sets of defensible actions**, not one "optimal" label; early-root-cause questions; multi-factor blinded explanation quality; skeptical follow-ups; exact factual-error annotations; A deterministic vs B fixed-evidence model. The pilot is for **falsification/UX feasibility**, not a representative estimate of false-criticism prevalence or a statistical efficacy claim.

**Correct before implementation:** time/method of case selection; pre-decision human blinding; actual `DecisionEvidenceV0` schema, player state freshness and decoder provenance; **PR #16 existing capabilities**; scoring-schema compatibility; 8-vs-9 rubric; output privacy and invented quantitative implications.

## Grounding in existing source

- [Claude PR #22](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/22): `coach-app/coach_app/decision_evidence.py` exposes `build_decision_evidence(payload,t0,focus_id,...)`, lists `evidence` (E./C.), `unknowns` (U.), `not_observable` and **separate** `retrospective`. Its builder does not supply expert labels, counterfactual numerical EV, raw camera awareness or verified native packet ages. Latest claimed 636/636 future-invariance cases are causal-fidelity checks, not expert reviews.
- [ChatGPT PR #27](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/27): `build_stage1_packet()` **whitelists an already-built single decision snapshot**. It is **not** an interactive video scrubber, an 8-second episode extractor, a pre/post-t0 video renderer, a hash-locking server, nor a clip exporter.
- [ChatGPT PR #29](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/29): `verify_stage1_claims()` checks existing source IDs and typed source-value predicates. Free-text tactical meaning is deliberately **never machine-certified**. Use it instead of Gemini's proposed unimplemented `scripts/pre_audit_claims.ts` when a typed claim is available; human audit remains essential.
- [Blind evaluation PR #16](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/16): actual existing `coach-app/evaluation/prepare.py`, `score.py`, `pilot.py`, `review.html`, `review_state.js`, `commitment_review.html`. The **tactical** blind-review UI reads anonymized JSON evidence packets; its own README explicitly states **there is no embedded replay renderer**. It does stage-1 decision verdicts (sound/risk/tradeoff/indeterminate) before stage-2 anonymous-quality feedback; this is **local exported review state**, not a server-signed cryptographic lock. The separate `commitment_review.html` is a 40-clip **commitment-timing** tool, not a tactical-merit video scrubber. Existing `evaluation.pilot.select_pilot()` deliberately combines detector and **independently sampled moments**; don't replace that check with 100% detector-selected cases.
- Actual `coach-app/coach_app/subtr_replays.py` says its ndarray rows are **RESAMPLED** at 30 Hz; 0–255 boost is **converted** to 0–100 in exported rows. Replay-native events may carry hindsight-derived semantics. `DecisionEvidenceV0` flags repeated samples and boost freshness as uncertain; **there is no validated `stale_ticks` source in the current normalized packet**. Boxcars/raw updates require separate implementation and verification.
- Existing score API uses a **strictly different** case schema (`case_id,t0,situation_type,pre_decision_evidence`), predecision individual evidence fields (`key,claim,event_time_s,finalized_through_s,source,source_quality`), and a 4-way verdict. Gemini's 8-action sets, 9-dimension rubric and `pilot_12_scenario_manifest.json` require an explicit validated adapter plus scoring extension; they cannot be dropped into PR #16 as-is.

## 1. Selection and blinding correction — critical

Gemini calls its structural buckets "non-evaluative" yet **B01, B02, B03, B04, B05** expressly select on **post-t0** events (ball spill, goal within 4s, an opponent miss, successful challenge). This is fine for an intentionally *outcome-stratified adversarial stress test*, but:
- It is NOT a prospective/predecision-only random cohort, nor a sample for population error rates. The selection method and outcomes belong in a **coordinator-only manifest**.
- No such future selector fields may be passed into `DecisionEvidenceV0` Stage 1, a review packet, model prompt, or deterministic baseline. Gemini's proposal for Condition A to read `automated_selector_predicates` is unsafe because its **synthetic manifest embeds `post_t0_outcome_summary_quarantined` underneath that object**. Strip selectors and retrospective metadata completely before creating any model input.
- For a practical first **12-case** diagnostic set, use **4 independent-time/detector-balanced reference cases** chosen without outcomes, **plus 8 targeted adversarial stress cases** (roughly one from each B01–B08, where feasible). Label the two panels separately in all scoring and preserve match/identity deduplication. Do not report their pooled false-blame rate as a population estimate. If scarcity prevents a bucket, disclose the absence, do not fabricate cases. Expand later to PR #16's larger coverage-first design.
- Freeze exact source replay hashes, case IDs, t0, selection policy, and permitted cohort; then generate competing coach outputs. Hashes in Gemini's **synthetic** examples, including the common empty-content SHA256, are placeholders and MUST NOT be promoted to real evidence.
- Never assume a 1575 MMR threshold proves "GC2 current rank" across seasons/modes; verify actual 2v2 playlist + season + provenance separately. The 15 existing real replays are rank-UNVERIFIED.

## 2. Human two-stage review correction — critical

Gemini's proposed **Phase 1** form both hides post-t0 media and asks humans to grade the **actual chosen action**. Claude's `observed_action` is finalized *after* t0 and lives in `retrospective`. A reviewer cannot reliably know that choice while frozen at t0. Recommended flow:

**Phase 1a (true ex ante):** watch only [t0−8s,t0] with **verified media cutoff**, score *sets of defensible actions* and constraints, earlier contributing cues, confidence/unknowns. Do NOT show observed action label, final result, quality output or why case was selected. Freeze/export this response.

**Phase 1b (observed action, no final outcome):** optionally show only the minimal post-t0 commitment interval and ask whether the observed action belonged to the **already-frozen Phase 1a acceptable set**; do not alter it. If commitment interval is not reliably isolatable, record `action_unobservable` and score after reveal with provenance labeling. Do not represent Phase 1b as strictly t0-only.

**Phase 2a (blind coaching explanation):** show normalized A/B replies **before outcome reveal**, assess source correctness, alternatives, teammate cover, early root causes, and value of the specific lesson. Keep system IDs hidden and preserve reviewer-level data.

**Phase 2b (retrospective):** disclose subsequent touches/goals and rate whether postdecision explanation fairly separates decision merit from execution/outcome. This prevents the reviewer from anchoring to a conceded goal *before* evaluating an ex ante explanation.

A true media lock must be enforced by clip trimming or a trusted playback service; merely moving the JavaScript scrubber or using the PR #27 JSON serializer does not prevent a reviewer from opening the source file. No server signed phase1 lock, crypto timestamp, two-stage 3D editor or /api/eval/phase1 endpoint exists in PR #16 today. Continue with PR #16's **local exported packet workflow** until the video/UI extension is actually implemented. Do not claim reviewer identity is cryptographically verified.

## 3. Metric and schema corrections

- Proposal says "8 mandatory dimensions" but supplies **D1–D9**; D9 is a ninth follow-up dimension. Decide on eight initial quality dimensions plus a **separately rated D9 follow-up**, not an inconsistent denominator.
- Keep the useful eight-action vocabulary as a multi-select **reviewer taxonomy**, but types such as `GRAB_100_BOOST_OR_DEMO` and `PASS_OR_CLEAR_TO_SPACE` merge strategically different actions. Allow optional modifiers or split after pilot feedback rather than claiming mutually exclusive natural actions.
- `D3_TEAMMATE_SUPPORT` must not require an **exact** recovery window if only rough kinematic bounds exist. A grounded conditional caveat earns credit; fabricated "1.6s" does not.
- `D4_POSSESSION_PRESSURE` should not imply we observe a *counterfactual* next controlled touch. Measured actual next touches belong after t0; a hypothetical collection must stay conditional.
- `D7_FACTUAL_UNCERTAINTY` should evaluate documented repeated/stale *heuristics* and missing flip/vision info; do not use missing `stale_ticks` as if measured.
- `NONE_VERIFIED_ACCURATE` in the proposal's claim error taxonomy must not imply that source ID equality machine-verified the full English statement. Use `NO_ERROR_FOUND_BY_REVIEWER` or separate structural `claim_verifier_status` vs human `factual_judgment`.
- If an independent reviewer disputes an action, retain reviewer-level labels and note why (uncertain, interpretation, style) rather than converting the confidence-dependent "defensible union" into an infallible expert truth.
- Report **raw counts + numerator/denominator + exact stratification + coverage**; no promised 0/12, false-criticism percentages or significance from 12 cherry-picked/high-stakes adversarial cases.

## 4. Minimal implementation order (no big architectural rewrite)

1. **Mapping layer** (new small module, owner to assign): `DecisionEvidenceV0` → `build_stage1_packet()` → strict PR #16 `pre_decision_evidence` rows; preserve each evidence item's `source_time_s`, provenance and unknowns without manufacturing a `finalized_through_s`. If a derived estimate cannot document its latest contributing data, mark the gap and fail safe. Keep coordinator-only source IDs and case selection data outside reviewer packet.
2. **Pilot manifest extension** (PR #16 side): add *separate* coordinator-only `selection_origin`, `stress_bucket`, `rank_verification` and source hashes; adapt existing `evaluation.pilot.select_pilot()` rather than replacing it. Freeze and audit 12 actual replays before any model comparison.
3. **Local reviewer workflow**: extend existing packet UI schema for acceptable action sets and confidence with explicit Phase 1a freeze/export. Do not claim an integrated pre-t0 replay viewer until built and tested. For initial pilot, provide a physically **trimmed** clip with no future material, or expert review of source-cited state packets if clips are unavailable.
4. **Fixed-packet A/B**: deterministic template and LLM receive the *same sanitized Stage1 packet*, no selection metadata/outcome. Gemini provider requires owner opt-in, current API availability, cost cap and redaction check. Apply ChatGPT's PR #29 typed-verifier gate to candidate factual assertions where available, but mark free text unverified pending review.
5. **Quality scoring**: extend or postprocess PR #16 quality outputs for D1–D8 (plus separate D9), action-set disagreement, speaker-agnostic specificity, false criticism; first prove the new rules with synthetic tests, then independent human raters and real clips. Preserve anonymous candidate mapping offline and never publicly commit individual platform IDs, expert reviewer credentials, or raw user-replay paths.

## Decision / next action

- **Accepted:** 12-case adversarial diagnostic, option-set expert labels, false-criticism traps, prior-root-cause evaluation, randomized paired A/B with reviewer-level disagreement.
- **Deferred:** server-signed stage lock, full clip-scrubber integration, raw-packet freshness, exact camera/flip availability, actual next-touch counterfactuals, numerical EV or training, external MMR-verified public replay fetching, real cloud LLM inference without consent.
- **Immediate coding target:** one *small* strict PR #22/#27 → PR #16 evidence adapter and 2–3 synthetic contract tests, then a pilot manifest and reviewer form update. Native replay companion PR #28 is independent and **not required** to begin this local evaluation.
- **Validation state:** This document is based on inspection of actual PR #16, #22, #27 and #29 files and the submitted Gemini proposal. It does not assert 12 clips exist, any expert labels are collected, or benchmark metrics are measured.

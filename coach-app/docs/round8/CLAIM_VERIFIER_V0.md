# Round 8 — ClaimVerifierV0 Handoff

Status: Draft PR #29, stacked on Stage 1 firewall PR #27 and Claude PR #22. No external model calls and no native-game operations.

## Scope

Python module: coach_app/claim_verifier.py
Entrypoint: verify_stage1_claims(packet, claims)
Test module: tests/test_claim_verifier.py

Input must be Stage1DecisionPacketV0 built by stage1_packet.build_stage1_packet(build_decision_evidence(...)). It deliberately excludes post-decision events and personally identifying player IDs from the model packet.

Verifier checks:
- E./C. cited evidence IDs exist and source_time_s does not exceed t0; U. is an unknown, not a fact; R. retrospective IDs are forbidden.
- A source-derived reachability/role estimate cannot be represented as an OBSERVED_FACT.
- PHYSICALLY_ESTIMATED_FEASIBILITY must cite actual evidence with kinematic-model provenance.
- Structured scalar assertion (evidence_id, value_path, relation, stated_value) must match the cited source value, with modest formatting/rounding tolerances only. Relations: eq, gte, lte.
- A numeral appearing in free-form text must match a valid structured predicate; otherwise reject. This heuristic is not a semantic entailment checker. A correct citation attached to unsupported words may still pass structure and require review.
- Missing/unobservable/stale information must remain explicitly caveated; no assumption of known human intent, field of view, or teammate calls.

## Return statuses

- rejected: contradiction, unsupported ID, future timestamp or invalid claim
- structured_fact_verified: typed numerical scalar and valid observed evidence, **without free text or unresolved warnings**. This is NOT a tactical verdict.
- needs_semantic_review: structure passes but text meaning or tactical inference remains unverified.

The result field all_factual_text_verified remains false in V0 by design. Do not use passing source IDs as proof that a model's tactical explanation is true.

## Synthetic example

~~~json
{
  "claim_id": "claim1",
  "epistemic_type": "OBSERVED_FACT",
  "temporal_scope": "PRE_DECISION",
  "cited_evidence_ids": ["E.focus.boost"],
  "predicate_checks": [
    {"evidence_id": "E.focus.boost", "value_path": [], "relation": "eq", "stated_value": 50.0}
  ],
  "text": "You had 50 boost."
}
~~~

If the source E.focus.boost is actually 50 and was observed by t0, the numeric check passes; the text still requires semantic review. A missing boost value is unknown, not zero. A false value such as 67 is rejected even with the correct citation.

For position vectors, value_path [0] selects x. For E.reach.focus, value_path ["t_min_s"] selects an estimated reachability bound; its epistemic type must not be OBSERVED_FACT.

## Episode integration warning

Claude's forthcoming episode may contain 2–3 different decisions with the *same local evidence ID* E.focus.boost but different values and t_i cutoffs. Do not concatenate those records into a single unnamespaced lookup. Use (episode_id, decision_id, evidence_id) as the globally unique reference. Verify every decision's Stage 1 record independently at its own t_i. Lock Stage 1 before allowing any Stage 2 retrospective output.

Tests cover numeric contradictions including seconds/boost, correct-but-insufficient citations, no future evidence, unknown-vs-zero boost, invalid categories, unsupported cameras, abstention, hypothetical claims and wrong reachability provenance.

No measured false-criticism rate, expert tactical correctness, calibrated EV, cloud model test, or gameplay capture in this PR.

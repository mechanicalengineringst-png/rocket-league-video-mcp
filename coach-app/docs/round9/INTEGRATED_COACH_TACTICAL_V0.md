# Round 9 — Integrated Tactical Coach Contract (draft PR #33)

**Status:** Cross-agent backend integration is tested; **frontend branch has not yet been published to this GitHub repository**. Do not call the full browser experience backend-integrated without a real browser-to-backend test.

## Composition

- Claude PR #32 `TacticalOptionsV0` -> nine option families from decision-time reachability, boost and cover data (uncalibrated policy/0.1; no unique best, no simulated outcomes).
- ChatGPT PR #31 `CoachLessonV0` and `CoachDraftV0` -> deterministic source facts or **opt-in** proposed language-model lessons, with numeric/citation checks and no retrospective data.
- Integrated PR #33 adds `tactical_coach_adapter.py`, verifies EVERY native tactical claim against the exact node's `ClaimVerifierV0`, and supplies a vetted `CoachTacticalContextV0` to the model transport and lesson response.

The adapter validates action names, feasibility/stance consistency, claim IDs and source links. **It does not validate English tactical semantic entailment or professional coaching merit**.

## API for Antigravity's frontend

The existing [Round 9 backend API specification](../../docs/round9/COACH_BACKEND_V0.md) is unchanged except that `POST /api/coach/lesson` adds the **`tactical_options`** field (below). All endpoints remain in `coach_app/coach_api.py`, registered in `main.py`.

- `GET /api/coach/capabilities`: local baseline available; opt-in model capability reported truthfully.
- `POST /api/coach/lesson`: requires decoded **four-player 2v2 replay**, focus player ID, 2–4 manually chosen ordered decision timestamps in a 5–20 second window, and optional `mode` (`deterministic` by default).
- `POST /api/coach/evidence`: same request plus `evidence_refs` (1–20 unique references), resolves actual sanitized node facts, uncertainty, timeline, changes or hypotheses **without** retrospective leakage.
- `POST /api/coach/followup`: same episode plus question, **local evidence-navigation only**. It is not a genuine free-form model conversation, and its answer should be labeled accordingly.

### Newly integrated `CoachLessonV0.tactical_options`

~~~json
{
  "schema": "CoachTacticalContextV0",
  "node_id": "N3",
  "decision_time_s": 11.0,
  "status": "ok",
  "calibration": {
    "status": "uncalibrated_rule_hypothesis",
    "policy_version": "tactical-options-policy/0.1",
    "expert_validated": false,
    "expected_value_modeled": false,
    "picks_single_best": false
  },
  "options": [{
    "action": "immediate_challenge",
    "physical_feasibility": "yes",
    "strategic_stance": "defensible",
    "defensive_risk": "not_elevated",
    "feasibility_claims": ["N3.c1"],
    "supporting_claims": ["N3.c6"],
    "limiting_claims": [],
    "severe_limit_claims": [],
    "team_context_claims": [],
    "depends_on_teammate": true,
    "depends_on_unobservable": ["flip availability", "carrier's intent"]
  }],
  "defensible_options": ["immediate_challenge"],
  "claims": [{
    "claim_id": "N3.c6",
    "node_id": "N3",
    "epistemic_type": "TACTICAL_INFERENCE",
    "text": "The focus player can reach the ball clearly before the nearest opponent.",
    "evidence_refs": ["N3/E.reach.focus", "N3/E.reach.opponent_1"],
    "review_status": "needs_semantic_review",
    "semantic_accuracy_verified": false,
    "review_warnings": []
  }],
  "earlier_contributors": [],
  "abstain_reasons": [],
  "unknowns": [],
  "validation": {
    "structural_claims_verified": 1,
    "rejected_tactical_claims": 0,
    "semantic_tactical_accuracy_verified": false,
    "retrospective_used": false
  }
}
~~~

**Illustrative JSON with shortened lists, not an actual analysis of a player.** The real response includes all nine action families or none on abstention, plus actual source IDs.

### Model support

`CoachDraftV0.claims[]` now optionally accepts `tactical_claim_ids: ["N3.c6"]`; each ID must actually occur in locally built `tactical_options.claims` for that decision, and must be grounded in underlying `cited_evidence_ids` of the `N3/E...` or `N3/C...` form. Fabricated/cross-node claim IDs are rejected.

**No automatic AI model calls:** `mode:"model"` plus an explicit server environment opt-in and a configured provider are both required. Default `deterministic` mode shows source facts + a deterministic option menu; its top-level assessment remains `undetermined`. Returned model judgments are labeled *hypotheses*, never verified SSL coaching.

## Frontend integration acceptance gates

1. **Distinguish real backend from fixtures** clearly. Never present a three-case `coaching-fixtures.js` demonstration as analysis of the user's uploaded match. For a real match, call `/api/coach/lesson`, and render `tactical_options` rather than hard-coding stances, options or causal links.
2. **Show uncalibrated tactical stances as possibilities**, not definitive warnings, blame or expert recommendation. No direct `Concern` label without acknowledging uncertainty and why a source supports it.
3. **Citations:** clicking an `N3/E...`, `D...` or `H...` tag calls `/api/coach/evidence`. Display raw recorded values and source provenance, or explicit unknown/derived/hypothesis status. The local backend can only resolve IDs that actually exist.
4. **Privacy & cutoff:** Stage 1 API delivers only decision-time data. Avoid leaking `retrospective`, winner/outcome fields or preselected result labels into UI or model prompts. A client-side toggle alone is not a trusted freeze for blinded expert research. A dedicated Stage 2 server contract is **not yet implemented** in PR #33.
5. **Follow-ups:** the current `/api/coach/followup` is evidence-navigation and must be labeled as such. Do not synthesize generic AI responses or cite nonexistent fields such as `E.teammate.spacing` unless those IDs exist in the packet.
6. **Playback:** seeking a decision must be bound to actual replay timestamps; camera and native-game controls remain separate, and live native client acceptance has not been performed.

## Validation

PR #33 combines PR #31 and PR #32 with a two-parent Git merge plus new strict adapter and synthetic integration tests. **GitHub exact-head check:** 307 passed, four skipped in coaching suite; general CI and camera-and-geometry both succeeded at first integration SHA `bb45c22`. No GC2/SSL tactical-accuracy trial, paid provider call, Windows gameplay or frontend host/browser verification occurred in this integration.

## Pending dependency — Antigravity frontend

Antigravity reported `feature/round9-coaching-experience-20261118` at local commit `d8700a1` and a host-verified screenshot/report. **The branch and commit were NOT present in the connected GitHub repository on review** (branches and open PRs checked). To inspect or integrate the actual UI, Antigravity must push its commit to `mechanicalengineringst-png/rocket-league-video-mcp` and open a draft PR with an exact comparison base. Its local browser tests may be valid but have not been independently inspected here. Do not re-create its unpublished work or claim it is already merged.

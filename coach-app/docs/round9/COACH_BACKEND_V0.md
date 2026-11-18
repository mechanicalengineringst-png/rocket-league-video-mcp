# Replay Lab Round 9 — CoachLessonV0 Backend Contract

**Implementation:** draft PR #31 stacked on integrated episode-evidence PR #30.
**Date:** 18 November 2026. **Engineering status:** first working lesson backend and opt-in model transport. **NOT expert-evaluated coaching.**

## What exists now

`coach_app.coach_lesson.build_lesson_from_episode(episode, *, model_draft=None)`:

1. Constructs a strictly sanitized `Stage1EpisodePacketV0` from Claude's `EpisodeEvidenceV0` (PR #22) using the audited serializer in PR #30.
2. Emits a deterministic baseline of observed, citable focus and teammate boost facts without pretending to decide tactical merit.
3. Optionally admits a proposed `CoachDraftV0` from an **external or locally configured** language model. Each proposed claim is bounded, classified, anchored to a target decision and evidence refs, verified against the existing `ClaimVerifierV0` at each cited node, and screened for unsupported numeric statements. Claims with invalid source values, future-node references, retrospective references, or unverified certainty about H. hypotheses are **excluded** and reported.
4. Retains sanitized `H.` earlier-contributor references as **hypotheses only**. Exposes primary-node U. unknowns and limitations; never transmits actual retrospective outcomes to the model.
5. Never labels the resulting prose `semantically_verified`. Even a passed typed observation cannot independently prove whether a tactical recommendation is sound.

`coach_app.coach_model.propose_coach_draft(stage1_packet)`:

- Provider-independent OpenAI-compatible HTTP JSON transport.
- **Disabled by default.** A call requires BOTH the user's explicit API request `mode:"model"` AND `REPLAY_LAB_ENABLE_COACH_MODEL=1` on the local server.
- Configuration is entirely server-side: `REPLAY_LAB_COACH_MODEL_URL` must be a configured `/chat/completions` endpoint; `REPLAY_LAB_COACH_MODEL_NAME` required; `REPLAY_LAB_COACH_MODEL_API_KEY` required for HTTPS. Non-local HTTP is refused.
- No model-specific training, provider preference, cost assumption or cloud call was made by implementing this. Do not enable a paid provider without explicit owner consent.
- Maximum sanitized prompt 128 KiB; model response up to 24 KiB of JSON. Provider errors are sanitized and never returned verbatim.
- No automatic fallback from a failed paid model call to an apparently successful AI answer; the API reports failure explicitly.

## HTTP API for Antigravity frontend

Server already enforces loopback allowed hosts and same-origin writes.

### GET /api/coach/capabilities

~~~json
{
  "schema":"CoachCapabilitiesV0",
  "lesson":"CoachLessonV0",
  "followup":"CoachFollowupV0",
  "local_deterministic_available":true,
  "optional_model_enabled":false,
  "model_requires_request_opt_in":true,
  "stage":"predecision",
  "automatic_episode_selection":false,
  "tactical_accuracy_expert_verified":false
}
~~~

`optional_model_enabled` signals the explicit server gate, not a verified successful provider request.

### POST /api/coach/lesson

Request JSON:

~~~json
{
  "replay": {"players": [], "frames": [], "events": [], "title":"..."},
  "player_id": "b1",
  "decision_times": [2.0, 6.0, 10.0],
  "episode_start_s": 0.5,
  "primary_t0": 10.0,
  "mode": "deterministic"
}
~~~

The `replay` object is **the entire decoded in-browser replay object** from the existing `/api/replays` response, with four players (2 blue + 2 orange), position/boost frames and optional events; the empty arrays above are placeholders, NOT a valid request. Limit 24 MiB and 30k frames. Times must be 2–4 distinct valid decision moments in a manually selected 5–20-second window; the primary time is the latest one. This route **does not auto-pick decisions** or fetch replay files from the owner's disk.

Response shape (abbreviated; values depend on actual source):

~~~json
{
  "schema": "CoachLessonV0",
  "stage": "predecision",
  "mode": "deterministic_baseline",
  "decision": {
    "node_id": "N3",
    "t0_s": 10.0,
    "episode_start_s": 0.5,
    "status": "ok",
    "other_decisions": [{"node_id":"N1","t0_s":2.0,"status":"ok"}]
  },
  "assessment": {
    "grade":"undetermined",
    "status":"no_verified_tactical_verdict"
  },
  "claims": [{
    "claim_id":"base-focus-boost",
    "node_id":"N3",
    "section":"observation",
    "epistemic_type":"OBSERVED_FACT",
    "text":"Recorded focus boost was 10.",
    "evidence_refs":["N3/E.focus.boost"],
    "predicate_checks":[{"evidence_id":"E.focus.boost","value_path":[],"relation":"eq","stated_value":10}],
    "review_status":"needs_semantic_review",
    "review_warnings":[],
    "author":"deterministic_template"
  }],
  "earlier_factors":[{
    "hypothesis_id":"H.1",
    "earlier_node":"N1",
    "evidence_refs":["D.N1-N2.focus.boost","N1/E.focus.boost","N2/E.focus.boost"],
    "status":"hypothesis_unverified"
  }],
  "uncertainties":[],
  "not_observable":["..."],
  "validation":{
    "stage1_packet_sha256":"...",
    "accepted_model_claims":0,
    "rejected_model_claims":[],
    "semantic_tactical_accuracy_verified":false,
    "future_outcomes_used":false,
    "note":"Evidence-checking and numeric agreement do not validate strategic merit."
  },
  "followup_supported":true
}
~~~

**UI rendering rules:**

- Timestamp and replay seeking come from `decision.t0_s`; earlier-node tabs from `other_decisions`.
- Group claim cards by `section`: observation, tactical_context, alternative, earlier_factor, takeaway, uncertainty.
- Resolve `N<k>/E...` citations by building the **same** episode on backend, not from invented frontend text; `H.` labels are questions and not causes. Do not expose raw `retrospective` in Stage 1.
- `review_status="needs_semantic_review"` means source references and structured numbers were checked but the English/tactical content has not been expert approved.
- `assessment.grade` on model proposals is a hypothesis, not an externally validated truth. Display that caveat.
- If `rejected_model_claims` is nonempty, show the number excluded or a safe warning, not a fabricated substitute.
- Render ALL model-provided strings as text, never raw HTML.

Response codes: `403` model server disabled, `503` model enabled but missing configuration, `502` provider/structured-response failure, `413` request too large, `415` not JSON, `422` malformed replay or unsafe episode.

### POST /api/coach/followup

Same request as the lesson, plus `question` (1–500 characters). `mode` must be `deterministic` in V0.

Returns `CoachFollowupV0` with `topic` (`boost`, `teammate_support`, `earlier_contributors`, `feasible_options`, `not_supported`), `related_refs` and a conservative answer. It **does not invoke an LLM** or claim natural-language follow-up intelligence. A model-backed multi-turn dialogue requires a later explicit implementation.

## Proposed CoachDraftV0 for a model

~~~json
{
  "schema": "CoachDraftV0",
  "assessment": "tradeoff",
  "claims": [
    {
      "claim_id": "c1",
      "node_id": "N3",
      "section": "alternative",
      "epistemic_type": "HYPOTHETICAL_ALTERNATIVE",
      "temporal_scope": "PRE_DECISION",
      "cited_evidence_ids": ["N3/E.focus.boost", "N3/E.ball.position"],
      "predicate_checks": [],
      "text": "Delaying the challenge might preserve a viable defensive option."
    }
  ]
}
~~~

- Model can mention earlier decisions by citing `N1/E...`, `N2/E...`, plus `H.` contributor **hypotheses**; Stage 1 chronological availability is enforced.
- All model numeric statements require matching typed `predicate_checks` on **actual node** observations.
- Unsupported words can still slip through: a numeric/citation check is not a semantic entailment engine. An external reviewer or future stronger semantic gate must assess tactical correctness.
- Do not use `D.` changes for definitive numeric arithmetic: PR #30 marks their math as not independently checked.
- A returned model verdict is only surfaced when a non-factual, correctly cited candidate tactical claim survives the gate; otherwise lesson grade is `undetermined`.

## Parallel agent integration rules

- **Claude** is building `TacticalOptionsV0`; not included yet. When it arrives, adapt its concrete schema into a **source-bound, validated set of possible actions** before sending to the model. Do not accept arbitrary model-provided "physical certainty" or change the claim verifier's assumptions.
- **Antigravity** is building the UI on its own branch. Please use these endpoints, avoid touching existing `coach_app/main.py` or implementing competing backend coaching routes, and send back any needed fields for a versioned contract update.
- **Gemini** is preparing adversarial tests; their synthetic labels are not real player judgments. Run the tests against both local and opted-in AI modes only when appropriate.
- **Main remains unchanged.** These are stacked draft PRs; verify the exact final SHA in CI before merging.

## Known missing pieces / explicit boundaries

- Automatic choice of coherent episode decision timestamps (still manual).
- Claude TacticalOptionsV0 wiring, physically validated alternatives and calibrated uncertainty.
- Semantic claim entailment or human-expert grading of model language.
- Multi-turn LLM follow-up; `/api/coach/followup` is evidence-navigation only.
- Server-enforced freeze and separate retrospective reveal. Only Stage 1 is exposed by Round 9 endpoints.
- Native Rocket League control and game/window capture (Antigravity PR #28 separate; live unverified).
- Real GC2/SSL coaching merit benchmark, repeatability and user-tested insight.

This is an **operational backend slice**, not a claim that the first elite tactical AI coach is complete.

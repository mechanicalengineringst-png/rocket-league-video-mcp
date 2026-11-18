# Round 10 — Stage-1 Source-backed Episode Discovery V0

**Status:** experimental selection/attention signals; not a tactical or mistake detector.

## Architectural alternatives considered

1. **Select review moments exclusively from native decoder event labels.** Lightweight, but derived labels such as fifty-fifty results and role transitions may be finalized using future frames; event categories also miss quiet, strategically meaningful recoveries.
2. **Ask an LLM to scan an entire match and identify important moments.** Flexible but costly, difficult to audit, context-heavy and exposed to outcome hindsight or ungrounded decisions. Not appropriate until evidence selection is trustworthy.
3. **Audit recorded state transitions (selected).** Compare two actual replay samples, score observables such as speed/heading/boost/spacing, and verify each referenced field against `EpisodeEvidenceV0`. Works without a key or training data and does not depend on post-decision outcomes. Important limitation: salience does **not** establish decision significance, tactical quality or causal explanation.
4. **Learn a validated specialist salience classifier from expert annotations.** Best longer-term candidate, but the current project has no representative expert-labeled dataset or reliable high-rank benchmark.

**Choice:** option 3 for V0. This is an auditable baseline to gather review examples and identify what calibrated discovery should replace or supplement.

## API

`POST /api/coach/candidates`

~~~json
{
  "replay": {"players": [], "frames": [], "events": []},
  "player_id": "b1",
  "max_candidates": 8,
  "horizon_s": 80.0
}
~~~

`replay` must be an actual decoded four-player 2v2 replay with 2 players on each team and up to 30,000 frames. `horizon_s` is optional and permits prefix-only tests/review. It must be finite and within the replay. Request body is limited to 24 MiB by the existing `_read_json_request` helper. Never transmit model credentials; no AI service is invoked.

Response (illustrative, not a purported real-match assessment):

~~~json
{
  "schema": "EpisodeCandidatesV0",
  "mode": "deterministic_source_observation",
  "stage": "predecision",
  "status": "ok",
  "discovery_horizon_s": 80,
  "candidate_count": 1,
  "signal_windows_scanned": 8,
  "policy": {
    "version": "episode-discovery/0.1",
    "calibration": "uncalibrated_attention_heuristics",
    "selection_uses_future_events": false,
    "node_semantics": "recorded snapshots, not automatically identified discrete decisions"
  },
  "candidates": [{
    "candidate_id": "ec-...",
    "primary_t0": 53.226,
    "comparison_sample_s": 52.096,
    "episode_start_s": 45.226,
    "decision_times": [52.096, 53.226],
    "node_meaning": {
      "N1": "observed comparison snapshot; not an identified player decision",
      "N2": "observed change endpoint; not proof of a tactical mistake"
    },
    "primary_signal": "heading_change",
    "salience_score": 4.6,
    "signals": [{
      "signal": "heading_change",
      "salience": 4.6,
      "observed_delta": 117,
      "unit": "degrees",
      "evidence_refs": ["N1/E.focus.forward", "N2/E.focus.forward"],
      "interpretation": "Observed car nose-direction change; camera, intention and controller inputs are unknown.",
      "tactical_quality_verified": false
    }],
    "status": "attention_candidate_not_coaching_verdict",
    "retrospective_consulted": false,
    "expert_validated": false,
    "source_ref_count": 2,
    "stage1_episode_status": "ok"
  }]
}
~~~

The candidates contain no replay title, raw account names, future goals, decoded action labels, confidence of tactical correctness, or claimed best move. All direct source IDs listed in `signals[].evidence_refs` have been independently checked against the actual Stage 1 episode snapshot builder before being returned.

## UI integration contract (for Antigravity)

1. On confirmed real replay/player selection, call `/api/coach/candidates` once for a source-backed shortlist. Display candidates as *review leads* (e.g., "Heading changed", "Boost decreased"), not *mistakes*.
2. On selection, pass `candidate.decision_times`, `candidate.episode_start_s`, and `candidate.primary_t0` unchanged to the existing `POST /api/coach/lesson` with `mode: "deterministic"`, plus the original decoded replay and player ID.
3. Resolve claims using `POST /api/coach/evidence` with the **same** selected times and the returned `N1/E...`, `N2/E...` IDs. Never fabricate source IDs.
4. `N1` is a **comparison observation**, not a known decision. `N2` marks the observed change endpoint, not a validated player choice. Backwards navigation must not imply that N1 caused anything.
5. Missing/abstained matches, sparse samples, invalid kinematics and low-salience matches may produce zero candidates. Offer manual timeline selection as an honest fallback; do not silently substitute fixture examples or arbitrary timestamps.
6. The API does not invoke a model and never returns Stage 2. The sample/selector is uncalibrated and is NOT evidence the coach understands GC/SSL mechanics.

## Signals and limits

- Boost decrease between two sampled states (not necessarily waste)
- Nose-heading change (not player camera angle)
- Car velocity change (not inferred intentional dodge)
- Closing distance to ball (not proof of a challenge)
- Teammate spacing change (not teammate fault)
- Ball velocity change nearby (not proof of who touched it)

Comparison samples are ~0.9-1.8 seconds apart, with 5-20 seconds of valid Stage 1 episode context. Candidate selection uses a deterministic salience score and 5-second temporal nonmaximum suppression, sorted chronologically for presentation.

Scores are a UI shortlist heuristic. They do not represent probabilities, evaluation grades or calibration.

## Temporal safeguards and remaining weaknesses

- The selector reads frames but no native match events, future score changes, goal results, 50/50 outcomes or other retrospective labels.
- Every selected candidate's cited `N1/E` and `N2/E` references must resolve in a real sanitized `EpisodeEvidenceV0` constructed from the selected timestamps.
- Changing replay data **after an explicit discovery horizon** cannot change that horizon's candidate output. When discovering an entire match without a horizon, later events can introduce additional candidates and change which ones survive the finite shortlist; this is ranking, not retroactive reasoning.
- Source extraction inherits the decoder's known 30 Hz sample-and-hold and provenance uncertainties. State changes need not correspond to a discrete deliberate action; sustained continuous actions may be missed.
- This V0 returns two-node episodes rather than constructing multi-step causal chains. Expanding to more nodes requires actual new evidence anchors, not evenly spaced fabricated points.
- Weak changes will be omitted; quiet good decisions and positional discipline remain underrepresented. This must not become the sole way players access coaching.
- No paid provider calls, native Rocket League modifications, or expert-calibrated coaching accuracy claims.

## Acceptance / testing

Tests in `coach-app/tests/test_episode_discovery.py` check temporal invariance, neutral outputs, deterministic ranking, verified source IDs, abstention, invalid payload rejection, and the handoff to `/api/coach/lesson`. Run full repository CI before presenting this as integrated.

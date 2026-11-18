# Replay Lab Round 7 — Evidence / Reasoner Integration Gate (Claude + Gemini)
**Status:** Reviewed architecture and implementable next-step contract. Not code, benchmark results, production approval, or final multi-agent meeting. **Antigravity report pending.** 17 November 2026 Central / 18 November UTC.

Read [Project Compass](replay-lab-project-compass.md) first. This summary is the durable integration decision, **not a transcript**. The complete Gemini report was supplied by the owner as an 885-line Markdown attachment in ChatGPT, not independently verified against the GitHub repository.

## Grounded project state

- **Claude:** [PR #22](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/22), `5dc35d1`, adds `coach_app/decision_evidence.py` and [exact contract](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/blob/claude/round5-tactical-intelligence-20261117/coach-app/docs/round5/05_DECISION_EVIDENCE_V0.md). `build_decision_evidence(payload, t0, focus_id, *, context_s=3.0, selection=None)` yields `DecisionEvidenceV0`, containing `evidence` (E./C. refs), `unknowns` (U. refs), `context`, `not_observable`, and a **separate** `retrospective` (R. refs). It does not score merit. Claude reports 204 tests passed, 4 skipped, plus 636/636 stable pre-t0 records under future truncation across 15 real unknown-rank replays. **Not high-rank coaching validation**.
- **ChatGPT:** [draft PR #26](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/26) prevents the legacy optional `/api/ai-review` from sending whole-match samples while claiming to review a selected time. It is separate from PR #22 and should not substitute for its new evidence contract.
- **Gemini:** Supplied a **design specification**, not executable code, for episode-level coaching, a two-stage reasoner, typed claims, and blind human reviews. Exact schema depends on unavailable or unverified data/simulations. No project training, cloud calls, or expert ratings resulted from that document.
- **Antigravity:** Native Stats API companion remains a separate proof task under [PR #20](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/20); live Windows game test not confirmed. No native feature is required for offline episode evidence.

## Adopt for Proof of Coach V0

**A. Two-stage temporal firewall in the application.**
Build an explicit **whitelist serializer** for Stage 1. It may expose only audited t<=t_i `DecisionEvidenceV0` observations, context, explicit unknowns, non-observable limits, and model-independent provenance. **Never expose** `retrospective`, `R.*`, goal/next-touch outcomes, model-generated interpretations based on future data, or selection-reason metadata derived from future outcomes. Do not pass Claude's entire raw `decision_snapshot` object unchanged: it has `retrospective`. Unit test the exact serialized model input against future-data tampering.

**B. First-stage question is action-option merit, not knowledge of later action.**
Gemini's proposed `actual_chosen_action_class` is derived from post-t0 evidence and contradicts the Stage 1 cutoff. Before Stage 2, assess the available decisions (challenge, delay, fake, rotation), their apparent feasibility, tradeoffs, and uncertainty. Once Stage 1 is locked, Stage 2 can compare its option assessments against Claude's retrospective `observed_action` and actual events. Never silently revise the Stage 1 judgment based on the score or eventual touch.

**C. Small episode wrapper, not premature causal-DAG simulation.**
For one **real 2v2 match**, select a useful 5–20-second window manually or using existing candidate logic. Produce 2–3 chronologically ordered `DecisionEvidenceV0` nodes at their own t_i and a short prior-state change summary (boost, spacing, opponent pressure where supported). Each node has its own information cutoff. A "possible earlier root cause" is initially a **hypothesis**, not a proven directed causal edge or precise numerical EV drop. Use nullable fields for unavailable possession, perception, teammate recovery and branch outcomes.

**D. Honest choices and model presentation.**
Use existing reachability **bounds**, boost, positions and cover, with 2–4 plausible conditional alternatives; explain tradeoffs without invented 50/50 probabilities, calibrated human execution percentages, ball destinations, or minimax EV. Use one concise actionable lesson if evidence is sufficient, otherwise abstain. Show evidence timestamps, alternative interpretations and unknowns. Compare deterministic baseline (A) vs a fixed-evidence Gemini reasoner (B) before more tool infrastructure. Cloud calls/data export require owner opt-in and actual model/API availability check.

**E. Claims and verification.**
Every numerical/spatial fact and feasibility estimate references existing E./C. item(s); unknowns are U. caveats; outcomes R. are confined to Stage 2. Deterministically validate identifier existence, temporal scope, units, values, modality and provenance before presenting the answer. Semantic entailment checking is a later experimental layer; an LLM's claim that "all verifier gates passed" is not proof. Do not accept a model-authored numeric predicate as verified merely because it has a plausible citation.

## Do NOT implement as assumed facts

1. **No RocketSim best-response / 120Hz full-arena rollout gate yet:** existing Round 5 work reports missing local arena collision meshes and unknown player inputs. Simulated optimal policies are assumptions, not real human opponent predictions.
2. **No precise camera-frustum, swivel, awareness or sound-audibility classification:** current `DecisionEvidenceV0` says player camera, input and comms are unobservable. Gemini's `NATIVE_EXACT`, `stale_ticks`, `REPLICAR_FITTED_NONCAUSAL` and `PlayerPerceptionEnvelopeV0` fields require separate provenance research and decoder work; never populate them with guesses.
3. **No `decision_regret_delta_ev`, `minimax_worst_case_ev_3s`, `mechanical_feasibility_prob`, or "rank-calibrated" EV** until trained/validated models and causal evaluation support them. Unknown is valid.
4. **No automatic HEF-2v2 training yet:** failed attempts and *intended* intercepts are not directly labeled in ordinary replay trajectories. Self-supervision cannot infer unchosen attempts without selection bias. Hardware, training speed, cost, AI model names and latency figures in Gemini's document are unverified estimates.
5. **No circular benchmark:** Gemini's proposed strata often use EV values, counterfactual labels or retrospective outcomes that our current system cannot compute. Design feasible objective selectors and blind high-rank human annotations; don't let system-generated judgments choose their own cases. Twenty examples are a pilot, not enough to guarantee an 8% false-criticism rate with tight confidence.
6. **No native command guessing:** Gemini describes some UDP/WebSocket control payloads, but use only the official Stats API command transport and verified code in PR #20. A successful local port probe is not verified replay control.

## Small next engineering test (does not require Antigravity)

**Unit under test:** `build_stage1_evidence_packet(record) -> dict` (provisional API), then `build_episode_packet(nodes, primary_t0) -> dict`.

Minimum acceptance tests:
- Rewrite/delete *all* frames/events after every decision t_i: Stage 1 packet bit-identical.
- Force a retrospective `observed_action`, next touch and goal to vary: Stage 1 packet unchanged, and there is no `R.` reference or `retrospective` key.
- Missing/NaN/stale boost or car state leads to explicit uncertainty or abstention, never to zero/synthetic exactness.
- A factual claim with a correct existing ID but an inverted or invented number is **rejected**.
- A hypothetical action remains hypothetical, with no fabricated EV/percentage.
- Stage 2 outcome access only after Stage 1 is frozen; outcome changes cannot change its stored verdict.
- No platform account IDs or original player names inside optional cloud prompt; use the exact E./C./U. IDs from Claude's contract.

**First demonstration:** one real preselected 2v2 tactical episode, 2 defensible options (include aggressive pressure, not just passive shadowing), source-cited explanation, visible uncertainty, optional post-decision result separately, a skeptical follow-up, and synchronized existing replay viewer. Human owner judges usefulness; expert blind benchmark comes afterward.

## Branch boundaries and next meeting

Keep this as docs on [PR #25](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/25). PR #22 is stacked on #21/#18, while PR #26 is stacked on #24/#23: **do not blindly merge either chain to main**. After Antigravity submits the native proof report, resolve branch integration order and green-test the exact combined tree before any app-wide rollout.

**Decision:** adopt Gemini's temporal split and structured claims; retain Claude's factual interface; postpone numeric counterfactual simulation, detailed perception and small-model training until supported by actual evidence and independent expert judgment.

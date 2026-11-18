# Round 8 — EpisodeEvidenceV0 to audited Stage1EpisodePacketV0

**Draft PR #30.** No actual tactical verdicts, paid LLM calls, live-game tests, private replay uploads, or changes to main.

## Combined implementation and ancestry

- Claude PR #22 / commit `1897569`: `episode_evidence.py`, `decision_evidence.py`, 625 real replay episodes checked for future invariance; these cases were sampled at fixed offsets and **were not manually ranked tactical episodes**.
- ChatGPT PR #27 / Stage 1 `stage1_packet.py`: whitelists one DecisionEvidenceV0 node's factual E./C., U. unknowns and constraints; omits `source`, `selection`, `retrospective`, identity metadata.
- ChatGPT PR #29 / `claim_verifier.py`: typed source-value assertions, citation scope and epistemic classes; no free-text semantic approval.
- This branch merges the above histories without overwriting the original PR heads and adds `episode_stage1.py` with regression tests.

## Why `stage1_view()` is not sufficient for model calls

Claude's `episode_evidence.stage1_view(episode)` faithfully removes the top-level `retrospective`, but retains `label`, node `selection` and `source` metadata, episode IDs, free-form change notes, and hypothesis questions. Those fields are useful in the internal/debug display but could reveal coordinator-selected outcomes, local file provenance, personal IDs or editorial judgments if future callers populate them.

**External AI prompt boundary:** use only `build_stage1_episode_packet(episode)`. It independently passes *each* node's DecisionEvidenceV0 snapshot through `build_stage1_packet`. Then it reconstructs the chronological relations, includes only whitelist typed source-backed D. changes (stamped at the **later** decision), anonymized timeline events, U./UD. unknown references and **unverified** hypothesis references. It omits `retrospective`, raw `selection`, `source`, `label`, actual outcome, arbitrary questions/notes and user identities.

## Usage

~~~python
from coach_app.episode_evidence import build_episode_evidence
from coach_app.episode_stage1 import build_stage1_episode_packet
from coach_app.claim_verifier import verify_stage1_claims

episode = build_episode_evidence(replay, focus_id, [t1, t2, t3], start_s, t3)
predecision_packet = build_stage1_episode_packet(episode)
node = predecision_packet["nodes"][1]          # N2 at t2
report = verify_stage1_claims(node["packet"], typed_claims_for_t2)
~~~

At the **episode level**, the globally unique reference is `N<k>/<local E./C./U. id>`. The underlying single-decision verifier expects local IDs, so choose the node first and do not accidentally cross-reference N1 values at N3. D. changes cite facts from the compared two nodes and are marked `derived_value_needs_independent_math_check`: the adapter validates time and references but **does not yet independently recompute the mathematical delta**. H. references are prompts **not causal conclusions**. U. and UD. are caveats, not support for claims.

Stage 2 outcome revelation must happen only **after** Stage 1 judgments are frozen and separately stored. No Stage 2 reasoner or server-side freeze protocol is implemented here.

## Tests and limitations

`tests/test_episode_stage1.py` has synthetic cases for future rewrite/removal invariance; metadata redaction; per-node claim verifier integration; corrupted timestamps/citations; unknown-versus-zero boost and missing frames; changed later node with stable earlier node; and no false assertion that math or tactical meaning was verified.

**Not built:** fixed-evidence LLM orchestration, human-reviewed usefulness, independently checked D. change math, PR #16's strict blind-review evidence adapter, video/media cutoff enforcement, exact camera/controller availability, trained calibrated models or native Windows game confirmation.

**Next gate:** once CI passes for exact final SHA, create an explicit source timestamp/provenance adapter into PR #16's `evaluation.prepare` format, without fabricating its required `finalized_through_s` metadata. This may require a conservative fail-closed policy for derived facts. Curate pilot cases only afterward.

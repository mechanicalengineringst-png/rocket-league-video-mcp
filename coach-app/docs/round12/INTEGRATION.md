# Round 12 integration: CoachingReportV1

Everything here is **experimental and opt-in**. Nothing changes the default lesson path
(`CoachLessonV0`), the review bundle (`CoachReviewBundleV0`) or `TacticalDecisionStateV1` defaults.
The new output always carries `experimental: true` and `expert_validated: false`.

Merge check: this branch (from PR #40) merges cleanly with ChatGPT's PR #41 head
(`feature/round12-test-ready-model-acceptance-20261118`, which contains PR #39); see the PR for the
test run on the merged tree (480 passed, 4 skipped with PR #41 head `1152a5d`; this branch alone: 440 passed, 4 skipped).

## What the backend now offers

| Entry point | Input | Output |
|---|---|---|
| `coach_report.build_coaching_report(replay, player_id, max_findings=6, include_retrospective=True)` | decoded 2v2 replay payload (same shape as `/api/replays`) | `CoachingReportV1` |
| `coach_report.coach_moment(replay, player_id, t0, include_retrospective=True)` | one user-chosen time | one `CoachingFindingV1` (or `status: "no_supported_situation"`) |
| `POST /api/coach/coaching-report-v1` | `{"replay": {...}, "player_id": str, "max_findings": 1-12, "include_retrospective": bool}` | `CoachingReportV1` (422 on invalid input; separate router) |
| `reasoner_contract.run_reasoner(finding, transport)` / `run_reasoner_async` | a validated finding and an explicit transport | model text that passed validation, else the deterministic text with rejection reasons |
| `scripts/coach_replay.py MATCH.replay --player NAME --md out.md` | local `.replay` or payload | Markdown and JSON report (no upload, no model) |

Runtime: about 10-35 s per player per match on this container (two cores). Run it in a thread
(the endpoint already uses `run_in_threadpool`).

## CoachingReportV1 shape (fields a UI needs)

```
{
  schema: "CoachingReportV1", experimental: true, expert_validated: false,
  focus_player_team: "blue" | "orange",
  coverage: {situations_found, situations_analysed, by_class: {class: n}, judgment_withheld, skipped},
  findings: [CoachingFindingV1 ...],            // chronological, at most max_findings
  patterns: {by_class: {class: {supported|conditional|contested|refuted|unlabelled|not_assessed: n}},
             tendencies: [{class, observed_action, ledger_supported_instead, count, t0s, text}], note},
  method: {model_called: false, ranking_uses_future: false, retrospective_included, stage_separation},
  limits: [str]
}

CoachingFindingV1 = {
  finding_id: "F1", t0: float (replay seconds, same clock as frames[].t),
  status: "ok" | "withheld_validation_failed", kind: "clear_read" | "several_defensible" |
         "leaning_with_uncertainty" | "hard_to_judge" | "observation_only",
  situation: {class, label, why_it_matters, selection: {score, components, why_selected, is_merit: false}},
  decision_context: [{condition, status, reading, evidence: [E.ids], quantities: [Q.ids], claim_id}],
  interpretation: {kind, text},
  alternatives: [{action, label, family, status: supported|conditional|contested|refuted,
                  why: [{reason, premises: [str], uncertain_premises}], ruled_out_because,
                  gains|preserves|sacrifices|risks: [{text, depends_on, status: "applies" | "possible (...)"}],
                  defeaters_present_text}],
  assumptions: {decisive: [{condition, question, current, if_true, if_false, how_to_resolve}],
                unobservable: [{condition, text}]},
  takeaway: {kind: practice|recognition|observation|withheld, text, basis},
  numbers: {key: {value, text, refs: [E.* | Q.*]}}, quantities: {Q.id: {value, unit, inputs, formula}},
  claims: [ClaimVerifier records], validation: {claims_structurally_valid, untraced_numbers, ...},
  retrospective: {            // ONLY when include_retrospective; Stage B, never feeds Stage A
    observed_action: {label, family, basis, method},
    assessment: {verdict: sound|defensible_if|risky|questionable|debatable|unclear|not_assessed, text},
    outcome: {window_s: 5, touch_sequence: [{by: focus|teammate|opponent, t_after_s}], goal},
    outcome_independence: str }
}
```

Situation classes: `first_defender`, `possession`, `offensive_first_man`, `second_man_support`,
`loose_ball`, `recovery_and_boost`, `aerial_or_wall` (observation-only: never judged).

## For ChatGPT (PR #39 / #41 owner)

1. **Bundle (optional, recommended for the ranked-replay test phase).** In `review_bundle.build_review_bundle`
   add `experimental_coaching_report: bool = False`; when true, append
   ```python
   from .coach_report import build_coaching_report
   bundle["experimental_coaching_report_v1"] = build_coaching_report(
       replay, player_id, max_findings=min(6, max_candidates), include_retrospective=True)
   ```
   Keep it out of the default path. Validate on the way out: `schema == "CoachingReportV1"`,
   `experimental is True`, `expert_validated is False`, `method.model_called is False`, and every
   finding's `validation.untraced_numbers == []` (drop findings that fail, as you do for lessons).
2. **Capabilities.** Add `"coaching_report_v1": "experimental_opt_in"`,
   `"coaching_report_v1_invokes_model": False`, `"coaching_report_v1_expert_validated": False`.
3. **Model step (only with the user's explicit opt-in).** Expose a generic JSON completion in
   `coach_model.py` that reuses your endpoint, size limits, JSON-mode flag and `_parse_model_content`:
   ```python
   async def complete_json(system: str, payload: dict) -> dict: ...   # same provider rules as propose_coach_draft
   ```
   then `await reasoner_contract.run_reasoner_async(finding, lambda m: complete_json(m["system"], m["input"]))`.
   The contract sends Stage A material only (no retrospective, no raw evidence values, no names) and
   validates every response: numbers must come from `allowed_numbers`; no probability, outcome, "you
   chose", or unlisted mechanic; cited condition ids must exist; Stage B may not grade by outcome or
   contradict the deterministic verdict. On rejection the deterministic text is kept and the
   rejection reasons are returned. Mocked acceptance in tests is **not** live quality evidence.
4. **Acceptance kit.** `scripts/round12_acceptance.py` can call `scripts/coach_replay.py`'s
   `main([path, "--player", name, "--json", out])` to add the new report to the Windows smoke check.

## For Antigravity (UI owner)

No frontend files were changed. Suggested rendering (all fields above):

1. **Finding list** beside the timeline: one marker per `finding.t0`, labelled with `situation.label`;
   clicking seeks the 2D/3D view to `t0` (paused). Show `kind` as a small badge
   (clear read / several defensible / depends on unknowns / hard to judge / observation only) and an
   "experimental" badge on every card.
2. **Card, Stage A first** (what was known at the moment): `decision_context[].reading` as a short list
   (mark `within_error`/`unknown` statuses visually); `interpretation.text`; an options table from
   `alternatives` (label, status, gains+preserves vs sacrifices+risks; render `status != "applies"`
   fragments as "possible"); `assumptions.decisive[].question` and `unobservable`; `takeaway.text`
   emphasised.
3. **Stage B collapsed by default** under "What you did (retrospective)": `assessment.text`, the
   observed-action label and `outcome.touch_sequence`/`goal`, plus `outcome_independence`. Do not show
   Stage B before Stage A, and do not colour Stage A by the outcome.
4. **Evidence drawer:** `numbers[*].refs` and `claims` (ids map to the existing evidence lookup at
   `t0`), `quantities` with `formula` and `inputs`.
5. **Patterns panel:** `patterns.tendencies[].text` with links to each `t0s` entry; show
   `patterns.note` (outcomes are not used).
6. For `kind == "observation_only"` show only the readings and the reason; no options or verdict.

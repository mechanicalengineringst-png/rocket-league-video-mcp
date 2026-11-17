"""Score evidence-grounded Rocket League coaching on blinded, human-reviewed cases.

This intentionally does NOT score game-state predictions against the final
match outcome. It measures whether a decision assessment was defensible at t0,
with disagreements and missing expert labels reported rather than hidden.
Stdlib only: safe to run without the replay decoder, GPU, or model API keys.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

VERDICTS = frozenset({"sound", "risk", "tradeoff", "indeterminate"})
PREDICTIONS = frozenset({"sound", "risk", "tradeoff", "abstain"})
CASE_FIELDS = frozenset({
    "case_id", "t0", "situation_type", "pre_decision_evidence",
    "replay_group", "mode",
})
EVIDENCE_FIELDS = frozenset({
    "key", "claim", "event_time_s", "finalized_through_s",
    "source", "source_quality",
})
PLATFORM_IDENTIFIER = re.compile(
    r"\b(?:Steam|Epic|PSN|PsyNet|Xbox):[A-Za-z0-9_-]{7,}\b", re.I
)


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def _ratio(top: int, bottom: int) -> float | None:
    return round(top / bottom, 4) if bottom else None


def _valid_cases(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Validate causally bounded *exported* fields; cannot prove semantic truth."""
    cases: dict[str, dict[str, Any]] = {}
    for case in records:
        _need(isinstance(case, dict), "Each case must be an object")
        unexpected = set(case) - CASE_FIELDS
        _need(not unexpected, f"Case has non-blind fields: {sorted(unexpected)}")
        case_id = case.get("case_id")
        _need(isinstance(case_id, str) and case_id.strip(), "Missing case_id")
        _need(case_id not in cases, f"Duplicate case_id: {case_id}")
        t0 = case.get("t0")
        _need(_finite_number(t0) and t0 >= 0, f"{case_id}: invalid t0")
        _need(isinstance(case.get("situation_type"), str), f"{case_id}: missing situation_type")
        evidence = case.get("pre_decision_evidence")
        _need(isinstance(evidence, list) and evidence, f"{case_id}: expected pre_decision_evidence list")
        keys: set[str] = set()
        for item in evidence:
            _need(isinstance(item, dict), f"{case_id}: evidence must be an object")
            _need(not (set(item) - EVIDENCE_FIELDS), f"{case_id}: unsupported evidence fields")
            key = item.get("key")
            _need(isinstance(key, str) and key and key not in keys,
                  f"{case_id}: missing/duplicate evidence key")
            keys.add(key)
            _need(isinstance(item.get("claim"), str), f"{case_id}: evidence claim must be a string")
            event_time = item.get("event_time_s")
            finalized = item.get("finalized_through_s")
            _need(_finite_number(event_time) and 0 <= event_time <= t0,
                  f"{case_id}/{key}: event is after decision")
            _need(_finite_number(finalized) and event_time <= finalized <= t0,
                  f"{case_id}/{key}: post-decision-derived evidence")
        # Explicitly catch common platform IDs; anonymization of arbitrary
        # nicknames is still the producer's responsibility.
        _need(not PLATFORM_IDENTIFIER.search(json.dumps(case)),
              f"{case_id}: platform identifier must be anonymized")
        cases[case_id] = case
    return cases


def evaluate(
    cases: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    quality_reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare systems using a shared blinded case cohort and expert labels.

    Two independent reviewers agreeing are required for a consensus verdict.
    Disputed, missing and indeterminate cases never become fake ground truth.
    Quality reviews are optional human ratings of *system outputs*, distinct
    from expert labels about the underlying decision.
    """
    indexed = _valid_cases(cases)
    labels: dict[str, dict[str, str]] = defaultdict(dict)
    for row in reviews:
        case_id, rater, verdict = row.get("case_id"), row.get("rater_id"), row.get("verdict")
        _need(case_id in indexed, f"Review refers to unknown case: {case_id}")
        _need(isinstance(rater, str) and rater.strip(), "Reviewer requires rater_id")
        _need(verdict in VERDICTS, f"Invalid review verdict: {verdict}")
        _need(rater not in labels[case_id], f"Duplicate review for {case_id}/{rater}")
        labels[case_id][rater] = verdict

    consensus: dict[str, str] = {}
    disputed: list[str] = []
    insufficient: list[str] = []
    indeterminate: list[str] = []
    for case_id in indexed:
        raters = labels.get(case_id, {})
        if len(raters) < 2:
            insufficient.append(case_id)
        elif len(set(raters.values())) != 1:
            disputed.append(case_id)
        elif next(iter(raters.values())) == "indeterminate":
            indeterminate.append(case_id)
        else:
            consensus[case_id] = next(iter(raters.values()))

    by_system: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in predictions:
        case_id, system, assessment = row.get("case_id"), row.get("system_id"), row.get("assessment")
        _need(case_id in indexed, f"Prediction refers to unknown case: {case_id}")
        _need(isinstance(system, str) and system.strip(), "Prediction requires system_id")
        _need(assessment in PREDICTIONS, f"{system}/{case_id}: invalid assessment: {assessment}")
        _need(case_id not in by_system[system], f"Duplicate prediction: {system}/{case_id}")
        cited = row.get("cited_evidence")
        _need(isinstance(cited, list) and all(isinstance(k, str) for k in cited),
              f"{system}/{case_id}: cited_evidence must be a string list")
        by_system[system][case_id] = row

    human_quality: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in quality_reviews or []:
        case_id, system, rater = row.get("case_id"), row.get("system_id"), row.get("rater_id")
        _need(case_id in indexed and case_id in by_system.get(system, {}),
              "Quality review must reference an existing prediction")
        _need(isinstance(rater, str) and rater.strip(), "Quality review requires rater_id")
        _need(rater not in human_quality[(system, case_id)],
              f"Duplicate quality review: {system}/{case_id}/{rater}")
        for field in ("factual_errors", "unsupported_claims"):
            value = row.get(field)
            _need(isinstance(value, int) and not isinstance(value, bool) and value >= 0,
                  f"Quality review {field} must be a nonnegative integer")
        _need(isinstance(row.get("useful"), bool), "Quality review useful must be boolean")
        human_quality[(system, case_id)][rater] = row

    systems = {}
    for system, outputs in sorted(by_system.items()):
        abstentions = 0
        citation_failures = 0
        citation_failure_examples = []
        comparable = []
        for case_id, output in outputs.items():
            if output["assessment"] == "abstain":
                abstentions += 1
            known = {e["key"] for e in indexed[case_id]["pre_decision_evidence"]}
            cited = output["cited_evidence"]
            if output["assessment"] != "abstain" and (
                not cited or len(cited) != len(set(cited)) or any(k not in known for k in cited)
            ):
                citation_failures += 1
                citation_failure_examples.append(case_id)
            if case_id in consensus and output["assessment"] != "abstain":
                comparable.append((output["assessment"], consensus[case_id]))

        risk_attempts = [(p, g) for p, g in comparable if p == "risk"]
        supported_risk = sum(g == "risk" for _, g in risk_attempts)
        refuted_risk = sum(g == "sound" for _, g in risk_attempts)
        agreement = sum(p == g for p, g in comparable)
        qrows = [
            row for (sid, cid), raters in human_quality.items()
            if sid == system for row in raters.values()
        ]
        systems[system] = {
            "predictions": len(outputs),
            "missing_case_predictions": len(indexed) - len(outputs),
            "abstentions": abstentions,
            "abstention_rate": _ratio(abstentions, len(outputs)),
            "invalid_evidence_citation_outputs": citation_failures,
            "invalid_evidence_citation_case_ids": citation_failure_examples,
            "consensus_comparable_cases": len(comparable),
            "consensus_agreement": _ratio(agreement, len(comparable)),
            "risk_warnings_on_consensus_cases": len(risk_attempts),
            "risk_warning_precision": _ratio(supported_risk, len(risk_attempts)),
            "risk_warnings_refuted_by_sound_consensus": refuted_risk,
            "quality_ratings": len(qrows),
            "human_reported_factual_errors": sum(r["factual_errors"] for r in qrows),
            "human_reported_unsupported_claims": sum(r["unsupported_claims"] for r in qrows),
            "human_usefulness_fraction": _ratio(sum(r["useful"] for r in qrows), len(qrows)),
        }
    return {
        "schema": "replay-lab-blind-benchmark-v1",
        "cases": len(indexed),
        "consensus_cases": len(consensus),
        "disputed_case_ids": disputed,
        "insufficient_review_case_ids": insufficient,
        "indeterminate_consensus_case_ids": indeterminate,
        "systems": systems,
        "interpretation": (
            "Agreement with two reviewers is not tactical optimality. "
            "Citations validate referenced keys, not the semantic truth of model claims. "
            "Review the disputed cases, mechanical feasibility, and causal provenance."
        ),
    }


def _read_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    value = json.loads(text)
    if isinstance(value, dict) and "cases" in value:
        value = value["cases"]
    _need(isinstance(value, list), f"{path}: expected JSON list/JSONL")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Score blind, human-reviewed Replay Lab coaching results")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--quality-reviews", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    scored = evaluate(
        _read_records(args.cases), _read_records(args.predictions),
        _read_records(args.reviews),
        _read_records(args.quality_reviews) if args.quality_reviews else None,
    )
    result = json.dumps(scored, indent=2)
    if args.output:
        args.output.write_text(result + "\n", encoding="utf-8")
    else:
        print(result)


if __name__ == "__main__":
    main()

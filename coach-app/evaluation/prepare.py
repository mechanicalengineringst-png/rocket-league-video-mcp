"""Create and resolve blinded human-review packets for Replay Lab.

This module does not read replay files or contact any AI service. Only
pre-decision case fields are allowed into decision packets; model names and
real case identifiers live in an OFFLINE mapping held by the coordinator.
Blinding is for review methodology, not cryptographic anonymization.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path
from typing import Any

from .score import PREDICTIONS, VERDICTS, _need, _read_records, _valid_cases


def build_packets(
    cases: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    seed: int = 20261117,
) -> dict[str, Any]:
    """Generate reviewer-safe packets and a separate private identity map.

    Reviewer packets contain no system_id, original case_id, replay_group,
    post-decision event, full source replay or proprietary telemetry.
    A reviewer may still recognize a game from its *content*: use anonymized
    evidence and avoid exposing model outputs before decision review.
    """
    indexed = _valid_cases(cases)
    rng = random.Random(seed)
    randomized_ids = list(indexed)
    rng.shuffle(randomized_ids)
    decision_ids = {f"C{i:05d}": case_id for i, case_id in enumerate(randomized_ids, 1)}
    public_id_by_case = {case_id: blinded for blinded, case_id in decision_ids.items()}

    decision_packets = []
    for blind_id, case_id in decision_ids.items():
        case = indexed[case_id]
        decision_packets.append({
            "review_id": blind_id,
            "situation_type": case["situation_type"],
            "t0": case["t0"],
            "pre_decision_evidence": case["pre_decision_evidence"],
            "review_question": (
                "Based only on information available before this time, "
                "was the decision sound, a tactical risk, a legitimate "
                "tradeoff, or indeterminate? Do not view the eventual outcome."
            ),
        })

    seen: set[tuple[str, str]] = set()
    candidates: list[dict[str, Any]] = []
    for row in predictions:
        _need(isinstance(row, dict), "Predictions must be objects")
        case_id, system_id = row.get("case_id"), row.get("system_id")
        _need(case_id in indexed, f"Prediction refers to unknown case: {case_id}")
        _need(isinstance(system_id, str) and system_id.strip(), "Missing system_id")
        _need((case_id, system_id) not in seen, f"Duplicate prediction: {system_id}/{case_id}")
        seen.add((case_id, system_id))
        _need(row.get("assessment") in PREDICTIONS,
              f"Invalid assessment on {system_id}/{case_id}")
        citations = row.get("cited_evidence")
        _need(isinstance(citations, list) and all(isinstance(c, str) for c in citations),
              f"{system_id}/{case_id}: citations must be an array of strings")
        # Only declared, useful reviewer-facing fields are retained. Arbitrary
        # model output metadata (including any retrospective rationale) cannot
        # be carried into the packet accidentally.
        title = row.get("title", "")
        advice = row.get("advice", "")
        _need(isinstance(title, str) and isinstance(advice, str),
              "Title and advice must be strings")
        output_text = title + "\n" + advice
        # A reviewer cannot be blind if the model signs its response.
        # Fail closed for common provider names and the exact experiment ID.
        # This is a guardrail, not exhaustive language-based de-identification.
        common_names = re.compile(
            r"\b(?:Claude|Gemini|ChatGPT|GPT[-_ ]?\d+(?:\.\d+)?|"
            r"Qwen|DeepSeek|Ollama|Llama)\b", re.IGNORECASE,
        )
        direct_id = re.compile(
            r"(?<![\w-])" + re.escape(system_id) + r"(?![\w-])",
            re.IGNORECASE,
        ) if len(system_id) >= 5 else None
        _need(not common_names.search(output_text)
              and not (direct_id and direct_id.search(output_text)),
              f"{case_id}/{system_id}: output self-identifies the model; anonymize it")
        candidates.append({
            "case_id": case_id,
            "system_id": system_id,
            "case_ref": public_id_by_case[case_id],
            "assessment": row["assessment"],
            "cited_evidence": citations,
            "title": title,
            "advice": advice,
        })
    rng.shuffle(candidates)

    quality_packets: list[dict[str, Any]] = []
    quality_ids: dict[str, dict[str, str]] = {}
    for i, row in enumerate(candidates, 1):
        review_id = f"Q{i:05d}"
        quality_ids[review_id] = {
            "case_id": row["case_id"],
            "system_id": row["system_id"],
        }
        quality_packets.append({
            "review_id": review_id,
            "case_ref": row["case_ref"],
            "assessment": row["assessment"],
            "cited_evidence": row["cited_evidence"],
            "title": row["title"],
            "advice": row["advice"],
            "review_question": (
                "Does this anonymous coaching output make accurate, justified "
                "claims and offer something useful? Rate factual_errors and "
                "unsupported_claims separately. The system identity is hidden."
            ),
        })

    return {
        "decision_packets": decision_packets,
        "quality_packets": quality_packets,
        "private_map": {
            "schema": "replay-lab-blind-packets-v1",
            "seed": seed,
            "decision_ids": decision_ids,
            "quality_ids": quality_ids,
        },
    }


def resolve_submissions(
    submissions: list[dict[str, Any]],
    private_map: dict[str, Any],
    kind: str,
) -> list[dict[str, Any]]:
    """Restore original IDs for scoring AFTER reviewer judgments are frozen."""
    _need(private_map.get("schema") == "replay-lab-blind-packets-v1",
          "Unexpected private mapping schema")
    _need(kind in {"decision", "quality"}, "kind must be decision or quality")
    mapping = private_map["decision_ids" if kind == "decision" else "quality_ids"]
    _need(isinstance(mapping, dict), "Malformed blind review mapping")
    resolved: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for review in submissions:
        _need(isinstance(review, dict), "Review must be an object")
        review_id = review.get("review_id")
        rater = review.get("rater_id")
        _need(isinstance(review_id, str) and review_id in mapping,
              f"Unknown blind review ID: {review_id}")
        _need(isinstance(rater, str) and rater.strip(), "Missing reviewer ID")
        _need((review_id, rater) not in seen,
              f"Duplicate review: {review_id}/{rater}")
        seen.add((review_id, rater))
        mapped = mapping[review_id]
        if kind == "decision":
            verdict = review.get("verdict")
            _need(verdict in VERDICTS, f"Invalid verdict on {review_id}")
            resolved.append({
                "case_id": mapped, "rater_id": rater, "verdict": verdict,
            })
        else:
            fields = {}
            for metric in ("factual_errors", "unsupported_claims"):
                value = review.get(metric)
                _need(isinstance(value, int) and not isinstance(value, bool) and value >= 0,
                      f"{review_id}: {metric} must be a nonnegative integer")
                fields[metric] = value
            _need(isinstance(review.get("useful"), bool),
                  f"{review_id}: useful must be true or false")
            resolved.append({
                "case_id": mapped["case_id"], "system_id": mapped["system_id"],
                "rater_id": rater, **fields, "useful": review["useful"],
            })
    return resolved


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare blinded review packets and resolve frozen judgments"
    )
    subs = parser.add_subparsers(dest="action", required=True)
    make = subs.add_parser("make", help="generate reviewer packets and private mapping")
    make.add_argument("--cases", type=Path, required=True)
    make.add_argument("--predictions", type=Path, required=True)
    make.add_argument("--output-dir", type=Path, required=True)
    make.add_argument("--seed", type=int, default=20261117)
    resolve = subs.add_parser("resolve", help="map blind review IDs to scoring IDs")
    resolve.add_argument("--kind", choices=["decision", "quality"], required=True)
    resolve.add_argument("--submissions", type=Path, required=True)
    resolve.add_argument("--mapping", type=Path, required=True)
    resolve.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.action == "make":
        packets = build_packets(_read_records(args.cases),
                                _read_records(args.predictions), args.seed)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _write(args.output_dir / "decision_packets.json", packets["decision_packets"])
        _write(args.output_dir / "quality_packets.json", packets["quality_packets"])
        _write(args.output_dir / "PRIVATE_DO_NOT_COMMIT_mapping.json",
               packets["private_map"])
    else:
        raw_map = json.loads(args.mapping.read_text(encoding="utf-8"))
        _write(args.output, resolve_submissions(_read_records(args.submissions),
                                                raw_map, args.kind))


if __name__ == "__main__":
    main()

"""Paired, match-clustered comparison of two evidence-grounded coaching systems.

Keep expert disagreements out of the ground-truth denominator. Compare both
systems on exactly the same independently rated cases; missing, abstained and
unsupported outputs count as zero grounded successes rather than silently
disappearing from a selective-accuracy numerator.

Match-cluster bootstrap is exploratory, not a test of tactical optimality.
This file has no dependency on an LLM, GPU, Rocket League, or replay parser.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from .score import _need, _read_records, _valid_cases, evaluate

SCHEMA = "replay-lab-paired-match-evaluation-v1"
METRIC_DIRECTION = {
    "grounded_correct": "positive_favors_first_system",
    "grounded_coverage": "positive_favors_first_system",
    "false_blame_on_sound": "negative_favors_first_system",
    "unsupported_attempt": "negative_favors_first_system",
}


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _quantile(sorted_values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile; only used with nonempty bootstrap draws."""
    pos = (len(sorted_values) - 1) * fraction
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def _consensus_labels(reviews: list[dict[str, Any]],
                      eligible_cases: set[str]) -> dict[str, str]:
    """Match score.evaluate consensus semantics after it validates reviews."""
    labels: dict[str, dict[str, str]] = defaultdict(dict)
    for row in reviews:
        labels[row["case_id"]][row["rater_id"]] = row["verdict"]
    return {
        cid: next(iter(raters.values()))
        for cid, raters in labels.items()
        if cid in eligible_cases and len(raters) >= 2
        and len(set(raters.values())) == 1
        and next(iter(raters.values())) != "indeterminate"
    }


def _quality(pred: dict[str, Any] | None, reference: str,
             evidence_ids: set[str]) -> dict[str, int]:
    """Four distinct binary observations, with no invented quality weight."""
    if pred is None or pred["assessment"] == "abstain":
        return {
            "grounded_correct": 0,
            "grounded_coverage": 0,
            "false_blame_on_sound": 0,
            "unsupported_attempt": 0,
        }
    citations = pred["cited_evidence"]
    grounded = bool(citations) and len(citations) == len(set(citations)) and all(
        citation in evidence_ids for citation in citations
    )
    return {
        "grounded_correct": int(grounded and pred["assessment"] == reference),
        "grounded_coverage": int(grounded),
        # An accusation of risk against an expert-sound play is counted as a
        # false blame even if the model supplied no legitimate citation.
        "false_blame_on_sound": int(
            reference == "sound" and pred["assessment"] == "risk"
        ),
        "unsupported_attempt": int(not grounded),
    }


def paired_compare(
    cases: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    system_a: str,
    system_b: str,
    *,
    seed: int = 20261117,
    bootstrap_samples: int = 2000,
) -> dict[str, Any]:
    """Compare paired model decisions with whole-match resampling.

    Macro-average over match groups so a match providing 50 moments does not
    dominate another match with 5 moments. Also provide case-weighted rates as
    context. Bootstrap whole matches, never individual frames in one match.

    No model is declared a winner: labels are sparse, experts can disagree,
    reviewed moments may be detector-selected, and replays are not a random
    population sample. The intervals are diagnostic exploration only.
    """
    _need(isinstance(system_a, str) and bool(system_a.strip())
          and isinstance(system_b, str) and bool(system_b.strip())
          and system_a != system_b, "Provide two distinct nonempty system IDs")
    _need(type(seed) is int, "Seed must be an integer")
    _need(type(bootstrap_samples) is int and 200 <= bootstrap_samples <= 10000,
          "bootstrap_samples must be an integer between 200 and 10000")

    indexed = _valid_cases(cases)
    # Reuse the existing benchmark contract to validate every input and
    # duplicate system prediction before computing any new statistics.
    baseline_report = evaluate(cases, predictions, reviews)
    available = baseline_report["systems"]
    _need(system_a in available and system_b in available,
          "Both systems must have predictions; missing systems cannot be silently scored")
    consensus = _consensus_labels(reviews, set(indexed))
    _need(bool(consensus),
          "No two-reviewer non-indeterminate consensus; paired metrics unavailable")
    groups: dict[str, list[str]] = defaultdict(list)
    for cid in indexed:
        if cid not in consensus:
            continue
        group = indexed[cid].get("replay_group")
        _need(isinstance(group, str) and bool(group.strip()),
              f"{cid}: a nonempty replay_group is required for match-cluster inference")
        groups[group].append(cid)

    outputs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in predictions:
        outputs[row["system_id"]][row["case_id"]] = row
    quality = {
        system: {
            cid: _quality(
                outputs[system].get(cid), reference,
                {e["key"] for e in indexed[cid]["pre_decision_evidence"]},
            )
            for cid, reference in consensus.items()
        }
        for system in (system_a, system_b)
    }
    rng = random.Random(seed)
    metrics: dict[str, dict[str, Any]] = {}
    for metric, direction in METRIC_DIRECTION.items():
        eligible = [
            cid for cid in consensus
            if metric != "false_blame_on_sound" or consensus[cid] == "sound"
        ]
        eligible_set = set(eligible)
        per_match = []
        total_a = total_b = 0
        for group, cids in sorted(groups.items()):
            selected = [cid for cid in cids if cid in eligible_set]
            if not selected:
                continue
            a_count = sum(quality[system_a][cid][metric] for cid in selected)
            b_count = sum(quality[system_b][cid][metric] for cid in selected)
            total_a += a_count
            total_b += b_count
            per_match.append({
                "group": group, "n": len(selected),
                "first_rate": a_count / len(selected),
                "second_rate": b_count / len(selected),
                "delta": (a_count - b_count) / len(selected),
            })
        if per_match:
            macro_a = statistics.fmean(g["first_rate"] for g in per_match)
            macro_b = statistics.fmean(g["second_rate"] for g in per_match)
            macro_delta = statistics.fmean(g["delta"] for g in per_match)
            case_delta = (total_a - total_b) / len(eligible)
        else:
            macro_a = macro_b = macro_delta = case_delta = None

        interval = None
        if len(per_match) >= 3:
            deltas = [g["delta"] for g in per_match]
            # Each resample draws whole replay groups. This does NOT convert
            # correlated clips from one match into independent observations.
            draws = sorted(statistics.fmean(rng.choices(deltas, k=len(deltas)))
                           for _ in range(bootstrap_samples))
            interval = [
                round(_quantile(draws, 0.025), 4),
                round(_quantile(draws, 0.975), 4),
            ]

        metrics[metric] = {
            "direction": direction,
            "paired_cases": len(eligible),
            "eligible_match_groups": len(per_match),
            "first_events": total_a,
            "second_events": total_b,
            "first_case_weighted_rate": _ratio(total_a, len(eligible)),
            "second_case_weighted_rate": _ratio(total_b, len(eligible)),
            "first_match_equal_rate": round(macro_a, 4) if macro_a is not None else None,
            "second_match_equal_rate": round(macro_b, 4) if macro_b is not None else None,
            "delta_case_weighted": round(case_delta, 4) if case_delta is not None else None,
            "delta_match_equal": round(macro_delta, 4) if macro_delta is not None else None,
            "bootstrap_95pct_interval_of_match_equal_delta": interval,
            "bootstrap_status": (
                "exploratory_cluster_interval" if interval is not None
                else "insufficient_match_groups_for_interval"
            ),
        }
    return {
        "schema": SCHEMA,
        "first_system": system_a,
        "second_system": system_b,
        "seed": seed,
        "bootstrap_samples": bootstrap_samples,
        "total_cases": len(indexed),
        "consensus_cases": len(consensus),
        "excluded_disputed": len(baseline_report["disputed_case_ids"]),
        "excluded_insufficient_review": len(
            baseline_report["insufficient_review_case_ids"]
        ),
        "excluded_indeterminate": len(
            baseline_report["indeterminate_consensus_case_ids"]
        ),
        "consensus_match_groups": len(groups),
        "metrics": metrics,
        "interpretation": (
            "Differences use the SAME expert-consensus cases for both systems. "
            "Missing predictions, abstentions, and invalid/absent citations score "
            "zero grounded correctness and coverage. False risk accusations on "
            "expert-sound cases count even without valid citations. "
            "Match-equal estimates and exploratory whole-match bootstrap intervals "
            "help avoid one replay dominating through many correlated cases; "
            "they do not establish population generalizability or tactical optimality. "
            "Expert disagreement and indeterminate decisions are excluded, never "
            "treated as proof that either model is right. A model may pass a citation "
            "format check while still making a semantically false claim. "
            "Do not select an architecture solely from these figures."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two replay coaching systems on paired, human-rated matches")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--system-a", required=True)
    parser.add_argument("--system-b", required=True)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = paired_compare(
        _read_records(args.cases), _read_records(args.predictions),
        _read_records(args.reviews), args.system_a, args.system_b,
        seed=args.seed, bootstrap_samples=args.bootstrap_samples,
    )
    serialized = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)


if __name__ == "__main__":
    main()

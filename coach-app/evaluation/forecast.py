"""Evaluate short-horizon outcome forecasts; never turn them into decision verdicts.

Outcome labels are ONLY loaded during evaluation after predictions are fixed.
An accurate forecast of conceding is not evidence that a particular player
could have prevented that concession, or that a tactical alternative was sound.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .score import _finite_number, _need, _read_records, _valid_cases


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 5) if values else None


def _logloss(p: float, y: int) -> float:
    p = min(1 - 1e-12, max(1e-12, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def evaluate_forecasts(
    cases: list[dict[str, Any]],
    forecasts: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    horizon_s: float,
) -> dict[str, Any]:
    """Score binary scoring/conceding forecasts on complete observation windows.

    Formats:
      forecasts: {case_id,system_id,horizon_s,p_score,p_concede}
      outcomes:  {case_id,horizon_s,observed_through_s,
                  scored_within_horizon,conceded_within_horizon}
    Realized outcomes are intentionally separate from the pre-t0 case data.
    """
    indexed = _valid_cases(cases)
    _need(_finite_number(horizon_s) and horizon_s > 0,
          "horizon_s must be positive and finite")

    labels = {}
    censored = []
    for row in outcomes:
        _need(isinstance(row, dict), "Outcome row must be an object")
        cid = row.get("case_id")
        _need(cid in indexed, f"Outcome for unknown case: {cid}")
        _need(cid not in labels, f"Duplicate outcome: {cid}")
        _need(_finite_number(row.get("horizon_s")) and
              abs(row["horizon_s"] - horizon_s) < 1e-6,
              f"{cid}: incorrect outcome horizon")
        observed = row.get("observed_through_s")
        _need(_finite_number(observed) and observed >= indexed[cid]["t0"],
              f"{cid}: invalid observation end")
        for key in ("scored_within_horizon", "conceded_within_horizon"):
            _need(isinstance(row.get(key), bool), f"{cid}: {key} must be boolean")
        if observed + 1e-6 < indexed[cid]["t0"] + horizon_s:
            censored.append(cid)
        labels[cid] = row

    eligible = {
        cid: row for cid, row in labels.items() if cid not in censored
    }
    per_system: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in forecasts:
        _need(isinstance(row, dict), "Forecast must be an object")
        cid, sid = row.get("case_id"), row.get("system_id")
        _need(cid in indexed, f"Forecast for unknown case: {cid}")
        _need(isinstance(sid, str) and sid.strip(), "Forecast requires system_id")
        _need(cid not in per_system[sid], f"Duplicate forecast: {sid}/{cid}")
        _need(_finite_number(row.get("horizon_s")) and
              abs(row["horizon_s"] - horizon_s) < 1e-6,
              f"{sid}/{cid}: forecast horizon mismatch")
        for field in ("p_score", "p_concede"):
            _need(_finite_number(row.get(field)) and 0 <= row[field] <= 1,
                  f"{sid}/{cid}: {field} must be between 0 and 1")
        per_system[sid][cid] = row

    systems = {}
    for sid, supplied in sorted(per_system.items()):
        valid_cases = sorted(set(supplied) & set(eligible))
        breakdown = {}
        for task, pkey, truthkey in [
            ("score", "p_score", "scored_within_horizon"),
            ("concede", "p_concede", "conceded_within_horizon"),
        ]:
            probs = [supplied[cid][pkey] for cid in valid_cases]
            truths = [int(eligible[cid][truthkey]) for cid in valid_cases]
            briers = [(p - y) ** 2 for p, y in zip(probs, truths)]
            losses = [_logloss(p, y) for p, y in zip(probs, truths)]
            base_rate = sum(int(v[truthkey]) for v in eligible.values()) / len(eligible) if eligible else None
            bins = []
            for i in range(5):
                selected = [(p, y) for p, y in zip(probs, truths)
                            if (i / 5 <= p < (i + 1) / 5) or (i == 4 and p == 1)]
                if selected:
                    bins.append({
                        "range": f"{i / 5:.1f}-{(i + 1) / 5:.1f}",
                        "n": len(selected),
                        "mean_predicted": _average([v[0] for v in selected]),
                        "empirical_rate": _average([v[1] for v in selected]),
                    })
            breakdown[task] = {
                "n": len(valid_cases),
                "observed_base_rate": round(base_rate, 5) if base_rate is not None else None,
                "brier": _average(briers),
                "log_loss": _average(losses),
                # This uses the held-out evaluation prevalence itself: an
                # optimistic diagnostic reference, NOT a deployable trained baseline.
                "evaluation_prevalence_reference_brier": (
                    _average([(base_rate - int(row[truthkey])) ** 2
                              for row in eligible.values()])
                    if base_rate is not None else None
                ),
                "calibration_bins": bins,
            }
        systems[sid] = {
            "forecasts_submitted": len(supplied),
            "complete_outcome_cases": len(eligible),
            "scored_forecasts": len(valid_cases),
            "missing_complete_outcome_forecasts": len(eligible) - len(valid_cases),
            "forecast_coverage": (
                round(len(valid_cases) / len(eligible), 4) if eligible else None
            ),
            "tasks": breakdown,
        }

    return {
        "schema": "replay-lab-state-forecast-benchmark-v1",
        "horizon_s": horizon_s,
        "cases": len(indexed),
        "labeled_cases": len(labels),
        "complete_outcome_cases": len(eligible),
        "censored_case_ids": sorted(censored),
        "systems": systems,
        "interpretation": (
            "Outcomes are post-decision labels evaluated only after forecasts "
            "are frozen. Brier/log loss measure probability forecasting, NOT "
            "the quality of a player choice or any counterfactual action. "
            "Matches are correlated; evaluate with entire-match holdouts."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score heldout state forecast calibration")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--forecasts", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--horizon", type=float, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    scored = evaluate_forecasts(
        _read_records(args.cases), _read_records(args.forecasts),
        _read_records(args.outcomes), args.horizon,
    )
    result = json.dumps(scored, indent=2) + "\n"
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result)


if __name__ == "__main__":
    main()

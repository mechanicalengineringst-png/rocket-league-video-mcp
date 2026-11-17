"""Choose a coverage-first blind pilot, not a cherry-picked detector-only set.

A proposed review cohort must include detector-selected moments AND moments
sampled independently from live gameplay. This helps quantify overlooked
situations rather than only testing precision on situations our system found.

Selection metadata is deliberately separate from reviewer-facing case packets.
It MUST NEVER be passed to a human reviewer or predictive model as a feature.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .score import _need, _read_records, _valid_cases

DEFAULT_SITUATIONS = (
    "kickoff_support",
    "first_man_challenge",
    "last_man_defense",
)
ORIGINS = ("detector", "independent_time_sample")


def select_pilot(
    cases: list[dict[str, Any]],
    selection_manifest: list[dict[str, Any]],
    *,
    per_situation: int = 20,
    min_replay_groups: int = 3,
    min_time_gap_s: float = 5.0,
    seed: int = 20261117,
    situation_types: tuple[str, ...] = DEFAULT_SITUATIONS,
) -> dict[str, Any]:
    """Select a balanced, reproducible cohort with explicit scarcity failures.

    selection_manifest entries: {case_id, origin}, where origin is either
    detector or independent_time_sample. The exporter is responsible for
    proving that independent_time_sample was drawn from eligible game clock
    windows BEFORE running the event detector or viewing the eventual outcome.

    Enforces temporal separation within each replay to avoid multiple near-
    duplicate judgments. Greedily balances match coverage; does not assert
    that individual reviews or future outcomes are statistically independent.
    """
    indexed = _valid_cases(cases)
    _need(isinstance(per_situation, int) and not isinstance(per_situation, bool)
          and per_situation >= 2 and per_situation % 2 == 0,
          "per_situation must be a positive even integer >= 2")
    _need(isinstance(min_replay_groups, int) and not isinstance(min_replay_groups, bool)
          and min_replay_groups >= 2, "min_replay_groups must be >= 2")
    _need(isinstance(min_time_gap_s, (int, float))
          and not isinstance(min_time_gap_s, bool)
          and math.isfinite(min_time_gap_s) and min_time_gap_s >= 0,
          "min_time_gap_s must be finite and nonnegative")
    _need(bool(situation_types) and len(situation_types) == len(set(situation_types)),
          "Provide unique nonempty situation types")
    _need(all(isinstance(s, str) and s.strip() for s in situation_types),
          "Situation type names must be nonempty strings")
    _need(isinstance(selection_manifest, list), "selection_manifest must be a list")

    labels: dict[str, str] = {}
    for row in selection_manifest:
        _need(isinstance(row, dict) and set(row) == {"case_id", "origin"},
              "Manifest entries must contain only case_id and origin")
        cid, origin = row["case_id"], row["origin"]
        _need(cid in indexed, f"Manifest contains unknown case_id: {cid}")
        _need(cid not in labels, f"Duplicate manifest case_id: {cid}")
        _need(origin in ORIGINS, f"{cid}: invalid selection origin {origin}")
        labels[cid] = origin
    missing = sorted(set(indexed) - set(labels))
    _need(not missing, f"Missing selection provenance for {len(missing)} cases: {missing[:5]}")

    group_by_case: dict[str, str] = {}
    for cid, case in indexed.items():
        group = case.get("replay_group")
        _need(isinstance(group, str) and group.strip(),
              f"{cid}: nonempty replay_group required")
        group_by_case[cid] = group

    all_groups = set(group_by_case.values())
    _need(len(all_groups) >= min_replay_groups,
          f"Insufficient distinct replay groups: found {len(all_groups)}, "
          f"need {min_replay_groups}. Do not review one replay as a general benchmark.")

    # Validate the stratum counts BEFORE drawing any cases. No unannounced
    # replacement of missing independent samples with detector candidates.
    by_stratum: dict[tuple[str, str], list[str]] = defaultdict(list)
    for cid, c in indexed.items():
        by_stratum[c["situation_type"], labels[cid]].append(cid)
    need = per_situation // 2
    shortages = {
        f"{sit}/{origin}": {"available": len(by_stratum[(sit, origin)]), "required": need}
        for sit in situation_types for origin in ORIGINS
        if len(by_stratum[(sit, origin)]) < need
    }
    _need(not shortages, "Insufficient case provenance strata: " + json.dumps(shortages))

    rng = random.Random(seed)
    selected: list[str] = []
    used_times: dict[str, list[float]] = defaultdict(list)
    global_count: Counter[str] = Counter()
    family_count: Counter[tuple[str, str]] = Counter()
    origin_count: Counter[tuple[str, str, str]] = Counter()

    # Interleave strata rather than selecting every detector case first.
    # This improves diversity when the temporal exclusion window overlaps.
    strata = [(sit, origin) for sit in situation_types for origin in ORIGINS]
    remaining = {key: list(by_stratum[key]) for key in strata}
    for pool in remaining.values():
        rng.shuffle(pool)
    for _ in range(need):
        rng.shuffle(strata)
        for sit, origin in strata:
            candidates = [
                cid for cid in remaining[(sit, origin)]
                if all(abs(indexed[cid]["t0"] - t) >= min_time_gap_s
                       for t in used_times[group_by_case[cid]])
            ]
            _need(bool(candidates), f"Temporal de-duplication exhausted {sit}/{origin}; "
                  "export more independent matches or lower time gap based on evidence.")
            # Prefer matches underrepresented overall, then within the
            # situation and source. Seeded pool order breaks exact ties.
            chosen = min(candidates, key=lambda cid: (
                global_count[group_by_case[cid]],
                family_count[(sit, group_by_case[cid])],
                origin_count[(sit, origin, group_by_case[cid])],
            ))
            selected.append(chosen)
            group = group_by_case[chosen]
            used_times[group].append(indexed[chosen]["t0"])
            global_count[group] += 1
            family_count[(sit, group)] += 1
            origin_count[(sit, origin, group)] += 1
            remaining[(sit, origin)].remove(chosen)

    actual_groups = set(group_by_case[cid] for cid in selected)
    _need(len(actual_groups) >= min_replay_groups,
          f"Selected cohort has only {len(actual_groups)} matches; "
          f"need at least {min_replay_groups}. Expand candidate pool.")

    # Order selected case IDs by type and stable time for audit/readability.
    selected.sort(key=lambda cid: (
        situation_types.index(indexed[cid]["situation_type"]),
        group_by_case[cid], indexed[cid]["t0"], cid,
    ))
    distribution: dict[str, dict[str, int]] = {
        sit: {origin: sum(
            indexed[cid]["situation_type"] == sit and labels[cid] == origin
            for cid in selected
        ) for origin in ORIGINS}
        for sit in situation_types
    }
    return {
        "schema": "replay-lab-coverage-first-pilot-v1",
        "method": "stratified_detector_and_independent_time_sample",
        "seed": seed,
        "min_time_gap_s": min_time_gap_s,
        "case_ids": selected,
        "total": len(selected),
        "match_groups": sorted(actual_groups),
        "cases_per_group": dict(sorted(global_count.items())),
        "per_situation": distribution,
        "warning": (
            "Source labels and sampling methods are assigned upstream, not proven "
            "by this selector. Independent-time cases must be sampled from "
            "eligible live play without consulting detector outputs/outcomes. "
            "Avoid disclosing manifest selection origin or later outcomes "
            "during the first-stage human review. Cases from one match are "
            "correlated even when separated in time."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select a multi-replay coverage-first blind coaching pilot"
    )
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--per-situation", type=int, default=20)
    parser.add_argument("--min-replays", type=int, default=3)
    parser.add_argument("--min-gap", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    selected = select_pilot(
        _read_records(args.cases), _read_records(args.manifest),
        per_situation=args.per_situation,
        min_replay_groups=args.min_replays,
        min_time_gap_s=args.min_gap,
        seed=args.seed,
    )
    result = json.dumps(selected, indent=2) + "\n"
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result)


if __name__ == "__main__":
    main()

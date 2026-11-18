"""Group-aware train/eval splits for experimental Rocket League models.

Never split individual situations at random. Adjacent frames, same kickoff,
same play and the same match are strongly dependent. Use match-level groups.
This does not fully protect against repeated *players* across different matches;
a later model may need player-level grouping as well.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .score import _need, _read_records, _valid_cases


def grouped_folds(
    cases: list[dict[str, Any]],
    n_folds: int = 3,
    seed: int = 20261117,
) -> list[dict[str, Any]]:
    """Build reproducible, approximately size-balanced match-level folds.

    The returned metadata contains case IDs and aggregate counts only, not
    player names or observations. Groups must identify distinct full replays.
    """
    indexed = _valid_cases(cases)
    by_group: dict[str, list[str]] = defaultdict(list)
    for case_id, case in indexed.items():
        group = case.get("replay_group")
        _need(isinstance(group, str) and group.strip(),
              f"{case_id}: replay_group required for leakage-safe splitting")
        by_group[group].append(case_id)

    _need(isinstance(n_folds, int) and not isinstance(n_folds, bool),
          "n_folds must be an integer")
    _need(n_folds >= 2, "n_folds must be >=2")
    _need(len(by_group) >= n_folds,
          f"At least {n_folds} different matches required; found {len(by_group)}")

    # Shuffle tied-size groups by seed, then first-fit the largest group into
    # the currently smallest fold. This reduces large match-count imbalance.
    groups = sorted(by_group)
    rng = random.Random(seed)
    rng.shuffle(groups)
    groups.sort(key=lambda g: len(by_group[g]), reverse=True)

    bins: list[list[str]] = [[] for _ in range(n_folds)]
    counts = [0] * n_folds
    for group in groups:
        smallest = min(range(n_folds), key=lambda i: (counts[i], i))
        bins[smallest].append(group)
        counts[smallest] += len(by_group[group])

    def summary(case_ids: list[str]) -> dict[str, int]:
        return dict(sorted(Counter(indexed[cid]["situation_type"] for cid in case_ids).items()))

    result = []
    all_ids = set(indexed)
    for i, test_groups in enumerate(bins):
        holdout = {cid for group in test_groups for cid in by_group[group]}
        train = all_ids - holdout
        _need(bool(train) and bool(holdout), "Fold has empty training or evaluation set")
        result.append({
            "fold": i + 1,
            "train_case_ids": sorted(train),
            "eval_case_ids": sorted(holdout),
            "train_replay_groups": sorted(set(by_group) - set(test_groups)),
            "eval_replay_groups": sorted(test_groups),
            "train_situations": summary(sorted(train)),
            "eval_situations": summary(sorted(holdout)),
        })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create match-grouped model evaluation folds"
    )
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    folds = grouped_folds(_read_records(args.cases), args.folds, args.seed)
    payload = {
        "schema": "replay-lab-match-group-folds-v1",
        "method": "entire_replay_holdout",
        "warning": (
            "Distinct replays may still feature the same players, sessions "
            "or nearly identical game states. Audit player overlap separately."
        ),
        "folds": folds,
    }
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()

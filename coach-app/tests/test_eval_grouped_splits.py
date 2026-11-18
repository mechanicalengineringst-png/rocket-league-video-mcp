"""Reject data leakage caused by random per-frame train/eval splits."""
import copy

import pytest

from evaluation.splits import grouped_folds


def match_cases():
    result = []
    for match, n in [("anonymous-m1", 3), ("anonymous-m2", 7),
                     ("anonymous-m3", 4), ("anonymous-m4", 6)]:
        for i in range(n):
            result.append({
                "case_id": f"{match}-case-{i}",
                "replay_group": match,
                "mode": "2v2",
                "situation_type": "last_man_defense" if i % 2 else "first_man_challenge",
                "t0": 40.0 + i,
                "pre_decision_evidence": [{
                    "key": "goal_side_position",
                    "claim": "Goal side car position observed",
                    "event_time_s": 40.0 + i,
                    "finalized_through_s": 40.0 + i,
                    "source": "replay", "source_quality": "high",
                }],
            })
    return result


def test_all_cases_appear_in_eval_once_and_no_match_crosses_train_boundary():
    cases = match_cases()
    folds = grouped_folds(cases, n_folds=3, seed=99)
    assert len(folds) == 3
    seen_holdouts = []
    for fold in folds:
        train = set(fold["train_case_ids"])
        test = set(fold["eval_case_ids"])
        assert train.isdisjoint(test)
        assert train.union(test) == {c["case_id"] for c in cases}
        assert set(fold["train_replay_groups"]).isdisjoint(fold["eval_replay_groups"])
        assert fold["eval_situations"]
        seen_holdouts.extend(test)
    assert len(seen_holdouts) == len(set(seen_holdouts)) == len(cases)
    assert folds == grouped_folds(cases, n_folds=3, seed=99)


def test_missing_replay_group_rejected_not_randomly_assigned():
    fixture = match_cases()
    fixture[0] = copy.deepcopy(fixture[0])
    fixture[0].pop("replay_group")
    with pytest.raises(ValueError, match="replay_group required"):
        grouped_folds(fixture)


def test_too_few_replays_and_empty_fold_are_rejected():
    with pytest.raises(ValueError, match="At least 5 different matches"):
        grouped_folds(match_cases(), n_folds=5)
    with pytest.raises(ValueError, match="n_folds must be >=2"):
        grouped_folds(match_cases(), n_folds=1)


def test_causal_evidence_validation_is_shared_with_eval_protocol():
    fixture = match_cases()
    fixture[0]["pre_decision_evidence"][0]["finalized_through_s"] = 999
    with pytest.raises(ValueError, match="post-decision-derived"):
        grouped_folds(fixture)

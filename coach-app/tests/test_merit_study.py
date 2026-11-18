"""Tactical merit study protocol (Round 11, Phase C).

ALL RATINGS HERE ARE SYNTHETIC, written to exercise the protocol and the metrics. They are not expert
labels and say nothing about the coach's quality.
"""
from __future__ import annotations

import copy

import pytest

from coach_app.merit_study import (ACTIONS, StudyError, build_stage_b, consensus, krippendorff_alpha_nominal,
                                   lock_stage_a, prepare_study, rationale_labels, score, validate_stage_a)


def _sys(acceptable=(), poor=()):
    return {a: "acceptable" if a in acceptable else "poor" if a in poor else "abstain" for a in ACTIONS}


def cases():
    out = []
    specs = [("covered_aggression", "challenge", _sys(("immediate_challenge", "shadow_delay"), ("rotate_through_small_pads",))),
             ("risky_aggression", "challenge", _sys(("shadow_delay",), ("immediate_challenge",))),
             ("intelligent_restraint", "shadow", _sys(("shadow_delay", "goal_side_hold"), ("immediate_challenge",))),
             ("withheld", "challenge", _sys()),
             ("possession", "challenge", _sys(("controlled_touch", "immediate_challenge"))),
             ("off_ball_defense", "retreat", _sys(("goal_side_hold", "yield_to_teammate")))]
    for k, (stratum, choice, labels) in enumerate(specs):
        for j in range(3):
            out.append({"case_id": f"c{k}{j}", "replay_group": f"m{j}", "team": "blue", "source_t0_s": 30.0 + k * 10 + j,
                        "stratum": stratum, "systems": {"sys": labels, "always_poor": _sys(poor=ACTIONS)},
                        "retrospective": {"observed_action": choice, "outcome": {"opponents_regained": j == 0}}})
    return out


def synthetic_rating(rid, rater, study, disagree_on=None):
    """A synthetic rater: rates the system's acceptable actions acceptable and the rest poor (SYNTHETIC)."""
    labels = study["private_map"][rid]["systems"]["sys"]
    ratings = {a: ("good" if v == "acceptable" else "poor" if v == "poor" else "cannot_judge") for a, v in labels.items()}
    if rid == disagree_on and rater == "r2":
        ratings["immediate_challenge"] = "good"
    return {"review_id": rid, "rater_id": rater, "ratings": ratings, "confidence": "medium",
            "preferred": [a for a, v in ratings.items() if v in ("good", "acceptable")][:1], "missing_info": ""}


@pytest.fixture
def study():
    return prepare_study(cases(), seed="test-seed", per_stratum=3)


def test_stage_a_packets_are_blind_and_end_at_t0(study):
    for p in study["stage_a_packets"]:
        assert p["clip_end_s"] == study["private_map"][p["review_id"]]["source_t0_s"]
        assert 3.0 <= p["clip_end_s"] - p["clip_start_s"] <= 5.0
        assert not {"systems", "stratum", "retrospective", "replay_group", "case_id"} & set(p)
        assert set(p["actions"]) == set(ACTIONS)
    assert set(study["strata_counts"]) >= {"withheld", "risky_aggression", "intelligent_restraint", "covered_aggression"}


def test_stage_a_validation_rejects_leaks_and_incomplete_ratings(study):
    rid = study["stage_a_packets"][0]["review_id"]
    good = synthetic_rating(rid, "r1", study)
    validate_stage_a([good], study["stage_a_packets"])
    bad = dict(good, outcome="goal")
    with pytest.raises(StudyError):
        validate_stage_a([bad], study["stage_a_packets"])
    partial = copy.deepcopy(good)
    partial["ratings"].pop("shadow_delay")
    with pytest.raises(StudyError):
        validate_stage_a([partial], study["stage_a_packets"])
    with pytest.raises(StudyError):
        validate_stage_a([good, good], study["stage_a_packets"])


def test_reveal_requires_the_matching_lock(study):
    resp = [synthetic_rating(p["review_id"], r, study) for p in study["stage_a_packets"] for r in ("r1", "r2")]
    lock = lock_stage_a(resp, study["stage_a_packets"])
    b = build_stage_b(study, resp, lock)
    assert b and all(x["clip_end_s"] > study["private_map"][x["review_id"]]["source_t0_s"] for x in b)
    tampered = copy.deepcopy(resp)
    tampered[0]["ratings"]["immediate_challenge"] = "good" if tampered[0]["ratings"]["immediate_challenge"] != "good" else "poor"
    with pytest.raises(StudyError):
        build_stage_b(study, tampered, lock)


def test_consensus_never_counts_contested_items_as_errors(study):
    rid = study["stage_a_packets"][0]["review_id"]
    a = {"review_id": rid, "rater_id": "r1", "ratings": {x: "poor" for x in ACTIONS}, "confidence": "low", "preferred": []}
    b = {"review_id": rid, "rater_id": "r2", "ratings": {x: "acceptable" for x in ACTIONS}, "confidence": "low", "preferred": []}
    c = consensus([a, b])
    assert {v["label"] for v in c.values()} == {"contested"}
    single = consensus([a])
    assert {v["label"] for v in single.values()} == {"insufficient"}


def test_metrics_detect_false_blame_and_reward_agreement(study):
    resp = [synthetic_rating(p["review_id"], r, study) for p in study["stage_a_packets"] for r in ("r1", "r2")]
    rep = score(study, resp)
    agree = rep["systems"]["sys"]["overall"]
    assert agree["false_blame"]["rate"] == 0.0 and agree["accuracy_when_judging"]["rate"] == 1.0
    blamer = rep["systems"]["always_poor"]["overall"]
    assert blamer["false_blame"]["rate"] == 1.0 and blamer["positive_recognition"]["rate"] == 0.0
    assert rep["inter_rater_alpha_nominal"] == 1.0
    assert "withheld" in rep["systems"]["sys"]["by_stratum"]


def test_withheld_cases_measure_abstention_quality(study):
    resp = [synthetic_rating(p["review_id"], r, study) for p in study["stage_a_packets"] for r in ("r1", "r2")]
    rep = score(study, resp)
    w = rep["systems"]["sys"]["by_stratum"]["withheld"]
    assert w["coverage"]["den"] == 0 or w["coverage"]["rate"] == 0.0
    assert rep["systems"]["sys"]["overall"]["expert_hard_share_among_abstentions"]["den"] > 0


def test_disagreement_lowers_alpha_and_is_reported(study):
    rid = study["stage_a_packets"][0]["review_id"]
    resp = []
    for p in study["stage_a_packets"]:
        for r in ("r1", "r2"):
            x = synthetic_rating(p["review_id"], r, study)
            if p["review_id"] == rid and r == "r2":
                x["ratings"] = {a: ("acceptable" if v == "poor" else "poor" if v in ("acceptable", "good") else v)
                                for a, v in x["ratings"].items()}
                x["preferred"] = []
            resp.append(x)
    rep = score(study, resp)
    assert rep["inter_rater_alpha_nominal"] < 1.0
    assert rep["expert_consensus_counts"].get("contested", 0) > 0


def test_hindsight_check_flags_ratings_that_follow_the_outcome(study):
    resp = [synthetic_rating(p["review_id"], r, study) for p in study["stage_a_packets"] for r in ("r1", "r2")]
    lock = lock_stage_a(resp, study["stage_a_packets"])
    reveal = build_stage_b(study, resp, lock)
    stage_b = []
    for x in reveal:
        bad_outcome = study["private_map"][x["review_id"]]["retrospective"]["outcome"]["opponents_regained"]
        stage_b.append({"review_id": x["review_id"], "rater_id": "r1",
                        "actual_action_rating": "poor" if bad_outcome else "good",
                        "outcome_view": "consistent", "view_changed": True})
    rep = score(study, resp, stage_b)
    h = rep["hindsight"]
    assert h["comparable"] > 0 and h["changed_in_outcome_direction"]["rate"] == 1.0


def test_rationale_adapter_abstains_when_judgment_is_withheld():
    assert set(rationale_labels({"judgment": "withheld"}).values()) == {"abstain"}
    assert krippendorff_alpha_nominal([]) is None

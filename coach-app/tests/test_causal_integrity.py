"""Causal-integrity regressions for decision cases (Round 4, Phase 1).

Synthetic fixtures only. They check that information available after t0 can
never be presented as pre-decision context, and that unknown telemetry stays
unknown instead of becoming an accusation.
"""
from __future__ import annotations

import copy

import pytest

from coach_app.commitment_detector import CommitmentWindow, detect_commitment_window
from coach_app.decision_cases import (
    extract_all_decision_cases,
    extract_first_man_challenge_cases,
    extract_kickoff_decision_cases,
    extract_last_man_defense_cases,
)
from coach_app.decision_evaluation import evaluate_decision_case_heuristics
from coach_app.evidence import Evidence, require_decision_evidence

PLAYERS = [
    {"id": "b1", "name": "Blue One", "team": "blue"},
    {"id": "b2", "name": "Blue Two", "team": "blue"},
    {"id": "o1", "name": "Orange One", "team": "orange"},
    {"id": "o2", "name": "Orange Two", "team": "orange"},
]


def _car(x, y, vx=0.0, vy=0.0, boost=50.0, z=17.0):
    return {"x": x, "y": y, "z": z, "velocity": [vx, vy, 0.0], "boost": boost}


def challenge_payload(mate_present: bool = True, mate_y: float = -4000.0) -> dict:
    """Blue One drives up the middle into a 50/50 at t=12.0 against Orange One."""
    frames = []
    for i in range(0, 141):
        t = round(i * 0.1, 2)
        b1_y = -3000.0 + (900.0 * t if t < 9.0 else 8100.0 + 1700.0 * (t - 9.0))
        b1_vy = 900.0 if t < 9.0 else 1700.0
        cars = {
            "b1": _car(0.0, min(b1_y, 1800.0), vy=b1_vy, boost=max(0.0, 80.0 - 3.0 * max(0.0, t - 9.0) * 10)),
            "o1": _car(0.0, 3000.0 - 60.0 * t, vy=-600.0, boost=40.0),
            "o2": _car(2000.0, 4000.0, boost=60.0),
        }
        if mate_present:
            cars["b2"] = _car(-500.0, mate_y, boost=30.0)
        frames.append({"t": t, "ball": {"x": 0.0, "y": 2000.0, "z": 93.0, "velocity": [0.0, 0.0, 0.0]}, "cars": cars})
    events = [{
        "type": "fifty_fifty", "startTime": 12.0, "resolveTime": 12.6,
        "teamZeroPlayerId": "b1", "teamOnePlayerId": "o1", "winningTeam": "orange",
    }]
    return {"title": "synthetic", "players": PLAYERS, "frames": frames, "events": events}


def _blue_challenge(payload):
    return [c for c in extract_first_man_challenge_cases(payload) if c.focus_player_id == "b1"][0]


# ---------- the leak itself ----------

def test_challenge_label_is_a_retrospective_observed_action_not_t0_context():
    case = _blue_challenge(challenge_payload())
    pre_keys = {e.key for e in case.pre_decision_evidence()}
    action = {e.key: e for e in case.observed_actions()}
    assert "challenge_approach" not in pre_keys
    assert "challenge_approach" in action
    assert action["challenge_approach"].finalized_through_s > case.t0      # needs the later 50/50
    with pytest.raises(ValueError, match="retrospective|future"):
        case.validate_admissibility(["challenge_approach"])


def test_every_pre_decision_fact_is_finalized_by_t0():
    payload = challenge_payload()
    payload["events"] += [{
        "type": "kickoff", "firstTouchTime": 3.0,
        "teamZeroNonTakers": [{"playerId": "b2", "startBoost": 85, "spawnPosition": "back_left"}],
        "teamOneNonTakers": [], "winningTeam": "blue",
    }]
    cases = extract_all_decision_cases(payload)
    assert cases
    for case in cases:
        for e in case.pre_decision_evidence():
            assert e.event_time_s <= case.t0 and e.finalized_through_s <= case.t0, (case.case_id, e.key)


def test_window_fields_never_reach_the_t0_context_or_eval_export():
    case = _blue_challenge(challenge_payload())
    ctx = case.sanitized_pre_decision_context()
    assert "commitment_window_s" not in ctx and "primary_constraint" not in ctx
    exported = case.to_eval_dict()
    keys = {e["key"] for e in exported["pre_decision_evidence"]}
    assert "challenge_approach" not in keys
    assert all(e["finalized_through_s"] <= exported["t0"] for e in exported["pre_decision_evidence"])


def test_llm_payload_labels_the_reviewed_action_and_retrospective_selection():
    case = _blue_challenge(challenge_payload())
    payload = case.to_llm_payload()
    assert all(f["key"] != "challenge_approach" for f in payload["pre_decision_facts"])
    assert payload["action_under_review"][0]["key"] == "challenge_approach"
    assert "NOT THE PLAYER'S INTENT" in payload["action_under_review"][0]["warning"]
    assert payload["case_selection"]["selection_finalized_through_s"] > case.t0


def test_pre_decision_facts_do_not_change_when_future_frames_are_poisoned(monkeypatch):
    """Fix t0, then rewrite every frame after t0. Facts at t0 must not move."""
    fixed = CommitmentWindow(9.0, 11.0, 9.0, "stopping_distance_exceeded", 0.0, 0.0, (), 12.0)
    monkeypatch.setattr("coach_app.commitment_detector.detect_commitment_window", lambda *a, **k: fixed)
    clean = challenge_payload()
    poisoned = copy.deepcopy(clean)
    for f in poisoned["frames"]:
        if f["t"] > 9.0:
            for car in f["cars"].values():
                car.update(x=9999.0, y=-9999.0, boost=0.0, velocity=[-2300.0, -2300.0, 0.0])
    a, b = _blue_challenge(clean), _blue_challenge(poisoned)
    assert a.t0 == b.t0 == 9.0
    assert [(e.key, e.claim) for e in a.pre_decision_evidence()] == [(e.key, e.claim) for e in b.pre_decision_evidence()]
    assert a.sanitized_pre_decision_context() == b.sanitized_pre_decision_context()


def test_observed_action_cannot_be_cited_as_decision_evidence():
    items = [
        Evidence("state", "Ball in own half.", 5.0, 5.0, "decision_context", "replay", "high"),
        Evidence("did", "Player challenged.", 5.0, 6.0, "observed_action", "derived", "experimental"),
    ]
    assert require_decision_evidence(["state"], items, 5.0)
    with pytest.raises(ValueError):
        require_decision_evidence(["did"], items, 5.0)


# ---------- unknown stays unknown; no false accusations ----------

def test_missing_teammate_is_unknown_and_the_verdict_abstains():
    case = _blue_challenge(challenge_payload(mate_present=False))
    assert case.tactical_context["mate_relative_depth"] == "unknown"
    verdict = evaluate_decision_case_heuristics(case)
    assert verdict["assessment"] == "abstain"


def test_teammate_ahead_is_a_tradeoff_not_an_accusation():
    case = _blue_challenge(challenge_payload(mate_y=2500.0))
    verdict = evaluate_decision_case_heuristics(case)
    assert verdict["assessment"] == "tradeoff"
    assert set(verdict["cited_evidence"]) <= {e.key for e in case.pre_decision_evidence()}


def test_last_man_case_is_dropped_when_teammate_is_deeper():
    frames = [{"t": 20.0, "ball": {"x": 0, "y": -3000, "z": 93, "velocity": [0, -800, 0]},
               "cars": {"b1": _car(0, -3500, boost=None), "b2": _car(0, -5000)}}]
    payload = {"title": "s", "players": PLAYERS, "frames": frames,
               "events": [{"type": "depth_role", "state": "most_back", "playerId": "b1", "t": 20.0}]}
    assert extract_last_man_defense_cases(payload) == []


def test_last_man_unknown_teammate_and_unknown_boost_stay_unknown():
    frames = [{"t": 20.0, "ball": {"x": 0, "y": -3000, "z": 93, "velocity": [0, -800, 0]},
               "cars": {"b1": {"x": 0, "y": -4500, "z": 17, "velocity": [0, 0, 0]}}}]
    payload = {"title": "s", "players": PLAYERS, "frames": frames,
               "events": [{"type": "depth_role", "state": "most_back", "playerId": "b1", "t": 20.0}]}
    case = extract_last_man_defense_cases(payload)[0]
    assert case.tactical_context["is_constrained_boost"] is None
    assert case.tactical_context["teammate_deeper_at_t0"] is None
    assert any("unknown" in u.lower() for u in case.uncertainties)
    verdict = evaluate_decision_case_heuristics(case)
    assert verdict["assessment"] != "constrained_situation"


def test_kickoff_role_is_finalized_at_first_touch_and_never_cited():
    events = [{"type": "kickoff", "firstTouchTime": 3.0,
               "teamZeroNonTakers": [{"playerId": "b2", "startBoost": 85, "spawnPosition": "back_left"}],
               "teamOneNonTakers": [], "winningTeam": "blue"}]
    frames = [{"t": round(i * 0.1, 2), "ball": {"x": 0, "y": 0, "z": 93},
               "cars": {"b2": _car(-256, -3840, vy=500.0)}} for i in range(40)]
    case = extract_kickoff_decision_cases({"title": "k", "players": PLAYERS, "frames": frames, "events": events})[0]
    assert "kickoff_role" not in {e.key for e in case.pre_decision_evidence()}
    verdict = evaluate_decision_case_heuristics(case)
    assert "kickoff_role" not in verdict["cited_evidence"]


# ---------- the detector's own claims ----------

def test_car_driving_away_is_not_marked_committed():
    """Reviewer counterexample: fast car right by the ball but moving away."""
    frames = [{"t": round(10 + i * 0.1, 2), "ball": {"x": 0, "y": 0, "z": 93},
               "cars": {"p": _car(0, -50 - 230 * i, vy=-2300.0)}} for i in range(10)]
    w = detect_commitment_window(frames, "p", 11.0)
    assert w.primary_constraint != "stopping_distance_exceeded"


def test_onset_is_the_sustained_approach_not_an_early_blip():
    frames = []
    for i in range(26):
        t = round(10 + i * 0.1, 2)
        if i == 2:
            vy, boost = 900.0, 70.0            # a one-sample blip at t=10.2
        elif i < 15:
            vy, boost = 300.0, 70.0            # cruising slowly
        else:
            vy, boost = 300.0 + 150.0 * (i - 14), 70.0 - 2.0 * (i - 14)   # sustained push from t=11.5
        y = -3000.0 + 300.0 * (t - 10)
        frames.append({"t": t, "ball": {"x": 0, "y": 0, "z": 93}, "cars": {"p": _car(0, y, vy=vy, boost=boost)}})
    w = detect_commitment_window(frames, "p", 12.5)
    assert w.t_earliest >= 11.4
    assert w.frames_used_through_s == 12.5
    assert w.to_dict()["retrospective"] is True


def test_detector_records_its_information_cutoff():
    w = detect_commitment_window([], "p", 30.0)
    assert w.frames_used_through_s == 30.0

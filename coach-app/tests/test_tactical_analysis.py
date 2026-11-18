"""Bounded tactical reading (Round 4, Phase 2). Synthetic fixtures only.

Each fixture is a hand-built 2v2 snapshot. These tests check behaviour and
honesty rules (t0-only inputs, unknowns stay unknown, no probabilities). They
say nothing about accuracy on real games.
"""
from __future__ import annotations

import copy
import json

from fastapi.testclient import TestClient

from coach_app.main import app
from coach_app.tactical_analysis import (
    assess_challenge,
    assess_shot,
    find_shot_opportunities,
    rank,
    read_state,
)

PLAYERS = [
    {"id": "b1", "name": "Blue One", "team": "blue"},
    {"id": "b2", "name": "Blue Two", "team": "blue"},
    {"id": "o1", "name": "Orange One", "team": "orange"},
    {"id": "o2", "name": "Orange Two", "team": "orange"},
]


def car(x, y, vx=0.0, vy=0.0, boost=50.0, z=17.0):
    return {"x": x, "y": y, "z": z, "velocity": [vx, vy, 0.0], "boost": boost}


def snapshot(cars, ball, t=10.0, players=PLAYERS):
    return {"title": "synthetic", "players": players, "frames": [{"t": t, "ball": ball, "cars": cars}], "events": []}


def ball(x, y, z=93.0, vx=0.0, vy=0.0):
    return {"x": x, "y": y, "z": z, "velocity": [vx, vy, 0.0]}


# Example A: Blue One carries the ball at y=3000; both defenders are low on boost,
# stationary and off the shot line.
EXAMPLE_A = dict(
    cars={"b1": car(0, 2850, vy=900, boost=60), "b2": car(-500, -1500, boost=40),
          "o1": car(-2500, 4400, boost=8), "o2": car(2600, 1500, boost=5)},
    ball=ball(0, 3000, vy=900),
)


def all_text(finding):
    d = finding.to_dict()
    parts = [d["headline"]] + [s["text"] for s in d["statements"]] + [a["basis"] for a in d["alternatives"]]
    return " ".join(parts)


# ---------- Example A: powershot vs possession ----------

def test_example_a_open_lane_flags_feasible_shot_without_a_probability():
    r = read_state(snapshot(**EXAMPLE_A), 10.0, "b1")
    f = assess_shot(r, "a", reviewed_action="no_shot")
    shot = next(a for a in f.alternatives if a.action == "immediate shot")
    carry = next(a for a in f.alternatives if a.action.startswith("keep possession"))
    assert shot.feasibility == "plausible"
    assert carry.feasibility == "plausible" and "low on boost" in carry.basis
    assert f.verdict == "missed_opportunity_hypothesis"
    assert "Scoring probability of the shot." in f.not_established
    assert "%" not in all_text(f) and "probab" not in all_text(f).lower()


def test_shot_taken_through_open_lane_is_reinforced():
    f = assess_shot(read_state(snapshot(**EXAMPLE_A), 10.0, "b1"), "a", reviewed_action="shot")
    assert f.verdict == "reinforce"


# ---------- adversarial: low-boost defender can still save ----------

def test_low_boost_defender_on_the_line_still_blocks():
    cars = dict(EXAMPLE_A["cars"], o1=car(0, 5000, boost=3))  # parked in goal with no boost
    f = assess_shot(read_state(snapshot(cars, EXAMPLE_A["ball"]), 10.0, "b1"), "a", reviewed_action="no_shot")
    shot = next(a for a in f.alternatives if a.action == "immediate shot")
    assert shot.feasibility == "implausible"
    assert f.verdict != "missed_opportunity_hypothesis"
    assert any("low boost does not stop" in s.text for s in f.statements)


# ---------- adversarial: apparent open net, unseen defender ----------

def test_missing_opponent_means_the_net_is_never_called_open():
    cars = {k: v for k, v in EXAMPLE_A["cars"].items() if k != "o1"}
    payload = snapshot(cars, EXAMPLE_A["ball"])
    f = assess_shot(read_state(payload, 10.0, "b1"), "a", reviewed_action="no_shot")
    shot = next(a for a in f.alternatives if a.action == "immediate shot")
    assert shot.feasibility == "unclear"
    assert f.verdict == "abstain"
    assert any("Orange One" in u for u in f.unknowns)
    assert find_shot_opportunities(payload, "b1") == []


# ---------- causal: future frames cannot change the reading ----------

def test_reading_is_identical_when_frames_after_t0_are_poisoned():
    base = snapshot(**EXAMPLE_A)
    later = copy.deepcopy(base["frames"][0])
    later["t"] = 10.1
    clean = copy.deepcopy(base)
    clean["frames"].append(copy.deepcopy(later))
    poisoned = copy.deepcopy(base)
    for c in later["cars"].values():
        c.update(x=0.0, y=5000.0, boost=100.0)               # every defender teleports into goal
    later["ball"] = ball(0, -5000)
    poisoned["frames"].append(later)
    a = assess_shot(read_state(clean, 10.0, "b1"), "a").to_dict()
    b = assess_shot(read_state(poisoned, 10.0, "b1"), "a").to_dict()
    assert a == b


def test_retrospective_shot_label_never_changes_the_t0_reading():
    r = read_state(snapshot(**EXAMPLE_A), 10.0, "b1")
    took, skipped = assess_shot(r, "a", "shot"), assess_shot(r, "a", "no_shot")
    assert [s.text for s in took.statements if s.kind != "interpretation"] == \
        [s.text for s in skipped.statements if s.kind != "interpretation"]
    assert [a.feasibility for a in took.alternatives] == [a.feasibility for a in skipped.alternatives]


def test_opportunity_scan_labels_what_followed_as_retrospective():
    frames = []
    for i in range(16):
        t = round(10 + i * 0.1, 2)
        frames.append({"t": t, "ball": ball(0, 3000 + 90 * i, vy=900), "cars": {
            "b1": car(0, 2850 + 90 * i, vy=900, boost=60), "b2": car(-500, -1500),
            "o1": car(-2500, 4400, boost=8), "o2": car(2600, 1500, boost=5)}})
    found = find_shot_opportunities({"players": PLAYERS, "frames": frames}, "b1")
    assert found and found[0].reviewed_action == "no_shot"   # the ball never headed at goal fast
    assert found[0].t0 == 10.0


# ---------- Example B: backboard challenge ----------

def test_example_b_backboard_challenge_isolating_teammate_is_a_risk_hypothesis():
    cars = {"b1": car(-2600, 4300, vy=1500, boost=12), "b2": car(-800, 1200, boost=40),
            "o1": car(-2900, 4900, boost=50), "o2": car(500, 3800, boost=70)}
    f = assess_challenge(read_state(snapshot(cars, ball(-2800, 4900, z=900)), 10.0, "b1"), "b")
    assert f.verdict == "risk_hypothesis"
    assert "mistake" not in all_text(f).lower()
    assert any(a.action.startswith("shadow") for a in f.alternatives)
    assert any(a.action.startswith("challenge") for a in f.alternatives)   # the action taken is compared, not assumed wrong
    assert "Probability of winning the 50/50." in f.not_established


def test_supported_aggressive_challenge_is_reinforced_not_flagged():
    cars = {"b1": car(0, 500, vy=1400, boost=70), "b2": car(-300, -1800, boost=60),
            "o1": car(0, 1500, vy=-1000, boost=40), "o2": car(1500, 4500, boost=50)}
    f = assess_challenge(read_state(snapshot(cars, ball(0, 1000)), 10.0, "b1"), "c")
    assert f.verdict == "reinforce"


def test_challenge_with_missing_teammate_abstains():
    cars = {"b1": car(-2600, 4300, boost=12), "o1": car(-2900, 4900), "o2": car(500, 3800)}
    f = assess_challenge(read_state(snapshot(cars, ball(-2800, 4900, z=900)), 10.0, "b1"), "d")
    assert f.verdict == "abstain"


def test_unknown_boost_never_becomes_costly_recovery():
    cars = {"b1": car(-2600, 4300, boost=None), "b2": car(-800, 1200, boost=40),
            "o1": car(-2900, 4900), "o2": car(500, 3800)}
    f = assess_challenge(read_state(snapshot(cars, ball(-2800, 4900, z=900)), 10.0, "b1"), "e")
    assert f.verdict != "risk_hypothesis"
    assert any("Boost of Blue One" in u for u in f.unknowns)


def test_orange_focus_uses_its_own_attacking_direction():
    """Example B mirrored for orange must read the same."""
    mirror = lambda c: dict(c, x=-c["x"], y=-c["y"], velocity=[-c["velocity"][0], -c["velocity"][1], 0.0])
    cars = {"o1": mirror(car(-2600, 4300, vy=1500, boost=12)), "o2": mirror(car(-800, 1200, boost=40)),
            "b1": mirror(car(-2900, 4900, boost=50)), "b2": mirror(car(500, 3800, boost=70))}
    f = assess_challenge(read_state(snapshot(cars, mirror(ball(-2800, 4900, z=900))), 10.0, "o1"), "m")
    assert f.verdict == "risk_hypothesis"


# ---------- honesty rules ----------

def test_interpretations_are_never_high_confidence_and_ranking_is_labelled():
    r = read_state(snapshot(**EXAMPLE_A), 10.0, "b1")
    findings = rank([assess_shot(r, "x-b1", "no_shot"), assess_shot(r, "y-b1", "shot")], "b1")
    for f in findings:
        assert all(s.confidence in ("low", "medium") for s in f.statements if s.kind == "interpretation")
        assert "not a probability" in f.ranking["note"]
        assert {"impact", "confidence", "relevance", "score"} <= f.ranking.keys()
    assert findings[0].verdict == "missed_opportunity_hypothesis"
    json.dumps([f.to_dict() for f in findings])   # serialisable for the API


def test_endpoint_returns_analysis_only_when_asked():
    from tests.test_causal_integrity import challenge_payload
    client = TestClient(app)
    payload = challenge_payload()
    plain = client.post("/api/decision-cases", json={"replay": payload, "evaluate": True}).json()
    assert all("analysis" not in c for c in plain["cases"])
    rich = client.post("/api/decision-cases", json={"replay": payload, "analyze": True, "player_id": "b1"}).json()
    challenge = [c for c in rich["cases"] if c["situation_type"] == "first_man_challenge"]
    assert challenge and challenge[0]["analysis"]["situation"] == "first_man_challenge"
    assert "opportunities" in rich

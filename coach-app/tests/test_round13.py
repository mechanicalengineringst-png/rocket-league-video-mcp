"""Round 13: field control, state features, value model, counterfactuals, control timeline, habits, V2 report.

Synthetic replays test mechanics and leakage guards only; they say nothing about tactical accuracy.
"""
from __future__ import annotations

import copy
import json
import math

import numpy as np
import pytest

from coach_app import field_control as fc
from coach_app.coach_report import analyze_moment
from coach_app.coach_report_v2 import VERDICT_V2, build_coaching_report_v2
from coach_app.coach_report_v2_render import render_markdown_v2
from coach_app.control_timeline import attribute, timeline, turning_points
from coach_app.counterfactual import drive, evaluate
from coach_app.habit_profile import _percentile, build_profile, measure, merge
from coach_app.situations import classify_frame
from coach_app.state_features import frame_features, mirror_frame, reach_times
from coach_app.synthetic_scenarios import T0, car, materialise, scenarios
from coach_app.value_model import FutureControlModel

SC = {s["name"]: s for s in scenarios()}
TEAM = {"b1": "blue", "b2": "blue", "o1": "orange", "o2": "orange"}


def frame_at(r, t=T0):
    return next(f for f in r["frames"] if abs(f["t"] - t) < 1e-6)


# ---------- field control ----------

def test_arrival_times_grow_with_distance_and_turning():
    c = car(0, 0, vy=1000, boost=50)
    pts = np.array([[0, 1000], [0, 3000], [0, -1000], [2000, 0]])
    t = fc.arrival_times(c, pts)
    assert t[0] < t[1]                          # farther ahead takes longer
    assert t[0] < t[2]                          # behind costs a turn
    assert np.all(t >= 0)


def test_airborne_car_lands_first_and_unusable_states_are_none():
    air = car(0, 0, vy=500, z=600)
    ground = car(0, 0, vy=500)
    p = np.array([[0, 500]])
    assert fc.arrival_times(air, p)[0] > fc.arrival_times(ground, p)[0]
    assert fc.arrival_times({"x": 0, "y": 0}, p) is None
    assert fc.arrival_times({**ground, "x": float("nan")}, p) is None


def test_control_is_mirror_symmetric_between_teams():
    r = materialise(SC["level_contest_with_cover"])
    fr = frame_at(r)
    a = fc.regions(fr, "blue", fc.control(fr, TEAM))
    swapped = {p: ("orange" if t == "blue" else "blue") for p, t in TEAM.items()}
    m = mirror_frame(fr, "orange")
    b = fc.regions(m, "orange", fc.control(m, swapped))
    for k in ("own_half", "own_goal_zone", "opponent_goal_zone"):
        assert a[k]["own"] == pytest.approx(b[k]["own"], abs=0.02)


def test_recovery_debt_zero_when_goal_side():
    r = materialise(SC["backboard_benchmark_ground"])
    d = fc.recovery_debt(frame_at(r), TEAM)
    assert d["b1"] == 0.0 and d["b2"] > 1.0 and d["o1"] > 0       # b2 is up-field, o1 is ball-side in our corner


# ---------- state features and value model ----------

def test_features_are_mirror_invariant():
    r = materialise(SC["level_contest_with_cover"])
    fr = frame_at(r)
    swapped = {p: ("orange" if t == "blue" else "blue") for p, t in TEAM.items()}
    m = mirror_frame(fr, "orange")
    a = frame_features(fr, TEAM, "blue", reach=reach_times(fr))
    b = frame_features(m, swapped, "orange", reach=reach_times(m))
    for k in a:
        if isinstance(a[k], float) and not math.isnan(a[k]) and not k.startswith("ctl_"):
            assert a[k] == pytest.approx(b[k], rel=1e-6, abs=1e-6), k


def test_value_model_loads_scores_and_ignores_the_future():
    m = FutureControlModel.load()
    assert m is not None and set(m.heads) == {"next_touch_own", "danger_5s"}
    r1 = materialise(SC["restraint_then_conceded"], "shadow_then_their_goal")
    r2 = materialise(SC["restraint_then_conceded"], "shadow_then_save")
    s1, s2 = m.score(frame_at(r1), TEAM, "blue"), m.score(frame_at(r2), TEAM, "blue")
    assert s1 == s2 and all(0 <= v <= 1 for v in s1.values())


def test_value_model_records_held_out_quality():
    spec = FutureControlModel.load().spec
    assert spec["held_out"]["next_touch_own"]["method"].startswith("leave-one-match-out")
    assert spec["held_out"]["danger_5s"]["auc"] > 0.7


# ---------- counterfactuals ----------

def test_counterfactual_families_and_horizon():
    r = materialise(SC["level_contest_with_cover"])
    out = evaluate(frame_at(r), TEAM, "b1", events=r["events"], value_model=FutureControlModel.load())
    assert out["status"] == "ok" and 0.25 <= out["horizon_s"] <= 1.0
    assert {"commit", "shadow", "retreat"} <= set(out["families"])
    assert all("value" in v for v in out["families"].values())


def test_counterfactual_ignores_events_after_t0_and_airborne_focus():
    r = materialise(SC["level_contest_with_cover"])
    fr = frame_at(r)
    late = r["events"] + [{"type": "boost_pickups", "t": T0 + 1, "padId": 3, "playerId": "o1"}]
    assert evaluate(fr, TEAM, "b1", events=late) == evaluate(fr, TEAM, "b1", events=r["events"])
    up = copy.deepcopy(fr)
    up["cars"]["b1"]["z"] = 500
    assert evaluate(up, TEAM, "b1")["status"] == "unsupported"


def test_drive_moves_toward_target():
    c = car(0, 0, vy=500, boost=50)
    a = drive(c, (0, 3000), 1.0, use_boost=True)
    assert a["y"] > 500 and a["boost"] < 50


# ---------- control timeline ----------

def test_timeline_and_attribution_shapes():
    r = materialise(SC["covered_first_man_aggression"], "challenge_then_their_goal")
    m = FutureControlModel.load()
    tl = timeline(r, "blue", m)
    assert tl and all(set(x) == {"t", "control", "next_touch_own", "danger_5s"} for x in tl)
    a = attribute(r, "blue", T0 - 1.0, T0 + 1.0, m)
    assert set(a["player_contribution"]) <= set(TEAM) and "change" in a
    tp = turning_points(r, "blue", k=3, model=m)
    assert tp["selection"].startswith("retrospective")


def test_timeline_skips_dead_ball_after_goal():
    r = materialise(SC["covered_first_man_aggression"], "challenge_then_their_goal")
    tl = timeline(r, "blue")
    goal_t = next(e["t"] for e in r["events"] if e["type"] == "goal_context")
    assert not [x for x in tl if goal_t <= x["t"] <= goal_t + 3]


# ---------- habit profile ----------

def test_habit_measure_merge_and_percentile():
    r = materialise(SC["second_man_low_boost"], "took_pads")
    m = measure(r, "b1")
    rates = merge([m, m])
    assert rates["last_back_share"]["n"] == 2 * m["time"]["last_back"]["n"]
    assert _percentile(0.5, [0.1, 0.2, 0.6, 0.9]) == 50 and _percentile(None, [0.1]) is None
    prof = build_profile([r], ["b1"])
    assert prof["schema"] == "HabitProfileV0" and len(prof["habits"]) == 10
    with pytest.raises(ValueError):
        build_profile([r], [])


# ---------- r13 ledger adjustment ----------

def test_r13_ledger_only_moves_toward_uncertainty_and_r12_is_unchanged():
    from coach_app.synthetic_scenarios import build
    cars = {"b1": car(0, -2200, fy=1.0, boost=50), "b2": car(-400, -4300, fy=1.0),
            "o1": car(0, -650, vy=0, fy=-1.0), "o2": car(2500, 3000)}          # opponent close to the ball, not moving
    r = build(cars, (0, -1000, 93), (0, 0, 0))
    fr = frame_at(r)
    sit = classify_frame(fr, r["players"], "b1").to_dict()
    a = analyze_moment(r, "b1", sit)
    b = analyze_moment(r, "b1", sit, ledger="r13")
    ca, cb = a["rationale"]["conditions"].get("carrier_committing"), b["rationale"]["conditions"].get("carrier_committing")
    assert ca["status"] == "fails" and cb["status"] == "within_error" and b["rationale"]["ledger_adjustments"]
    # R12 supported challenging because "the opponent is not driving at it"; R13 no longer trusts that at close range
    assert a["rationale"]["actions"]["immediate_challenge"]["status"] == "supported"
    assert b["rationale"]["actions"]["immediate_challenge"]["status"] == "conditional"
    assert a["rationale"]["ledger"] == "r12" and a["rationale"]["ledger_adjustments"] == []
    strength = {"supported": 3, "refuted": 3, "contested": 2, "conditional": 1}
    for act, x in a["rationale"]["actions"].items():
        assert strength[b["rationale"]["actions"][act]["status"]] <= strength[x["status"]] or \
            b["rationale"]["actions"][act]["status"] == x["status"]


# ---------- V2 report ----------

def test_v2_report_has_no_mistake_labels_and_stage_a_ignores_the_future():
    reps = {}
    for fut in ("shadow_then_their_goal", "shadow_then_save"):
        reps[fut] = build_coaching_report_v2(materialise(SC["restraint_then_conceded"], fut), "b1", max_findings=3)
    for rep in reps.values():
        assert rep["schema"] == "CoachingReportV2" and rep["method"]["model_called"] is False
        for f in rep["matches"][0]["decision_findings"]:
            assert f["retrospective"]["assessment"]["verdict_v2"] in set(VERDICT_V2.values())
            assert "questionable" not in json.dumps(f["retrospective"]["assessment"].get("verdict_v2"))
    strip = [[{k: v for k, v in f.items() if k != "retrospective"} for f in rep["matches"][0]["decision_findings"]]
             for rep in reps.values()]
    assert strip[0] == strip[1]
    md = render_markdown_v2(reps["shadow_then_save"])
    assert "Evidence status" in md and "Habits" in md and "%" in md


def test_v2_report_validates_input_and_api_route():
    r = materialise(SC["level_contest_with_cover"])
    with pytest.raises(ValueError):
        build_coaching_report_v2(r, "nobody")
    from fastapi.testclient import TestClient
    from coach_app.main import app
    c = TestClient(app)
    res = c.post("/api/coach/coaching-report-v2", json={"replay": r, "player_id": "b1", "max_findings": 2})
    assert res.status_code == 200, res.text[:300]
    assert res.json()["schema"] == "CoachingReportV2"
    assert c.post("/api/coach/coaching-report-v2", json={"replay": r, "player_id": "zz"}).status_code == 422

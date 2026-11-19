"""Round 14.5: a turning point's nearest earlier decision is not presumed to be its cause.

SYNTHETIC cases (mechanics and guards only, not tactical accuracy):
A. A boost detour leaves the player far up-field; the later linked moment is already too late to cover.
B. A safe boost pickup ends goal-side; a later decision is linked and the pickup must not be implicated.
"""
from __future__ import annotations

import copy

from coach_app.coach_report_v2 import build_coaching_report_v2, upstream_check
from coach_app.coach_report_v2_render import render_markdown_v2
from coach_app.synthetic_scenarios import T0, build, car, materialise, scenarios

SC = {s["name"]: s for s in scenarios()}


def items(*pairs):
    return [{"situation": {"t0": t, "situation_class": c}} for t, c in pairs]


def detour_replay():
    # focus came back from a far big pad: still deep in the opponent half when the attack arrives
    cars = {"b1": car(-3000, 3600, vy=-900, boost=100), "b2": car(500, 1200, vy=-600, boost=20),
            "o1": car(0, -1200, vy=-900, boost=50), "o2": car(1500, 500, vy=-700, boost=60)}
    return build(cars, (0, -1500, 93), (0, -900, 0))


def safe_pickup_replay():
    # focus took a pad on the way back and is goal-side when the next decision comes
    cars = {"b1": car(-600, -3000, vy=300, fy=1.0, boost=60), "b2": car(800, 800, vy=-500, boost=40),
            "o1": car(0, -1200, vy=-500, boost=50), "o2": car(2000, 1500, boost=60)}
    return build(cars, (0, -1500, 93), (0, -500, 0))


def test_case_a_detour_flags_that_the_linked_moment_was_already_constrained():
    r = detour_replay()
    out = upstream_check(r, "b1", T0, items((T0 - 4.0, "recovery_and_boost"), (T0, "first_defender")))
    up = out["upstream"]
    assert up["status"] == "already_constrained"
    assert up["recovery_debt_s"] > up["nearest_opponent_reach_s"] + 1.0
    assert [e["class"] for e in up["earlier_decisions"]] == ["recovery_and_boost"]   # listed, not blamed
    assert "cannot establish" in up["note"]
    assert "not evidence of cause" in out["link_basis"]


def test_case_b_safe_pickup_is_not_implicated_in_a_later_decision():
    r = safe_pickup_replay()
    out = upstream_check(r, "b1", T0, items((T0 - 4.0, "recovery_and_boost"), (T0, "first_defender")))
    up = out["upstream"]
    assert up["status"] == "in_position" and "earlier_decisions" not in up
    assert "not implicated" in up["note"]


def test_no_earlier_decision_says_so_instead_of_guessing():
    out = upstream_check(detour_replay(), "b1", T0, items((T0, "first_defender")))
    assert out["upstream"]["earlier_decisions"] == [] and "outside your choices" in out["upstream"]["note"]


def test_missing_focus_car_is_unknown_not_a_verdict():
    r = detour_replay()
    for f in r["frames"]:
        f["cars"].pop("b1", None)
    assert upstream_check(r, "b1", T0, [])["upstream"]["status"] == "unknown"


def test_guard_uses_no_information_after_the_linked_decision():
    a = detour_replay()
    b = copy.deepcopy(a)
    for f in b["frames"]:
        if f["t"] > T0:
            f["cars"]["b1"].update(x=0.0, y=-4800.0)        # rewrite the future: he gets back instantly
            f["ball"]["x"] += 2000
    b["events"].append({"type": "goal_context", "t": T0 + 1.0, "scoringTeam": "orange"})
    its = items((T0 - 4.0, "recovery_and_boost"))
    assert upstream_check(a, "b1", T0, its) == upstream_check(b, "b1", T0, its)


def test_v2_links_carry_the_basis_and_render():
    rep = build_coaching_report_v2(materialise(SC["covered_first_man_aggression"], "challenge_then_their_goal"), "b1",
                                   max_findings=2)
    for tp in rep["matches"][0]["turning_points"]:
        link = tp.get("decision_time_reading")
        if link:
            assert "not evidence of cause" in link["link_basis"]
            assert link["upstream"]["status"] in ("in_position", "already_constrained", "unknown")
    render_markdown_v2(rep)

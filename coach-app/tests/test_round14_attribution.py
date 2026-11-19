"""Round 14: turning-point attribution split into model heads; restraint and trade-offs are not scored as losses."""
from __future__ import annotations

import pytest

from coach_app.control_timeline import attribute, classify_heads
from coach_app.coach_report_v2 import build_coaching_report_v2
from coach_app.coach_report_v2_render import render_markdown_v2
from coach_app.synthetic_scenarios import T0, materialise, scenarios
from coach_app.value_model import FutureControlModel

SC = {s["name"]: s for s in scenarios()}


@pytest.mark.parametrize("dt, dd, back, gs, want", [
    (0.20, -0.10, None, None, "supports"),         # closer to the ball and less danger
    (0.00, -0.10, None, None, "supports"),         # pure defensive gain
    (-0.20, 0.10, None, None, "hurts"),
    (0.20, 0.15, None, None, "tradeoff"),          # chased: more touch chance, more danger
    (-0.20, -0.10, None, None, "tradeoff"),        # dropped off: less touch chance, less danger (no retreat info)
    (-0.20, 0.00, 900, True, "restraint"),         # retreated goal-side, danger not up: not a loss
    (-0.20, -0.10, 900, True, "restraint"),
    (-0.20, 0.10, 900, True, "hurts"),             # retreat that still raised danger is not shielded
    (-0.20, 0.00, 900, False, "hurts"),            # moved back but still not goal-side
    (0.01, -0.01, None, None, "negligible"),
])
def test_head_classification(dt, dd, back, gs, want):
    r = classify_heads(dt, dd, moved_back_uu=back, ended_goal_side=gs)
    assert r["label"] == want and r["kind"] == "model_association_not_cause"


def test_retreat_into_goal_side_is_never_labelled_hurts_unless_danger_rises():
    for dt in (-0.5, -0.1, -0.03):
        for dd in (-0.3, 0.0, 0.01):
            assert classify_heads(dt, dd, moved_back_uu=1200, ended_goal_side=True)["label"] in ("restraint", "supports",
                                                                                                    "negligible", "tradeoff")


def test_attribute_reports_heads_for_every_scored_player():
    r = materialise(SC["restraint_then_conceded"], "shadow_then_their_goal")
    a = attribute(r, "blue", T0, T0 + 2.0, FutureControlModel.load())
    assert set(a["player_heads"]) == set(a["player_contribution"])
    for pid, h in a["player_heads"].items():
        net = h["next_touch_change"] - h["danger_change"]
        assert net == pytest.approx(a["player_contribution"][pid], abs=2e-3)
    focus = a["player_heads"]["b1"]
    assert focus["moved_back_uu"] > 500 and focus["ended_goal_side"] is True
    assert focus["label"] != "hurts" or focus["danger_change"] > 0.02   # restraint is only 'hurts' if danger rose


def test_v2_keeps_frontend_fields_and_adds_the_reading():
    rep = build_coaching_report_v2(materialise(SC["covered_first_man_aggression"], "challenge_then_their_goal"), "b1",
                                   max_findings=2)
    for tp in rep["matches"][0]["turning_points"]:
        assert tp["your_movement"] in ("raised", "lowered") and isinstance(tp["your_movement_effect"], float)
        assert tp["your_movement_reading"]["kind"] == "model_association_not_cause"
        assert tp["causal_status"].startswith("association")
    md = render_markdown_v2(rep)
    assert "not proof your choice caused it" in md or "None found" in md

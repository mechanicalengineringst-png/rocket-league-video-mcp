"""TacticalOptionsV0 (Round 9): adversarial tests. Synthetic fixtures only.

Each scenario is a hand-built 2v2 snapshot run through the real pipeline:
build_episode_evidence -> build_stage1_episode_packet -> analyze_tactical_options.
They check reasoning rules (no style bias, no hindsight, unknowns stay unknown),
not tactical accuracy.
"""
from __future__ import annotations

import copy
import json

import pytest

from coach_app.claim_verifier import verify_stage1_claims
from coach_app.episode_evidence import build_episode_evidence
from coach_app.episode_stage1 import build_stage1_episode_packet
from coach_app.tactical_options import POLICY, TacticalOptionsError, analyze_tactical_options
from tests.test_episode_evidence import episode_replay

PLAYERS = [{"id": "b1", "name": "B1", "team": "blue"}, {"id": "b2", "name": "B2", "team": "blue"},
           {"id": "o1", "name": "O1", "team": "orange"}, {"id": "o2", "name": "O2", "team": "orange"}]
TIMES, START, PRIMARY = [4.0, 8.0, 11.0], 1.0, 11.0


def car(x, y, fy=1.0, vy=0.0, boost=60.0, z=17.0):
    return {"x": x, "y": y, "z": z, "velocity": [0.0, vy, 0.0], "forward": [0.0, fy, 0.0], "boost": boost}


def replay(cars: dict, ball=(0.0, -1000.0, 93.0), ball_v=(0.0, 0.0, 0.0), future=None, events=()):
    """Static snapshot repeated for 13 s; ``future`` rewrites frames after PRIMARY."""
    frames = []
    for i in range(13 * 30 + 1):
        t = round(i / 30, 4)
        fr = {"t": t, "ball": {"x": ball[0], "y": ball[1], "z": ball[2], "velocity": list(ball_v)},
              "cars": copy.deepcopy(cars)}
        if future and t > PRIMARY:
            future(fr)
        frames.append(fr)
    return {"title": "synthetic-options", "players": PLAYERS, "frames": frames, "events": list(events)}


def analyze(r):
    ep = build_episode_evidence(r, "b1", TIMES, START, PRIMARY)
    packet = build_stage1_episode_packet(ep)
    return analyze_tactical_options(packet), packet


def opt(out, action):
    return next(o for o in out["options"] if o["action"] == action)


# Blue One (focus) defends the -y goal. Ball in Blue's half.
FIRST_MAN = {"b1": car(0, -1600, fy=1.0), "b2": car(-400, -4300, fy=1.0),              # teammate deep: covering
             "o1": car(0, 600, fy=-1.0), "o2": car(2500, 3500, fy=-1.0)}                 # carrier further away
EVEN = {"b1": car(0, -1800, fy=1.0), "b2": car(-400, -4300, fy=1.0),
        "o1": car(0, -200, fy=-1.0), "o2": car(2500, 3500, fy=-1.0)}                      # equal distance to the ball
LATE_UNCOVERED = {"b1": car(0, -3600, fy=1.0, boost=8.0), "b2": car(1500, 1500, fy=-1.0),  # teammate up-field
                  "o1": car(0, -700, fy=-1.0), "o2": car(600, 300, fy=-1.0)}                # carrier on the ball, support close


# ---------- style neutrality ----------

def test_intelligent_first_man_aggression_is_not_criticized():
    out, packet = analyze(replay(FIRST_MAN))
    ch = opt(out, "immediate_challenge")
    assert out["state"]["contest_band"] == "focus_first" and out["state"]["covered"] is True
    assert ch["physically_feasible"] == "yes" and ch["strategic_stance"] == "defensible"
    assert ch["defensive_risk"] == "not_elevated" and ch["severe_limit_claims"] == []
    assert opt(out, "controlled_touch")["physically_feasible"] == "yes"


def test_deliberate_fifty_fifty_is_a_legitimate_option():
    out, _ = analyze(replay(EVEN))
    ff = opt(out, "controlled_fifty_fifty")
    assert out["state"]["contest_band"] == "even"
    assert ff["physically_feasible"] == "yes" and ff["strategic_stance"] == "defensible"
    assert ff["supporting_claims"]


def test_several_defensible_options_coexist_and_no_single_best_is_picked():
    for cars in (FIRST_MAN, EVEN):
        out, _ = analyze(replay(cars))
        assert out["multiple_defensible"] and len(out["defensible_options"]) >= 2
        assert out["picks_single_best"] is False
        assert not any(k in json.dumps(out).lower() for k in ("optimal", "best_action", "expected_value", "probability"))


def test_negative_control_late_uncovered_challenge_is_questionable_while_delay_is_not():
    out, _ = analyze(replay(LATE_UNCOVERED))
    assert out["state"]["contest_band"] in ("focus_late", "focus_late_close") and out["state"]["covered"] is False
    assert opt(out, "immediate_challenge")["strategic_stance"] == "questionable"
    assert opt(out, "immediate_challenge")["severe_limit_claims"]
    assert opt(out, "immediate_challenge")["defensive_risk"] == "elevated"
    assert opt(out, "shadow_delay")["strategic_stance"] in ("defensible", "defensible_with_conditions")


# ---------- teammate context is not blame ----------

def test_teammate_position_changes_options_without_blaming_the_focus_player():
    covered, _ = analyze(replay(FIRST_MAN))
    exposed_cars = dict(FIRST_MAN, b2=car(1500, 2500, fy=-1.0))         # teammate far up-field instead of deep
    exposed, _ = analyze(replay(exposed_cars))
    assert covered["teammate_support"]["covered"] is True and exposed["teammate_support"]["covered"] is False
    a, b = opt(covered, "immediate_challenge"), opt(exposed, "immediate_challenge")
    assert len(b["limiting_claims"]) > len(a["limiting_claims"])
    assert b["team_context_claims"] and exposed["teammate_support"]["team_context_claims"]
    assert "not attributed to the focus player" in exposed["teammate_support"]["attribution"]
    text = json.dumps(exposed).lower()
    assert "mistake" not in text and "blame" not in text and "fault" not in text


# ---------- unknowns stay unknown ----------

def test_unknown_boost_awareness_intent_and_flip_are_never_facts():
    cars = copy.deepcopy(FIRST_MAN)
    cars["b1"]["boost"] = None
    out, packet = analyze(replay(cars))
    assert out["state"]["focus_boost"] is None
    assert "The focus player's boost is unknown." in out["abstain_reasons"]
    texts = " ".join(c["text"] for c in out["claims"]).lower()
    assert "boost (freshness" not in texts                       # no boost number stated for the focus player
    for word in ("saw", "noticed", "intended", "wanted", "has a flip", "flip available"):
        assert word not in texts
    assert all(o["depends_on_unobservable"] for o in out["options"])
    assert any(c["epistemic_type"] == "UNKNOWN_INFORMATION" and "U.focus.boost" in c["cited_evidence_ids"]
               for c in out["claims"])
    assert any("could see" in n for n in out["not_observable"])


def test_every_claim_passes_the_existing_claim_verifier():
    for cars in (FIRST_MAN, EVEN, LATE_UNCOVERED):
        out, packet = analyze(replay(cars))
        node = next(n for n in packet["nodes"] if n["node_id"] == out["node_id"])["packet"]
        rep = verify_stage1_claims(node, out["claims"])
        assert rep["all_structural_checks_passed"], [r for r in rep["results"] if r["status"] == "rejected"]


# ---------- hindsight ----------

def _goal_future(fr):
    fr["ball"] = {"x": 0.0, "y": -5000.0, "z": 300.0, "velocity": [0.0, -2500.0, 0.0]}
    fr["cars"]["b1"].update(y=-4000.0, boost=0.0)


def test_rewriting_future_outcomes_does_not_change_the_analysis():
    calm = replay(LATE_UNCOVERED)
    conceded = replay(LATE_UNCOVERED, future=_goal_future,
                      events=[{"type": "touch", "t": 11.3, "playerId": "o1"},
                              {"type": "goal_context", "t": 12.0, "scorerId": "o1", "scoringTeam": "orange"}])
    assert analyze(calm)[0] == analyze(conceded)[0]


def test_acceptable_defence_is_not_judged_by_whether_a_goal_followed():
    shadow_ok = replay(LATE_UNCOVERED)
    goal_anyway = replay(LATE_UNCOVERED, future=_goal_future,
                         events=[{"type": "goal_context", "t": 12.5, "scorerId": "o2", "scoringTeam": "orange"}])
    a, b = analyze(shadow_ok)[0], analyze(goal_anyway)[0]
    assert opt(a, "shadow_delay") == opt(b, "shadow_delay")
    text = json.dumps(a).lower()
    assert a["uses_retrospective"] is False and "scored" not in text and "goal_context" not in text and "conceded" not in text


def test_input_with_retrospective_material_is_refused():
    _, packet = analyze(replay(FIRST_MAN))
    bad = dict(packet, retrospective={"nodes": {}})
    with pytest.raises(TacticalOptionsError):
        analyze_tactical_options(bad)
    with pytest.raises(TacticalOptionsError):
        analyze_tactical_options(dict(packet, retrospective_present=True))


# ---------- earlier contributors ----------

def test_earlier_contributors_remain_hypotheses():
    ep = build_episode_evidence(episode_replay(), "b1", [2.0, 6.0, 10.0], 0.5, 10.0)
    out = analyze_tactical_options(build_stage1_episode_packet(ep))
    hs = out["earlier_contributors"]
    assert hs and all(h["status"] == "hypothesis_unverified" for h in hs)
    assert any(h["kind"] == "boost" and h["observed_changes"] for h in hs)
    for h in hs:
        assert "not show the earlier choice was a mistake or a cause" in h["would_need"]
        assert set(h["bears_on_actions"]) <= {o["action"] for o in out["options"]}


def test_missing_primary_frame_abstains():
    r = replay(FIRST_MAN)
    r["frames"] = [f for f in r["frames"] if not 10.8 <= f["t"] <= 11.0]
    out, _ = analyze(r)
    assert out["status"] == "abstain" and out["options"] == [] and out["defensible_options"] == []


def test_earlier_node_can_be_analyzed_and_policy_is_reported():
    out, _ = analyze(replay(FIRST_MAN))
    first = analyze_tactical_options(build_stage1_episode_packet(build_episode_evidence(
        replay(FIRST_MAN), "b1", TIMES, START, PRIMARY)), focus_node_id="N1")
    assert first["node_id"] == "N1" and first["information_cutoff_s"] == 4.0
    assert out["policy"] == POLICY and "uncalibrated" in POLICY["note"]

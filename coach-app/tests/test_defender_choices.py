"""First-defender candidates, choice labels, defender reading and reconciliation (Round 5, checkpoint 3).

Synthetic fixtures only. They check the information rules and the decision
table, not tactical accuracy.
"""
from __future__ import annotations

import copy
import re

import pytest

from coach_app.choices import build_commitment_manifest, classify_choice, find_defender_candidates
from coach_app.coaching_view import reconcile
from coach_app.defender_decisions import assess_defender, defender_verdict
from coach_app.strategic_state import build_state
from coach_app.tactical_analysis import Finding

PLAYERS = [{"id": "b1", "name": "B1", "team": "blue"}, {"id": "b2", "name": "B2", "team": "blue"},
           {"id": "o1", "name": "O1", "team": "orange"}, {"id": "o2", "name": "O2", "team": "orange"}]
PR16_HINT = re.compile(r"^(?:Follow|Track) the (?:outlined|marked) (?:blue|orange) car$", re.I)


def car(x, y, fy, vy=0.0, boost=50.0):
    return {"x": x, "y": y, "z": 17.0, "velocity": [0.0, vy, 0.0], "forward": [0.0, fy, 0.0], "boost": boost}


def scenario(b1_y=-2400.0, mate=(0.0, 2000.0, -1.0), future="shadow"):
    """Orange One carries the ball into the blue half; Blue One is the goal-side first defender.

    Frames up to t=0.5 are identical for every ``future``; after that Blue One either
    drives into the ball (``challenge``) or backs off goal-side (``shadow``).
    """
    frames, events = [], []
    for i in range(91):
        t = round(i / 30, 4)
        ball_y = -1500.0 - 300.0 * t
        b1 = car(0.0, b1_y, 1.0)
        if t > 0.5 and future == "challenge":
            b1 = car(0.0, min(b1_y + 1800.0 * (t - 0.5), ball_y - 150.0), 1.0, 1800.0)
        elif t > 0.5 and future == "shadow":
            b1 = car(0.0, b1_y - 300.0 * (t - 0.5), -1.0, -300.0)
        frames.append({"t": t, "ball": {"x": 0.0, "y": ball_y, "z": 93.0, "velocity": [0.0, -300.0, 0.0]},
                       "cars": {"b1": b1, "b2": car(mate[0], mate[1], mate[2]),
                                "o1": car(0.0, ball_y + 500.0, -1.0, -800.0), "o2": car(2000.0, 2000.0, -1.0)}})
    if future == "challenge":
        events.append({"type": "touch", "t": 1.2, "playerId": "b1"})
    return {"title": "s", "players": PLAYERS, "frames": frames, "events": events}


def b1_candidates(payload):
    return [c for c in find_defender_candidates(payload) if c.player_id == "b1"]


# ---------- eligibility is decided at t0 ----------

def test_same_past_different_future_gives_the_same_candidate():
    a, b = b1_candidates(scenario(future="challenge")), b1_candidates(scenario(future="shadow"))
    assert a and b and a[0].t0 == b[0].t0 == 0.0
    assert a[0].eligibility == b[0].eligibility and a[0].state == b[0].state
    assert classify_choice(scenario(future="challenge"), 0.0, "b1").choice == "challenge"
    assert classify_choice(scenario(future="shadow"), 0.0, "b1").choice == "shadow"


def test_deleting_every_future_frame_keeps_the_candidate():
    full = scenario()
    cand = b1_candidates(full)[0]
    cut = dict(full, frames=[f for f in full["frames"] if f["t"] <= cand.t0])
    again = [c for c in find_defender_candidates(cut, start=cand.t0, end=cand.t0) if c.player_id == "b1"]
    assert again and again[0].eligibility == cand.eligibility and again[0].frames_used_through_s <= cand.t0


def test_choice_label_is_an_observed_action_finalized_after_t0():
    lab = classify_choice(scenario(future="challenge"), 0.0, "b1")
    assert lab.kind == "observed_action" and lab.finalized_through_s > 0.0
    assert "not the player's intent" in lab.warning


def test_defender_not_goal_side_is_not_a_candidate():
    p = scenario()
    for f in p["frames"]:
        f["cars"]["b1"]["y"] = f["ball"]["y"] + 600.0            # ahead of the ball
    assert b1_candidates(p) == []


# ---------- manifest matches PR #16's contract ----------

def test_manifest_rows_match_the_study_contract_and_jitter_lead_in():
    rows, side = [], []
    for k, b1_y in enumerate((-2400.0, -2600.0, -2800.0, -3000.0, -2300.0, -2500.0)):
        p = scenario(b1_y=b1_y, future=("challenge", "shadow")[k % 2])
        r, s = build_commitment_manifest(f"match-{k % 3}", p, b1_candidates(p))
        rows += r
        side += s
    fields = {"case_id", "replay_group", "detector_choice", "source_t0_s", "clip_start_s", "clip_end_s", "clip_file",
              "focus_hint"}
    assert rows and all(set(r) == fields for r in rows)
    assert all(PR16_HINT.fullmatch(r["focus_hint"]) for r in rows)
    assert all(r["detector_choice"] in ("challenge", "shadow", "unclear") for r in rows)
    assert all(0 <= r["clip_start_s"] <= r["source_t0_s"] <= r["clip_end_s"] for r in rows)
    leads = [r["source_t0_s"] - r["clip_start_s"] for r in rows if r["clip_start_s"] > 0]
    assert all(2.5 <= x <= 4.5 for x in leads)
    assert all(s["choice_finalized_through_s"] > s["eligibility_frames_used_through_s"] for s in side)


def test_manifest_clip_ends_before_a_goal():
    p = scenario(future="challenge")
    rows, _ = build_commitment_manifest("m", p, b1_candidates(p), goal_times=[1.8])
    assert rows and all(r["clip_end_s"] <= 1.3 for r in rows)


# ---------- defender reading: restraint, risk and unknowns ----------

@pytest.mark.parametrize("factors,choice,expected", [
    ({"contest_in_time": False, "teammate_can_cover": False}, "shadow", "reinforce"),     # high-value restraint
    ({"contest_in_time": False, "teammate_can_cover": False}, "challenge", "risk_hypothesis"),
    ({"contest_in_time": True, "teammate_can_cover": True}, "challenge", "reinforce"),    # correct aggression
    ({"contest_in_time": True, "teammate_can_cover": True}, "shadow", "tradeoff"),
    ({"contest_in_time": None, "teammate_can_cover": True}, "challenge", "abstain"),
    ({"contest_in_time": True, "teammate_can_cover": True}, "boost", "situation_brief"),
])
def test_defender_decision_table(factors, choice, expected):
    assert defender_verdict(factors, choice) == expected


def test_late_uncovered_shadow_is_reinforced_end_to_end():
    p = scenario(b1_y=-3200.0, future="shadow")
    cand = b1_candidates(p)[0]
    f = assess_defender(build_state(p, cand.t0, "b1"), classify_choice(p, cand.t0, "b1"), "x")
    assert f.factors == {"contest_in_time": False, "teammate_can_cover": False}
    assert f.verdict == "reinforce" and "mistake" not in f.headline.lower()


def test_deep_teammate_counts_as_covering():
    st = build_state(scenario(mate=(-300.0, -4500.0, 1.0)), 0.0, "b1")
    assert st.cover_s == 0.0


def test_teammate_on_a_wall_leaves_cover_unknown_and_abstains():
    p = scenario()
    for f in p["frames"]:
        f["cars"]["b2"].update(x=4050.0, z=700.0)
    st = build_state(p, 0.0, "b1")
    assert st.cover_s is None
    assert assess_defender(st, classify_choice(scenario(future="challenge"), 0.0, "b1"), "w").verdict == "abstain"


# ---------- reconciliation ----------

def _finding(verdict):
    return Finding("c", 1.0, "first_man_challenge", "h", verdict, [], [], [], [], "challenge", factors={})


@pytest.mark.parametrize("new,old,status,shown", [
    ("reinforce", "tactical_risk", "disputed", "disputed"),
    ("risk_hypothesis", "sound_positioning", "disputed", "disputed"),
    ("risk_hypothesis", "tradeoff", "single_method", "concern"),     # non-committal rule label is no opinion
    ("tradeoff", "tactical_risk", "partial", "neutral"),
    ("reinforce", "sound_positioning", "agree", "support"),
    ("reinforce", "reinforce_unknown_label", "single_method", "support"),
    ("abstain", "tactical_risk", "abstain", "abstain"),
    ("tradeoff", "unverified_coverage_hypothesis", "single_method", "neutral"),
])
def test_reconcile_never_shows_contradicting_verdicts(new, old, status, shown):
    out = reconcile(_finding(new), {"assessment": old})
    assert out["agreement"] == status and out["display"]["stance"] == shown
    assert out["baselines"]["rule_v1"]["shown_to_player"] is False
    assert out["needs_expert_rating"] == (status in ("disputed", "partial"))


def test_reconcile_keeps_outcome_out_of_the_judgement():
    out = reconcile(_finding("reinforce"), None, outcome_note="Conceded 4 s later")
    assert out["layers"]["happened"]["used_in_judgement"] is False
    assert out["layers"]["chosen"]["kind"] == "observed_action"


def test_candidates_ignore_a_rewritten_future():
    a = scenario(future="shadow")
    b = copy.deepcopy(a)
    for f in b["frames"]:
        if f["t"] > 0.5:
            f["ball"] = {"x": 3000.0, "y": 4000.0, "z": 800.0, "velocity": [2000.0, 2000.0, 500.0]}
    assert [(c.t0, c.eligibility) for c in b1_candidates(a) if c.t0 <= 0.5] == \
        [(c.t0, c.eligibility) for c in b1_candidates(b) if c.t0 <= 0.5]


def test_endpoint_returns_reconciled_coaching_and_defender_decisions():
    from fastapi.testclient import TestClient

    from coach_app.main import app
    from tests.test_causal_integrity import challenge_payload
    client = TestClient(app)
    body = client.post("/api/decision-cases", json={"replay": challenge_payload(), "analyze": True, "player_id": "b1"}).json()
    assert all("coaching" in c and c["coaching"]["baselines"]["rule_v1"]["shown_to_player"] is False for c in body["cases"])
    d = client.post("/api/decision-cases", json={"replay": scenario(b1_y=-3200.0), "analyze": True, "player_id": "b1"}).json()
    assert d["defender_decisions"] and d["defender_decisions"][0]["eligibility"]["rule"].startswith("defender-candidate")
    assert d["defender_decisions"][0]["coaching"]["layers"]["chosen"]["kind"] == "observed_action"

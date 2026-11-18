"""EpisodeEvidenceV0 (Round 8). Synthetic fixtures only; they check information rules, not tactics."""
from __future__ import annotations

import copy
import json

import pytest

from coach_app.episode_evidence import (EpisodeError, all_ids, build_episode_evidence, resolve, stage1_view)

PLAYERS = [{"id": "b1", "name": "B1", "team": "blue"}, {"id": "b2", "name": "B2", "team": "blue"},
           {"id": "o1", "name": "O1", "team": "orange"}, {"id": "o2", "name": "O2", "team": "orange"}]
TIMES, PRIMARY = [2.0, 6.0, 10.0], 10.0


def _car(x, y, vy, boost, fy=None):
    fy = fy if fy is not None else (1.0 if vy >= 0 else -1.0)
    return {"x": x, "y": y, "z": 17.0, "velocity": [0.0, vy, 0.0], "forward": [0.0, fy, 0.0], "boost": boost}


def episode_replay():
    """Blue One pushes up-field spending boost (0-7 s), then Orange counter-attacks into Blue's half (7-12 s)."""
    frames = []
    for i in range(0, 13 * 30 + 1):
        t = round(i / 30, 4)
        if t <= 7.0:
            b1 = _car(0.0, -3000.0 + 800.0 * t, 800.0, max(0.0, 80.0 - 10.0 * t))
            ball = {"x": 0.0, "y": -2500.0 + 800.0 * t, "z": 93.0, "velocity": [0.0, 800.0, 0.0]}
        else:
            b1 = _car(0.0, 2600.0 - 900.0 * (t - 7.0), -900.0, 10.0)
            ball = {"x": 500.0, "y": 3100.0 - 1500.0 * (t - 7.0), "z": 93.0, "velocity": [0.0, -1500.0, 0.0]}
        frames.append({"t": t, "ball": ball, "cars": {
            "b1": b1,
            "b2": _car(-1500.0, -2000.0 + 300.0 * min(t, 7.0), 300.0 if t <= 7 else 0.0, 45.0),
            "o1": _car(800.0, ball["y"] + 400.0, -800.0, 60.0),
            "o2": _car(-2000.0, 4000.0, 0.0, 70.0, fy=-1.0)}})
    events = [{"type": "touch", "t": 3.0, "playerId": "b1", "touchKind": "hard_hit", "ballSpeedChange": 900.0},
              {"type": "boost_pickups", "t": 5.0, "playerId": "b2", "padType": "small"},
              {"type": "bump", "t": 7.5, "playerId": "o2", "victimId": "b2"},
              {"type": "touch", "t": 10.5, "playerId": "o1"},
              {"type": "goal_context", "t": 12.0, "scorerId": "o1", "scoringTeam": "orange"}]
    return {"title": "synthetic-episode", "players": PLAYERS, "frames": frames, "events": events}


def build(replay=None, times=TIMES, start=0.5, primary=PRIMARY):
    return build_episode_evidence(replay or episode_replay(), "b1", times, start, primary, label="test")


# ---------- ordering and identity ----------

def test_episode_and_node_order_are_stable():
    a = build(times=[10.0, 2.0, 6.0])
    b = build(times=[2.0, 6.0, 10.0])
    assert a["episode_id"] == b["episode_id"]
    assert [n["node_id"] for n in a["nodes"]] == ["N1", "N2", "N3"]
    assert [n["t0"] for n in a["nodes"]] == [2.0, 6.0, 10.0]
    assert a["nodes"][-1]["is_primary"] and not any(n["is_primary"] for n in a["nodes"][:-1])
    assert [r["relation"] for r in a["relations"]] == ["precedes", "precedes"]
    assert json.dumps(stage1_view(a), sort_keys=True) == json.dumps(stage1_view(b), sort_keys=True)


def test_invalid_requests_are_refused():
    with pytest.raises(EpisodeError):
        build(times=[10.0])                                   # one node
    with pytest.raises(EpisodeError):
        build(times=[2.0, 6.0], primary=10.0)                 # primary not a decision time
    with pytest.raises(EpisodeError):
        build(times=[2.0, 12.0, 10.0])                        # node after the primary
    with pytest.raises(EpisodeError):
        build(start=-15.0)                                    # window longer than 20 s


# ---------- decision-time boundaries ----------

def test_every_node_respects_its_own_cutoff():
    ep = build()
    for n in ep["nodes"]:
        for e in n["snapshot"]["evidence"]:
            assert e["source_time_s"] is None or e["source_time_s"] <= n["t0"]
            if e["id"].startswith("C.") and isinstance(e["value"], dict):
                assert e["value"]["t"] <= n["t0"]
        assert "retrospective" not in n["snapshot"]
    # the N1 snapshot does not know about the touch at 3.0 s or the bump at 7.5 s
    n1_events = [e for e in ep["nodes"][0]["snapshot"]["evidence"] if e["id"].startswith("C.touch")]
    assert n1_events == []
    assert all(t["t"] <= PRIMARY for t in ep["timeline"])
    assert all(c["known_at_s"] in (6.0, 10.0) for c in ep["changes"])


def test_rewriting_future_outcomes_does_not_change_stage1():
    base = episode_replay()
    alt = copy.deepcopy(base)
    alt["events"] = [e for e in alt["events"] if e["t"] <= PRIMARY] + [
        {"type": "touch", "t": 10.2, "playerId": "b1"}, {"type": "goal_context", "t": 11.0, "scorerId": "b1"}]
    for f in alt["frames"]:
        if f["t"] > PRIMARY:
            f["ball"] = {"x": 0.0, "y": 4900.0, "z": 300.0, "velocity": [0.0, 2500.0, 0.0]}
            f["cars"]["b1"].update(y=4500.0, boost=100.0)
    a, b = build(base), build(alt)
    assert stage1_view(a) == stage1_view(b)
    assert a["retrospective"] != b["retrospective"]


def test_rewriting_after_an_earlier_node_changes_only_later_nodes():
    base = episode_replay()
    alt = copy.deepcopy(base)
    for f in alt["frames"]:
        if 2.0 < f["t"] <= 6.0:
            f["cars"]["b1"]["boost"] = 100.0
    a, b = build(base), build(alt)
    assert a["nodes"][0]["snapshot"] == b["nodes"][0]["snapshot"]      # N1 cannot see after 2.0 s
    assert a["nodes"][1]["snapshot"] != b["nodes"][1]["snapshot"]


# ---------- unknowns ----------

def test_unknown_boost_and_missing_positions_stay_unknown():
    r = episode_replay()
    for f in r["frames"]:
        if 5.5 <= f["t"] <= 6.0:
            f["cars"]["b1"]["boost"] = None
            f["cars"]["b2"]["x"] = float("nan")
    ep = build(r)
    ids = {c["id"] for c in ep["changes"]}
    unk = {u["id"]: u for u in ep["unknowns"]}
    assert "D.N1-N2.focus.boost" not in ids and "UD.N1-N2.focus.boost" in unk
    assert "N2/U.focus.boost" in unk["UD.N1-N2.focus.boost"]["refs"]
    assert "D.N1-N2.team_spacing" not in ids and "UD.N1-N2.team_spacing" in unk
    assert "N2/U.teammate.state" in unk
    assert resolve(ep, "N2/E.focus.boost") is None and resolve(ep, "N2/E.teammate.position") is None


def test_missing_decision_frame_abstains_gracefully():
    r = episode_replay()
    r["frames"] = [f for f in r["frames"] if not 5.7 <= f["t"] <= 6.0]
    ep = build(r)
    n2 = ep["nodes"][1]
    assert n2["status"] == "abstain" and ep["status"] == "partial"
    assert "N2/U.frame" in {u["id"] for u in ep["unknowns"]}
    assert any(u["id"].startswith("UD.N1-N2.") for u in ep["unknowns"])
    r["frames"] = [f for f in r["frames"] if not 9.7 <= f["t"] <= 10.0]
    assert build(r)["status"] == "abstain"                            # primary node missing


# ---------- earlier decisions vs later outcomes ----------

def test_earlier_decisions_are_separate_from_later_outcomes():
    ep = build()
    s1 = json.dumps(stage1_view(ep))
    assert "R." not in s1 and "goal_context" not in s1 and "retrospective" not in s1
    retro = ep["retrospective"]["nodes"]
    assert set(retro) == {"N1", "N2", "N3"}
    assert retro["N3"]["goal_within_5s"]["scored_by"] == "opponents"
    assert retro["N3"]["goal_within_5s"]["id"] == "N3/R.goal_within_5s"
    assert ep["retrospective"]["stage"] == 2


def test_possible_contributors_are_neutral_hypotheses_with_real_refs():
    ep = build()
    hyps = ep["possible_earlier_contributors"]
    assert hyps, "the fixture spends boost and pushes up-field; prompts are expected"
    for h in hyps:
        assert h["status"] == "hypothesis_unverified" and "no causal claim" in h["not_established"]
        assert h["question"].endswith("?")
        assert all(resolve(ep, ref) is not None for ref in h["evidence_refs"])
        assert not any(w in h["question"].lower() for w in ("caused", "mistake", "because", "should"))
    assert any("boost fell" in h["question"] for h in hyps)
    assert any("up-field" in h["question"] for h in hyps)


# ---------- identifiers ----------

def test_ids_are_unique_and_node_ids_are_preserved_exactly():
    ep = build()
    ids = all_ids(ep)
    assert len(ids) == len(set(ids))
    json.dumps(ep, allow_nan=False)                      # no NaN/inf can reach a serialized packet
    for n in ep["nodes"]:
        local = [e["id"] for e in n["snapshot"]["evidence"]]
        assert all(resolve(ep, f"{n['node_id']}/{i}")["id"] == i for i in local)
    for c in ep["changes"]:
        assert all(resolve(ep, ref) is not None for ref in c["refs"])

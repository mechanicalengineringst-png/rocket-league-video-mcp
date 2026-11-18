"""Round 12D independent math grounding for high-rank coaching.

These tests prove coordinate signs and Stage1 isolation, NOT recoverability,
possession, tactical quality, opponent intentions or a calibrated better play.
"""
from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient

from coach_app.main import app
from coach_app.episode_evidence import build_episode_evidence
from coach_app.episode_stage1 import build_stage1_episode_packet
from coach_app.relational_invariants import build_relational_invariants
from coach_app.stage1_packet import Stage1PacketError
from tests.test_episode_evidence import episode_replay


def artificial_packet(*, team="blue"):
    enemy = "orange" if team == "blue" else "blue"
    def node(nid, t):
        def ev(key, value, provenance=None):
            return {"id": key, "kind": "observation", "value": value,
                    "unit": "uu", "source_time_s": t,
                    "provenance": provenance or ["replay_sample"]}
        signed = -1 if team == "blue" else 1
        evidence = [
            ev("E.ball.position", [0, 0, 100]),
            ev("E.focus.position", [0, signed*2000, 17]),
            ev("E.teammate.position", [500, signed*1000, 17]),
            ev("E.opponent_1.position", [0, -signed*1000, 17]),
            ev("E.opponent_2.position", [800, -signed*2300, 17]),
            ev("E.focus.forward", [0, -signed, 0]),
            ev("E.teammate.forward", [1, 0, 0]),
            ev("E.opponent_1.forward", [0, signed, 0]),
            ev("E.opponent_2.forward", [-1, 0, 0]),
        ]
        return {"node_id": nid, "t0": t,
                "packet": {"cutoff_s":t, "status":"ok",
                   "slots":{"focus":{"team":team},"teammate":{"team":team},
                            "opponent_1":{"team":enemy},"opponent_2":{"team":enemy}},
                   "evidence":evidence}}
    return {"schema":"Stage1EpisodePacketV0",
            "nodes":[node("N1",3.),node("N2",7.)],
            "retrospective_present":False}


def find(data, metric, subject, nid="N2"):
    node = next(n for n in data["nodes"] if n["node_id"] == nid)
    return next(m for m in node["metrics"]
                if m["metric"] == metric and m["subject"] == subject)


@pytest.mark.parametrize("team",["blue","orange"])
def test_goalward_relation_has_correct_team_direction_not_tactical_grade(team):
    out=build_relational_invariants(artificial_packet(team=team))
    assert out["schema"]=="RelationalInvariantsV0"
    assert out["uses_future"] is False
    assert out["calculates_possession"] is False
    assert out["calculates_tactical_merit"] is False
    assert out["expert_calibrated"] is False
    assert find(out,"longitudinal_goal_side_of_ball","focus")["value"]=="goalward"
    assert find(out,"longitudinal_goal_side_of_ball","teammate")["value"]=="goalward"
    assert find(out,"longitudinal_goal_side_of_ball","opponent_1")["value"]=="upfield"
    assert find(out,"planar_ball_distance","focus")["value"]==2000.
    assert find(out,"teammate_lateral_separation","focus_and_teammate")["value"]==500.
    assert find(out,"teammate_planar_separation","focus_and_teammate")["value"]==round((1250000.)**0.5,1)
    face=find(out,"nose_to_ball_angle","focus")
    assert face["value"]==0
    assert face["source_refs"]==["N2/E.focus.forward","N2/E.focus.position","N2/E.ball.position"]
    assert all(m["derivation"]=="direct_coordinate_geometry_not_calibrated_tactics"
               for n in out["nodes"] for m in n["metrics"])


def test_stale_possible_and_missing_angle_abstain_instead_of_inventing_geometry():
    packet=artificial_packet()
    for node in packet["nodes"]:
        for e in node["packet"]["evidence"]:
            if e["id"]=="E.teammate.position":
                e["provenance"].append("stale_possible")
            if e["id"]=="E.focus.forward":
                e["value"]=[0,0,1]  # vertical nose cannot give a planar angle
    out=build_relational_invariants(packet)
    primary=out["nodes"][-1]
    assert not [m for m in primary["metrics"] if m["subject"]=="teammate"]
    assert any(u["metric"]=="planar_ball_distance" and u["subject"]=="teammate"
               for u in primary["unknowns"])
    assert any(u["metric"]=="nose_to_ball_angle" and u["subject"]=="focus"
               for u in primary["unknowns"])
    assert primary["status"]=="partial"


def test_each_earlier_node_has_its_own_geometry_never_recomputed_from_primary():
    p=artificial_packet()
    first=next(e for e in p["nodes"][0]["packet"]["evidence"]
               if e["id"]=="E.focus.position")
    first["value"]=[0,1000,17]  # Blue focus upfield of ball at N1 only
    out=build_relational_invariants(p)
    assert find(out,"longitudinal_goal_side_of_ball","focus","N1")["value"]=="upfield"
    assert find(out,"longitudinal_goal_side_of_ball","focus","N2")["value"]=="goalward"


def test_rejects_invalid_packet_schema_future_source_and_no_exposure_of_identity():
    p=artificial_packet()
    p["schema"]="RawReplayV0"
    with pytest.raises(Stage1PacketError):
        build_relational_invariants(p)
    p=artificial_packet()
    pos=next(e for e in p["nodes"][-1]["packet"]["evidence"]
             if e["id"]=="E.focus.position")
    pos["source_time_s"]=9.
    out=build_relational_invariants(p)
    assert find(out,"longitudinal_goal_side_of_ball","teammate")["value"]=="goalward"
    assert any(x["metric"]=="longitudinal_goal_side_of_ball" and x["subject"]=="focus"
               for x in out["nodes"][-1]["unknowns"])
    assert "private-player" not in json.dumps(out)


def packet_from_real_builder(r=None):
    replay=episode_replay() if r is None else r
    return build_stage1_episode_packet(build_episode_evidence(
        replay,"b1",[2.,6.,10.],0.5,10.))


def test_future_rewrite_does_not_change_any_scene_relation_or_source_refs():
    orig=episode_replay()
    changed=copy.deepcopy(orig)
    for frame in changed["frames"]:
        if frame["t"]>10:
            frame["ball"]["x"]=999999
            frame["cars"]["b1"]["x"]=-999999
    changed["events"].append({"type":"goal_context","t":12.8,"scorerId":"b1"})
    before=build_relational_invariants(packet_from_real_builder(orig))
    after=build_relational_invariants(packet_from_real_builder(changed))
    assert before==after
    assert all(m["source_refs"] and all("/E." in ref for ref in m["source_refs"])
               for n in after["nodes"] for m in n["metrics"])


def test_real_local_http_scene_relations_requires_deterministic_and_no_model(monkeypatch):
    monkeypatch.setenv("REPLAY_LAB_ENABLE_COACH_MODEL","0")
    client=TestClient(app)
    request={"replay":episode_replay(),"player_id":"b1",
             "decision_times":[2.,6.,10.],"episode_start_s":0.5,"primary_t0":10.,
             "mode":"deterministic"}
    resp=client.post("/api/coach/scene-relations",json=request)
    assert resp.status_code==200, resp.text
    body=resp.json()
    assert body["schema"]=="RelationalInvariantsV0"
    assert body["information_cutoff_s"]==10.
    assert body["nodes"][-1]["metrics"]
    assert body["calculates_tactical_merit"] is False
    assert client.post("/api/coach/scene-relations",json={**request,"mode":"model"}).status_code==422
    assert client.post("/api/coach/scene-relations",json={
        **request,"experimental_tactical_v1":True}).status_code==422

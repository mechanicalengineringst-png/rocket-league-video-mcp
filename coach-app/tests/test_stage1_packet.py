"""Pre-decision-only model packet: no future data, no verdicts, no paid calls."""
from __future__ import annotations

import copy
import json

import pytest

from coach_app.decision_evidence import build_decision_evidence
from coach_app.stage1_packet import (
    STAGE1_SCHEMA,
    Stage1PacketError,
    build_stage1_packet,
)
from tests.test_defender_choices import scenario

T0 = 1.0


def _record(payload=None):
    p = payload if payload is not None else scenario(future="challenge")
    return build_decision_evidence(
        p, T0, "b1", selection={"rule": "picked_using_future_goal", "actual_winner": "private_result"}
    )


def _with_predecision_touch():
    p = scenario(future="challenge")
    p["events"].append({
        "type": "touch", "t": 0.6, "playerId": "o1",
        "touchKind": "strong", "secret_outcome": "made_later"
    })
    return p


def test_stage1_whitelist_strips_retrospective_selection_raw_source_and_names():
    rec = _record(_with_predecision_touch())
    rec["source"] = {"path": "PRIVATE_LOCAL_REPLAY_FILE"}
    packet = build_stage1_packet(rec)
    encoded = json.dumps(packet, allow_nan=False)
    assert packet["schema"] == STAGE1_SCHEMA
    assert packet["decision_merit_calculated"] is False
    assert "retrospective" not in packet and "selection" not in packet and "source" not in packet
    assert not any(term in encoded for term in (
        "R.observed_action", "PRIVATE_LOCAL_REPLAY_FILE", "private_result",
        "secret_outcome", "made_later", '"b1"', '"o1"'
    ))
    event = next(e for e in packet["evidence"] if e["id"] == "C.touch.1")
    assert event["value"]["playerId"] == "opponent_1"
    assert "touchKind" not in event["value"]
    assert all(e["source_time_s"] is None or e["source_time_s"] <= T0 for e in packet["evidence"])


def test_future_rewrites_and_deletions_leave_entire_stage1_packet_identical():
    original = _with_predecision_touch()
    rewritten = copy.deepcopy(original)
    for frame in rewritten["frames"]:
        if frame["t"] > T0:
            frame["ball"].update(x=3900.0, y=4700.0, z=450.0)
            for car in frame["cars"].values():
                car.update(x=-2500.0, y=-1500.0, boost=0.0)
    rewritten["events"] = [e for e in rewritten["events"] if e["t"] <= T0]
    rewritten["events"].extend([
        {"type": "touch", "t": 1.15, "playerId": "o2"},
        {"type": "goal_context", "t": 1.8, "scorerId": "o2"},
    ])
    truncated = copy.deepcopy(original)
    truncated["frames"] = [f for f in truncated["frames"] if f["t"] <= T0]
    truncated["events"] = [e for e in truncated["events"] if e["t"] <= T0]
    a, b, c = (_record(p) for p in (original, rewritten, truncated))
    assert a["retrospective"] != b["retrospective"]
    assert build_stage1_packet(a) == build_stage1_packet(b) == build_stage1_packet(c)


def test_changing_stored_retrospective_and_selection_never_reaches_model():
    rec = _record()
    baseline = build_stage1_packet(rec)
    rec["retrospective"] = {
        "observed_action": "TERRIBLE_OUTCOME_YOU_MUST_BLAME",
        "next_touch": "R.leaked", "goal_within_5s": {"scored_by": "private_scored"}
    }
    rec["selection"] = {"future_result": "PRIVATE_SPOILER"}
    rec["source"] = {"player_id": "PRIVATE_USER_ID"}
    assert build_stage1_packet(rec) == baseline
    # No alias to a mutable nested record can corrupt a previously issued packet.
    rec["evidence"][0]["value"] = "MUTATED_LATER"
    assert build_stage1_packet(rec) != baseline
    assert baseline["evidence"][0]["value"] != "MUTATED_LATER"


def test_unknown_boost_and_exact_zero_are_distinct():
    p = scenario()
    for f in p["frames"]:
        f["cars"]["b1"]["boost"] = None
        f["cars"]["b2"]["boost"] = 0.0
    packet = build_stage1_packet(_record(p))
    ids = {e["id"]: e for e in packet["evidence"]}
    assert "E.focus.boost" not in ids
    assert any(u["id"] == "U.focus.boost" for u in packet["unknowns"])
    assert ids["E.teammate.boost"]["value"] == 0.0
    assert "freshness_unverified" in ids["E.teammate.boost"]["provenance"]


def test_abstained_decision_stays_abstained_without_fake_frame():
    p = scenario()
    p["frames"] = [f for f in p["frames"] if f["t"] < 0.5]
    rec = _record(p)
    assert rec["status"] == "abstain"
    packet = build_stage1_packet(rec)
    assert packet["status"] == "abstain"
    assert packet["evidence"] == []
    assert "frame_time_s" not in packet
    assert any(u["id"] == "U.frame" for u in packet["unknowns"])


@pytest.mark.parametrize("tamper", ["retrospective_id", "future_time", "nan_time", "future_event"])
def test_malicious_or_invalid_evidence_cannot_cross_stage1_boundary(tamper):
    rec = _record(_with_predecision_touch())
    if tamper == "retrospective_id":
        injected = copy.deepcopy(rec["evidence"][0])
        injected["id"] = "R.goal_within_5s"
        rec["evidence"].append(injected)
    elif tamper == "future_time":
        rec["evidence"][0]["source_time_s"] = T0 + 1.0
    elif tamper == "nan_time":
        rec["evidence"][0]["source_time_s"] = float("nan")
    else:
        event = next(e for e in rec["evidence"] if e["id"] == "C.touch.1")
        event["value"]["t"] = T0 + 0.1
    with pytest.raises(Stage1PacketError):
        build_stage1_packet(rec)


def test_context_citation_to_missing_or_retrospective_fact_fails_closed():
    rec = _record(_with_predecision_touch())
    rec["context"]["event_ids"].append("R.next_touch")
    with pytest.raises(Stage1PacketError):
        build_stage1_packet(rec)


def test_unanonymized_context_actor_id_is_not_sent_to_cloud_model():
    rec = _record(_with_predecision_touch())
    event = next(e for e in rec["evidence"] if e["id"] == "C.touch.1")
    event["value"]["playerId"] = "Steam:PRIVATE-ACCOUNT-ID"
    with pytest.raises(Stage1PacketError, match="Unanonymized"):
        build_stage1_packet(rec)


def test_untrusted_nonfinite_evidence_value_fails_closed():
    rec = _record()
    rec["evidence"][0]["value"] = [0.0, float("inf"), 5.0]
    with pytest.raises(Stage1PacketError, match="Non-JSON"):
        build_stage1_packet(rec)

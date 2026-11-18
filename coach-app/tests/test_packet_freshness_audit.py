"""Causal, conservative tests for resampled telemetry freshness auditing."""
from __future__ import annotations

import copy

import pytest

from evaluation.packet_freshness import audit_replay


def car(x=0.0, y=0.0, **extra):
    return {
        "x": x, "y": y, "z": 17.0,
        "velocity": [0.0, 0.0, 0.0],
        "rotation": [0.0, 0.0, 0.0],
        "boost": 30.0,
        **extra,
    }


def ball(x=0.0, **extra):
    return {
        "x": x, "y": 0.0, "z": 93.0,
        "velocity": [0.0, 0.0, 0.0],
        **extra,
    }


def payload():
    return {
        "source": "subtr-actor-native-replay",
        "players": [{"id": "blue1", "team": "blue"}, {"id": "orange1", "team": "orange"}],
        "frames": [
            {"t": 9.9, "ball": ball(), "cars": {"blue1": car(), "orange1": car(1)}},
            {"t": 10.0, "ball": ball(), "cars": {"blue1": car(), "orange1": car(1)}},
            {"t": 10.033, "ball": ball(5), "cars": {"blue1": car(), "orange1": car(1)}},
            {"t": 10.066, "ball": ball(6), "cars": {"blue1": car(), "orange1": car(1)}},
        ],
    }


def case(cid="c", t0=10.04, focus="blue1"):
    return {"case_id": cid, "t0": t0, "focus_player_id": focus}


def test_regular_30hz_frames_cannot_prove_native_actor_packet_freshness():
    report = audit_replay(payload(), [case()])
    assert report["release_gate"] == "native_actor_packet_freshness_not_established"
    assert report["rows"][0]["safe_to_claim_packet_freshness"] is False
    rows = report["rows"][0]["actors"]
    assert [r["actor"] for r in rows] == ["ball", "blue1"]
    assert rows[0]["sample_at_s"] == 10.033
    assert rows[0]["sample_age_s"] == 0.007
    assert all(r["sample_status"] == "sampled_state_available" for r in rows)
    assert all(r["native_packet_freshness"] == "unverifiable" for r in rows)
    assert all(r["reported_native_update_age_s"] is None for r in rows)
    assert report["summary"]["native_packet_freshness_unverifiable"] == 2


def test_stale_output_row_is_different_from_unknown_native_packet_age():
    report = audit_replay(payload(), [case(t0=10.2)], max_sample_age_s=0.05)
    for r in report["rows"][0]["actors"]:
        assert r["sample_at_s"] == 10.066
        assert r["sample_age_s"] == 0.134
        assert r["sample_status"] == "row_too_old"
        assert r["native_packet_freshness"] == "unverifiable"


def test_repeated_stationary_values_are_not_falsely_called_stale():
    report = audit_replay(payload(), [case()])
    r = report["rows"][0]["actors"][1]
    assert r["identical_sample_run_length"] == 3
    assert r["sample_status"] == "sampled_state_available"
    assert report["summary"]["identical_sample_runs_not_proof_of_staleness"] >= 1
    assert r["native_packet_freshness"] == "unverifiable"


def test_future_mutations_cannot_affect_a_predecision_audit():
    source = payload()
    baseline = audit_replay(source, [case()])
    altered = copy.deepcopy(source)
    altered["frames"][3]["ball"] = ball(9999)
    altered["frames"][3]["cars"]["blue1"] = car(9876)
    altered["frames"].append(
        {"t": 21.0, "ball": ball(10000), "cars": {"blue1": car(123)}})
    assert audit_replay(altered, [case()]) == baseline


def test_missing_or_demolished_cars_remain_unavailable():
    s = payload()
    s["frames"][2]["cars"].pop("blue1")
    missing = audit_replay(s, [case()])["rows"][0]["actors"][1]
    assert missing["sample_status"] == "actor_missing"
    assert missing["native_packet_freshness"] == "unverifiable"
    s["frames"][2]["cars"]["blue1"] = car(demolished=True)
    demolished = audit_replay(s, [case()])["rows"][0]["actors"][1]
    assert demolished["sample_status"] == "actor_demolished"


def test_optional_native_update_hint_is_only_self_report_and_never_certified():
    s = payload()
    s["frames"][2]["cars"]["blue1"]["nativeUpdateTimeS"] = 9.0
    old = audit_replay(s, [case()])["rows"][0]["actors"][1]
    assert old["reported_native_update_hint"] == "reported_old_unverified"
    assert old["reported_native_update_age_s"] == 1.04
    assert old["native_packet_freshness"] == "unverifiable"
    s["frames"][2]["cars"]["blue1"]["nativeUpdateTimeS"] = 10.02
    recent = audit_replay(s, [case()])["rows"][0]["actors"][1]
    assert recent["reported_native_update_hint"] == "reported_recent_unverified"
    assert recent["native_packet_freshness"] == "unverifiable"
    # No post-t0 or post-row source timestamp is accepted.
    s["frames"][2]["cars"]["blue1"]["nativeUpdateTimeS"] = 10.05
    future = audit_replay(s, [case()])["rows"][0]["actors"][1]
    assert future["reported_native_update_hint"] == "future_timestamp_invalid"
    assert future["reported_native_update_age_s"] is None
    assert future["native_packet_freshness"] == "unverifiable"


def test_no_prior_frame_never_uses_a_later_one():
    report = audit_replay(payload(), [case(t0=0.5)])
    for r in report["rows"][0]["actors"]:
        assert r["sample_at_s"] is None
        assert r["sample_status"] == "no_sample_at_or_before_t0"
    assert report["rows"][0]["safe_to_claim_packet_freshness"] is False


def test_no_focus_audits_all_rostered_players_without_guessing_identity():
    s = payload()
    report = audit_replay(s, [{"case_id": "c", "t0": 10.04}])
    assert report["rows"][0]["focus_scope"] == "all_rostered_players"
    assert [row["actor"] for row in report["rows"][0]["actors"]] == [
        "ball", "blue1", "orange1"]
    assert report["summary"]["native_packet_freshness_unverifiable"] == 3


def test_supports_evidence_packet_case_timing_fields():
    s = payload()
    result = audit_replay(s, [{
        "decision_case_id": "d1",
        "decision_time_s": 10.04,
        "focus_player": {"id": "orange1"},
    }])
    assert result["rows"][0]["case_id"] == "d1"
    assert result["rows"][0]["actors"][1]["actor"] == "orange1"


def test_invalid_clocks_ids_and_inputs_fail_closed():
    s = payload()
    with pytest.raises(ValueError, match="strictly increasing"):
        bad = copy.deepcopy(s)
        bad["frames"][2]["t"] = bad["frames"][1]["t"]
        audit_replay(bad, [case()])
    with pytest.raises(ValueError, match="invalid t0"):
        audit_replay(s, [case(t0=float("nan"))])
    with pytest.raises(ValueError, match="invalid t0"):
        audit_replay(s, [case(t0=True)])
    with pytest.raises(ValueError, match="focus player absent"):
        audit_replay(s, [case(focus="not_in_roster")])
    with pytest.raises(ValueError, match="Duplicate case_id"):
        audit_replay(s, [case(), case()])
    with pytest.raises(ValueError, match="max_sample_age"):
        audit_replay(s, [case()], max_sample_age_s=-1)
    with pytest.raises(ValueError, match="Duplicate player id"):
        bad = copy.deepcopy(s)
        bad["players"].append({"id": "blue1"})
        audit_replay(bad, [case()])

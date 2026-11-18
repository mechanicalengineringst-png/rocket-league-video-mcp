"""Regression tests for the Round 8 episode-to-reasoner causal firewall.

All fixtures synthetic. Passing proves packet invariants, not coaching quality.
"""
from __future__ import annotations

import copy
import json

import pytest

from coach_app.claim_verifier import verify_stage1_claims
from coach_app.episode_evidence import build_episode_evidence
from coach_app.episode_stage1 import SCHEMA, build_stage1_episode_packet
from coach_app.stage1_packet import Stage1PacketError
from tests.test_episode_evidence import episode_replay


def _episode(replay=None):
    return build_episode_evidence(
        episode_replay() if replay is None else replay,
        "b1", [2.0, 6.0, 10.0], 0.5, 10.0,
        label="TOP_SECRET_LABEL_FROM_OUTCOME",
    )


def _packet(replay=None):
    return build_stage1_episode_packet(_episode(replay))


def test_audited_episode_composes_all_three_node_packets_without_retro():
    packet = _packet()
    assert packet["schema"] == SCHEMA
    assert packet["tactical_merit_calculated"] is False
    assert packet["retrospective_present"] is False
    assert [n["node_id"] for n in packet["nodes"]] == ["N1", "N2", "N3"]
    assert [n["t0"] for n in packet["nodes"]] == [2.0, 6.0, 10.0]
    assert len(packet["relations"]) == 2
    assert len(packet["changes"]) > 0
    assert len(packet["possible_earlier_contributors"]) > 0
    for node in packet["nodes"]:
        inner = node["packet"]
        assert inner["cutoff_s"] == node["t0"]
        assert all(
            e["source_time_s"] is None or e["source_time_s"] <= node["t0"]
            for e in inner["evidence"]
        )
        assert "retrospective" not in inner
    serialized = json.dumps(packet, allow_nan=False)
    for forbidden in ("retrospective", "goal_context", "observed_action", "private-result",
                      "TOP_SECRET_LABEL_FROM_OUTCOME", '"selection"', '"source"', "scorerId"):
        if forbidden == "retrospective":
            # The boolean 'retrospective_present' is deliberate metadata.
            assert '"retrospective":' not in serialized
        else:
            assert forbidden not in serialized


def test_untrusted_selection_source_label_questions_and_notes_never_leave_boundary():
    episode = _episode()
    episode["label"] = "LEAK_THIS_FUTURE_WIN"
    episode["episode_id"] = "PRIVATE_REPLAY_ID"
    episode["nodes"][0]["snapshot"]["selection"] = {"scored_after_t0": "LEAK_THIS_FUTURE_WIN"}
    episode["nodes"][0]["snapshot"]["source"] = {"raw_player_id": "PRIVATE_PLAYER"}
    episode["changes"][0]["note"] = "PRIVATE_REPLAY_ID"
    episode["possible_earlier_contributors"][0]["question"] = "Because we saw the future goal"
    packet = build_stage1_episode_packet(episode)
    text = json.dumps(packet)
    for secret in ("LEAK_THIS_FUTURE_WIN", "PRIVATE_REPLAY_ID",
                   "PRIVATE_PLAYER", "Because we saw the future goal"):
        assert secret not in text


def test_deleting_or_rewriting_all_future_states_does_not_change_exact_packet():
    original = episode_replay()
    modified = copy.deepcopy(original)
    for frame in modified["frames"]:
        if frame["t"] > 10.0:
            frame["ball"]["x"] = -4000.0
            frame["cars"]["b1"]["boost"] = 100.0
    modified["events"] = [
        e for e in modified["events"] if e["t"] <= 10.0
    ] + [{"type": "goal_context", "t": 10.3, "scorerId": "b1"}]
    truncated = copy.deepcopy(original)
    truncated["frames"] = [f for f in truncated["frames"] if f["t"] <= 10.0]
    truncated["events"] = [e for e in truncated["events"] if e["t"] <= 10.0]
    assert _packet(original) == _packet(modified) == _packet(truncated)


def test_earlier_decision_is_not_revised_using_later_node_information():
    source = episode_replay()
    updated = copy.deepcopy(source)
    for frame in updated["frames"]:
        if 2.0 < frame["t"] <= 6.0:
            frame["cars"]["b1"]["boost"] = 100.0
    original, changed = _packet(source), _packet(updated)
    assert original["nodes"][0] == changed["nodes"][0]
    assert original["nodes"][1] != changed["nodes"][1]
    assert original["changes"] != changed["changes"]


def test_original_claim_verifier_operates_on_each_node_without_global_id_collision():
    packet = _packet()
    for node in packet["nodes"]:
        source = next(e for e in node["packet"]["evidence"] if e["id"] == "E.focus.boost")
        claim = {
            "claim_id": "focus-boost",
            "epistemic_type": "OBSERVED_FACT",
            "temporal_scope": "PRE_DECISION",
            "cited_evidence_ids": ["E.focus.boost"],
            "predicate_checks": [{
                "evidence_id": "E.focus.boost", "value_path": [],
                "relation": "eq", "stated_value": source["value"],
            }],
        }
        report = verify_stage1_claims(node["packet"], [claim])
        assert report["all_structural_checks_passed"]
        assert report["results"][0]["status"] != "rejected"
    # Use N1/E.focus.boost, N2/E.focus.boost ... to disambiguate
    assert packet["nodes"][0]["t0"] != packet["nodes"][1]["t0"]


def test_missing_decision_frame_abstains_and_cannot_recreate_synthetic_facts():
    r = episode_replay()
    r["frames"] = [f for f in r["frames"] if not 5.7 <= f["t"] <= 6.0]
    packet = _packet(r)
    assert packet["status"] == "partial"
    assert packet["nodes"][1]["status"] == "abstain"
    assert packet["nodes"][1]["packet"]["evidence"] == []
    assert any(u["id"] == "N2/U.frame" for u in packet["unknowns"])


@pytest.mark.parametrize("kind", ["future_timestamp", "wrong_node_cutoff", "future_timeline",
                                  "raw_player_id", "retrospective_change_ref",
                                  "unverified_hypothesis_ref"])
def test_tampered_episode_is_rejected_before_ai_uses_it(kind):
    episode = _episode()
    if kind == "future_timestamp":
        episode["nodes"][0]["snapshot"]["evidence"][0]["source_time_s"] = 12.0
    elif kind == "wrong_node_cutoff":
        episode["nodes"][0]["information_cutoff_s"] = 10.0
    elif kind == "future_timeline":
        episode["timeline"][0]["t"] = 11.0
    elif kind == "raw_player_id":
        episode["timeline"][0]["playerId"] = "Steam/private_user_123"
    elif kind == "retrospective_change_ref":
        episode["changes"][0]["refs"] = ["N1/R.goal_within_5s", "N2/E.focus.boost"]
    else:
        episode["possible_earlier_contributors"][0]["evidence_refs"] = ["R.goal_within_5s"]
    with pytest.raises(Stage1PacketError):
        build_stage1_episode_packet(episode)


def test_missing_change_sources_remain_unknown_not_fake_exact_values():
    r = episode_replay()
    for frame in r["frames"]:
        if 5.5 <= frame["t"] <= 6.0:
            frame["cars"]["b1"]["boost"] = None
            frame["cars"]["b2"]["x"] = float("nan")
    packet = _packet(r)
    ids = {e["id"] for e in packet["changes"]}
    assert "D.N1-N2.focus.boost" not in ids
    unknown = {x["id"]: x for x in packet["unknowns"]}
    assert "UD.N1-N2.focus.boost" in unknown
    assert unknown["UD.N1-N2.focus.boost"]["refs"] == ["N2/U.focus.boost"]
    assert "N2/U.focus.boost" in unknown


def test_stage1_packet_does_not_claim_that_derived_changes_are_verified_math():
    packet = _packet()
    for change in packet["changes"]:
        assert change["verification"] == "derived_value_needs_independent_math_check"
        assert 0.5 <= change["known_at_s"] <= 10.0
        assert all(ref.startswith(("N1/E.", "N2/E.", "N3/E.")) for ref in change["refs"])
    assert all(h["status"] == "hypothesis_unverified"
               for h in packet["possible_earlier_contributors"])

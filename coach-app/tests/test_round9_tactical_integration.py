"""Round 9 cross-agent acceptance: Claude tactical menu -> verified coach layer.

These are synthetic/contract tests, not SSL/GC2 tactical quality ratings.
"""
from __future__ import annotations

import copy
import json

import pytest

from coach_app.claim_verifier import verify_stage1_claims
from coach_app.coach_lesson import build_lesson_from_episode, lookup_episode_evidence
from coach_app.episode_evidence import build_episode_evidence
from coach_app.episode_stage1 import build_stage1_episode_packet
from coach_app.tactical_coach_adapter import SCHEMA, build_verified_tactical_context
from tests.test_tactical_options import FIRST_MAN, LATE_UNCOVERED, replay


def episode(cars=FIRST_MAN):
    return build_episode_evidence(replay(copy.deepcopy(cars)), "b1", [4., 8., 11.], 1., 11.)


def proposed_claim(evidence_ref, tactical_claim_ids):
    return {
        "claim_id": "tactical-proposal",
        "node_id": "N3",
        "section": "alternative",
        "epistemic_type": "TACTICAL_INFERENCE",
        "temporal_scope": "PRE_DECISION",
        "cited_evidence_ids": [evidence_ref],
        "tactical_claim_ids": tactical_claim_ids,
        "predicate_checks": [],
        "text": "This option could be considered, but the timing estimate alone does not determine merit.",
    }


def proposed_lesson(claim):
    return {"schema": "CoachDraftV0", "assessment": "tradeoff", "claims": [claim]}


def test_covered_aggression_shows_as_one_uncalibrated_option_not_expert_grade():
    e = episode()
    out = build_lesson_from_episode(e)
    assert out["schema"] == "CoachLessonV0"
    assert out["assessment"]["grade"] == "undetermined"
    menu = out["tactical_options"]
    assert menu["schema"] == SCHEMA
    assert menu["node_id"] == "N3" and menu["decision_time_s"] == 11.
    assert menu["status"] in ("ok", "partial")
    assert menu["calibration"]["status"] == "uncalibrated_rule_hypothesis"
    assert menu["calibration"]["expert_validated"] is False
    assert menu["calibration"]["picks_single_best"] is False
    assert len(menu["options"]) == 9
    ch = next(x for x in menu["options"] if x["action"] == "immediate_challenge")
    assert ch["strategic_stance"] == "defensible"
    assert ch["physical_feasibility"] == "yes"
    assert len(menu["defensible_options"]) > 1
    assert menu["validation"]["semantic_tactical_accuracy_verified"] is False
    assert not menu["validation"]["retrospective_used"]


def test_late_uncovered_challenge_is_flagged_as_hypothesis_without_blame():
    lesson = build_lesson_from_episode(episode(LATE_UNCOVERED))
    opts = {o["action"]: o for o in lesson["tactical_options"]["options"]}
    assert opts["immediate_challenge"]["strategic_stance"] == "questionable"
    assert opts["immediate_challenge"]["severe_limit_claims"]
    assert opts["shadow_delay"]["strategic_stance"] in ("defensible", "defensible_with_conditions")
    assert lesson["assessment"]["grade"] == "undetermined"
    assert "mistake" not in json.dumps(lesson["tactical_options"]).lower()


def test_every_tactical_claim_is_a_verified_source_link_and_inspectable():
    e = episode()
    packet = build_stage1_episode_packet(e)
    menu = build_verified_tactical_context(packet)
    node_packet = packet["nodes"][-1]["packet"]
    assert menu["validation"]["rejected_tactical_claims"] == 0
    assert len(menu["claims"]) >= 5
    assert all(c["node_id"] == "N3" and c["semantic_accuracy_verified"] is False
               for c in menu["claims"])
    for c in menu["claims"]:
        assert c["evidence_refs"]
        assert all(x.startswith("N3/") for x in c["evidence_refs"])
        assert c["review_status"] != "rejected"
    first = next(c for c in menu["claims"] if c["evidence_refs"][0].startswith("N3/E."))
    lookup = lookup_episode_evidence(e, [first["evidence_refs"][0]])
    assert lookup["records"][0]["id"] == first["evidence_refs"][0]
    assert lookup["retrospective_exposed"] is False
    raw = [c for c in __import__("coach_app.tactical_options", fromlist=["analyze_tactical_options"])
           .analyze_tactical_options(packet)["claims"]]
    report = verify_stage1_claims(node_packet, raw)
    assert report["all_structural_checks_passed"]


def test_model_can_link_specific_tactical_claim_only_to_its_actual_source():
    e = episode()
    menu = build_lesson_from_episode(e)["tactical_options"]
    source_claim = next(c for c in menu["claims"] if c["epistemic_type"] == "TACTICAL_INFERENCE"
                        and c["evidence_refs"] and all(x.startswith("N3/E.") for x in c["evidence_refs"])
                        and "N3/E.focus.boost" not in c["evidence_refs"])
    valid = proposed_claim(source_claim["evidence_refs"][0], [source_claim["claim_id"]])
    lesson = build_lesson_from_episode(e, model_draft=proposed_lesson(valid))
    assert lesson["validation"]["accepted_model_claims"] == 1
    accepted = next(c for c in lesson["claims"] if c["author"] == "model_proposal")
    assert accepted["tactical_claim_ids"] == [source_claim["claim_id"]]
    assert accepted["review_status"] == "needs_semantic_review"
    assert lesson["assessment"]["status"] == "model_hypothesis_not_expert_validated"

    wrong_source = proposed_claim("N3/E.focus.boost", [source_claim["claim_id"]])
    bad = build_lesson_from_episode(e, model_draft=proposed_lesson(wrong_source))
    assert bad["validation"]["accepted_model_claims"] == 0
    assert bad["validation"]["rejected_model_claims"]
    assert bad["assessment"]["grade"] == "undetermined"


@pytest.mark.parametrize("bad_tactical_ids", [["N3.c999"], ["N2.c1"], [42], [{"unhashable": "value"}]])
def test_model_cannot_invent_or_borrow_tactical_claim_ids(bad_tactical_ids):
    lesson = build_lesson_from_episode(episode(), model_draft=proposed_lesson(
        proposed_claim("N3/E.focus.boost", bad_tactical_ids)
    ))
    assert lesson["validation"]["accepted_model_claims"] == 0
    assert lesson["validation"]["rejected_model_claims"]
    assert lesson["assessment"]["grade"] == "undetermined"


def test_future_goals_never_change_options_or_earlier_factors():
    r = replay(copy.deepcopy(LATE_UNCOVERED))
    original = build_episode_evidence(r, "b1", [4., 8., 11.], 1., 11.)
    future = copy.deepcopy(r)
    future["events"].append({"type": "goal_context", "t": 11.9,
                             "scorerId": "o1", "scoringTeam": "orange"})
    for frame in future["frames"]:
        if frame["t"] > 11.:
            frame["ball"]["x"] = 4096.
            frame["cars"]["b1"]["boost"] = 100.
    changed = build_episode_evidence(future, "b1", [4., 8., 11.], 1., 11.)
    assert build_lesson_from_episode(original) == build_lesson_from_episode(changed)


def test_unknown_primary_frame_produces_no_tactical_options():
    r = replay(copy.deepcopy(FIRST_MAN))
    r["frames"] = [f for f in r["frames"] if f["t"] < 10.7 or f["t"] > 11.]
    e = build_episode_evidence(r, "b1", [4., 8., 11.], 1., 11.)
    lesson = build_lesson_from_episode(e)
    assert lesson["decision"]["status"] == "abstain"
    assert lesson["tactical_options"]["options"] == []
    assert lesson["tactical_options"]["claims"] == []
    assert lesson["assessment"]["grade"] == "undetermined"

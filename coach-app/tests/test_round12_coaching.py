"""Round 12 coaching pipeline: SYNTHETIC scenarios through the real pipeline, plus contract tests.

The synthetic scenarios test the reasoning scheme and its stage separation, not tactical accuracy.
"""
from __future__ import annotations

import copy
import json

import pytest

from coach_app import reasoner_contract as rc
from coach_app.coach_report import build_coaching_report, coach_moment, prefix
from coach_app.coaching_findings import check_finding_numbers
from coach_app.contact_geometry import MODEL, destination_zones, race_after_contact, summarise, zone_of
from coach_app.moment_ranking import rank, score
from coach_app.situation_rationale import SituationRationaleError, analyze_situation
from coach_app.situations import classify_frame, discover_situations
from coach_app.synthetic_scenarios import T0, build, car, materialise, scenarios

SC = {s["name"]: s for s in scenarios()}


def run(name, future=None, **kw):
    return coach_moment(materialise(SC[name], future), "b1", T0, **kw)


def stage_a(f):
    return {k: v for k, v in f.items() if k != "retrospective"}


# ---------- difficult scenarios (synthetic) ----------

@pytest.mark.parametrize("name", [n for n, s in SC.items() if len(s["futures"]) >= 1])
def test_stage_a_is_identical_whatever_happens_next(name):
    base = stage_a(run(name))
    for fut in SC[name]["futures"]:
        assert stage_a(run(name, fut)) == base, fut


def test_backboard_benchmark_ground_prefers_restraint_and_names_the_exposure():
    f = run("backboard_benchmark_ground")
    assert f["situation"]["class"] == "first_defender" and f["status"] == "ok"
    st = {a["action"]: a for a in f["alternatives"]}
    assert st["immediate_challenge"]["status"] in ("refuted", "contested")
    assert {"shadow_delay", "goal_side_hold"} & {a for a, x in st.items() if x["status"] == "supported"}
    ctx = {c["condition"]: c for c in f["decision_context"]}
    assert ctx["teammate_covers"]["status"] == "fails" and "s to get goal-side" in ctx["teammate_covers"]["reading"]
    risks = " ".join(r["text"] for r in st["immediate_challenge"]["risks"])
    assert "goal-side" in risks                                   # what losing the challenge exposes
    assert f["assumptions"]["unobservable"]                      # contact direction etc. named as unknowable


def test_backboard_aerial_variant_abstains_instead_of_simulating():
    f = run("backboard_benchmark_aerial")
    assert f["kind"] == "observation_only" and f["alternatives"] == []
    assert "not modelled" in f["interpretation"]["text"]
    assert f["retrospective"]["assessment"]["verdict"] == "not_assessed"


def test_sound_restraint_is_not_blamed_for_the_goal():
    f = run("restraint_then_conceded", "shadow_then_their_goal")
    b = f["retrospective"]
    assert b["outcome"]["goal"]["scored_by"] == "opponents"
    assert b["assessment"]["verdict"] == "sound"
    assert "does not make the choice wrong" in b["assessment"]["text"]
    assert run("restraint_then_conceded", "shadow_then_save")["retrospective"]["assessment"]["verdict"] == "sound"


def test_poor_decision_that_works_is_still_flagged():
    f = run("challenge_works_anyway", "challenge_then_our_goal")
    b = f["retrospective"]
    assert b["outcome"]["goal"]["scored_by"] == "own team"
    assert b["assessment"]["verdict"] in ("questionable", "risky")
    assert "worked out this time" in b["assessment"]["text"] or b["assessment"]["verdict"] == "risky"


def test_level_contest_is_not_forced_into_one_answer():
    f = run("level_contest_with_cover")
    decisive = {d["condition"] for d in f["assumptions"]["decisive"]}
    assert decisive & {"focus_first", "carrier_first"}
    assert sum(a["status"] in ("supported", "conditional") for a in f["alternatives"]) >= 3
    assert "currently within error" in f["interpretation"]["text"]


def test_excellent_aggression_is_recognised_even_when_a_goal_follows():
    f = run("covered_first_man_aggression", "challenge_then_their_goal")
    assert "immediate_challenge" in {a["action"] for a in f["alternatives"] if a["status"] == "supported"}
    assert f["retrospective"]["assessment"]["verdict"] == "sound"


def test_off_ball_second_man_has_its_own_vocabulary_and_boost_route():
    f = run("second_man_low_boost", "took_pads")
    assert f["situation"]["class"] == "second_man_support"
    acts = {a["action"] for a in f["alternatives"]}
    assert {"support_behind", "aggressive_follow_up", "boost_while_teammate_plays", "challenge_as_well"} <= acts
    assert "Q.boost_then_cover_s" in f["quantities"]
    assert f["retrospective"]["observed_action"]["label"] == "boost_while_teammate_plays"


def test_teammate_cover_uncertainty_is_named_as_the_deciding_unknown():
    f = run("teammate_cover_borderline")
    unc = {c["condition"] for c in f["decision_context"] if c["status"] in ("within_error", "unknown")}
    dec = {d["condition"] for d in f["assumptions"]["decisive"]}
    assert "teammate_covers" in unc | dec


def test_missing_focus_telemetry_abstains():
    f = run("missing_focus_telemetry")
    assert f["status"] == "no_supported_situation" and f["kind"] == "observation_only"


def test_recovery_route_compares_direct_small_pads_and_big_boost_with_times():
    f = run("recovery_route")
    assert f["situation"]["class"] == "recovery_and_boost"
    q = f["quantities"]
    assert {"Q.direct_return_s", "Q.big_boost_detour_extra_s", "Q.small_pads_on_route"} <= set(q)
    assert {a["action"] for a in f["alternatives"]} == {"return_direct", "small_pad_route", "big_boost_detour"}
    assert run("recovery_route", "big_boost")["retrospective"]["observed_action"]["label"] == "big_boost_detour"


def test_possession_with_open_lane_supports_the_shot_and_labels_it():
    f = run("possession_open_lane", "shot")
    assert "shoot_now" in {a["action"] for a in f["alternatives"] if a["status"] == "supported"}
    assert f["retrospective"]["observed_action"]["label"] == "shoot_now"


@pytest.mark.parametrize("name", list(SC))
def test_every_number_is_traced_and_claims_verify(name):
    f = run(name)
    if f.get("status") == "no_supported_situation":
        return
    assert check_finding_numbers(f) == []
    assert f["validation"]["claims_structurally_valid"] is True
    for v in f["numbers"].values():
        assert all(r.startswith(("E.", "Q.")) for r in v["refs"])


@pytest.mark.parametrize("name", list(SC))
def test_stage_a_never_mentions_outcomes_or_probabilities(name):
    f = run(name)
    text = json.dumps(stage_a(f)).lower()
    for w in ("scored", "conceded", "probability", "likely", "%"):
        assert w not in text


# ---------- leakage guards ----------

def test_situation_rationale_refuses_a_prefix_that_extends_past_t0():
    sc = SC["level_contest_with_cover"]
    r = materialise(sc)
    s = classify_frame(next(f for f in r["frames"] if abs(f["t"] - T0) < 1e-6), r["players"], "b1").to_dict()
    from coach_app.coach_report import analyze_moment
    it = analyze_moment(r, "b1", s)
    packet = {"schema": "Stage1EpisodePacketV0", "retrospective_present": False, "nodes": [{"node_id": "N1", "is_primary": True,
                                                                                           "packet": it["packet"]}]}
    with pytest.raises(SituationRationaleError):
        analyze_situation(packet, r, s)                     # full replay, not a prefix


def test_situations_depend_only_on_the_past():
    r = materialise(SC["level_contest_with_cover"])
    a = [x.to_dict() for x in discover_situations(r, "b1", end=T0)]
    r2 = copy.deepcopy(r)
    for fr in r2["frames"]:
        if fr["t"] > T0:
            fr["ball"]["x"] += 3000
    r2["events"].append({"type": "goal_context", "t": T0 + 2, "scoringTeam": "orange"})
    assert [x.to_dict() for x in discover_situations(r2, "b1", end=T0)] == a


def test_dead_ball_after_goal_is_not_analysed():
    r = materialise(SC["level_contest_with_cover"])
    r["events"].append({"type": "goal_context", "t": T0 - 2.0, "scoringTeam": "orange"})
    assert not [s for s in discover_situations(r, "b1") if T0 - 2.0 <= s.t0 <= T0 + 1]


def test_ranking_uses_no_future_information():
    r = materialise(SC["level_contest_with_cover"])
    s = classify_frame(next(f for f in r["frames"] if abs(f["t"] - T0) < 1e-6), r["players"], "b1").to_dict()
    from coach_app.coach_report import analyze_moment
    it = analyze_moment(r, "b1", s)
    sc = score(it["situation"], it["rationale"], 1)
    assert sc["uses_future"] is False and sc["is_merit"] is False
    assert rank([it], 3)[0]["salience"]["score"] == sc["score"]


def test_prefix_drops_future_frames_and_events():
    r = materialise(SC["restraint_then_conceded"], "shadow_then_their_goal")
    p = prefix(r, T0)
    assert max(f["t"] for f in p["frames"]) <= T0 and all(e["t"] <= T0 for e in p["events"])


# ---------- full report ----------

def test_report_on_a_synthetic_replay_is_well_formed():
    rep = build_coaching_report(materialise(SC["restraint_then_conceded"], "shadow_then_their_goal"), "b1", max_findings=3)
    assert rep["schema"] == "CoachingReportV1" and rep["experimental"] is True and rep["expert_validated"] is False
    assert rep["method"]["model_called"] is False and rep["method"]["ranking_uses_future"] is False
    for f in rep["findings"]:
        assert f["situation"]["selection"]["is_merit"] is False
    assert "players" not in json.dumps(rep) or "player_id" not in json.dumps(rep)


def test_report_input_validation():
    r = materialise(SC["level_contest_with_cover"])
    with pytest.raises(ValueError):
        build_coaching_report(r, "nobody")
    with pytest.raises(ValueError):
        build_coaching_report(r, "b1", max_findings=0)


# ---------- reasoner contract (mocked transports only; NOT evidence of live model quality) ----------

def _finding():
    f = run("restraint_then_conceded", "shadow_then_their_goal")
    assert f["status"] == "ok"
    return f


def test_no_transport_means_no_model_call_and_deterministic_text():
    out = rc.run_reasoner(_finding())
    assert out["model_called"] is False and out["stage_a"]["mode"] == "deterministic"


def test_stage_a_request_contains_no_retrospective_material():
    req = rc.build_stage_a_request(_finding())
    s = json.dumps(req).lower()
    assert "retrospective" not in s and "observed_action" not in s and "goal_context" not in s
    assert "scored" not in s and "outcome" not in s


def _ok_a(req):
    cid = req["conditions"][0]["id"]
    return {"schema": rc.SCHEMA_A_RESP, "finding_id": req["finding_id"], "cited_conditions": [cid],
            "interpretation": "The opponent had the ball and your teammate was not back, so giving ground keeps the play in front of you.",
            "takeaway": "Before committing, check whether your teammate is goal-side."}


def test_valid_mock_response_is_accepted_but_marked_unverified():
    def transport(msg):
        if msg["input"]["schema"] == rc.SCHEMA_A_REQ:
            return _ok_a(msg["input"])
        return {"schema": rc.SCHEMA_B_RESP, "finding_id": msg["input"]["finding_id"],
                "feedback": "Shadowing kept you goal-side while help arrived; that read holds regardless of what followed."}
    out = rc.run_reasoner(_finding(), transport)
    assert out["stage_a"]["mode"] == "model_validated" and "not semantically verified" in out["stage_a"]["note"]
    assert out["stage_b"]["mode"] == "model_validated"


@pytest.mark.parametrize("bad_text, why", [
    ("You had a 70% chance to win that ball.", "probability"),
    ("The opponent was 1234 uu away so you should hold.", "numbers"),
    ("Holding was right and the opponents scored anyway.", "outcomes"),
    ("You chose to shadow, which kept you goal-side.", "what the player did"),
    ("A flip reset would have beaten them to it.", "mechanic"),
])
def test_stage_a_validator_rejects_fabrication_and_leakage(bad_text, why):
    f = _finding()
    req = rc.build_stage_a_request(f)
    resp = _ok_a(req)
    resp["interpretation"] = bad_text + " " + resp["interpretation"]
    errs = rc.validate_stage_a_response(req, resp)
    assert errs, why
    out = rc.run_reasoner(f, lambda m: resp if m["input"]["schema"] == rc.SCHEMA_A_REQ else None)
    assert out["stage_a"]["mode"] == "deterministic" and out["stage_a"]["rejections"]


def test_stage_a_validator_rejects_unknown_condition_ids_and_wrong_finding():
    req = rc.build_stage_a_request(_finding())
    resp = _ok_a(req)
    resp["cited_conditions"] = ["opponent_was_tired"]
    assert rc.validate_stage_a_response(req, resp)
    resp = _ok_a(req)
    resp["finding_id"] = "F99"
    assert rc.validate_stage_a_response(req, resp)
    assert rc.validate_stage_a_response(req, "not json") == ["Response is not a CoachReasonerStageAResponseV1 object."]


@pytest.mark.parametrize("fb", [
    "That was a mistake because the goal went in right after.",
    "You should have challenged; they scored.",
    "There was a 40 percent chance of a save.",
])
def test_stage_b_validator_rejects_outcome_grading_and_contradiction(fb):
    f = _finding()
    req = rc.build_stage_b_request(f, {"interpretation": "x", "takeaway": "y"})
    assert req["verdict"] == "sound"
    assert rc.validate_stage_b_response(req, {"schema": rc.SCHEMA_B_RESP, "finding_id": f["finding_id"], "feedback": fb})


def test_observation_only_findings_are_never_sent_to_a_model():
    f = run("backboard_benchmark_aerial")
    called = []
    out = rc.run_reasoner(f, lambda m: called.append(m))
    assert not called and out["model_called"] is False


# ---------- contact model ----------

def test_contact_model_is_calibrated_and_aerials_are_unsupported():
    assert MODEL["k"] and MODEL["cone_half_deg"]
    z = destination_zones((0, -1500), (0, 1400), (0, -1000, 93), (0, 0), "blue")
    assert z["status"] == "ok" and sum(z["zone_counts"].values()) == z["sampled_directions"]
    assert destination_zones((0, -1500), (0, 1400), (0, -1000, 900), (0, 0), "blue")["status"] == "unsupported"
    assert zone_of(0, -4500, "blue") == "own_goal_area" and zone_of(0, -4500, "orange") == "opponent_goal_area"


def test_next_ball_race_is_worded_as_counts_not_probabilities():
    cars = {"b1": car(0, -1500, vy=1400), "b2": car(0, -4000), "o1": car(0, 500), "o2": car(2000, 2000)}
    r = race_after_contact(cars, {"b1": "blue", "b2": "blue", "o1": "orange", "o2": "orange"}, "b1", (0, -1000, 93), 0.0,
                           (0, 1400), (0, 0), "blue")
    s = summarise(r)
    assert s and "of 7 modelled contact directions" in s and "%" not in s


def test_api_endpoint_is_opt_in_and_separate():
    from fastapi.testclient import TestClient
    from coach_app.main import app
    c = TestClient(app)
    r = materialise(SC["level_contest_with_cover"])
    for fr in r["frames"]:
        fr["t"] = float(fr["t"])
    res = c.post("/api/coach/coaching-report-v1", json={"replay": r, "player_id": "b1", "max_findings": 2})
    assert res.status_code == 200, res.text[:300]
    body = res.json()
    assert body["schema"] == "CoachingReportV1" and body["method"]["model_called"] is False
    assert c.post("/api/coach/coaching-report-v1", json={"replay": r, "player_id": "zz"}).status_code == 422


def test_build_helper_keeps_states_consistent():
    r = build({"b1": car(0, 0, vy=100), "b2": car(0, -4000), "o1": car(0, 3000), "o2": car(1000, 3000)}, (500, 500, 93))
    a = next(f for f in r["frames"] if abs(f["t"] - (T0 - 1)) < 1e-6)
    assert abs(a["cars"]["b1"]["y"] - (-100)) < 1e-6


def test_async_reasoner_uses_the_same_validation():
    import asyncio

    async def transport(msg):
        if msg["input"]["schema"] == rc.SCHEMA_A_REQ:
            r = _ok_a(msg["input"])
            r["takeaway"] = "You had a 90% chance here."
            return r
        return {"schema": rc.SCHEMA_B_RESP, "finding_id": msg["input"]["finding_id"], "feedback": "Fine read; it held up."}
    out = asyncio.run(rc.run_reasoner_async(_finding(), transport))
    assert out["stage_a"]["mode"] == "deterministic" and out["stage_a"]["rejections"]

"""DecisionEvidenceV0 (Round 7). Synthetic fixtures only; they check information rules, not tactics."""
from __future__ import annotations

import copy
import math

from coach_app.decision_evidence import SCHEMA, build_decision_evidence, check_citations, resolve
from tests.test_defender_choices import scenario

T0 = 1.0


def record(p, t0=T0):
    return build_decision_evidence(p, t0, "b1", selection={"rule": "test"})


def pre_decision(rec):
    """Everything an explanation may cite as known at t0."""
    return {k: rec[k] for k in ("evidence", "unknowns", "context", "frame_time_s", "status")}


def with_events(p):
    p = copy.deepcopy(p)
    p["events"] += [{"type": "touch", "t": 0.4, "playerId": "o1", "touchKind": "hard_hit"},
                    {"type": "boost_pickups", "t": 0.6, "playerId": "b2", "padType": "small"},
                    {"type": "goal_context", "t": 2.4, "scorerId": "o1"}]
    return p


# ---------- future invariance ----------

def test_rewriting_or_deleting_the_future_leaves_pre_decision_evidence_unchanged():
    base = with_events(scenario(future="challenge"))
    rewritten = copy.deepcopy(base)
    for f in rewritten["frames"]:
        if f["t"] > T0:
            f["ball"] = {"x": 4000.0, "y": 5000.0, "z": 1500.0, "velocity": [-2000.0, 0.0, 300.0]}
            for c in f["cars"].values():
                c.update(x=-3000.0, y=-3000.0, boost=0.0)
    rewritten["events"] = [e for e in rewritten["events"] if e["t"] <= T0] + [
        {"type": "touch", "t": 1.1, "playerId": "o2"}, {"type": "demolition", "t": 1.3, "attackerId": "o2", "victimId": "b2"}]
    deleted = dict(copy.deepcopy(base), frames=[f for f in base["frames"] if f["t"] <= T0],
                   events=[e for e in base["events"] if e["t"] <= T0])
    a, b, c = record(base), record(rewritten), record(deleted)
    assert pre_decision(a) == pre_decision(b) == pre_decision(c)
    assert a["retrospective"] != b["retrospective"]          # only the retrospective block may differ


def test_every_pre_decision_item_is_timed_at_or_before_t0():
    rec = record(with_events(scenario()))
    assert all(e["source_time_s"] is None or e["source_time_s"] <= T0 for e in rec["evidence"])
    assert not any(e["id"].startswith("R.") for e in rec["evidence"])
    retro = rec["retrospective"]
    assert all(retro[k]["finalized_through_s"] > T0 for k in ("observed_action", "next_touch", "goal_within_5s"))


def test_touch_attributes_computed_from_later_frames_are_dropped():
    rec = record(with_events(scenario()))
    touch = resolve(rec, "C.touch.1")
    assert touch["value"] == {"t": 0.4, "playerId": "opponent_1"} and "touchKind" not in touch["value"]


# ---------- boost: unknown and finite ----------

def test_missing_boost_is_unknown_and_zero_boost_is_a_finite_fact():
    p = scenario()
    for f in p["frames"]:
        f["cars"]["b1"]["boost"] = None
        f["cars"]["b2"]["boost"] = 0.0
    rec = record(p)
    assert resolve(rec, "E.focus.boost") is None
    assert any(u["id"] == "U.focus.boost" for u in rec["unknowns"])
    assert resolve(rec, "E.teammate.boost")["value"] == 0.0
    assert "freshness_unverified" in resolve(rec, "E.teammate.boost")["provenance"]
    reach = resolve(rec, "E.reach.focus")["value"]
    assert any("boost unknown" in u for u in reach["unknowns"])     # both bounds, never assumed full or empty


def test_out_of_range_boost_is_unknown_not_clipped():
    p = scenario()
    for f in p["frames"]:
        f["cars"]["b1"]["boost"] = 255.0
    assert any(u["id"] == "U.focus.boost" for u in record(p)["unknowns"])


# ---------- missing or invalid telemetry ----------

def test_invalid_coordinates_make_the_car_unknown_and_block_derived_claims():
    p = scenario()
    for f in p["frames"]:
        f["cars"]["o1"]["x"] = float("nan")
        f["cars"]["b2"]["y"] = 99999.0
    rec = record(p)
    ids = {e["id"] for e in rec["evidence"]}
    assert not {"E.opponent_1.position", "E.teammate.position", "E.reach.opponent_1"} & ids
    unk = {u["id"] for u in rec["unknowns"]}
    assert {"U.opponent_1.state", "U.teammate.state", "U.reach.opponent_1", "U.roles.own", "U.roles.opponents"} <= unk
    assert "E.cover.teammate" not in ids


def test_no_frame_near_t0_abstains():
    p = scenario()
    p["frames"] = [f for f in p["frames"] if f["t"] < 0.5]
    rec = record(p)
    assert rec["status"] == "abstain" and rec["evidence"] == []


def test_unchanged_state_is_flagged_as_possibly_stale():
    rec = record(scenario())                       # o2 never moves in the fixture
    assert "stale_possible" in resolve(rec, "E.opponent_2.position")["provenance"]
    assert resolve(rec, "E.opponent_2.state_age")["value"] >= 0.9


# ---------- stable, real source references ----------

def test_evidence_ids_are_stable_unique_and_resolve_to_real_values():
    a, b = record(with_events(scenario())), record(with_events(scenario()))
    ids = [e["id"] for e in a["evidence"]]
    assert ids == [e["id"] for e in b["evidence"]] and len(ids) == len(set(ids))
    for e in a["evidence"]:
        assert resolve(a, e["id"]) is e and e["value"] is not None or e["id"] == "E.cover.teammate"
    pos = resolve(a, "E.focus.position")["value"]
    raw = next(f for f in reversed(scenario()["frames"]) if f["t"] <= T0)["cars"]["b1"]
    assert pos == [raw["x"], raw["y"], raw["z"]]


def test_citation_check_rejects_unknown_retrospective_and_invented_ids():
    p = scenario()
    for f in p["frames"]:
        f["cars"]["b1"]["boost"] = None
    rec = record(p)
    assert check_citations(rec, ["E.ball.position", "E.reach.focus"]) == []
    problems = " ".join(check_citations(rec, ["U.focus.boost", "R.observed_action", "E.focus.vision"]))
    assert "unknown" in problems and "retrospective" in problems and "does not exist" in problems


def test_record_states_what_cannot_be_observed_and_has_no_merit_fields():
    rec = record(scenario())
    assert rec["schema"] == SCHEMA
    assert any("could see" in n for n in rec["not_observable"])
    flat = str(rec["evidence"]).lower()
    assert "probab" not in flat and "verdict" not in flat and "mistake" not in flat
    roles = resolve(rec, "E.roles.own")["value"]
    assert roles["confidence"] in ("estimate", "ambiguous")
    assert not any(isinstance(e["value"], float) and math.isinf(e["value"]) for e in rec["evidence"])


def test_both_teammates_out_of_reach_gives_unknown_roles_not_nan():
    """Real-replay regression: inf - inf produced a NaN role gap."""
    from coach_app import decision_evidence as de
    from coach_app.reachability import Reach

    class St:
        t0, margin_s, margin_interval = T0, None, (None, None)

    b = de._Builder()
    slots = {"b1": "focus", "b2": "teammate", "o1": "opponent_1", "o2": "opponent_2"}
    far = Reach("out_of_horizon")
    near = Reach("ok", t_min=0.5)
    de._roles(b, St(), slots, {"b1": far, "b2": far, "o1": near, "o2": far})
    assert any(u["id"] == "U.roles.own" for u in b.unknowns)
    own = [e for e in b.evidence if e["id"] == "E.roles.own"]
    assert own == []
    opp = next(e for e in b.evidence if e["id"] == "E.roles.opponents")
    assert opp["value"]["gap_s"] is None and opp["value"]["first"] == "opponent_1"

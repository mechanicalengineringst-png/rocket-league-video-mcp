"""Round 15: CoachingReviewV1 (few moments, firm reads only, outcome kept apart).

Real-data tests use tests/fixtures_real_slice.json.gz: the first 130 s of a public subtr-actor test replay,
decoded by the app's own parser, with player names and IDs replaced (p1..p4). Synthetic scenarios test the
reasoning guards only; neither says anything about tactical accuracy at high rank.
"""
from __future__ import annotations

import copy
import gzip
import json
import re
from pathlib import Path

import pytest

from coach_app.coaching_review import (BUDGET, MAX_MOMENTS, NUM, build_moment, build_review, review_moment_at)
from coach_app.synthetic_scenarios import T0, materialise, scenarios

FIX = Path(__file__).parent / "fixtures_real_slice.json.gz"
SC = {s["name"]: s for s in scenarios()}
BANNED = re.compile(r"%|probab|likel|\bhabit|\btend(s|ency)? to\b|\balways\b|\bcaused?\b|\bbecause of (this|that)\b", re.I)


@pytest.fixture(scope="module")
def real():
    return json.loads(gzip.open(FIX).read())


@pytest.fixture(scope="module")
def reviews(real):
    return {pid: build_review(real, pid) for pid in ("p1", "p2", "p3", "p4")}


def _texts(m):
    return [m["situation"], m["assessment"]] + [o[k] or "" for o in m["options"] for k in ("for", "against")] + m["uncertainty"]


# ---------- real decoded replay ----------

def test_real_fixture_is_anonymised_and_decoded(real):
    assert {p["id"] for p in real["players"]} == {"p1", "p2", "p3", "p4"}
    assert len(real["frames"]) > 3000 and any(e["type"] == "touch" for e in real["events"])


def test_small_number_of_moments_with_exact_frame_times_and_live_clips(real, reviews):
    ts = {f["t"] for f in real["frames"]}
    kicks = [e["t"] for e in real["events"] if e["type"] == "kickoff"]
    goals = [e["t"] for e in real["events"] if e["type"] == "goal_context"]
    total = 0
    for rep in reviews.values():
        assert rep["schema"] == "CoachingReviewV1" and rep["expert_validated"] is False
        assert len(rep["moments"]) <= MAX_MOMENTS
        total += len(rep["moments"])
        for m in rep["moments"]:
            assert m["t0"] in ts                                          # a recorded frame, not an interpolated time
            c = m["clip"]
            assert c["start"] <= c["decision"] == m["t0"] <= c["end"]
            assert not any(c["start"] < g < c["end"] for g in goals)        # the clip ends at a goal, never runs past it
            last_kick = max([k for k in kicks if k <= m["t0"]], default=None)
            assert last_kick is None or c["start"] >= last_kick             # no kickoff countdown inside the clip
    assert total >= 8                                                        # the fixture does yield real moments


def test_every_moment_is_specific_traced_and_not_repeated(reviews):
    for rep in reviews.values():
        seen = set()
        for m in rep["moments"]:
            body = m["situation"] + " " + m["assessment"]
            nums = NUM.findall(body)
            assert len(nums) >= 2                                            # would not read the same in another replay
            allowed = {str(v["value"]) for v in m["numbers"].values()} | \
                      {f"{v['value']:g}" for v in m["numbers"].values() if isinstance(v["value"], (int, float))}
            assert all(n in allowed or n in ("0.30", "0.55") for n in nums), (nums, allowed)
            tpl = NUM.sub("#", m["assessment"])
            assert tpl not in seen
            seen.add(tpl)
            for t in _texts(m):
                assert not BANNED.search(t), t
            assert len(m["situation"]) <= BUDGET["situation"] and len(m["assessment"]) <= BUDGET["assessment"]
            assert 1 <= len(m["options"]) <= 3


def test_outcome_is_separate_and_never_changes_the_assessment(real, reviews):
    rep = reviews["p1"]
    m = rep["moments"][0]
    assert m["outcome_after"]["used_in_assessment"] is False
    altered = copy.deepcopy(real)
    for f in altered["frames"]:
        if f["t"] > m["t0"] + 3.0:                                           # after the 2.5 s observation window
            f["ball"]["x"] = -f["ball"]["x"]
    altered["events"] = [e for e in altered["events"] if e["t"] <= m["t0"] + 3.0] + \
                        [{"type": "goal_context", "t": m["t0"] + 3.5, "scoringTeam": "orange"}]
    r2 = review_moment_at(altered, "p1", m["t0"])
    assert r2["status"] == "ok"
    keep = ("category", "situation", "assessment", "options", "uncertainty", "t0")
    r1 = review_moment_at(real, "p1", m["t0"])["moment"]
    assert {k: r1[k] for k in keep} == {k: r2["moment"][k] for k in keep}


def test_missing_information_abstains_explicitly(real):
    gone = copy.deepcopy(real)
    for f in gone["frames"]:
        f["cars"].pop("p1", None)
    r = build_review(gone, "p1")
    assert r["moments"] == []
    assert review_moment_at(gone, "p1", 50.0)["status"] == "abstain"
    assert review_moment_at(real, "p1", 9999.0)["status"] == "abstain"


def test_compact_payload_for_the_side_panel(reviews):
    for rep in reviews.values():
        assert len(json.dumps(rep)) < 30_000
        for m in rep["moments"]:
            visible = len(m["headline"]) + len(m["situation"]) + len(m["assessment"]) + \
                sum(len(o["label"]) + len(o["for"] or "") + len(o["against"] or "") for o in m["options"])
            assert visible <= 1200                                           # a card, not a wall of text


def test_no_habits_turning_points_or_model_scores(reviews):
    for rep in reviews.values():
        s = json.dumps(rep["moments"])
        assert not re.search(r"\bhabit|\bturning point", s, re.I) and "next_touch_own" not in s
        assert rep["method"]["model_called"] is False


# ---------- synthetic guards ----------

def cat(name, fut=None):
    r = review_moment_at(materialise(SC[name], fut), "b1", T0)
    return r.get("moment", {}).get("category"), r


def test_good_restraint_is_not_criticised_even_when_a_goal_follows():
    for fut in ("shadow_then_their_goal", "shadow_then_save"):
        c, _ = cat("restraint_then_conceded", fut)
        assert c == "good_decision"


def test_uncovered_challenge_is_not_praised_even_when_it_works():
    c, r = cat("challenge_works_anyway", "challenge_then_our_goal")
    assert c not in ("good_decision", "tradeoff")


def test_covered_aggression_is_recognised_and_holding_back_is_only_a_missed_chance():
    assert cat("covered_first_man_aggression", "challenge_then_their_goal")[0] == "good_decision"
    assert cat("covered_first_man_aggression")[0] in ("possible_missed_opportunity", None)


def test_ambiguous_fifty_fifty_is_not_criticised():
    assert cat("level_contest_with_cover")[0] not in ("possible_mistake",)


def test_teammate_cover_uncertainty_is_named():
    c, r = cat("teammate_cover_borderline")
    assert c != "possible_mistake"
    if r["status"] == "ok":
        assert any("teammate" in u for u in r["moment"]["uncertainty"])


def test_aerial_and_missing_telemetry_abstain():
    assert cat("backboard_benchmark_aerial")[1]["status"] == "abstain"
    assert cat("missing_focus_telemetry")[1]["status"] == "abstain"


def test_aggressive_touch_without_cover_is_never_a_good_decision():
    """_categorise: a touch-family action is only 'good' when the teammate-cover premise holds."""
    from coach_app import coaching_review as cr
    fa = {"kind": "clear_read", "alternatives": [{"action": "immediate_challenge", "status": "supported", "family": "touch"}]}
    fb = {"observed_action": {"label": "immediate_challenge", "family": "touch"}, "assessment": {"verdict": "sound"}}
    covered = {"conditions": {"teammate_covers": {"status": "holds"}}, "decisive_information": []}
    uncovered = {"conditions": {"teammate_covers": {"status": "fails"}}, "decisive_information": []}
    assert cr._categorise(fa, fb, covered) == "good_decision"
    assert cr._categorise(fa, fb, uncovered) == "tradeoff"
    assert cr._categorise(fa, fb, {**covered, "ledger_adjustments": [{"condition": "x"}]}) is None


# ---------- API and the decision-cases crash ----------

def test_review_endpoint_and_capability(real):
    from fastapi.testclient import TestClient

    from coach_app.main import app
    c = TestClient(app)
    caps = c.get("/api/coach/capabilities").json()
    assert caps["coaching_review"] == "CoachingReviewV1" and caps["coaching_review_endpoint"] == "/api/coach/review"
    r = c.post("/api/coach/review", json={"replay": real, "player_id": "p1", "max_moments": 3})
    assert r.status_code == 200 and len(r.json()["moments"]) <= 3
    assert c.post("/api/coach/review", json={"replay": real, "player_id": "zz"}).status_code == 422


def test_json_safe_replaces_non_finite_numbers():
    from coach_app.main import _json_safe
    assert _json_safe({"a": float("inf"), "b": [1.0, float("nan")], "c": "x"}) == {"a": None, "b": [1.0, None], "c": "x"}


def test_build_moment_is_none_for_non_firm_reads(real):
    from coach_app.coach_report import analyze_moment
    from coach_app.situations import discover_situations
    sits = [s.to_dict() for s in discover_situations(real, "p1")]
    n_none = 0
    for s in sits:
        it = analyze_moment(real, "p1", s, ledger="r13")
        if not it:
            continue
        it["salience"] = {"score": 0}
        n_none += build_moment(real, "p1", it, moment_id="x") is None
    assert n_none >= 1                                                       # abstention happens on real data


def test_single_moment_mode_reviews_or_abstains(real, reviews):
    from fastapi.testclient import TestClient

    from coach_app.main import app
    c = TestClient(app)
    m = reviews["p1"]["moments"][0]
    r = c.post("/api/coach/review", json={"replay": real, "player_id": "p1", "t0": m["t0"]}).json()
    assert r["mode"] == "single_moment" and r["status"] == "ok" and r["moments"][0]["category"] == m["category"]
    r = c.post("/api/coach/review", json={"replay": real, "player_id": "p1", "t0": 5.0}).json()     # before kickoff
    assert r["status"] == "abstain" and r["moments"] == [] and r["abstention_reason"]


def test_rotation_is_not_called_a_mistake_without_a_present_risk():
    """Real slice, p2 at 51.6 s: rotating through pads while not goal-side was 'refuted' only because the player
    had 66 boost (no modelled reason applied). That is not a mistake; a mistake needs a risk present at t0."""
    from coach_app import coaching_review as cr
    fa = {"kind": "clear_read", "alternatives": [
        {"action": "rotate_through_small_pads", "status": "refuted", "family": "boost",
         "ruled_out_because": [{"reason": "x", "fails_because": ["you had 66 boost"]}], "why": []},
        {"action": "immediate_challenge", "status": "supported", "family": "touch", "why": []}]}
    fb = {"observed_action": {"label": "rotate_through_small_pads", "family": "boost"}, "assessment": {"verdict": "questionable"}}
    no_risk = {"conditions": {"teammate_covers": {"status": "holds"}}, "decisive_information": []}
    risk = {"conditions": {"teammate_covers": {"status": "fails"}}, "decisive_information": []}
    assert cr._categorise(fa, fb, no_risk) is None
    assert cr._categorise(fa, fb, risk) == "possible_mistake"


def test_real_slice_has_no_rotation_mistake(reviews):
    for rep in reviews.values():
        for m in rep["moments"]:
            if m["category"] == "possible_mistake":
                assert m["your_choice"]["label"] not in ("Rotate through small pads", "Return directly",
                                                         "Return through small pads", "Hold goal-side", "Shadow and delay")

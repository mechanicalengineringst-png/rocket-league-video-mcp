"""Tests for the research prototypes. Synthetic data checks code paths only.

The last test decodes real replays when COACH_SAMPLE_REPLAY_DIR is set, matching
the convention in coach-app/tests/test_audit_regressions.py.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from research.tactical_intel import contract, metrics, profile
from research.tactical_intel.decisions import extract_decisions
from research.tactical_intel.features import ALL_FEATURES, frame_table, next_goal_labels, team_features
from research.tactical_intel.frames import dedupe
from research.tactical_intel.retrieval import Retriever, evaluate_retrieval
from research.tactical_intel.value_model import group_folds, heuristic_score, run_value_experiment
from research.tests.synthetic import defence_scene, make_match, rotated_copy


# ---------- features ----------

def test_rotation_symmetry_team1_equals_team0_of_rotated_match():
    m = make_match(goals=[(20.0, 1)])
    r = rotated_copy(m)
    a = team_features(m, 1)
    b = team_features(r, 0)
    np.testing.assert_allclose(a.to_numpy(), b.to_numpy(), rtol=1e-9, atol=1e-6, equal_nan=True)


def test_features_are_causal():
    m = make_match()
    full = team_features(m, 0)
    cut = 300
    from dataclasses import replace
    short = replace(m, t=m.t[:cut], live=m.live[:cut], ball=m.ball[:cut], cars=m.cars[:cut],
                    boost=m.boost[:cut], present=m.present[:cut],
                    seconds_remaining=m.seconds_remaining[:cut], builtin_threat=m.builtin_threat[:cut])
    part = team_features(short, 0)
    np.testing.assert_allclose(full.iloc[:cut].to_numpy(), part.to_numpy(), equal_nan=True)


def test_absent_cars_are_ignored_not_treated_as_at_origin():
    m = make_match()
    m.present[:, 0] = False
    f = team_features(m, 0)
    assert (f["own_present"] == 1).all()
    assert np.isfinite(f["own_min_dist"]).all()


def test_labels_horizon_and_censoring():
    m = make_match(n=600, goals=[(10.0, 0), (30.0, 1)])
    y0, valid0 = next_goal_labels(m, 0, 5.0)
    t = m.t
    assert y0[(t >= 5.01) & (t < 10.0)].all()
    assert not y0[(t < 4.99)].any()
    assert not y0[(t > 25) & (t < 30)].any()          # the other team's goal
    assert not valid0[t > m.t[-1] - 5.0 + 1e-9].any()   # no goal can resolve the window


def test_step_hold_does_not_carry_values_across_a_stoppage():
    from research.tactical_intel.frames import _step_hold
    src_t = np.array([0.0, 0.2, 0.4, 10.0])
    src_v = np.array([0.1, 0.5, 0.99, 0.02])
    out = _step_hold(src_t, src_v, np.array([0.3, 0.8, 5.0, 10.1]))
    assert out[0] == 0.5 and out[1] == 0.99
    assert np.isnan(out[2])          # a pre-goal value must not reach the next kickoff
    assert out[3] == 0.02


# ---------- data hygiene ----------

def test_dedupe_drops_identical_replays():
    a, b = make_match("same"), make_match("same")
    kept, dropped = dedupe([a, b, make_match("other")])
    assert len(kept) == 2 and dropped == ["same.replay"]


def test_group_folds_never_share_a_match():
    groups = np.repeat([f"m{i}" for i in range(7)], 50)
    for tr, te in group_folds(groups, 5):
        assert not set(groups[tr]) & set(groups[te])


# ---------- value experiment ----------

def test_value_experiment_runs_end_to_end_on_synthetic_data():
    ms = [make_match(f"m{i}", n=400, seed=i, goals=[(12.0 + i, i % 2), (28.0, (i + 1) % 2)]) for i in range(6)]
    res = run_value_experiment(frame_table(ms), n_splits=3, n_boot=0)
    for k in ("base_rate", "heuristic", "builtin_raw", "builtin_recal", "logreg", "lgbm_full"):
        s = res.summary["head_to_head"]["systems"][k]
        assert 0 <= s["brier"] <= 1 and np.isfinite(s["log_loss"])
    assert res.failures["missed_goals"]


def test_value_summary_scores_modes_without_builtin_threat():
    ms = [make_match(f"a{i}", n=400, seed=i, goals=[(12.0, i % 2)]) for i in range(3)]
    ms += [make_match(f"b{i}", n=400, seed=10 + i, sizes=(3, 3), threat=False, goals=[(15.0, 1)]) for i in range(3)]
    res = run_value_experiment(frame_table(ms), n_splits=3, n_boot=0)
    three = res.summary["by_mode"]["3v3"]["systems"]
    assert "lgbm_full" in three and "builtin_raw" not in three
    assert res.summary["head_to_head"]["modes"] == ["2v2"]


def test_heuristic_is_bounded_count():
    ms = [make_match()]
    h = heuristic_score(frame_table(ms))
    assert h.min() >= 0 and h.max() <= 5


# ---------- metrics ----------

def test_metrics_known_values():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.4, 0.35, 0.8])
    assert metrics.auc(y, p) == pytest.approx(0.75)
    assert metrics.brier(y, np.full(4, 0.5)) == pytest.approx(0.25)
    assert metrics.ece(np.array([0, 1]), np.array([0.5, 0.5])) == pytest.approx(0.0)


def test_bootstrap_resamples_matches_not_frames():
    g = np.repeat(["a", "b", "c"], [1, 1, 98])
    lo, hi = metrics.match_bootstrap(g, lambda i: float(len(np.unique(g[i]))), n_boot=200)
    assert 1 <= lo <= hi <= 3


# ---------- decisions ----------

@pytest.mark.parametrize("choice", ["challenge", "shadow"])
def test_decision_extractor_reads_choice(choice):
    pts = [p for p in extract_decisions(defence_scene(choice)) if p.team == 0]
    assert len(pts) == 1
    p = pts[0]
    assert p.choice == choice
    assert p.tactical["mate_goalside"] == 1.0
    assert set(p.retrospective) >= {"value_change", "conceded_within_5s"}


def test_decision_features_do_not_depend_on_future_frames():
    m = defence_scene("challenge")
    a = [p for p in extract_decisions(m) if p.team == 0][0]
    other = defence_scene("shadow")
    b = [p for p in extract_decisions(other) if p.team == 0][0]
    assert a.t0 == b.t0
    assert a.tactical == b.tactical and a.geometric == b.geometric   # same past, different future
    assert a.choice != b.choice


# ---------- retrieval ----------

def _corpus():
    pts = []
    for i in range(6):
        for c in ("challenge", "shadow"):
            for p in extract_decisions(defence_scene(c, match_id=f"{c}{i}")):
                if p.team == 0:
                    p.tactical["focal_boost"] += i   # make points distinct
                    pts.append(p)
    return pts


def test_retrieval_never_returns_the_query_match():
    pts = _corpus()
    q = [p for p in pts if p.match_id == "challenge0"]
    train = [p for p in pts if p.match_id != "challenge0"]
    for idx in Retriever("learned", k=5).fit(train).query(q):
        assert all(train[j].match_id != "challenge0" for j in idx)


def test_retrieval_evaluation_reports_all_representations():
    out = evaluate_retrieval(_corpus(), k=3, n_boot=0)
    assert set(out["representations"]) == {"geometric", "tactical", "learned", "velocity"}
    assert out["queries"] == 12


# ---------- contract ----------

def test_assessment_abstains_with_thin_support_and_never_claims_causality():
    pts = _corpus()
    a = contract.assess(pts[0], pts[1:6], {"value_model": "test"})
    assert a.verdict == "abstain"
    assert all("Not a causal estimate" in alt.note for alt in a.alternatives)
    payload = a.explanation_payload()
    assert payload["facts"] and payload["rules_for_narrator"]


def test_blind_case_is_pre_decision_only_and_matches_pr16_fields():
    p = _corpus()[0]
    case = contract.to_blind_case(p, "c1", "anonymous-match-00")
    assert set(case) <= {"case_id", "t0", "situation_type", "pre_decision_evidence", "replay_group", "mode"}
    for e in case["pre_decision_evidence"]:
        assert set(e) <= {"key", "claim", "event_time_s", "finalized_through_s", "source", "source_quality"}
        assert e["event_time_s"] <= e["finalized_through_s"] <= case["t0"]
    blob = json.dumps(case)
    for leaked in ("value_change", "conceded", "retrospective", "choice"):
        assert leaked not in blob


def test_blind_prediction_cites_only_case_keys():
    pts = _corpus()
    a = contract.assess(pts[0], pts[1:], {})
    case = contract.to_blind_case(pts[0], "c1", "g")
    pred = contract.to_blind_prediction(a, "c1")
    keys = {e["key"] for e in case["pre_decision_evidence"]}
    assert set(pred["cited_evidence"]) <= keys
    assert pred["assessment"] in {"sound", "risk", "tradeoff", "abstain"}


# ---------- personal adaptation ----------

def test_shrinkage_pulls_small_samples_to_population():
    prior = profile.BetaPrior(20, 30)                     # population rate 0.4, strength 50
    tiny = profile.shrink(1, 1, prior)
    big = profile.shrink(270, 300, prior)
    assert abs(tiny.estimate - 0.4) < 0.02               # 1/1 is not a 100% challenger
    assert big.estimate == pytest.approx(290 / 350)       # 300 attempts carry 6/7 of the weight
    assert big.weight_on_player == pytest.approx(300 / 350)
    assert tiny.high90 - tiny.low90 > big.high90 - big.low90
    assert not profile.distinguishable(tiny, profile.shrink(0, 2, prior))


def test_prior_fit_handles_few_players():
    pr = profile.fit_prior(np.array([3, 1]), np.array([5, 4]))
    assert profile.MIN_PRIOR_STRENGTH <= pr.strength <= profile.MAX_PRIOR_STRENGTH


# ---------- real decoder (optional) ----------

SAMPLES = os.getenv("COACH_SAMPLE_REPLAY_DIR")


@pytest.mark.skipif(not SAMPLES, reason="set COACH_SAMPLE_REPLAY_DIR to run the real decoder")
def test_real_replays_goals_reconcile_and_threat_is_present():
    from research.tactical_intel.frames import load_match
    checked = 0
    for path in sorted(Path(SAMPLES).glob("*.replay")):
        try:
            m = load_match(path)
        except ValueError:
            continue
        if m.mode != "2v2":
            continue
        assert not m.notes, f"{path.name}: {m.notes}"
        assert 0.4 < m.live.mean() < 0.98   # short replays with several goal replays sit near 0.6
        assert np.isfinite(m.builtin_threat).mean() > 0.9
        assert set(team_features(m, 0).columns) == set(ALL_FEATURES)
        checked += 1
        if checked == 3:
            break
    assert checked

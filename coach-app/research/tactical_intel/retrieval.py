"""Prototype 2: retrieve comparable human decisions, and test whether "comparable" means anything.

Three representations of a decision point are compared under leave-one-match-out:
- ``geometric``: ball and focal-car position/velocity. What naive "similar plays" uses.
- ``tactical``: arrival times, boost, teammate cover, score, clock.
- ``learned``: Neighbourhood Components Analysis on both, supervised by the choice
  humans made, fitted on training matches only.
- ``velocity``: a diagnostic, the defender's motion at t0 only. If it predicts the
  choice as well as geometry, the choice was largely made before t0.

Three questions per representation, all answered on held-out matches:
1. Choice: do neighbours' choices predict the query's choice (log loss vs base rate)?
2. Outcome: does the neighbours' mean value change predict the query's?
3. Context: do neighbours share the query's tactical context (teammate goal-side,
   who arrives first, defensive third)? Pure geometry often does not.

A rule baseline answers question 1 too: "challenge if you arrive no later than
0.3 s after the attacker". It stands in for the app's current rule style.
"""
from __future__ import annotations

import warnings

import numpy as np
from sklearn.neighbors import NearestNeighbors, NeighborhoodComponentsAnalysis
from sklearn.preprocessing import StandardScaler

from . import metrics as M
from .decisions import CHOICES, GEOMETRIC_KEYS, TACTICAL_KEYS, DecisionPoint, as_matrix

K = 15
SEED = 7


def _design(points: list[DecisionPoint], rep: str) -> np.ndarray:
    if rep == "velocity":
        # Diagnostic only: the defender's motion at t0 and nothing else.
        return np.array([[p.geometric["focal_vx"], p.geometric["focal_vy"],
                          p.tactical["focal_closing_speed"]] for p in points], dtype=float)
    if rep == "geometric":
        return as_matrix(points, GEOMETRIC_KEYS, "geometric")
    tac = as_matrix(points, TACTICAL_KEYS, "tactical")
    if rep == "tactical":
        return tac
    return np.hstack([tac, as_matrix(points, GEOMETRIC_KEYS, "geometric")])


def context_signature(p: DecisionPoint) -> tuple:
    t = p.tactical
    return (t["mate_goalside"] > 0.5, t["ttb_adv"] > -0.3, t["ball_dist_own_goal"] < 3500)


class Retriever:
    """Fit on training decisions; query returns indices into the training list."""

    def __init__(self, rep: str, k: int = K):
        self.rep, self.k = rep, k

    def fit(self, train: list[DecisionPoint]) -> "Retriever":
        X = np.nan_to_num(_design(train, self.rep))
        self.scaler = StandardScaler().fit(X)
        Z = self.scaler.transform(X)
        self.nca = None
        if self.rep == "learned":
            y = np.array([CHOICES.index(p.choice) for p in train])
            if len(np.unique(y)) > 1:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    self.nca = NeighborhoodComponentsAnalysis(
                        n_components=min(4, Z.shape[1]), random_state=SEED, max_iter=200).fit(Z, y)
                Z = self.nca.transform(Z)
        self.index = NearestNeighbors(n_neighbors=min(self.k, len(train))).fit(Z)
        return self

    def _embed(self, pts: list[DecisionPoint]) -> np.ndarray:
        Z = self.scaler.transform(np.nan_to_num(_design(pts, self.rep)))
        return self.nca.transform(Z) if self.nca is not None else Z

    def query(self, pts: list[DecisionPoint]) -> np.ndarray:
        return self.index.kneighbors(self._embed(pts), return_distance=False)


def rule_choice(p: DecisionPoint) -> str:
    """The app's style: a fixed tactical rule."""
    return "challenge" if p.tactical["ttb_adv"] > -0.3 else "shadow"


def momentum_choice(p: DecisionPoint) -> str:
    """Predict the choice from how the defender is already moving at t0.

    If this does as well as retrieval, the "decision" was made before t0 and the
    situation trigger fires too late to capture it.
    """
    if p.tactical["focal_closing_speed"] > 500:
        return "challenge"
    if p.tactical["focal_vy"] < -200:
        return "shadow"
    return "unclear"


def evaluate_retrieval(points: list[DecisionPoint], k: int = K, n_boot: int = 500) -> dict:
    """Leave-one-match-out evaluation. Neighbours always come from other matches."""
    matches = sorted({p.match_id for p in points})
    reps = ("geometric", "tactical", "learned", "velocity")
    rows = {r: {"ll": [], "acc": [], "dv_pred": [], "ctx": []} for r in reps}
    base = {"ll": [], "acc": [], "dv_pred": []}
    rule_acc, mom_acc, truth_dv, truth_choice, groups, query_ids = [], [], [], [], [], []
    readable = {r: [] for r in reps}
    readable_rule, readable_mom, readable_base = [], [], []
    for m in matches:
        train = [p for p in points if p.match_id != m]
        test = [p for p in points if p.match_id == m]
        if not test or len(train) < k:
            continue
        counts = np.array([sum(p.choice == c for p in train) for c in CHOICES], float)
        prior = (counts + 1) / (counts.sum() + len(CHOICES))
        dv_train = np.array([p.retrospective["value_change"] for p in train])
        dv_mean = float(np.nanmean(dv_train)) if np.isfinite(dv_train).any() else 0.0
        for q in test:
            ci = CHOICES.index(q.choice)
            base["ll"].append(-np.log(prior[ci]))
            base["acc"].append(float(np.argmax(prior) == ci))
            base["dv_pred"].append(dv_mean)
            rule_acc.append(float(rule_choice(q) == q.choice))
            mom_acc.append(float(momentum_choice(q) == q.choice))
            if q.choice != "unclear":
                readable_rule.append(float(rule_choice(q) == q.choice))
                readable_mom.append(float(momentum_choice(q) == q.choice))
                readable_base.append(float(("challenge" if prior[0] >= prior[1] else "shadow") == q.choice))
            truth_dv.append(q.retrospective["value_change"])
            truth_choice.append(q.choice)
            groups.append(m)
            query_ids.append(q.decision_id)
        for rep in reps:
            r = Retriever(rep, k).fit(train)
            nn = r.query(test)
            for q, idx in zip(test, nn):
                neigh = [train[j] for j in idx]
                cnt = np.array([sum(p.choice == c for p in neigh) for c in CHOICES], float)
                dist = (cnt + prior * 2.0) / (cnt.sum() + 2.0)  # shrink toward the prior
                ci = CHOICES.index(q.choice)
                rows[rep]["ll"].append(-np.log(dist[ci]))
                rows[rep]["acc"].append(float(np.argmax(dist) == ci))
                if q.choice != "unclear":
                    readable[rep].append(float(("challenge" if cnt[0] >= cnt[1] else "shadow") == q.choice))
                dvs = np.array([p.retrospective["value_change"] for p in neigh])
                rows[rep]["dv_pred"].append(float(np.nanmean(dvs)) if np.isfinite(dvs).any() else dv_mean)
                sig = context_signature(q)
                rows[rep]["ctx"].append(float(np.mean([context_signature(p) == sig for p in neigh])))

    groups_a = np.array(groups)
    tdv = np.array(truth_dv, float)
    ok = np.isfinite(tdv)
    out = {
        "decisions": len(points), "queries": len(truth_choice), "matches": len(set(groups)), "k": k,
        "choice_distribution": {c: int(sum(x == c for x in truth_choice)) for c in CHOICES},
        "base_rate": {"choice_log_loss": float(np.mean(base["ll"])), "choice_accuracy": float(np.mean(base["acc"]))},
        "rule_baseline": {"choice_accuracy": float(np.mean(rule_acc)),
                          "readable_choice_accuracy": float(np.mean(readable_rule)) if readable_rule else None,
                          "note": "challenge if ttb_adv > -0.3 s, else shadow; never predicts unclear"},
        "momentum_baseline": {"choice_accuracy": float(np.mean(mom_acc)),
                              "readable_choice_accuracy": float(np.mean(readable_mom)) if readable_mom else None,
                              "note": "reads the defender's velocity at t0 only"},
        "readable_majority_baseline_accuracy": float(np.mean(readable_base)) if readable_base else None,
        "representations": {},
    }
    bdv = np.array(base["dv_pred"])
    sse_base = np.sum((tdv[ok] - bdv[ok]) ** 2)
    random_ctx = _random_context_agreement(points)
    out["context_agreement_if_random"] = random_ctx
    for rep in reps:
        ll = np.array(rows[rep]["ll"])
        pred = np.array(rows[rep]["dv_pred"])
        r2 = 1 - np.sum((tdv[ok] - pred[ok]) ** 2) / sse_base if sse_base > 0 else None
        res = {
            "choice_log_loss": float(ll.mean()),
            "choice_log_loss_gain_vs_base": float(np.mean(base["ll"]) - ll.mean()),
            "choice_accuracy": float(np.mean(rows[rep]["acc"])),
            "readable_choice_accuracy": float(np.mean(readable[rep])) if readable[rep] else None,
            "value_change_r2_vs_mean": r2,
            "context_agreement": float(np.mean(rows[rep]["ctx"])),
        }
        if n_boot:
            bl = np.array(base["ll"])
            res["choice_log_loss_gain_ci95"] = M.match_bootstrap(
                groups_a, lambda i, ll=ll: float(np.mean(bl[i]) - np.mean(ll[i])), n_boot=n_boot)
            okg = groups_a[ok]
            t, pp, bb = tdv[ok], pred[ok], bdv[ok]
            res["value_change_r2_ci95"] = M.match_bootstrap(
                okg, lambda i: 1 - np.sum((t[i] - pp[i]) ** 2) / max(np.sum((t[i] - bb[i]) ** 2), 1e-12),
                n_boot=n_boot)
        out["representations"][rep] = res
    return out


def _random_context_agreement(points: list[DecisionPoint]) -> float:
    sigs = [str(context_signature(p)) for p in points]
    if not sigs:
        return float("nan")
    _, counts = np.unique(np.array(sigs), return_counts=True)
    share = counts / counts.sum()
    return float(np.sum(share ** 2))

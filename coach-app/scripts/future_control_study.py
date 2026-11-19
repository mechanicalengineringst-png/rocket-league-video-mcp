"""Which information predicts the next seconds? Architecture comparison on held-out matches (Round 13).

Targets (from build_state_dataset.py): next_touch_own (3 s), danger_5s, goal_against_10s.
Models, all evaluated leave-one-match-out (15 folds) on rows from both team perspectives:
  base           training base rate
  physics        logistic on the first-arrival reach margin only (the Round 10-12 core quantity)
  reach          logistic on all reach features
  ledger_like    logistic on reach + boost + goal-side + cover-like features (what the R12 ledger reads)
  logistic_all   logistic on every feature (median-imputed, missing flags)
  gbm_all        LightGBM on every feature (research only; not a runtime dependency)
  gbm_minus_X    ablations dropping one feature group
  knn            scenario retrieval: 50 nearest situations (standardised features) from other matches
Metrics: log loss, Brier, AUC; match-level bootstrap CI for the log-loss gain over physics.
Usage (from coach-app/): python scripts/future_control_study.py STATES.pkl OUT.json
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach_app.state_features import group_of  # noqa: E402

warnings.filterwarnings("ignore")
LABELS = ["next_touch_own", "danger_5s", "opportunity_5s", "goal_against_10s", "goal_for_10s", "danger_5s_from_outside"]
META = ["match", "t", "team"]
TARGETS = ["next_touch_own", "danger_5s", "danger_5s_from_outside", "goal_against_10s"]
DERIVED = {"danger_5s_from_outside": ("danger_5s", "ball_own_goal_dist", 3000.0)}   # only rows with the ball >= 3000 uu from our goal


def feats(df):
    return [c for c in df.columns if c not in LABELS + META]


def _prep(tr, te, cols):
    Xtr, Xte = tr[cols].astype(float).copy(), te[cols].astype(float).copy()
    med = Xtr.median()
    miss = [c for c in cols if Xtr[c].isna().any() or Xte[c].isna().any()]
    for c in miss:
        Xtr[c + "_missing"] = Xtr[c].isna().astype(float)
        Xte[c + "_missing"] = Xte[c].isna().astype(float)
    Xtr, Xte = Xtr.fillna(med).fillna(0.0), Xte.fillna(med).fillna(0.0)
    mu, sd = Xtr.mean(), Xtr.std().replace(0, 1.0)
    return ((Xtr - mu) / sd).values, ((Xte - mu) / sd).values


def logistic(tr, te, cols, y):
    from sklearn.linear_model import LogisticRegression
    Xtr, Xte = _prep(tr, te, cols)
    m = LogisticRegression(C=0.5, max_iter=2000).fit(Xtr, tr[y].values)
    return m.predict_proba(Xte)[:, 1]


def gbm(tr, te, cols, y):
    import lightgbm as lgb
    m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=60,
                           subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)
    m.fit(tr[cols].astype(float), tr[y].values)
    return m.predict_proba(te[cols].astype(float))[:, 1]


def knn(tr, te, cols, y, k=50):
    from sklearn.neighbors import KNeighborsClassifier
    Xtr, Xte = _prep(tr, te, cols)
    m = KNeighborsClassifier(n_neighbors=k).fit(Xtr, tr[y].values)
    return m.predict_proba(Xte)[:, 1]


def metrics(p, y):
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return {"log_loss": round(float(log_loss(y, p, labels=[0, 1])), 4), "brier": round(float(brier_score_loss(y, p)), 4),
            "auc": round(float(roc_auc_score(y, p)), 4) if 0 < y.sum() < len(y) else None}


def run(df, target):
    if target in DERIVED:
        src, col, lo = DERIVED[target]
        df = df[df[col] >= lo].copy()
        df[target] = df[src]
    d = df[~df[target].isna()].copy()
    allc = feats(d)
    groups = {g: [c for c in allc if group_of(c) == g] for g in ("ball", "reach", "players", "control")}
    ledger_like = groups["reach"] + [c for c in allc if c.endswith(("_boost", "_goal_side"))] + \
        [c for c in allc if c.startswith("debt_")]
    models = {
        "physics": lambda tr, te: logistic(tr, te, ["reach_margin_first"], target),
        "reach": lambda tr, te: logistic(tr, te, groups["reach"], target),
        "ledger_like": lambda tr, te: logistic(tr, te, ledger_like, target),
        "logistic_all": lambda tr, te: logistic(tr, te, allc, target),
        "gbm_all": lambda tr, te: gbm(tr, te, allc, target),
        "knn": lambda tr, te: knn(tr, te, allc, target),
    }
    for g in groups:
        models[f"gbm_minus_{g}"] = (lambda gg: (lambda tr, te: gbm(tr, te, [c for c in allc if group_of(c) != gg], target)))(g)
    preds = {name: np.zeros(len(d)) for name in ["base"] + list(models)}
    for m in d["match"].unique():
        tr, te = d[d["match"] != m], d[d["match"] == m]
        idx = np.where(d["match"].values == m)[0]
        preds["base"][idx] = tr[target].mean()
        for name, fn in models.items():
            preds[name][idx] = fn(tr, te)
    y = d[target].values.astype(int)
    res = {"n": len(d), "matches": int(d["match"].nunique()), "base_rate": round(float(y.mean()), 3),
           "models": {k: metrics(v, y) for k, v in preds.items()}}
    # match-level bootstrap of log-loss gain over physics
    from sklearn.metrics import log_loss
    mids = d["match"].values
    rng = np.random.default_rng(0)
    um = np.unique(mids)
    per = {k: {m: log_loss(y[mids == m], np.clip(v[mids == m], 1e-4, 1 - 1e-4), labels=[0, 1]) * (mids == m).sum()
               for m in um} for k, v in preds.items()}
    cnt = {m: (mids == m).sum() for m in um}
    ci = {}
    for k in preds:
        if k == "physics":
            continue
        diffs = []
        for _ in range(500):
            s = rng.choice(um, len(um))
            n = sum(cnt[m] for m in s)
            diffs.append((sum(per["physics"][m] for m in s) - sum(per[k][m] for m in s)) / n)
        ci[k] = [round(float(np.quantile(diffs, 0.025)), 4), round(float(np.quantile(diffs, 0.975)), 4)]
    res["log_loss_gain_vs_physics_95ci"] = ci
    # calibration of the best compact model
    for name in ("logistic_all", "gbm_all"):
        p = preds[name]
        bins = np.linspace(0, 1, 6)
        cal = []
        for lo, hi in zip(bins[:-1], bins[1:]):
            mk = (p >= lo) & (p < hi)
            if mk.sum() >= 30:
                cal.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": int(mk.sum()), "mean_pred": round(float(p[mk].mean()), 3),
                            "observed": round(float(y[mk].mean()), 3)})
        res[f"calibration_{name}"] = cal
    return res, preds, d


def importance(df, target):
    import lightgbm as lgb
    if target in DERIVED:
        src, col, lo = DERIVED[target]
        df = df[df[col] >= lo].copy()
        df[target] = df[src]
    d = df[~df[target].isna()]
    cols = feats(d)
    m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=60, verbose=-1,
                           importance_type="gain").fit(d[cols].astype(float), d[target].values)
    imp = sorted(zip(cols, m.feature_importances_), key=lambda x: -x[1])
    tot = sum(v for _, v in imp) or 1.0
    by_group = {}
    for c, v in imp:
        by_group[group_of(c)] = by_group.get(group_of(c), 0.0) + v / tot
    return {"top": [[c, round(v / tot, 3)] for c, v in imp[:15]], "by_group": {k: round(v, 3) for k, v in by_group.items()}}


def main(states: Path, out: Path, only: list[str] | None = None):
    df = pd.read_pickle(states)
    res = {"rows": len(df), "matches": int(df["match"].nunique()),
           "note": "Public 2v2 replays of unknown rank; consecutive rows are strongly correlated (0.5 s apart).",
           "targets": {}}
    for tgt in (only or TARGETS):
        r, _, _ = run(df, tgt)
        r["importance_gbm_gain"] = importance(df, tgt)
        res["targets"][tgt] = r
        print(tgt, json.dumps(r["models"]), flush=True)
    out.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].split(",") if len(sys.argv) > 3 else None)

"""Prototype 1: short-horizon state value, compared across very different predictors.

Target: P(perspective team scores within ``horizon`` seconds of live play).
Every learned model is scored out-of-fold with folds grouped by match, so no
match contributes frames to both training and evaluation.

Systems compared:
- ``base_rate``: training-fold goal rate. The floor.
- ``heuristic``: a hand-written danger rule, isotonic-calibrated on training folds.
  Stands in for the rule-based coaching style the app uses today.
- ``builtin_raw`` / ``builtin_recal``: subtr-actor's shipped threat model (trained
  upstream on 2,540 ranked-doubles replays), as is and Platt-recalibrated.
- ``logreg`` and ``lgbm_*``: small models trained here, with an off-ball ablation.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import metrics as M
from .features import FEATURE_GROUPS

SEED = 7


def heuristic_score(df: pd.DataFrame) -> np.ndarray:
    """A deliberately simple 0-5 danger count, like a rule a coach might write.

    Ball in the attacking third, ball moving toward goal, attacker arrives first,
    no more than one defender goal-side, and ball close to goal.
    """
    s = np.zeros(len(df))
    s += (df["ball_y"] > 1700).to_numpy()
    s += (df["ball_vy"] > 300).to_numpy()
    s += (df["ttb_adv"].fillna(0) > 0).to_numpy()
    s += (df["opp_goalside"].fillna(0) <= 1).to_numpy()
    s += (df["ball_dist_opp_goal"] < 2500).to_numpy()
    return s


def _lgbm(seed: int = SEED):
    import lightgbm as lgb

    return lgb.LGBMClassifier(
        n_estimators=250, learning_rate=0.04, num_leaves=15, min_child_samples=200,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
        random_state=seed, n_jobs=1, deterministic=True, force_row_wise=True, verbose=-1,
    )


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


@dataclass
class ValueResults:
    oof: pd.DataFrame
    summary: dict
    failures: dict


def group_folds(groups: np.ndarray, n_splits: int) -> list[tuple[np.ndarray, np.ndarray]]:
    n = min(n_splits, len(np.unique(groups)))
    return list(GroupKFold(n_splits=n).split(np.zeros(len(groups)), groups=groups))


def run_value_experiment(table: pd.DataFrame, n_splits: int = 5, n_boot: int = 500) -> ValueResults:
    df = table.reset_index(drop=True).copy()
    y = df["y"].to_numpy().astype(float)
    groups = df["match_id"].to_numpy()
    preds = {k: np.full(len(df), np.nan) for k in (
        "base_rate", "heuristic", "builtin_raw", "builtin_recal", "logreg",
        "lgbm_ball_only", "lgbm_on_ball", "lgbm_full")}
    folds = group_folds(groups, n_splits)
    has_builtin = df["builtin_v"].notna().to_numpy()

    for tr, te in folds:
        ytr = y[tr]
        preds["base_rate"][te] = ytr.mean()

        h = heuristic_score(df)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=1e-4, y_max=1 - 1e-4)
        iso.fit(h[tr], ytr)
        preds["heuristic"][te] = iso.predict(h[te])

        bv = df["builtin_v"].to_numpy()
        preds["builtin_raw"][te] = bv[te]
        trb = tr[has_builtin[tr]]
        if len(np.unique(y[trb])) == 2:
            pl = LogisticRegression(C=1e3)
            pl.fit(_logit(bv[trb])[:, None], y[trb])
            teb = te[has_builtin[te]]
            preds["builtin_recal"][teb] = pl.predict_proba(_logit(bv[teb])[:, None])[:, 1]

        X = df[FEATURE_GROUPS["full"]]
        lr = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                           LogisticRegression(C=0.5, max_iter=2000))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lr.fit(X.iloc[tr], ytr)
        preds["logreg"][te] = lr.predict_proba(X.iloc[te])[:, 1]

        for name, cols in (("lgbm_ball_only", FEATURE_GROUPS["ball_only"]),
                           ("lgbm_on_ball", FEATURE_GROUPS["on_ball"]),
                           ("lgbm_full", FEATURE_GROUPS["full"])):
            mdl = _lgbm()
            mdl.fit(df[cols].iloc[tr], ytr)
            preds[name][te] = mdl.predict_proba(df[cols].iloc[te])[:, 1]

    for k, v in preds.items():
        df[f"p_{k}"] = v

    finite = {k: np.isfinite(v) for k, v in preds.items()}
    # Head-to-head: identical rows for every system (the built-in model only covers 2v2).
    common = np.all(list(finite.values()), axis=0)
    summary: dict = {"rows_total": int(len(df)), "matches": int(len(np.unique(groups))),
                     "folds": len(folds), "trained_on_modes": sorted(df["mode"].unique().tolist()),
                     "head_to_head": _scope(df, common, list(preds), n_boot, compare=True),
                     "by_mode": {}}
    for mode in sorted(df["mode"].unique()):
        mm = (df["mode"] == mode).to_numpy()
        systems = [k for k in preds if finite[k][mm].all()]
        summary["by_mode"][mode] = _scope(df, mm, systems, n_boot if mode != "2v2" else 0, compare=False)
    failures = failure_cases(df[common], "p_builtin_recal") if common.any() else {}
    return ValueResults(oof=df, summary=summary, failures=failures)


def _scope(df: pd.DataFrame, mask: np.ndarray, systems: list[str], n_boot: int, compare: bool) -> dict:
    sub = df[mask]
    if sub.empty:
        return {}
    ys, base = sub["y"].to_numpy().astype(float), sub["p_base_rate"].to_numpy()
    g = sub["match_id"].to_numpy()
    res = {"matches": int(sub["match_id"].nunique()), "modes": sorted(sub["mode"].unique().tolist()),
           "systems": {}}
    for k in systems:
        p = sub[f"p_{k}"].to_numpy()
        r = M.summarize(ys, p, base)
        if n_boot and k != "base_rate":
            r["brier_skill_ci95"] = M.match_bootstrap(
                g, lambda i, p=p: 1 - M.brier(ys[i], p[i]) / max(M.brier(ys[i], base[i]), 1e-12),
                n_boot=n_boot)
        res["systems"][k] = r
    if compare and n_boot:
        pb = sub["p_builtin_recal"].to_numpy()
        for k in ("lgbm_full", "heuristic", "lgbm_ball_only"):
            pk = sub[f"p_{k}"].to_numpy()
            res[f"brier_diff_{k}_minus_builtin_recal_ci95"] = M.match_bootstrap(
                g, lambda i, pk=pk: M.brier(ys[i], pk[i]) - M.brier(ys[i], pb[i]), n_boot=n_boot)
        pf, pbo = sub["p_lgbm_full"].to_numpy(), sub["p_lgbm_ball_only"].to_numpy()
        res["brier_diff_lgbm_full_minus_ball_only_ci95"] = M.match_bootstrap(
            g, lambda i: M.brier(ys[i], pf[i]) - M.brier(ys[i], pbo[i]), n_boot=n_boot)
    if "builtin_raw" in systems:
        res["reliability_builtin_raw"] = M.reliability(ys, sub["p_builtin_raw"].to_numpy())
    if "lgbm_full" in systems:
        res["reliability_lgbm_full"] = M.reliability(ys, sub["p_lgbm_full"].to_numpy())
    return res


def failure_cases(df: pd.DataFrame, col: str, k: int = 8, gap_s: float = 4.0) -> dict:
    """Most confident misses and false alarms, one per ``gap_s`` window, for human review."""
    def pick(sub: pd.DataFrame, ascending: bool) -> list[dict]:
        out, taken = [], []
        for _, r in sub.sort_values(col, ascending=ascending).iterrows():
            key = (r["match_id"], r["team"])
            if any(key == kk and abs(r["t"] - tt) < gap_s for kk, tt in taken):
                continue
            taken.append((key, r["t"]))
            out.append({"source": r["source"], "mode": r["mode"], "team": int(r["team"]),
                        "t": round(float(r["t"]), 2), "pred": round(float(r[col]), 4),
                        "ball_y": round(float(r["ball_y"]), 0), "ttb_adv": None if pd.isna(r["ttb_adv"]) else round(float(r["ttb_adv"]), 2),
                        "opp_goalside": float(r["opp_goalside"])})
            if len(out) >= k:
                break
        return out
    return {"model": col,
            "missed_goals": pick(df[df["y"] == 1], ascending=True),
            "false_alarms": pick(df[df["y"] == 0], ascending=False)}

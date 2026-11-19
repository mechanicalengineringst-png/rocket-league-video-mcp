"""Observational action value with negative controls: does challenging vs holding change the next seconds? (Round 13)

The counterfactual simulator could not separate challenge from restraint (counterfactual_study.py). This
study asks the data directly. For every Round 12 first-defender / loose-ball / offensive-first-man
situation (all players, all cached matches), using only decision-time state features:

  action    commit (R12 Stage B family "touch") vs hold ("hold": shadow, delay, goal-side hold)
  outcomes  danger_5s (ball within 2000 uu of our goal within 5 s), next_touch_own (3 s), goal_against_10s
  placebo   danger_before: the ball was within 2000 uu of our goal at some point in the 3 s BEFORE t0.
            The action cannot cause it, so any "effect" after adjusting for the t0 state is confounding.

Estimator: T-learner (separate gradient-boosted models for commit and hold rows) with leave-one-match-out
cross-fitting; per-situation effect = model_commit(x) - model_hold(x). Also: naive difference, propensity
overlap (how well the t0 state predicts the action), and the effect split by the R12 ledger's verdict.
Usage (from coach-app/): python scripts/action_value_study.py CACHE_DIR OUT.json
"""
from __future__ import annotations

import bisect
import glob
import hashlib
import json
import math
import pickle
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach_app.coach_report import analyze_moment  # noqa: E402
from coach_app.coaching_findings import observe_action  # noqa: E402
from coach_app.situations import discover_situations  # noqa: E402
from coach_app.state_features import frame_features, reach_times  # noqa: E402

warnings.filterwarnings("ignore")
GOAL_Y = 5120.0
CLASSES = ("first_defender", "loose_ball", "offensive_first_man")
OUTCOMES = ("danger_5s", "next_touch_own", "goal_against_10s", "danger_before_placebo")


def rows_for(path: str) -> list[dict]:
    d = pickle.loads(Path(path).read_bytes())
    team_of = {p["id"]: p["team"] for p in d["players"]}
    frames, ts = d["frames"], [f["t"] for f in d["frames"]]
    ev = d["events"]
    touches = sorted((e["t"], team_of.get(e.get("playerId"))) for e in ev if e["type"] == "touch" and e.get("playerId"))
    tt = [x[0] for x in touches]
    goals = sorted((e["t"], e.get("scoringTeam")) for e in ev if e["type"] == "goal_context")
    mid = hashlib.sha256(Path(path).stem.encode()).hexdigest()[:8]
    out = []
    for pid, team in team_of.items():
        s = 1 if team == "blue" else -1
        for sit in discover_situations(d, pid):
            sd = sit.to_dict()
            if sd["situation_class"] not in CLASSES:
                continue
            obs = observe_action(d, sd)
            if obs.get("family") not in ("touch", "hold"):
                continue
            t0 = sd["t0"]
            i = bisect.bisect_right(ts, t0) - 1
            fr = frames[i]
            f = frame_features(fr, team_of, team, reach=reach_times(fr))
            if f is None:
                continue
            reach = reach_times(fr)
            mate = next(p for p in team_of if team_of[p] == team and p != pid)
            f["focus_is_first"] = float((reach.get(pid) or 9) <= (reach.get(mate) or 9))
            fut = frames[i + 1:bisect.bisect_right(ts, t0 + 5.0)]
            past = frames[bisect.bisect_left(ts, t0 - 3.0):i]
            j = bisect.bisect_right(tt, t0)
            nxt = touches[j] if j < len(touches) and touches[j][0] <= t0 + 3.0 else None
            it = None
            try:
                it = analyze_moment(d, pid, sd)
            except Exception:  # noqa: BLE001
                pass
            st = (it or {}).get("rationale", {}).get("actions", {}) if it else {}
            ch = st.get("immediate_challenge", {}).get("status")
            hold = [st.get(a, {}).get("status") for a in ("shadow_delay", "goal_side_hold")]
            ledger = ("hold_over_challenge" if "supported" in hold and ch == "refuted" else
                      "challenge_over_hold" if ch == "supported" and "refuted" in hold else "neither")
            f.update({
                "match": mid, "t0": t0, "cls": sd["situation_class"], "action_commit": float(obs["family"] == "touch"),
                "ledger": ledger,
                "danger_5s": float(any(math.hypot(x["ball"]["x"], s * x["ball"]["y"] + GOAL_Y) < 2000 for x in fut)),
                "danger_before_placebo": float(any(math.hypot(x["ball"]["x"], s * x["ball"]["y"] + GOAL_Y) < 2000 for x in past)),
                "next_touch_own": float(nxt[1] == team) if nxt else float("nan"),
                "goal_against_10s": float(any(t0 < gt <= t0 + 10 and tm not in (None, team) for gt, tm in goals)),
            })
            out.append(f)
    return out


def _gbm():
    import lightgbm as lgb
    return lgb.LGBMClassifier(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=40,
                              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)


def analyse(df: pd.DataFrame) -> dict:
    from sklearn.metrics import roc_auc_score
    meta = {"match", "t0", "cls", "action_commit", "ledger", *OUTCOMES}
    X = [c for c in df.columns if c not in meta]
    res = {"situations": len(df), "matches": int(df["match"].nunique()), "commit_share": round(float(df["action_commit"].mean()), 3),
           "by_class": df["cls"].value_counts().to_dict(), "ledger_counts": df["ledger"].value_counts().to_dict()}
    # propensity overlap
    prop = np.zeros(len(df))
    for m in df["match"].unique():
        tr, te = df[df["match"] != m], df[df["match"] == m]
        prop[np.where(df["match"].values == m)[0]] = _gbm().fit(tr[X].astype(float), tr["action_commit"]).predict_proba(te[X].astype(float))[:, 1]
    res["propensity_auc"] = round(float(roc_auc_score(df["action_commit"], prop)), 3)
    res["propensity_extreme_share"] = round(float(((prop < 0.05) | (prop > 0.95)).mean()), 3)
    keep = (prop > 0.05) & (prop < 0.95)
    res["outcomes"] = {}
    for y in OUTCOMES:
        d = df[keep & ~df[y].isna()].copy()
        eff = np.full(len(d), np.nan)
        for m in d["match"].unique():
            tr, te = d[d["match"] != m], d[d["match"] == m]
            idx = np.where(d["match"].values == m)[0]
            c1, c0 = tr[tr["action_commit"] == 1], tr[tr["action_commit"] == 0]
            if c1[y].nunique() < 2 or c0[y].nunique() < 2:
                continue
            p1 = _gbm().fit(c1[X].astype(float), c1[y]).predict_proba(te[X].astype(float))[:, 1]
            p0 = _gbm().fit(c0[X].astype(float), c0[y]).predict_proba(te[X].astype(float))[:, 1]
            eff[idx] = p1 - p0
        d["eff"] = eff
        naive = d[d["action_commit"] == 1][y].mean() - d[d["action_commit"] == 0][y].mean()
        rng = np.random.default_rng(0)
        mids = d["match"].unique()
        boot = []
        for _ in range(400):
            sm = rng.choice(mids, len(mids))
            boot.append(np.nanmean(np.concatenate([d[d["match"] == m]["eff"].values for m in sm])))
        res["outcomes"][y] = {
            "n": int(len(d)), "naive_difference_commit_minus_hold": round(float(naive), 3),
            "adjusted_average_effect": round(float(np.nanmean(eff)), 3),
            "adjusted_95ci_match_bootstrap": [round(float(np.nanquantile(boot, 0.025)), 3), round(float(np.nanquantile(boot, 0.975)), 3)],
            "by_ledger": {k: {"n": int(len(x)), "mean_effect": round(float(np.nanmean(x["eff"])), 3) if len(x) else None}
                          for k, x in d.groupby("ledger")},
            "by_focus_first": {str(int(k)): {"n": int(len(x)), "mean_effect": round(float(np.nanmean(x["eff"])), 3)}
                               for k, x in d.groupby("focus_is_first")}}
    return res


def main(cache: Path, out: Path, workers: int = 2):
    files = sorted(glob.glob(str(cache / "*.pkl")))
    with ProcessPoolExecutor(workers) as ex:
        parts = list(ex.map(rows_for, files))
    df = pd.DataFrame([r for p in parts for r in p])
    df.to_pickle(out.with_suffix(".rows.pkl"))
    res = analyse(df)
    res["note"] = ("Observational, public cohort of unknown rank; effects are associations adjusted for the t0 state, "
                   "valid only if the placebo shows no effect.")
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))

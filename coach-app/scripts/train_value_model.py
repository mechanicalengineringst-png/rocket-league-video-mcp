"""Train FutureControlModel V0 (logistic, numpy-exportable) and write coach_app/models/future_control_v0.json.

Also reports leave-one-match-out metrics of exactly this exported form, so the shipped model's
held-out quality is recorded next to it.
Usage (from coach-app/): python scripts/train_value_model.py STATES.pkl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach_app.value_model import MODEL_PATH, FutureControlModel  # noqa: E402

LABELS = {"next_touch_own", "danger_5s", "opportunity_5s", "goal_against_10s", "goal_for_10s"}
META = {"match", "t", "team"}
HEADS = {"next_touch_own": "next_touch_own", "danger_5s": "danger_5s"}
C = 0.5


def fit_head(d: pd.DataFrame, target: str, cols: list[str]) -> dict:
    X = d[cols].astype(float)
    med = X.median().fillna(0.0)
    Xf = X.fillna(med)
    mu, sd = Xf.mean(), Xf.std().replace(0, 1.0).fillna(1.0)
    m = LogisticRegression(C=C, max_iter=3000).fit(((Xf - mu) / sd).values, d[target].values)
    return {"features": cols, "coef": [round(float(c), 6) for c in m.coef_[0]], "intercept": round(float(m.intercept_[0]), 6),
            "mean": [round(float(v), 6) for v in mu], "std": [round(float(v), 6) for v in sd],
            "median": [round(float(v), 6) for v in med]}


def main(states: Path):
    df = pd.read_pickle(states)
    cols = [c for c in df.columns if c not in LABELS | META]
    spec = {"version": "future-control/0.1", "trained_on": {"rows": len(df), "matches": int(df["match"].nunique()),
                                                          "cohort": "public 2v2 replays, unknown rank"},
            "heads": {}, "held_out": {},
            "use": "ranking and comparing states only; not shown to players as a percentage"}
    for head, target in HEADS.items():
        d = df[~df[target].isna()]
        p = np.zeros(len(d))
        for m in d["match"].unique():
            tr, te = d[d["match"] != m], d[d["match"] == m]
            h = fit_head(tr, target, cols)
            mdl = FutureControlModel({"version": "tmp", "heads": {head: h}})
            p[np.where(d["match"].values == m)[0]] = [mdl._head(h, r) for r in te[cols].to_dict("records")]
        y = d[target].values.astype(int)
        spec["held_out"][head] = {"log_loss": round(float(log_loss(y, np.clip(p, 1e-4, 1 - 1e-4))), 4),
                                  "brier": round(float(brier_score_loss(y, p)), 4), "auc": round(float(roc_auc_score(y, p)), 4),
                                  "base_rate": round(float(y.mean()), 3), "method": "leave-one-match-out, 15 folds"}
        spec["heads"][head] = fit_head(d, target, cols)
        print(head, spec["held_out"][head], flush=True)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text(json.dumps(spec))
    print("written", MODEL_PATH)


if __name__ == "__main__":
    main(Path(sys.argv[1]))

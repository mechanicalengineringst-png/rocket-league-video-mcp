"""Probability-forecast metrics and match-level bootstrap intervals."""
from __future__ import annotations

import numpy as np

EPS = 1e-6


def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, EPS, 1 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def auc(y: np.ndarray, p: np.ndarray) -> float | None:
    """Rank AUC with tie handling. None when only one class is present."""
    y = np.asarray(y)
    pos, neg = y == 1, y == 0
    if not pos.any() or not neg.any():
        return None
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    sp = np.asarray(p)[order]
    i = 0
    while i < len(sp):
        j = i
        while j + 1 < len(sp) and sp[j + 1] == sp[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    n1, n0 = pos.sum(), neg.sum()
    return float((ranks[pos].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def reliability(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    """Equal-width bins: mean prediction against observed rate, with counts."""
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    out = []
    for b in range(bins):
        sel = idx == b
        if sel.any():
            out.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "n": int(sel.sum()),
                        "mean_pred": float(p[sel].mean()), "observed": float(y[sel].mean())})
    return out


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    rows = reliability(y, p, bins)
    n = len(y)
    return float(sum(r["n"] / n * abs(r["mean_pred"] - r["observed"]) for r in rows))


def summarize(y: np.ndarray, p: np.ndarray, base_p: np.ndarray) -> dict:
    """Headline metrics. Brier skill is against a base rate fitted on training folds."""
    b = brier(y, p)
    bb = brier(y, base_p)
    return {
        "n_frames": int(len(y)), "positives": int(y.sum()), "log_loss": log_loss(y, p),
        "brier": b, "brier_skill_vs_base_rate": (1 - b / bb) if bb > 0 else None,
        "auc": auc(y, p), "ece": ece(y, p),
    }


def match_bootstrap(groups: np.ndarray, stat, n_boot: int = 1000, seed: int = 0) -> tuple[float, float]:
    """95% interval of ``stat(index_array)`` resampling whole matches with replacement.

    Frames within a match are strongly correlated; resampling frames would give
    intervals that are far too narrow.
    """
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    by_group = {g: np.flatnonzero(groups == g) for g in uniq}
    vals = []
    for _ in range(n_boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([by_group[g] for g in pick])
        v = stat(idx)
        if v is not None and np.isfinite(v):
            vals.append(v)
    if not vals:
        return (float("nan"), float("nan"))
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return (float(lo), float(hi))

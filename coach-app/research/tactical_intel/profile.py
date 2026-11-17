"""Personal adaptation without overfitting: empirical-Bayes shrinkage of per-player rates.

A player's raw rate from a handful of games is mostly noise. Each rate is pulled
toward the population rate by an amount set by how much the population varies.
A player with 3 attempts sits near the population; one with 300 sits near their
own record. Intervals stay honest about what is not known yet.

Used for any "k successes in n attempts" trait: challenge rate in a situation,
challenge success, aerial conversion, recovery within a time budget.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

MIN_PRIOR_STRENGTH = 2.0
MAX_PRIOR_STRENGTH = 200.0


@dataclass(frozen=True)
class BetaPrior:
    alpha: float
    beta: float

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def strength(self) -> float:
        return self.alpha + self.beta


def fit_prior(successes: np.ndarray, trials: np.ndarray) -> BetaPrior:
    """Method-of-moments beta prior from many players' records.

    Strength (alpha + beta) is how many attempts a player needs before their own
    record outweighs the population. It is clipped to a sane range because the
    moment estimate is unstable with few players.
    """
    successes = np.asarray(successes, float)
    trials = np.asarray(trials, float)
    keep = trials > 0
    s, n = successes[keep], trials[keep]
    if len(n) == 0:
        return BetaPrior(1.0, 1.0)
    p = s / n
    mu = float(np.clip(np.sum(s) / np.sum(n), 1e-3, 1 - 1e-3))
    if len(n) < 3:
        k = MIN_PRIOR_STRENGTH
    else:
        observed_var = float(np.average((p - mu) ** 2, weights=n))
        binomial_var = float(mu * (1 - mu) * np.mean(1.0 / n))
        between = max(observed_var - binomial_var, 1e-6)
        k = mu * (1 - mu) / between - 1.0
    k = float(np.clip(k, MIN_PRIOR_STRENGTH, MAX_PRIOR_STRENGTH))
    return BetaPrior(mu * k, (1 - mu) * k)


@dataclass(frozen=True)
class ShrunkRate:
    successes: int
    trials: int
    raw: float | None
    estimate: float
    low90: float
    high90: float
    weight_on_player: float


def shrink(successes: int, trials: int, prior: BetaPrior) -> ShrunkRate:
    a, b = prior.alpha + successes, prior.beta + (trials - successes)
    lo, hi = stats.beta.ppf([0.05, 0.95], a, b)
    return ShrunkRate(
        successes=int(successes), trials=int(trials),
        raw=(successes / trials) if trials else None,
        estimate=float(a / (a + b)), low90=float(lo), high90=float(hi),
        weight_on_player=float(trials / (trials + prior.strength)),
    )


def distinguishable(x: ShrunkRate, y: ShrunkRate) -> bool:
    """True only when the two 90% intervals do not overlap. Deliberately conservative."""
    return x.high90 < y.low90 or y.high90 < x.low90

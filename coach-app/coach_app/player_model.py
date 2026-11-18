"""Cross-match player model (Round 5, checkpoint 4).

Keeps four things apart that are easy to blur:

- **preferences / tendencies**: how often the player picks an option when it is
  available (e.g. challenge vs delay in first-defender moments). Not good or bad.
- **decision consistency**: how often the choice fits the t0 situation under the
  stated principle (reinforce vs risk_hypothesis), per situation type.
- **mechanical execution**: decoder whiffs against touches. Separate from decisions:
  a correct decision can be badly executed and vice versa.
- **team context**: how often the teammate could cover when the player was first defender.

Every rate is a Beta posterior shrunk toward the pooled rate of all players in
the dataset (empirical Bayes, prior strength ``PRIOR_N``), with a 90% interval.
A "recurring pattern" needs at least ``MIN_N`` judged moments across ``MIN_MATCHES``
matches *and* an interval that excludes the pooled rate. Otherwise the answer is
"not established", whatever the raw count says. Nothing here says a player
cannot improve: rates describe these matches only.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

PRIOR_N = 6.0
MIN_N = 8
MIN_MATCHES = 3
MODEL_VERSION = "player-model/0.1"


def _beta_quantile(a: float, b: float, q: float) -> float:
    """Quantile of Beta(a, b) by bisection on a numerically integrated CDF (no SciPy needed)."""
    import math
    n = 2000
    xs = [(i + 0.5) / n for i in range(n)]
    logc = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    dens = [math.exp(logc + (a - 1) * math.log(x) + (b - 1) * math.log(1 - x)) / n for x in xs]
    total, acc = sum(dens), 0.0
    for x, w in zip(xs, dens):
        acc += w / total
        if acc >= q:
            return x
    return 1.0


@dataclass
class Rate:
    label: str
    k: int
    n: int
    matches: int
    pooled: float | None
    mean: float | None = None
    lo90: float | None = None
    hi90: float | None = None
    status: str = "insufficient"          # insufficient | consistent_with_pool | above_pool | below_pool

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def shrunk_rate(label: str, k: int, n: int, matches: int, pooled: float | None) -> Rate:
    r = Rate(label, k, n, matches, None if pooled is None else round(pooled, 3))
    if n == 0 or pooled is None:
        return r
    p = min(max(pooled, 0.02), 0.98)
    a, b = k + PRIOR_N * p, (n - k) + PRIOR_N * (1 - p)
    r.mean = round(a / (a + b), 3)
    r.lo90, r.hi90 = round(_beta_quantile(a, b, 0.05), 3), round(_beta_quantile(a, b, 0.95), 3)
    if n < MIN_N or matches < MIN_MATCHES:
        r.status = "insufficient"
    elif r.lo90 > pooled:
        r.status = "above_pool"
    elif r.hi90 < pooled:
        r.status = "below_pool"
    else:
        r.status = "consistent_with_pool"
    return r


@dataclass
class Observation:
    """One reviewed moment for the model. Built from a Finding plus its match id."""
    player_id: str
    match_id: str
    situation: str
    verdict: str
    choice: str | None
    factors: dict[str, Any] = field(default_factory=dict)


def observations_from(findings: list, player_id: str, match_id: str) -> list[Observation]:
    return [Observation(player_id, match_id, f.situation, f.verdict, f.reviewed_action, dict(f.factors)) for f in findings]


def execution_counts(events: list[dict], player_id: str) -> tuple[int, int]:
    """(whiffs, touches) from decoder events; the decoder's definitions, unvalidated here."""
    w = sum(1 for e in events if e.get("type") == "whiff" and e.get("playerId") == player_id)
    t = sum(1 for e in events if e.get("type") == "touch" and e.get("playerId") == player_id)
    return w, t


def _matches(obs: list[Observation]) -> int:
    return len({o.match_id for o in obs})


def build_profile(player_id: str, all_obs: list[Observation],
                  execution: dict[str, list[tuple[str, int, int]]] | None = None) -> dict[str, Any]:
    """Profile for ``player_id``; ``all_obs`` holds every player's observations (for pooled rates).

    ``execution`` maps player -> [(match_id, whiffs, touches), ...].
    """
    mine = [o for o in all_obs if o.player_id == player_id]
    out: dict[str, Any] = {"player_id": player_id, "model": MODEL_VERSION, "moments": len(mine),
                           "matches": _matches(mine), "preferences": {}, "decision_consistency": {},
                           "execution": {}, "team_context": {}, "patterns": [],
                           "notes": ["Rates describe these matches only and say nothing about ability to improve.",
                                     "Shrunk toward the pooled rate of all players in this dataset; "
                                     f"patterns need {MIN_N}+ moments in {MIN_MATCHES}+ matches."]}

    def pooled(pred_all, pred_hit):
        pool = [o for o in all_obs if pred_all(o)]
        return (sum(pred_hit(o) for o in pool) / len(pool)) if pool else None

    # preferences: challenge vs delay when a first-defender moment arises
    is_def = lambda o: o.situation == "defender_decision" and o.choice in ("challenge", "shadow", "retreat")  # noqa: E731
    is_ch = lambda o: o.choice == "challenge"  # noqa: E731
    d = [o for o in mine if is_def(o)]
    out["preferences"]["challenges_as_first_defender"] = shrunk_rate(
        "Chooses to challenge (vs shadow/retreat) as first defender", sum(map(is_ch, d)), len(d), _matches(d),
        pooled(is_def, is_ch)).to_dict()
    for cond, name in (((True, True), "contest_and_cover"), ((False, False), "late_and_uncovered")):
        sel = lambda o, c=cond: is_def(o) and (o.factors.get("contest_in_time"), o.factors.get("teammate_can_cover")) == c  # noqa: E731
        dd = [o for o in mine if sel(o)]
        out["preferences"][f"challenges_when_{name}"] = shrunk_rate(
            f"Challenges when {name.replace('_', ' ')}", sum(map(is_ch, dd)), len(dd), _matches(dd),
            pooled(sel, is_ch)).to_dict()

    # decision consistency per situation: share of judged moments flagged as risk
    by_sit: dict[str, list[Observation]] = defaultdict(list)
    for o in mine:
        if o.verdict in ("reinforce", "tradeoff", "risk_hypothesis", "missed_opportunity_hypothesis"):
            by_sit[o.situation].append(o)
    for sit, obs in sorted(by_sit.items()):
        concern = lambda o: o.verdict in ("risk_hypothesis", "missed_opportunity_hypothesis")  # noqa: E731
        judged = lambda o, s=sit: o.situation == s and o.verdict in ("reinforce", "tradeoff", "risk_hypothesis", "missed_opportunity_hypothesis")  # noqa: E731
        r = shrunk_rate(f"{sit.replace('_', ' ')}: moments flagged as a concern", sum(map(concern, obs)), len(obs),
                        _matches(obs), pooled(judged, concern))
        out["decision_consistency"][sit] = r.to_dict()
        if r.status == "above_pool":
            out["patterns"].append({"kind": "decision", "situation": sit, "rate": r.to_dict(),
                                    "wording": f"In these {r.matches} matches, {sit.replace('_', ' ')} moments were "
                                               f"flagged more often than for other players here ({r.k} of {r.n})."})

    # execution
    if execution:
        rows = execution.get(player_id, [])
        w, t = sum(x[1] for x in rows), sum(x[2] for x in rows)
        all_w = sum(x[1] for v in execution.values() for x in v)
        all_t = sum(x[2] for v in execution.values() for x in v)
        r = shrunk_rate("Whiffs per attempted touch (decoder 'whiff' events)", w, w + t, len(rows),
                        all_w / (all_w + all_t) if all_w + all_t else None)
        out["execution"]["whiff_rate"] = r.to_dict()
        if r.status == "above_pool":
            out["patterns"].append({"kind": "execution", "rate": r.to_dict(),
                                    "wording": f"Missed touches were more frequent than for other players here ({w} whiffs, {t} touches)."})

    # team context
    cov = [o for o in d if o.factors.get("teammate_can_cover") is not None]
    is_cov = lambda o: o.factors.get("teammate_can_cover") is True  # noqa: E731
    out["team_context"]["teammate_could_cover"] = shrunk_rate(
        "Teammate could get goal-side in time when this player was first defender", sum(map(is_cov, cov)), len(cov),
        _matches(cov), pooled(lambda o: is_def(o) and o.factors.get("teammate_can_cover") is not None, is_cov)).to_dict()
    return out


def practice_priority(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Order established patterns by how far the interval sits above the pool. Empty if none is established."""
    items = []
    for p in profile.get("patterns", []):
        r = p["rate"]
        gap = (r["lo90"] or 0) - (r["pooled"] or 0)
        items.append({"kind": p["kind"], "situation": p.get("situation"), "wording": p["wording"],
                      "evidence": f"{r['k']} of {r['n']} in {r['matches']} matches; 90% interval {r['lo90']}-{r['hi90']} "
                                  f"vs pooled {r['pooled']}", "margin_above_pool": round(gap, 3)})
    return sorted(items, key=lambda x: -x["margin_above_pool"])

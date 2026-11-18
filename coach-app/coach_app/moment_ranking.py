"""Quality-aware selection of coaching moments from decision-time information only (Round 12).

Salience is NOT merit. A high score means "a coach would want to look at this and the system can say
something specific about it", never "the player made a mistake". Inputs are the situation (t0
frame features) and its Stage A rationale ledger; nothing after t0 (no touches, goals or observed
actions) enters the score, so a moment is never chosen because it went badly.

Components (each 0..1, weights are editorial and documented, not fitted):
- responsibility  how directly the decision falls on the focus player (class, last man, ball near own goal)
- teachable       distinguishable alternatives: at least one supported and one argued-against option,
                  or several defensible families (a "good restraint/aggression" moment counts)
- sufficiency     share of the ledger's conditions that are established (holds/fails) rather than uncertain
- recurrence      the same class and the same deciding conditions recur in this match (a pattern, not a verdict)
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .action_rationale import FAILS, HOLDS

VERSION = "moment-ranking/0.1"
WEIGHTS = {"responsibility": 0.30, "teachable": 0.30, "sufficiency": 0.25, "recurrence": 0.15}
CLASS_RESPONSIBILITY = {"first_defender": 1.0, "possession": 0.8, "second_man_support": 0.7, "offensive_first_man": 0.7,
                        "loose_ball": 0.6, "recovery_and_boost": 0.5, "aerial_or_wall": 0.2}
MIN_SEPARATION_S = 6.0
PER_CLASS_FIRST_PASS = 2


def signature(rationale: dict) -> tuple:
    """Pattern key: class + established conditions that decide at least one action."""
    cond = rationale.get("conditions", {})
    used = set()
    for a in rationale.get("actions", {}).values():
        for r in a["reasons"]:
            if r["status"] in ("satisfied", "refuted"):
                used |= {p["condition"].lstrip("!") for p in r["premises"] if p["status"] in (HOLDS, FAILS)}
    return (rationale.get("situation_class"),) + tuple(sorted(f"{c}={cond[c]['status']}" for c in used if c in cond))


def score(situation: dict, rationale: dict, recurrence: int) -> dict[str, Any]:
    cls = situation["situation_class"]
    v = situation.get("values", {})
    resp = CLASS_RESPONSIBILITY.get(cls, 0.3)
    cond = rationale.get("conditions", {})
    if cond.get("teammate_deeper", {}).get("status") == FAILS and cls in ("first_defender", "loose_ball"):
        resp = min(1.0, resp + 0.1)              # the focus player is the last line
    by = v.get("ball_rel_y")
    if isinstance(by, (int, float)) and by < -2500 and cls in ("first_defender", "loose_ball", "second_man_support"):
        resp = min(1.0, resp + 0.1)
    sigs = Counter(a["status"] for a in rationale.get("actions", {}).values())
    fams = set()
    from .coaching_findings import ACTIONS
    for a, x in rationale.get("actions", {}).items():
        if x["status"] == "supported":
            fams.add(ACTIONS.get(a, {}).get("family", a))
    teach = 1.0 if (sigs["supported"] and (sigs["refuted"] or sigs["contested"])) else 0.8 if len(fams) >= 2 else \
        0.4 if sigs["supported"] or sigs["conditional"] >= 2 else 0.0
    real = [c for c in cond.values() if c.get("kind") != "unobservable"]
    suff = sum(c["status"] in (HOLDS, FAILS) for c in real) / len(real) if real else 0.0
    rec = min(1.0, (recurrence - 1) / 3) if recurrence > 1 else 0.0
    parts = {"responsibility": round(resp, 2), "teachable": teach, "sufficiency": round(suff, 2), "recurrence": round(rec, 2)}
    total = sum(WEIGHTS[k] * parts[k] for k in WEIGHTS)
    if rationale.get("judgment") == "withheld":
        total *= 0.5
    return {"score": round(total, 3), "components": parts, "weights": WEIGHTS, "version": VERSION,
            "uses_future": False, "is_merit": False,
            "why_selected": _why(parts, recurrence)}


def _why(parts, recurrence) -> list[str]:
    out = []
    if parts["responsibility"] >= 0.8:
        out.append("the decision fell directly on you")
    if parts["teachable"] >= 0.8:
        out.append("the options were clearly distinguishable at decision time")
    if parts["sufficiency"] >= 0.7:
        out.append("most deciding conditions were measurable")
    if recurrence >= 3:
        out.append(f"a similar situation came up {recurrence} times in this match")
    return out or ["a representative decision of this kind"]


def rank(items: list[dict], max_findings: int = 6) -> list[dict]:
    """items: [{'situation', 'rationale'}]. Returns selected items with 'salience', class-diverse and separated."""
    sig_count = Counter(signature(it["rationale"]) for it in items)
    for it in items:
        it["salience"] = score(it["situation"], it["rationale"], sig_count[signature(it["rationale"])])
        it["salience"]["pattern_count"] = sig_count[signature(it["rationale"])]
    ordered = sorted(items, key=lambda it: (-it["salience"]["score"], it["situation"]["t0"]))
    chosen: list[dict] = []
    per_class: Counter = Counter()

    def ok(it, cap):
        t = it["situation"]["t0"]
        return per_class[it["situation"]["situation_class"]] < cap and all(abs(t - c["situation"]["t0"]) >= MIN_SEPARATION_S for c in chosen)

    for cap in (PER_CLASS_FIRST_PASS, 10 ** 6):
        for it in ordered:
            if len(chosen) >= max_findings:
                break
            if it in chosen or it["situation"]["situation_class"] == "aerial_or_wall" or not ok(it, cap):
                continue
            chosen.append(it)
            per_class[it["situation"]["situation_class"]] += 1
    return sorted(chosen, key=lambda it: it["situation"]["t0"])

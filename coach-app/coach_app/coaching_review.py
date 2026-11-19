"""CoachingReviewV1: a few high-value moments for the viewer side panel (Round 15).

Not a new tactical system. It is a strict, compact projection of the existing pipeline:
situations -> decision-time ledger (Round 12, with the Round 13 ``r13`` adjustments) -> Stage A finding
(validated claims, traced numbers) -> Stage B observed action (movement label) -> outcome kept apart.

What it adds is discipline:
- at most ``MAX_MOMENTS`` moments, spread across the match, mixing good decisions, possible mistakes,
  trade-offs and possible missed opportunities, and nothing when the evidence is weak;
- a category is only assigned when the decision-time read is firm enough (``_categorise``); everything
  else is counted as abstained, not shown as a vague card;
- every moment must carry at least two replay-specific numbers and must not repeat another moment's
  wording (the "could this be pasted into another replay?" test);
- a clip interval inside live play (no kickoff countdown or post-goal replay);
- each field is labelled with its basis: replay measurement, kinematic estimate, rule heuristic,
  movement label. Nothing here is statistical, model-generated, or expert-validated.
"""
from __future__ import annotations

import bisect
import re
from typing import Any

from .action_rationale import FAILS, HOLDS
from .coach_report import _validate, analyze_moment
from .coaching_findings import ACTIONS, CLASS_LABEL, build_stage_a, build_stage_b
from .moment_ranking import score as salience_score
from .moment_ranking import signature
from .situation_rationale import SituationRationaleError
from .situations import discover_situations

SCHEMA = "CoachingReviewV1"
VERSION = "coaching-review/0.1"
MAX_MOMENTS = 5
MIN_SEPARATION_S = 10.0
PRE_ROLL_S, POST_ROLL_S = 4.0, 3.0
MIN_SPECIFIC_NUMBERS = 2
NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
BUDGET = {"headline": 90, "situation": 260, "assessment": 300, "option": 170, "uncertainty": 160}
ATTACK_ACTIONS = {"immediate_challenge", "controlled_touch", "shoot_now", "pass_or_center", "push_forward", "aggressive_follow_up"}
# A mistake label needs a RISK that is present at t0, not merely the absence of a modelled reason
# (e.g. "refuted because you had 66 boost" is not a mistake: rotating can be positional).
RISK_PRESENT = {"teammate_covers": FAILS, "threat_now": HOLDS, "double_commit_risk": HOLDS,
                "play_uncovered_if_lost": HOLDS, "focus_covers_teammate": FAILS, "boost_route_keeps_cover": FAILS,
                "room_to_delay": FAILS}
CATEGORY_ORDER = ("good_decision", "possible_mistake", "tradeoff", "possible_missed_opportunity")
CATEGORY_LABEL = {"good_decision": "Good decision", "possible_mistake": "Possible mistake (unconfirmed)",
                  "tradeoff": "Defensible trade-off", "possible_missed_opportunity": "Possible missed opportunity"}
BASIS = {
    "situation": "replay_measurement + kinematic_estimate (decoded positions/velocities; arrival times are model estimates)",
    "assessment": "rule_heuristic (Round 12 condition ledger with Round 13 adjustments; not expert-validated)",
    "options": "rule_heuristic",
    "your_choice": "movement_label (what the car did in the next 2.5 s; not intent)",
    "outcome": "replay_measurement (touches and goals after t0; never used to assess the decision)",
}


def _clip(text: str | None, n: int) -> str | None:
    if text is None:
        return None
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip(" ,;:") + "…"


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _live_window(replay: dict, t0: float) -> tuple[float, float]:
    """Clip bounds inside live play: after the last kickoff (+0.5 s) and before the next goal."""
    frames = replay["frames"]
    first, last = frames[0]["t"], frames[-1]["t"]
    ev = replay.get("events", [])
    kicks = [e["t"] for e in ev if e.get("type") == "kickoff" and isinstance(e.get("t"), (int, float)) and e["t"] <= t0]
    goals_after = [e["t"] for e in ev if e.get("type") == "goal_context" and isinstance(e.get("t"), (int, float)) and e["t"] > t0]
    lo = max([first] + [k + 0.5 for k in kicks])
    hi = min([last] + goals_after)
    return max(lo, t0 - PRE_ROLL_S), min(hi, t0 + POST_ROLL_S)


def _frame_time(replay: dict, t0: float) -> float:
    ts = [f["t"] for f in replay["frames"]]
    return ts[max(0, bisect.bisect_right(ts, t0 + 1e-9) - 1)]


def _categorise(fa: dict, fb: dict, rationale: dict) -> str | None:
    """Assign a category only when the decision-time read is firm; return None to abstain."""
    obs = fb.get("observed_action", {})
    v = fb.get("assessment", {}).get("verdict")
    if not obs.get("label") or fa.get("kind") in (None, "observation_only", "hard_to_judge"):
        return None
    if rationale.get("ledger_adjustments"):
        return None                                        # the read itself was downgraded by falsification
    cond = rationale.get("conditions", {})
    alts = {a["action"]: a for a in fa["alternatives"]}
    supported = [a for a in fa["alternatives"] if a["status"] == "supported"]
    chosen_status = alts.get(obs["label"], {}).get("status")
    flips = any(obs["label"] in (d.get("if_true") or {}) or obs["label"] in (d.get("if_false") or {})
                for d in rationale.get("decisive_information", []))
    passive = obs.get("family") in ("hold", "keep", "support", "direct", "small_pads")
    if v == "sound" and fa["kind"] == "clear_read":
        if flips:
            return "tradeoff"                              # an unknown could change the read of this very choice
        if chosen_status != "supported":
            return "tradeoff" if chosen_status == "conditional" else None   # only a sibling action was supported
        if obs.get("family") in ("touch", "support_close", "push") and cond.get("teammate_covers", {}).get("status") not in (HOLDS, None):
            return "tradeoff"                              # an aggressive touch is not praised without cover behind it
        return "good_decision"
    if v == "sound" and fa["kind"] == "several_defensible":
        return "tradeoff"
    if v == "questionable" and passive and fa["kind"] == "clear_read" and not rationale.get("decisive_information") \
            and any(a["action"] in ATTACK_ACTIONS for a in supported):
        return "possible_missed_opportunity"               # holding back is never called a mistake
    if v == "questionable" and fa["kind"] == "clear_read" and not rationale.get("decisive_information"):
        x = alts.get(obs["label"])
        fails = [p for b in (x or {}).get("ruled_out_because", []) for p in b.get("fails_because", [])]
        prem = [p for a in (x or {}).get("why", []) for p in a.get("uncertain_premises", [])]
        risk = [c for c, bad in RISK_PRESENT.items() if cond.get(c, {}).get("status") == bad]
        if fails and not prem and risk:
            return "possible_mistake"
        return None                                       # argued against, but no present risk: not called a mistake
    if passive and fa["kind"] == "clear_read":
        att = [a for a in supported if a["action"] in ATTACK_ACTIONS]
        if att and not rationale.get("decisive_information") and \
                (att[0]["action"] == "shoot_now" or cond.get("teammate_covers", {}).get("status") == HOLDS):
            return "possible_missed_opportunity"
    return None


def _first(frags: list[dict]) -> str | None:
    return next((f["text"] for f in frags if f["status"] == "applies"), None)


def _options(fa: dict, chosen: str | None) -> list[dict]:
    """The chosen action plus up to two contrasting alternatives from other families."""
    alts = fa["alternatives"]
    out, fams = [], set()
    pick = [a for a in alts if a["action"] == chosen] + [a for a in alts if a["status"] == "supported"] + \
           [a for a in alts if a["status"] in ("refuted", "contested")] + [a for a in alts if a["status"] == "conditional"]
    for a in pick:
        if a["family"] in fams:
            continue
        fams.add(a["family"])
        plus = _first(a["gains"]) or _first(a["preserves"])
        minus = _first(a["risks"]) or _first(a["sacrifices"])
        out.append({"action": a["action"], "label": a["label"], "status_at_t0": a["status"], "chosen": a["action"] == chosen,
                    "for": _clip(plus, BUDGET["option"]), "against": _clip(minus, BUDGET["option"])})
        if len(out) == 3:
            break
    return out


def _situation_text(fa: dict) -> str:
    ctx = [c for c in fa["decision_context"] if c.get("reading") and c["status"] in (HOLDS, FAILS)]
    numbered = [c for c in ctx if NUM.search(c["reading"])]
    parts = (numbered + [c for c in ctx if c not in numbered])[:3]
    txt = "; ".join(c["reading"] for c in parts)
    return txt[:1].upper() + txt[1:] + "." if txt else ""


def _assessment(cat: str, fa: dict, fb: dict) -> str:
    obs = fb["observed_action"]["label"]
    label = ACTIONS.get(obs, {}).get("label", obs).lower()
    alts = {a["action"]: a for a in fa["alternatives"]}
    sup = [a for a in fa["alternatives"] if a["status"] == "supported"]
    if cat == "good_decision":
        w = (alts.get(obs) or (sup[0] if sup else {})).get("why", [{}])
        prem = "; ".join(w[0].get("premises", [])[:2]) if w else ""
        return f"You chose to {label}, which fits the read at the moment: {prem}."
    if cat == "tradeoff":
        fam = alts.get(obs, {}).get("family")
        others = [a["label"].lower() for a in sup if a["action"] != obs and a["family"] != fam][:1] or \
                 [a["label"].lower() for a in sup if a["action"] != obs][:1]
        dec = fa["assumptions"]["decisive"]
        q = f" Deciding question: {dec[0]['question'].replace('whether if ', 'whether, if ')}." if dec else ""
        return f"You chose to {label}; {others[0] if others else 'another option'} was also defensible.{q}"
    if cat == "possible_mistake":
        why = "; ".join(p for b in alts[obs]["ruled_out_because"] for p in b["fails_because"][:2])
        return (f"You chose to {label}, but the read argued against it ({why}); {sup[0]['label'].lower()} was supported. "
                "Rule-based and unconfirmed.")
    att = next(a for a in sup if a["action"] in ATTACK_ACTIONS)
    prem = "; ".join(att["why"][0]["premises"][:2]) if att["why"] else ""
    return f"{att['label']} was available ({prem}), and you chose to {label}. A possible missed chance, not a confirmed mistake."


def _uncertainty(fa: dict) -> list[str]:
    out = [f"Unknown: {d['question'].replace('whether if ', 'whether, if ')}" for d in fa["assumptions"]["decisive"][:1]]
    unobs = [u["condition"].replace("_", " ") for u in fa["assumptions"]["unobservable"][:2]]
    if unobs:
        out.append("Not observable in replay data: " + ", ".join(unobs))
    out.append("No expert has validated this read; arrival times are kinematic estimates.")
    return [_clip(x, BUDGET["uncertainty"]) for x in out]


def _template(text: str) -> str:
    return NUM.sub("#", text)


def build_moment(replay: dict, focus: str, it: dict, *, moment_id: str) -> dict | None:
    sit = it["situation"]
    fa = build_stage_a(sit, it["rationale"], it["packet"], finding_id=moment_id)
    _validate(fa, it["packet"])
    if fa.get("status") != "ok":
        return None
    fb = build_stage_b(fa, replay, sit)
    cat = _categorise(fa, fb, it["rationale"])
    if cat is None:
        return None
    situation = _situation_text(fa)
    assessment = _assessment(cat, fa, fb)
    specific = len(NUM.findall(situation + " " + assessment))
    if specific < MIN_SPECIFIC_NUMBERS:
        return None                                        # would read the same in any replay
    t0 = _frame_time(replay, sit["t0"])
    lo, hi = _live_window(replay, t0)
    obs = fb["observed_action"]
    out = fb["outcome"]
    return {
        "id": moment_id, "category": cat, "category_label": CATEGORY_LABEL[cat],
        "t0": t0, "clip": {"start": round(lo, 3), "decision": t0, "end": round(hi, 3)},     # t0 = exact recorded frame time
        "headline": _clip(f"{_mmss(t0)} {CLASS_LABEL[sit['situation_class']].split(':')[0]}", BUDGET["headline"]),
        "situation_class": sit["situation_class"],
        "situation": _clip(situation, BUDGET["situation"]),
        "your_choice": {"label": ACTIONS.get(obs["label"], {}).get("label", obs["label"]), "basis": BASIS["your_choice"]},
        "assessment": _clip(assessment, BUDGET["assessment"]),
        "options": _options(fa, obs["label"]),
        "uncertainty": _uncertainty(fa),
        "evidence": [{"condition": c["condition"], "status": c["status"], "reading": c["reading"], "refs": c["evidence"][:4]}
                     for c in fa["decision_context"] if c.get("reading")][:6],
        "numbers": {k: {"value": v["value"], "refs": v["refs"]} for k, v in fa["numbers"].items()},
        "outcome_after": {"shown_separately": True, "used_in_assessment": False,
                          "touch_sequence": out["touch_sequence"][:4], "goal_within_5s": out["goal"]},
        "basis": BASIS, "_template": _template(assessment), "_salience": it["salience"]["score"],
        "_pattern": (cat, sit["situation_class"], obs["label"],
                     tuple(sorted({a["family"] for a in fa["alternatives"] if a["status"] == "supported"}))),
    }


def review_moment_at(replay: dict[str, Any], focus: str, t0: float) -> dict[str, Any]:
    """Review one chosen time (e.g. a moment the player picks). Returns the moment or an explicit abstention."""
    from .situations import classify_frame
    ts = [f["t"] for f in replay.get("frames", [])]
    i = bisect.bisect_right(ts, t0 + 1e-6) - 1
    if i < 0 or t0 - ts[i] > 0.15:
        return {"status": "abstain", "reason": "No recorded frame at that time."}
    sit = classify_frame(replay["frames"][i], replay.get("players", []), focus)
    if sit is None:
        return {"status": "abstain", "reason": "No supported decision situation at that time (or a car is missing)."}
    sit.t0 = ts[i]
    it = analyze_moment(replay, focus, sit.to_dict(), ledger="r13")
    if not it:
        return {"status": "abstain", "reason": "Not enough replay before this time."}
    it["salience"] = {"score": None}
    m = build_moment(replay, focus, it, moment_id="M1")
    if m is None:
        return {"status": "abstain", "situation_class": sit.situation_class,
                "reason": "The decision-time evidence is not firm or specific enough to assess this choice."}
    for k in ("_template", "_salience", "_pattern"):
        m.pop(k, None)
    return {"status": "ok", "moment": m}


def build_review(replay: dict[str, Any], focus: str, *, max_moments: int = MAX_MOMENTS) -> dict[str, Any]:
    players = {p["id"]: p for p in replay.get("players", [])}
    if focus not in players:
        raise ValueError("Unknown focus player.")
    if not 1 <= max_moments <= MAX_MOMENTS:
        raise ValueError(f"max_moments must be 1-{MAX_MOMENTS}.")
    sits = discover_situations(replay, focus)
    items = []
    for s in sits:
        try:
            it = analyze_moment(replay, focus, s.to_dict(), ledger="r13")
        except (SituationRationaleError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError):
            continue
        if it:
            items.append(it)
    sigs = {}
    for it in items:
        sigs[signature(it["rationale"])] = sigs.get(signature(it["rationale"]), 0) + 1
    for it in items:
        it["salience"] = salience_score(it["situation"], it["rationale"], sigs[signature(it["rationale"])])
    cands = []
    for k, it in enumerate(sorted(items, key=lambda x: -x["salience"]["score"])):
        m = build_moment(replay, focus, it, moment_id=f"m{k}")
        if m:
            cands.append(m)
    chosen: list[dict] = []

    def ok(m):
        return all(abs(m["t0"] - c["t0"]) >= MIN_SEPARATION_S and m["_template"] != c["_template"]
                   and m["_pattern"][:2] + m["_pattern"][3:] != c["_pattern"][:2] + c["_pattern"][3:] for c in chosen)

    for cat in CATEGORY_ORDER:                              # one of each category first, best salience
        m = next((m for m in cands if m["category"] == cat and ok(m)), None)
        if m and len(chosen) < max_moments:
            chosen.append(m)
    for m in cands:                                         # then fill by salience
        if len(chosen) >= max_moments:
            break
        if m not in chosen and ok(m):
            chosen.append(m)
    chosen.sort(key=lambda m: m["t0"])
    for i, m in enumerate(chosen, 1):
        m["id"] = f"M{i}"
        m.pop("_template", None)
        m.pop("_salience", None)
        m.pop("_pattern", None)
    counts = {c: sum(m["category"] == c for m in cands) for c in CATEGORY_ORDER}
    return {
        "schema": SCHEMA, "version": VERSION, "experimental": True, "expert_validated": False,
        "player_team": players[focus].get("team"),
        "moments": chosen,
        "coverage": {"situations_found": len(sits), "situations_analysed": len(items),
                     "eligible_by_category": counts, "abstained": len(items) - len(cands),
                     "abstention_reason": "No firm decision-time read, a falsification-downgraded premise, too few "
                                          "replay-specific numbers, or aerial/wall mechanics (not modelled)."},
        "not_included": ["habit claims (one match is not enough; see V2 reliability study)",
                         "turning-point attributions and earlier-cause hypotheses (associations, not causes)",
                         "probabilities or model scores"],
        "method": {"model_called": False, "future_frames_in_assessment": False, "ledger": "r13",
                   "selection": "decision-time salience within categories; categories use the observed action, never "
                                "the outcome"},
    }

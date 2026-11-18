"""ActionRationaleV0: why several actions can be reasonable, and what would change that (Round 11).

Round 10 showed that V1's single stance per action did not separate later outcomes. This module
replaces the stance with a *condition ledger* (an assumption-based reasoning scheme):

- Each tactical **condition** (e.g. "the focus player gets there first", "the teammate covers",
  "the contact goes away from their second player") is evaluated from t0 evidence to one of:
  ``holds`` / ``fails`` (beyond the calibrated model error), ``within_error`` (measured but inside
  the error band), ``unknown`` (input missing) or ``unobservable`` (no replay can show it: contact
  angle, comms, camera, flip, intent).
- Each action has one or more **reasons** it can be right (all conditions in a reason must hold) and
  **defeaters** that make it wrong. An action is
  ``supported`` (some reason is fully established by evidence),
  ``conditional`` (some reason has no failing condition but rests on named uncertain premises),
  ``refuted`` (every reason has a failing condition) - and its defeaters are listed as present,
  possible or absent.
- **Decisive information**: every uncertain condition is flipped both ways; the ones that change which
  actions are supported/conditional/refuted are reported as "what would change the assessment".
- **Judgment gate**: when no action is refuted and no action is supported by evidence alone, the
  result is ``judgment_withheld`` with the premises that would decide it.

There is no stance grade, no probability, no ball destination and no outcome. ``refuted`` means
"every modelled reason fails on t0 evidence", never "a mistake" - the vocabulary of reasons is limited
(``unmodelled_alternatives``).
"""
from __future__ import annotations

import math
from itertools import product
from typing import Any

from .decision_state_v1 import _cover, _margin, _scenario, margin_override
from .episode_stage1 import SCHEMA as EPISODE_PACKET_SCHEMA
from .tactical_options import _Claims, _pred, _r, _State

SCHEMA = "ActionRationaleV0"
VERSION = "action-rationale/0.1"
HOLDS, FAILS, WITHIN, UNKNOWN, UNOBS = "holds", "fails", "within_error", "unknown", "unobservable"
UNCERTAIN = (WITHIN, UNKNOWN, UNOBS)
LOW_BOOST = 25.0
ROOM_UU = 2500.0
POSSESSION = {"dist_uu": 350.0, "rel_speed": 700.0, "ball_z": 400.0}   # Round 4 heuristic, labelled as such
# Round 11 falsification (docs/round11/v1_falsification.json): leave-one-match-out fitting picks 0.30 s in every
# fold and a match bootstrap ranges 0.10-0.65 s, so V1's 0.55 s is one point in an unstable range. Ordering
# conditions are evaluated at both ends of this band; a status that differs between them is "within_error".
MARGIN_BAND_S = (0.30, 0.55)
MARGIN_SENSITIVE = ("focus_first", "carrier_first", "contest_level", "teammate_covers", "loose_ball_ours", "teammate_first")
UNMODELLED_ALTERNATIVES = [
    "bump or demolition on the carrier", "aerial challenge or backboard read", "boost denial / steal",
    "wall or ceiling play", "pass or infield to the teammate", "second-man support position for a pass",
    "kickoff-specific options",
]


class RationaleError(ValueError):
    """Input is not an audited Stage 1 episode packet."""


# ---------- conditions ----------

def _conditions(s: _State, c: _Claims) -> dict[str, dict[str, Any]]:
    """Conditions at the upper margin; ordering conditions that change across MARGIN_BAND_S become within_error."""
    with margin_override(MARGIN_BAND_S[1]):
        hi = _conditions_at(s, c)
    with margin_override(MARGIN_BAND_S[0]):
        lo = _conditions_at(s, _Claims("scratch"))
    for cid in MARGIN_SENSITIVE:
        if hi[cid]["status"] != lo[cid]["status"] and hi[cid]["status"] not in (UNKNOWN, UNOBS):
            hi[cid].update(status=WITHIN, claim=None,
                           margin_sensitivity={f"{MARGIN_BAND_S[0]}s": lo[cid]["status"], f"{MARGIN_BAND_S[1]}s": hi[cid]["status"]})
    for cid, cond in hi.items():
        if cond["status"] in (HOLDS, FAILS) and cond["evidence"] and cond["kind"] != "unobservable":
            refs = [r for r in cond["evidence"] if r in s.ev]
            if refs:
                cond["claim"] = c.add("TACTICAL_INFERENCE" if cond["kind"] in ("estimate", "heuristic") else "OBSERVED_FACT",
                                      refs, ("" if cond["status"] == HOLDS else "Not the case: ") + cond["text"])
    return hi


def _conditions_at(s: _State, c: _Claims) -> dict[str, dict[str, Any]]:
    sc = _scenario(s)
    cov = _cover(s, sc)
    out: dict[str, dict[str, Any]] = {}

    def put(cid, status, text, refs=(), claim=None, kind="estimate"):
        out[cid] = {"status": status, "text": text, "evidence": [r for r in refs if r in s.ev or r.startswith("U.")],
                    "claim": claim, "kind": kind}

    reach = [r for r in ("E.reach.focus", f"E.reach.{sc['carrier']}") if r in s.ev]
    fvc = sc["focus_vs_carrier"]
    m = {"a_first": (HOLDS, FAILS), "b_first": (FAILS, HOLDS), "ambiguous": (WITHIN, WITHIN), "unknown": (UNKNOWN, UNKNOWN)}[fvc]
    put("focus_first", m[0], "The focus player reaches the ball before the nearest opponent.", reach)
    put("carrier_first", m[1], "The nearest opponent reaches the ball before the focus player.", reach)
    put("contest_level", {"ambiguous": HOLDS, "unknown": UNKNOWN}.get(fvc, FAILS),
        "Arrival order is inside the calibrated model error: a genuine contest.", reach)
    put("teammate_covers", {"covered": HOLDS, "uncovered": FAILS, "ambiguous": WITHIN, "unknown": UNKNOWN}[cov["status"]],
        "If the focus player is beaten, the teammate can be goal-side in time.",
        ["E.cover.teammate"] + reach[1:])
    race = sc["loose_ball_race"]
    put("loose_ball_ours", {"teammate_first": HOLDS, "second_opponent_first": FAILS, "ambiguous": WITHIN,
                            "unknown": UNKNOWN}[race],
        "The teammate is ahead of the other opponent for a loose ball near the contact.",
        [r for r in ("E.reach.teammate", f"E.reach.{sc['second_opponent']}") if r in s.ev])
    roles = sc["roles_own"]
    put("teammate_first", {"teammate": HOLDS, "focus": FAILS}.get(roles.get("first"),
        WITHIN if roles.get("relation") == "ambiguous" else UNKNOWN if roles.get("relation") == "unknown" else FAILS),
        "The teammate is the first player to the ball on the focus player's team.", ["E.reach.focus", "E.reach.teammate"])
    fy, by = s.rel_y("E.focus.position"), s.rel_y("E.ball.position")
    put("focus_goal_side", UNKNOWN if fy is None or by is None else (HOLDS if fy < by else FAILS),
        "The focus player is goal-side of the ball.", ["E.focus.position", "E.ball.position"], kind="observed")
    p = s.val("E.focus.position")
    put("focus_grounded", UNKNOWN if not isinstance(p, list) else (HOLDS if p[2] < 40 else FAILS),
        "The focus player is on the ground.", ["E.focus.position"], kind="observed")
    b = s.val("E.focus.boost") if "E.focus.boost" in s.ev else None
    put("boost_for_recovery", UNKNOWN if b is None else (HOLDS if b >= LOW_BOOST else FAILS),
        "The focus player has enough boost for a quick recovery (threshold in LOW_BOOST).", ["E.focus.boost"] if b is not None else ["U.focus.boost"],
        kind="observed")
    ball = s.val("E.ball.position")
    if isinstance(ball, list):
        d = math.dist((ball[0], s.sign * ball[1]), (0.0, -5120.0))
        put("room_to_delay", HOLDS if d >= ROOM_UU else FAILS, "The ball is far enough from the own goal to give ground.",
            ["E.ball.position"], kind="observed")
    else:
        put("room_to_delay", UNKNOWN, "The ball is far enough from the own goal to give ground.", ["U.ball.state"])
    put("carrier_controls", _carrier_controls(s, sc["carrier"]),
        "The nearest opponent has the ball under control (close, moving with it, low ball). Heuristic.",
        [r for r in ("E.ball.position", "E.ball.velocity", f"E.{sc['carrier']}.position", f"E.{sc['carrier']}.velocity")
         if sc["carrier"]], kind="heuristic")
    put("teammate_deeper", _deeper(s), "The teammate is nearer the own goal than the focus player.",
        ["E.teammate.position", "E.focus.position"], kind="observed")
    for cid, text in (("contact_away_from_second_opponent", "The contact sends the ball away from the other opponent."),
                      ("teammate_will_rotate", "The teammate intends to rotate behind (comms, intent)."),
                      ("flip_available", "The focus player still has a flip available."),
                      ("aware_of_second_opponent", "The focus player has seen the other opponent (camera).")):
        put(cid, UNOBS, text, (), kind="unobservable")
    # verifiable claims for the measured inputs
    for slot, label in (("focus", "The focus player"), (sc["carrier"], "The nearest opponent"),
                        ("teammate", "The teammate"), (sc["second_opponent"], "The other opponent")):
        iv = sc["intervals"].get(slot) if slot else None
        if slot and iv and not math.isinf(iv[0]) and f"E.reach.{slot}" in s.ev:
            c.add("PHYSICALLY_ESTIMATED_FEASIBILITY", [f"E.reach.{slot}"],
                  f"{label} can touch the ball at the earliest {_r(iv[0], 2)} s after the decision.",
                  [_pred(f"E.reach.{slot}", ["t_min_s"], _r(iv[0], 2))])
    return out


def _carrier_controls(s: _State, carrier: str | None) -> str:
    if not carrier:
        return UNKNOWN
    bp, bv = s.val("E.ball.position"), s.val("E.ball.velocity")
    cp, cv = s.val(f"E.{carrier}.position"), s.val(f"E.{carrier}.velocity")
    if not all(isinstance(x, list) for x in (bp, bv, cp, cv)):
        return UNKNOWN
    d = math.dist(bp[:2], cp[:2])
    rel = math.dist(bv[:2], cv[:2])
    return HOLDS if d < POSSESSION["dist_uu"] and rel < POSSESSION["rel_speed"] and bp[2] < POSSESSION["ball_z"] else FAILS


def _deeper(s: _State) -> str:
    fy, my = s.rel_y("E.focus.position"), s.rel_y("E.teammate.position")
    return UNKNOWN if fy is None or my is None else (HOLDS if my < fy else FAILS)


# ---------- action rationales ----------
# reasons: any one complete set justifies the action; defeaters: conditions that make it wrong when they hold.
# A defeater written "!x" is present when condition x FAILS.

RATIONALES: dict[str, dict[str, Any]] = {
    "immediate_challenge": {
        "reasons": [
            ("win_it_with_cover", ["focus_first", "teammate_covers"], "Get there first with a teammate behind."),
            ("deny_control_with_cover", ["contest_level", "teammate_covers", "!carrier_controls"],
             "Contest a ball nobody controls yet, with a teammate behind."),
            ("win_it_and_keep_it", ["focus_first", "loose_ball_ours"], "Get there first; a loose ball favours the teammate."),
            ("win_it_and_steer", ["focus_first", "contact_away_from_second_opponent"],
             "Get there first and direct the contact away from their second player (angle not observable)."),
            ("aggressive_contest", ["contest_level", "contact_away_from_second_opponent", "flip_available"],
             "Contest it and steer the contact away from their second player (premises not observable)."),
        ],
        "defeaters": [("beaten_and_exposed", ["carrier_first", "!teammate_covers"]),
                      ("loose_ball_theirs_uncovered", ["!loose_ball_ours", "!teammate_covers"]),
                      ("slow_recovery", ["!boost_for_recovery", "!teammate_covers"])],
    },
    "controlled_fifty_fifty": {
        "reasons": [("level_contest_covered", ["contest_level", "teammate_covers"], "A level contest with a teammate behind."),
                    ("level_contest_toward_teammate", ["contest_level", "contact_away_from_second_opponent"],
                     "A level contest angled toward safety (angle not observable).")],
        "defeaters": [("loose_ball_theirs_uncovered", ["!loose_ball_ours", "!teammate_covers"])],
    },
    "controlled_touch": {
        "reasons": [("clear_possession_window", ["focus_first", "!carrier_controls"], "Get there first and keep it.")],
        "defeaters": [("heavy_touch_to_them_uncovered", ["!loose_ball_ours", "!teammate_covers"])],
    },
    "shadow_delay": {
        "reasons": [("late_so_delay", ["carrier_first", "focus_goal_side", "room_to_delay"],
                     "The opponent is first; stay goal-side and give ground."),
                    ("uncovered_so_delay", ["!teammate_covers", "focus_goal_side", "room_to_delay"],
                     "Nobody covers a beaten challenge; delay until support arrives."),
                    ("controlled_carrier", ["carrier_controls", "focus_goal_side", "room_to_delay"],
                     "The carrier has control; force a decision instead of diving in.")],
        "defeaters": [("no_room", ["!room_to_delay", "carrier_first"]),
                      ("concedes_a_winnable_ball", ["focus_first", "teammate_covers"])],
    },
    "goal_side_hold": {
        "reasons": [("last_line", ["focus_goal_side", "!teammate_deeper"], "The focus player is the last line; hold it."),
                    ("teammate_has_it", ["teammate_first", "focus_goal_side"], "The teammate plays the ball; hold behind.")],
        "defeaters": [("concedes_a_winnable_ball", ["focus_first", "teammate_covers"])],
    },
    "fake_challenge": {
        "reasons": [("pressure_without_commit", ["carrier_controls", "focus_goal_side", "focus_grounded", "!focus_first"],
                     "Show pressure to force a rushed play without committing (carrier's read not observable).")],
        "defeaters": [],
    },
    "yield_to_teammate": {
        "reasons": [("teammate_ball", ["teammate_first", "focus_goal_side"], "The teammate is first; support from behind."),
                    ("avoid_double_commit", ["teammate_first", "teammate_will_rotate"], "Avoid a double commit (comms not observable).")],
        "defeaters": [("teammate_beaten_and_exposed", ["carrier_first", "teammate_deeper"])],
    },
    "rotate_through_small_pads": {
        "reasons": [("refill_while_covered", ["!boost_for_recovery", "teammate_covers"], "Low boost while a teammate covers.")],
        "defeaters": [("leaves_goal_open", ["carrier_first", "!teammate_covers"])],
    },
    "clear_or_pass_to_space": {
        "reasons": [("first_and_under_threat", ["focus_first", "!room_to_delay"], "First to a ball near the own goal: clear it."),
                    ("level_near_goal", ["contest_level", "!room_to_delay"], "A level contest near the own goal: get it away.")],
        "defeaters": [("clear_to_their_second_man_uncovered", ["!loose_ball_ours", "!teammate_covers"])],
    },
}


def _lit(cond: dict[str, dict], lit: str) -> str:
    """Status of a literal: 'x' or '!x' (negated). Uncertain statuses stay uncertain."""
    neg = lit.startswith("!")
    st = cond[lit.lstrip("!")]["status"]
    if not neg or st in UNCERTAIN:
        return st
    return HOLDS if st == FAILS else FAILS


def _evaluate(cond: dict[str, dict]) -> dict[str, dict]:
    res = {}
    for action, spec in RATIONALES.items():
        reasons = []
        for rid, lits, text in spec["reasons"]:
            sts = {lit: _lit(cond, lit) for lit in lits}
            status = "refuted" if FAILS in sts.values() else ("satisfied" if all(v == HOLDS for v in sts.values()) else "conditional")
            reasons.append({"reason": rid, "text": text, "status": status,
                            "premises": [{"condition": lit, "status": st} for lit, st in sts.items()],
                            "uncertain_premises": [lit for lit, st in sts.items() if st in UNCERTAIN]})
        defeaters = []
        for did, lits in spec["defeaters"]:
            sts = [_lit(cond, lit) for lit in lits]
            status = "absent" if FAILS in sts else ("present" if all(v == HOLDS for v in sts) else "possible")
            defeaters.append({"defeater": did, "status": status, "conditions": lits})
        rs = {r["status"] for r in reasons}
        status = "supported" if "satisfied" in rs else ("conditional" if "conditional" in rs else "refuted")
        if status != "refuted" and any(d["status"] == "present" for d in defeaters):
            status = "contested"      # a reason holds or may hold, and a defeater is established too
        res[action] = {"status": status, "reasons": reasons, "defeaters": defeaters}
    return res


def _signature(ev: dict[str, dict]) -> dict[str, str]:
    return {a: v["status"] for a, v in ev.items()}


def _decisive(cond: dict[str, dict], base: dict[str, str], limit: int = 4) -> list[dict]:
    """Uncertain conditions whose resolution would change some action's status (one at a time)."""
    out = []
    for cid, c in cond.items():
        if c["status"] not in UNCERTAIN:
            continue
        changes = {}
        for val in (HOLDS, FAILS):
            alt = {k: dict(v) for k, v in cond.items()}
            alt[cid]["status"] = val
            sig = _signature(_evaluate(alt))
            diff = {a: f"{base[a]} -> {sig[a]}" for a in base if sig[a] != base[a]}
            if diff:
                changes[val] = diff
        if changes:
            out.append({"condition": cid, "current": c["status"], "text": c["text"], "if_true": changes.get(HOLDS, {}),
                        "if_false": changes.get(FAILS, {}),
                        "how_to_resolve": {"within_error": "a better physical model (e.g. RocketSim) or expert review of the clip",
                                           "unknown": "the missing telemetry", "unobservable": "the player's account or expert review"}[c["status"]]})
    out.sort(key=lambda d: -(len(d["if_true"]) + len(d["if_false"])))
    return out[:limit] if limit else out


def analyze_action_rationale(stage1_episode_packet: dict[str, Any], *, focus_node_id: str | None = None) -> dict[str, Any]:
    p = stage1_episode_packet
    if not isinstance(p, dict) or p.get("schema") != EPISODE_PACKET_SCHEMA:
        raise RationaleError("Expected a Stage1EpisodePacketV0.")
    if p.get("retrospective_present") is not False or "retrospective" in p:
        raise RationaleError("Stage 1 input must not contain retrospective material.")
    nodes = {n["node_id"]: n for n in p["nodes"]}
    nid = focus_node_id or next(n["node_id"] for n in p["nodes"] if n["is_primary"])
    if nid not in nodes:
        raise RationaleError(f"Unknown node {nid}.")
    node, packet = nodes[nid], nodes[nid]["packet"]
    base = {"schema": SCHEMA, "version": VERSION, "node_id": nid, "t0": node["t0"], "information_cutoff_s": node["t0"],
            "calibration": {"order_margin_band_s": list(MARGIN_BAND_S), "v1_margin_s": _margin(),
                            "source": "docs/round11/v1_falsification.json"},
            "uses_retrospective": False, "unmodelled_alternatives": UNMODELLED_ALTERNATIVES}
    if packet["status"] == "abstain":
        return {**base, "status": "abstain", "judgment": "withheld", "reasons_for_withholding": ["No decision-time frame."],
                "conditions": {}, "actions": {}, "reasonable_choices": [], "decisive_information": [], "claims": []}
    s = _State(packet)
    c = _Claims(nid)
    cond = _conditions(s, c)
    ev = _evaluate(cond)
    sig = _signature(ev)
    supported = [a for a, v in sig.items() if v == "supported"]
    conditional = [a for a, v in sig.items() if v == "conditional"]
    refuted = [a for a, v in sig.items() if v == "refuted"]
    contested = [a for a, v in sig.items() if v == "contested"]
    decisive = _decisive(cond, sig)
    withheld = []
    if not supported and not refuted:
        withheld.append("No action is established or ruled out by the t0 evidence alone.")
    if cond["focus_first"]["status"] == UNKNOWN:
        withheld.append("Arrival order is unknown.")
    judgment = "withheld" if withheld else "available"
    for a, v in ev.items():
        v["claims"] = sorted({cond[pr["condition"].lstrip("!")]["claim"] for r in v["reasons"] for pr in r["premises"]
                              if cond[pr["condition"].lstrip("!")]["claim"]})
    return {
        **base,
        "status": "ok" if judgment == "available" else "partial",
        "judgment": judgment,
        "reasons_for_withholding": withheld,
        "conditions": cond,
        "actions": ev,
        "reasonable_choices": [{"action": a, "basis": sig[a],
                                "premises": next((r["uncertain_premises"] for r in ev[a]["reasons"] if r["status"] != "refuted"), []),
                                "why": [r["text"] for r in ev[a]["reasons"] if r["status"] != "refuted"]}
                               for a in supported + conditional],
        "supported": supported, "conditional": conditional, "contested": contested, "refuted": refuted,
        "decisive_information": decisive,
        "claims": c.items,
        "vocabulary_note": "'refuted' = every modelled reason fails on t0 evidence. It is not a verdict that the action "
                           "was a mistake; unmodelled alternatives are listed.",
    }


def enumerate_condition_worlds(result: dict[str, Any], max_uncertain: int = 6) -> list[dict]:
    """All combinations of up to ``max_uncertain`` uncertain conditions, with the resulting supported actions.

    For explanation only ("if X and Y, then challenge is supported"); no world is weighted or predicted.
    """
    cond = result["conditions"]
    decisive = [d["condition"] for d in result.get("decisive_information", [])]
    unc = [k for k, v in cond.items() if v["status"] in UNCERTAIN]
    unc = sorted(unc, key=lambda k: (k not in decisive, decisive.index(k) if k in decisive else 0))[:max_uncertain]
    worlds = []
    for vals in product((HOLDS, FAILS), repeat=len(unc)):
        alt = {k: dict(v) for k, v in cond.items()}
        for k, v in zip(unc, vals):
            alt[k]["status"] = v
        sig = _signature(_evaluate(alt))
        worlds.append({"assumptions": dict(zip(unc, vals)), "status": sig,
                       "supported": sorted(a for a, s in sig.items() if s == "supported")})
    return worlds

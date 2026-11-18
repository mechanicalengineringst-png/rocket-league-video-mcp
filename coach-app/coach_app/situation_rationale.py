"""Class-specific condition ledgers for 2v2 decision situations (Round 12).

Extends ActionRationaleV0 (defensive challenge vocabulary) to the other situation classes from
``situations.py``. The scheme is the same: conditions with an evidence status, reasons that can
justify an action, defeaters that can make it wrong, decisive-information search, a judgment gate.

Two kinds of evidence back the conditions:
- packet facts and kinematic estimates from the node's Stage 1 packet (``E.`` ids, verifier-checked);
- **derived quantities** (``Q.`` ids): deterministic computations from those facts and from the replay
  prefix up to t0, e.g. route times via a boost pad, shot-lane clearance, pad availability from pickup
  events at or before t0. Each has its inputs and formula, and is recomputed, never estimated by a model.

Nothing reads frames or events after t0: the caller passes the replay truncated at t0 and this module
refuses a prefix that extends past it.
"""
from __future__ import annotations

import math
from typing import Any

from .action_rationale import (FAILS, HOLDS, RATIONALES, UNCERTAIN, UNKNOWN, UNOBS, WITHIN, _conditions, _decisive,
                               _evaluate, _signature)
from .boost_pad_events import PADS
from .decision_state_v1 import POLICY as V1_POLICY
from .reachability import CarState, car_state, ground_time
from .situations import SUPPORTED_FOR_JUDGMENT
from .tactical_analysis import read_state, shot_lane
from .tactical_options import _Claims, _State

SCHEMA = "SituationRationaleV1"
VERSION = "situation-rationale/0.1"
GOAL_Y = 5120.0
BAND = 0.30                       # Round 11 lower margin; values within it of a threshold are within_error
PRESSURE_S = 0.8                  # time before an opponent can touch a ball the focus player controls
DETOUR_OK_S = 0.8                 # extra time a big-boost detour may cost before it competes with returning
SMALL_PAD_CORRIDOR_UU = 700.0
LOW_BOOST = 30.0


class SituationRationaleError(ValueError):
    pass


def _rel(team: str, x: float, y: float) -> tuple[float, float]:
    return (x, y) if team == "blue" else (-x, -y)


def _band(value: float | None, threshold: float, higher_is_true: bool = True) -> str:
    if value is None:
        return UNKNOWN
    if math.isinf(value):
        return HOLDS if higher_is_true else FAILS
    if abs(value - threshold) <= BAND:
        return WITHIN
    return HOLDS if (value > threshold) == higher_is_true else FAILS


class _Q:
    """Derived quantities with stable ids, inputs and formulas."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def add(self, qid: str, value: Any, unit: str | None, inputs: list[str], formula: str) -> str:
        self.items[qid] = {"id": qid, "value": value, "unit": unit, "inputs": inputs, "formula": formula}
        return qid


def _cond(status, text, evidence=(), quantities=(), kind="estimate"):
    return {"status": status, "text": text, "evidence": list(evidence), "quantities": list(quantities),
            "claim": None, "kind": kind}


# ---------- extra conditions per class ----------

def _possession(s: _State, prefix: dict, t0: float, focus: str, q: _Q, base: dict) -> dict:
    out = {}
    team = s.team
    opp = [k for k in s.slots if k.startswith("opponent")]
    ts = [s.reach(k)[0] for k in opp]
    nearest = None if any(t is None for t in ts) else min(ts)
    out["time_before_pressure"] = _cond(_band(nearest, PRESSURE_S), "No opponent can touch the ball for a while.",
                                        [f"E.reach.{k}" for k in opp])
    if nearest is not None:
        q.add("Q.pressure_time_s", None if math.isinf(nearest) else round(nearest, 2), "s", [f"E.reach.{k}" for k in opp],
              "min over opponents of the kinematic earliest touch")
        out["time_before_pressure"]["quantities"].append("Q.pressure_time_s")
    ball = s.val("E.ball.position")
    if isinstance(ball, list):
        bx, by = _rel(team, ball[0], ball[1])
        dist_goal = math.hypot(bx, GOAL_Y - by)
        out["in_shooting_range"] = _cond(HOLDS if by > 1500 and dist_goal < 4500 else FAILS,
                                         "The ball is within shooting range of the opponent goal.", ["E.ball.position"],
                                         kind="observed")
        out["ball_in_own_half"] = _cond(HOLDS if by < 0 else FAILS, "The ball is in the own half.", ["E.ball.position"],
                                        kind="observed")
        q.add("Q.ball_to_opponent_goal_uu", round(dist_goal), "uu", ["E.ball.position"], "distance from ball to opponent goal centre")
    else:
        for k in ("in_shooting_range", "ball_in_own_half"):
            out[k] = _cond(UNKNOWN, k.replace("_", " "), ["U.ball.state"])
    # shot lane from the replay prefix (Round 4 geometry on the kinematic engine)
    try:
        r = read_state(prefix, t0, focus)
        lane = shot_lane(r) if r.ball is not None and r.focus is not None else None
    except Exception:  # noqa: BLE001  (fail closed: unknown)
        lane = None
    if lane is None or out["in_shooting_range"]["status"] != HOLDS:
        out["shot_lane_open"] = _cond(UNKNOWN if lane is None else FAILS, "An immediate shot has an open lane.",
                                      ["E.ball.position"])
    else:
        slacks = [d["slack_s"] for d in lane["defenders"]]
        open9 = round(lane["open_fraction"] * 9)
        q.add("Q.shot_open_lines", open9, "of 9", ["E.ball.position"] + [f"E.{k}.position" for k in opp],
              "straight lines ball->goal mouth not within 200 uu of a known opponent")
        if None in slacks:
            st = UNKNOWN
        else:
            ms = min(slacks) if slacks else math.inf
            q.add("Q.shot_defender_margin_s", None if math.isinf(ms) else round(ms, 2), "s",
                  [f"E.reach.{k}" for k in opp] + ["E.ball.position"],
                  "fastest defender's kinematic time to the shot line minus ball time at 2500 uu/s")
            st = HOLDS if lane["open_fraction"] >= 0.45 and ms > 0.15 + BAND else (
                WITHIN if lane["open_fraction"] >= 0.45 and ms > 0.15 - BAND else FAILS)
        out["shot_lane_open"] = _cond(st, "An immediate shot has an open lane and no defender reaches the line first.",
                                      ["E.ball.position"], ["Q.shot_open_lines"] + (["Q.shot_defender_margin_s"] if
                                                                                    "Q.shot_defender_margin_s" in q.items else []))
    my = s.rel_y("E.teammate.position")
    by_ = s.rel_y("E.ball.position")
    mate_t, _ = s.reach("teammate")
    if my is None or by_ is None or mate_t is None:
        out["teammate_forward_option"] = _cond(UNKNOWN, "The teammate is level or ahead to receive a pass.", ["U.teammate.state"])
    else:
        out["teammate_forward_option"] = _cond(HOLDS if my > by_ - 1000 and mate_t <= 2.0 else FAILS,
                                               "The teammate is level or ahead and could reach the ball within two seconds.",
                                               ["E.teammate.position", "E.ball.position", "E.reach.teammate"])
    out["play_uncovered_if_lost"] = _cond(
        {HOLDS: FAILS, FAILS: HOLDS}.get(base["teammate_covers"]["status"], base["teammate_covers"]["status"]),
        "If the ball is lost, the teammate cannot be goal-side in time.", base["teammate_covers"]["evidence"])
    return out


def _pad_status(prefix: dict, t0: float, pad: dict) -> str:
    window = 10.0 if pad["big"] else 4.0
    for e in prefix.get("events", []):
        if e.get("type") != "boost_pickups" or not isinstance(e.get("t"), (int, float)) or not (t0 - window < e["t"] <= t0):
            continue
        if e.get("padId") == pad["id"]:
            return "taken"
        if e.get("padId") is None and e.get("padType") == ("big" if pad["big"] else "small"):
            return "unknown"
    return "available"


def _recovery(s: _State, prefix: dict, t0: float, focus: str, q: _Q, base: dict) -> dict:
    out = {}
    team = s.team
    car = s.val("E.focus.position")
    vel = s.val("E.focus.velocity")
    fwd = s.val("E.focus.forward")
    ball = s.val("E.ball.position")
    if not all(isinstance(x, list) for x in (car, vel, fwd, ball)):
        for k in ("big_boost_detour_cheap", "big_pad_available", "small_pads_on_route", "threat_now"):
            out[k] = _cond(UNKNOWN, k.replace("_", " "), ["U.focus.state"])
        return out
    boost = s.val("E.focus.boost") if "E.focus.boost" in s.ev else None
    st, _ = car_state({"x": car[0], "y": car[1], "z": car[2], "velocity": vel, "forward": fwd, "boost": boost})
    own_y = -GOAL_Y if team == "blue" else GOAL_Y
    gx, gy = ball[0] * 2 / 3, ball[1] + (own_y - ball[1]) / 3            # goal-side point (V1 definition)
    direct, _ = ground_time(st, gx, gy, 6.0, (boost or 0) > 0) if st and st.mode == "ground" else (None, None)
    q.add("Q.direct_return_s", None if direct is None else round(direct, 2), "s",
          ["E.focus.position", "E.focus.velocity", "E.focus.forward", "E.ball.position"],
          "kinematic time to the goal-side point (a third of the way from ball to own goal)")
    pads = sorted((p for p in PADS if p["big"]), key=lambda p: math.dist((p["x"], p["y"]), (car[0], car[1])))
    best = None
    for pad in pads[:2]:
        status = _pad_status(prefix, t0, pad)
        t1, _ = ground_time(st, pad["x"], pad["y"], 6.0, (boost or 0) > 0) if st and st.mode == "ground" else (None, None)
        if t1 is None:
            continue
        hd = math.atan2(gy - pad["y"], gx - pad["x"])
        at_pad = CarState(pad["x"], pad["y"], 17.0, 1400 * math.cos(hd), 1400 * math.sin(hd), 0.0, hd, 100.0, "ground")
        t2, _ = ground_time(at_pad, gx, gy, 6.0, True)
        if t2 is None:
            continue
        total = t1 + t2
        if best is None or total < best[0]:
            best = (total, pad, status)
    if best is None or direct is None:
        out["big_boost_detour_cheap"] = _cond(UNKNOWN, "A big-boost detour costs little extra time.", ["E.focus.position"])
        out["big_pad_available"] = _cond(UNKNOWN, "The nearest big pad is available.", ["E.focus.position"])
    else:
        extra = best[0] - direct
        q.add("Q.big_boost_detour_extra_s", round(extra, 2), "s", ["E.focus.position", "E.focus.velocity", "E.ball.position"],
              f"(time to big pad {best[1]['id']} + pad to goal-side point) - direct return")
        out["big_boost_detour_cheap"] = _cond(_band(extra, DETOUR_OK_S, higher_is_true=False),
                                              "A big-boost detour costs little extra time.", ["E.focus.position"],
                                              ["Q.big_boost_detour_extra_s", "Q.direct_return_s"])
        q.add("Q.big_pad_status", best[2], None, ["C.boost_pickups"], "matched pickup events at or before t0 within the respawn time")
        out["big_pad_available"] = _cond({"available": HOLDS, "taken": FAILS, "unknown": UNKNOWN}[best[2]],
                                         "The nearest big pad is available.", [], ["Q.big_pad_status"], kind="observed")
    # small pads within a corridor along the direct line, available
    vx, vy = gx - car[0], gy - car[1]
    L = math.hypot(vx, vy) or 1.0
    on_route = []
    for pad in (p for p in PADS if not p["big"]):
        px, py = pad["x"] - car[0], pad["y"] - car[1]
        u = (px * vx + py * vy) / (L * L)
        lateral = abs(px * vy - py * vx) / L
        if 0.05 < u < 1.0 and lateral < SMALL_PAD_CORRIDOR_UU and _pad_status(prefix, t0, pad) == "available":
            on_route.append(pad["id"])
    q.add("Q.small_pads_on_route", len(on_route), "pads", ["E.focus.position", "E.ball.position"],
          f"available small pads within {SMALL_PAD_CORRIDOR_UU:.0f} uu of the direct line to the goal-side point")
    out["small_pads_on_route"] = _cond(HOLDS if on_route else FAILS, "Small pads lie along the return route.",
                                       ["E.focus.position"], ["Q.small_pads_on_route"])
    out["low_boost"] = _cond(UNKNOWN if boost is None else (HOLDS if boost < LOW_BOOST else FAILS),
                             "The focus player is low on boost.", ["E.focus.boost"] if boost is not None else ["U.focus.boost"],
                             kind="observed")
    bx, by = _rel(team, ball[0], ball[1])
    toward = None
    bv = s.val("E.ball.velocity")
    if isinstance(bv, list):
        toward = -(bv[1] if team == "blue" else -bv[1])
    threat = base["carrier_first"]["status"] == HOLDS and (by < 1000 or (toward or 0) > 500)
    out["threat_now"] = _cond(HOLDS if threat else (UNKNOWN if base["carrier_first"]["status"] == UNKNOWN else FAILS),
                              "An opponent is first to the ball in or toward the own half.",
                              ["E.ball.position", "E.ball.velocity"] + base["carrier_first"]["evidence"])
    return out


def _second_man(s: _State, prefix: dict, t0: float, focus: str, q: _Q, base: dict) -> dict:
    out = {}
    f_t, _ = s.reach("focus")
    m_t, _ = s.reach("teammate")
    v = s.val("E.focus.velocity")
    p, b = s.val("E.focus.position"), s.val("E.ball.position")
    if None in (f_t, m_t) or not all(isinstance(x, list) for x in (v, p, b)):
        out["double_commit_risk"] = _cond(UNKNOWN, "The focus player is also driving at the ball.", ["U.focus.state"])
    else:
        dx, dy = b[0] - p[0], b[1] - p[1]
        d = math.hypot(dx, dy) or 1.0
        closing = (v[0] * dx + v[1] * dy) / d
        q.add("Q.focus_closing_speed", round(closing), "uu/s", ["E.focus.velocity", "E.focus.position", "E.ball.position"],
              "focus velocity component toward the ball")
        out["double_commit_risk"] = _cond(HOLDS if closing > 800 and f_t <= m_t + 0.6 else FAILS,
                                          "The focus player is driving at the ball while the teammate plays it.",
                                          ["E.focus.velocity", "E.reach.focus", "E.reach.teammate"], ["Q.focus_closing_speed"])
    # can the focus player cover if the teammate loses the ball? (cover computed for the focus player)
    opp = [k for k in s.slots if k.startswith("opponent")]
    ts = [s.reach(k)[0] for k in opp]
    team = s.team
    if any(t is None for t in ts) or not all(isinstance(x, list) for x in (p, b, s.val("E.focus.forward"))):
        out["focus_covers_teammate"] = _cond(UNKNOWN, "If the teammate is beaten, the focus player can be goal-side in time.",
                                             ["U.focus.state"])
    else:
        own_y = -GOAL_Y if team == "blue" else GOAL_Y
        gx, gy = b[0] * 2 / 3, b[1] + (own_y - b[1]) / 3
        fy, by = s.rel_y("E.focus.position"), s.rel_y("E.ball.position")
        st, _ = car_state({"x": p[0], "y": p[1], "z": p[2], "velocity": v, "forward": s.val("E.focus.forward"),
                           "boost": s.val("E.focus.boost") if "E.focus.boost" in s.ev else None})
        if fy is not None and by is not None and fy < by:
            cover = 0.0
        else:
            g, _ = ground_time(st, gx, gy, 4.0, True) if st and st.mode == "ground" else (None, None)
            cover = math.inf if g is None else g
        c_t = min(ts)
        q.add("Q.focus_cover_s", None if math.isinf(cover) else round(cover, 2), "s", ["E.focus.position", "E.ball.position"],
              "0 if already goal-side, else kinematic time to the goal-side point")
        out["focus_covers_teammate"] = _cond(_band(c_t + V1_POLICY["cover_window_s"] - (cover if not math.isinf(cover) else 99), 0.0),
                                             "If the teammate is beaten, the focus player can be goal-side in time.",
                                             ["E.focus.position", "E.ball.position"] + [f"E.reach.{k}" for k in opp],
                                             ["Q.focus_cover_s"])
    out["opponents_far"] = _cond(_band(min(ts) if None not in ts else None, 1.2),
                                 "Both opponents are well away from the ball.", [f"E.reach.{k}" for k in opp])
    b2 = s.val("E.focus.boost") if "E.focus.boost" in s.ev else None
    out["low_boost"] = _cond(UNKNOWN if b2 is None else (HOLDS if b2 < LOW_BOOST else FAILS), "The focus player is low on boost.",
                             ["E.focus.boost"] if b2 is not None else ["U.focus.boost"], kind="observed")
    return out


EXTRA = {"possession": _possession, "recovery_and_boost": _recovery, "second_man_support": _second_man}

SPECS: dict[str, dict[str, dict]] = {
    "possession": {
        "keep_possession": {"reasons": [
            ("time_and_space", ["time_before_pressure", "!play_uncovered_if_lost"], "Time before pressure and cover behind: keep it and build."),
            ("time_no_better_option", ["time_before_pressure", "!shot_lane_open", "!teammate_forward_option"],
             "Time before pressure and no better option: keep it until one appears.")],
            "defeaters": [("lose_it_uncovered", ["!time_before_pressure", "play_uncovered_if_lost"])]},
        "shoot_now": {"reasons": [("open_lane", ["in_shooting_range", "shot_lane_open"], "In range with an open lane.")],
                      "defeaters": []},
        "pass_or_center": {"reasons": [
            ("teammate_ahead_under_pressure", ["teammate_forward_option", "!time_before_pressure"],
             "Pressure is arriving and the teammate can receive."),
            ("teammate_ahead_in_range", ["teammate_forward_option", "in_shooting_range"], "The teammate is placed for a follow-up.")],
            "defeaters": []},
        "clear_to_space": {"reasons": [
            ("pressured_in_own_half", ["ball_in_own_half", "!time_before_pressure"], "Pressured in the own half: get it away.")],
            "defeaters": []},
        "wait_for_support": {"reasons": [
            ("slow_down_for_teammate", ["time_before_pressure", "!teammate_forward_option", "!in_shooting_range"],
             "No pressure yet and no support: slow the play down for the teammate.")],
            "defeaters": [("lose_it_uncovered", ["!time_before_pressure", "play_uncovered_if_lost"])]},
    },
    "recovery_and_boost": {
        "return_direct": {"reasons": [
            ("threat_and_no_cover", ["threat_now", "!teammate_covers"], "A threat with no cover: get back now."),
            ("enough_boost", ["!low_boost"], "Enough boost already: the shortest route back.")],
            "defeaters": []},
        "small_pad_route": {"reasons": [
            ("refill_on_the_way", ["low_boost", "small_pads_on_route"], "Low on boost; small pads lie on the way back.")],
            "defeaters": []},
        "big_boost_detour": {"reasons": [
            ("covered_and_cheap", ["low_boost", "teammate_covers", "big_pad_available", "big_boost_detour_cheap"],
             "Covered, low on boost, and the big pad costs little extra time."),
            ("no_threat_and_cheap", ["low_boost", "!threat_now", "big_pad_available", "big_boost_detour_cheap"],
             "No immediate threat, and the big pad costs little extra time.")],
            "defeaters": [("leaves_team_exposed", ["threat_now", "!teammate_covers"])]},
    },
    "second_man_support": {
        "support_behind": {"reasons": [
            ("cover_the_first_man", ["teammate_first", "focus_covers_teammate"], "Stay where you can cover if the teammate is beaten.")],
            "defeaters": [("double_commit", ["double_commit_risk"])]},
        "aggressive_follow_up": {"reasons": [
            ("opponents_out_of_play", ["teammate_first", "opponents_far"], "Opponents are far from the ball: support close for a follow-up."),
            ("pass_option_with_cover", ["teammate_first", "focus_covers_teammate", "!double_commit_risk"],
             "Close support without driving at the ball, still able to cover.")],
            "defeaters": [("double_commit", ["double_commit_risk"])]},
        "boost_while_teammate_plays": {"reasons": [
            ("low_and_not_needed", ["teammate_first", "low_boost", "!carrier_first"], "Low on boost while the teammate has the ball.")],
            "defeaters": [("leaves_teammate_alone", ["carrier_first", "!focus_covers_teammate"])]},
        "challenge_as_well": {"reasons": [
            ("level_with_teammate_and_contest", ["!teammate_first", "contest_level"], "Not clearly behind the teammate in a contest.")],
            "defeaters": [("double_commit", ["double_commit_risk", "teammate_first"])]},
    },
}
BASE_ACTIONS = {
    "first_defender": list(RATIONALES),
    "offensive_first_man": ["immediate_challenge", "fake_challenge", "controlled_touch", "shadow_delay",
                            "yield_to_teammate", "rotate_through_small_pads"],
    "loose_ball": ["immediate_challenge", "shadow_delay", "goal_side_hold", "rotate_through_small_pads"],
}


def specs_for(cls: str) -> dict[str, dict]:
    if cls in SPECS:
        return SPECS[cls]
    keep = BASE_ACTIONS.get(cls, list(RATIONALES))
    return {a: RATIONALES[a] for a in keep}


def analyze_situation(stage1_episode_packet: dict[str, Any], replay_prefix: dict[str, Any], situation: dict[str, Any]) -> dict:
    """Condition ledger for one situation. ``replay_prefix`` must contain nothing after t0."""
    p = stage1_episode_packet
    if p.get("retrospective_present") is not False or "retrospective" in p:
        raise SituationRationaleError("Stage 1 input must not contain retrospective material.")
    cls, t0 = situation["situation_class"], float(situation["t0"])
    if any(f.get("t", 0) > t0 + 1e-6 for f in replay_prefix.get("frames", [])) or \
            any(isinstance(e.get("t"), (int, float)) and e["t"] > t0 + 1e-6 for e in replay_prefix.get("events", [])):
        raise SituationRationaleError("Replay prefix extends past t0.")
    node = next(n for n in p["nodes"] if n["is_primary"])
    packet = node["packet"]
    out = {"schema": SCHEMA, "version": VERSION, "situation_class": cls, "t0": t0, "node_id": node["node_id"],
           "uses_retrospective": False}
    if not situation.get("supported_for_judgment", cls in SUPPORTED_FOR_JUDGMENT):
        return {**out, "judgment": "withheld", "reasons_for_withholding":
                ["Aerial and wall mechanics are not modelled; only observations are given."],
                "conditions": {}, "actions": {}, "quantities": {}, "claims": [], "decisive_information": []}
    if packet["status"] == "abstain":
        return {**out, "judgment": "withheld", "reasons_for_withholding": ["No decision-time frame."],
                "conditions": {}, "actions": {}, "quantities": {}, "claims": [], "decisive_information": []}
    s = _State(packet)
    c = _Claims(node["node_id"])
    cond = _conditions(s, c)
    q = _Q()
    if cls in EXTRA:
        extra = EXTRA[cls](s, replay_prefix, t0, situation["player_id"], q, cond)
        for cond_x in extra.values():
            refs = [r for r in cond_x["evidence"] if r in s.ev]
            if cond_x["status"] in (HOLDS, FAILS) and refs and not cond_x["quantities"]:
                cond_x["claim"] = c.add("OBSERVED_FACT" if cond_x["kind"] == "observed" else "TACTICAL_INFERENCE", refs,
                                        ("" if cond_x["status"] == HOLDS else "Not the case: ") + cond_x["text"])
        cond.update(extra)
    specs = specs_for(cls)
    used = {lit.lstrip("!") for sp in specs.values() for _, lits, _ in sp["reasons"] for lit in lits} | \
           {lit.lstrip("!") for sp in specs.values() for _, lits in sp["defeaters"] for lit in lits}
    cond = {k: v for k, v in cond.items() if k in used}
    ev = _evaluate(cond, specs)
    sig = _signature(ev)
    decisive = _decisive(cond, sig, limit=4, specs=specs)
    supported = [a for a, v in sig.items() if v == "supported"]
    refuted = [a for a, v in sig.items() if v == "refuted"]
    withheld = []
    if not supported and not refuted:
        withheld.append("No action is established or ruled out by the t0 evidence alone.")
    if all(v["status"] in UNCERTAIN for v in cond.values()):
        withheld.append("Every relevant condition is uncertain.")
    return {**out, "judgment": "withheld" if withheld else "available", "reasons_for_withholding": withheld,
            "conditions": cond, "actions": ev, "quantities": q.items, "claims": c.items,
            "supported": supported, "conditional": [a for a, v in sig.items() if v == "conditional"],
            "contested": [a for a, v in sig.items() if v == "contested"], "refuted": refuted,
            "decisive_information": decisive}


__all__ = ["analyze_situation", "specs_for", "SituationRationaleError", "HOLDS", "FAILS", "WITHIN", "UNKNOWN", "UNOBS"]

"""TacticalDecisionStateV1: calibrated, branch-aware decision state for 2v2 (Round 10).

Three changes over TacticalOptionsV0 (which stays unchanged and available):

1. **Calibrated ambiguity instead of hand thresholds for "who gets there first".**
   Arrival-order comparisons use a margin fitted on real replays against held-out
   touch order (``scripts/calibrate_contest_margin.py``,
   ``docs/round10/contest_margin_calibration.json``). Inside the margin the order is
   reported as *ambiguous*, not guessed.
2. **Scenario classification.** Ball state (own team first, opponent first,
   contested, loose), responsibilities (first/second per team with "shared" when
   ambiguous) and a decision profile (pressure window, forced contest, restraint
   window, teammate's ball, transition, mixed) are derived from the same intervals.
3. **Opponent-response branches for committing actions.** For a challenge-type action
   the reachable first-contact branches are enumerated (focus touches first, carrier
   touches first, simultaneous contact). Each branch is checked for its consequence
   using only t0 evidence: who could reach a loose ball next (teammate vs second
   opponent), and whether anyone could be goal-side if the focus player is beaten.
   No branch gets a probability and no ball destination is simulated.

Stances describe robustness across reachable branches:
``robustly_defensible`` (no reachable branch leaves the team exposed),
``defensible_gamble`` (exposure only in a branch the timing leaves open: a legitimate
aggressive choice with a named downside), ``defensible_tradeoff`` (sound but gives
something up, e.g. delay concedes a ball the player could have won),
``questionable`` (exposure in the branch the timing makes primary, with no cover),
``undetermined`` (a deciding input is unknown), ``not_available``.

Stage 1 only: the input is a Stage1EpisodePacketV0; retrospective input is refused.
"""
from __future__ import annotations

import contextlib
import contextvars
import math
from typing import Any

from .episode_stage1 import SCHEMA as EPISODE_PACKET_SCHEMA
from .tactical_options import _Claims, _earlier, _pred, _r, _State, analyze_tactical_options

SCHEMA = "TacticalDecisionStateV1"
MAX_CAR_SPEED = 2300.0
GOAL_Y = 5120.0
# Filled from docs/round10/contest_margin_calibration.json (test_decision_state_v1 checks they match).
CALIBRATION = {
    "source": "docs/round10/contest_margin_calibration.json",
    "order_margin_s": None,          # set below
    "target_accuracy": 0.90,
    "held_out_accuracy": None,
    "held_out_pairs": None,
    "scope": "public unknown-rank 2v2 replays; kinematic ordering error, not expert judgement",
}
POLICY = {
    "version": "decision-state-policy/1.0",
    "immediate_s": 0.6,          # a touch within this is imminent
    "loose_s": 1.5,              # nobody can touch within this: the ball is loose / in transition
    "cover_window_s": 1.0,       # as V0: teammate goal-side within this after the carrier's touch
    "low_boost": 25.0,
    "note": "Order comparisons use the calibrated margin; the remaining values are uncalibrated hypotheses.",
}
COMMIT_ACTIONS = ("immediate_challenge", "controlled_fifty_fifty", "controlled_touch", "clear_or_pass_to_space")
DELAY_ACTIONS = ("shadow_delay", "goal_side_hold", "fake_challenge")
SUPPORT_ACTIONS = ("yield_to_teammate", "rotate_through_small_pads")
V0_STANCE = {"robustly_defensible": "defensible", "defensible_gamble": "defensible_with_conditions",
             "defensible_tradeoff": "defensible_with_conditions", "questionable": "questionable",
             "undetermined": "not_assessable", "not_available": "not_available"}


class DecisionStateError(ValueError):
    """Input is not an audited Stage 1 episode packet."""


_MARGIN_OVERRIDE: contextvars.ContextVar[float | None] = contextvars.ContextVar("v1_margin_override", default=None)


@contextlib.contextmanager
def margin_override(margin: float):
    """Evaluate V1 helpers with another ordering margin (sensitivity analysis); context-local, thread-safe."""
    token = _MARGIN_OVERRIDE.set(float(margin))
    try:
        yield
    finally:
        _MARGIN_OVERRIDE.reset(token)


def _margin() -> float:
    override = _MARGIN_OVERRIDE.get()
    if override is not None:
        return override
    m = CALIBRATION["order_margin_s"]
    if m is None:
        raise DecisionStateError("Order margin is not calibrated.")
    return float(m)


# ---------- interval comparisons ----------

def _interval(s: _State, slot: str) -> tuple[float, float] | None:
    v = s.val(f"E.reach.{slot}")
    if not isinstance(v, dict):
        return None
    if v.get("status") == "out_of_horizon":
        return (math.inf, math.inf)
    if v.get("status") != "ok" or not isinstance(v.get("t_min_s"), (int, float)):
        return None
    lo = float(v["t_min_s"])
    hi = v.get("t_max_s")
    hi = float(hi) if isinstance(hi, (int, float)) and hi >= lo else lo
    if v.get("unknowns"):
        hi = max(hi, lo + _margin())      # unknown boost: widen the pessimistic side
    return (lo, hi)


def order(a: tuple[float, float] | None, b: tuple[float, float] | None) -> str:
    """'a_first', 'b_first', 'ambiguous' or 'unknown' using the calibrated margin."""
    if a is None or b is None:
        return "unknown"
    if math.isinf(a[0]) and math.isinf(b[0]):
        return "ambiguous"
    m = _margin()
    if b[0] - a[0] > m and a[1] <= b[1]:
        return "a_first"
    if a[0] - b[0] > m and b[1] <= a[1]:
        return "b_first"
    return "ambiguous"


# ---------- scenario ----------

def _scenario(s: _State) -> dict[str, Any]:
    slots = list(s.slots)
    opp = [k for k in slots if k.startswith("opponent")]
    iv = {k: _interval(s, k) for k in slots}
    known_opp = [k for k in opp if iv[k] is not None]
    carrier = min(known_opp, key=lambda k: iv[k][0]) if len(known_opp) == len(opp) and opp else None
    second = next((k for k in opp if k != carrier), None) if carrier else None
    own = [k for k in ("focus", "teammate") if k in slots]
    own_first = min(own, key=lambda k: iv[k][0]) if all(iv[k] is not None for k in own) else None

    def team_role(a: str, b: str) -> dict:
        rel = order(iv.get(a), iv.get(b))
        return {"first": a if rel == "a_first" else b if rel == "b_first" else None,
                "relation": rel, "clarity": "clear" if rel in ("a_first", "b_first") else rel}

    roles_own = team_role("focus", "teammate") if "teammate" in slots else {"first": "focus", "relation": "single"}
    roles_opp = team_role(opp[0], opp[1]) if len(opp) == 2 else {"first": carrier, "relation": "single"}
    ball_rel = order(iv.get(own_first) if own_first else None, iv.get(carrier) if carrier else None)
    soonest = None if own_first is None or carrier is None else min(iv[own_first][0], iv[carrier][0])
    if ball_rel == "unknown":
        ball_state = "unknown"
    elif soonest is not None and soonest >= POLICY["loose_s"]:
        ball_state = "loose"
    else:
        ball_state = {"a_first": "own_team_first", "b_first": "opponent_first", "ambiguous": "contested"}[ball_rel]
    focus_vs_carrier = order(iv.get("focus"), iv.get(carrier)) if carrier else "unknown"
    second_vs_mate = order(iv.get("teammate"), iv.get(second)) if second and "teammate" in slots else "unknown"
    return {"intervals": iv, "carrier": carrier, "second_opponent": second, "own_first": own_first,
            "roles_own": roles_own, "roles_opponents": roles_opp, "ball_state": ball_state,
            "soonest_touch_s": soonest, "focus_vs_carrier": focus_vs_carrier,
            "loose_ball_race": {"a_first": "teammate_first", "b_first": "second_opponent_first",
                                "ambiguous": "ambiguous", "unknown": "unknown"}[second_vs_mate]}


def _cover(s: _State, sc: dict) -> dict[str, Any]:
    """Could the teammate be goal-side if the focus player is beaten by the carrier?"""
    cov = s.val("E.cover.teammate") if "E.cover.teammate" in s.ev else "missing"
    carrier = sc["carrier"]
    if cov == "missing" or carrier is None or sc["intervals"].get(carrier) is None:
        return {"status": "unknown", "cover_s": None}
    cov_t = math.inf if cov is None else float(cov)
    c_lo = sc["intervals"][carrier][0]
    m = _margin()
    if cov_t <= c_lo + POLICY["cover_window_s"] - m:
        status = "covered"
    elif cov_t > c_lo + POLICY["cover_window_s"] + m:
        status = "uncovered"
    else:
        status = "ambiguous"
    return {"status": status, "cover_s": None if math.isinf(cov_t) else cov_t}


def _recovery(s: _State) -> dict[str, Any]:
    """Physics lower bound on the focus player's time to the own goal mouth (max car speed)."""
    p = s.val("E.focus.position")
    if not isinstance(p, list):
        return {"lower_bound_s": None}
    gy = -s.sign * (GOAL_Y - 800.0)
    return {"lower_bound_s": round(math.dist((p[0], p[1]), (0.0, gy)) / MAX_CAR_SPEED, 2),
            "basis": "straight-line distance to the goal mouth at the 2300 uu/s top speed; a true lower bound"}


def _momentum(s: _State) -> dict[str, Any]:
    bv = s.val("E.ball.velocity")
    toward = None if not isinstance(bv, list) else -s.sign * bv[1]
    return {"ball_speed_toward_own_goal": None if toward is None else round(toward),
            "toward_own_goal": None if toward is None else toward > 500.0}


def _profile(sc: dict, cover: dict) -> str:
    fvc, bs = sc["focus_vs_carrier"], sc["ball_state"]
    if bs == "unknown" or fvc == "unknown":
        return "unknown"
    if bs == "loose":
        return "transition"
    if sc["roles_own"].get("first") == "teammate" and bs != "opponent_first":
        return "teammates_ball"
    if fvc == "a_first" and cover["status"] == "covered":
        return "pressure_window"
    if fvc == "ambiguous":
        return "forced_contest"
    if fvc == "b_first" and cover["status"] == "uncovered":
        return "restraint_window"
    return "mixed"


# ---------- branches ----------

def _branches(sc: dict, cover: dict) -> list[dict]:
    fvc = sc["focus_vs_carrier"]
    race = sc["loose_ball_race"]
    beaten_exposure = {"covered": "covered", "uncovered": "exposed", "ambiguous": "ambiguous",
                       "unknown": "unknown"}[cover["status"]]
    spill = {"teammate_first": "teammate_favoured", "second_opponent_first": "opponent_favoured",
             "ambiguous": "ambiguous", "unknown": "unknown"}[race]

    def reach(primary: bool, possible: bool) -> str:
        return "unknown" if fvc == "unknown" else ("primary" if primary else "possible" if possible else "only_if_execution_fails")

    out = [
        {"branch": "focus_touches_first", "reachability": reach(fvc == "a_first", fvc == "ambiguous"),
         "consequence": {"next_loose_ball": spill,
                         "exposure": "exposed" if spill == "opponent_favoured" and beaten_exposure == "exposed" else
                                     "unknown" if "unknown" in (spill, beaten_exposure) else "limited"}},
        {"branch": "carrier_touches_first", "reachability": reach(fvc == "b_first", fvc == "ambiguous"),
         "consequence": {"focus_beaten": True, "exposure": beaten_exposure}},
        {"branch": "simultaneous_contact", "reachability": reach(False, fvc == "ambiguous")
         if fvc != "a_first" and fvc != "b_first" else "only_if_execution_fails",
         "consequence": {"next_loose_ball": spill,
                         "exposure": "exposed" if spill == "opponent_favoured" and beaten_exposure != "covered" else
                                     "unknown" if "unknown" in (spill, beaten_exposure) else "limited"}},
    ]
    return out


def _commit_stance(branches: list[dict]) -> tuple[str, list[str]]:
    live = [b for b in branches if b["reachability"] in ("primary", "possible")]
    if any(b["reachability"] == "unknown" for b in branches) or any(b["consequence"]["exposure"] == "unknown" for b in live):
        return "undetermined", ["arrival order or teammate cover is unknown"]
    exposed_primary = [b["branch"] for b in live if b["reachability"] == "primary" and b["consequence"]["exposure"] == "exposed"]
    exposed_possible = [b["branch"] for b in live if b["reachability"] == "possible" and b["consequence"]["exposure"] in ("exposed", "ambiguous")]
    if exposed_primary:
        return "questionable", exposed_primary
    if exposed_possible:
        return "defensible_gamble", exposed_possible
    if any(b["consequence"]["exposure"] == "ambiguous" for b in live):
        return "defensible_gamble", [b["branch"] for b in live if b["consequence"]["exposure"] == "ambiguous"]
    return "robustly_defensible", []


# ---------- public API ----------

def analyze_decision_state(stage1_episode_packet: dict[str, Any], *, focus_node_id: str | None = None,
                           include_v0: bool = False) -> dict[str, Any]:
    p = stage1_episode_packet
    if not isinstance(p, dict) or p.get("schema") != EPISODE_PACKET_SCHEMA:
        raise DecisionStateError("Expected a Stage1EpisodePacketV0.")
    if p.get("retrospective_present") is not False or "retrospective" in p:
        raise DecisionStateError("Stage 1 input must not contain retrospective material.")
    nodes = {n["node_id"]: n for n in p["nodes"]}
    nid = focus_node_id or next(n["node_id"] for n in p["nodes"] if n["is_primary"])
    if nid not in nodes:
        raise DecisionStateError(f"Unknown node {nid}.")
    node, packet = nodes[nid], nodes[nid]["packet"]
    base = {"schema": SCHEMA, "policy": POLICY, "calibration": CALIBRATION, "node_id": nid, "t0": node["t0"],
            "information_cutoff_s": node["t0"], "uses_retrospective": False, "picks_single_best": False,
            "compatible_with": "TacticalOptionsV0 (see to_v0_stances / include_v0)"}
    if include_v0:
        base["tactical_options_v0"] = analyze_tactical_options(p, focus_node_id=nid)
    if packet["status"] == "abstain":
        return {**base, "status": "abstain", "abstain_reasons": ["No decision-time frame for this node."],
                "scenario": None, "actions": [], "claims": [], "earlier_contributors": _earlier(p, nid)}
    s = _State(packet)
    c = _Claims(nid)
    sc = _scenario(s)
    cover = _cover(s, sc)
    profile = _profile(sc, cover)
    claims = _claims(c, s, sc, cover)
    branches = _branches(sc, cover)
    actions = _actions(s, sc, cover, branches, profile, claims)
    abstain = []
    if sc["focus_vs_carrier"] == "unknown":
        abstain.append("Arrival order between the focus player and the nearest opponent is unknown.")
    if cover["status"] == "unknown":
        abstain.append("Teammate cover is unknown.")
    iv = {k: (None if v is None else [None if math.isinf(x) else _r(x, 3) for x in v]) for k, v in sc["intervals"].items()}
    return {
        **base,
        "status": "ok" if not abstain else ("abstain" if sc["focus_vs_carrier"] == "unknown" else "partial"),
        "abstain_reasons": abstain,
        "scenario": {"profile": profile, "ball_state": sc["ball_state"], "carrier_slot": sc["carrier"],
                     "second_opponent_slot": sc["second_opponent"], "soonest_touch_s": sc["soonest_touch_s"],
                     "focus_vs_carrier": sc["focus_vs_carrier"], "loose_ball_race": sc["loose_ball_race"],
                     "roles_own": sc["roles_own"], "roles_opponents": sc["roles_opponents"],
                     "reach_intervals_s": iv, "cover": cover, "focus_recovery": _recovery(s),
                     "momentum": _momentum(s), "claims": claims},
        "branches": branches,
        "actions": actions,
        "supported_choices": [a["action"] for a in actions if a["stance"] in
                              ("robustly_defensible", "defensible_gamble", "defensible_tradeoff")],
        "robust_choices": [a["action"] for a in actions if a["stance"] == "robustly_defensible"],
        "claims": c.items,
        "unknowns": packet["unknowns"],
        "not_observable": packet.get("not_observable", []),
        "earlier_contributors": _earlier(p, nid),
        "layers": {"observed": "OBSERVED_FACT claims", "estimate": "reach intervals, cover, recovery bound",
                   "interpretation": "scenario.profile, branch consequences, action stances (hypotheses)",
                   "unknown": "unknowns, not_observable, 'unknown'/'ambiguous' values",
                   "outcome": "not available (Stage 2)"},
    }


def to_v0_stances(result: dict[str, Any]) -> dict[str, str]:
    """Migration helper: V1 stance per action mapped onto the V0 stance vocabulary."""
    return {a["action"]: V0_STANCE[a["stance"]] for a in result.get("actions", [])}


def _claims(c: _Claims, s: _State, sc: dict, cover: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for slot, label in (("focus", "The focus player"), ("teammate", "The teammate"),
                        (sc["carrier"], "The nearest opponent"), (sc["second_opponent"], "The other opponent")):
        if not slot or f"E.reach.{slot}" not in s.ev:
            continue
        iv = sc["intervals"].get(slot)
        if iv is None:
            continue
        ref = f"E.reach.{slot}"
        if math.isinf(iv[0]):
            out[slot] = c.add("PHYSICALLY_ESTIMATED_FEASIBILITY", [ref], f"{label} cannot reach the ball within the model horizon.")
        else:
            out[slot] = c.add("PHYSICALLY_ESTIMATED_FEASIBILITY", [ref],
                              f"{label} can touch the ball at the earliest {_r(iv[0], 2)} s after the decision.",
                              [_pred(ref, ["t_min_s"], _r(iv[0], 2))])
    reach_refs = [f"E.reach.{k}" for k in ("focus", sc["carrier"]) if k and f"E.reach.{k}" in s.ev]
    rel = sc["focus_vs_carrier"]
    if rel != "unknown":
        out["order"] = c.add("TACTICAL_INFERENCE", reach_refs, {
            "a_first": "Beyond the calibrated ordering error, the focus player gets to the ball before the nearest opponent.",
            "b_first": "Beyond the calibrated ordering error, the nearest opponent gets to the ball before the focus player.",
            "ambiguous": "Within the calibrated ordering error, it is not determinable who gets to the ball first: a genuine contest.",
        }[rel])
    if cover["status"] != "unknown":
        cov_refs = ["E.cover.teammate"] + reach_refs[1:]
        out["cover"] = c.add("TACTICAL_INFERENCE", cov_refs, {
            "covered": "If the focus player is beaten, the teammate can be goal-side in time.",
            "uncovered": "If the focus player is beaten, the teammate cannot be goal-side in time.",
            "ambiguous": "Whether the teammate could cover a beaten challenge is within the model's error.",
        }[cover["status"]])
    if sc["loose_ball_race"] in ("teammate_first", "second_opponent_first", "ambiguous") and sc["second_opponent"]:
        refs = [f"E.reach.{k}" for k in ("teammate", sc["second_opponent"]) if f"E.reach.{k}" in s.ev]
        out["race"] = c.add("TACTICAL_INFERENCE", refs, {
            "teammate_first": "Near the ball, the teammate is ahead of the other opponent for a loose ball.",
            "second_opponent_first": "Near the ball, the other opponent is ahead of the teammate for a loose ball.",
            "ambiguous": "Neither the teammate nor the other opponent is clearly ahead for a loose ball.",
        }[sc["loose_ball_race"]])
    if "E.focus.boost" in s.ev:
        b = s.val("E.focus.boost")
        out["boost"] = c.add("OBSERVED_FACT", ["E.focus.boost"], f"The focus player has {_r(b, 1)} boost (freshness unverified).",
                             [_pred("E.focus.boost", [], _r(b, 1))])
    if isinstance(s.val("E.focus.position"), list) and isinstance(s.val("E.ball.position"), list):
        fy, by = s.rel_y("E.focus.position"), s.rel_y("E.ball.position")
        out["goal_side"] = c.add("OBSERVED_FACT", ["E.focus.position", "E.ball.position"],
                                 "The focus player is goal-side of the ball." if fy < by else "The focus player is not goal-side of the ball.")
    return out


def _actions(s: _State, sc: dict, cover: dict, branches: list[dict], profile: str, cl: dict) -> list[dict]:
    fvc = sc["focus_vs_carrier"]
    focus_iv = sc["intervals"].get("focus")
    on_ground = None
    p = s.val("E.focus.position")
    if isinstance(p, list):
        on_ground = p[2] < 40.0
    fy, by = s.rel_y("E.focus.position"), s.rel_y("E.ball.position")
    goal_side = None if fy is None or by is None else fy < by
    boost = s.val("E.focus.boost") if "E.focus.boost" in s.ev else None
    low_boost = None if boost is None else boost < POLICY["low_boost"]
    commit_stance, exposed_in = _commit_stance(branches)
    G = lambda *k: [cl[x] for x in k if x in cl]  # noqa: E731
    out = []

    def add(action, feasible, stance, why, cost=None, upside=None, refs=()):
        st = "not_available" if feasible == "no" else ("undetermined" if feasible == "unknown" and stance != "not_available" else stance)
        out.append({"action": action, "physically_feasible": feasible, "stance": st, "v0_stance": V0_STANCE[st],
                    "reasons": why, "named_cost": cost, "named_upside": upside, "claims": list(dict.fromkeys(refs)),
                    "exposed_branches": exposed_in if action in COMMIT_ACTIONS else []})

    reach_ok = "unknown" if focus_iv is None else ("no" if math.isinf(focus_iv[0]) else "yes")
    gamble_cost = "If the contest goes the other way, " + ("the team is exposed." if exposed_in else "the downside is limited.")
    # committing actions: robustness across branches
    add("immediate_challenge", reach_ok, commit_stance, _commit_reason(commit_stance, exposed_in),
        cost=gamble_cost if commit_stance == "defensible_gamble" else ("Low boost slows the recovery." if low_boost else None),
        upside="Wins or denies the ball while the opponent is not yet in control." if fvc in ("a_first", "ambiguous") else None,
        refs=G("order", "cover", "race", "focus"))
    ff_feasible = "unknown" if fvc == "unknown" else ("yes" if fvc == "ambiguous" else "no")
    add("controlled_fifty_fifty", ff_feasible, commit_stance, _commit_reason(commit_stance, exposed_in),
        cost=gamble_cost, upside="A deliberate contest can be angled toward the teammate (angle not observable).",
        refs=G("order", "cover", "race"))
    ct_feasible = "unknown" if fvc == "unknown" else ("yes" if fvc == "a_first" else "no")
    # A controlled touch keeps the ball, so only the focus-first branch matters; its risk is a heavy touch
    # that hands a loose ball to the other opponent while the team is uncovered.
    loose_risk = sc["loose_ball_race"] == "second_opponent_first" and cover["status"] != "covered"
    ct_stance = "undetermined" if cover["status"] == "unknown" else ("defensible_gamble" if loose_risk else "robustly_defensible")
    add("controlled_touch", ct_feasible, ct_stance,
        "The focus player is clearly first; keeping the ball avoids a contest." + (
            " A heavy touch would favour the other opponent while the team is not covered." if loose_risk else ""),
        cost="Depends on touch quality (not observable)." if loose_risk else None,
        upside="Keeps possession instead of contesting it.", refs=G("order", "race", "cover"))
    add("clear_or_pass_to_space", "unknown" if fvc == "unknown" else ("yes" if fvc in ("a_first", "ambiguous") else "no"),
        commit_stance, _commit_reason(commit_stance, exposed_in),
        cost="Ball destination is not modelled; a clear can return the ball to the opponents.", refs=G("order", "race"))
    # delaying actions
    delay_feasible = "unknown" if goal_side is None or on_ground is None else ("yes" if goal_side and on_ground else "no")
    if commit_stance in ("questionable",) or (fvc == "b_first"):
        d_stance, d_why = "robustly_defensible", "The opponent gets there first or a commit would expose the team: delaying keeps a defender goal-side."
        d_upside = "Intelligent restraint: denies the opponent an easy beat while support arrives."
        d_cost = None
    elif profile == "pressure_window":
        d_stance, d_why = "defensible_tradeoff", "A covered challenge was available; delaying keeps shape but concedes the ball."
        d_upside, d_cost = "Keeps the team's shape.", "Gives the opponent time to take control."
    elif commit_stance == "undetermined":
        d_stance, d_why, d_upside, d_cost = "undetermined", "Inputs needed to weigh delay against a commit are unknown.", None, None
    else:
        d_stance, d_why = "defensible_tradeoff", "Both delaying and contesting are supportable here; delay trades pressure for safety."
        d_upside, d_cost = "Keeps a defender goal-side.", "Less pressure on the ball."
    add("shadow_delay", delay_feasible, d_stance, d_why, d_cost, d_upside, G("goal_side", "order", "cover"))
    add("goal_side_hold", "yes" if goal_side is not None else "unknown", d_stance, d_why, d_cost, d_upside, G("goal_side", "cover"))
    fake_feasible = "unknown" if None in (goal_side, on_ground) or fvc == "unknown" else (
        "yes" if goal_side and on_ground and fvc in ("b_first", "ambiguous") else "no")
    add("fake_challenge", fake_feasible, d_stance if d_stance != "undetermined" else "undetermined",
        "Shows pressure without committing; depends on the carrier's read, which is not observable.",
        "Can fail against a patient carrier.", "Can force a rushed touch.", G("goal_side", "order"))
    # supporting actions
    mate_first = sc["roles_own"].get("first") == "teammate"
    add("yield_to_teammate", "unknown" if sc["roles_own"].get("relation") == "unknown" else ("yes" if mate_first or
        sc["roles_own"].get("relation") == "ambiguous" else "no"),
        "robustly_defensible" if mate_first and goal_side else "defensible_tradeoff",
        "The teammate is first or level to the ball; supporting from behind avoids a double commit.",
        None if goal_side else "Support depends on getting goal-side.", "Avoids a double commit.", G("goal_side"))
    add("rotate_through_small_pads", "yes" if boost is not None else "unknown",
        "defensible_tradeoff" if cover["status"] != "uncovered" else "questionable" if fvc == "b_first" else "defensible_tradeoff",
        "Refills boost while the teammate holds; leaves the team short if the teammate cannot cover." ,
        "Out of the play while rotating.", "More boost for the next decision." if low_boost else None, G("boost", "cover"))
    return out


def _commit_reason(stance: str, exposed: list[str]) -> str:
    return {
        "robustly_defensible": "No reachable first-contact branch leaves the team exposed.",
        "defensible_gamble": f"Defensible aggression with a named downside: exposure in {', '.join(exposed)}.",
        "questionable": f"The branch the timing makes primary ({', '.join(exposed)}) leaves the team exposed with no cover.",
        "undetermined": "Arrival order or teammate cover is unknown, so the branches cannot be checked.",
    }[stance]


def _load_calibration() -> None:
    import json
    from pathlib import Path
    f = Path(__file__).resolve().parent.parent / CALIBRATION["source"]
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        return
    ch = data.get("chosen", {})
    CALIBRATION.update(order_margin_s=ch.get("margin_s"), held_out_accuracy=ch.get("held_out_accuracy"),
                       held_out_pairs=ch.get("held_out_resolved"), target_accuracy=data.get("target_accuracy"))


_load_calibration()

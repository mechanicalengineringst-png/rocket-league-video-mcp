"""TacticalOptionsV0: decision-time action families with supporting and limiting evidence (Round 9).

Input: a ``Stage1EpisodePacketV0`` (``episode_stage1.build_stage1_episode_packet``). That
packet has no retrospective material, so nothing here can see what the player did or
what happened next. Output: for one decision node, the tactical state in time terms,
the action families that were physically available, what supports and what limits each,
how each depends on the teammate, the unknowns, and the earlier-contributor hypotheses,
all as claims the existing ``claim_verifier`` can check against that node's packet.

What this module never does
- pick a single "optimal" action, score expected value or give probabilities;
- read the chosen action or the outcome (Stage 2 owns that comparison);
- blame the focus player for constraints created by the teammate's position;
- turn an earlier-contributor hypothesis into a cause.

Representation (versioned in ``POLICY``): every interaction is expressed as a time
relation between kinematic lower bounds from ``reachability``:
- contest window   = focus earliest touch - carrier's earliest touch;
- spill support    = second opponent's earliest touch - carrier's;
- cover margin     = teammate's time to get goal-side - carrier's earliest touch;
- possession window = carrier's earliest touch - focus earliest touch.
The bands are hypotheses for expert calibration, listed in every output.
"""
from __future__ import annotations

import math
from typing import Any

from .episode_stage1 import SCHEMA as EPISODE_PACKET_SCHEMA

SCHEMA = "TacticalOptionsV0"
POLICY = {
    "version": "tactical-options-policy/0.1",
    "contest_first_s": 0.15,        # focus earlier than the carrier by at least this: focus arrives first
    "contest_even_s": 0.30,         # |contest window| within this: a genuine fifty-fifty
    "fake_range_s": 1.00,           # late by more than contest_even_s but within this: close enough to fake
    "possession_window_s": 0.30,    # focus earlier by at least this: time for a controlled touch
    "cover_window_s": 1.00,         # teammate goal-side within this after the carrier's touch: covered
    "spill_close_s": 0.60,          # second opponent within this of the carrier: a loose ball is contested
    "immediate_threat_s": 0.60,     # carrier can touch within this
    "low_boost": 25.0,
    "shadow_room_uu": 2500.0,       # ball closer than this to the own goal: little room to delay
    "note": "Bands are uncalibrated hypotheses; expert tactical-merit ratings should replace them.",
}
GOAL_Y = 5120.0
ACTIONS = ("immediate_challenge", "controlled_fifty_fifty", "fake_challenge", "shadow_delay", "goal_side_hold",
           "rotate_through_small_pads", "controlled_touch", "clear_or_pass_to_space", "yield_to_teammate")
UNOBSERVABLE_DEPENDENCIES = {
    "immediate_challenge": ["flip availability", "carrier's intent"],
    "controlled_fifty_fifty": ["flip availability", "contact angle the player intends"],
    "fake_challenge": ["carrier's intent and read of the fake", "camera awareness"],
    "shadow_delay": ["camera awareness of the second opponent"],
    "goal_side_hold": ["camera awareness"],
    "rotate_through_small_pads": ["teammate's intended rotation (comms)"],
    "controlled_touch": ["ball spin", "player's dribbling execution"],
    "clear_or_pass_to_space": ["contact angle and ball destination"],
    "yield_to_teammate": ["teammate's intent (comms)"],
}


class TacticalOptionsError(ValueError):
    """The input is not an audited Stage 1 episode packet."""


# ---------- small helpers ----------

def _finite(v: Any) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


def _r(v: float, nd: int) -> float:
    return round(float(v), nd)


class _Claims:
    """Claims in claim_verifier's record shape, citing node-local ids."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.items: list[dict] = []

    def add(self, ctype: str, refs: list[str], text: str, preds: list[dict] | None = None) -> str:
        cid = f"{self.node_id}.c{len(self.items) + 1}"
        rec = {"claim_id": cid, "epistemic_type": ctype, "temporal_scope": "PRE_DECISION",
               "cited_evidence_ids": list(dict.fromkeys(refs)), "text": text}
        if preds:
            rec["predicate_checks"] = preds
        self.items.append(rec)
        return cid


def _pred(ref: str, path: list, value: Any) -> dict:
    return {"evidence_id": ref, "value_path": path, "relation": "eq", "stated_value": value}


# ---------- state ----------

class _State:
    def __init__(self, packet: dict) -> None:
        self.ev = {e["id"]: e for e in packet["evidence"]}
        self.unknown = {u["id"] for u in packet["unknowns"]}
        self.slots = packet["slots"]
        self.team = self.slots.get("focus", {}).get("team")
        self.sign = 1.0 if self.team == "blue" else -1.0

    def val(self, ref: str) -> Any:
        e = self.ev.get(ref)
        return None if e is None else e["value"]

    def reach(self, slot: str) -> tuple[float | None, str | None]:
        """(t_min, status); out_of_horizon -> (inf, status); unknown -> (None, None)."""
        v = self.val(f"E.reach.{slot}")
        if not isinstance(v, dict):
            return None, None
        if v.get("status") == "ok" and _finite(v.get("t_min_s")):
            return float(v["t_min_s"]), "ok"
        if v.get("status") == "out_of_horizon":
            return math.inf, "out_of_horizon"
        return None, None

    def rel_y(self, ref: str) -> float | None:
        p = self.val(ref)
        return None if not isinstance(p, list) else self.sign * p[1]


def _features(s: _State) -> dict[str, Any]:
    opps = [k for k in s.slots if k.startswith("opponent")]
    opp_t = {k: s.reach(k)[0] for k in opps}
    known_opp = {k: v for k, v in opp_t.items() if v is not None}
    carrier = min(known_opp, key=known_opp.get) if known_opp and len(known_opp) == len(opps) else None
    carrier_t = known_opp.get(carrier) if carrier else None
    second = next((k for k in opps if k != carrier), None) if carrier else None
    second_t = opp_t.get(second) if second else None
    focus_t, _ = s.reach("focus")
    mate_t, _ = s.reach("teammate")
    cover = s.val("E.cover.teammate") if "E.cover.teammate" in s.ev else None
    cover_known = "E.cover.teammate" in s.ev
    cover_t = (math.inf if cover is None else float(cover)) if cover_known else None
    ball = s.val("E.ball.position")
    ball_v = s.val("E.ball.velocity")
    ball_rel_y = None if not isinstance(ball, list) else s.sign * ball[1]
    toward_own = None if not isinstance(ball_v, list) else -s.sign * ball_v[1]
    fy, my = s.rel_y("E.focus.position"), s.rel_y("E.teammate.position")
    fpos = s.val("E.focus.position")

    def diff(a, b):
        return None if a is None or b is None or math.isinf(a) and math.isinf(b) else a - b

    f = {
        "carrier_slot": carrier, "carrier_t": carrier_t, "second_opponent_slot": second, "second_opponent_t": second_t,
        "focus_t": focus_t, "teammate_t": mate_t, "cover_t": cover_t,
        "contest_window_s": diff(focus_t, carrier_t),
        "spill_support_s": diff(second_t, carrier_t),
        "cover_margin_s": diff(cover_t, carrier_t),
        "ball_rel_y": ball_rel_y, "ball_to_own_goal_uu": None if not isinstance(ball, list) else
        math.dist((ball[0], ball_rel_y), (0.0, -GOAL_Y)),
        "ball_speed_toward_own_goal": toward_own,
        "focus_goal_side": None if fy is None or ball_rel_y is None else fy < ball_rel_y,
        "teammate_goal_side": None if my is None or ball_rel_y is None else my < ball_rel_y,
        "teammate_deeper_than_focus": None if my is None or fy is None else my < fy,
        "focus_boost": s.val("E.focus.boost") if "E.focus.boost" in s.ev else None,
        "focus_on_ground": None if not isinstance(fpos, list) else fpos[2] < 40.0,
        "focus_to_own_goal_uu": None if not isinstance(fpos, list) or fy is None else math.dist((fpos[0], fy), (0.0, -GOAL_Y)),
    }
    cw = f["contest_window_s"]
    f["contest_band"] = (None if cw is None or math.isnan(cw) else
                         "focus_first" if cw <= -POLICY["contest_first_s"] else
                         "even" if abs(cw) <= POLICY["contest_even_s"] else
                         "focus_late_close" if cw <= POLICY["fake_range_s"] else "focus_late")
    cm = f["cover_margin_s"]
    f["covered"] = None if cm is None or (isinstance(cm, float) and math.isnan(cm)) else cm <= POLICY["cover_window_s"]
    sp = f["spill_support_s"]
    f["second_opponent_close"] = None if sp is None or (isinstance(sp, float) and math.isnan(sp)) else sp <= POLICY["spill_close_s"]
    f["immediate_threat"] = (None if carrier_t is None or ball_rel_y is None else
                             carrier_t <= POLICY["immediate_threat_s"] and (ball_rel_y < 0 or (toward_own or 0) > 500))
    f["low_boost"] = None if f["focus_boost"] is None else f["focus_boost"] < POLICY["low_boost"]
    f["possession_available"] = None if cw is None or math.isnan(cw) else cw <= -POLICY["possession_window_s"]
    f["teammate_can_play"] = (None if mate_t is None or focus_t is None else
                              mate_t <= (focus_t + POLICY["contest_even_s"]) if not math.isinf(mate_t) else False)
    return {k: (None if isinstance(v, float) and (math.isnan(v)) else v) for k, v in f.items()}


# ---------- claims about the state ----------

def _reach_claim(c: _Claims, s: _State, slot: str, label: str) -> str | None:
    t, status = s.reach(slot)
    ref = f"E.reach.{slot}"
    if t is None:
        return None
    if status == "out_of_horizon":
        return c.add("PHYSICALLY_ESTIMATED_FEASIBILITY", [ref], f"{label} cannot reach the ball within the model horizon.")
    return c.add("PHYSICALLY_ESTIMATED_FEASIBILITY", [ref],
                 f"{label} can touch the ball at the earliest {_r(t, 2)} s after the decision (kinematic lower bound).",
                 [_pred(ref, ["t_min_s"], _r(t, 2))])


def _state_claims(c: _Claims, s: _State, f: dict) -> dict[str, str | None]:
    out = {"focus_reach": _reach_claim(c, s, "focus", "The focus player"),
           "teammate_reach": _reach_claim(c, s, "teammate", "The teammate")}
    if f["carrier_slot"]:
        out["carrier_reach"] = _reach_claim(c, s, f["carrier_slot"], "The nearest opponent")
    if f["second_opponent_slot"]:
        out["second_reach"] = _reach_claim(c, s, f["second_opponent_slot"], "The other opponent")
    if "E.cover.teammate" in s.ev:
        v = s.val("E.cover.teammate")
        out["cover"] = c.add("PHYSICALLY_ESTIMATED_FEASIBILITY", ["E.cover.teammate"],
                             "The teammate is already between the ball and the own goal." if v == 0 else
                             "The teammate cannot get goal-side within the model horizon." if v is None else
                             f"The teammate could be goal-side at the earliest {_r(v, 2)} s after the decision.",
                             None if v in (None, 0) else [_pred("E.cover.teammate", [], _r(v, 2))])
    if f["focus_boost"] is not None:
        out["focus_boost"] = c.add("OBSERVED_FACT", ["E.focus.boost"],
                                   f"The focus player has {_r(f['focus_boost'], 1)} boost (freshness unverified).",
                                   [_pred("E.focus.boost", [], _r(f["focus_boost"], 1))])
    if isinstance(s.val("E.ball.position"), list):
        b = s.val("E.ball.position")
        out["ball"] = c.add("OBSERVED_FACT", ["E.ball.position"],
                            f"The ball is at height {round(b[2])} uu.", [_pred("E.ball.position", [2], round(b[2]))])
    return out


# ---------- options ----------

def _option(action: str, feasible: str, basis: list[str], supports: list[str], limits: list[str],
            severe: list[str], depends_on_teammate: bool, risk: str, team_constraints: list[str]) -> dict:
    if feasible == "no":
        stance = "not_available"
    elif feasible == "unknown":
        stance = "not_assessable"
    elif severe and len(supports) < len(limits):
        stance = "questionable"          # a severe limit and more limits than supports
    elif supports and not severe:
        stance = "defensible"
    else:
        stance = "defensible_with_conditions"
    return {"action": action, "physically_feasible": feasible, "feasibility_claims": basis,
            "supporting_claims": supports, "limiting_claims": limits, "severe_limit_claims": severe,
            "strategic_stance": stance, "depends_on_teammate": depends_on_teammate,
            "defensive_risk": risk, "team_context_claims": team_constraints,
            "depends_on_unobservable": UNOBSERVABLE_DEPENDENCIES[action]}


def _tri(v: bool | None, yes: str = "yes", no: str = "no") -> str:
    return "unknown" if v is None else (yes if v else no)


def _options(c: _Claims, s: _State, f: dict, sc: dict) -> list[dict]:
    T = "TACTICAL_INFERENCE"
    reach_refs = [r for r in ("E.reach.focus", f"E.reach.{f['carrier_slot']}" if f["carrier_slot"] else None) if r in s.ev]
    cover_ref = ["E.cover.teammate"] if "E.cover.teammate" in s.ev else []
    second_ref = [f"E.reach.{f['second_opponent_slot']}"] if f["second_opponent_slot"] and \
        f"E.reach.{f['second_opponent_slot']}" in s.ev else []
    band = f["contest_band"]
    claim = {}

    def once(key, ctype, refs, text):
        if key not in claim and refs:
            claim[key] = c.add(ctype, refs, text)
        return claim.get(key)

    # reusable interpretations (cite the facts they rest on)
    if band:
        once("band", T, reach_refs, {
            "focus_first": "The focus player can reach the ball clearly before the nearest opponent.",
            "even": "The focus player and the nearest opponent can arrive at about the same time: a genuine fifty-fifty.",
            "focus_late_close": "The nearest opponent can touch first; the focus player is close enough to pressure or fake.",
            "focus_late": "The nearest opponent can touch well before the focus player could.",
        }[band])
    if f["covered"] is not None:
        once("cover", T, cover_ref + reach_refs[1:], "The teammate can get goal-side in time to cover a beaten challenge."
             if f["covered"] else "The teammate cannot get goal-side in time to cover a beaten challenge.")
    if f["second_opponent_close"] is not None:
        once("spill", T, second_ref + reach_refs[1:], "The other opponent is close enough to collect a loose ball."
             if f["second_opponent_close"] else "The other opponent is far from a loose ball.")
    if f["immediate_threat"]:
        once("threat", T, reach_refs[1:] + ["E.ball.position"], "An opponent can play the ball soon in or toward the own half.")
    if f["low_boost"]:
        once("low_boost", T, ["E.focus.boost"], "The focus player is low on boost, which slows a recovery after a commit.")
    if f["ball_to_own_goal_uu"] is not None and f["ball_to_own_goal_uu"] < POLICY["shadow_room_uu"]:
        once("no_room", T, ["E.ball.position"], "The ball is close to the own goal, leaving little room to delay.")
    if f["teammate_can_play"]:
        once("mate_play", T, [r for r in ("E.reach.teammate", "E.reach.focus") if r in s.ev],
             "The teammate can reach the ball about as early as the focus player.")
    if f["focus_goal_side"] is not None:
        once("goal_side", "OBSERVED_FACT", ["E.focus.position", "E.ball.position"],
             "The focus player is goal-side of the ball." if f["focus_goal_side"] else "The focus player is not goal-side of the ball.")
    if f["teammate_deeper_than_focus"] is not None:
        once("mate_deeper", "OBSERVED_FACT", ["E.teammate.position", "E.focus.position"],
             "The teammate is deeper (nearer the own goal) than the focus player." if f["teammate_deeper_than_focus"]
             else "The teammate is further up-field than the focus player.")

    covered, spill, threat = f["covered"], f["second_opponent_close"], f["immediate_threat"]
    team_ctx = [claim[k] for k in ("cover", "mate_deeper") if k in claim and covered is False]
    risk_commit = "unknown" if covered is None else ("elevated" if (covered is False or f["low_boost"]) else "not_elevated")
    G = lambda *keys: [claim[k] for k in keys if k in claim]  # noqa: E731
    focus_feasible = "unknown" if f["focus_t"] is None else ("no" if math.isinf(f["focus_t"]) else "yes")
    opts = []

    # 1 immediate challenge
    sup = G("band") if band in ("focus_first", "even") else []
    sup += G("cover") if covered else []
    sup += G("spill") if spill is False else []
    lim = G("band") if band in ("focus_late", "focus_late_close") else []
    lim += G("cover") if covered is False else []
    lim += G("spill") if spill else []
    lim += G("low_boost")
    sev = G("band") if band == "focus_late" else []
    sev += G("cover") if covered is False and band in ("focus_late", "focus_late_close") else []
    opts.append(_option("immediate_challenge", focus_feasible, [sc["focus_reach"]] if sc.get("focus_reach") else [],
                        sup, lim, sev, True, risk_commit, team_ctx))
    # 2 controlled fifty-fifty (a deliberate contest, possibly played toward the teammate)
    feas = "unknown" if band is None else ("yes" if band == "even" else "no")
    sup = G("band") + (G("cover") if covered else []) + (G("mate_deeper") if f["teammate_deeper_than_focus"] else [])
    lim = (G("cover") if covered is False else []) + (G("spill") if spill else [])
    opts.append(_option("controlled_fifty_fifty", feas, G("band"), sup if feas == "yes" else [], lim,
                        G("cover") if covered is False and spill else [], True, risk_commit, team_ctx))
    # 3 fake challenge
    # a fake needs the defender in front of the carrier (goal-side), on the ground, close but not first
    feas = "unknown" if None in (band, f["focus_on_ground"], f["focus_goal_side"]) else (
        "yes" if band == "focus_late_close" and f["focus_on_ground"] and f["focus_goal_side"] else "no")
    opts.append(_option("fake_challenge", feas, G("band", "goal_side"), G("band", "goal_side") if feas == "yes" else [],
                        G("spill") if spill else [], [], False, "not_elevated" if f["focus_goal_side"] else "unknown", []))
    # 4 shadow delay
    feas = _tri(None if f["focus_goal_side"] is None or f["focus_on_ground"] is None
                else f["focus_goal_side"] and f["focus_on_ground"])
    sup = (G("band") if band in ("focus_late", "focus_late_close") else []) + (G("cover") if covered is False else []) \
        + (G("spill") if spill else [])
    lim = G("no_room") + (G("band") if band == "focus_first" else [])
    opts.append(_option("shadow_delay", feas, G("goal_side"), sup, lim, G("no_room") if threat else [], False,
                        "elevated" if "no_room" in claim and threat else ("unknown" if threat is None else "not_elevated"), []))
    # 5 goal-side hold
    feas = "yes" if f["focus_to_own_goal_uu"] is not None else "unknown"
    sup = (G("threat") if threat else []) + (G("cover") if covered is False else []) + (G("mate_play") if f["teammate_can_play"] else [])
    lim = G("band") if band == "focus_first" else []
    opts.append(_option("goal_side_hold", feas, G("goal_side"), sup, lim, [], True,
                        "not_elevated" if f["focus_goal_side"] else "unknown", team_ctx))
    # 6 rotate through small pads
    feas = "yes" if f["focus_boost"] is not None or "U.focus.boost" in s.unknown else "unknown"
    sup = G("low_boost") + (G("mate_play") if f["teammate_can_play"] else [])
    lim = (G("threat") if threat and covered is False else []) + (G("band") if band == "focus_first" else [])
    opts.append(_option("rotate_through_small_pads", feas, [sc["focus_boost"]] if sc.get("focus_boost") else [], sup, lim,
                        G("threat") if threat and covered is False else [], True,
                        "elevated" if threat and covered is False else "unknown" if threat is None else "not_elevated", team_ctx))
    # 7 controlled touch / possession
    feas = _tri(f["possession_available"])
    opts.append(_option("controlled_touch", feas, G("band"), G("band") + (G("spill") if spill is False else []) if feas == "yes" else [],
                        G("spill") if spill else [], [], False, risk_commit, []))
    # 8 clear or pass to space
    feas = "unknown" if band is None else ("yes" if band in ("focus_first", "even") else "no")
    opts.append(_option("clear_or_pass_to_space", feas, G("band"),
                        (G("threat") if threat else []) + (G("band") if feas == "yes" else []),
                        G("spill") if spill else [], [], False, risk_commit, []))
    # 9 yield to teammate
    feas = _tri(f["teammate_can_play"])
    sup = G("mate_play") + (G("low_boost"))
    lim = (G("mate_deeper") if f["teammate_deeper_than_focus"] else []) + (G("threat", "cover") if threat and covered is False else [])
    opts.append(_option("yield_to_teammate", feas, G("mate_play"), sup if feas == "yes" else [], lim, [], True,
                        "unknown", team_ctx))
    return opts


# ---------- earlier contributors ----------

BEARS_ON = {"boost": ["immediate_challenge", "controlled_fifty_fifty", "rotate_through_small_pads"],
            "advance": ["shadow_delay", "goal_side_hold"],
            "roles": ["yield_to_teammate", "immediate_challenge"],
            "teammate_cover": ["immediate_challenge", "controlled_fifty_fifty", "shadow_delay"],
            "timeline": ["immediate_challenge", "goal_side_hold"]}


def _earlier(packet: dict, node_id: str) -> list[dict]:
    changes = {c["id"]: c for c in packet["changes"]}
    out = []
    for h in packet["possible_earlier_contributors"]:
        if h["concerns_node"] != node_id:
            continue
        kind = "timeline"
        for ref in h["evidence_refs"]:
            if ref.startswith("D."):
                kind = ("boost" if ref.endswith(".focus.boost") else "advance" if "advance" in ref else
                        "roles" if ref.endswith("roles.own") else "teammate_cover" if ref.endswith("teammate_cover") else kind)
        observed = [{"change_id": r, "value": changes[r]["value"], "unit": changes[r]["unit"],
                     "known_at_s": changes[r]["known_at_s"]} for r in h["evidence_refs"] if r in changes]
        out.append({"hypothesis_id": h["id"], "earlier_node": h["earlier_node"], "kind": kind,
                    "observed_changes": observed, "evidence_refs": h["evidence_refs"],
                    "bears_on_actions": BEARS_ON[kind], "status": "hypothesis_unverified",
                    "would_need": "Expert review of the earlier decision with its own decision-time evidence; "
                                  "the observed change alone does not show the earlier choice was a mistake or a cause."})
    return out


# ---------- public API ----------

def analyze_tactical_options(stage1_episode_packet: dict[str, Any], *, focus_node_id: str | None = None) -> dict[str, Any]:
    """Tactical options at one decision node of a Stage1EpisodePacketV0 (default: the primary node)."""
    p = stage1_episode_packet
    if not isinstance(p, dict) or p.get("schema") != EPISODE_PACKET_SCHEMA:
        raise TacticalOptionsError("Expected a Stage1EpisodePacketV0.")
    if p.get("retrospective_present") is not False or "retrospective" in p:
        raise TacticalOptionsError("Stage 1 input must not contain retrospective material.")
    nodes = {n["node_id"]: n for n in p["nodes"]}
    nid = focus_node_id or next(n["node_id"] for n in p["nodes"] if n["is_primary"])
    if nid not in nodes:
        raise TacticalOptionsError(f"Unknown node {nid}.")
    node = nodes[nid]
    packet = node["packet"]
    c = _Claims(nid)
    base = {"schema": SCHEMA, "policy": POLICY, "node_id": nid, "t0": node["t0"],
            "information_cutoff_s": node["t0"], "is_primary": node["is_primary"],
            "claims_verify_with": "claim_verifier.verify_stage1_claims(node packet, claims)",
            "uses_retrospective": False, "picks_single_best": False}
    abstain: list[str] = []
    if packet["status"] == "abstain":
        abstain.append("No decision-time frame for this node.")
        return {**base, "status": "abstain", "abstain_reasons": abstain, "claims": [], "state": {}, "options": [],
                "defensible_options": [], "unknowns": packet["unknowns"],
                "not_observable": packet.get("not_observable", []), "earlier_contributors": _earlier(p, nid)}
    s = _State(packet)
    f = _features(s)
    sc = _state_claims(c, s, f)
    options = _options(c, s, f, sc)
    for key, why in (("focus_t", "The focus player's earliest touch is unknown."),
                     ("carrier_t", "An opponent's earliest touch is unknown, so the contest timing is unknown."),
                     ("covered", "Teammate cover is unknown."),
                     ("focus_boost", "The focus player's boost is unknown.")):
        if f.get(key) is None:
            abstain.append(why)
    defensible = [o["action"] for o in options if o["strategic_stance"] in ("defensible", "defensible_with_conditions")]
    unknown_claims = [c.add("UNKNOWN_INFORMATION", [u["id"]], f"{u['what']} is unknown: {u['why']}.")
                      for u in packet["unknowns"] if u["id"].startswith("U.")][:12]
    team_ctx = sorted({x for o in options for x in o["team_context_claims"]})
    state = {k: (None if isinstance(v, float) and math.isinf(v) else (_r(v, 3) if isinstance(v, float) else v))
             for k, v in f.items()}
    state["claims"] = {k: v for k, v in sc.items() if v}
    return {
        **base,
        "status": "partial" if abstain else "ok",
        "state": state,
        "threats": {"immediate_threat": f["immediate_threat"], "carrier_slot": f["carrier_slot"],
                    "second_opponent_close": f["second_opponent_close"]},
        "teammate_support": {"covered": f["covered"], "teammate_deeper_than_focus": f["teammate_deeper_than_focus"],
                             "teammate_can_play": f["teammate_can_play"], "team_context_claims": team_ctx,
                             "attribution": "Constraints created by the teammate's position are team context; "
                                            "they are not attributed to the focus player's decision."},
        "options": options,
        "defensible_options": defensible,
        "multiple_defensible": len(defensible) > 1,
        "abstain_reasons": abstain,
        "unknown_claims": unknown_claims,
        "unknowns": packet["unknowns"],
        "not_observable": packet.get("not_observable", []),
        "earlier_contributors": _earlier(p, nid),
        "claims": c.items,
        "layers": {"observed": "claims of type OBSERVED_FACT",
                   "feasibility": "claims of type PHYSICALLY_ESTIMATED_FEASIBILITY and options[].physically_feasible",
                   "interpretation": "claims of type TACTICAL_INFERENCE and options[].strategic_stance",
                   "hypothetical": "options are alternatives, not predictions of what would have happened",
                   "outcomes": "not available here (Stage 2)"},
    }

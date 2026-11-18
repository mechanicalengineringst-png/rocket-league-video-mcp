"""CoachingFindingV1: from a condition ledger to a specific, auditable coaching finding (Round 12).

A finding has two strictly separated stages:

**Stage A (decision time, t0 and earlier only).** What the situation was, which conditions held at
t0 (with the measured numbers behind them), which alternatives were reasonable and what each would
preserve, gain, sacrifice or risk *given those conditions*, which assumptions decide between them, and
what to read next time. Built from ``situation_rationale.analyze_situation`` output only.

**Stage B (retrospective, kept apart).** What the player actually did (a heuristic label from the
next seconds of movement and touches), how that action compares with the Stage A ledger, and what
happened next. The outcome is reported, never used to grade: a sound choice followed by a goal is
still sound, and a refuted choice that worked is still flagged.

Every number in a finding's text is drawn from ``numbers`` (each with a source id: ``E.`` packet
evidence or ``Q.`` derived quantity); ``check_finding_numbers`` enforces that. Text fragments are
deterministic templates selected by condition status, not free generation.
"""
from __future__ import annotations

import bisect
import math
import re
from typing import Any

from .action_rationale import FAILS, HOLDS, UNCERTAIN, UNKNOWN, UNOBS, _lit
from .decision_state_v1 import _scenario
from .tactical_options import _State

SCHEMA = "CoachingFindingV1"
VERSION = "coaching-findings/0.1"
GOAL_Y = 5120.0
NUM_RE = re.compile(r"(?<![A-Za-z_.])-?\d+(?:\.\d+)?")

CLASS_LABEL = {
    "first_defender": "First defender: first to the ball in your half with an opponent able to contest",
    "possession": "In possession of the ball",
    "offensive_first_man": "First player to a ball in the opponent half",
    "second_man_support": "Second man while the teammate plays the ball",
    "loose_ball": "Loose ball in transition",
    "recovery_and_boost": "Recovering back into play",
    "aerial_or_wall": "Aerial or wall situation",
}
WHY_IT_MATTERS = {
    "first_defender": "The first defender's choice decides whether the opponent gets a free play and whether the teammate is left alone.",
    "possession": "What you do with the ball decides whether the possession turns into pressure or into a turnover with nobody back.",
    "offensive_first_man": "As first man forward, a challenge here either keeps pressure on or opens a counter behind you.",
    "second_man_support": "Second-man position decides whether your teammate's play can be followed up or covered if it fails.",
    "loose_ball": "Who commits to a loose ball, and who waits, decides the next possession.",
    "recovery_and_boost": "The route back decides how soon you are useful again and with how much boost.",
    "aerial_or_wall": "Aerial and wall mechanics are not modelled, so only observations are given.",
}

# ---------- action knowledge: what each alternative preserves, gains, sacrifices, risks ----------
# Fragments are (literal or None, text). A fragment is shown when its literal holds; when it is
# uncertain, it is shown as conditional; when it fails, it is omitted. {name} placeholders are filled
# from the finding's numbers and the fragment is dropped if a value is missing.

A = dict
ACTIONS: dict[str, dict[str, Any]] = {
    "immediate_challenge": A(label="Challenge now", family="touch",
        gains=[(None, "takes time from the opponent before they settle it"),
               ("focus_first", "arriving first lets you choose the contact")],
        preserves=[("teammate_covers", "your teammate stays as the last line")],
        sacrifices=[(None, "your goal-side position for the next seconds"),
                    ("!boost_for_recovery", "a quick recovery: you have {boost} boost")],
        risks=[("carrier_first", "the opponent touches first ({carrier_t} s vs {focus_t} s) and can go past you"),
               ("!teammate_covers", "if beaten, your teammate needs {cover_s} s to get goal-side"),
               ("!loose_ball_ours", "a rebound favours their second player ({second_t} s vs your teammate {mate_t} s)")]),
    "controlled_fifty_fifty": A(label="Controlled 50/50", family="touch",
        gains=[(None, "neutralises their touch without over-committing")],
        preserves=[("teammate_covers", "coverage behind you"), (None, "a ball that stays near you after a soft contact")],
        sacrifices=[(None, "control of the ball's direction: it is shared, not chosen")],
        risks=[("!loose_ball_ours", "the ball pops toward their second player"),
               ("!teammate_covers", "a bad bounce with nobody behind")]),
    "controlled_touch": A(label="Take it with a controlled touch", family="touch",
        gains=[(None, "possession and the next decision")],
        preserves=[("teammate_covers", "your shape: your teammate stays back")],
        sacrifices=[(None, "tempo: the opponents get time to recover goal-side")],
        risks=[("!loose_ball_ours", "a heavy touch hands the loose ball to their second player"),
               ("carrier_first", "they arrive first and the touch never happens")]),
    "shadow_delay": A(label="Shadow and delay", family="hold",
        gains=[(None, "time for your teammate to recover"),
               ("carrier_controls", "forces the opponent in control to make the first move")],
        preserves=[("focus_goal_side", "your goal-side position"), (None, "your boost and flip for the save")],
        sacrifices=[(None, "pressure on the ball"), ("focus_first", "a ball you could reach first")],
        risks=[("!room_to_delay", "little space to give: the ball is {ball_own_goal_uu} uu from your goal"),
               (None, "a well-timed shot or pass from the carrier")]),
    "goal_side_hold": A(label="Hold goal-side", family="hold",
        gains=[(None, "a safe last line")], preserves=[(None, "net coverage and boost")],
        sacrifices=[(None, "any pressure on the ball"), ("focus_first", "a winnable ball")],
        risks=[("carrier_controls", "an opponent in control gets free time to set up")]),
    "fake_challenge": A(label="Fake challenge", family="hold",
        gains=[(None, "can force a rushed touch without committing")],
        preserves=[("focus_goal_side", "your goal-side position"), (None, "your flip")],
        sacrifices=[(None, "a little speed if they do not react")],
        risks=[(None, "a patient carrier simply gets more time")]),
    "yield_to_teammate": A(label="Leave it to your teammate", family="hold",
        gains=[(None, "no double commit")], preserves=[(None, "cover behind your teammate")],
        sacrifices=[(None, "a quick second touch")],
        risks=[("carrier_first", "if your teammate is beaten you are the last defender")]),
    "rotate_through_small_pads": A(label="Rotate through small pads", family="boost",
        gains=[(None, "boost without leaving the play")], preserves=[("teammate_covers", "your teammate covers the ball")],
        sacrifices=[(None, "immediate presence on the ball")],
        risks=[("!teammate_covers", "nobody on the ball while you refill")]),
    "clear_or_pass_to_space": A(label="Clear or pass to space", family="touch",
        gains=[(None, "distance between the ball and your goal")], preserves=[(None, "time for both of you to reset")],
        sacrifices=[(None, "possession")],
        risks=[("!loose_ball_ours", "the clear lands with their second player while you are out of position")]),
    # possession
    "keep_possession": A(label="Keep it and build", family="keep",
        gains=[("time_before_pressure", "time to choose: no opponent can touch it for {pressure_s} s")],
        preserves=[("!play_uncovered_if_lost", "your shape: your teammate can be goal-side if you lose it")],
        sacrifices=[(None, "tempo: defenders recover while you carry")],
        risks=[("!time_before_pressure", "pressure arrives in {pressure_s} s, before you can use the ball"),
               ("play_uncovered_if_lost", "a dispossession leaves nobody goal-side")]),
    "shoot_now": A(label="Shoot now", family="shot",
        gains=[("shot_lane_open", "an open lane: {shot_open_lines} of 9 lines to goal unblocked")],
        preserves=[], sacrifices=[(None, "possession: a saved shot usually hands them the ball")],
        risks=[("!shot_lane_open", "a defender reaches the shot line first (margin {shot_margin_s} s)"),
               ("play_uncovered_if_lost", "a blocked shot with nobody back")]),
    "pass_or_center": A(label="Pass or centre to your teammate", family="pass",
        gains=[("teammate_forward_option", "uses your teammate, who could reach the ball in {mate_t} s")],
        preserves=[(None, "attacking momentum")], sacrifices=[(None, "control: your teammate must win the next touch")],
        risks=[("!teammate_forward_option", "with nobody to receive, a pass is a clear to the opponents")]),
    "push_forward": A(label="Push it forward to keep pressure", family="push",
        gains=[(None, "keeps the attack moving past an arriving defender"),
               ("teammate_forward_option", "your teammate can follow up ({mate_t} s from the ball)")],
        preserves=[(None, "field position in their half")], sacrifices=[(None, "control of the ball")],
        risks=[("!teammate_forward_option", "nobody follows up, so the defender collects it"),
               ("play_uncovered_if_lost", "a counter with nobody back")]),
    "clear_to_space": A(label="Clear to space", family="clear",
        gains=[("ball_in_own_half", "distance from your goal")], preserves=[],
        sacrifices=[(None, "a possession you already have")],
        risks=[(None, "clearing a controlled ball usually gives it back")]),
    "wait_for_support": A(label="Slow down and wait for support", family="keep",
        gains=[(None, "time for your teammate to join")], preserves=[(None, "possession")],
        sacrifices=[(None, "tempo")], risks=[("!time_before_pressure", "waiting under pressure loses the ball")]),
    # recovery
    "return_direct": A(label="Return directly", family="direct",
        gains=[(None, "the fastest way back: {direct_s} s to the goal-side point")],
        preserves=[(None, "defensive coverage")],
        sacrifices=[("low_boost", "boost: you arrive with {boost} and cannot challenge strongly")], risks=[]),
    "small_pad_route": A(label="Return through small pads", family="small_pads",
        gains=[("small_pads_on_route", "refill on the way: {small_pads} available small pads lie on the line back")],
        preserves=[(None, "near-direct timing")], sacrifices=[(None, "small detours from the straight line")],
        risks=[("threat_now", "any detour while an opponent is attacking")]),
    "big_boost_detour": A(label="Detour for big boost", family="big_boost",
        gains=[(None, "a full tank for the next challenge or save")], preserves=[],
        sacrifices=[(None, "time: {detour_extra_s} s longer than returning directly")],
        risks=[("threat_now", "being out of the play while an opponent attacks"),
               ("!big_pad_available", "the pad is not there (taken recently)")]),
    # second man
    "support_behind": A(label="Support from behind", family="support",
        gains=[(None, "cover if your teammate is beaten")], preserves=[(None, "your boost and a clean rotation")],
        sacrifices=[(None, "a quick follow-up on a weak clear")],
        risks=[("!focus_covers_teammate", "you are {focus_cover_s} s from goal-side: too far to cover")]),
    "aggressive_follow_up": A(label="Support close for a follow-up", family="support_close",
        gains=[(None, "a second touch if their clear is weak"), ("opponents_far", "both opponents are far from the ball")],
        preserves=[("focus_covers_teammate", "the ability to get goal-side ({focus_cover_s} s)")],
        sacrifices=[(None, "defensive depth")],
        risks=[("!focus_covers_teammate", "if they break out, nobody is back"),
               ("double_commit_risk", "driving at the ball your teammate is playing ({closing} uu/s toward it)")]),
    "boost_while_teammate_plays": A(label="Collect boost while your teammate plays it", family="boost",
        gains=[("low_boost", "boost for your next role (you have {boost})"),
               ("boost_route_keeps_cover", "a full rotation: the {boost_pad} pad route still reaches goal-side in {boost_cover_s} s")],
        preserves=[("boost_route_keeps_cover", "cover behind your teammate")],
        sacrifices=[(None, "support for your teammate's play")],
        risks=[("carrier_first", "an opponent wins the ball while you are away"),
               ("!boost_route_keeps_cover", "the pad route takes {boost_cover_s} s to get goal-side, too slow to cover")]),
    "challenge_as_well": A(label="Challenge as well", family="touch",
        gains=[("contest_level", "a second body in a contested ball")], preserves=[],
        sacrifices=[(None, "all coverage behind")],
        risks=[("teammate_first", "a double commit on a ball your teammate already has")]),
}

# Readings: second-person descriptions of a condition's status, with the numbers behind it.
# Entries are (status, template[, required_flag]); the first entry whose status matches and whose
# placeholders (and flag) are all available is used. Status "within" covers within_error.
H, F, W = "holds", "fails", "within_error"
READINGS: dict[str, list[tuple]] = {
    "focus_first": [(H, "you could touch the ball first ({focus_t} s vs {carrier_t} s)"),
                    (F, "the nearest opponent could touch the ball before you ({carrier_t} s vs {focus_t} s)"),
                    (W, "arrival order was inside the model error ({focus_t} s vs {carrier_t} s)")],
    "carrier_first": [(H, "the nearest opponent could touch the ball first ({carrier_t} s vs your {focus_t} s)"),
                      (F, "you could touch the ball before the nearest opponent ({focus_t} s vs {carrier_t} s)"),
                      (W, "arrival order was inside the model error ({focus_t} s vs {carrier_t} s)")],
    "contest_level": [(H, "arrival order could not be separated (earliest touches {focus_t} s vs {carrier_t} s, allowing for "
                          "model error and approach uncertainty): a genuine contest"),
                      (F, "one side was clearly first to the ball ({focus_t} s vs {carrier_t} s)")],
    "teammate_covers": [(H, "your teammate was already goal-side", "teammate_already_goal_side"),
                        (H, "your teammate could be goal-side in {cover_s} s, in time if you were beaten"),
                        (F, "your teammate needed {cover_s} s to get goal-side, too late if you were beaten"),
                        (F, "your teammate could not get goal-side in time if you were beaten"),
                        (W, "whether your teammate could cover in time was inside the model error")],
    "loose_ball_ours": [(H, "for a loose ball your teammate was ahead of their second player ({mate_t} s vs {second_t} s)"),
                        (F, "for a loose ball their second player was ahead of your teammate ({second_t} s vs {mate_t} s)")],
    "teammate_first": [(H, "your teammate could reach the ball first ({mate_t} s vs your {focus_t} s)"),
                       (F, "you were your team's first player to the ball ({focus_t} s vs {mate_t} s)")],
    "focus_goal_side": [(H, "you were goal-side of the ball"), (F, "you were not goal-side of the ball")],
    "focus_grounded": [(H, "you were on the ground"), (F, "you were in the air")],
    "boost_for_recovery": [(H, "you had {boost} boost"), (F, "you had only {boost} boost")],
    "room_to_delay": [(H, "the ball was {ball_own_goal_uu} uu from your goal: room to give ground"),
                      (F, "the ball was only {ball_own_goal_uu} uu from your goal: no room to give ground")],
    "carrier_controls": [(H, "the nearest opponent had the ball under control"), (F, "no opponent had the ball under control")],
    "teammate_deeper": [(H, "your teammate was deeper than you"), (F, "you were your team's last player back")],
    "time_before_pressure": [(H, "no opponent could touch the ball for {pressure_s} s"),
                             (F, "an opponent could touch the ball in {pressure_s} s"),
                             (W, "an opponent could touch the ball in {pressure_s} s (borderline)")],
    "in_shooting_range": [(H, "the ball was {ball_goal_uu} uu from their goal, in shooting range"),
                          (F, "the ball was {ball_goal_uu} uu from their goal, out of shooting range")],
    "ball_in_own_half": [(H, "the ball was in your half"), (F, "the ball was in their half")],
    "shot_lane_open": [(H, "{shot_open_lines} of 9 lines to goal were open and no defender could reach the shot line first"),
                       (F, "no clean shot: a defender could reach the shot line {defender_early_s} s before the ball", "defender_early"),
                       (F, "no clean shot: the nearest defender could reach the shot line just after the ball ({shot_margin_s} s)"),
                       (F, "no clean shot lane")],
    "teammate_forward_option": [(H, "your teammate was level or ahead and could reach the ball in {mate_t} s"),
                                (F, "your teammate was not placed to receive a pass")],
    "play_uncovered_if_lost": [(H, "if you lost the ball your teammate could not be goal-side in time"),
                               (F, "your teammate could cover if you lost the ball")],
    "big_boost_detour_cheap": [(H, "the big-boost detour cost only {detour_extra_s} s more than returning directly ({direct_s} s)"),
                               (F, "the big-boost detour cost {detour_extra_s} s more than returning directly ({direct_s} s)"),
                               (W, "the big-boost detour cost {detour_extra_s} s more than returning directly (borderline)")],
    "big_pad_available": [(H, "the nearest big pad was up"), (F, "the nearest big pad had been taken recently")],
    "small_pads_on_route": [(H, "{small_pads} available small pads lay on the direct route"),
                            (F, "no available small pads lay on the direct route")],
    "low_boost": [(H, "you had only {boost} boost"), (F, "you had {boost} boost")],
    "threat_now": [(H, "an opponent was first to a ball in or heading into your half"), (F, "there was no immediate threat to your goal")],
    "double_commit_risk": [(H, "you were driving at the ball ({closing} uu/s) while your teammate played it"),
                           (F, "you were not driving at the ball your teammate was playing")],
    "focus_covers_teammate": [(H, "you were already goal-side", "focus_already_goal_side"),
                              (H, "you could be goal-side in {focus_cover_s} s, in time to cover"),
                              (F, "you needed {focus_cover_s} s to get goal-side, too late to cover"),
                              (F, "you could not get goal-side in time to cover"),
                              (W, "whether you could cover in time was borderline ({focus_cover_s} s)")],
    "contact_away_from_second_opponent": [(H, "your contact would send the ball away from their second player")],
    "teammate_will_rotate": [(H, "your teammate intended to rotate behind you")],
    "flip_available": [(H, "you still had a flip available")],
    "aware_of_second_opponent": [(H, "you had seen their second player")],
    "boost_route_keeps_cover": [(H, "the {boost_pad} pad route still reached goal-side in {boost_cover_s} s, in time to cover"),
                                (F, "the {boost_pad} pad route took {boost_cover_s} s to reach goal-side, too slow to cover"),
                                (F, "no available pad route kept you in cover"),
                                (W, "the pad route ({boost_cover_s} s) was borderline for covering")],
    "carrier_committing": [(H, "the nearest opponent was already on the ball", "carrier_at_ball"),
                           (H, "the nearest opponent was driving at the ball ({carrier_closing} uu/s closing)"),
                           (F, "the nearest opponent was moving away from the ball ({carrier_away} uu/s)", "carrier_moving_away"),
                           (F, "the nearest opponent was not driving at the ball (closing at only {carrier_closing} uu/s)"),
                           (W, "it was unclear whether the nearest opponent was going for the ball ({carrier_closing} uu/s closing)")],
    "opponents_far": [(H, "both opponents were at least {carrier_t} s from the ball"),
                      (F, "an opponent could reach the ball in {carrier_t} s"),
                      (W, "an opponent could reach the ball in {carrier_t} s (borderline)")],
}


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 100 else f"{v:.0f}"
    return str(v)


class _Numbers:
    def __init__(self) -> None:
        self.vals: dict[str, dict] = {}
        self.flags: set[str] = set()

    def put(self, key: str, value: Any, ref: str | list[str]) -> None:
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            return
        if isinstance(value, float):
            value = round(value, 2)
        self.vals[key] = {"value": value, "text": _fmt(value), "refs": [ref] if isinstance(ref, str) else ref}

    def fill(self, template: str) -> str | None:
        keys = re.findall(r"{(\w+)}", template)
        if any(k not in self.vals for k in keys):
            return None
        return template.format(**{k: self.vals[k]["text"] for k in keys})


def _numbers(packet: dict, rationale: dict) -> _Numbers:
    s = _State(packet)
    n = _Numbers()
    sc = _scenario(s)
    iv = sc["intervals"]
    for key, slot in (("focus_t", "focus"), ("mate_t", "teammate"), ("carrier_t", sc["carrier"]),
                      ("second_t", sc["second_opponent"])):
        if slot and iv.get(slot) and math.isfinite(iv[slot][0]):
            n.put(key, float(iv[slot][0]), f"E.reach.{slot}")
    if "E.cover.teammate" in s.ev and s.val("E.cover.teammate") is not None:
        if float(s.val("E.cover.teammate")) <= 0.0:
            n.flags.add("teammate_already_goal_side")
        else:
            n.put("cover_s", float(s.val("E.cover.teammate")), "E.cover.teammate")
    if "E.focus.boost" in s.ev and s.val("E.focus.boost") is not None:
        n.put("boost", int(round(s.val("E.focus.boost"))), "E.focus.boost")
    b = s.val("E.ball.position")
    if isinstance(b, list):
        n.put("ball_own_goal_uu", int(round(math.dist((b[0], s.sign * b[1]), (0.0, -GOAL_Y)), -1)), "E.ball.position")
    q = rationale.get("quantities", {})
    for key, qid in (("pressure_s", "Q.pressure_time_s"), ("shot_open_lines", "Q.shot_open_lines"),
                     ("shot_margin_s", "Q.shot_defender_margin_s"), ("ball_goal_uu", "Q.ball_to_opponent_goal_uu"), ("direct_s", "Q.direct_return_s"),
                     ("detour_extra_s", "Q.big_boost_detour_extra_s"), ("small_pads", "Q.small_pads_on_route"),
                     ("big_pad_status", "Q.big_pad_status"), ("focus_cover_s", "Q.focus_cover_s"),
                     ("closing", "Q.focus_closing_speed"), ("boost_cover_s", "Q.boost_then_cover_s"),
                     ("boost_pad", "Q.boost_route_pad"), ("carrier_closing", "Q.carrier_closing_speed")):
        if qid in q and q[qid]["value"] is not None:
            if key == "carrier_closing" and q.get("Q.carrier_at_ball"):
                n.flags.add("carrier_at_ball")
                continue
            if key == "carrier_closing" and q[qid]["value"] < 0:
                n.flags.add("carrier_moving_away")
                n.put("carrier_away", -q[qid]["value"], qid)
                continue
            if key == "shot_margin_s" and q[qid]["value"] < 0:
                n.flags.add("defender_early")
                n.put("defender_early_s", -q[qid]["value"], qid)
                continue
            if key == "focus_cover_s" and q[qid]["value"] <= 0:
                n.flags.add("focus_already_goal_side")
                continue
            n.put(key, q[qid]["value"], qid)
    return n


def _reading(cid: str, status: str, nums: _Numbers) -> str | None:
    for entry in READINGS.get(cid, []):
        when, tpl = entry[0], entry[1]
        if when != status or (len(entry) > 2 and entry[2] not in nums.flags):
            continue
        filled = nums.fill(tpl)
        if filled is not None:
            return filled
    return None


def _fragments(spec_list, cond, nums):
    out = []
    for lit, text in spec_list:
        filled = nums.fill(text)
        if filled is None:
            continue
        if lit is None:
            out.append({"text": filled, "depends_on": None, "status": "applies"})
            continue
        st = _lit(cond, lit) if lit.lstrip("!") in cond else UNKNOWN
        if st == HOLDS:
            out.append({"text": filled, "depends_on": lit, "status": "applies"})
        elif st in UNCERTAIN:
            out.append({"text": filled, "depends_on": lit, "status": f"possible ({st.replace('_', ' ')})"})
    return out


def _premise_reading(lits: list[str], cond: dict, nums: _Numbers) -> list[str]:
    out = []
    for lit in lits:
        cid = lit.lstrip("!")
        if cid not in cond:
            continue
        st = cond[cid]["status"]
        r = _reading(cid, st, nums)
        if r is None:
            base = _reading(cid, HOLDS, nums) or cond[cid]["text"].rstrip(".").lower()
            r = (base if st == HOLDS else f"not the case that {base}" if st == FAILS
                 else f"unknown whether {base}" if st == UNKNOWN else f"unclear whether {base}")
        out.append(r)
    return out


def _family_status(actions: dict, family: str) -> str | None:
    sts = [v["status"] for a, v in actions.items() if ACTIONS.get(a, {}).get("family") == family]
    for st in ("supported", "conditional", "contested", "refuted"):
        if st in sts:
            return st
    return None


# ---------- Stage A ----------

def build_stage_a(situation: dict, rationale: dict, packet: dict, *, finding_id: str,
                  salience: dict | None = None) -> dict[str, Any]:
    cls = situation["situation_class"]
    base = {"schema": SCHEMA, "version": VERSION, "finding_id": finding_id, "experimental": True,
            "expert_validated": False, "stage": "A_predecision", "t0": situation["t0"],
            "situation": {"class": cls, "label": CLASS_LABEL[cls], "why_it_matters": WHY_IT_MATTERS[cls],
                          "selection": salience or {}}}
    if rationale.get("judgment") == "withheld" and not rationale.get("conditions"):
        obs = rationale.get("observations", {})
        nums = _numbers(packet, rationale) if obs and packet.get("status") != "abstain" else _Numbers()
        ctx = [{"condition": k, "status": v["status"], "statement": v["text"], "reading": _premise_reading([k], obs, nums)[0],
                "evidence": v["evidence"], "quantities": [], "claim_id": None, "margin_sensitivity": None} for k, v in obs.items()]
        return {**base, "kind": "observation_only", "decision_context": ctx, "alternatives": [],
                "interpretation": {"kind": "observation_only", "text": " ".join(rationale.get("reasons_for_withholding", []))},
                "assumptions": [], "takeaway": {"kind": "observation_only", "text": None, "basis": []},
                "numbers": nums.vals, "claims": [], "limits": rationale.get("reasons_for_withholding", [])}
    cond, acts = rationale["conditions"], rationale["actions"]
    nums = _numbers(packet, rationale)
    # decision context: certain conditions with readings, then uncertain ones
    ctx = []
    for cid, c in cond.items():
        if c["kind"] == "unobservable":
            continue
        ctx.append({"condition": cid, "status": c["status"], "statement": c["text"],
                    "reading": _premise_reading([cid], cond, nums)[0], "evidence": c["evidence"],
                    "quantities": c.get("quantities", []), "claim_id": c.get("claim"),
                    "margin_sensitivity": c.get("margin_sensitivity")})
    ctx.sort(key=lambda r: (r["status"] in UNCERTAIN, r["condition"]))
    # complementary conditions repeat the same fact; show one
    shown = {r["condition"] for r in ctx}
    ctx = [r for r in ctx if not (r["condition"] == "focus_first" and "carrier_first" in shown)
           and not (r["condition"] == "contest_level" and r["status"] == FAILS and "carrier_first" in shown)]
    # alternatives
    alts = []
    order = {"supported": 0, "conditional": 1, "contested": 2, "refuted": 3}
    def n_sat(v):
        return -sum(r["status"] == "satisfied" for r in v["reasons"])
    for a, v in sorted(acts.items(), key=lambda kv: (order[kv[1]["status"]], n_sat(kv[1]), kv[0])):
        prof = ACTIONS.get(a, {"label": a.replace("_", " "), "family": a, "gains": [], "preserves": [], "sacrifices": [], "risks": []})
        sat = [r for r in v["reasons"] if r["status"] == "satisfied"]
        cnd = [r for r in v["reasons"] if r["status"] == "conditional"]
        ref = [r for r in v["reasons"] if r["status"] == "refuted"]
        why = (sat or cnd or ref)[:1]
        blocking = []
        if v["status"] == "refuted":
            for r in ref[:2]:
                fails = [p["condition"] for p in r["premises"] if p["status"] == FAILS]
                blocking.append({"reason": r["text"], "fails_because": _premise_reading(fails, cond, nums)})
        alts.append({
            "action": a, "label": prof["label"], "family": prof["family"], "status": v["status"],
            "why": [{"reason": r["text"], "premises": _premise_reading([p["condition"] for p in r["premises"]], cond, nums),
                     "uncertain_premises": r["uncertain_premises"]} for r in why],
            "ruled_out_because": blocking,
            "defeaters_present": [d["defeater"] for d in v["defeaters"] if d["status"] == "present"],
            "defeaters_present_text": [_and(_premise_reading(d["conditions"], cond, nums)) for d in v["defeaters"]
                                       if d["status"] == "present"],
            "defeaters_possible": [d["defeater"] for d in v["defeaters"] if d["status"] == "possible"],
            "gains": _fragments(prof["gains"], cond, nums), "preserves": _fragments(prof["preserves"], cond, nums),
            "sacrifices": _fragments(prof["sacrifices"], cond, nums), "risks": _fragments(prof["risks"], cond, nums),
        })
    supported = [x for x in alts if x["status"] == "supported"]
    conditional = [x for x in alts if x["status"] == "conditional"]
    refuted = [x for x in alts if x["status"] == "refuted"]
    fams_ok = {x["family"] for x in supported}
    decisive = rationale.get("decisive_information", [])
    unobs = [{"condition": cid, "text": c["text"]} for cid, c in cond.items() if c["status"] == UNOBS]
    for d in decisive:
        d["question"] = "whether " + (_reading(d["condition"], HOLDS, nums) or d["text"].rstrip(".").lower())
    if rationale.get("judgment") == "withheld":
        kind = "hard_to_judge"
    elif len(fams_ok) >= 2:
        kind = "several_defensible"
    elif supported and decisive and any(any(x in d["if_true"] or x in d["if_false"] for x in [s["action"] for s in supported])
                                        for d in decisive):
        kind = "leaning_with_uncertainty"
    elif supported:
        kind = "clear_read"
    else:
        kind = "hard_to_judge"
    interp = _interpretation(kind, supported, conditional, refuted, decisive)
    take = _takeaway(cls, kind, supported, refuted, conditional, decisive, cond, nums)
    limits = ["Tactical interpretation is rule-based and not expert-validated.",
              "Arrival times are kinematic lower bounds; the 0.30-0.55 s ordering error band is applied."]
    if unobs:
        limits.append("Some premises are unobservable from replay data: " + ", ".join(u["condition"] for u in unobs) + ".")
    return {**base, "kind": kind, "decision_context": ctx, "alternatives": alts, "interpretation": interp,
            "assumptions": {"decisive": [{"condition": d["condition"], "current": d["current"], "text": d["text"],
                                          "question": "whether " + (_reading(d["condition"], HOLDS, nums) or d["text"].rstrip(".").lower()),
                                          "if_true": d["if_true"], "if_false": d["if_false"], "how_to_resolve": d["how_to_resolve"]}
                                         for d in decisive],
                            "unobservable": unobs},
            "takeaway": take, "numbers": nums.vals, "claims": rationale.get("claims", []),
            "quantities": rationale.get("quantities", {}), "limits": limits}


def _names(xs):
    return " / ".join(x["label"].lower() for x in xs)


def _and(xs: list[str]) -> str:
    xs = [x for x in xs if x]
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1] if xs else ""


def _interpretation(kind, supported, conditional, refuted, decisive) -> dict:
    parts = []
    if supported:
        r = supported[0]["why"][0] if supported[0]["why"] else None
        parts.append(f"At decision time the evidence supports {_names(supported[:3])}"
                     + (f", because {_and(r['premises'])}" if r and r["premises"] else "") + ".")
    for x in refuted[:2]:
        if x["ruled_out_because"] and x["ruled_out_because"][0]["fails_because"]:
            parts.append(f"It argues against {x['label'].lower()}: {_and(x['ruled_out_because'][0]['fails_because'])}.")
    if conditional and not supported:
        parts.append(f"{_names(conditional[:3]).capitalize()} could be right, depending on conditions the replay cannot settle.")
    if decisive:
        parts.append("What would change the read: " + "; ".join(f"{d['question']} (currently {d['current'].replace('_', ' ')})"
                                                                 for d in decisive[:2]) + ".")
    return {"kind": kind, "text": " ".join(parts) or "The decision-time evidence does not separate the options."}


def _takeaway(cls, kind, supported, refuted, conditional, decisive, cond, nums) -> dict:
    """A cue to recognise next time, tied to the conditions that decided this situation."""
    if kind == "hard_to_judge":
        cues = [d["question"] for d in decisive[:2]]
        return {"kind": "observation", "text": ("The read here hinges on " + " and ".join(cues)
                                                 + ", which the replay cannot settle. Review the clip with that question in mind."
                                                 if cues else None), "basis": [d["condition"] for d in decisive[:2]]}
    deciding = []
    for x in supported[:1]:
        for w in x["why"][:1]:
            deciding += w["premises"]
    contrast = next((x for x in refuted if x["family"] != (supported[0]["family"] if supported else None)
                     and x["ruled_out_because"]), None)
    if contrast:
        deciding += contrast["ruled_out_because"][0]["fails_because"]
    deciding = list(dict.fromkeys(deciding))[:3]
    if kind == "several_defensible":
        fams = {}
        for x in supported:
            fams.setdefault(x["family"], x)
        pair = list(fams.values())[:2]
        text = (f"More than one choice holds up: {pair[0]['label'].lower()} or {pair[1]['label'].lower()}. "
                f"What makes both reasonable: {_and(deciding)}."
                + (f" Between them, the deciding question is {decisive[0]['question']}." if decisive else ""))
        if contrast:
            risk = next((r["text"] for r in contrast["risks"] if r["status"] == "applies"), None)
            text += f" What was not on: {contrast['label'].lower()}" + (f" (risk: {risk})." if risk else ".")
        return {"kind": "recognition", "text": text, "basis": deciding}
    best = supported[0]
    gain = next((g["text"] for g in best["gains"] if g["status"] == "applies"), None)
    text = f"Read: {_and(deciding) if deciding else 'these conditions'}. In that picture, {best['label'].lower()} is the sound option"
    text += f" ({gain})." if gain else "."
    if contrast:
        risk = next((r["text"] for r in contrast["risks"] if r["status"] == "applies"), None)
        if risk:
            text += f" {contrast['label']} would risk this: {risk}."
    if kind == "leaning_with_uncertainty" and decisive:
        text += f" This depends on {decisive[0]['question']}, which the replay cannot settle."
    return {"kind": "practice" if refuted else "recognition", "text": text, "basis": deciding}


# ---------- Stage B: retrospective, separate ----------

OBS_WINDOW_S = 2.5
OUTCOME_WINDOW_S = 5.0


def _rel_y(team, y):
    return y if team == "blue" else -y


def observe_action(replay: dict, situation: dict) -> dict[str, Any]:
    """Heuristic label of what the focus player did in the next seconds (retrospective)."""
    cls, t0, pid, team = situation["situation_class"], situation["t0"], situation["player_id"], situation["team"]
    frames = replay["frames"]
    ts = [f["t"] for f in frames]
    seg = frames[bisect.bisect_right(ts, t0):bisect.bisect_right(ts, t0 + OBS_WINDOW_S)]
    ev = [e for e in replay.get("events", []) if isinstance(e.get("t"), (int, float)) and t0 < e["t"] <= t0 + OBS_WINDOW_S]
    team_of = {p["id"]: p.get("team") for p in replay.get("players", [])}
    touches = sorted((e["t"], e.get("playerId")) for e in ev if e.get("type") == "touch")
    mine = [t for t, p in touches if p == pid]
    pickups = [e for e in ev if e.get("type") == "boost_pickups" and e.get("playerId") == pid]
    if not seg or any(math.dist((a["ball"]["x"], a["ball"]["y"]), (b["ball"]["x"], b["ball"]["y"])) > 1500
                      for a, b in zip(seg, seg[1:])):
        return {"label": None, "family": None, "basis": {"reason": "reset or missing frames in the window"}}
    rows = [(f["cars"][pid], f["ball"]) for f in seg if pid in f["cars"]]
    if len(rows) < 0.7 * len(seg):
        return {"label": None, "family": None, "basis": {"reason": "car missing for part of the window"}}
    dmin = min(math.dist((c["x"], c["y"]), (b["x"], b["y"])) for c, b in rows)
    goal_side = sum(_rel_y(team, c["y"]) < _rel_y(team, b["y"]) for c, b in rows) / len(rows)
    basis = {"window_s": OBS_WINDOW_S, "touched_at_s": round(mine[0] - t0, 2) if mine else None,
             "min_distance_to_ball_uu": round(dmin), "goal_side_share": round(goal_side, 2),
             "big_pad_pickup": any(e.get("padType") == "big" for e in pickups),
             "small_pad_pickups": sum(e.get("padType") == "small" for e in pickups)}
    lab = None
    if cls == "possession":
        first = next((t for t in mine if t <= t0 + 1.2), None)
        if first is not None:
            k = bisect.bisect_left(ts, first + 0.25)
            after = frames[min(k, len(frames) - 1)]["ball"]
            vy = _rel_y(team, after["velocity"][1])
            by = _rel_y(team, after["y"])
            ax = after["x"] if team == "blue" else -after["x"]
            avx = after["velocity"][0] if team == "blue" else -after["velocity"][0]
            nxt = next(((t, p) for t, p in touches if t > first and p != pid), None)
            x_at_goal = ax + avx * ((GOAL_Y - by) / vy) if vy > 300 else None
            speed = math.hypot(*after["velocity"][:2])
            if vy > 1200 and math.hypot(ax, GOAL_Y - by) < 4500 and x_at_goal is not None and abs(x_at_goal) < 1100:
                lab = "shoot_now"
            elif nxt and team_of.get(nxt[1]) == team and nxt[0] - first <= 2.0:
                lab = "pass_or_center"
            elif speed > 2000:
                lab = "push_forward" if by > 0 else "clear_to_space"
            else:
                lab = "keep_possession"
            basis["first_touch_at_s"] = round(first - t0, 2)
        else:
            near = [math.dist((c["x"], c["y"]), (b["x"], b["y"])) for c, b in rows if seg and c is not None]
            lab = "keep_possession" if near and near[min(len(near) - 1, int(len(near) * 0.5))] < 500 else None
    elif cls == "recovery_and_boost":
        if basis["big_pad_pickup"]:
            lab = "big_boost_detour"
        elif basis["small_pad_pickups"]:
            lab = "small_pad_route"
        elif _rel_y(team, rows[0][0]["y"]) - _rel_y(team, rows[-1][0]["y"]) > 600 or goal_side >= 0.8:
            lab = "return_direct"
    elif cls == "second_man_support":
        if mine:
            lab = "challenge_as_well"
        elif basis["big_pad_pickup"] or basis["small_pad_pickups"] >= 2:
            lab = "boost_while_teammate_plays"
        elif goal_side >= 0.8 and dmin > 1500:
            lab = "support_behind"
        elif dmin <= 1500:
            lab = "aggressive_follow_up"
    elif cls != "aerial_or_wall":
        if mine or dmin < 260:
            lab = "immediate_challenge"
        elif basis["big_pad_pickup"] or basis["small_pad_pickups"] >= 2:
            lab = "rotate_through_small_pads"
        elif goal_side >= 0.8 and dmin >= 500:
            lab = "shadow_delay"
    fam = ACTIONS.get(lab, {}).get("family") if lab else None
    return {"label": lab, "family": fam, "basis": basis,
            "method": "heuristic label from movement, touches and pickups in the next seconds; not an intent reading"}


def outcome(replay: dict, situation: dict) -> dict[str, Any]:
    t0, team = situation["t0"], situation["team"]
    team_of = {p["id"]: p.get("team") for p in replay.get("players", [])}
    ev = sorted((e for e in replay.get("events", []) if isinstance(e.get("t"), (int, float))
                 and t0 < e["t"] <= t0 + OUTCOME_WINDOW_S and e.get("type") in ("touch", "goal_context")),
                key=lambda e: e["t"])
    seq = []
    goal = None
    for e in ev:
        if e["type"] == "goal_context":
            goal = {"t_after_s": round(e["t"] - t0, 2), "scored_by": "own team" if e.get("scoringTeam") == team else "opponents"}
            break
        side = "focus" if e.get("playerId") == situation["player_id"] else (
            "teammate" if team_of.get(e.get("playerId")) == team else "opponent")
        if not seq or seq[-1]["by"] != side:
            seq.append({"by": side, "t_after_s": round(e["t"] - t0, 2)})
    return {"window_s": OUTCOME_WINDOW_S, "touch_sequence": seq[:6], "goal": goal}


def build_stage_b(stage_a: dict, replay: dict, situation: dict) -> dict[str, Any]:
    obs = observe_action(replay, situation)
    alts = {x["action"]: x for x in stage_a.get("alternatives", [])}
    out = {"stage": "B_retrospective", "observed_action": obs, "outcome": outcome(replay, situation),
           "outcome_independence": "The assessment below uses only the decision-time ledger and the observed action; "
                                   "the outcome is shown for context and does not change it."}
    if stage_a["kind"] == "observation_only" or obs["label"] is None:
        out["assessment"] = {"verdict": "not_assessed",
                             "text": "No assessment: " + ("the situation is observation-only." if stage_a["kind"] == "observation_only"
                                                           else "the action could not be labelled from the replay.")}
        return out
    fam_status = _family_status({a: {"status": x["status"]} for a, x in alts.items()}, obs["family"])
    supported = [x for x in alts.values() if x["status"] == "supported"]
    x = alts.get(obs["label"])
    label = ACTIONS[obs["label"]]["label"].lower()
    if fam_status == "supported":
        verdict, text = "sound", f"You chose to {label}, which the decision-time evidence supports."
        if x and x["why"]:
            text += f" Reason: {x['why'][0]['reason'].rstrip('.').lower()}."
        if stage_a["kind"] == "several_defensible":
            text += " Other choices were also defensible here."
    elif fam_status == "conditional":
        unc = sorted({u for a in alts.values() if a["family"] == obs["family"] for w in a["why"] for u in w["uncertain_premises"]})
        verdict = "defensible_if"
        text = f"You chose to {label}. It is defensible if " + (", ".join(u.lstrip('!').replace('_', ' ') for u in unc) or "its premises hold") + \
               ", which the replay cannot confirm."
    elif fam_status == "contested":
        verdict = "risky"
        d = list(dict.fromkeys(dd for a in alts.values() if a["family"] == obs["family"] for dd in a["defeaters_present_text"]))
        text = f"You chose to {label}. A reason for it held, but so did a known risk: {'; '.join(d[:2])}."
    elif fam_status == "refuted" and supported and stage_a["kind"] == "leaning_with_uncertainty":
        verdict = "debatable"
        text = (f"You chose to {label}. The decision-time evidence leaned toward {supported[0]['label'].lower()}, "
                f"but that lean depends on something the replay cannot settle.")
    elif fam_status == "refuted" and supported and stage_a["kind"] == "clear_read":
        verdict = "questionable"
        why = x["ruled_out_because"][0]["fails_because"] if x and x["ruled_out_because"] else []
        text = (f"You chose to {label}, which the decision-time evidence argues against"
                + (f" ({'; '.join(why)})" if why else "") + f"; {supported[0]['label'].lower()} was supported.")
    else:
        verdict, text = "unclear", f"You chose to {label}; the evidence does not clearly support or rule it out."
    if out["outcome"]["goal"] and verdict == "sound" and out["outcome"]["goal"]["scored_by"] == "opponents":
        text += " The goal that followed does not make the choice wrong."
    if out["outcome"]["goal"] and verdict == "questionable" and out["outcome"]["goal"]["scored_by"] == "own team":
        text += " It worked out this time, but the read at decision time still argued against it."
    out["assessment"] = {"verdict": verdict, "text": text, "family_status_at_t0": fam_status}
    return out


def check_finding_numbers(finding: dict) -> list[str]:
    """Every number in the finding's generated text must come from its numbers table (or fixed wording)."""
    allowed = {v["text"] for v in finding.get("numbers", {}).values()} | {"0.30", "0.55", "9"}
    texts = [finding.get("interpretation", {}).get("text") or "", finding.get("takeaway", {}).get("text") or ""]
    for c in finding.get("decision_context", []):
        texts.append(c.get("reading") or "")
    for a in finding.get("alternatives", []):
        for k in ("gains", "preserves", "sacrifices", "risks"):
            texts += [f["text"] for f in a[k]]
    bad = []
    for t in texts:
        for tok in NUM_RE.findall(re.sub(r"\b\d+v\d+\b|50/50", "", t)):
            if tok not in allowed:
                bad.append(f"{tok} in: {t[:80]}")
    return bad


__all__ = ["build_stage_a", "build_stage_b", "observe_action", "outcome", "check_finding_numbers", "ACTIONS", "SCHEMA"]

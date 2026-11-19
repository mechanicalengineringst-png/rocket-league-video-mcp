"""CoachingReportV2: habits first, turning points second, single decisions third (Round 13, experimental).

Why the order changed (docs/round13/ROUND13_REPORT.md):
- Round 13 falsification found that single-moment "questionable" verdicts carry no measurable consequence
  in the cohort (action-value study, value-model regret) and rest on proxies that fail in places (intent at
  close range, cover estimates, reach lower bound). So V2 never labels one decision a mistake.
- Habits are rates over many comparable situations, checked against a reference distribution.
- Turning points show the sequences where the team's expected control changed most (both directions),
  with how much each player's movement moved it. Selection is retrospective and says so; the decision
  inside a turning point is still read from decision-time evidence only.
- Single decisions keep the Round 12 Stage A ledger, with the Round 13 adjustments (``ledger="r13"``);
  the retrospective part says whether the action matched the rule read, never that it was wrong.
- Aerial/wall moments get commitment context (who was back, recovery debt) without judging the mechanics.

Nothing here calls a language model, and nothing reads the future for Stage A.
"""
from __future__ import annotations

import bisect
from typing import Any

from . import field_control as fc
from .coach_report import _validate, analyze_moment
from .coaching_findings import build_stage_a, build_stage_b
from .control_timeline import turning_points
from .habit_profile import build_profile
from .moment_ranking import rank
from .situation_rationale import SituationRationaleError
from .situations import discover_situations
from .state_features import reach_times
from .value_model import FutureControlModel

SCHEMA = "CoachingReportV2"
VERSION = "coach-report-v2/0.1"
LINK_LOOKBACK_S = 3.0              # a decision up to 3 s before the turning point window can be linked
VERDICT_V2 = {"sound": "consistent_with_rule_read", "defensible_if": "defensible_if", "unclear": "unclear",
              "not_assessed": "not_assessed", "risky": "against_rule_read_unconfirmed",
              "questionable": "against_rule_read_unconfirmed", "debatable": "against_rule_read_unconfirmed"}
EVIDENCE_STATUS = [
    {"component": "kinematic reach (who can touch first)", "status": "partly validated",
     "detail": "Lower bound broken in 8-24% of real ground touches at 0.5-2 s lead; ordering band kept."},
    {"component": "future-control value model", "status": "validated on held-out matches (unknown rank)",
     "detail": "Next touch AUC 0.82, danger-5s AUC 0.89; used for ranking and attribution, never shown as a percentage."},
    {"component": "pre-contact counterfactual simulator", "status": "failed validation, not used for judgments",
     "detail": "Worse than constant velocity at the 0.5 s horizon; value ordering preferred challenging almost always."},
    {"component": "opponent intent from closing speed", "status": "downgraded",
     "detail": "At close range a slow-closing opponent still took the next touch about half the time."},
    {"component": "single-decision 'questionable' verdicts", "status": "not supported by cohort data",
     "detail": "Commit vs hold showed no adjusted danger difference; goals-against difference was near the placebo level."},
    {"component": "habit rates", "status": "low within-match reliability",
     "detail": "Split-half Spearman 0.0-0.45; most habits need 3-8+ matches before a rate describes a tendency."},
    {"component": "teammate cover estimate", "status": "validated as a predictor",
     "detail": "When it said the teammate could cover, the teammate was goal-side in time 94% of the time; 19% when it said not."},
    {"component": "field control", "status": "explanatory only",
     "detail": "Adds almost nothing to prediction beyond positions; shown as physical area shares."},
]


def _frame(replay, t):
    ts = [f["t"] for f in replay["frames"]]
    return replay["frames"][bisect.bisect_right(ts, t + 1e-6) - 1]


def _context(replay: dict, focus: str, t0: float) -> dict[str, Any] | None:
    """Commitment context at t0: who was back, recovery debt, own-goal-zone control (physical facts only)."""
    team_of = {p["id"]: p.get("team") for p in replay.get("players", [])}
    team = team_of[focus]
    fr = _frame(replay, t0)
    summ = fc.summarise(fr, team_of, team)
    if summ is None:
        return None
    mate = next((p for p in team_of if team_of[p] == team and p != focus), None)
    debt = summ["recovery_debt"]
    return {"t0": t0, "teammate_recovery_debt_s": debt.get(mate), "your_recovery_debt_s": debt.get(focus),
            "own_goal_zone_control": summ["regions"]["own_goal_zone"]["own"],
            "own_half_control": summ["regions"]["own_half"]["own"],
            "opponent_recovery_debt_s": summ["team_debt"]["opponent"],
            "note": "Physical reachability at the decision moment; the aerial or wall mechanics are not modelled."}


UPSTREAM_LOOKBACK_S = 8.0          # earlier decisions listed (not blamed) when the linked moment was already constrained
COVER_WINDOW_S = 1.0               # same window as the R10-R12 cover check, which survived Round 13 falsification


def upstream_check(replay: dict, focus: str, link_t0: float, items: list[dict]) -> dict[str, Any]:
    """Was the linked decision already constrained by where the player was? (Round 14.5)

    A turning point is linked to the nearest earlier decision in TIME. Time is not cause: a late, desperate
    decision can be the nearest one while the situation was set by an earlier choice (e.g. a long boost
    detour), and an earlier safe choice that ended in position should not be implicated in a later mistake.

    Uses only the frame at ``link_t0`` (the same information the decision read uses): if the player was not
    goal-side and needed longer to get there than the nearest opponent's earliest touch plus the cover window,
    the linked decision may already have been too late. Then the earlier decisions in the lookback are LISTED
    as candidates, without choosing among them; the replay cannot establish which choice caused it.
    """
    team_of = {p["id"]: p.get("team") for p in replay.get("players", [])}
    fr = _frame(replay, link_t0)
    out: dict[str, Any] = {"link_basis": "nearest earlier decision in time; time order is not evidence of cause"}
    if not fr or focus not in fr.get("cars", {}) or not fr["cars"][focus] or not fr.get("ball"):
        return {**out, "upstream": {"status": "unknown", "reason": "no decision-time frame"}}
    debt = fc.recovery_debt({"ball": fr["ball"], "cars": {focus: fr["cars"][focus]}}, {focus: team_of[focus]}).get(focus)
    reach = reach_times(fr)
    opp = [reach[p] for p in reach if team_of.get(p) not in (None, team_of[focus]) and reach[p] is not None]
    if debt is None or not opp:
        return {**out, "upstream": {"status": "unknown", "reason": "recovery or opponent reach unknown at that moment"}}
    opp_t = min(opp)
    if debt <= opp_t + COVER_WINDOW_S:
        return {**out, "upstream": {
            "status": "in_position", "recovery_debt_s": debt, "nearest_opponent_reach_s": round(opp_t, 2),
            "note": "You could get goal-side in time at this decision, so earlier choices are not implicated."}}
    earlier = [{"t0": it["situation"]["t0"], "class": it["situation"]["situation_class"]}
               for it in items if link_t0 - UPSTREAM_LOOKBACK_S <= it["situation"]["t0"] < link_t0 - 0.5]
    return {**out, "upstream": {
        "status": "already_constrained", "recovery_debt_s": debt, "nearest_opponent_reach_s": round(opp_t, 2),
        "earlier_decisions": earlier,
        "note": (f"At this decision you needed {debt} s to get goal-side while an opponent could reach the ball in "
                 f"{round(opp_t, 2)} s, so the outcome may already have been set. "
                 + ("Earlier decisions in the previous 8 s are listed for review; the replay cannot establish which "
                    "of them, if any, caused it." if earlier else
                    "No earlier decision of yours was recorded in the previous 8 s; the cause may be outside your choices."))}}


def build_coaching_report_v2(replays: list[dict] | dict, focus_ids: list[str] | str, *, max_findings: int = 6,
                             max_turning_points: int = 4) -> dict[str, Any]:
    if isinstance(replays, dict):
        replays, focus_ids = [replays], [focus_ids]
    if not replays or len(replays) != len(focus_ids):
        raise ValueError("Give one focus id per replay.")
    for r, f in zip(replays, focus_ids):
        if f not in {p["id"] for p in r.get("players", [])}:
            raise ValueError("Unknown focus player.")
    model = FutureControlModel.load()
    profile = build_profile(replays, focus_ids)
    matches = []
    for mi, (replay, focus) in enumerate(zip(replays, focus_ids)):
        team = {p["id"]: p.get("team") for p in replay["players"]}[focus]
        items = []
        for s in discover_situations(replay, focus):
            try:
                it = analyze_moment(replay, focus, s.to_dict(), ledger="r13")
            except (SituationRationaleError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError):
                continue
            if it:
                items.append(it)
        chosen = rank(items, max_findings=max_findings)
        findings = []
        for k, it in enumerate(chosen, 1):
            f = build_stage_a(it["situation"], it["rationale"], it["packet"], finding_id=f"M{mi + 1}F{k}", salience=it["salience"])
            _validate(f, it["packet"])
            f["ledger_adjustments"] = it["rationale"].get("ledger_adjustments", [])
            b = build_stage_b(f, replay, it["situation"])
            v = b.get("assessment", {}).get("verdict")
            b["assessment"]["verdict_v2"] = VERDICT_V2.get(v, v)
            if VERDICT_V2.get(v) == "against_rule_read_unconfirmed":
                b["assessment"]["text_v2"] = ("Your choice went against the decision-time rule read. Round 13 found no "
                                              "measurable cost for this kind of disagreement in the reference cohort, so "
                                              "treat it as a question to review, not a mistake.")
            f["retrospective"] = b
            if it["situation"]["situation_class"] == "aerial_or_wall":
                f["commitment_context"] = _context(replay, focus, it["situation"]["t0"])
            findings.append(f)
        # turning points: retrospective selection, focus-player attribution, linked decision-time reading
        tps = []
        if model is not None:
            tp = turning_points(replay, team, k=12, model=model)
            for p in tp.get("points", []):
                mine = p.get("player_contribution", {}).get(focus)
                if mine is None:
                    continue
                total = sum(abs(v) for v in p["player_contribution"].values()) or 1.0
                share = abs(mine) / total
                cut = min([x["t"] - 0.2 for x in p["touches"]] + [p["t_end"]])   # strictly before the first touch
                linked = [it for it in items if p["t_start"] - LINK_LOOKBACK_S <= it["situation"]["t0"] <= cut]
                link = None
                if linked:
                    it = linked[-1]                    # the last decision before the first touch of the window
                    fa = build_stage_a(it["situation"], it["rationale"], it["packet"], finding_id="tp")
                    link = {"t0": it["situation"]["t0"], "class": it["situation"]["situation_class"],
                            "interpretation": fa["interpretation"]["text"], "kind": fa["kind"],
                            "takeaway": fa["takeaway"]["text"]}
                    if fa["kind"] == "observation_only":
                        link["commitment_context"] = _context(replay, focus, it["situation"]["t0"])
                    link.update(upstream_check(replay, focus, it["situation"]["t0"], items))
                tps.append({"t_start": p["t_start"], "t_end": p["t_end"], "direction": p["direction"],
                            "team_control_change": p["change"], "your_movement_effect": mine,
                            "your_share_of_attributed_change": round(share, 2),
                            "your_movement": "raised" if mine > 0 else "lowered",
                            "your_movement_reading": p.get("player_heads", {}).get(focus),
                            "causal_status": "association in a model, not evidence that your choice caused the change",
                            "touches": [{"t": x["t"], "by": "you" if x["player"] == focus else
                                         ("teammate" if x["own_team"] else "opponent")} for x in p["touches"]],
                            "decision_time_reading": link})
            tps.sort(key=lambda x: -abs(x["your_movement_effect"]))
            tps = sorted(tps[:max_turning_points], key=lambda x: x["t_start"])
        matches.append({"match_index": mi, "team": team, "situations_analysed": len(items),
                        "decision_findings": findings, "turning_points": tps})
    return {
        "schema": SCHEMA, "version": VERSION, "experimental": True, "expert_validated": False,
        "habit_profile": profile, "matches": matches, "evidence_status": EVIDENCE_STATUS,
        "method": {"model_called": False, "ledger": "r13",
                   "turning_point_selection": "retrospective: largest changes of a learned control score; your movement's "
                                              "share is a leave-one-player-out attribution of that score, not blame",
                   "stage_separation": "decision readings use frames and events at or before t0 only"},
        "limits": ["Reference cohort: 15 public 2v2 matches of unknown rank; nothing is expert-validated.",
                   "Habit percentiles describe how unusual a rate is against that cohort, not whether it is good.",
                   "Aerial, wall and ceiling mechanics are not modelled; only their positional context is shown."],
    }

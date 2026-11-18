"""Defensive decision candidates, retrospective choice labels and the study manifest (Round 5, checkpoint 3).

Two parts with different information rules:

1. ``find_defender_candidates`` decides **eligibility from the t0 frame only**
   (plus earlier candidates for debouncing). A moment qualifies because a
   defender faced an opponent about to play the ball and could have contested
   it, not because anything happened later. Shadowing, challenging and doing
   something else are all possible outcomes of the same rule, so the 40-clip
   commitment study can sample all three without hand-picking.

2. ``classify_choice`` reads the ``CHOICE_WINDOW_S`` after t0 and labels what
   the defender did. That label is an ``observed_action``: retrospective, shown
   as the action under review, never t0 evidence or intent.

``build_commitment_manifest`` turns candidates into rows that match PR #16's
``validate_manifest`` contract, plus a private provenance sidecar.
"""
from __future__ import annotations

import bisect
import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

from .reachability import car_state, estimate_reach
from .strategic_state import StrategicState, build_state

RULE_VERSION = "defender-candidate/0.1"
CHOICE_WINDOW_S = 1.5
SCAN_STEP_S = 0.1
DEBOUNCE_S = 3.0
GOAL_Y = 5120.0

# Eligibility, all evaluated at t0
CARRIER_MAX_S = 0.5          # an opponent can touch the ball within this time
CONTEST_SLACK_S = 1.0        # the defender's own earliest touch is at most this much later
BALL_MAX_Y_REL = 1500.0      # ball in the defender's half or midfield (team frame)
GOAL_SIDE_MARGIN = 200.0


def _rel_y(team: str, y: float) -> float:
    return y if team == "blue" else -y


@dataclass
class Candidate:
    t0: float
    player_id: str
    team: str
    state: dict[str, Any]
    eligibility: dict[str, Any]
    frames_used_through_s: float
    rule: str = RULE_VERSION


def eligible(st: StrategicState, frame: dict) -> tuple[bool, dict[str, Any]]:
    """Apply the t0 rule. Returns (eligible, the values it was decided on)."""
    ball = frame["ball"]
    team, focus = st.team, st.focus
    car = frame["cars"].get(focus)
    c, _ = car_state(car)
    why: dict[str, Any] = {}
    if c is None or c.mode != "ground" or len(frame["cars"]) < 4:
        return False, {"reason": "focus not on ground or a car missing"}
    if ball["x"] == 0 and ball["y"] == 0 and not any(ball.get("velocity") or [0]):
        return False, {"reason": "kickoff setup"}
    reach = st.reach
    opps = [p for p, tm in st.team_of.items() if tm not in (None, team)]
    opp_t = [reach[p]["t_min"] for p in opps if reach[p]["status"] == "ok"]
    mate = next((p for p, tm in st.team_of.items() if tm == team and p != focus), None)
    focus_t = reach[focus]["t_min"] if reach[focus]["status"] == "ok" else None
    mate_t = (reach[mate]["t_min"] if mate and reach[mate]["status"] == "ok" else
              math.inf if mate and reach[mate]["status"] == "out_of_horizon" else None)
    why.update(carrier_t=min(opp_t) if opp_t else None, focus_t=focus_t, mate_t=mate_t,
               ball_y_rel=round(_rel_y(team, ball["y"])), focus_y_rel=round(_rel_y(team, c.y)))
    ok = (
        bool(opp_t) and min(opp_t) <= CARRIER_MAX_S
        and focus_t is not None and focus_t <= min(opp_t) + CONTEST_SLACK_S
        and mate_t is not None and focus_t <= mate_t
        and why["ball_y_rel"] <= BALL_MAX_Y_REL
        and why["focus_y_rel"] < why["ball_y_rel"] - GOAL_SIDE_MARGIN
    )
    return ok, why


def _prefilter(fr: dict, pid: str, team: str | None, payload: dict) -> bool:
    """Necessary conditions only (cheap); the full rule in ``eligible`` decides."""
    car, ball = fr["cars"].get(pid), fr["ball"]
    if not car or team not in ("blue", "orange") or len(fr["cars"]) < 4:
        return False
    by, cy = _rel_y(team, ball["y"]), _rel_y(team, car["y"])
    if by > BALL_MAX_Y_REL or cy >= by - GOAL_SIDE_MARGIN:
        return False
    teams = {q["id"]: q.get("team") for q in payload.get("players", [])}
    # an opponent touching within CARRIER_MAX_S must be within contact + top speed * time
    reach_uu = 240.0 + 2300.0 * CARRIER_MAX_S + 200.0
    return any(math.dist((c["x"], c["y"], c["z"]), (ball["x"], ball["y"], ball["z"])) <= reach_uu
               for q, c in fr["cars"].items() if teams.get(q) not in (None, team))


def find_defender_candidates(payload: dict[str, Any], start: float | None = None, end: float | None = None) -> list[Candidate]:
    """Scan for eligible moments. Each decision reads only the frame at t0."""
    frames = payload.get("frames", [])
    if not frames:
        return []
    times = [f["t"] for f in frames]
    t = times[0] if start is None else start
    end = times[-1] if end is None else end
    last: dict[str, float] = {}
    out: list[Candidate] = []
    while t <= end:
        t = round(t, 3)     # the recorded t0 must be the exact time the frame lookup used
        fr = frames[bisect.bisect_right(times, t) - 1]
        if t - fr["t"] <= 0.15 and fr.get("ball") and fr["ball"].get("velocity"):
            cache: dict = {}
            for p in payload.get("players", []):
                pid = p["id"]
                if t - last.get(pid, -1e9) < DEBOUNCE_S or not _prefilter(fr, pid, p.get("team"), payload):
                    continue
                team = p.get("team")
                opps = [q["id"] for q in payload["players"] if q.get("team") not in (None, team)]
                for q in opps:
                    if q not in cache:
                        cache[q] = estimate_reach(fr["cars"].get(q), fr["ball"])
                if not any(cache[q].status == "ok" and cache[q].t_min <= CARRIER_MAX_S for q in opps):
                    continue
                st = build_state(payload, t, pid, cache)
                if st is None:
                    continue
                ok, why = eligible(st, fr)
                if ok:
                    last[pid] = t
                    out.append(Candidate(t, pid, st.team, st.to_dict(), why, fr["t"]))
        t = round(t + SCAN_STEP_S, 6)
    return out


# ---------- retrospective choice ----------

@dataclass
class ChoiceLabel:
    choice: str                   # challenge | shadow | retreat | boost | unclear
    finalized_through_s: float
    basis: dict[str, Any] = field(default_factory=dict)
    kind: str = "observed_action"
    warning: str = "Retrospective label of what happened next. Not known at t0 and not the player's intent."


def classify_choice(payload: dict[str, Any], t0: float, pid: str, window: float = CHOICE_WINDOW_S) -> ChoiceLabel:
    frames = payload.get("frames", [])
    team = {p["id"]: p.get("team") for p in payload.get("players", [])}.get(pid)
    seg = [f for f in frames if t0 < f["t"] <= t0 + window]
    end = t0 + window
    if not seg or team is None:
        return ChoiceLabel("unclear", end, {"reason": "no frames after t0"})
    touches = [e["t"] for e in payload.get("events", []) if e.get("type") == "touch" and e.get("playerId") == pid
               and t0 < e["t"] <= end]
    prev = None
    for f in seg:
        b = f["ball"]
        if prev and math.hypot(b["x"] - prev["x"], b["y"] - prev["y"]) > 1500:
            return ChoiceLabel("unclear", end, {"reason": "reset or goal inside the window"})
        prev = b
    if touches:
        return ChoiceLabel("challenge", end, {"touched_at_s": round(touches[0] - t0, 3)})
    rows = []
    for f in seg:
        c = f["cars"].get(pid)
        if not c:
            continue
        b = f["ball"]
        rows.append((_rel_y(team, c["y"]), _rel_y(team, b["y"]), math.dist((c["x"], c["y"]), (b["x"], b["y"])),
                     c.get("boost")))
    if len(rows) < 0.7 * len(seg):
        return ChoiceLabel("unclear", end, {"reason": "car missing for part of the window"})
    min_d = min(r[2] for r in rows)
    goal_side = sum(r[0] < r[1] for r in rows) / len(rows)
    moved_back = rows[0][0] - rows[-1][0]
    boosts = [r[3] for r in rows if r[3] is not None]
    gained = (max(boosts) - boosts[0]) if boosts else None
    basis = {"min_distance_uu": round(min_d), "goal_side_share": round(goal_side, 2),
             "moved_toward_own_goal_uu": round(moved_back), "boost_gained": gained}
    if min_d < 260:
        return ChoiceLabel("challenge", end, basis | {"reason": "reached the ball without a recorded touch"})
    if gained is not None and gained >= 20 and min_d > 800:
        return ChoiceLabel("boost", end, basis)
    if goal_side >= 0.8 and 500 <= min_d and rows[-1][2] <= 2500:
        return ChoiceLabel("shadow", end, basis)
    if goal_side >= 0.8 and moved_back > 800 and rows[-1][2] > 2500:
        return ChoiceLabel("retreat", end, basis)
    return ChoiceLabel("unclear", end, basis)


# ---------- manifest for the blind commitment study (PR #16 contract) ----------

STUDY_CHOICE = {"challenge": "challenge", "shadow": "shadow"}   # everything else -> "unclear"


def _digest(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def build_commitment_manifest(replay_group: str, payload: dict[str, Any], candidates: list[Candidate],
                              goal_times: list[float] | None = None) -> tuple[list[dict], list[dict]]:
    """Rows for ``evaluation.commitment_review.validate_manifest`` and a private provenance sidecar.

    Clip lead-in before t0 is jittered deterministically (2.5-4.5 s) so reviewers
    cannot learn where t0 sits. Clips end 1 s after the choice window, and at
    least 0.5 s before any goal, so outcomes are not shown.
    """
    goal_times = sorted(goal_times or [])
    rows, side = [], []
    for c in candidates:
        label = classify_choice(payload, c.t0, c.player_id)
        h = _digest(replay_group, c.player_id, c.t0)
        case_id = f"dc-{h[:12]}"
        lead = 2.5 + (int(h[12:20], 16) % 2000) / 1000.0
        start = max(0.0, c.t0 - lead)
        end = c.t0 + CHOICE_WINDOW_S + 1.0
        nxt = next((g for g in goal_times if g > c.t0), None)
        if nxt is not None:
            end = min(end, nxt - 0.5)
        if end <= c.t0 + 0.5:
            continue                       # a goal follows too soon to show the choice without the outcome
        rows.append({
            "case_id": case_id, "replay_group": replay_group,
            "detector_choice": STUDY_CHOICE.get(label.choice, "unclear"),
            "source_t0_s": round(c.t0, 3), "clip_start_s": round(start, 3), "clip_end_s": round(end, 3),
            "clip_file": f"{case_id}.mp4", "focus_hint": f"Follow the marked {c.team} car",
        })
        side.append({
            "case_id": case_id, "player_id": c.player_id, "eligibility_rule": c.rule,
            "eligibility_values": c.eligibility, "eligibility_frames_used_through_s": c.frames_used_through_s,
            "choice_label": label.choice, "choice_basis": label.basis,
            "choice_finalized_through_s": round(label.finalized_through_s, 3),
            "clip_lead_in_s": round(c.t0 - start, 3), "clip_end_rule": "t0 + 2.5 s, or 0.5 s before the next goal",
        })
    return rows, side

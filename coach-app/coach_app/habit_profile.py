"""Habit profile: what a player tends to do, measured across whole matches (Round 13, experimental).

The owner's leading hypothesis is that confident coaching happens at the level of habits across many
situations, with single moments as examples. A single-moment verdict is fragile (Round 12/13 falsification);
a habit is a rate over dozens of comparable situations and can be checked against a reference.

Every metric is descriptive and decision-time based (states at sampled instants, or the player's observed
action in a classified situation). Nothing uses whether a goal followed. Each metric reports:
- the player's value and the number of instances behind it,
- where it sits in a reference distribution (public cohort, unknown rank: a reference, not a norm),
- up to three example times to review.
"""
from __future__ import annotations

import bisect
import json
import math
from pathlib import Path
from typing import Any

from . import field_control as fc
from .coaching_findings import observe_action
from .situations import discover_situations

VERSION = "habit-profile/0.1"
STEP_S = 0.5
GOAL_Y = 5120.0
REFERENCE_PATH = Path(__file__).resolve().parent / "models" / "habit_reference_v0.json"

METRICS = {
    "last_back_share": "Share of live play in which you were your team's deepest player.",
    "last_back_low_boost_share": "When you were last back, share of the time you had under 20 boost.",
    "both_ball_side_share": "Share of live play in which neither you nor your teammate was goal-side of the ball.",
    "both_near_ball_share": "Share of live play in which you and your teammate were both within 1500 uu of the ball.",
    "behind_play_share": "Share of live play in which you needed more than 2 s to get goal-side (recovery debt).",
    "first_defender_commit_rate": "In first-defender situations, how often you went for the ball.",
    "first_defender_commit_rate_uncovered": "... when your teammate was not goal-side at the decision moment.",
    "second_man_double_commit_rate": "As second man, how often you played the ball before or with your teammate.",
    "recovery_big_boost_rate": "When recovering, how often you took a big-boost detour.",
    "aerial_commit_teammate_not_back_rate": "When you went for an aerial or wall play, how often your teammate was not goal-side.",
}


def _dead(events):
    kicks = sorted(e["t"] for e in events if e.get("type") == "kickoff")
    goals = sorted(e["t"] for e in events if e.get("type") == "goal_context")
    out = [(k - 4.0, k + 3.0) for k in kicks]
    for g in goals:
        out.append((g - 0.5, next((k for k in kicks if k > g), g + 15.0) + 3.0))
    return out


def _goal_side(c, ball, team):
    return (c["y"] < ball["y"] - 200) if team == "blue" else (c["y"] > ball["y"] + 200)


def measure(replay: dict[str, Any], focus: str) -> dict[str, Any]:
    """Raw counts and examples for one player in one replay."""
    team_of = {p["id"]: p.get("team") for p in replay.get("players", [])}
    team = team_of.get(focus)
    if team not in ("blue", "orange"):
        raise ValueError("Unknown focus player.")
    mate = next((p for p in team_of if team_of[p] == team and p != focus), None)
    frames = replay.get("frames", [])
    ts = [f["t"] for f in frames]
    dead = _dead(replay.get("events", []))
    s = 1 if team == "blue" else -1
    c: dict[str, list] = {k: [0, 0, []] for k in ("last_back", "last_back_low_boost", "both_ball_side", "both_near_ball", "behind_play")}
    t = ts[0] + 3.0 if ts else 0.0
    while ts and t <= ts[-1]:
        fr = frames[bisect.bisect_right(ts, t) - 1]
        t += STEP_S
        if fr["t"] < t - STEP_S - 0.1 or any(a <= fr["t"] <= b for a, b in dead):
            continue
        me, tm, ball = fr["cars"].get(focus), fr["cars"].get(mate), fr.get("ball")
        if not me or not tm or not ball:
            continue
        last = s * me["y"] < s * tm["y"]
        _tick(c["last_back"], last, fr["t"])
        if last:
            _tick(c["last_back_low_boost"], (me.get("boost") or 0) < 20, fr["t"])
        _tick(c["both_ball_side"], not _goal_side(me, ball, team) and not _goal_side(tm, ball, team), fr["t"])
        _tick(c["both_near_ball"], math.dist((me["x"], me["y"]), (ball["x"], ball["y"])) < 1500 and
              math.dist((tm["x"], tm["y"]), (ball["x"], ball["y"])) < 1500, fr["t"])
        debt = fc.recovery_debt({"ball": ball, "cars": {focus: me}}, {focus: team}).get(focus)
        if debt is not None:
            _tick(c["behind_play"], debt > 2.0, fr["t"])
    out = {"time": {k: {"hits": v[0], "n": v[1], "examples": v[2][:3]} for k, v in c.items()}}
    sit = {k: [0, 0, []] for k in ("fd_commit", "fd_commit_uncovered", "sm_double", "rec_big", "aerial_mate_not_back")}
    for sd in (x.to_dict() for x in discover_situations(replay, focus)):
        cls, t0 = sd["situation_class"], sd["t0"]
        obs = observe_action(replay, sd)
        fr = frames[bisect.bisect_right(ts, t0) - 1]
        tm, ball = fr["cars"].get(mate), fr.get("ball")
        if cls == "first_defender" and obs["family"] in ("touch", "hold"):
            commit = obs["family"] == "touch"
            _tick(sit["fd_commit"], commit, t0)
            if tm and ball and not _goal_side(tm, ball, team):
                _tick(sit["fd_commit_uncovered"], commit, t0)
        elif cls == "second_man_support" and obs["label"]:
            _tick(sit["sm_double"], obs["label"] == "challenge_as_well", t0)
        elif cls == "recovery_and_boost" and obs["label"]:
            _tick(sit["rec_big"], obs["label"] == "big_boost_detour", t0)
        elif cls == "aerial_or_wall":
            touched = any(e.get("type") == "touch" and e.get("playerId") == focus and t0 < e["t"] <= t0 + 2.5
                          for e in replay.get("events", []))
            if touched and tm and ball:
                _tick(sit["aerial_mate_not_back"], not _goal_side(tm, ball, team), t0)
    out["situations"] = {k: {"hits": v[0], "n": v[1], "examples": v[2][:3]} for k, v in sit.items()}
    return out


def _tick(acc, hit, t):
    acc[1] += 1
    if hit:
        acc[0] += 1
        if not acc[2] or t - acc[2][-1] > 8.0:
            acc[2].append(round(t, 1))


KEYMAP = {"last_back_share": ("time", "last_back"), "last_back_low_boost_share": ("time", "last_back_low_boost"),
          "both_ball_side_share": ("time", "both_ball_side"), "both_near_ball_share": ("time", "both_near_ball"),
          "behind_play_share": ("time", "behind_play"), "first_defender_commit_rate": ("situations", "fd_commit"),
          "first_defender_commit_rate_uncovered": ("situations", "fd_commit_uncovered"),
          "second_man_double_commit_rate": ("situations", "sm_double"), "recovery_big_boost_rate": ("situations", "rec_big"),
          "aerial_commit_teammate_not_back_rate": ("situations", "aerial_mate_not_back")}
MIN_N = {"time": 40, "situations": 6}


def merge(measures: list[dict]) -> dict[str, dict]:
    """Combine several replays of the same player into rates."""
    out = {}
    for name, (grp, key) in KEYMAP.items():
        hits = sum(m[grp][key]["hits"] for m in measures)
        n = sum(m[grp][key]["n"] for m in measures)
        ex = [e for m in measures for e in m[grp][key]["examples"]][:3]
        out[name] = {"rate": round(hits / n, 3) if n else None, "hits": hits, "n": n, "examples": ex,
                     "enough_data": n >= MIN_N[grp] * max(1, len(measures) // 2)}
    return out


def load_reference(path: Path | None = None) -> dict | None:
    try:
        return json.loads((path or REFERENCE_PATH).read_text())
    except (OSError, ValueError):
        return None


def _percentile(value: float, ref: list[float]) -> int | None:
    if value is None or not ref:
        return None
    below = sum(r < value for r in ref) + 0.5 * sum(r == value for r in ref)
    return int(round(100 * below / len(ref)))


def build_profile(replays: list[dict], focus_ids: list[str], *, reference: dict | None = None) -> dict[str, Any]:
    """Habit profile for one player across one or more replays (focus_ids[i] is their id in replays[i])."""
    if not replays or len(replays) != len(focus_ids):
        raise ValueError("Give one focus id per replay.")
    ms = [measure(r, f) for r, f in zip(replays, focus_ids)]
    rates = merge(ms)
    ref = reference if reference is not None else load_reference()
    habits = []
    for name, r in rates.items():
        refv = (ref or {}).get("metrics", {}).get(name, [])
        rel = (ref or {}).get("reliability", {}).get(name, {})
        need = rel.get("matches_needed_for_0.7")
        pct = _percentile(r["rate"], refv) if r["enough_data"] else None
        reliable_now = need is not None and len(replays) >= need
        standout = None if pct is None else ("high" if pct >= 85 else "low" if pct <= 15 else None)
        habits.append({"metric": name, "description": METRICS[name], **r, "reference_percentile": pct,
                       "reference_n_player_matches": len(refv),
                       "per_match_reliability": rel.get("per_match_reliability"), "matches_needed": need,
                       "reliable_with_these_matches": reliable_now,
                       "standout": standout if reliable_now else None,
                       "standout_if_reliable": standout,
                       "status": ("measured" if reliable_now else
                                  "not yet a stable tendency in the reference data" if need is None else
                                  f"needs about {need} matches before it describes a tendency")})
    return {"schema": "HabitProfileV0", "version": VERSION, "replays": len(replays), "experimental": True,
            "habits": habits,
            "reference": {"cohort": (ref or {}).get("cohort"), "note": "Reference = public 2v2 replays of unknown rank. "
                                                                   "A high or low percentile means 'unusual against that "
                                                                   "reference', not good or bad."},
            "limits": ["Split-half reliability within a match is low for most metrics (docs/round13/habit_reliability.json): "
                       "a standout is only flagged once enough matches are combined.",
                       "Rates are descriptive; team strategy and rank change what is normal.",
                       "Observed actions are movement-based labels, not intent.",
                       "Needs several matches before a standout means much."]}

"""DecisionEvidenceV0: one inspectable pre-commitment evidence record for a 2v2 decision (Round 7).

A record holds what was observable at or before t0, each item under a stable id
that an explanation can cite, plus a separate retrospective block. It reuses
Round 5 code (``reachability``, ``strategic_state``, ``choices``) and adds no
tactical judgement: a reachable touch is feasibility, not merit.

Information rules
- Pre-decision fields read only frames and events with time <= t0. Decoder
  event attributes computed from later frames (touch kind, ball speed change,
  whiff/shadow classifications, 50/50 winners) are excluded from context.
- Unknown stays unknown: a missing or invalid value is listed under ``unknowns``
  with a ``U.`` id and is never replaced by zero, a default or a guess.
- Freshness: the parser samples the replay at 30 Hz and holds the last state, so
  a car state can repeat. A state unchanged for longer than ``STALE_S`` is marked
  ``stale_possible``. Boost carries ``freshness_unverified`` always: the parser
  does not expose when the boost value was last replicated.
- Visibility: positions are what the replay recorded, not what the player saw.
- Retrospective fields (observed action, next touch, goal) live only under
  ``retrospective``, each with ``finalized_through_s`` after t0.
"""
from __future__ import annotations

import bisect
import math
from typing import Any

from .choices import classify_choice
from .reachability import estimate_reach
from .strategic_state import build_state

SCHEMA = "DecisionEvidenceV0"
CONTEXT_S = 3.0
STALE_S = 0.1
MAX_LOOKBACK_S = 0.15
ROLE_AMBIGUOUS_S = 0.25
RETRO_TOUCH_S = 3.0
RETRO_GOAL_S = 5.0
ARENA = {"x": 4300.0, "y": 6200.0, "z_min": -50.0, "z_max": 2200.0}   # generous bounds incl. goal depth
CONTEXT_EVENT_TYPES = {"touch": ("playerId",), "boost_pickups": ("playerId", "padType"),
                       "demolition": ("attackerId", "victimId"), "bump": ("playerId", "victimId")}
NOT_OBSERVABLE = [
    "What each player could see (camera direction, ball cam). Positions are recorded, not perceived.",
    "Controller inputs and intent.",
    "Quick chat, voice calls and agreements between teammates.",
    "Ball spin.",
    "Whether each car still had a flip or dodge available.",
    "Exact boost between replicated updates.",
    "Network latency each player experienced.",
]


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _valid_position(c: dict) -> bool:
    x, y, z = c.get("x"), c.get("y"), c.get("z")
    return (all(_finite(v) for v in (x, y, z)) and abs(x) <= ARENA["x"] and abs(y) <= ARENA["y"]
            and ARENA["z_min"] <= z <= ARENA["z_max"])


def _vec_ok(v: Any) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == 3 and all(_finite(c) for c in v)


def _state_key(c: dict | None) -> tuple | None:
    if not c:
        return None
    return (c.get("x"), c.get("y"), c.get("z"), tuple(c.get("velocity") or ()))


def _first_seen(frames: list[dict], idx: int, get) -> float:
    """Time the state at ``idx`` was first sampled, scanning back while it is unchanged (past frames only)."""
    key, j = _state_key(get(frames[idx])), idx
    while j > 0 and _state_key(get(frames[j - 1])) == key and key is not None:
        j -= 1
    return frames[j]["t"]


class _Builder:
    def __init__(self) -> None:
        self.evidence: list[dict] = []
        self.unknowns: list[dict] = []

    def fact(self, id_: str, value: Any, unit: str | None, source_time_s: float | None, provenance: list[str],
             kind: str = "observation", note: str | None = None) -> str:
        item = {"id": id_, "kind": kind, "value": value, "unit": unit, "source_time_s": source_time_s,
                "provenance": provenance}
        if note:
            item["note"] = note
        self.evidence.append(item)
        return id_

    def unknown(self, id_: str, what: str, why: str) -> str:
        self.unknowns.append({"id": id_, "what": what, "why": why})
        return id_


def _slots(players: list[dict], focus: str) -> dict[str, str]:
    """Stable anonymous slot per player: focus, teammate, opponent_1/2 (opponents ordered by player id)."""
    team = {p["id"]: p.get("team") for p in players}
    me = team.get(focus)
    mates = sorted(p for p, t in team.items() if t == me and p != focus)
    opps = sorted(p for p, t in team.items() if t not in (None, me))
    out = {focus: "focus"}
    if mates:
        out[mates[0]] = "teammate"
    for k, p in enumerate(opps, 1):
        out[p] = f"opponent_{k}"
    return out


def build_decision_evidence(payload: dict[str, Any], t0: float, focus_id: str, *, context_s: float = CONTEXT_S,
                            selection: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a DecisionEvidenceV0 record. ``selection`` records why this t0 was chosen (rule, version, values)."""
    frames = payload.get("frames", [])
    players = payload.get("players", [])
    slots = _slots(players, focus_id)
    team_of = {p["id"]: p.get("team") for p in players}
    b = _Builder()
    times = [f.get("t", 0.0) for f in frames]
    idx = bisect.bisect_right(times, t0) - 1
    record: dict[str, Any] = {
        "schema": SCHEMA, "t0": t0, "focus_slot": "focus",
        "slots": {slot: {"team": team_of.get(pid)} for pid, slot in slots.items()},
        "selection": selection or {"rule": "caller-provided t0", "note": "no selection rule recorded"},
        "source": {"parser": payload.get("source"), "sampling_s": payload.get("samplingSeconds"),
                   "player_mapping_verified": payload.get("playerMappingVerified"),
                   "note": "30 Hz sample-and-hold of replicated states; parser-level future invariance is "
                           "tested here by truncation, raw packet update ages are not available."},
        "not_observable": list(NOT_OBSERVABLE),
        "rules": ["Pre-decision evidence uses only data at or before t0.",
                  "Reachability is physical feasibility, not tactical merit.",
                  "Cite evidence by id; a U. id is an unknown and cannot support a claim.",
                  "Retrospective fields describe what happened later and are never reasons the player could know."],
    }
    if idx < 0 or t0 - times[idx] > MAX_LOOKBACK_S:
        b.unknown("U.frame", "Game state at t0", "no sampled frame within 0.15 s before t0")
        record.update(evidence=b.evidence, unknowns=b.unknowns, status="abstain", retrospective=None)
        return record
    fr = frames[idx]
    record["frame_time_s"] = fr["t"]
    lookback = round(t0 - fr["t"], 4)

    # ---- ball ----
    ball = fr.get("ball") or {}
    ball_ok = _valid_position(ball) and _vec_ok(ball.get("velocity"))
    if ball_ok:
        seen = _first_seen(frames, idx, lambda f: f.get("ball"))
        prov = ["replay_sample"] + (["stale_possible"] if t0 - seen > STALE_S else [])
        b.fact("E.ball.position", [ball["x"], ball["y"], ball["z"]], "uu", fr["t"], prov)
        b.fact("E.ball.velocity", list(ball["velocity"]), "uu/s", fr["t"], prov)
        b.fact("E.ball.state_age", round(t0 - seen, 3), "s", fr["t"], ["derived"], "derived",
               "Time since the sampled ball state last changed.")
    else:
        b.unknown("U.ball.state", "Ball position/velocity at t0", "missing or outside the arena in the t0 sample")

    # ---- cars ----
    clean_cars: dict[str, dict] = {}
    for pid, slot in slots.items():
        c = (fr.get("cars") or {}).get(pid)
        if not c:
            b.unknown(f"U.{slot}.state", f"{slot} car state", "car absent from the t0 sample")
            continue
        if c.get("demolished"):
            b.unknown(f"U.{slot}.state", f"{slot} car state", "demolished (waiting to respawn) at t0")
            continue
        if not _valid_position(c):
            b.unknown(f"U.{slot}.state", f"{slot} car position", "non-finite or outside the arena in the t0 sample")
            continue
        seen = _first_seen(frames, idx, lambda f, p=pid: (f.get("cars") or {}).get(p))
        stale = t0 - seen > STALE_S
        prov = ["replay_sample"] + (["stale_possible"] if stale else [])
        b.fact(f"E.{slot}.position", [c["x"], c["y"], c["z"]], "uu", fr["t"], prov)
        b.fact(f"E.{slot}.state_age", round(t0 - seen, 3), "s", fr["t"], ["derived"], "derived",
               "Time since this car's sampled state last changed.")
        clean = {k: c[k] for k in ("x", "y", "z")}
        if _vec_ok(c.get("velocity")):
            b.fact(f"E.{slot}.velocity", list(c["velocity"]), "uu/s", fr["t"], prov)
            clean["velocity"] = list(c["velocity"])
        else:
            b.unknown(f"U.{slot}.velocity", f"{slot} velocity", "missing in the t0 sample")
        if _vec_ok(c.get("forward")):
            b.fact(f"E.{slot}.forward", list(c["forward"]), "unit vector", fr["t"], prov,
                   note="Nose direction from the rotation; not the camera direction.")
            clean["forward"] = list(c["forward"])
        else:
            b.unknown(f"U.{slot}.forward", f"{slot} orientation", "rotation missing in the t0 sample")
        boost = c.get("boost")
        if _finite(boost) and 0.0 <= boost <= 100.0:
            b.fact(f"E.{slot}.boost", boost, "0-100", fr["t"], prov + ["freshness_unverified"],
                   note="Finite amount; 0 means empty, not unknown.")
            clean["boost"] = boost
        else:
            b.unknown(f"U.{slot}.boost", f"{slot} boost", "missing or out of range in the t0 sample")
            clean["boost"] = None
        if "jumpActive" in c:
            b.fact(f"E.{slot}.jump_active", bool(c["jumpActive"]), None, fr["t"], prov)
        clean_cars[pid] = clean

    # ---- reachability, roles, cover (Round 5 code on a sanitized single-frame copy) ----
    if ball_ok:
        ball_clean = {"x": ball["x"], "y": ball["y"], "z": ball["z"], "velocity": list(ball["velocity"])}
        reach = {}
        for pid, slot in slots.items():
            r = estimate_reach(clean_cars.get(pid), ball_clean)
            reach[pid] = r
            if r.status == "abstain":
                b.unknown(f"U.reach.{slot}", f"{slot} earliest feasible touch", r.reason or "abstained")
            else:
                b.fact(f"E.reach.{slot}", {"status": r.status, "t_min_s": r.t_min, "t_max_s": r.t_max,
                                           "approach": r.approach, "unknowns": r.unknowns},
                       "s after t0", fr["t"], ["derived", "kinematic_model:" + r.model], "derived",
                       "Lower bound on time to touch under the listed assumptions; not a prediction.")
        single = {"players": players, "frames": [{"t": fr["t"], "ball": ball_clean, "cars": clean_cars}]}
        st = build_state(single, t0, focus_id, reach_cache={p: reach[p] for p in reach})
        _roles(b, st, slots, reach)
        if st is not None and "teammate" in slots.values():
            if st.cover_s is None:
                b.unknown("U.cover.teammate", "Time for the teammate to get goal-side",
                          "teammate state, orientation or ground contact unknown")
            else:
                b.fact("E.cover.teammate", None if math.isinf(st.cover_s) else st.cover_s, "s after t0", fr["t"],
                       ["derived", "kinematic_model"], "derived",
                       "0 = already between ball and own goal; null = not reachable within 4 s. A feasibility "
                       "bound, not proof the teammate would cover.")
    else:
        b.unknown("U.reach.all", "Reachability for every car", "ball state unknown at t0")

    # ---- preceding context (t0 - context_s, t0] ----
    record["context"] = _context(b, payload, frames, times, idx, t0, context_s, slots)
    if lookback > 0:
        record["lookback_s"] = lookback
    record.update(evidence=b.evidence, unknowns=b.unknowns, status="ok" if ball_ok else "partial")
    record["retrospective"] = _retrospective(payload, t0, focus_id, slots)
    return record


def _roles(b: _Builder, st, slots: dict[str, str], reach: dict) -> None:
    if st is None:
        b.unknown("U.roles", "First/second roles", "strategic state unavailable")
        return
    for team_label, pids in (("own", [p for p, s in slots.items() if s in ("focus", "teammate")]),
                             ("opponents", [p for p, s in slots.items() if s.startswith("opponent")])):
        times = {p: (reach[p].t_min if reach[p].status == "ok" else math.inf if reach[p].status == "out_of_horizon"
                     else None) for p in pids}
        if len(pids) < 2 or any(v is None for v in times.values()):
            b.unknown(f"U.roles.{team_label}", f"{team_label} first/second roles", "a car's earliest touch is unknown")
            continue
        if all(math.isinf(v) for v in times.values()):
            # inf - inf would be NaN: neither car can touch within the horizon, so the order is unknown
            b.unknown(f"U.roles.{team_label}", f"{team_label} first/second roles",
                      "neither car can reach the ball within the model horizon")
            continue
        order = sorted(pids, key=lambda p: times[p])
        gap = times[order[1]] - times[order[0]]
        b.fact(f"E.roles.{team_label}", {"first": slots[order[0]], "second": slots[order[1]],
                                          "gap_s": None if math.isinf(gap) else round(gap, 3),
                                          "confidence": "ambiguous" if gap < ROLE_AMBIGUOUS_S else "estimate"},
               None, st.t0, ["derived"], "derived",
               "Ordered by earliest feasible touch, not by rotation intent or what the players agreed.")
    if st.margin_s is not None:
        lo, hi = st.margin_interval
        b.fact("E.race.margin", {"margin_s": st.margin_s, "pessimistic_s": lo, "optimistic_s": hi}, "s", st.t0,
               ["derived"], "derived", "Fastest opponent minus fastest own-team touch bound; positive = own team first.")


def _context(b: _Builder, payload, frames, times, idx, t0, context_s, slots) -> dict:
    start = t0 - context_s
    events = sorted((e for e in payload.get("events", []) if e.get("type") in CONTEXT_EVENT_TYPES
                     and _finite(e.get("t")) and start < e["t"] <= t0), key=lambda e: e["t"])
    ids = []
    for k, e in enumerate(events, 1):
        fields = {f: slots.get(e.get(f), "unknown_player") if f.endswith("Id") else e.get(f)
                  for f in CONTEXT_EVENT_TYPES[e["type"]]}
        prov = ["decoder_event"] + (["pad_inferred_from_position"] if e["type"] == "boost_pickups" else [])
        ids.append(b.fact(f"C.{e['type']}.{k}", {"t": e["t"], **fields}, None, e["t"], prov, "context_event"))
    j = bisect.bisect_right(times, start) - 1
    boost_change = {}
    if j >= 0:
        for pid, slot in slots.items():
            before = (frames[j].get("cars") or {}).get(pid, {}).get("boost")
            now = (frames[idx].get("cars") or {}).get(pid, {}).get("boost")
            if _finite(before) and _finite(now):
                boost_change[slot] = b.fact(f"C.boost_change.{slot}", round(now - before, 1), "boost", frames[idx]["t"],
                                            ["derived", "freshness_unverified"], "derived",
                                            f"Boost at t0 minus boost {context_s:.0f} s earlier (net of pickups).")
            else:
                b.unknown(f"U.boost_change.{slot}", f"{slot} boost change over the context window", "boost unknown at one end")
    return {"window_s": context_s, "from_s": round(start, 3), "event_ids": ids,
            "excluded": "Touch kind/strength, whiffs, shadow and 50/50 labels are decided from later frames and are omitted."}


def _retrospective(payload, t0, focus_id, slots) -> dict:
    lab = classify_choice(payload, t0, focus_id)
    touches = sorted((e["t"], e.get("playerId")) for e in payload.get("events", [])
                     if e.get("type") == "touch" and _finite(e.get("t")) and t0 < e["t"] <= t0 + RETRO_TOUCH_S)
    goal = next((e for e in sorted(payload.get("events", []), key=lambda e: e.get("t", 0))
                 if e.get("type") == "goal_context" and _finite(e.get("t")) and t0 < e["t"] <= t0 + RETRO_GOAL_S), None)
    team_of = {p["id"]: p.get("team") for p in payload.get("players", [])}
    focus_team = team_of.get(focus_id)
    return {
        "kind": "retrospective",
        "warning": "Happened after t0. Not known at the decision, not intent, and not proof of decision quality.",
        "observed_action": {"id": "R.observed_action", "label": lab.choice, "basis": lab.basis,
                            "finalized_through_s": round(lab.finalized_through_s, 3)},
        "next_touch": {"id": "R.next_touch",
                       "slot": slots.get(touches[0][1], "unknown_player") if touches else None,
                       "after_s": round(touches[0][0] - t0, 3) if touches else None,
                       "finalized_through_s": round(touches[0][0] if touches else t0 + RETRO_TOUCH_S, 3)},
        "goal_within_5s": {"id": "R.goal_within_5s",
                           "scored_by": None if goal is None else ("own team" if team_of.get(goal.get("scorerId")) == focus_team
                                                                   else "opponents"),
                           "finalized_through_s": round(goal["t"] if goal else t0 + RETRO_GOAL_S, 3)},
    }


def resolve(record: dict, evidence_id: str) -> dict | None:
    """Return the evidence item for an id, or None if the record has no such fact."""
    for item in record.get("evidence", []):
        if item["id"] == evidence_id:
            return item
    return None


def check_citations(record: dict, ids: list[str]) -> list[str]:
    """Problems with a set of citations: unknown ids, U. ids (unknowns) or R. ids used as decision-time support."""
    known = {e["id"] for e in record.get("evidence", [])}
    unknown_ids = {u["id"] for u in record.get("unknowns", [])}
    problems = []
    for i in ids:
        if i in unknown_ids:
            problems.append(f"{i} is an unknown; it cannot support a claim.")
        elif i.startswith("R."):
            problems.append(f"{i} is retrospective; it cannot be a reason available at t0.")
        elif i not in known:
            problems.append(f"{i} does not exist in this record.")
    return problems

"""EpisodeEvidenceV0: a chronological episode of DecisionEvidenceV0 nodes (Round 8).

Composes 2-4 existing decision records from one manually selected 5-20 s window
so a reasoner can ask how an earlier situation shaped a later one. It does not
change the DecisionEvidenceV0 contract and makes no judgement.

Information rules
- Each node is built from the replay **truncated at its own t_i** (frames and
  events after t_i deleted), so no node can see beyond its own decision time.
- The episode's Stage 1 information horizon is ``primary_t0``: every decision
  time must be at or before it, and nothing after it enters the Stage 1 part.
- Change summaries compare node snapshots only. A change from N_i to N_j is
  information available at t_j, not a verdict on N_i.
- "Possible earlier contributing decisions" are neutral questions with the
  evidence ids that prompted them. They never assert causation.
- Retrospective labels (each node's observed action, next touch, goal) live only
  in ``retrospective``, which ``stage1_view`` strips.

Ids: a node's own ids are kept exactly and addressed globally as
``N<k>/<local id>`` (e.g. ``N2/E.focus.boost``). Episode-level ids are
``D.`` (change), ``UD.`` (change that cannot be computed), ``T.`` (timeline
event), ``H.`` (hypothesis prompt) and ``N<k>/R.`` (retrospective).
"""
from __future__ import annotations

import copy
import hashlib
import math
from typing import Any

from .decision_evidence import CONTEXT_EVENT_TYPES, _finite, _slots, build_decision_evidence

SCHEMA = "EpisodeEvidenceV0"
MIN_WINDOW_S, MAX_WINDOW_S = 5.0, 20.0
MIN_NODES, MAX_NODES = 2, 4
GOAL_Y = 5120.0
# Prompts for earlier contributing decisions: deliberately coarse, each one only opens a question.
BOOST_DROP = 30.0
ADVANCE_UU = 1500.0


class EpisodeError(ValueError):
    """The requested window or decision times cannot form a valid episode."""


def _truncate(payload: dict[str, Any], t: float) -> dict[str, Any]:
    out = dict(payload)
    out["frames"] = [f for f in payload.get("frames", []) if f.get("t", math.inf) <= t]
    out["events"] = [e for e in payload.get("events", []) if _finite(e.get("t")) and e["t"] <= t]
    return out


def _value(snapshot: dict, local_id: str) -> Any:
    for e in snapshot.get("evidence", []):
        if e["id"] == local_id:
            return e["value"]
    return None


def _unknown_ids(snapshot: dict, prefix: str) -> list[str]:
    return [u["id"] for u in snapshot.get("unknowns", []) if u["id"].startswith(prefix)]


def _rel_y(team: str | None, y: float) -> float:
    return y if team == "blue" else -y


def build_episode_evidence(replay: dict[str, Any], focus_id: str, decision_times: list[float],
                           episode_start_s: float, primary_t0: float, *, label: str | None = None) -> dict[str, Any]:
    """Assemble an EpisodeEvidenceV0 record. Raises EpisodeError for an invalid request."""
    times = sorted({round(float(t), 3) for t in decision_times})
    primary_t0 = round(float(primary_t0), 3)
    if not MIN_NODES <= len(times) <= MAX_NODES:
        raise EpisodeError(f"Need {MIN_NODES}-{MAX_NODES} distinct decision times, got {len(times)}.")
    if primary_t0 not in times or times[-1] != primary_t0:
        raise EpisodeError("primary_t0 must be one of the decision times and the latest of them.")
    window = primary_t0 - episode_start_s
    if not MIN_WINDOW_S <= window <= MAX_WINDOW_S or times[0] < episode_start_s:
        raise EpisodeError(f"Window must be {MIN_WINDOW_S:.0f}-{MAX_WINDOW_S:.0f} s and contain every decision time.")
    players = replay.get("players", [])
    if focus_id not in {p["id"] for p in players}:
        raise EpisodeError("Focus player is not in this replay.")
    slots = _slots(players, focus_id)
    team = {p["id"]: p.get("team") for p in players}.get(focus_id)
    episode_id = "ep-" + hashlib.sha256(
        f"{replay.get('title')}|{focus_id}|{episode_start_s:.3f}|{','.join(f'{t:.3f}' for t in times)}".encode()
    ).hexdigest()[:12]

    nodes, retro = [], {}
    for k, t in enumerate(times, 1):
        nid = f"N{k}"
        # The node sees only the replay up to its own decision time.
        rec = build_decision_evidence(_truncate(replay, t), t, focus_id,
                                      selection={"rule": "manual episode selection", "episode_id": episode_id})
        full = build_decision_evidence(replay, t, focus_id, selection=rec["selection"])
        retro[nid] = _namespace_retro(nid, full["retrospective"])
        snapshot = {k2: v for k2, v in rec.items() if k2 != "retrospective"}
        nodes.append({"node_id": nid, "t0": t, "is_primary": t == primary_t0, "status": rec["status"],
                      "information_cutoff_s": t, "snapshot": snapshot})
    relations = [{"from": a["node_id"], "to": b["node_id"], "relation": "precedes",
                  "gap_s": round(b["t0"] - a["t0"], 3)} for a, b in zip(nodes, nodes[1:])]
    changes, change_unknowns = _changes(nodes, team)
    timeline = _timeline(replay, episode_start_s, primary_t0, slots)
    hypotheses = _hypotheses(nodes, changes, timeline)
    unknowns = [{"id": f"{n['node_id']}/{u['id']}", "what": u["what"], "why": u["why"]}
                for n in nodes for u in n["snapshot"]["unknowns"]] + change_unknowns
    primary = nodes[-1]
    status = "abstain" if primary["status"] == "abstain" else (
        "partial" if any(n["status"] != "ok" for n in nodes) else "ok")
    return {
        "schema": SCHEMA, "episode_id": episode_id, "label": label, "status": status,
        "focus_slot": "focus", "slots": nodes[0]["snapshot"]["slots"],
        "window": {"start_s": episode_start_s, "end_s": primary_t0, "length_s": round(window, 3),
                   "selection": "manual", "stage1_horizon_s": primary_t0},
        "nodes": nodes, "relations": relations,
        "changes": changes, "timeline": timeline, "unknowns": unknowns,
        "possible_earlier_contributors": hypotheses,
        "rules": [
            "Each node's snapshot was built from the replay truncated at that node's t0.",
            "Changes between nodes are known at the later node's time; they are not verdicts on the earlier node.",
            "Possible earlier contributors are questions to investigate, not established causes.",
            "Cite node evidence as N<k>/<id>. U./UD. ids are unknowns. Retrospective ids are Stage 2 only.",
        ],
        "retrospective": {"stage": 2, "warning": "After each node's t0. Not available to Stage 1 reasoning, "
                                                  "not intent and not proof of decision quality.",
                          "nodes": retro},
    }


def _namespace_retro(nid: str, r: dict | None) -> dict | None:
    if not r:
        return None
    out = copy.deepcopy(r)
    for key in ("observed_action", "next_touch", "goal_within_5s"):
        if isinstance(out.get(key), dict) and "id" in out[key]:
            out[key]["id"] = f"{nid}/{out[key]['id']}"
    return out


def _change(changes, unknowns, pair, field, a, b, a_id, b_id, value_fn, unit, note, missing):
    cid = f"{pair}.{field}"
    if a is None or b is None:
        unknowns.append({"id": f"UD.{cid}", "what": f"Change in {field.replace('.', ' ')}",
                         "why": "a required value is unknown at one node", "refs": missing})
        return
    changes.append({"id": f"D.{cid}", "kind": "change", "value": value_fn(a, b), "unit": unit,
                    "refs": [a_id, b_id], "known_at_s": None, "note": note})


def _changes(nodes: list[dict], team: str | None) -> tuple[list[dict], list[dict]]:
    changes: list[dict] = []
    unknowns: list[dict] = []
    pairs = list(zip(nodes, nodes[1:]))
    if len(nodes) > 2:
        pairs.append((nodes[0], nodes[-1]))
    for a, b in pairs:
        pair = f"{a['node_id']}-{b['node_id']}"
        sa, sb = a["snapshot"], b["snapshot"]
        start = len(changes)

        def ref(n, local):
            return f"{n['node_id']}/{local}"

        def miss(local):
            return [ref(n, u) for n, s in ((a, sa), (b, sb))
                    for u in _unknown_ids(s, local) + _unknown_ids(s, "U.frame")]

        for slot in sa.get("slots", {}):
            pa, pb = _value(sa, f"E.{slot}.position"), _value(sb, f"E.{slot}.position")
            _change(changes, unknowns, pair, f"{slot}.distance_moved", pa, pb,
                    ref(a, f"E.{slot}.position"), ref(b, f"E.{slot}.position"),
                    lambda p, q: round(math.dist(p, q)), "uu", "Straight-line displacement, not path length.",
                    miss(f"U.{slot}.state"))
            if slot in ("focus", "teammate"):
                _change(changes, unknowns, pair, f"{slot}.advance_toward_opponent_goal", pa, pb,
                        ref(a, f"E.{slot}.position"), ref(b, f"E.{slot}.position"),
                        lambda p, q: round(_rel_y(team, q[1]) - _rel_y(team, p[1])), "uu",
                        "Positive = moved up-field (toward the opponent goal).", miss(f"U.{slot}.state"))
            ba, bb = _value(sa, f"E.{slot}.boost"), _value(sb, f"E.{slot}.boost")
            _change(changes, unknowns, pair, f"{slot}.boost", ba, bb, ref(a, f"E.{slot}.boost"),
                    ref(b, f"E.{slot}.boost"), lambda p, q: round(q - p, 1), "boost",
                    "Net change; includes pickups. Boost freshness is unverified at both ends.",
                    miss(f"U.{slot}.boost"))
        fa, fb = _value(sa, "E.focus.position"), _value(sb, "E.focus.position")
        ma, mb = _value(sa, "E.teammate.position"), _value(sb, "E.teammate.position")
        if None in (fa, fb, ma, mb):
            unknowns.append({"id": f"UD.{pair}.team_spacing", "what": "Change in focus-teammate spacing",
                             "why": "a position is unknown at one node",
                             "refs": miss("U.focus.state") + miss("U.teammate.state")})
        else:
            changes.append({"id": f"D.{pair}.team_spacing", "kind": "change",
                            "value": {"from_uu": round(math.dist(fa, ma)), "to_uu": round(math.dist(fb, mb))}, "unit": "uu",
                            "refs": [ref(a, "E.focus.position"), ref(a, "E.teammate.position"),
                                     ref(b, "E.focus.position"), ref(b, "E.teammate.position")],
                            "known_at_s": None, "note": "Distance between the focus player and the teammate."})
        ra, rb = _value(sa, "E.roles.own"), _value(sb, "E.roles.own")
        _change(changes, unknowns, pair, "roles.own", ra, rb, ref(a, "E.roles.own"), ref(b, "E.roles.own"),
                lambda p, q: {"from_first": p["first"], "to_first": q["first"],
                              "from_confidence": p["confidence"], "to_confidence": q["confidence"]},
                None, "Role estimates by earliest feasible touch at each node; not rotation intent.", miss("U.roles.own"))
        xa, xb = _value(sa, "E.reach.focus"), _value(sb, "E.reach.focus")
        _change(changes, unknowns, pair, "focus.earliest_touch", xa, xb, ref(a, "E.reach.focus"), ref(b, "E.reach.focus"),
                lambda p, q: {"from_s": p["t_min_s"], "to_s": q["t_min_s"], "from_status": p["status"],
                              "to_status": q["status"]}, "s after each node's t0",
                "Feasibility bounds at each node, not a measure of effort or choice.", miss("U.reach.focus"))
        ca, cb = _value(sa, "E.cover.teammate"), _value(sb, "E.cover.teammate")
        has_a = any(e["id"] == "E.cover.teammate" for e in sa["evidence"])
        has_b = any(e["id"] == "E.cover.teammate" for e in sb["evidence"])
        if has_a and has_b:
            changes.append({"id": f"D.{pair}.teammate_cover", "kind": "change", "value": {"from_s": ca, "to_s": cb},
                            "unit": "s after each node's t0", "refs": [ref(a, "E.cover.teammate"), ref(b, "E.cover.teammate")],
                            "known_at_s": None, "note": "Teammate's feasible time to get goal-side; null = beyond 4 s."})
        else:
            unknowns.append({"id": f"UD.{pair}.teammate_cover", "what": "Change in teammate cover time",
                             "why": "teammate cover unknown at one node", "refs": miss("U.cover.teammate")})
        for c in changes[start:]:
            c["known_at_s"] = b["t0"]
    return changes, unknowns


def _timeline(replay: dict, start: float, end: float, slots: dict[str, str]) -> list[dict]:
    """Decision-time-safe events inside the window, attributes limited as in DecisionEvidenceV0."""
    evs = sorted((e for e in replay.get("events", []) if e.get("type") in CONTEXT_EVENT_TYPES
                  and _finite(e.get("t")) and start <= e["t"] <= end), key=lambda e: (e["t"], e["type"]))
    out = []
    for k, e in enumerate(evs, 1):
        fields = {f: slots.get(e.get(f), "unknown_player") if f.endswith("Id") else e.get(f)
                  for f in CONTEXT_EVENT_TYPES[e["type"]]}
        out.append({"id": f"T.{e['type']}.{k}", "type": e["type"], "t": e["t"], **fields,
                    "provenance": ["decoder_event"] + (["pad_inferred_from_position"] if e["type"] == "boost_pickups" else [])})
    return out


def _hypotheses(nodes: list[dict], changes: list[dict], timeline: list[dict]) -> list[dict]:
    """Neutral prompts: earlier observations worth checking against the primary situation."""
    primary = nodes[-1]["node_id"]
    by_id = {c["id"]: c for c in changes}
    out: list[dict] = []

    def add(earlier, question, refs):
        out.append({"id": f"H.{len(out) + 1}", "earlier_node": earlier, "concerns_node": primary,
                    "question": question, "evidence_refs": refs, "status": "hypothesis_unverified",
                    "not_established": "Whether this contributed to the later situation; no causal claim is made."})

    for a, b in zip(nodes, nodes[1:]):
        pair = f"{a['node_id']}-{b['node_id']}"
        boost = by_id.get(f"D.{pair}.focus.boost")
        if boost and boost["value"] <= -BOOST_DROP:
            add(a["node_id"], f"Focus boost fell by {-boost['value']:.0f} between {a['node_id']} and {b['node_id']}. "
                              "Did the way it was spent limit options later?", [boost["id"], *boost["refs"]])
        adv = by_id.get(f"D.{pair}.focus.advance_toward_opponent_goal")
        if adv and adv["value"] >= ADVANCE_UU:
            add(a["node_id"], f"Focus moved {adv['value']} uu up-field between {a['node_id']} and {b['node_id']}. "
                              "Did that position affect the later defensive options?", [adv["id"], *adv["refs"]])
        roles = by_id.get(f"D.{pair}.roles.own")
        if roles and roles["value"]["from_first"] != roles["value"]["to_first"]:
            add(a["node_id"], f"The estimated first player changed from {roles['value']['from_first']} to "
                              f"{roles['value']['to_first']}. Was that handover planned or forced?",
                [roles["id"], *roles["refs"]])
        cover = by_id.get(f"D.{pair}.teammate_cover")
        if cover and _worse(cover["value"]["from_s"], cover["value"]["to_s"]):
            add(a["node_id"], f"Teammate cover time went from {_fmt(cover['value']['from_s'])} to "
                              f"{_fmt(cover['value']['to_s'])}. What changed in the team's spacing?",
                [cover["id"], *cover["refs"]])
    for ev in timeline:
        actors = {ev.get("victimId"), ev.get("playerId"), ev.get("attackerId")}
        if ev["type"] in ("demolition", "bump") and actors & {"focus", "teammate"}:
            add(None, f"A {ev['type']} involving the focus team happened at {ev['t']:.1f} s. Did it change the later situation?",
                [ev["id"]])
    return out


def _worse(a: float | None, b: float | None) -> bool:
    a = math.inf if a is None else a
    b = math.inf if b is None else b
    return b > a + 0.5


def _fmt(t: float | None) -> str:
    return "beyond 4 s" if t is None else f"{t:.2f} s"


def stage1_view(episode: dict[str, Any]) -> dict[str, Any]:
    """Everything a Stage 1 reasoner may see: the episode without its retrospective section."""
    return copy.deepcopy({k: v for k, v in episode.items() if k != "retrospective"})


def all_ids(episode: dict[str, Any]) -> list[str]:
    """Every globally addressable id in the episode, for uniqueness and citation checks."""
    ids = []
    for n in episode["nodes"]:
        ids += [f"{n['node_id']}/{e['id']}" for e in n["snapshot"]["evidence"]]
    ids += [u["id"] for u in episode["unknowns"]]
    ids += [c["id"] for c in episode["changes"]] + [t["id"] for t in episode["timeline"]]
    ids += [h["id"] for h in episode["possible_earlier_contributors"]]
    for r in episode["retrospective"]["nodes"].values():
        if r:
            ids += [r[k]["id"] for k in ("observed_action", "next_touch", "goal_within_5s")]
    return ids


def resolve(episode: dict[str, Any], gid: str) -> dict | None:
    """Look up a Stage 1 id (N<k>/E..., N<k>/C..., D., T., H.). Unknown and retrospective ids return None."""
    if "/" in gid:
        nid, local = gid.split("/", 1)
        node = next((n for n in episode["nodes"] if n["node_id"] == nid), None)
        if node is None:
            return None
        return next((e for e in node["snapshot"]["evidence"] if e["id"] == local), None)
    for coll in ("changes", "timeline", "possible_earlier_contributors"):
        hit = next((x for x in episode[coll] if x["id"] == gid), None)
        if hit:
            return hit
    return None

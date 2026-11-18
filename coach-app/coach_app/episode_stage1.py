"""Hard Stage 1 episode boundary for the later replay-coaching reasoner.

EpisodeEvidenceV0.stage1_view() strips the outcome block but leaves raw
selection/source/label metadata; DO NOT send it straight to an LLM.
Use this strict whitelist serializer instead. No coaching conclusions are made.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .decision_evidence import CONTEXT_EVENT_TYPES
from .episode_evidence import SCHEMA as EPISODE_SCHEMA
from .stage1_packet import Stage1PacketError, _copy_json_safe, build_stage1_packet

SCHEMA = "Stage1EpisodePacketV0"
MAX_NODES = 4
MAX_ITEMS = 1200
SLOTS = frozenset(("focus", "teammate", "opponent_1", "opponent_2"))
NODE = re.compile(r"N[1-4]$")
CHANGE_ID = re.compile(r"D\.N[1-4]-N[1-4]\.[a-zA-Z][a-zA-Z0-9_.]*$")
TIMELINE_ID = re.compile(r"T\.(touch|boost_pickups|bump|demolition)\.[1-9][0-9]*$")
H_ID = re.compile(r"H\.[1-9][0-9]*$")


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _refs(refs: Any, allowed: set[str], kind: str, *, allow_empty: bool = False) -> list[str]:
    if (not isinstance(refs, list) or (not refs and not allow_empty) or len(refs) > 12
            or not all(isinstance(x, str) for x in refs)
            or len(set(refs)) != len(refs)
            or any(ref not in allowed for ref in refs)):
        raise Stage1PacketError(f"Invalid or unsupported {kind} references.")
    return list(refs)


def build_stage1_episode_packet(episode: dict[str, Any]) -> dict[str, Any]:
    """Whitelist node packets, source-backed changes, neutral prompts and timeline.

    Every node is reviewed using its OWN t_i cutoff. A relation or computed
    change is knowledge at the LATER timestamp, never at the earlier node.
    This is a model input boundary, not a simulator or verdict.
    """
    if not isinstance(episode, dict) or episode.get("schema") != EPISODE_SCHEMA:
        raise Stage1PacketError("Expected an EpisodeEvidenceV0 record.")
    raw_nodes = episode.get("nodes")
    if not isinstance(raw_nodes, list) or not 2 <= len(raw_nodes) <= MAX_NODES:
        raise Stage1PacketError("An episode requires 2-4 decision nodes.")

    window = episode.get("window")
    if not isinstance(window, dict):
        raise Stage1PacketError("Missing episode window.")
    start, horizon = window.get("start_s"), window.get("stage1_horizon_s")
    if (not _finite(start) or not _finite(horizon)
            or not 5 <= horizon - start <= 20):
        raise Stage1PacketError("Episode window must be a finite 5-20 seconds.")

    nodes: list[dict[str, Any]] = []
    fact_ids: set[str] = set()
    unknown_ids: set[str] = set()
    node_times: dict[str, float] = {}

    for i, node in enumerate(raw_nodes, 1):
        nid = f"N{i}"
        if not isinstance(node, dict) or node.get("node_id") != nid:
            raise Stage1PacketError("Episode node names must be N1...N4 in time order.")
        t = node.get("t0")
        if (not _finite(t) or t < start or t > horizon
                or (nodes and t <= nodes[-1]["t0"])
                or node.get("information_cutoff_s") != t):
            raise Stage1PacketError("Invalid or inconsistent node information cutoff.")
        if bool(node.get("is_primary")) != (i == len(raw_nodes)):
            raise Stage1PacketError("Only the final node may be primary.")
        snapshot = node.get("snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("t0") != t:
            raise Stage1PacketError("Node does not match its DecisionEvidenceV0 snapshot.")
        packet = build_stage1_packet(snapshot)
        if node.get("status") != packet["status"]:
            raise Stage1PacketError("Node status differs from its audited evidence.")
        for record in packet["evidence"]:
            fact_ids.add(f"{nid}/{record['id']}")
        for record in packet["unknowns"]:
            unknown_ids.add(f"{nid}/{record['id']}")
        node_times[nid] = t
        nodes.append({"node_id": nid, "t0": t, "is_primary": i == len(raw_nodes),
                      "status": packet["status"], "packet": packet})

    if nodes[-1]["t0"] != horizon:
        raise Stage1PacketError("Stage 1 horizon must be the primary decision time.")

    statuses = [n["status"] for n in nodes]
    expected_status = ("abstain" if statuses[-1] == "abstain" else
                       "partial" if any(s != "ok" for s in statuses) else "ok")
    if episode.get("status") != expected_status:
        raise Stage1PacketError("Episode status differs from decision nodes.")

    # Reconstruct chronological relations; never pass arbitrary caller text.
    relations = [
        {"from": a["node_id"], "to": b["node_id"], "relation": "precedes",
         "gap_s": round(b["t0"] - a["t0"], 3)}
        for a, b in zip(nodes, nodes[1:])
    ]

    changes: list[dict[str, Any]] = []
    change_ids: set[str] = set()
    raw_changes = episode.get("changes", [])
    if not isinstance(raw_changes, list) or len(raw_changes) > MAX_ITEMS:
        raise Stage1PacketError("Invalid or oversized episode change list.")
    for change in raw_changes:
        if not isinstance(change, dict):
            raise Stage1PacketError("Invalid change record.")
        cid = change.get("id")
        if not isinstance(cid, str) or not CHANGE_ID.fullmatch(cid) or cid in change_ids:
            raise Stage1PacketError("Invalid or duplicate change id.")
        pair = cid[2:].split(".", 1)[0].split("-")
        first, second = pair
        if first not in node_times or second not in node_times or node_times[first] >= node_times[second]:
            raise Stage1PacketError("Invalid chronological change pair.")
        at = change.get("known_at_s")
        if not _finite(at) or at != node_times[second] or at > horizon:
            raise Stage1PacketError("Change is not available at the claimed decision time.")
        refs = _refs(change.get("refs"), fact_ids, "change")
        if any(r.split("/", 1)[0] not in {first, second} for r in refs):
            raise Stage1PacketError("Change references an unrelated node.")
        if not any(r.startswith(first + "/") for r in refs) or not any(
                r.startswith(second + "/") for r in refs):
            raise Stage1PacketError("Change must cite both compared decisions.")
        # Preserve only typed values/units, not free-text model prompts/metadata.
        unit = change.get("unit")
        if unit is not None and (not isinstance(unit, str) or len(unit) > 50):
            raise Stage1PacketError("Invalid change unit.")
        item = {"id": cid, "refs": refs, "value": _copy_json_safe(change.get("value")),
                "unit": unit, "known_at_s": at,
                "verification": "derived_value_needs_independent_math_check"}
        changes.append(item)
        change_ids.add(cid)

    timeline: list[dict[str, Any]] = []
    timeline_ids: set[str] = set()
    raw_timeline = episode.get("timeline", [])
    if not isinstance(raw_timeline, list) or len(raw_timeline) > MAX_ITEMS:
        raise Stage1PacketError("Invalid or oversized episode timeline.")
    for event in raw_timeline:
        if not isinstance(event, dict):
            raise Stage1PacketError("Invalid timeline event.")
        event_id, typ, t = event.get("id"), event.get("type"), event.get("t")
        if (not isinstance(event_id, str) or not TIMELINE_ID.fullmatch(event_id)
                or event_id in timeline_ids or typ not in CONTEXT_EVENT_TYPES
                or not event_id.startswith(f"T.{typ}.")
                or not _finite(t) or not start <= t <= horizon):
            raise Stage1PacketError("Invalid, duplicate or future episode timeline item.")
        allowed_fields = CONTEXT_EVENT_TYPES[typ]
        filtered = {"id": event_id, "type": typ, "t": t}
        for field in allowed_fields:
            if field not in event:
                continue
            value = event[field]
            if field.endswith("Id"):
                if value not in SLOTS | {"unknown_player"}:
                    raise Stage1PacketError("Timeline event leaks an un-anonymized player ID.")
            elif value is not None and (not isinstance(value, str) or len(value) > 40):
                raise Stage1PacketError("Invalid pad metadata.")
            filtered[field] = value
        timeline.append(_copy_json_safe(filtered))
        timeline_ids.add(event_id)

    unknowns = [{"id": f"{node['node_id']}/{u['id']}",
                 "what": u["what"], "why": u["why"]}
                for node in nodes for u in node["packet"]["unknowns"]]
    raw_unknowns = episode.get("unknowns", [])
    if not isinstance(raw_unknowns, list) or len(raw_unknowns) > MAX_ITEMS:
        raise Stage1PacketError("Invalid or oversized episode unknown list.")
    unknowns_by_id = {u["id"] for u in unknowns}
    for unknown in raw_unknowns:
        if not isinstance(unknown, dict) or not isinstance(unknown.get("id"), str):
            raise Stage1PacketError("Malformed episode uncertainty.")
        uid = unknown["id"]
        if uid in unknowns_by_id:
            continue
        if not uid.startswith("UD.") or uid in fact_ids | change_ids | timeline_ids:
            raise Stage1PacketError("Unknown item has unsupported or conflicting ID.")
        refs = _refs(unknown.get("refs"), unknown_ids, "unknown", allow_empty=True)
        # The actual field is unknown; an unknown cannot establish a positive fact.
        unknowns.append({"id": uid, "refs": refs,
                         "kind": "missing_source_for_derived_change"})
        unknowns_by_id.add(uid)

    hypotheses = []
    hypothesis_ids: set[str] = set()
    raw_hypotheses = episode.get("possible_earlier_contributors", [])
    if not isinstance(raw_hypotheses, list) or len(raw_hypotheses) > 100:
        raise Stage1PacketError("Invalid episode hypothesis list.")
    for h in raw_hypotheses:
        if not isinstance(h, dict):
            raise Stage1PacketError("Malformed episode hypothesis.")
        hid = h.get("id")
        if (not isinstance(hid, str) or not H_ID.fullmatch(hid)
                or hid in hypothesis_ids or h.get("status") != "hypothesis_unverified"
                or h.get("concerns_node") != nodes[-1]["node_id"]):
            raise Stage1PacketError("Invalid episode hypothesis.")
        earlier = h.get("earlier_node")
        if earlier is not None and earlier not in node_times:
            raise Stage1PacketError("Hypothesis references unknown earlier decision.")
        refs = _refs(h.get("evidence_refs"), fact_ids | change_ids | timeline_ids, "hypothesis")
        hypotheses.append({"id": hid, "earlier_node": earlier,
                           "concerns_node": nodes[-1]["node_id"],
                           "evidence_refs": refs, "status": "hypothesis_unverified"})
        hypothesis_ids.add(hid)

    return {
        "schema": SCHEMA,
        "status": expected_status,
        "window": {"start_s": start, "stage1_horizon_s": horizon},
        "nodes": nodes,
        "relations": relations,
        "changes": changes,
        "timeline": timeline,
        "unknowns": unknowns,
        "possible_earlier_contributors": hypotheses,
        "tactical_merit_calculated": False,
        "retrospective_present": False,
    }

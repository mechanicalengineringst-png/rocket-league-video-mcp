"""A fail-closed, pre-decision-only packet for a future coaching reasoner.

The input is Claude's DecisionEvidenceV0, which intentionally includes a
*separate* retrospective section. Never give the entire input record to a
Stage 1 model: explicit whitelisting is essential to prevent hindsight leakage.

This module makes NO coaching verdicts, cloud calls or causal predictions.
"""
from __future__ import annotations

import json
import math
from typing import Any

from .decision_evidence import SCHEMA

STAGE1_SCHEMA = "Stage1DecisionPacketV0"
SLOTS = frozenset(("focus", "teammate", "opponent_1", "opponent_2"))
TEAMS = frozenset(("blue", "orange", None))
KINDS = frozenset(("observation", "derived", "context_event"))


class Stage1PacketError(ValueError):
    """The evidence record cannot be safely released to a decision-time model."""


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _copy_json_safe(value: Any) -> Any:
    """Copy without retaining mutable input references or invalid JSON floats."""
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise Stage1PacketError("Non-JSON or non-finite evidence field.") from exc


def build_stage1_packet(decision_record: dict[str, Any]) -> dict[str, Any]:
    """Serialize only recorded facts at/before t0; never include future labels.

    Deliberately excludes 'selection' (a selection algorithm may use future
    outcomes), 'source' (may include a raw file path), 'rules' supplied by the
    caller, and *all* 'retrospective' material. This is a data boundary, not
    a prompt asking a model to ignore something it already received.
    """
    if not isinstance(decision_record, dict) or decision_record.get("schema") != SCHEMA:
        raise Stage1PacketError("Expected a DecisionEvidenceV0 record.")
    t0 = decision_record.get("t0")
    if not _finite(t0) or t0 < 0:
        raise Stage1PacketError("Decision time must be finite and nonnegative.")
    status = decision_record.get("status")
    if status not in ("ok", "partial", "abstain"):
        raise Stage1PacketError("Unknown decision evidence status.")

    raw_slots = decision_record.get("slots", {})
    if not isinstance(raw_slots, dict) or not raw_slots:
        raise Stage1PacketError("Missing anonymous player slots.")
    slots: dict[str, dict[str, Any]] = {}
    for slot, meta in raw_slots.items():
        if slot not in SLOTS or not isinstance(meta, dict) or meta.get("team") not in TEAMS:
            raise Stage1PacketError("Invalid or identifying player-slot data.")
        slots[slot] = {"team": meta["team"]}

    raw_evidence = decision_record.get("evidence")
    raw_unknowns = decision_record.get("unknowns")
    if not isinstance(raw_evidence, list) or not isinstance(raw_unknowns, list):
        raise Stage1PacketError("Evidence and unknowns must be lists.")
    if len(raw_evidence) > 1000 or len(raw_unknowns) > 1000:
        raise Stage1PacketError("Evidence packet exceeds safe bounds.")

    evidence: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for source_item in raw_evidence:
        if not isinstance(source_item, dict):
            raise Stage1PacketError("Evidence item is not a record.")
        item_id = source_item.get("id")
        if not isinstance(item_id, str) or not item_id.startswith(("E.", "C.")):
            raise Stage1PacketError("Non-predecision evidence id present.")
        if item_id in seen_ids or source_item.get("kind") not in KINDS:
            raise Stage1PacketError("Duplicate id or unknown evidence kind.")
        seen_ids.add(item_id)
        source_time = source_item.get("source_time_s")
        if source_time is not None and (not _finite(source_time) or source_time > t0 + 1e-8):
            raise Stage1PacketError("Future or invalid evidence timestamp.")
        required = ("id", "kind", "value", "unit", "source_time_s", "provenance")
        if any(k not in source_item for k in required):
            raise Stage1PacketError("Evidence item is missing required provenance.")
        if not isinstance(source_item["provenance"], list) or not all(
            isinstance(p, str) for p in source_item["provenance"]
        ):
            raise Stage1PacketError("Invalid provenance tags.")
        item = {k: source_item[k] for k in required}
        if isinstance(source_item.get("note"), str):
            item["note"] = source_item["note"]
        safe = _copy_json_safe(item)
        # Context event timestamps are inside their values, not only source_time.
        if item_id.startswith("C.") and isinstance(safe["value"], dict) and "t" in safe["value"]:
            event_time = safe["value"]["t"]
            if not _finite(event_time) or event_time > t0 + 1e-8:
                raise Stage1PacketError("Future event embedded in context evidence.")
        # Claude anonymizes event player IDs to slots. Do not ship a raw ID if
        # a caller accidentally injects one into a pre-decision event.
        if item_id.startswith("C.") and isinstance(safe["value"], dict):
            for key in ("playerId", "attackerId", "victimId"):
                if key in safe["value"] and safe["value"][key] not in SLOTS | {"unknown_player"}:
                    raise Stage1PacketError("Unanonymized actor identifier in context event.")
        evidence.append(safe)

    unknowns: list[dict[str, str]] = []
    for source_item in raw_unknowns:
        if not isinstance(source_item, dict) or not isinstance(source_item.get("id"), str):
            raise Stage1PacketError("Malformed unknown-item record.")
        if not source_item["id"].startswith("U.") or source_item["id"] in seen_ids:
            raise Stage1PacketError("Unknown item must have a unique U. identifier.")
        for field in ("what", "why"):
            if not isinstance(source_item.get(field), str):
                raise Stage1PacketError("Unknown item needs a textual explanation.")
        seen_ids.add(source_item["id"])
        unknowns.append({k: source_item[k] for k in ("id", "what", "why")})

    output: dict[str, Any] = {
        "schema": STAGE1_SCHEMA,
        "source_schema": SCHEMA,
        "cutoff_s": t0,
        "status": status,
        "slots": slots,
        "evidence": evidence,
        "unknowns": _copy_json_safe(unknowns),
        "decision_merit_calculated": False,
    }

    frame_time = decision_record.get("frame_time_s")
    if status != "abstain":
        if not _finite(frame_time) or not 0 <= t0 - frame_time <= 0.1500001:
            raise Stage1PacketError("Missing or stale decision frame.")
        output["frame_time_s"] = frame_time
    elif raw_evidence:
        raise Stage1PacketError("Abstained record cannot claim positive evidence.")

    raw_context = decision_record.get("context")
    if raw_context is not None:
        if not isinstance(raw_context, dict):
            raise Stage1PacketError("Invalid preceding context.")
        context = {k: raw_context[k] for k in
                   ("window_s", "from_s", "event_ids", "excluded") if k in raw_context}
        if (not _finite(context.get("window_s")) or context["window_s"] <= 0
                or not _finite(context.get("from_s")) or context["from_s"] > t0
                or not isinstance(context.get("event_ids"), list)):
            raise Stage1PacketError("Invalid context window.")
        if any(not isinstance(i, str) or not i.startswith("C.") or i not in seen_ids
               for i in context["event_ids"]):
            raise Stage1PacketError("Context references nonexistent or retrospective evidence.")
        output["context"] = _copy_json_safe(context)

    observations = decision_record.get("not_observable", [])
    if not isinstance(observations, list) or len(observations) > 30 or not all(
        isinstance(n, str) for n in observations
    ):
        raise Stage1PacketError("Unobservable-information list is invalid.")
    output["not_observable"] = list(observations)
    # Do not add 'selection', 'source', or 'retrospective' here, even if a
    # later schema revision adds fields that appear harmless.
    return output

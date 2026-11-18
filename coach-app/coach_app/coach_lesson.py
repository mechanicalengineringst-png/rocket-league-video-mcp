"""CoachLessonV0: Stage 1 evidence-bound lesson composition.

This module deliberately separates *software-valid references and numbers*
from tactical correctness. Generated prose can never label itself verified.
Use build_lesson_from_episode() on an internally built EpisodeEvidenceV0;
raw replay metadata/outcomes must NOT be supplied to the language model.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from .claim_verifier import CLAIM_TYPES, NUMBER_IN_PROSE, verify_stage1_claims
from .episode_stage1 import SCHEMA as PACKET_SCHEMA, build_stage1_episode_packet
from .stage1_packet import Stage1PacketError, _copy_json_safe
from .tactical_coach_adapter import build_verified_tactical_context, build_verified_experimental_decision_state_v1

SCHEMA = "CoachLessonV0"
DRAFT_SCHEMA = "CoachDraftV0"
ALLOWED_GRADES = frozenset(("undetermined", "defensible", "risky", "tradeoff"))
SECTIONS = frozenset((
    "observation", "tactical_context", "alternative",
    "earlier_factor", "takeaway", "uncertainty",
))
MODEL_CLAIM_KEYS = frozenset((
    "claim_id", "node_id", "section", "epistemic_type",
    "temporal_scope", "cited_evidence_ids", "predicate_checks", "text", "tactical_claim_ids",
))
REF = re.compile(r"^(N[1-4])/(E\.[A-Za-z0-9_.-]+|C\.[A-Za-z0-9_.-]+|U\.[A-Za-z0-9_.-]+)$")
MODEL_ID = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.:-]{0,63}$")
CERTAINTY = re.compile(r"\b(?:guaranteed|definitely|inevitably|certainly|must have caused|caused the goal)\b", re.I)


class CoachDraftError(ValueError):
    """Invalid model-output schema or impossible Stage 1 evidence request."""


def _finite(v: Any) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


def _fmt_scalar(v: int | float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def _packet_commitment(packet: dict[str, Any]) -> str:
    data = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _baseline_facts(primary: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic source-grounded observations; no tactical verdict or EV."""
    inner = primary["packet"]
    if inner["status"] == "abstain":
        return []
    indexed = {e["id"]: e for e in inner["evidence"]}
    out = []
    for slot in ("focus", "teammate"):
        ref = f"E.{slot}.boost"
        item = indexed.get(ref)
        if item is None or not _finite(item.get("value")):
            continue
        claim = {
            "claim_id": f"base-{slot}-boost",
            "epistemic_type": "OBSERVED_FACT",
            "temporal_scope": "PRE_DECISION",
            "cited_evidence_ids": [ref],
            "predicate_checks": [{"evidence_id": ref, "value_path": [], "relation": "eq",
                                   "stated_value": item["value"]}],
            "text": f"Recorded {slot} boost was {_fmt_scalar(item['value'])}.",
        }
        verified = verify_stage1_claims(inner, [claim])["results"][0]
        if verified["status"] == "rejected":
            continue
        out.append({
            "claim_id": claim["claim_id"], "node_id": primary["node_id"],
            "section": "observation", "epistemic_type": "OBSERVED_FACT",
            "text": claim["text"], "evidence_refs": [f"{primary['node_id']}/{ref}"],
            "predicate_checks": claim["predicate_checks"],
            "review_status": verified["status"],
            "review_warnings": verified["warnings"],
            "author": "deterministic_template",
        })
    return out


def _checked_draft_claim(claim: dict[str, Any], packet: dict[str, Any], tactical_context: dict[str, Any]) -> tuple[dict | None, list[str]]:
    """Validate global citations, their availability AT the target node and facts.

    Each node's own claim verifier enforces source types and typed numeric
    predicates. Episode-level refs (D./T./H.) can provide *context* but can
    never certify English claims or unverified computed quantities.
    """
    errors: list[str] = []
    if not isinstance(claim, dict) or set(claim) - MODEL_CLAIM_KEYS:
        return None, ["Unsupported or malformed model claim fields."]
    claim_id, nid = claim.get("claim_id"), claim.get("node_id")
    if not isinstance(claim_id, str) or not MODEL_ID.fullmatch(claim_id):
        errors.append("Invalid claim ID.")
    if not isinstance(nid, str) or nid not in {n["node_id"] for n in packet["nodes"]}:
        return None, errors + ["Claim references an unknown decision node."]
    target = next(n for n in packet["nodes"] if n["node_id"] == nid)
    typ, section, scope = claim.get("epistemic_type"), claim.get("section"), claim.get("temporal_scope")
    if not isinstance(typ, str) or typ not in CLAIM_TYPES:
        errors.append("Unknown epistemic category.")
    if not isinstance(section, str) or section not in SECTIONS:
        errors.append("Invalid lesson section.")
    if scope != "PRE_DECISION":
        errors.append("Only Stage 1 claims are supported.")
    if typ in ("TACTICAL_INFERENCE", "HYPOTHETICAL_ALTERNATIVE", "PRACTICAL_TEACHING_RECOMMENDATION") and CERTAINTY.search(str(claim.get("text", ""))):
        errors.append("Tactical hypotheses must not assert guaranteed or certain outcomes.")
    text = claim.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 900 or any(
            ord(c) < 32 and c not in "\n\t" for c in text if isinstance(text, str)):
        errors.append("Claim text must be concise, nonempty and plain.")
        text = ""
    refs = claim.get("cited_evidence_ids")
    if (not isinstance(refs, list) or not 1 <= len(refs) <= 12
            or any(not isinstance(r, str) for r in refs)
            or len(set(refs)) != len(refs)):
        return None, errors + ["A claim requires unique, explicit source IDs."]
    preds = claim.get("predicate_checks", [])
    if not isinstance(preds, list) or len(preds) > 12:
        return None, errors + ["Invalid typed predicate list."]

    # Tactical claim IDs are a *second evidence link*, not a proof that the
    # English recommendation is strategically sound. They must be produced by
    # the verified local TacticalOptions engine, at the cited decision only.
    tactical_refs = claim.get("tactical_claim_ids", [])
    if (not isinstance(tactical_refs, list) or len(tactical_refs) > 8
            or not all(isinstance(v, str) for v in tactical_refs)
            or len(set(tactical_refs)) != len(tactical_refs)):
        return None, errors + ["Malformed tactical claim IDs."]
    tactical_index = {c["claim_id"]: c for c in tactical_context.get("claims", [])}
    for tactical_ref in tactical_refs:
        cited_claim = tactical_index.get(tactical_ref)
        if cited_claim is None or cited_claim["node_id"] != nid:
            errors.append("Tactical claim ID does not belong to this decision.")
            continue
        if not any(source in refs for source in cited_claim["evidence_refs"]):
            errors.append("Tactical claim is not linked to its underlying cited evidence.")
        if (cited_claim["epistemic_type"] == "UNKNOWN_INFORMATION"
                and typ != "UNKNOWN_INFORMATION"):
            errors.append("An unknown tactical claim cannot support a positive assertion.")

    by_node: dict[str, list[str]] = {}
    checks_by_node: dict[str, list[dict[str, Any]]] = {}
    extra_refs: list[str] = []
    cited_known_fact = False
    cited_unknown = False
    for ref in refs:
        match = REF.fullmatch(ref)
        if match:
            source_node, local = match.groups()
            source = next(n for n in packet["nodes"] if n["node_id"] == source_node)
            if source["t0"] > target["t0"]:
                errors.append("An earlier decision cannot cite later node evidence.")
            by_node.setdefault(source_node, []).append(local)
            if local.startswith("U."):
                cited_unknown = True
            else:
                cited_known_fact = True
        elif ref.startswith("D."):
            change = next((c for c in packet["changes"] if c["id"] == ref), None)
            if change is None or change["known_at_s"] > target["t0"]:
                errors.append("Unknown or not-yet-known episode change.")
            if typ == "OBSERVED_FACT":
                errors.append("A derived episode change cannot be claimed as a direct observation.")
            extra_refs.append(ref)
        elif ref.startswith("T."):
            event = next((e for e in packet["timeline"] if e["id"] == ref), None)
            if event is None or event["t"] > target["t0"]:
                errors.append("Unknown or future episode event.")
            extra_refs.append(ref)
        elif ref.startswith("H."):
            hypothesis = next((h for h in packet["possible_earlier_contributors"] if h["id"] == ref), None)
            if hypothesis is None:
                errors.append("Unknown earlier-contributor hypothesis.")
            if typ in ("OBSERVED_FACT", "PHYSICALLY_ESTIMATED_FEASIBILITY"):
                errors.append("A hypothesis cannot prove a fact or physical feasibility.")
            if CERTAINTY.search(text):
                errors.append("Unverified contributor may not be stated as a certain cause.")
            extra_refs.append(ref)
        elif ref.startswith("UD."):
            if not any(u["id"] == ref for u in packet["unknowns"]):
                errors.append("Unknown episode uncertainty reference.")
            if typ != "UNKNOWN_INFORMATION":
                errors.append("An unknown cannot establish a positive assertion.")
            cited_unknown = True
            extra_refs.append(ref)
        else:
            errors.append("Unsupported or non-predecision citation.")
    if typ == "UNKNOWN_INFORMATION" and cited_known_fact:
        errors.append("Unknown-information claim cannot cite known observations as proof.")
    if typ != "UNKNOWN_INFORMATION" and cited_unknown:
        errors.append("Missing information cannot support a positive tactical claim.")
    if typ != "UNKNOWN_INFORMATION" and not cited_known_fact:
        # D. numbers are derived but not independently recalculated in V0;
        # H. hypotheses and timeline items alone are also insufficient.
        errors.append("A positive claim needs at least one direct node fact.")
    if typ == "UNKNOWN_INFORMATION" and preds:
        errors.append("Unknown information cannot supply a numeric fact.")

    for pred in preds:
        if not isinstance(pred, dict) or not isinstance(pred.get("evidence_id"), str):
            errors.append("Malformed typed predicate.")
            continue
        match = REF.fullmatch(pred["evidence_id"])
        if match is None or match.group(2).startswith("U.") or pred["evidence_id"] not in refs:
            errors.append("Predicate must cite a known node fact in the claim.")
            continue
        source_node, local = match.groups()
        checks_by_node.setdefault(source_node, []).append({
            **{k: v for k, v in pred.items() if k != "evidence_id"}, "evidence_id": local,
        })

    checked: list[dict[str, Any]] = []
    warnings: list[str] = []
    for source in packet["nodes"]:
        sid = source["node_id"]
        if sid not in by_node:
            continue
        subclaim = {
            "claim_id": claim_id if isinstance(claim_id, str) else "malformed",
            "epistemic_type": typ,
            "temporal_scope": scope,
            "cited_evidence_ids": by_node[sid],
            "predicate_checks": checks_by_node.get(sid, []),
            # text intentionally omitted: a sentence may cite *several* nodes;
            # its complete numeric scan happens below against ALL checked facts.
        }
        try:
            verified = verify_stage1_claims(source["packet"], [subclaim])["results"][0]
        except (TypeError, ValueError, KeyError, Stage1PacketError):
            errors.append("Cited node evidence failed verification.")
            continue
        if verified["status"] == "rejected":
            errors.extend(verified["errors"])
        else:
            checked.extend({
                **p, "evidence_id": f"{sid}/{p['evidence_id']}"
            } for p in verified["verified_predicates"])
            warnings.extend(verified["warnings"])

    # Even if all cited measurements are correct, a persuasive sentence can
    # be tactically false. This is a numeric contradiction screen ONLY.
    cleaned = re.sub(r"\b50\s*/\s*50\b|\b\d+v\d+\b|\b\d+(?:st|nd|rd|th)\b", "", text, flags=re.I)
    numeric_values = [p["stated_value"] for p in checked if _finite(p["stated_value"])]
    for token in NUMBER_IN_PROSE.findall(cleaned):
        if not any(math.isclose(float(token), v, abs_tol=1e-8) for v in numeric_values):
            errors.append("Numerical statement lacks a matching checked source predicate.")
            break
    if errors:
        return None, list(dict.fromkeys(errors))

    return {
        "claim_id": claim_id, "node_id": nid, "section": section,
        "epistemic_type": typ, "text": text.strip(),
        "evidence_refs": list(refs), "predicate_checks": checked,
        "tactical_claim_ids": list(tactical_refs),
        "review_status": "needs_semantic_review",
        "review_warnings": list(dict.fromkeys(warnings + [
            "Evidence matching does not establish tactical correctness or English entailment.",
        ])),
        "author": "model_proposal",
    }, []


def build_lesson_from_episode(episode: dict[str, Any], *, model_draft: dict[str, Any] | None = None,
                              experimental_tactical_v1: bool = False) -> dict[str, Any]:
    """Make a usable, timestamped lesson; no model calls or future outcomes.

    model_draft is a candidate structured proposal, never granted authority.
    Invalid individual claims are discarded and reported, not shown as facts.
    """
    if experimental_tactical_v1 and model_draft is not None:
        raise CoachDraftError("Experimental V1 is deterministic-only and cannot enter the model prompt.")
    packet = build_stage1_episode_packet(episode)
    tactical_context = build_verified_tactical_context(packet)
    experimental_v1 = (
        build_verified_experimental_decision_state_v1(packet)
        if experimental_tactical_v1 else None
    )
    primary = packet["nodes"][-1]
    status = packet["status"]
    base_claims = _baseline_facts(primary)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    assessment = "undetermined"
    mode = "deterministic_baseline"

    if model_draft is not None:
        mode = "model_proposal"
        if not isinstance(model_draft, dict) or model_draft.get("schema") != DRAFT_SCHEMA:
            raise CoachDraftError("Model did not return the CoachDraftV0 contract.")
        if set(model_draft) - {"schema", "assessment", "claims"}:
            raise CoachDraftError("Model returned unsupported top-level fields.")
        proposed_grade = model_draft.get("assessment")
        if not isinstance(proposed_grade, str) or proposed_grade not in ALLOWED_GRADES:
            raise CoachDraftError("Invalid tactical assessment.")
        claims = model_draft.get("claims")
        if not isinstance(claims, list) or len(claims) > 12:
            raise CoachDraftError("Expected up to 12 typed claims.")
        seen = set()
        for i, claim in enumerate(claims):
            cid = claim.get("claim_id") if isinstance(claim, dict) else None
            if not isinstance(cid, str) or cid in seen:
                rejected.append({"index": i, "reason": "Missing or duplicate claim id."})
                continue
            seen.add(cid)
            checked, errors = _checked_draft_claim(claim, packet, tactical_context)
            if status == "abstain" and checked and checked["epistemic_type"] != "UNKNOWN_INFORMATION":
                checked, errors = None, ["Primary decision lacks usable evidence; positive verdict abstained."]
            if checked:
                accepted.append(checked)
            else:
                rejected.append({"index": i, "reason": "; ".join(errors)[:250] or "Evidence rejected."})
        tactical = [c for c in accepted if c["epistemic_type"] in (
            "TACTICAL_INFERENCE", "HYPOTHETICAL_ALTERNATIVE",
            "PRACTICAL_TEACHING_RECOMMENDATION",
        )]
        if tactical and status != "abstain":
            assessment = proposed_grade

    # All model-generated statements, even successful source matches, remain
    # explicitly unverified for tactical meaning. The deterministic baseline
    # is a source-backed observation display, never a coach-quality grade.
    return {
        "schema": SCHEMA,
        "stage": "predecision",
        "mode": mode,
        "decision": {
            "node_id": primary["node_id"], "t0_s": primary["t0"],
            "episode_start_s": packet["window"]["start_s"],
            "status": status,
            "other_decisions": [
                {"node_id": n["node_id"], "t0_s": n["t0"], "status": n["status"]}
                for n in packet["nodes"][:-1]
            ],
        },
        "assessment": {"grade": assessment, "status": (
            "model_hypothesis_not_expert_validated" if assessment != "undetermined"
            else "no_verified_tactical_verdict")},
        "claims": base_claims + accepted,
        "tactical_options": tactical_context,  # uncalibrated V0 menu, NOT an expert verdict
        **({"experimental_decision_state_v1": experimental_v1} if experimental_tactical_v1 else {}),
        "earlier_factors": [
            {"hypothesis_id": h["id"], "earlier_node": h["earlier_node"],
             "evidence_refs": h["evidence_refs"], "status": "hypothesis_unverified"}
            for h in packet["possible_earlier_contributors"]
        ],
        "uncertainties": [
            {"id": u["id"], "what": u.get("what", "Unknown episode change"),
             "why": u.get("why", "Required source is unavailable")}
            for u in packet["unknowns"] if u["id"].startswith(primary["node_id"] + "/")
        ][:20],
        "not_observable": list(primary["packet"].get("not_observable", [])),
        "validation": {
            "stage1_packet_sha256": _packet_commitment(packet),
            "accepted_model_claims": len(accepted),
            "rejected_model_claims": rejected,
            "semantic_tactical_accuracy_verified": False,
            "future_outcomes_used": False,
            "note": "Evidence-checking and numeric agreement do not validate strategic merit.",
        },
        "followup_supported": True,
    }


def answer_evidence_followup(episode: dict[str, Any], question: str) -> dict[str, Any]:
    """Local, deterministic evidence-navigation response, NOT semantic chat.

    The user can ask freely; this version responds with relevant trusted source
    references or explicit inability. A future approved model may compose prose.
    """
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
        raise ValueError("Follow-up question must be 1-500 characters.")
    packet = build_stage1_episode_packet(episode)
    node = packet["nodes"][-1]
    q = question.lower()
    indexed = {e["id"]: e for e in node["packet"]["evidence"]}
    if any(s in q for s in ("boost", "pad", "resource")):
        refs = [f"{node['node_id']}/{key}" for key in ("E.focus.boost", "E.teammate.boost") if key in indexed]
        topic = "boost"
    elif any(s in q for s in ("teammate", "cover", "spacing", "rotation")):
        refs = [f"{node['node_id']}/{key}" for key in ("E.teammate.position", "E.cover.teammate")
                if key in indexed]
        topic = "teammate_support"
    elif any(s in q for s in ("earlier", "before", "cause", "root", "decision")):
        refs = [h["id"] for h in packet["possible_earlier_contributors"][:5]]
        topic = "earlier_contributors"
    elif any(s in q for s in ("challenge", "shadow", "50", "alternative", "option")):
        refs = [f"{node['node_id']}/{key}" for key in ("E.reach.focus", "E.reach.opponent_1")
                if key in indexed]
        topic = "feasible_options"
    else:
        refs, topic = [], "not_supported"
    return {
        "schema": "CoachFollowupV0", "mode": "local_evidence_navigation",
        "topic": topic, "related_refs": refs,
        "answer": (
            "These are the recorded sources relevant to your question. They do not, "
            "by themselves, establish which tactical option was best."
            if refs else "The available decision-time evidence does not support a reliable answer to that question."
        ),
        "stage1_packet_sha256": _packet_commitment(packet),
        "semantic_answer_verified": False,
        "model_called": False,
    }


def lookup_episode_evidence(episode: dict[str, Any], evidence_refs: list[str]) -> dict[str, Any]:
    """Resolve user-selected global citation IDs without any retrospective data.

    Provides actual, anonymized, recorded source values for the frontend's
    evidence inspector. H. prompts are *questions*, D. deltas are marked math
    unverified, and U./UD. are missing information, never factual support.
    """
    if (not isinstance(evidence_refs, list) or not 1 <= len(evidence_refs) <= 20
            or not all(isinstance(ref, str) and 1 <= len(ref) <= 160 for ref in evidence_refs)
            or len(set(evidence_refs)) != len(evidence_refs)):
        raise ValueError("Expected 1-20 unique global evidence references.")
    packet = build_stage1_episode_packet(episode)
    index: dict[str, dict[str, Any]] = {}
    for node in packet["nodes"]:
        nid = node["node_id"]
        for source in node["packet"]["evidence"]:
            ref = f"{nid}/{source['id']}"
            index[ref] = {
                "id": ref, "category": "observed_or_estimated_node_fact",
                "node_id": nid, "decision_time_s": node["t0"],
                "kind": source["kind"], "value": source["value"],
                "unit": source["unit"], "source_time_s": source["source_time_s"],
                "provenance": source["provenance"],
                "meaning_verified": False,
            }
        for unknown in node["packet"]["unknowns"]:
            ref = f"{nid}/{unknown['id']}"
            index[ref] = {
                "id": ref, "category": "unknown",
                "node_id": nid, "decision_time_s": node["t0"],
                "what": unknown["what"], "why": unknown["why"],
                "factual_support": False,
            }
    for delta in packet["changes"]:
        index[delta["id"]] = {
            "id": delta["id"], "category": "derived_episode_change",
            "value": delta["value"], "unit": delta["unit"],
            "known_at_s": delta["known_at_s"], "source_refs": delta["refs"],
            "verification": delta["verification"],
            "meaning_verified": False,
        }
    for event in packet["timeline"]:
        index[event["id"]] = {
            **event, "category": "anonymized_predecision_event",
            "meaning_verified": False,
        }
    for hypothesis in packet["possible_earlier_contributors"]:
        index[hypothesis["id"]] = {
            "id": hypothesis["id"], "category": "unverified_contributor_hypothesis",
            "earlier_node": hypothesis["earlier_node"],
            "evidence_refs": hypothesis["evidence_refs"],
            "status": "hypothesis_unverified",
            "established_cause": False,
        }
    for unknown in packet["unknowns"]:
        if unknown["id"].startswith("UD."):
            index[unknown["id"]] = {
                "id": unknown["id"], "category": "unknown_episode_change",
                "source_refs": unknown["refs"], "factual_support": False,
            }
    missing = [ref for ref in evidence_refs if ref not in index]
    if missing:
        raise ValueError("One or more source IDs do not exist in this predecision episode.")
    return {
        "schema": "CoachEvidenceLookupV0",
        "stage": "predecision",
        "stage1_packet_sha256": _packet_commitment(packet),
        "records": _copy_json_safe([index[ref] for ref in evidence_refs]),
        "retrospective_exposed": False,
    }


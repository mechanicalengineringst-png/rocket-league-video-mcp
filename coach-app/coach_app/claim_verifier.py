"""Verify typed pre-decision coaching assertions against Claude's actual evidence IDs.

This is a *deterministic evidence/predicate gate*, not an AI semantic entailment
model and not proof that tactical advice is sound. Free-form prose ALWAYS remains
unverified until a separate semantic/human review.

Input: Stage1DecisionPacketV0 from stage1_packet.build_stage1_packet().
Output: one status per candidate claim, errors and source-backed predicates.
No LLM calls, no future outcomes, no fabricated precision.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .stage1_packet import STAGE1_SCHEMA, Stage1PacketError

CLAIM_TYPES = frozenset({
    "OBSERVED_FACT",
    "PHYSICALLY_ESTIMATED_FEASIBILITY",
    "TACTICAL_INFERENCE",
    "HYPOTHETICAL_ALTERNATIVE",
    "UNKNOWN_INFORMATION",
    "PRACTICAL_TEACHING_RECOMMENDATION",
})
RELATIONS = frozenset(("eq", "gte", "lte"))
# These tolerances compare a stated scalar with a *stored source value*, not
# with physical reality. Physical estimation error belongs to evidence itself.
SCALAR_ROUNDING_TOLERANCE = {
    "0-100": 0.05, "boost": 0.05,
    "s": 0.005, "s after t0": 0.005,
    "uu": 0.5, "uu/s": 0.5,
    "unit vector": 0.005,
}
NUMBER_IN_PROSE = re.compile(r"(?<![A-Za-z0-9_.])[-+]?\d+(?:\.\d+)?(?![A-Za-z0-9_.])")
MAX_CLAIMS = 40
MAX_CITATIONS = 12
MAX_PREDICATES = 15


def _finite_number(value: Any) -> bool:
    return type(value) in (float, int) and math.isfinite(value)


def _extract_value(item: dict[str, Any], path: list[str | int]) -> Any:
    """Read a scalar from evidence.value; refuse arbitrary paths or objects."""
    current: Any = item["value"]
    if len(path) > 5:
        raise ValueError("Predicate value path exceeds maximum depth.")
    for step in path:
        if type(step) is int and step >= 0 and type(current) is list and step < len(current):
            current = current[step]
        elif (type(step) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", step)
              and type(current) is dict and step in current):
            current = current[step]
        else:
            raise ValueError("Predicate references unavailable evidence value.")
    if current is None or type(current) not in (float, int, bool, str):
        raise ValueError("Predicate must resolve to an observed scalar, not an object or unknown.")
    if _finite_number(current) or type(current) in (bool, str):
        return current
    raise ValueError("Predicate resolved to a non-finite number.")


def _check_predicate(predicate: dict, cited: set[str],
                     sources: dict[str, dict]) -> tuple[dict[str, Any] | None, str | None]:
    """Support equality and conservative scalar inequalities only."""
    if not isinstance(predicate, dict):
        return None, "Malformed predicate."
    ref = predicate.get("evidence_id")
    path = predicate.get("value_path", [])
    relation = predicate.get("relation")
    stated = predicate.get("stated_value")
    if not isinstance(ref, str) or ref not in cited or ref not in sources:
        return None, "Predicate citation is absent, unknown or retrospective."
    if not isinstance(path, list) or any(type(p) not in (str, int) for p in path):
        return None, "Predicate value_path must be a list of keys/indices."
    if relation not in RELATIONS:
        return None, "Only eq, gte and lte predicate relations are supported."
    if type(stated) not in (str, bool, int, float) or (_finite_number(stated) is False
                                                      and type(stated) in (int, float)):
        return None, "Predicate stated_value must be a finite scalar."
    item = sources[ref]
    try:
        actual = _extract_value(item, path)
    except ValueError as exc:
        return None, str(exc)
    if relation == "eq":
        if _finite_number(actual) and _finite_number(stated):
            tol = SCALAR_ROUNDING_TOLERANCE.get(item.get("unit"), 0.0)
            correct = abs(actual - stated) <= tol
        else:
            correct = type(actual) is type(stated) and actual == stated
    else:
        if not _finite_number(actual) or not _finite_number(stated):
            return None, "Inequality predicates require numeric scalars."
        # Predicates say the observed actual value is >= / <= the stated bound.
        correct = actual >= stated if relation == "gte" else actual <= stated
    if not correct:
        return None, f"Predicate contradicts {ref}: source {actual!r}, claimed {relation} {stated!r}."
    return {
        "evidence_id": ref, "value_path": list(path), "source_value": actual,
        "relation": relation, "stated_value": stated,
        "source_time_s": item["source_time_s"], "unit": item["unit"],
    }, None


def verify_stage1_claims(packet: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Check exact citations and typed predicates, never mark AI prose verified.

    Status:
      rejected              impossible, unsupported or structurally invalid claim
      needs_semantic_review  cited facts/predicates pass, but natural-language
                             meaning or tactical merit has NOT been established
      structured_fact_verified  machine-readable scalar assertions on direct
                             source observations pass; no free-form claim text
    """
    if not isinstance(packet, dict) or packet.get("schema") != STAGE1_SCHEMA:
        raise Stage1PacketError("Claim verifier requires a Stage1DecisionPacketV0.")
    t0 = packet.get("cutoff_s")
    if not _finite_number(t0) or t0 < 0:
        raise Stage1PacketError("Invalid cutoff.")
    if packet.get("status") not in ("ok", "partial", "abstain"):
        raise Stage1PacketError("Invalid packet status.")
    if not isinstance(claims, list) or len(claims) > MAX_CLAIMS:
        raise ValueError(f"Expected <= {MAX_CLAIMS} claim records.")

    evidence = packet.get("evidence")
    unknowns = packet.get("unknowns")
    if not isinstance(evidence, list) or not isinstance(unknowns, list):
        raise Stage1PacketError("Packet evidence/unknown lists are invalid.")
    sources: dict[str, dict] = {}
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise Stage1PacketError("Malformed evidence record.")
        ref = item["id"]
        if not ref.startswith(("E.", "C.")) or ref in sources:
            raise Stage1PacketError("Invalid or duplicated pre-decision citation.")
        when = item.get("source_time_s")
        if when is not None and (not _finite_number(when) or when > t0 + 1e-8):
            raise Stage1PacketError("Evidence has an invalid or post-decision timestamp.")
        if not isinstance(item.get("provenance"), list):
            raise Stage1PacketError("Missing provenance metadata.")
        sources[ref] = item
    unknown_ids = {u["id"] for u in unknowns
                   if isinstance(u, dict) and isinstance(u.get("id"), str)
                   and u["id"].startswith("U.")}

    results: list[dict[str, Any]] = []
    seen_claims = set()
    for pos, claim in enumerate(claims):
        errors: list[str] = []
        warnings: list[str] = []
        checks: list[dict] = []
        if not isinstance(claim, dict):
            results.append({"claim_id": f"at_index_{pos}", "status": "rejected",
                            "errors": ["Claim must be a record."], "verified_predicates": []})
            continue

        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", claim_id):
            errors.append("Invalid claim_id.")
            claim_id = f"at_index_{pos}"
        if claim_id in seen_claims:
            errors.append("Duplicate claim_id.")
        seen_claims.add(claim_id)

        claim_type = claim.get("epistemic_type")
        if claim_type not in CLAIM_TYPES:
            errors.append("Unsupported epistemic_type.")
        if claim.get("temporal_scope") != "PRE_DECISION":
            errors.append("Stage 1 cannot judge post-decision or timeless claims as predecision facts.")

        citations = claim.get("cited_evidence_ids")
        if not isinstance(citations, list) or not (1 <= len(citations) <= MAX_CITATIONS) or not all(
            isinstance(x, str) for x in citations
        ):
            errors.append("Expected 1–12 evidence IDs.")
            citations = []
        if len(citations) != len(set(citations)):
            errors.append("Duplicate citations.")
        cited = set(citations)
        for ref in citations:
            if ref.startswith("R."):
                errors.append(f"Retrospective citation forbidden: {ref}.")
            elif ref in unknown_ids:
                if claim_type != "UNKNOWN_INFORMATION":
                    errors.append(f"Unknown {ref} cannot establish a factual claim.")
            elif ref in sources:
                if claim_type == "UNKNOWN_INFORMATION":
                    errors.append(f"Known fact {ref} is not an unknown citation.")
                if claim_type == "OBSERVED_FACT" and sources[ref].get("kind") not in (
                    "observation", "context_event"
                ):
                    errors.append(f"Derived estimate {ref} cannot be called a direct observation.")
                if "stale_possible" in sources[ref].get("provenance", []):
                    warnings.append(f"{ref} may be stale.")
                if "freshness_unverified" in sources[ref].get("provenance", []):
                    warnings.append(f"{ref} freshness unverified.")
            else:
                errors.append(f"Nonexistent citation: {ref}.")

        if packet["status"] == "abstain" and claim_type != "UNKNOWN_INFORMATION":
            errors.append("Abstained decision cannot support a positive claim.")
        if claim_type == "PHYSICALLY_ESTIMATED_FEASIBILITY" and not any(
            ref in sources and sources[ref].get("kind") == "derived"
            and any("kinematic_model" in str(p) for p in sources[ref].get("provenance", []))
            for ref in citations
        ):
            errors.append("Physical feasibility requires a derived kinematic source.")

        predicates = claim.get("predicate_checks", [])
        if not isinstance(predicates, list) or len(predicates) > MAX_PREDICATES:
            errors.append("Invalid predicate_checks list.")
            predicates = []
        for pred in predicates:
            match, error = _check_predicate(pred, cited, sources)
            if error:
                errors.append(error)
            else:
                checks.append(match)

        prose = claim.get("text")
        if prose is not None and (not isinstance(prose, str) or len(prose) > 1200):
            errors.append("Free-form claim text is invalid or too long.")
        elif isinstance(prose, str):
            # A very limited *numeric* guard, not a natural-language verifier:
            # any explicit prose numeral must be among the cited typed checks.
            # Always require semantic review even when all numbers match.
            allowed_nums = [c["stated_value"] for c in checks if _finite_number(c["stated_value"])]
            for token in NUMBER_IN_PROSE.findall(prose):
                number = float(token)
                if not any(abs(number - v) <= 1e-8 for v in allowed_nums):
                    errors.append(f"Unverified numeric assertion in text: {token}.")
        if not errors and isinstance(prose, str):
            warnings.append("Free-form sentence meaning has not been semantically verified.")
        if not errors and claim_type not in ("OBSERVED_FACT",):
            warnings.append("Tactical interpretation, hypothetical consequence or unknown requires human/semantic review.")
        if not errors and claim_type == "OBSERVED_FACT" and not predicates:
            warnings.append("No scalar checks supplied; attribution alone does not establish factual entailment.")

        status = ("rejected" if errors else
                  "structured_fact_verified" if (claim_type == "OBSERVED_FACT" and not isinstance(prose, str)
                                                  and len(checks) > 0 and not warnings) else
                  "needs_semantic_review")
        results.append({
            "claim_id": claim_id, "status": status, "errors": errors,
            "warnings": list(dict.fromkeys(warnings)),
            "verified_predicates": checks,
        })

    return {
        "schema": "ClaimVerificationReportV0",
        "stage1_cutoff_s": t0,
        "all_structural_checks_passed": all(x["status"] != "rejected" for x in results),
        "all_factual_text_verified": False,  # no semantic verifier exists in V0
        "results": results,
    }

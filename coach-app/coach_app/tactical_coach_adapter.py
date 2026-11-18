"""Verified, narrow Round 9 TacticalOptionsV0 -> coach/model contract.

Never pass raw replay records, unrestricted Stage1 episode metadata, or
unvalidated tactical summaries directly to a language model. The tactical
engine's stances are uncalibrated deterministic hypotheses, NOT expert grades.
"""
from __future__ import annotations

import math
from typing import Any

from .claim_verifier import verify_stage1_claims
from .episode_stage1 import SCHEMA as EPISODE_SCHEMA
from .stage1_packet import Stage1PacketError, _copy_json_safe
from .tactical_options import ACTIONS, POLICY, SCHEMA as TACTICAL_SCHEMA, TacticalOptionsError, analyze_tactical_options

SCHEMA = "CoachTacticalContextV0"
STANCE = frozenset(("defensible", "defensible_with_conditions", "questionable",
                    "not_available", "not_assessable"))
FEASIBILITY = frozenset(("yes", "no", "unknown"))
RISK = frozenset(("elevated", "not_elevated", "unknown"))
MAX_CLAIMS = 180


def _valid_finite(v: Any) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


def build_verified_tactical_context(packet: dict[str, Any]) -> dict[str, Any]:
    """Generate options from Stage 1 only and validate EACH supporting claim.

    The structural/numeric verifier cannot prove that the generated strategic
    stance, English explanation, or hypothetical alternative is tactically
    sound. We preserve the boundary explicitly in our return value.
    """
    if not isinstance(packet, dict) or packet.get("schema") != EPISODE_SCHEMA:
        raise Stage1PacketError("Tactical integration requires a sanitized Stage1EpisodePacketV0.")
    nodes = packet.get("nodes")
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 4:
        raise Stage1PacketError("Tactical integration requires 2–4 audited decisions.")
    primary = nodes[-1]
    if primary.get("is_primary") is not True:
        raise Stage1PacketError("Primary coaching decision is not the final decision.")
    node_id, t0 = primary.get("node_id"), primary.get("t0")
    raw = analyze_tactical_options(packet, focus_node_id=node_id)
    if (not isinstance(raw, dict) or raw.get("schema") != TACTICAL_SCHEMA
            or raw.get("node_id") != node_id or raw.get("t0") != t0
            or raw.get("information_cutoff_s") != t0
            or raw.get("uses_retrospective") is not False
            or raw.get("picks_single_best") is not False
            or raw.get("status") not in ("ok", "partial", "abstain")):
        raise TacticalOptionsError("Tactical engine did not return a safe decision-time assessment.")
    policy = raw.get("policy")
    if not isinstance(policy, dict) or policy.get("version") != POLICY["version"]:
        raise TacticalOptionsError("Unrecognized tactical-policy version.")
    source_claims = raw.get("claims")
    if not isinstance(source_claims, list) or len(source_claims) > MAX_CLAIMS:
        raise TacticalOptionsError("Missing or oversized tactical claim list.")
    ids = [c.get("claim_id") for c in source_claims if isinstance(c, dict)]
    if len(ids) != len(source_claims) or len(set(ids)) != len(ids):
        raise TacticalOptionsError("Duplicate or malformed tactical claim IDs.")
    if any(not isinstance(c, str) or not c.startswith(node_id + ".c") for c in ids):
        raise TacticalOptionsError("Tactical claims must belong to the primary decision.")
    report = verify_stage1_claims(primary["packet"], source_claims)
    if not report["all_structural_checks_passed"] or len(report["results"]) != len(source_claims):
        raise TacticalOptionsError("Tactical engine produced an unsupported source claim.")
    if any(check.get("status") == "rejected" for check in report["results"]):
        raise TacticalOptionsError("A tactical option asserted invalid or retrospective evidence.")
    verified_by_id = {r["claim_id"]: r for r in report["results"]}
    claims = []
    for original in source_claims:
        cid = original["claim_id"]
        refs = original.get("cited_evidence_ids", [])
        if not isinstance(refs, list) or any(not isinstance(r, str) or not r.startswith(("E.", "C.", "U."))
                                                  for r in refs):
            raise TacticalOptionsError("Unsupported tactical evidence citation.")
        prose = original.get("text")
        if not isinstance(prose, str) or len(prose) > 1200:
            raise TacticalOptionsError("Invalid tactical claim text.")
        claims.append({
            "claim_id": cid, "node_id": node_id,
            "epistemic_type": original["epistemic_type"],
            "text": prose, "evidence_refs": [f"{node_id}/{r}" for r in refs],
            "review_status": verified_by_id[cid]["status"],
            "semantic_accuracy_verified": False,
            "review_warnings": verified_by_id[cid].get("warnings", []),
        })
    allowed = set(ids)
    opts = raw.get("options")
    if not isinstance(opts, list):
        raise TacticalOptionsError("Tactical options must form a list.")
    if raw["status"] == "abstain":
        if opts or source_claims:
            raise TacticalOptionsError("An abstention cannot expose actionable tactical claims.")
    elif len(opts) != len(ACTIONS):
        raise TacticalOptionsError("Missing action families from tactical analysis.")
    known_actions = set()
    formatted_options = []
    for option in opts:
        if not isinstance(option, dict):
            raise TacticalOptionsError("Malformed tactical action family.")
        action, feas, stance, risk = (option.get("action"), option.get("physically_feasible"),
                                      option.get("strategic_stance"), option.get("defensive_risk"))
        if action not in ACTIONS or action in known_actions or feas not in FEASIBILITY or stance not in STANCE or risk not in RISK:
            raise TacticalOptionsError("Unknown or duplicate tactical action or stance.")
        known_actions.add(action)
        if (feas == "no" and stance != "not_available") or (feas == "unknown" and stance != "not_assessable"):
            raise TacticalOptionsError("Tactical stance contradicts physical availability.")
        references = {}
        for field in ("feasibility_claims", "supporting_claims", "limiting_claims",
                      "severe_limit_claims", "team_context_claims"):
            values = option.get(field)
            if (not isinstance(values, list) or len(values) > 25
                    or any(not isinstance(v, str) or v not in allowed for v in values)):
                raise TacticalOptionsError("Tactical action cites a nonexistent verified claim.")
            references[field] = list(dict.fromkeys(values))
        unknown_deps = option.get("depends_on_unobservable")
        if (not isinstance(unknown_deps, list) or len(unknown_deps) > 12 or
                any(not isinstance(x, str) or len(x) > 100 for x in unknown_deps)):
            raise TacticalOptionsError("Invalid action awareness dependencies.")
        if type(option.get("depends_on_teammate")) is not bool:
            raise TacticalOptionsError("Malformed teammate dependency.")
        formatted_options.append({
            "action": action, "physical_feasibility": feas,
            "strategic_stance": stance, "defensive_risk": risk,
            "depends_on_teammate": option["depends_on_teammate"],
            "depends_on_unobservable": unknown_deps,
            **references,
        })
    if raw["status"] != "abstain" and known_actions != set(ACTIONS):
        raise TacticalOptionsError("Tactical option families are incomplete.")
    defensible = [o["action"] for o in formatted_options
                  if o["strategic_stance"] in ("defensible", "defensible_with_conditions")]
    if set(defensible) != set(raw.get("defensible_options", [])):
        raise TacticalOptionsError("Advertised defensible actions are inconsistent with options.")
    earlier = []
    known_h = {h["id"] for h in packet.get("possible_earlier_contributors", [])}
    for h in raw.get("earlier_contributors", []):
        if not isinstance(h, dict) or h.get("hypothesis_id") not in known_h or h.get("status") != "hypothesis_unverified":
            raise TacticalOptionsError("Unsupported earlier-contributor conclusion.")
        actions = h.get("bears_on_actions")
        if not isinstance(actions, list) or any(a not in ACTIONS for a in actions):
            raise TacticalOptionsError("Unsupported contributors/action mapping.")
        earlier.append({"hypothesis_id": h["hypothesis_id"], "earlier_node": h.get("earlier_node"),
                        "bears_on_actions": actions, "status": "hypothesis_unverified"})
    reasons = raw.get("abstain_reasons", [])
    if not isinstance(reasons, list) or any(not isinstance(v, str) or len(v) > 200 for v in reasons):
        raise TacticalOptionsError("Invalid tactical uncertainty reasons.")
    output = {
        "schema": SCHEMA, "node_id": node_id, "decision_time_s": t0,
        "status": raw["status"],
        "calibration": {"status": "uncalibrated_rule_hypothesis",
                        "policy_version": policy["version"], "expert_validated": False,
                        "expected_value_modeled": False, "picks_single_best": False},
        "options": formatted_options, "defensible_options": defensible,
        "claims": claims, "earlier_contributors": earlier, "abstain_reasons": reasons,
        "unknowns": [
            {"id": f"{node_id}/{u['id']}", "what": u["what"], "why": u["why"]}
            for u in primary["packet"]["unknowns"][:20]
        ],
        "validation": {"structural_claims_verified": len(claims),
                       "rejected_tactical_claims": 0,
                       "semantic_tactical_accuracy_verified": False,
                       "retrospective_used": False},
    }
    return _copy_json_safe(output)

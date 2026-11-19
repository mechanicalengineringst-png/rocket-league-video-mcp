"""Optional reasoning-model step for CoachingFindingV1: contract, prompt and fail-closed validator (Round 12).

Where a language model can help: rewording a dense, correct ledger into a short coaching paragraph,
prioritising what matters most, and phrasing the takeaway as a cue a player can remember. Where it
must not act: positions, arrival times, contact mechanics, probabilities, outcomes, or what the
player did. So the model sees only the validated Stage A finding (conditions with their readings,
alternatives with gains/risks, decisive assumptions, allowed numbers) and returns prose that cites
condition ids. The validator rejects anything that introduces a number, a probability, an outcome,
an action the player took, or an unknown id; on rejection the deterministic text is used.

Stage B (retrospective) is a separate request that additionally receives the observed action, the
deterministic verdict and the outcome; its validator rejects grading by outcome and contradicting the
verdict.

No transport is built in: callers pass ``transport`` explicitly (opt-in). ChatGPT's coach_model
transport (PR #39/#41) can be adapted as ``lambda prompt: propose(...)``. Tests use mocks only;
mocked acceptance is NOT evidence of live model quality.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

SCHEMA_A_REQ, SCHEMA_A_RESP = "CoachReasonerStageARequestV1", "CoachReasonerStageAResponseV1"
SCHEMA_B_REQ, SCHEMA_B_RESP = "CoachReasonerStageBRequestV1", "CoachReasonerStageBResponseV1"
MAX_INTERP, MAX_TAKEAWAY, MAX_FEEDBACK = 700, 350, 500
NUM_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
PROBABILITY = re.compile(r"%|\bpercent\b|\bprobab|\bchance[s]?\b|\bodds\b|\blikel(y|ihood)\b|\bexpected goals?\b|\bxg\b", re.I)
OUTCOME_A = re.compile(r"\b(scored|score[sd]? a goal|conceded?|saved|went in|ended up|turned out|afterwards|result(ed)?|"
                       r"the goal that|was punished|got punished|paid off)\b", re.I)
ACTION_A = re.compile(r"\byou (chose|went for|challenged|decided|took|hit|jumped|rotated|whiffed|committed|waited|cleared|shot|passed)\b", re.I)
MECHANICS = re.compile(r"\b(flip reset|ceiling|air ?dribble|musty|flick|wave ?dash|half[- ]flip|bump|demo(lition)?|dribble)\b", re.I)
SYSTEM_A = (
    "You are a Rocket League 2v2 coach writing for an experienced player. You receive a verified decision-time "
    "analysis of one moment. Rewrite it as (1) a short interpretation of the situation and the reasonable options, "
    "and (2) one takeaway cue the player can recognise next time. Rules: use only the conditions, readings and "
    "alternatives given; copy numbers exactly from allowed_numbers or use none; never state probabilities, "
    "percentages or likelihoods; never mention what the player actually did or what happened afterwards (you do not "
    "know); never introduce mechanics, positions or players not in the input; when several options are defensible, "
    "say so; when an assumption is unobservable, say it is unknown. Return JSON only: "
    '{"schema": "CoachReasonerStageAResponseV1", "finding_id": str, "interpretation": str, "takeaway": str, '
    '"cited_conditions": [condition ids]}.'
)
SYSTEM_B = (
    "You add short retrospective feedback to a verified decision-time analysis. You receive the analysis, the "
    "player's observed action (a heuristic label), a deterministic verdict and what happened next. Explain the "
    "verdict in one or two sentences. Rules: never grade the decision by its outcome; never contradict the verdict; "
    "copy numbers only from allowed_numbers; no probabilities. Return JSON only: "
    '{"schema": "CoachReasonerStageBResponseV1", "finding_id": str, "feedback": str}.'
)


class ReasonerContractError(ValueError):
    pass


def build_stage_a_request(finding: dict[str, Any]) -> dict[str, Any]:
    """Whitelisted Stage A material only: no retrospective block, no claims internals, no raw evidence values."""
    if finding.get("schema") != "CoachingFindingV1" or finding.get("stage") != "A_predecision":
        raise ReasonerContractError("Expected a CoachingFindingV1 Stage A finding.")
    if finding.get("status") not in (None, "ok"):
        raise ReasonerContractError("Finding did not pass validation.")
    if finding.get("kind") == "observation_only":
        raise ReasonerContractError("Observation-only findings are not sent to a model.")
    return {
        "schema": SCHEMA_A_REQ, "finding_id": finding["finding_id"],
        "situation": {k: finding["situation"][k] for k in ("class", "label", "why_it_matters")},
        "kind": finding["kind"],
        "conditions": [{"id": c["condition"], "status": c["status"], "reading": c["reading"]} for c in finding["decision_context"]],
        "alternatives": [{"label": a["label"], "status": a["status"],
                          "why": [w["reason"] for w in a["why"]],
                          "ruled_out_because": [x for b in a["ruled_out_because"] for x in b["fails_because"]],
                          **{k: [f"{f['text']} [{f['status']}]" for f in a[k]] for k in ("gains", "preserves", "sacrifices", "risks")}}
                         for a in finding["alternatives"]],
        "assumptions": {"decisive": [{"id": d["condition"], "question": d.get("question"), "current": d["current"]}
                                     for d in finding["assumptions"]["decisive"]],
                        "unobservable": [u["condition"] for u in finding["assumptions"]["unobservable"]]},
        "deterministic": {"interpretation": finding["interpretation"]["text"], "takeaway": finding["takeaway"]["text"]},
        "allowed_numbers": sorted({v["text"] for v in finding["numbers"].values()}),
    }


def _numbers_ok(text: str, allowed: set[str]) -> list[str]:
    t = re.sub(r"\b\d+v\d+\b|50/50|\b2v2\b", "", text)
    return [tok for tok in NUM_RE.findall(t) if tok not in allowed and tok.lstrip("-") not in allowed]


def validate_stage_a_response(request: dict, response: Any) -> list[str]:
    errs = []
    if not isinstance(response, dict) or response.get("schema") != SCHEMA_A_RESP:
        return ["Response is not a CoachReasonerStageAResponseV1 object."]
    if response.get("finding_id") != request["finding_id"]:
        errs.append("finding_id does not match the request.")
    interp, take = response.get("interpretation"), response.get("takeaway")
    if not isinstance(interp, str) or not 20 <= len(interp) <= MAX_INTERP:
        errs.append("interpretation missing or too long.")
    if not isinstance(take, str) or not 10 <= len(take) <= MAX_TAKEAWAY:
        errs.append("takeaway missing or too long.")
    ids = {c["id"] for c in request["conditions"]} | {d["id"] for d in request["assumptions"]["decisive"]}
    cited = response.get("cited_conditions")
    if not isinstance(cited, list) or not cited or any(c not in ids for c in cited):
        errs.append("cited_conditions must be a non-empty list of condition ids from the request.")
    allowed = set(request["allowed_numbers"])
    known_mech = " ".join(json.dumps(request)).lower()
    for name, text in (("interpretation", interp), ("takeaway", take)):
        if not isinstance(text, str):
            continue
        bad = _numbers_ok(text, allowed)
        if bad:
            errs.append(f"{name}: numbers not in the evidence: {', '.join(bad)}.")
        if PROBABILITY.search(text):
            errs.append(f"{name}: probability or likelihood language.")
        if OUTCOME_A.search(text):
            errs.append(f"{name}: refers to outcomes, which Stage A does not know.")
        if ACTION_A.search(text):
            errs.append(f"{name}: states what the player did, which Stage A does not know.")
        for m in MECHANICS.findall(text):
            mech = m[0] if isinstance(m, tuple) else m
            if mech.lower() not in known_mech:
                errs.append(f"{name}: introduces a mechanic not in the evidence ({mech}).")
    return errs


def build_stage_b_request(finding: dict[str, Any], stage_a_text: dict[str, str]) -> dict[str, Any]:
    retro = finding.get("retrospective")
    if not retro or "assessment" not in retro:
        raise ReasonerContractError("No retrospective block.")
    obs = retro["observed_action"]
    nums = {v["text"] for v in finding["numbers"].values()}
    for row in retro["outcome"]["touch_sequence"]:
        nums.add(f"{row['t_after_s']:g}")
    if retro["outcome"]["goal"]:
        nums.add(f"{retro['outcome']['goal']['t_after_s']:g}")
    return {"schema": SCHEMA_B_REQ, "finding_id": finding["finding_id"], "stage_a": stage_a_text,
            "observed_action": {"label": obs["label"], "method": obs.get("method")},
            "verdict": retro["assessment"]["verdict"], "deterministic_feedback": retro["assessment"]["text"],
            "outcome": retro["outcome"], "outcome_independence": retro["outcome_independence"],
            "allowed_numbers": sorted(nums)}


OUTCOME_GRADING = re.compile(r"\b(because|since|as|so)\b[^.]{0,40}\b(goal|scored|conceded|went in|it worked|worked out|failed)\b"
                             r"|\b(the goal|conceding|the outcome|the result) (shows|proves|means)\b", re.I)
NEGATIVE = re.compile(r"\b(mistake|wrong|bad (decision|choice)|should(n't| not)? have|poor (decision|choice)|error)\b", re.I)
POSITIVE = re.compile(r"\b(good|great|correct|right|excellent|smart) (decision|choice|read|call)\b", re.I)


def validate_stage_b_response(request: dict, response: Any) -> list[str]:
    if not isinstance(response, dict) or response.get("schema") != SCHEMA_B_RESP:
        return ["Response is not a CoachReasonerStageBResponseV1 object."]
    errs = []
    if response.get("finding_id") != request["finding_id"]:
        errs.append("finding_id does not match the request.")
    fb = response.get("feedback")
    if not isinstance(fb, str) or not 10 <= len(fb) <= MAX_FEEDBACK:
        return errs + ["feedback missing or too long."]
    bad = _numbers_ok(fb, set(request["allowed_numbers"]))
    if bad:
        errs.append(f"feedback: numbers not in the evidence: {', '.join(bad)}.")
    if PROBABILITY.search(fb):
        errs.append("feedback: probability or likelihood language.")
    if OUTCOME_GRADING.search(fb):
        errs.append("feedback: grades the decision by its outcome.")
    v = request["verdict"]
    if v in ("sound", "defensible_if") and NEGATIVE.search(fb):
        errs.append("feedback: contradicts a sound/defensible verdict.")
    if v in ("questionable", "risky") and POSITIVE.search(fb):
        errs.append("feedback: contradicts a questionable/risky verdict.")
    if v in ("not_assessed", "unclear") and (NEGATIVE.search(fb) or POSITIVE.search(fb)):
        errs.append("feedback: judges an unassessed decision.")
    return errs


def _call(transport: Callable[[dict], Any], system: str, req: dict) -> Any:
    raw = transport({"system": system, "input": req})
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return raw


def run_reasoner(finding: dict[str, Any], transport: Callable[[dict], Any] | None = None) -> dict[str, Any]:
    """Stage A then Stage B. Without an explicit transport, returns the deterministic text (no model)."""
    det_a = {"interpretation": finding["interpretation"]["text"], "takeaway": finding["takeaway"]["text"]}
    out = {"finding_id": finding["finding_id"], "model_called": False, "stage_a": {"mode": "deterministic", **det_a,
                                                                                   "rejections": []}}
    retro = finding.get("retrospective")
    if retro and "assessment" in retro:
        out["stage_b"] = {"mode": "deterministic", "feedback": retro["assessment"]["text"], "rejections": []}
    if transport is None or finding.get("kind") == "observation_only" or finding.get("status") != "ok":
        return out
    req_a = build_stage_a_request(finding)
    out["model_called"] = True
    resp = _call(transport, SYSTEM_A, req_a)
    errs = validate_stage_a_response(req_a, resp)
    if errs:
        out["stage_a"]["rejections"] = errs
    else:
        out["stage_a"] = {"mode": "model_validated", "interpretation": resp["interpretation"], "takeaway": resp["takeaway"],
                          "cited_conditions": resp["cited_conditions"], "rejections": [],
                          "note": "Passed structural, numeric and leakage checks; tactical meaning not semantically verified."}
    if "stage_b" in out:
        req_b = build_stage_b_request(finding, {k: out["stage_a"][k] for k in ("interpretation", "takeaway")})
        resp_b = _call(transport, SYSTEM_B, req_b)
        errs_b = validate_stage_b_response(req_b, resp_b)
        if errs_b:
            out["stage_b"]["rejections"] = errs_b
        else:
            out["stage_b"] = {"mode": "model_validated", "feedback": resp_b["feedback"], "rejections": []}
    return out


async def run_reasoner_async(finding: dict[str, Any], transport) -> dict[str, Any]:
    """Async variant for an async transport (e.g. an httpx-based provider client). Same validation and fallback."""
    results: dict[str, Any] = {}

    async def call(system, req):
        raw = await transport({"system": system, "input": req})
        return json.loads(raw) if isinstance(raw, str) else raw

    # Pre-compute both responses with the async transport, then reuse the sync validation path.
    if transport is None or finding.get("kind") == "observation_only" or finding.get("status") != "ok":
        return run_reasoner(finding, None)
    req_a = build_stage_a_request(finding)
    try:
        results["a"] = await call(SYSTEM_A, req_a)
    except ValueError:
        results["a"] = None
    errs = validate_stage_a_response(req_a, results["a"])
    text_a = ({"interpretation": results["a"]["interpretation"], "takeaway": results["a"]["takeaway"]} if not errs else
              {"interpretation": finding["interpretation"]["text"], "takeaway": finding["takeaway"]["text"]})
    retro = finding.get("retrospective")
    if retro and "assessment" in retro:
        try:
            results["b"] = await call(SYSTEM_B, build_stage_b_request(finding, text_a))
        except ValueError:
            results["b"] = None

    def replay_transport(msg):
        return results.get("a") if msg["input"]["schema"] == SCHEMA_A_REQ else results.get("b")
    return run_reasoner(finding, replay_transport)

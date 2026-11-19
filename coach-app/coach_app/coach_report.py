"""CoachingReportV1: one replay + one player -> ranked, two-stage coaching findings (Round 12, experimental).

Pipeline (each step fails closed for its moment, never for the whole report):

1. ``situations.discover_situations``: decision situations from t0 frames (seven classes).
2. For each situation, the replay is truncated at t0; ``episode_evidence`` -> Stage 1 packet ->
   ``situation_rationale.analyze_situation`` (condition ledger, alternatives, decisive information).
3. ``moment_ranking.rank``: decision-time salience (responsibility, teachability, sufficiency,
   recurrence); never outcomes.
4. ``coaching_findings.build_stage_a`` for selected moments; claims are re-verified with
   ``claim_verifier.verify_stage1_claims`` and numbers checked against the finding's number table.
5. Optional Stage B (``include_retrospective``): observed action and outcome from the full replay,
   attached separately; also used for match-level patterns (actions only, never outcomes).

Nothing here calls a model. ``reasoner_contract`` defines the optional, opt-in model step.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .claim_verifier import verify_stage1_claims
from .coaching_findings import ACTIONS, CLASS_LABEL, build_stage_a, build_stage_b, check_finding_numbers, observe_action
from .episode_evidence import build_episode_evidence
from .episode_stage1 import build_stage1_episode_packet
from .moment_ranking import VERSION as RANK_VERSION
from .moment_ranking import rank
from .situation_rationale import SituationRationaleError, analyze_situation
from .situations import RULE_VERSION, classify_frame, discover_situations

SCHEMA = "CoachingReportV1"
VERSION = "coach-report/0.1"
EPISODE_LOOKBACK_S = 7.0
NODE_OFFSETS_S = (6.0, 3.0)


def prefix(replay: dict[str, Any], t0: float) -> dict[str, Any]:
    """The replay as known at t0: frames and timed events at or before t0 only."""
    return {**replay, "frames": [f for f in replay.get("frames", []) if f["t"] <= t0 + 1e-9],
            "events": [e for e in replay.get("events", []) if isinstance(e.get("t"), (int, float)) and e["t"] <= t0 + 1e-9]}


def analyze_moment(replay: dict[str, Any], focus: str, situation: dict[str, Any], *, ledger: str = "r12") -> dict[str, Any] | None:
    t0 = situation["t0"]
    pre = prefix(replay, t0)
    if not pre["frames"] or t0 - EPISODE_LOOKBACK_S < pre["frames"][0]["t"]:
        return None
    ep = build_episode_evidence(pre, focus, [round(t0 - o, 3) for o in NODE_OFFSETS_S] + [t0], t0 - EPISODE_LOOKBACK_S, t0)
    st1 = build_stage1_episode_packet(ep)
    rat = analyze_situation(st1, pre, situation, ledger=ledger)
    node = next(n for n in st1["nodes"] if n["is_primary"])
    return {"situation": situation, "rationale": rat, "packet": node["packet"]}


def coach_moment(replay: dict[str, Any], focus: str, t0: float, *, include_retrospective: bool = True,
                 finding_id: str = "M1") -> dict[str, Any]:
    """Coach one user-chosen moment: classify the frame at t0, then Stage A (and optionally Stage B)."""
    frames = [f for f in replay.get("frames", []) if f["t"] <= t0 + 1e-9]
    if not frames or t0 - frames[-1]["t"] > 0.15:
        raise ValueError("No frame at the requested time.")
    sit = classify_frame(frames[-1], replay.get("players", []), focus)
    if sit is None:
        return {"schema": "CoachingFindingV1", "finding_id": finding_id, "t0": t0, "status": "no_supported_situation",
                "kind": "observation_only", "experimental": True,
                "reason": "The frame does not match a supported decision situation (or a car or reach estimate is missing)."}
    sit.t0 = t0
    it = analyze_moment(replay, focus, sit.to_dict())
    if it is None:
        raise ValueError("Not enough replay before t0 for an episode.")
    f = build_stage_a(it["situation"], it["rationale"], it["packet"], finding_id=finding_id,
                      salience={"why_selected": ["chosen by the user"], "uses_future": False, "is_merit": False})
    _validate(f, it["packet"])
    if include_retrospective:
        f["retrospective"] = build_stage_b(f, replay, it["situation"])
    return f


def _validate(f: dict, packet: dict) -> None:
    ver = verify_stage1_claims(packet, f["claims"]) if f["claims"] else {"all_structural_checks_passed": True, "results": []}
    bad_numbers = check_finding_numbers(f)
    f["validation"] = {"claims_structurally_valid": ver["all_structural_checks_passed"],
                       "claims_checked": len(ver["results"]),
                       "rejected_claims": [r["claim_id"] for r in ver["results"] if r["status"] == "rejected"],
                       "untraced_numbers": bad_numbers, "future_frames_used": False,
                       "semantic_tactical_accuracy_verified": False}
    if not ver["all_structural_checks_passed"] or bad_numbers:
        f["status"] = "withheld_validation_failed"
        f["takeaway"] = {"kind": "withheld", "text": None, "basis": []}
    else:
        f["status"] = "ok"


def build_coaching_report(replay: dict[str, Any], focus: str, *, max_findings: int = 6,
                          include_retrospective: bool = True, start: float | None = None,
                          end: float | None = None) -> dict[str, Any]:
    if not isinstance(max_findings, int) or not 1 <= max_findings <= 12:
        raise ValueError("max_findings must be an integer from 1 to 12.")
    players = {p["id"]: p for p in replay.get("players", [])}
    if focus not in players:
        raise ValueError("Unknown focus player.")
    sits = discover_situations(replay, focus, start=start, end=end)
    items, skipped = [], Counter()
    for s in sits:
        try:
            it = analyze_moment(replay, focus, s.to_dict())
        except (SituationRationaleError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError):
            skipped["evidence_error"] += 1
            continue
        if it is None:
            skipped["too_early_in_replay"] += 1
            continue
        items.append(it)
    chosen = rank(items, max_findings=max_findings)
    findings = []
    for k, it in enumerate(chosen, 1):
        f = build_stage_a(it["situation"], it["rationale"], it["packet"], finding_id=f"F{k}", salience=it["salience"])
        _validate(f, it["packet"])
        if include_retrospective:
            f["retrospective"] = build_stage_b(f, replay, it["situation"])
        findings.append(f)
    patterns = _patterns(items, replay) if include_retrospective else None
    return {
        "schema": SCHEMA, "version": VERSION, "experimental": True, "expert_validated": False,
        "focus_player_team": players[focus].get("team"),
        "coverage": {"situations_found": len(sits), "situations_analysed": len(items),
                     "by_class": dict(Counter(it["situation"]["situation_class"] for it in items)),
                     "judgment_withheld": sum(it["rationale"].get("judgment") == "withheld" for it in items),
                     "skipped": dict(skipped)},
        "findings": findings, "patterns": patterns,
        "method": {"situations": RULE_VERSION, "ranking": RANK_VERSION, "ranking_uses_future": False,
                   "model_called": False, "retrospective_included": include_retrospective,
                   "stage_separation": "Stage A uses frames and events at or before t0; Stage B (retrospective) is separate "
                                       "and never changes Stage A."},
        "limits": ["Rule-based tactical reasoning; not validated by expert raters.",
                   "Public calibration cohort has unknown rank; thresholds are documented coaching heuristics.",
                   "Aerial, wall and ceiling mechanics are not modelled (observation-only).",
                   "Observed-action labels are movement heuristics, not intent."],
    }


def _patterns(items: list[dict], replay: dict) -> dict[str, Any]:
    """Match-level tendencies: how often the observed action matched the decision-time ledger, per class.

    Uses observed actions (retrospective) but never outcomes. A tendency needs at least 3 instances.
    """
    by = defaultdict(Counter)
    examples = defaultdict(list)
    for it in items:
        cls = it["situation"]["situation_class"]
        if cls == "aerial_or_wall" or it["rationale"].get("judgment") == "withheld":
            by[cls]["not_assessed"] += 1
            continue
        obs = observe_action(replay, it["situation"])
        if obs["label"] is None:
            by[cls]["unlabelled"] += 1
            continue
        fam = obs["family"]
        sts = [v["status"] for a, v in it["rationale"]["actions"].items() if ACTIONS.get(a, {}).get("family") == fam]
        st = next((x for x in ("supported", "conditional", "contested", "refuted") if x in sts), "not_in_ledger")
        by[cls][st] += 1
        if st == "refuted" and it["rationale"].get("supported"):
            key = (cls, obs["label"], tuple(it["rationale"]["supported"][:1]))
            examples[key].append(it["situation"]["t0"])
    tendencies = []
    for (cls, did, better), ts in sorted(examples.items(), key=lambda kv: -len(kv[1])):
        if len(ts) >= 3:
            tendencies.append({"class": cls, "label": CLASS_LABEL[cls], "observed_action": did,
                               "ledger_supported_instead": list(better), "count": len(ts), "t0s": ts[:8],
                               "text": f"{len(ts)} times as '{CLASS_LABEL[cls].lower()}', you chose to "
                                       f"{ACTIONS[did]['label'].lower()} when the decision-time evidence supported "
                                       f"{ACTIONS[better[0]]['label'].lower() if better and better[0] in ACTIONS else better}."})
    return {"by_class": {k: dict(v) for k, v in by.items()}, "tendencies": tendencies,
            "note": "Counts compare observed actions with the decision-time ledger; outcomes are not used."}

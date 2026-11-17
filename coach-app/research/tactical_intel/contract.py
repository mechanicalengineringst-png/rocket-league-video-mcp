"""Assessment contract for experimental tactical models, plus adapters to the blind evaluation.

``TacticalAssessment`` is what any model in this module returns about one
decision point. It keeps four things apart that are easy to blur:

- **prediction**: a measurable quantity with a stated target and horizon;
- **evidence**: decision-time facts, each with provenance and a finalization time <= t0;
- **calibration / uncertainty**: how far to trust the prediction, from held-out data;
- **alternatives**: what comparable humans did, explicitly marked observational.

The verdict policy abstains by default. A predicted outcome is never presented as
proof that an unchosen action was better.

Adapters produce records accepted by the blind evaluator in PR #16
(``replay-lab-blind-benchmark-v1``) without modifying it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .decisions import CHOICES, DecisionPoint

SCHEMA = "replay-lab-tactical-assessment/0.1"
SYSTEM_ID = "claude-retrieval-v0"
MIN_PER_ALTERNATIVE = 30
SITUATION_TYPE = "last_man_defense"

EVIDENCE_TEXT = {
    "focal_ttb": "Defender's estimated time to ball: {v:.2f} s (approximation, not a reachability check)",
    "opp_ttb": "Nearest attacker's estimated time to ball: {v:.2f} s",
    "ttb_adv": "Arrival margin, attacker minus defender: {v:+.2f} s",
    "focal_boost": "Defender boost: {v:.0f}",
    "opp_near_boost": "Nearest attacker boost: {v:.0f}",
    "mate_goalside": "Teammate goal-side of the ball: {b}",
    "mate_depth_rel_ball": "Teammate depth relative to ball: {v:+.0f} uu (negative is behind the ball)",
    "ball_dist_own_goal": "Ball distance to own goal: {v:.0f} uu",
    "score_diff": "Score margin for defending team: {v:+.0f}",
    "seconds_remaining": "Seconds remaining: {v:.0f}",
}


@dataclass
class Alternative:
    choice: str
    neighbour_count: int
    neighbour_share: float
    mean_value_change: float | None
    note: str = "Observational: what comparable players did and what followed. Not a causal estimate."


@dataclass
class TacticalAssessment:
    schema: str
    system_id: str
    decision_id: str
    situation: str
    detector: str
    t0: float
    prediction: dict
    evidence: list[dict]
    calibration: dict
    uncertainty: dict
    alternatives: list[Alternative]
    verdict: str
    verdict_reason: str
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def explanation_payload(self) -> dict:
        """Structured input for a separate language model. It may restate, never add."""
        return {
            "verdict": self.verdict,
            "verdict_reason": self.verdict_reason,
            "facts": [{"key": e["key"], "claim": e["claim"]} for e in self.evidence],
            "comparable_human_choices": [
                {"choice": a.choice, "share": round(a.neighbour_share, 2), "n": a.neighbour_count}
                for a in self.alternatives],
            "limitations": self.limitations,
            "rules_for_narrator": [
                "Do not state any fact that is not in 'facts'.",
                "Do not say an unchosen option was better unless verdict is 'risk'.",
                "Present comparable choices as what other players did, not as advice.",
            ],
        }


def decision_evidence(p: DecisionPoint) -> list[dict]:
    out = []
    for key, tmpl in EVIDENCE_TEXT.items():
        v = p.tactical.get(key)
        if v is None or not np.isfinite(v):
            continue
        claim = tmpl.format(v=v, b="yes" if v > 0.5 else "no")
        out.append({"key": key, "claim": claim, "event_time_s": round(p.t0, 3),
                    "finalized_through_s": round(p.t0, 3), "source": "replay_frame_state",
                    "source_quality": "medium" if "ttb" in key else "high"})
    return out


def assess(p: DecisionPoint, neighbours: list[DecisionPoint], calibration: dict) -> TacticalAssessment:
    """Turn retrieved neighbours into an assessment. Abstains unless support is adequate."""
    evidence = decision_evidence(p)
    n = len(neighbours)
    alts = []
    for c in CHOICES:
        grp = [q for q in neighbours if q.choice == c]
        dv = [q.retrospective["value_change"] for q in grp if np.isfinite(q.retrospective["value_change"])]
        alts.append(Alternative(choice=c, neighbour_count=len(grp),
                                neighbour_share=len(grp) / n if n else 0.0,
                                mean_value_change=float(np.mean(dv)) if dv else None))
    thin = [a.choice for a in alts if a.choice != "unclear" and a.neighbour_count < MIN_PER_ALTERNATIVE]
    verdict, reason = "abstain", ""
    if p.choice == "unclear":
        reason = "The choice could not be read from movement; ask the player what they intended."
    elif thin:
        reason = (f"Too few comparable decisions for {', '.join(thin)} "
                  f"(need {MIN_PER_ALTERNATIVE} each). One moment cannot be graded from its outcome.")
    else:
        reason = ("Support is adequate, but per-moment verdicts are disabled in this prototype; "
                  "aggregate into a habit before judging.")
    return TacticalAssessment(
        schema=SCHEMA, system_id=SYSTEM_ID, decision_id=p.decision_id, situation=SITUATION_TYPE,
        detector=p.detector, t0=p.t0,
        prediction={"target": "team value change over 3 s (own minus opponent five-second scoring threat)",
                    "source": "subtr-actor built-in threat model v7, read at t0 only",
                    "value_at_t0": None},
        evidence=evidence, calibration=calibration,
        uncertainty={"neighbours": n, "min_per_alternative": MIN_PER_ALTERNATIVE},
        alternatives=alts, verdict=verdict, verdict_reason=reason,
        limitations=[
            "Choice labels come from a movement rule that has not been checked against human labels.",
            "Time-to-ball is an approximation; it is not a physics reachability check.",
            "The threat model was trained on ranked doubles; other modes are out of distribution.",
            "Comparable decisions are observational; players chose them for reasons not in the data.",
        ],
    )


def to_blind_case(p: DecisionPoint, case_id: str, replay_group: str) -> dict:
    """A PR #16 case: decision-time evidence only. Retrospective fields are never copied."""
    return {"case_id": case_id, "replay_group": replay_group, "mode": p.mode,
            "situation_type": SITUATION_TYPE, "t0": round(p.t0, 3),
            "pre_decision_evidence": decision_evidence(p)}


def to_blind_prediction(a: TacticalAssessment, case_id: str) -> dict:
    """A PR #16 prediction. Cites evidence keys only when not abstaining."""
    cited = [] if a.verdict == "abstain" else [e["key"] for e in a.evidence][:3]
    return {"case_id": case_id, "system_id": a.system_id, "assessment": a.verdict,
            "cited_evidence": cited, "advice": a.verdict_reason}

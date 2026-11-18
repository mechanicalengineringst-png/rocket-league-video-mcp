"""Small, dependency-free guard for coaching evidence and hindsight leakage.

This is a *data boundary*, not a decision-quality oracle.

A claim about a player's decision may only cite facts that could be
established from observations through the decision timestamp.  Later
outcomes and player-supplied intent remain useful, but are returned
separately so they cannot silently become pre-decision evidence.

Not yet wired into the optional Gemini endpoint.  A future integration
must populate finalized_through_s conservatively from decoder metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Literal

EvidenceKind = Literal["decision_context", "observed_action", "post_decision_outcome", "player_intent"]
EvidenceSource = Literal["replay", "derived", "model", "player_feedback"]
SourceQuality = Literal["high", "medium", "experimental", "unrated"]


@dataclass(frozen=True)
class Evidence:
    """Timestamped support for one atomic claim.

    event_time_s: replay time the described event occurred.
    finalized_through_s: latest replay time whose information was
        necessary to establish the claim.  For a label finalized using
        later frames, this MUST be later than event_time_s.
    kind: separates facts available to a decision-maker from outcome
        descriptions and intent supplied later by the player.
        ``observed_action`` is a retrospective label of what the player did
        (for example a detector's "challenged" classification). It names the
        action under review; it is never pre-decision context and never intent.
    source_quality: confidence category of the *source/measurement*;
        it is NOT the probability a coaching interpretation is correct.
    """

    key: str
    claim: str
    event_time_s: float
    finalized_through_s: float
    kind: EvidenceKind
    source: EvidenceSource
    source_quality: SourceQuality = "unrated"

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError("Evidence key must be nonempty.")
        if not isinstance(self.claim, str) or not self.claim.strip():
            raise ValueError("Evidence claim must be nonempty.")
        for name in ("event_time_s", "finalized_through_s"):
            value = getattr(self, name)
            if not isinstance(value, (float, int)) or isinstance(value, bool) or not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite, nonnegative replay time.")
        if self.finalized_through_s < self.event_time_s:
            raise ValueError("Evidence cannot be finalized before its event occurred.")
        if self.kind not in ("decision_context", "observed_action", "post_decision_outcome", "player_intent"):
            raise ValueError("Invalid evidence kind.")
        if self.source not in ("replay", "derived", "model", "player_feedback"):
            raise ValueError("Invalid evidence source.")
        if self.source_quality not in ("high", "medium", "experimental", "unrated"):
            raise ValueError("Invalid source quality.")


@dataclass(frozen=True)
class EvidencePartition:
    """Keep pre-decision data separate from hindsight and player annotation."""

    decision_context: tuple[Evidence, ...]
    future_derived: tuple[Evidence, ...]
    outcomes: tuple[Evidence, ...]
    player_intent: tuple[Evidence, ...]
    observed_actions: tuple[Evidence, ...] = ()


def partition_evidence(items: Iterable[Evidence], decision_time_s: float) -> EvidencePartition:
    """Partition evidence at a decision-time cutoff.

    Note: this cannot *discover* hidden hindsight leakage.  Producers must
    truthfully set finalized_through_s for every derived label/model feature.
    """
    if not isinstance(decision_time_s, (int, float)) or isinstance(decision_time_s, bool) or not isfinite(decision_time_s) or decision_time_s < 0:
        raise ValueError("Decision time must be finite and nonnegative.")

    decision: list[Evidence] = []
    future: list[Evidence] = []
    outcomes: list[Evidence] = []
    intent: list[Evidence] = []
    actions: list[Evidence] = []
    seen: set[str] = set()

    for item in items:
        if item.key in seen:
            raise ValueError(f"Duplicate evidence key: {item.key}")
        seen.add(item.key)
        if item.kind == "post_decision_outcome":
            outcomes.append(item)
        elif item.kind == "player_intent":
            intent.append(item)
        elif item.kind == "observed_action":
            actions.append(item)
        elif item.event_time_s <= decision_time_s and item.finalized_through_s <= decision_time_s:
            decision.append(item)
        else:
            future.append(item)
    return EvidencePartition(tuple(decision), tuple(future), tuple(outcomes), tuple(intent), tuple(actions))


def require_decision_evidence(
    evidence_keys: Iterable[str],
    items: Iterable[Evidence],
    decision_time_s: float,
) -> tuple[Evidence, ...]:
    """Fail closed if a proposed decision claim cites missing or hindsight evidence.

    This verifies *temporal admissibility and provenance* of references,
    NOT the semantic truth of the model-generated sentence.  Human/decoder
    validation is still needed before labeling a tactical mistake.
    """
    keys = tuple(evidence_keys)
    if not keys:
        raise ValueError("A coaching claim must cite at least one evidence key.")
    if len(set(keys)) != len(keys):
        raise ValueError("A coaching claim must not repeat evidence keys.")
    partition = partition_evidence(items, decision_time_s)
    eligible = {item.key: item for item in partition.decision_context}
    missing_or_future = [key for key in keys if key not in eligible]
    if missing_or_future:
        raise ValueError(
            "Claim cited unknown, retrospective, or future-derived evidence: "
            + ", ".join(missing_or_future)
        )
    return tuple(eligible[key] for key in keys)

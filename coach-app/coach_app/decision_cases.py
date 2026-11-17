"""DecisionCase extraction and evidence-safe tactical coaching representations.

This module provides structured decision-point extraction for Rocket League replays,
anchored to native subtr-actor event streams (kickoff, fifty_fifty, beaten_to_ball,
depth_role, rotation_role, territorial_pressure) and gated against hindsight leakage
via coach_app.evidence.Evidence.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from .evidence import (
    Evidence,
    EvidencePartition,
    partition_evidence,
    require_decision_evidence,
)
from .subtr_replays import _player_key

SituationType = Literal[
    "kickoff_support",
    "kickoff_taker",
    "first_man_challenge",
    "last_man_defense",
    "second_man_support",
    "fifty_fifty_contest",
]

PRE_DECISION_CONTEXT_ALLOWLIST: dict[str, set[str]] = {
    "kickoff_support": {
        "kickoff_index",
        "spawn_position",
        "start_boost",
        "observed_motion_at_t0",
    },
    "first_man_challenge": {
        "mate_distance",
        "mate_relative_depth",
        "defensive_coverage_verified",
        "boost_at_t0",
        "valid_pre_decision_metric",
    },
    "last_man_defense": {
        "dist_to_goal",
        "dist_to_ball",
        "ball_dist",
        "ball_goal_dist",
        "boost_at_t0",
        "is_constrained_boost",
    },
}


@dataclass(frozen=True)
class DecisionCase:
    """A verified tactical decision point with temporal evidence separation.

    All facts known *at or before* t0 are recorded with finalized_through_s <= t0.
    Outcomes resolving *after* t0 are recorded with kind='post_decision_outcome'.
    """

    case_id: str
    replay_id: str
    t0: float
    focus_player_id: str
    focus_player_name: str
    focus_player_team: str
    situation_type: SituationType
    evidence: tuple[Evidence, ...]
    tactical_context: dict[str, Any]
    feasible_alternatives: tuple[str, ...]
    uncertainties: tuple[str, ...]
    provenance: dict[str, Any] = field(default_factory=dict)

    def pre_decision_evidence(self) -> tuple[Evidence, ...]:
        """Return strictly pre-decision observations available at t0."""
        partition = partition_evidence(self.evidence, self.t0)
        return partition.decision_context

    def post_decision_outcomes(self) -> tuple[Evidence, ...]:
        """Return outcomes that resolved strictly after t0."""
        partition = partition_evidence(self.evidence, self.t0)
        return partition.outcomes

    def validate_admissibility(self, cited_keys: Iterable[str]) -> tuple[Evidence, ...]:
        """Verify that a coaching claim cites only eligible pre-decision evidence."""
        return require_decision_evidence(cited_keys, self.evidence, self.t0)

    def sanitized_pre_decision_context(self) -> dict[str, Any]:
        """Return tactical context strictly sanitized of any future timestamps or outcomes via strict allowlist."""
        allowed = PRE_DECISION_CONTEXT_ALLOWLIST.get(self.situation_type, set())
        sanitized = {}
        for k, v in self.tactical_context.items():
            if k not in allowed:
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if "time" in k.lower() and v > self.t0:
                    continue
            sanitized[k] = v
        return sanitized

    def to_eval_dict(self) -> dict[str, Any]:
        """Serialize into ChatGPT PR #16 blind evaluation schema."""
        pre_ev = self.pre_decision_evidence()
        return {
            "case_id": self.case_id,
            "replay_group": self.replay_id,
            "mode": "2v2",
            "situation_type": self.situation_type,
            "t0": round(self.t0, 3),
            "pre_decision_evidence": [
                {
                    "key": e.key,
                    "claim": e.claim,
                    "event_time_s": round(e.event_time_s, 3),
                    "finalized_through_s": round(e.finalized_through_s, 3),
                    "source": e.source,
                    "source_quality": e.source_quality,
                }
                for e in pre_ev
            ],
        }

    def to_llm_payload(self, include_quarantined_outcomes: bool = False) -> dict[str, Any]:
        """Serialize into a structured, evidence-guarded payload for LLM analysis.

        Outcomes are quarantined or withheld so models cannot confound outcome bias
        with decision quality at t0.
        """
        pre_ev = self.pre_decision_evidence()
        outcomes = self.post_decision_outcomes()

        payload: dict[str, Any] = {
            "decision_case_id": self.case_id,
            "decision_time_s": round(self.t0, 3),
            "focus_player": {
                "id": self.focus_player_id,
                "name": self.focus_player_name,
                "team": self.focus_player_team,
            },
            "situation_type": self.situation_type,
            "pre_decision_facts": [
                {
                    "key": e.key,
                    "fact": e.claim,
                    "event_time_s": round(e.event_time_s, 3),
                    "source": e.source,
                }
                for e in pre_ev
            ],
            "tactical_context": self.sanitized_pre_decision_context(),
            "hypothetical_alternatives_to_inspect": list(self.feasible_alternatives),
            "epistemic_uncertainties": list(self.uncertainties),
        }

        if include_quarantined_outcomes and outcomes:
            payload["quarantined_post_decision_outcomes"] = [
                {
                    "key": e.key,
                    "outcome": e.claim,
                    "finalized_time_s": round(e.finalized_through_s, 3),
                    "warning": "DO NOT USE THIS LATER OUTCOME TO JUSTIFY OR CONDEMN THE T0 DECISION",
                }
                for e in outcomes
            ]

        return payload


def _find_car_at_time(
    frames: list[dict],
    target_time: float,
    player_id: str,
    max_lookback_s: float = 0.15,
) -> dict[str, Any] | None:
    """Find the latest car state observed AT OR BEFORE target_time (ft <= target_time).

    Strictly forbids sampling any future frame (ft > target_time) to prevent hindsight leakage.
    """
    if not frames:
        return None
    times = [f.get("t", 0.0) for f in frames]
    idx = bisect.bisect_right(times, target_time) - 1
    if idx < 0:
        return None
    frame = frames[idx]
    ft = frame.get("t", 0.0)
    if ft > target_time:
        return None
    if (target_time - ft) <= max_lookback_s:
        return frame.get("cars", {}).get(player_id)
    return None


def _find_ball_at_time(
    frames: list[dict],
    target_time: float,
    max_lookback_s: float = 0.15,
) -> dict[str, Any] | None:
    """Find the latest ball state observed AT OR BEFORE target_time (ft <= target_time).

    Strictly forbids sampling any future frame (ft > target_time) to prevent hindsight leakage.
    """
    if not frames:
        return None
    times = [f.get("t", 0.0) for f in frames]
    idx = bisect.bisect_right(times, target_time) - 1
    if idx < 0:
        return None
    frame = frames[idx]
    ft = frame.get("t", 0.0)
    if ft > target_time:
        return None
    if (target_time - ft) <= max_lookback_s:
        return frame.get("ball")
    return None


def extract_kickoff_decision_cases(
    replay_payload: dict[str, Any],
    raw_events: list[dict[str, Any]] | None = None,
) -> list[DecisionCase]:
    """Extract kickoff decision cases for all players using native kickoff events.

    Pre-decision evidence is strictly bounded to observations through t0 (prior to touch).
    Decoder classifications finalized across the kickoff window are partitioned as future-derived.
    """
    cases: list[DecisionCase] = []
    replay_id = replay_payload.get("title", "replay")
    players = {p["id"]: p for p in replay_payload.get("players", [])}
    frames = replay_payload.get("frames", [])

    events_to_scan = raw_events if raw_events is not None else replay_payload.get("events", [])
    kickoff_events = [
        ev for ev in events_to_scan
        if ev.get("meta", {}).get("stream") == "kickoff" or ev.get("type") == "kickoff"
    ]

    for idx, kov in enumerate(kickoff_events):
        payload = kov.get("payload", {})
        if "payload" in payload:
            payload = payload["payload"]

        # Time of kickoff first touch
        t_touch = (
            payload.get("first_touch_time")
            or payload.get("team_zero_taker_touch_time")
            or kov.get("firstTouchTime")
            or kov.get("t")
            or kov.get("meta", {}).get("timing", {}).get("start_time", 0.0)
        )
        t0 = round(max(0.0, t_touch - 0.5), 3)
        t_spawn = round(max(0.0, min(t0, t_touch - 2.5)), 3)

        z_non_takers = payload.get("team_zero_non_takers") or kov.get("teamZeroNonTakers", [])
        o_non_takers = payload.get("team_one_non_takers") or kov.get("teamOneNonTakers", [])
        winning_team_0 = payload.get("winning_team_is_team_0")
        if winning_team_0 is None and "winningTeam" in kov:
            winning_team_0 = (kov.get("winningTeam") == "blue")
        win_strength = payload.get("win_strength_band") or kov.get("winStrength") or "unknown"

        all_non_takers = [(nt, "blue") for nt in z_non_takers] + [(nt, "orange") for nt in o_non_takers]
        for nt, team in all_non_takers:
            full_pid = nt.get("playerId") or _player_key(nt.get("player", {}))
            if not full_pid or full_pid not in players:
                raw_p = nt.get("player", {})
                val = next(iter(raw_p.values()), "") if isinstance(raw_p, dict) and raw_p else ""
                val_str = str(val) if not isinstance(val, dict) else str(val.get("online_id", ""))
                full_pid = next((p for p in players if val_str and val_str in p), None)
            if not full_pid or full_pid not in players:
                continue

            player_info = players[full_pid]
            pname = player_info.get("name", full_pid)
            support_behavior = nt.get("supportBehavior") or nt.get("support_behavior", "unknown")
            spawn_pos = nt.get("spawnPosition") or nt.get("spawn_position", "unknown")

            raw_boost = nt.get("startBoost") if "startBoost" in nt else nt.get("start_boost")
            if raw_boost is not None:
                if raw_boost > 40.0:
                    start_boost = round(min(100.0, max(0.0, (raw_boost / 255.0) * 100.0)), 1)
                else:
                    start_boost = round(float(raw_boost), 1)
                boost_claim = f"{start_boost:.1f}%"
            else:
                start_boost = None
                boost_claim = "unrecorded"

            # Check observed motion at t0 from frames through t0
            car_t0 = _find_car_at_time(frames, t0, full_pid)
            motion_desc = "unknown"
            if car_t0 and car_t0.get("velocity"):
                v = car_t0.get("velocity")
                if isinstance(v, (list, tuple)) and len(v) >= 2:
                    vy = v[1]
                    is_fwd = (team == "blue" and vy > 200) or (team == "orange" and vy < -200)
                    if is_fwd:
                        motion_desc = "moving forward toward midfield"
                    elif (team == "blue" and vy < -200) or (team == "orange" and vy > 200):
                        motion_desc = "reversing or braking toward net"
                    else:
                        motion_desc = "turning laterally or toward defensive corner"

            ev_items: list[Evidence] = [
                Evidence(
                    key="kickoff_spawn",
                    claim=f"{pname} spawned at {spawn_pos} with {boost_claim} boost.",
                    event_time_s=t_spawn,
                    finalized_through_s=t_spawn,
                    kind="decision_context",
                    source="replay",
                    source_quality="high",
                ),
                Evidence(
                    key="kickoff_role",
                    claim=f"{pname} is second man on kickoff, observing teammate approach.",
                    event_time_s=t_spawn,
                    finalized_through_s=t_spawn,
                    kind="decision_context",
                    source="derived",
                    source_quality="high",
                ),
                Evidence(
                    key="kickoff_approach_motion",
                    claim=f"{pname} observed at t0: {motion_desc}.",
                    event_time_s=t0,
                    finalized_through_s=t0,
                    kind="decision_context",
                    source="replay",
                    source_quality="high",
                ),
                # Note: support_behavior was finalized across the whole kickoff through t_touch,
                # so its finalized_through_s must be t_touch. At t0 it is strictly future_derived!
                Evidence(
                    key="kickoff_support_classified",
                    claim=f"Decoder post-hoc classified kickoff support as {support_behavior}.",
                    event_time_s=t0,
                    finalized_through_s=round(t_touch, 3),
                    kind="decision_context",
                    source="derived",
                    source_quality="medium",
                ),
            ]

            # Quarantined post-decision outcome
            if winning_team_0 is not None:
                won = (winning_team_0 and team == "blue") or (not winning_team_0 and team == "orange")
                ev_items.append(
                    Evidence(
                        key="kickoff_outcome",
                        claim=f"Kickoff resolved with team {'winning' if won else 'losing'} (strength: {win_strength}).",
                        event_time_s=round(t_touch + 0.5, 3),
                        finalized_through_s=round(t_touch + 0.5, 3),
                        kind="post_decision_outcome",
                        source="replay",
                        source_quality="high",
                    )
                )

            case = DecisionCase(
                case_id=f"case-kickoff-{idx}-{full_pid}",
                replay_id=replay_id,
                t0=t0,
                focus_player_id=full_pid,
                focus_player_name=pname,
                focus_player_team=team,
                situation_type="kickoff_support",
                evidence=tuple(ev_items),
                tactical_context={
                    "kickoff_index": idx,
                    "spawn_position": spawn_pos,
                    "start_boost": start_boost,
                    "observed_motion_at_t0": motion_desc,
                },
                feasible_alternatives=(
                    "cheat_up_for_dead_ball",
                    "route_to_corner_boost",
                    "hold_defensive_net",
                ),
                uncertainties=(
                    "Pre-match teammate kickoff communication (e.g. 'I got it!', 'Need boost!').",
                    "Opponent non-taker cheat speed and angle.",
                    "Whether kicker intended a dead ball or a controlled corner spill.",
                ),
                provenance={"source": "subtr-actor-native-kickoff", "native_event_id": kov.get("meta", {}).get("id") or kov.get("nativeFrame")},
            )
            cases.append(case)

    return cases


def extract_first_man_challenge_cases(
    replay_payload: dict[str, Any],
    raw_events: list[dict[str, Any]] | None = None,
) -> list[DecisionCase]:
    """Extract first-man challenges & 50/50 decisions with honest depth descriptions.

    Does NOT equate relative depth with verified defensive coverage.
    """
    cases: list[DecisionCase] = []
    replay_id = replay_payload.get("title", "replay")
    players = {p["id"]: p for p in replay_payload.get("players", [])}
    frames = replay_payload.get("frames", [])

    events_to_scan = raw_events if raw_events is not None else replay_payload.get("events", [])
    fifty_events = [
        ev for ev in events_to_scan
        if ev.get("meta", {}).get("stream") == "fifty_fifty" or ev.get("type") == "fifty_fifty"
    ]

    for idx, fev in enumerate(fifty_events):
        if "payload" in fev:
            payload = fev.get("payload", {})
            if "payload" in payload:
                payload = payload["payload"]
        else:
            payload = {}

        is_kickoff = payload.get("is_kickoff") if "is_kickoff" in payload else fev.get("isKickoff", False)
        if is_kickoff:
            continue

        start_time = (
            payload.get("start_time")
            or fev.get("startTime")
            or fev.get("t")
            or fev.get("meta", {}).get("timing", {}).get("start_time", 0.0)
        )
        resolve_time = (
            payload.get("resolve_time")
            or fev.get("resolveTime")
            or (start_time + 0.4)
        )
        winning_team_0 = payload.get("winning_team_is_team_0")
        if winning_team_0 is None and "winningTeam" in fev:
            winning_team_0 = (fev.get("winningTeam") == "blue")

        full_id0 = fev.get("teamZeroPlayerId") or _player_key(payload.get("team_zero_player") or {})
        full_id1 = fev.get("teamOnePlayerId") or _player_key(payload.get("team_one_player") or {})
        if not full_id0 or full_id0 not in players:
            p0_dict = payload.get("team_zero_player") or {}
            v0 = next(iter(p0_dict.values()), "") if isinstance(p0_dict, dict) and p0_dict else ""
            v0_str = str(v0) if not isinstance(v0, dict) else str(v0.get("online_id", ""))
            full_id0 = next((p for p in players if v0_str and v0_str in p), None)
        if not full_id1 or full_id1 not in players:
            p1_dict = payload.get("team_one_player") or {}
            v1 = next(iter(p1_dict.values()), "") if isinstance(p1_dict, dict) and p1_dict else ""
            v1_str = str(v1) if not isinstance(v1, dict) else str(v1.get("online_id", ""))
            full_id1 = next((p for p in players if v1_str and v1_str in p), None)

        participants = [(full_id0, "blue", winning_team_0 is True), (full_id1, "orange", winning_team_0 is False)]

        for pid, team, won in participants:
            if not pid or pid not in players:
                continue
            pinfo = players[pid]
            pname = pinfo.get("name", pid)

            t0 = round(max(0.0, start_time - 0.4), 3)

            car_t0 = _find_car_at_time(frames, t0, pid)
            boost_t0 = car_t0.get("boost") if car_t0 else None

            teammates = [other_id for other_id, other_p in players.items() if other_p.get("team") == team and other_id != pid]
            mate_car = _find_car_at_time(frames, t0, teammates[0]) if teammates else None

            mate_distance = None
            mate_is_back = False
            if car_t0 and mate_car:
                dx = car_t0.get("x", 0) - mate_car.get("x", 0)
                dy = car_t0.get("y", 0) - mate_car.get("y", 0)
                mate_distance = round(math.hypot(dx, dy), 1)
                if team == "blue":
                    mate_is_back = mate_car.get("y", 0) < car_t0.get("y", 0)
                else:
                    mate_is_back = mate_car.get("y", 0) > car_t0.get("y", 0)

            ev_items: list[Evidence] = [
                Evidence(
                    key="challenge_approach",
                    claim=f"{pname} approached a 50/50 challenge as first man.",
                    event_time_s=t0,
                    finalized_through_s=t0,
                    kind="decision_context",
                    source="derived",
                    source_quality="high",
                ),
            ]

            if boost_t0 is not None:
                ev_items.append(
                    Evidence(
                        key="challenge_boost",
                        claim=f"{pname} had {boost_t0:.1f} boost at commitment.",
                        event_time_s=t0,
                        finalized_through_s=t0,
                        kind="decision_context",
                        source="replay",
                        source_quality="high",
                    )
                )

            if mate_distance is not None:
                ev_items.append(
                    Evidence(
                        key="second_man_depth",
                        claim=f"Teammate was {mate_distance:.0f} units away at defensive depth ({'behind' if mate_is_back else 'ahead of'} {pname}).",
                        event_time_s=t0,
                        finalized_through_s=t0,
                        kind="decision_context",
                        source="replay",
                        source_quality="high",
                    )
                )

            # Quarantined post-decision outcome
            ev_items.append(
                Evidence(
                    key="fifty_fifty_outcome",
                    claim=f"50/50 resolved with {pname}'s team {'winning' if won else 'conceding'} possession.",
                    event_time_s=round(resolve_time, 3),
                    finalized_through_s=round(resolve_time, 3),
                    kind="post_decision_outcome",
                    source="replay",
                    source_quality="high",
                )
            )

            case = DecisionCase(
                case_id=f"case-challenge-{idx}-{pid}",
                replay_id=replay_id,
                t0=t0,
                focus_player_id=pid,
                focus_player_name=pname,
                focus_player_team=team,
                situation_type="first_man_challenge",
                evidence=tuple(ev_items),
                tactical_context={
                    "mate_distance": mate_distance,
                    "mate_relative_depth": "behind" if mate_is_back else "ahead",
                    "defensive_coverage_verified": False,
                    "boost_at_t0": boost_t0,
                },
                feasible_alternatives=(
                    "commit_to_50_50_block",
                    "fake_challenge_and_rotate_out",
                    "shadow_and_delay",
                ),
                uncertainties=(
                    "Teammate car orientation, angular velocity, and defensive readiness cannot be verified from depth alone.",
                    "Opponent flip timing and direction.",
                    "Whether teammate called for a challenge or advised shadow.",
                ),
                provenance={"source": "subtr-actor-native-fifty_fifty", "native_event_id": fev.get("meta", {}).get("id") or fev.get("nativeFrame")},
            )
            cases.append(case)

    return cases


def extract_last_man_defense_cases(
    replay_payload: dict[str, Any],
    raw_events: list[dict[str, Any]] | None = None,
) -> list[DecisionCase]:
    """Extract last-man defense decisions where the player is deepest protector of the goal."""
    cases: list[DecisionCase] = []
    replay_id = replay_payload.get("title", "replay")
    players = {p["id"]: p for p in replay_payload.get("players", [])}
    frames = replay_payload.get("frames", [])

    events_to_scan = raw_events if raw_events is not None else replay_payload.get("events", [])
    depth_events = [
        ev for ev in events_to_scan
        if ev.get("meta", {}).get("stream") == "depth_role" or ev.get("type") == "depth_role"
    ]

    for idx, dev in enumerate(depth_events):
        if "payload" in dev:
            payload = dev.get("payload", {})
            if "payload" in payload:
                payload = payload["payload"]
        else:
            payload = {}

        state = payload.get("state") or dev.get("state")
        if state not in ("most_back", "second_man", "last_man", "third_man"):
            continue

        full_pid = dev.get("playerId") or _player_key(payload.get("player") or dev.get("meta", {}).get("primary_player") or {})
        if not full_pid or full_pid not in players:
            raw_p = payload.get("player") or dev.get("meta", {}).get("primary_player") or {}
            val = next(iter(raw_p.values()), "") if isinstance(raw_p, dict) and raw_p else ""
            val_str = str(val) if not isinstance(val, dict) else str(val.get("online_id", ""))
            full_pid = next((p for p in players if val_str and val_str in p), None)
        if not full_pid or full_pid not in players:
            continue

        pinfo = players[full_pid]
        pname = pinfo.get("name", full_pid)
        team = pinfo.get("team", "blue")
        timing = dev.get("meta", {}).get("timing", {})
        t0 = round(payload.get("time") or timing.get("start_time") or dev.get("t", 0.0), 3)

        car = _find_car_at_time(frames, t0, full_pid)
        ball = _find_ball_at_time(frames, t0)
        if not car or not ball:
            continue

        is_defending = (team == "blue" and car.get("y", 0) < -1000) or (team == "orange" and car.get("y", 0) > 1000)
        if not is_defending:
            continue

        goal_y = -5120 if team == "blue" else 5120
        dist_to_goal = math.hypot(car.get("x", 0), car.get("y", 0) - goal_y)
        ball_dist = math.hypot(car.get("x", 0) - ball.get("x", 0), car.get("y", 0) - ball.get("y", 0))

        ball_goal_dist = math.hypot(ball.get("x", 0), ball.get("y", 0) - goal_y)
        if ball_goal_dist > 3500:
            continue

        boost = car.get("boost")

        ev_items: list[Evidence] = [
            Evidence(
                key="last_man_role",
                claim=f"{pname} is last man defending own net at {dist_to_goal:.0f} units from goal line.",
                event_time_s=t0,
                finalized_through_s=t0,
                kind="decision_context",
                source="derived",
                source_quality="high",
            ),
        ]

        if boost is not None:
            ev_items.append(
                Evidence(
                    key="last_man_boost",
                    claim=f"{pname} has {boost:.1f} boost in net defense.",
                    event_time_s=t0,
                    finalized_through_s=t0,
                    kind="decision_context",
                    source="replay",
                    source_quality="high",
                )
            )

        ev_items.append(
            Evidence(
                key="ball_threat",
                claim=f"Ball is {ball_dist:.0f} units away from {pname} and approaching goal area.",
                event_time_s=t0,
                finalized_through_s=t0,
                kind="decision_context",
                source="replay",
                source_quality="high",
            )
        )

        case = DecisionCase(
            case_id=f"case-lastman-{idx}-{full_pid}",
            replay_id=replay_id,
            t0=t0,
            focus_player_id=full_pid,
            focus_player_name=pname,
            focus_player_team=team,
            situation_type="last_man_defense",
            evidence=tuple(ev_items),
            tactical_context={
                "dist_to_goal": round(dist_to_goal, 1),
                "ball_dist": round(ball_dist, 1),
                "dist_to_ball": round(ball_dist, 1),
                "ball_goal_dist": round(ball_goal_dist, 1),
                "boost_at_t0": round(boost, 1) if boost is not None else None,
                "is_constrained_boost": (boost < 20.0) if boost is not None else False,
            },
            feasible_alternatives=(
                "shadow_across_goal_mouth",
                "challenge_early_before_shot",
                "hold_back_post_position",
            ),
            uncertainties=(
                "Opponent strike vector and visual perspective.",
                "Teammate recovery speed off screen.",
            ),
            provenance={"source": "subtr-actor-native-depth_role", "native_event_id": dev.get("meta", {}).get("id") or dev.get("nativeFrame")},
        )
        cases.append(case)

    filtered: list[DecisionCase] = []
    for c in sorted(cases, key=lambda x: x.t0):
        if not any(c.focus_player_id == ex.focus_player_id and abs(c.t0 - ex.t0) < 5.0 for ex in filtered):
            filtered.append(c)

    return filtered


def extract_all_decision_cases(
    replay_payload: dict[str, Any],
    raw_events: list[dict[str, Any]] | None = None,
) -> list[DecisionCase]:
    """Extract all structured decision cases across all tactical categories."""
    kickoffs = extract_kickoff_decision_cases(replay_payload, raw_events)
    challenges = extract_first_man_challenge_cases(replay_payload, raw_events)
    last_man = extract_last_man_defense_cases(replay_payload, raw_events)

    all_cases = kickoffs + challenges + last_man
    all_cases.sort(key=lambda c: c.t0)
    return all_cases

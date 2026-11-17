"""DecisionCase extraction and evidence-safe tactical coaching representations.

This module provides structured decision-point extraction for Rocket League replays,
anchored to native subtr-actor event streams (kickoff, fifty_fifty, beaten_to_ball,
depth_role, rotation_role, territorial_pressure) and gated against hindsight leakage
via coach_app.evidence.Evidence.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from .evidence import (
    Evidence,
    EvidencePartition,
    partition_evidence,
    require_decision_evidence,
)

SituationType = Literal[
    "kickoff_support",
    "kickoff_taker",
    "first_man_challenge",
    "last_man_defense",
    "second_man_support",
    "fifty_fifty_contest",
]


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

    def to_llm_payload(self, include_quarantined_outcomes: bool = False) -> dict[str, Any]:
        """Serialize into a structured, evidence-guarded payload for LLM analysis.

        Outcomes are quarantined in a separately labeled block so models cannot
        confound outcome bias with decision quality.
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
            "tactical_context": self.tactical_context,
            "feasible_alternatives": list(self.feasible_alternatives),
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


def _find_car_at_time(frames: list[dict], target_time: float, player_id: str) -> dict[str, Any] | None:
    """Find the car state closest to target_time in 30Hz resampled frames."""
    if not frames:
        return None
    # Quick binary search for time
    low, high = 0, len(frames) - 1
    best_frame = None
    best_diff = float("inf")
    while low <= high:
        mid = (low + high) // 2
        ft = frames[mid].get("t", 0.0)
        diff = abs(ft - target_time)
        if diff < best_diff:
            best_diff = diff
            best_frame = frames[mid]
        if ft < target_time:
            low = mid + 1
        elif ft > target_time:
            high = mid - 1
        else:
            break
    if best_frame and best_diff <= 0.15:
        return best_frame.get("cars", {}).get(player_id)
    return None


def _find_ball_at_time(frames: list[dict], target_time: float) -> dict[str, Any] | None:
    if not frames:
        return None
    low, high = 0, len(frames) - 1
    best_frame = None
    best_diff = float("inf")
    while low <= high:
        mid = (low + high) // 2
        ft = frames[mid].get("t", 0.0)
        diff = abs(ft - target_time)
        if diff < best_diff:
            best_diff = diff
            best_frame = frames[mid]
        if ft < target_time:
            low = mid + 1
        elif ft > target_time:
            high = mid - 1
        else:
            break
    if best_frame and best_diff <= 0.15:
        return best_frame.get("ball")
    return None


def extract_kickoff_decision_cases(
    replay_payload: dict[str, Any],
    raw_events: list[dict[str, Any]] | None = None,
) -> list[DecisionCase]:
    """Extract kickoff decision cases for all players using native kickoff events."""
    cases: list[DecisionCase] = []
    replay_id = replay_payload.get("title", "replay")
    players = {p["id"]: p for p in replay_payload.get("players", [])}
    frames = replay_payload.get("frames", [])

    # If raw_events not supplied, check replay_payload['events'] or filter
    events_to_scan = raw_events if raw_events is not None else replay_payload.get("events", [])

    kickoff_events = [
        ev for ev in events_to_scan
        if ev.get("meta", {}).get("stream") == "kickoff" or ev.get("type") == "kickoff"
    ]

    for idx, kov in enumerate(kickoff_events):
        payload = kov.get("payload", {})
        if "payload" in payload:
            payload = payload["payload"]

        # Time of kickoff first touch or spawn
        t_touch = (
            payload.get("first_touch_time")
            or payload.get("team_zero_taker_touch_time")
            or kov.get("t")
            or kov.get("meta", {}).get("timing", {}).get("start_time", 0.0)
        )
        t0 = round(max(0.0, t_touch - 0.5), 3)
        t_spawn = round(max(0.0, min(t0, t_touch - 2.5)), 3)

        # Team zero non-takers (cheaters / boost grabbers)
        z_non_takers = payload.get("team_zero_non_takers", [])
        o_non_takers = payload.get("team_one_non_takers", [])
        z_taker = payload.get("team_zero_taker", {})
        o_taker = payload.get("team_one_taker", {})

        winning_team_0 = payload.get("winning_team_is_team_0")
        win_strength = payload.get("win_strength_band", "unknown")

        # Process non-takers (GC2 tactical decision: cheat vs corner boost)
        all_non_takers = [(nt, "blue") for nt in z_non_takers] + [(nt, "orange") for nt in o_non_takers]
        for nt, team in all_non_takers:
            raw_p = nt.get("player", {})
            pid = next(iter(raw_p.values()), None) if isinstance(raw_p, dict) and raw_p else None
            full_pid = next((p for p in players if pid and pid in p), None)
            if not full_pid or full_pid not in players:
                continue

            player_info = players[full_pid]
            pname = player_info.get("name", full_pid)
            support_behavior = nt.get("support_behavior", "unknown")
            spawn_pos = nt.get("spawn_position", "unknown")
            start_boost = nt.get("start_boost", 33.0)

            ev_items: list[Evidence] = [
                Evidence(
                    key="kickoff_spawn",
                    claim=f"{pname} spawned at {spawn_pos} with {start_boost} boost.",
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
                    key="kickoff_support_chosen",
                    claim=f"{pname} committed to {support_behavior} kickoff support.",
                    event_time_s=t0,
                    finalized_through_s=t0,
                    kind="decision_context",
                    source="replay",
                    source_quality="high",
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
                    "support_behavior": support_behavior,
                    "start_boost": start_boost,
                    "is_legitimate_cheat": support_behavior == "cheat",
                },
                feasible_alternatives=(
                    "cheat_up_for_dead_ball",
                    "route_to_corner_boost",
                    "hold_defensive_net",
                ),
                uncertainties=(
                    "Pre-match teammate kickoff communication (e.g. 'I got it!', 'Need boost!').",
                    "Opponent non-taker cheat speed and angle.",
                ),
                provenance={"source": "subtr-actor-native-kickoff", "native_event_id": kov.get("meta", {}).get("id")},
            )
            cases.append(case)

    return cases


def extract_first_man_challenge_cases(
    replay_payload: dict[str, Any],
    raw_events: list[dict[str, Any]] | None = None,
) -> list[DecisionCase]:
    """Extract first-man challenges & 50/50 decisions with support context."""
    cases: list[DecisionCase] = []
    replay_id = replay_payload.get("title", "replay")
    players = {p["id"]: p for p in replay_payload.get("players", [])}
    frames = replay_payload.get("frames", [])

    events_to_scan = raw_events if raw_events is not None else replay_payload.get("events", [])
    fifty_events = [
        ev for ev in events_to_scan
        if ev.get("meta", {}).get("stream") == "fifty_fifty"
    ]

    for idx, fev in enumerate(fifty_events):
        payload = fev.get("payload", {})
        if "payload" in payload:
            payload = payload["payload"]

        # Avoid duplicating kickoffs here; kickoffs have dedicated handler
        if payload.get("is_kickoff"):
            continue

        start_time = payload.get("start_time") or fev.get("t") or fev.get("meta", {}).get("timing", {}).get("start_time", 0.0)
        resolve_time = payload.get("resolve_time") or (start_time + 0.4)
        winning_team_0 = payload.get("winning_team_is_team_0")

        # Determine participants
        p0_dict = payload.get("team_zero_player") or {}
        p1_dict = payload.get("team_one_player") or {}
        id0 = next(iter(p0_dict.values()), None) if isinstance(p0_dict, dict) and p0_dict else None
        id1 = next(iter(p1_dict.values()), None) if isinstance(p1_dict, dict) and p1_dict else None

        full_id0 = next((p for p in players if id0 and id0 in p), None)
        full_id1 = next((p for p in players if id1 and id1 in p), None)

        participants = [(full_id0, "blue", winning_team_0 is True), (full_id1, "orange", winning_team_0 is False)]

        for pid, team, won in participants:
            if not pid or pid not in players:
                continue
            pinfo = players[pid]
            pname = pinfo.get("name", pid)

            # Pre-decision window: 0.5s before contact
            t0 = round(max(0.0, start_time - 0.4), 3)

            # Check car state at t0
            car_t0 = _find_car_at_time(frames, t0, pid)
            boost_t0 = car_t0.get("boost") if car_t0 else None

            # Check teammate state at t0
            teammates = [other_id for other_id, other_p in players.items() if other_p.get("team") == team and other_id != pid]
            mate_car = _find_car_at_time(frames, t0, teammates[0]) if teammates else None

            mate_distance = None
            mate_is_back = False
            if car_t0 and mate_car:
                dx = car_t0.get("x", 0) - mate_car.get("x", 0)
                dy = car_t0.get("y", 0) - mate_car.get("y", 0)
                mate_distance = round(math.hypot(dx, dy), 1)
                # Defending net check (y coordinate relative to own side)
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
                        key="second_man_coverage",
                        claim=f"Teammate was {mate_distance:.0f} units away ({'behind' if mate_is_back else 'ahead of'} {pname}).",
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
                    event_time_s=resolve_time,
                    finalized_through_s=resolve_time,
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
                    "start_time": start_time,
                    "resolve_time": resolve_time,
                    "mate_distance": mate_distance,
                    "mate_is_covering": mate_is_back,
                    "has_backup": mate_is_back and (mate_distance is not None and mate_distance < 3500),
                },
                feasible_alternatives=(
                    "commit_to_50_50_block",
                    "fake_challenge_and_rotate_out",
                    "shadow_and_delay",
                ),
                uncertainties=(
                    "Opponent flip timing and direction.",
                    "Whether teammate called for a challenge or advised shadow.",
                ),
                provenance={"source": "subtr-actor-native-fifty_fifty", "native_event_id": fev.get("meta", {}).get("id")},
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
        if ev.get("meta", {}).get("stream") == "depth_role"
    ]

    # Look for last man transitions during defensive half
    for idx, dev in enumerate(depth_events):
        payload = dev.get("payload", {})
        if "payload" in payload:
            payload = payload["payload"]

        # Only check players labeled as deepest or second man in defense
        state = payload.get("state")
        if state not in ("most_back", "second_man", "last_man", "third_man"):
            continue

        raw_p = payload.get("player") or dev.get("meta", {}).get("primary_player") or {}
        pid = next(iter(raw_p.values()), None) if isinstance(raw_p, dict) and raw_p else None
        full_pid = next((p for p in players if pid and pid in p), None)
        if not full_pid or full_pid not in players:
            continue

        pinfo = players[full_pid]
        pname = pinfo.get("name", full_pid)
        team = pinfo.get("team", "blue")
        timing = dev.get("meta", {}).get("timing", {})
        t0 = round(payload.get("time") or timing.get("start_time") or dev.get("t", 0.0), 3)

        # Check position relative to goal
        car = _find_car_at_time(frames, t0, full_pid)
        ball = _find_ball_at_time(frames, t0)
        if not car or not ball:
            continue

        # In defense? (Blue defends y < 0, Orange defends y > 0)
        is_defending = (team == "blue" and car.get("y", 0) < -1000) or (team == "orange" and car.get("y", 0) > 1000)
        if not is_defending:
            continue

        goal_y = -5120 if team == "blue" else 5120
        dist_to_goal = math.hypot(car.get("x", 0), car.get("y", 0) - goal_y)
        ball_dist = math.hypot(car.get("x", 0) - ball.get("x", 0), car.get("y", 0) - ball.get("y", 0))

        # Only evaluate significant moments (ball within 3500 units of goal)
        ball_goal_dist = math.hypot(ball.get("x", 0), ball.get("y", 0) - goal_y)
        if ball_goal_dist > 3500:
            continue

        boost = car.get("boost", 0.0)

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
            Evidence(
                key="last_man_boost",
                claim=f"{pname} has {boost:.1f} boost in net defense.",
                event_time_s=t0,
                finalized_through_s=t0,
                kind="decision_context",
                source="replay",
                source_quality="high",
            ),
            Evidence(
                key="ball_threat",
                claim=f"Ball is {ball_dist:.0f} units away from {pname} and approaching goal area.",
                event_time_s=t0,
                finalized_through_s=t0,
                kind="decision_context",
                source="replay",
                source_quality="high",
            ),
        ]

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
                "boost": round(boost, 1),
                "is_low_boost": boost < 20,
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
            provenance={"source": "subtr-actor-native-depth_role", "native_event_id": dev.get("meta", {}).get("id")},
        )
        cases.append(case)

    # Deduplicate cases that are within 5 seconds of each other for the same player
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

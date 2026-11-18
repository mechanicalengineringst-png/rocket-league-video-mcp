"""Round 10: select inspectable replay moments without hindsight or tactical grading.

This is SOURCE-OBSERVATION discovery, not mistake detection. Two sampled
moments define each episode: a recorded comparison snapshot and a recorded
state change. Neither is presumed to be a deliberate player decision.
Signals are uncalibrated attention cues, never counterfactuals or causal claims.

Only sampled player/ball states at or before each primary timestamp contribute.
Native event labels, match scores, goals, and post-decision outcomes are not
read. The final candidate list may change as the match progresses because new
candidates compete for a bounded shortlist, but an individual candidate's
metrics cannot change when future frames/events are rewritten.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

from .episode_evidence import EpisodeError, build_episode_evidence

SCHEMA = "EpisodeCandidatesV0"
POLICY = "episode-discovery/0.1"
SAMPLE_SPACING_S = 0.35
COMPARISON_LAG_S = 0.9
MIN_PRIMARY_AGE_S = 5.25
MIN_CANDIDATE_GAP_S = 5.0
MAX_CANDIDATES = 12
MAX_FRAMES = 30000


class DiscoveryError(ValueError):
    """Input cannot be safely evaluated as a time-ordered 2v2 match."""


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _vec(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) != 3 or not all(_finite(v) for v in value):
        return None
    v = tuple(float(x) for x in value)
    return v if max(abs(x) for x in v) <= 100000 else None


def _pos(entity: Any) -> tuple[float, float, float] | None:
    if not isinstance(entity, dict):
        return None
    v = _vec([entity.get("x"), entity.get("y"), entity.get("z")])
    return v if v and abs(v[0]) <= 5000 and abs(v[1]) <= 6000 and -50 <= v[2] <= 2400 else None


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.dist(a, b)


def _ceil_ms(t: float) -> float:
    # Endpoint episode times are normalized to 3 decimals; round UP to make
    # sure the actual supporting sample remains inside the Stage 1 cutoff.
    return round(math.ceil(t * 1000 - 1e-7) / 1000, 3)


def _snap(frame: dict, focus: str, teammate: str) -> dict | None:
    if not isinstance(frame, dict) or not _finite(frame.get("t")):
        return None
    cars = frame.get("cars")
    if not isinstance(cars, dict):
        return None
    mine = cars.get(focus)
    ball = frame.get("ball")
    if not isinstance(mine, dict) or not isinstance(ball, dict):
        return None
    focus_pos, ball_pos = _pos(mine), _pos(ball)
    if not focus_pos or not ball_pos:
        return None
    mate = cars.get(teammate)
    b = mine.get("boost")
    return {
        "t": float(frame["t"]),
        "focus": focus_pos,
        "ball": ball_pos,
        "teammate": _pos(mate),
        "boost": float(b) if _finite(b) and 0 <= b <= 100 else None,
        "velocity": _vec(mine.get("velocity")),
        "forward": _vec(mine.get("forward")),
        "ball_velocity": _vec(ball.get("velocity")),
    }


def _signal(code: str, score: float, unit: str, value: float,
            references: list[str], description: str) -> dict:
    return {
        "signal": code, "salience": round(score, 2),
        "observed_delta": round(value, 2), "unit": unit,
        "evidence_refs": references, "interpretation": description,
        "tactical_quality_verified": False,
    }


def _signals(a: dict, b: dict) -> list[dict]:
    out: list[dict] = []
    boost = (a["boost"], b["boost"])
    if all(v is not None for v in boost):
        spent = boost[0] - boost[1]
        if spent >= 23:
            out.append(_signal("boost_decrease", 2.7 + min(spent, 70) / 25, "boost", -spent,
                ["N1/E.focus.boost", "N2/E.focus.boost"],
                "Observed reduction in boost between samples; efficiency and intent are unknown."))
    va, vb = a["velocity"], b["velocity"]
    if va and vb:
        delta = _distance(va, vb)
        if delta >= 750:
            out.append(_signal("velocity_change", 2.2 + min(delta, 2000) / 700, "uu/s", delta,
                ["N1/E.focus.velocity", "N2/E.focus.velocity"],
                "Observed change in car velocity, not necessarily a chosen maneuver."))
    fa, fb = a["forward"], b["forward"]
    if fa and fb:
        na, nb = math.hypot(fa[0], fa[1]), math.hypot(fb[0], fb[1])
        if na >= 0.4 and nb >= 0.4:
            dot = max(-1, min(1, (fa[0] * fb[0] + fa[1] * fb[1]) / (na * nb)))
            heading_deg = math.degrees(math.acos(dot))
            if heading_deg >= 60:
                out.append(_signal("heading_change", 2 + min(heading_deg, 180) / 45, "degrees", heading_deg,
                    ["N1/E.focus.forward", "N2/E.focus.forward"],
                    "Observed car nose-direction change; camera, intention and controller inputs are unknown."))
    prev_dist = _distance(a["focus"], a["ball"])
    now_dist = _distance(b["focus"], b["ball"])
    closing = prev_dist - now_dist
    if closing >= 600 and now_dist <= 2400:
        out.append(_signal("ball_distance_decrease", 2.5 + min(closing, 2000) / 650, "uu", -closing,
            ["N1/E.focus.position", "N1/E.ball.position",
             "N2/E.focus.position", "N2/E.ball.position"],
            "Observed decrease in focal-car-to-ball distance; no challenge outcome inferred."))
    if a["teammate"] and b["teammate"]:
        before = _distance(a["focus"], a["teammate"])
        after = _distance(b["focus"], b["teammate"])
        difference = after - before
        if abs(difference) >= 1050:
            out.append(_signal("team_spacing_change", 1.8 + min(abs(difference), 2600) / 950, "uu", difference,
                ["N1/E.focus.position", "N1/E.teammate.position",
                 "N2/E.focus.position", "N2/E.teammate.position"],
                "Observed team spacing change; no rotation, fault or defensive coverage inferred."))
    if a["ball_velocity"] and b["ball_velocity"]:
        delta = _distance(a["ball_velocity"], b["ball_velocity"])
        if delta >= 1100 and now_dist <= 2700:
            out.append(_signal("ball_velocity_change", 2 + min(delta, 2400) / 900, "uu/s", delta,
                ["N1/E.ball.velocity", "N2/E.ball.velocity",
                 "N2/E.focus.position", "N2/E.ball.position"],
                "Observed ball velocity change near focus; no toucher or cause inferred."))
    return sorted(out, key=lambda s: (-s["salience"], s["signal"]))


def _frames_through(replay: dict, horizon: float | None) -> tuple[list[dict], float]:
    frames = replay.get("frames")
    if not isinstance(frames, list) or not 2 <= len(frames) <= MAX_FRAMES:
        raise DiscoveryError("Expected 2-30000 decoded replay frames.")
    valid: list[dict] = []
    last = -math.inf
    for frame in frames:
        if not isinstance(frame, dict) or not _finite(frame.get("t")):
            raise DiscoveryError("Frame timestamps must be finite.")
        t = float(frame["t"])
        if t < 0 or t <= last:
            raise DiscoveryError("Frame timestamps must increase strictly.")
        last = t
        if horizon is None or t <= horizon:
            valid.append(frame)
    if horizon is not None:
        if not _finite(horizon) or horizon < 0 or horizon > last:
            raise DiscoveryError("Requested horizon lies outside the replay.")
        if not valid:
            raise DiscoveryError("No frames exist before the requested horizon.")
    return valid, (horizon if horizon is not None else last)


def _audit(replay: dict, focus: str, row: dict) -> dict | None:
    """Verify advertised N1/N2 references exist in the actual Stage 1 packet."""
    try:
        episode = build_episode_evidence(
            replay, focus, row["decision_times"], row["episode_start_s"], row["primary_t0"]
        )
    except (EpisodeError, ValueError, TypeError, KeyError):
        return None
    if episode["status"] == "abstain":
        return None
    available = {
        f"{node['node_id']}/{ev['id']}"
        for node in episode["nodes"]
        for ev in node["snapshot"].get("evidence", [])
    }
    signals = [signal for signal in row["signals"]
               if all(ref in available for ref in signal["evidence_refs"])]
    if not signals:
        return None
    row["signals"] = signals
    row["source_ref_count"] = len(set(ref for signal in signals for ref in signal["evidence_refs"]))
    row["stage1_episode_status"] = episode["status"]
    return row


def discover_episode_candidates(replay: dict, player_id: str, *,
                                max_candidates: int = 8,
                                horizon_s: float | None = None) -> dict:
    """Generate a small, diverse, causal-neutral shortlist from real frames.

    Returned (decision_times, episode_start_s, primary_t0) can be passed
    unchanged to POST /api/coach/lesson. No external model is invoked.
    """
    if not isinstance(replay, dict) or not isinstance(player_id, str) or not player_id:
        raise DiscoveryError("Replay and player ID are required.")
    if type(max_candidates) is not int or not 1 <= max_candidates <= MAX_CANDIDATES:
        raise DiscoveryError("Candidate limit must be 1-12.")
    players = replay.get("players")
    if not isinstance(players, list) or len(players) != 4 or not all(isinstance(p, dict) for p in players):
        raise DiscoveryError("Only full 2v2 replay data can be analyzed.")
    ids = [p.get("id") for p in players]
    teams = [p.get("team") for p in players]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != 4:
        raise DiscoveryError("Replay player IDs must be unique strings.")
    if teams.count("blue") != 2 or teams.count("orange") != 2 or player_id not in ids:
        raise DiscoveryError("Expected a selected player in a 2v2 match.")
    team = next(p["team"] for p in players if p["id"] == player_id)
    teammate = next(p["id"] for p in players if p["team"] == team and p["id"] != player_id)
    frames, horizon = _frames_through(replay, horizon_s)
    first = float(frames[0]["t"])
    if horizon - first < MIN_PRIMARY_AGE_S:
        return _result(horizon, [], scanned=0)

    # Downsample for efficiency, preserving exact observed source timestamps.
    samples: list[dict] = []
    last_sample = -math.inf
    for frame in frames:
        t = float(frame["t"])
        if t - last_sample < SAMPLE_SPACING_S:
            continue
        sample = _snap(frame, player_id, teammate)
        if sample:
            samples.append(sample)
            last_sample = t
    if len(samples) < 4:
        return _result(horizon, [], scanned=0)

    potential: list[dict] = []
    j = 0
    for current in samples:
        while j + 1 < len(samples) and current["t"] - samples[j + 1]["t"] >= COMPARISON_LAG_S:
            j += 1
        earlier = samples[j]
        if current["t"] - first < MIN_PRIMARY_AGE_S:
            continue
        if not 0.85 <= current["t"] - earlier["t"] <= 1.8:
            continue
        signals = _signals(earlier, current)
        if not signals:
            continue
        early_t = _ceil_ms(earlier["t"])
        primary_t = _ceil_ms(current["t"])
        if primary_t - early_t < 0.6 or primary_t > horizon + 0.001:
            continue
        episode_start = round(max(first, primary_t - 8), 3)
        if primary_t - episode_start < 5 or early_t < episode_start:
            continue
        dominant = signals[0]["signal"]
        salience = round(signals[0]["salience"] + min(len(signals) - 1, 3) * 0.35, 2)
        identifier = hashlib.sha256(
            f"{player_id}|{primary_t:.3f}|{dominant}|{POLICY}".encode("utf-8")
        ).hexdigest()[:14]
        potential.append({
            "candidate_id": "ec-" + identifier,
            "primary_t0": primary_t,
            "comparison_sample_s": early_t,
            "episode_start_s": episode_start,
            "decision_times": [early_t, primary_t],
            "node_meaning": {
                "N1": "observed comparison snapshot; not an identified player decision",
                "N2": "observed change endpoint; not proof of a tactical mistake",
            },
            "primary_signal": dominant,
            "salience_score": salience,
            "signals": signals,
            "status": "attention_candidate_not_coaching_verdict",
            "retrospective_consulted": False,
            "expert_validated": False,
        })

    # Deterministic salience ranking and temporal non-max suppression.
    # This is a review shortlist, not a ranking of mistakes or player skill.
    ranked = sorted(potential, key=lambda row: (-row["salience_score"], row["primary_t0"], row["candidate_id"]))
    shortlisted: list[dict] = []
    for row in ranked:
        if any(abs(row["primary_t0"] - sel["primary_t0"]) < MIN_CANDIDATE_GAP_S for sel in shortlisted):
            continue
        checked = _audit(replay, player_id, row)
        if checked:
            shortlisted.append(checked)
        if len(shortlisted) >= max_candidates:
            break
    shortlisted.sort(key=lambda row: row["primary_t0"])
    return _result(horizon, shortlisted, scanned=len(potential))


def _result(horizon: float, candidates: list[dict], *, scanned: int) -> dict:
    return {
        "schema": SCHEMA,
        "mode": "deterministic_source_observation",
        "stage": "predecision",
        "status": "ok" if candidates else "no_supported_candidates",
        "discovery_horizon_s": round(horizon, 3),
        "candidate_count": len(candidates),
        "signal_windows_scanned": scanned,
        "policy": {
            "version": POLICY,
            "calibration": "uncalibrated_attention_heuristics",
            "does_not_establish": ["mistakes", "player_intent", "causes", "best_move", "skill_level"],
            "selection_uses_future_events": False,
            "spacing_s": MIN_CANDIDATE_GAP_S,
            "node_semantics": "recorded snapshots, not automatically identified discrete decisions",
        },
        "candidates": candidates,
    }

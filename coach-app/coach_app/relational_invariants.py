"""RelationalInvariantsV0: defensible *geometry*, not tactics.

Calculate source-linked, pre-decision spatial relations directly from the
audited Stage1EpisodePacketV0. The model needn't guess 2D geometry from raw
coordinate arrays, but a calculated relation is NOT proof of possession,
turning feasibility, camera information, teammate recovery or best move.

No post-decision frames, full replay metadata, raw IDs, predicted ball
physics, model calls, or player-history state enter this module.
"""
from __future__ import annotations

import math
from typing import Any

from .episode_stage1 import SCHEMA as STAGE1_EPISODE
from .stage1_packet import Stage1PacketError, _copy_json_safe

SCHEMA = "RelationalInvariantsV0"
ROLES = ("focus", "teammate", "opponent_1", "opponent_2")
# A normal game has blue defending negative Y and orange defending positive
# Y. This is only a longitudinal arena-coordinate convention.
_ATTACK_SIGN = {"blue": 1, "orange": -1}
MAX_METRICS = 22


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _source(index: dict, key: str, t0: float, *, size: int = 3) -> tuple[tuple[float, ...] | None, str]:
    item = index.get(key)
    if not isinstance(item, dict):
        return None, "missing source"
    if item.get("kind") != "observation":
        return None, "not a direct observation"
    tags = item.get("provenance")
    if not isinstance(tags, list) or "replay_sample" not in tags:
        return None, "source is not recorded telemetry"
    if "stale_possible" in tags:
        return None, "recorded state may be stale"
    sampled = item.get("source_time_s")
    if not _finite(sampled) or sampled > t0 or t0 - sampled > 0.1500001:
        return None, "position or orientation sample is not contemporaneous"
    vector = item.get("value")
    if not isinstance(vector, list) or len(vector) != size or not all(_finite(x) for x in vector):
        return None, "missing or invalid numeric vector"
    return tuple(float(x) for x in vector), ""


def _metric(name: str, subject: str, value: str | float, sources: list[str],
            unit: str | None = None, caveat: str = "") -> dict:
    return {
        "metric": name, "subject": subject, "value": value,
        "unit": unit, "source_refs": sources,
        "derivation": "direct_coordinate_geometry_not_calibrated_tactics",
        "caveat": caveat,
    }


def build_relational_invariants(packet: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded, deterministic, abstention-aware relational packet.

    Input is *only* output from build_stage1_episode_packet(). Source values
    and timestamps are checked again locally. Every measurement lists the
    original N#/E... source IDs, never an invented source.
    """
    if not isinstance(packet, dict) or packet.get("schema") != STAGE1_EPISODE:
        raise Stage1PacketError("Relational geometry requires a Stage1EpisodePacketV0.")
    nodes = packet.get("nodes")
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 4:
        raise Stage1PacketError("Relational geometry requires two to four audited nodes.")
    result = []
    for i, node in enumerate(nodes, 1):
        nid = f"N{i}"
        if not isinstance(node, dict) or node.get("node_id") != nid:
            raise Stage1PacketError("Relational nodes must be in audited time order.")
        t0 = node.get("t0")
        inner = node.get("packet")
        if not _finite(t0) or not isinstance(inner, dict) or inner.get("cutoff_s") != t0:
            raise Stage1PacketError("Relational node time does not match its Stage 1 source.")
        if inner.get("status") not in ("ok", "partial", "abstain"):
            raise Stage1PacketError("Relational source status is not recognized.")
        sources = inner.get("evidence")
        slots = inner.get("slots")
        if not isinstance(sources, list) or not isinstance(slots, dict):
            raise Stage1PacketError("Relational source evidence is missing.")
        index = {x["id"]: x for x in sources if isinstance(x, dict) and isinstance(x.get("id"), str)}
        if len(index) != len(sources):
            raise Stage1PacketError("Relational source evidence contains duplicate or malformed IDs.")

        metrics: list[dict] = []
        unknowns: list[dict] = []
        def unknown(metric: str, role: str, reason: str) -> None:
            unknowns.append({"metric": metric, "subject": role,
                             "status": "unavailable", "reason": reason})
        def add(name: str, role: str, value: str | float, refs: list[str],
                unit: str | None = None, caveat: str = "") -> None:
            metrics.append(_metric(name, role, value,
                                   [f"{nid}/{r}" for r in refs], unit, caveat))

        if inner["status"] == "abstain":
            unknown("all_spatial_relations", "all", "decision source abstained")
        else:
            ball, ball_problem = _source(index, "E.ball.position", t0)
            positions: dict[str, tuple[float, ...]] = {}
            problems: dict[str, str] = {}
            for role in ROLES:
                positions[role], problems[role] = _source(
                    index, f"E.{role}.position", t0)
            focus_team = slots.get("focus", {}).get("team")
            if focus_team not in _ATTACK_SIGN:
                raise Stage1PacketError("The focus team is not verified.")
            attack = _ATTACK_SIGN[focus_team]
            # Goal-side positioning is just longitudinal ordering relative to
            # the ball, NOT proof the player could recover, cover, or save.
            for role in ROLES:
                p = positions[role]
                if ball is None or p is None:
                    unknown("longitudinal_goal_side_of_ball", role,
                            ball_problem or problems[role])
                    unknown("planar_ball_distance", role,
                            ball_problem or problems[role])
                    continue
                directed_delta = attack * (ball[1] - p[1])
                relation = ("goalward" if directed_delta > 0
                            else "upfield" if directed_delta < 0 else "level")
                refs = [f"E.{role}.position", "E.ball.position"]
                add("longitudinal_goal_side_of_ball", role, relation, refs,
                    caveat="Y-axis ordering only; not a covered lane, ball ownership or defensive safety.")
                add("planar_ball_distance", role,
                    round(math.hypot(ball[0]-p[0], ball[1]-p[1]), 1),
                    refs, "uu",
                    "2D separation only; not intercept time, reachability or possession.")
            f, m = positions["focus"], positions["teammate"]
            if f is not None and m is not None:
                refs = ["E.focus.position", "E.teammate.position"]
                add("teammate_planar_separation", "focus_and_teammate",
                    round(math.hypot(f[0]-m[0], f[1]-m[1]), 1),
                    refs, "uu", "Separation alone does not establish rotational coverage.")
                add("teammate_lateral_separation", "focus_and_teammate",
                    round(abs(f[0]-m[0]), 1),
                    refs, "uu", "X-axis difference, not evidence of overlapping roles.")
            else:
                unknown("teammate_planar_separation", "focus_and_teammate",
                        problems["focus"] or problems["teammate"])
                unknown("teammate_lateral_separation", "focus_and_teammate",
                        problems["focus"] or problems["teammate"])
            # Heading uses observed car *nose* direction. It is not camera
            # view or evidence a player intended to challenge the ball.
            for role in ROLES:
                p = positions[role]
                facing, facing_problem = _source(index, f"E.{role}.forward", t0)
                if ball is None or p is None or facing is None:
                    unknown("nose_to_ball_angle", role,
                            ball_problem or problems[role] or facing_problem)
                    continue
                dx, dy = ball[0]-p[0], ball[1]-p[1]
                distance = math.hypot(dx, dy)
                facing_length = math.hypot(facing[0], facing[1])
                if distance < 1e-6 or facing_length < 1e-6:
                    unknown("nose_to_ball_angle", role,
                            "ball shares planar position or heading cannot be projected to ground")
                    continue
                cosine = max(-1.0, min(1.0,
                    (facing[0]*dx + facing[1]*dy)/(distance*facing_length)))
                add("nose_to_ball_angle", role,
                    round(math.degrees(math.acos(cosine)), 1),
                    [f"E.{role}.forward", f"E.{role}.position", "E.ball.position"],
                    "deg", "Planar nose orientation only; NOT camera/awareness, turning time or an intention.")

        if len(metrics) > MAX_METRICS:
            raise Stage1PacketError("Relational geometry unexpectedly exceeded bounded metric count.")
        result.append({
            "node_id": nid, "t0_s": t0,
            "status": "abstain" if not metrics else ("partial" if unknowns else "observed_geometry"),
            "metrics": metrics, "unknowns": unknowns
        })

    return _copy_json_safe({
        "schema": SCHEMA, "stage": "predecision",
        "information_cutoff_s": nodes[-1]["t0"],
        "nodes": result,
        "uses_future": False, "predicts_ball_outcome": False,
        "calculates_possession": False, "calculates_tactical_merit": False,
        "expert_calibrated": False,
        "disclaimer": (
            "Observed-coordinate geometry only. Teammate coverage, possession, "
            "recoveries, opponent intentions and strategic desirability are not established."
        ),
    })

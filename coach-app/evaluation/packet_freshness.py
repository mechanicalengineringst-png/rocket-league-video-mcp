"""Read-only audit of decision-time replay sample recency and source provenance.

A dense subtr-actor NDArray at fps=30 is a RESAMPLED OUTPUT timeline. It is
not a list of the original per-actor network packet updates. The timestamp of
the chosen array row can prove only row recency, not when the car/ball state was
last natively updated. Repeated identical states may be legitimate stationary
gameplay and MUST NOT be labelled stale packets.

This audit deliberately does not patch coaching data or infer ground truth.
It never reads a frame after the decision time. It has no decoder/GPU/model
dependencies and does not include coordinates or player names in its output.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from .score import _read_records

SCHEMA = "replay-lab-packet-provenance-audit-v1"
SOURCE_HINT_FIELD = "nativeUpdateTimeS"  # experimental field, not emitted by the current decoder


def _num(value: Any) -> bool:
    return type(value) in (float, int) and math.isfinite(value)


def _require(ok: bool, why: str) -> None:
    if not ok:
        raise ValueError(why)


def _samples(payload: dict[str, Any]) -> tuple[list[dict], list[float]]:
    frames = payload.get("frames")
    _require(isinstance(frames, list) and frames, "Expected nonempty frames list")
    times: list[float] = []
    for i, frame in enumerate(frames):
        _require(isinstance(frame, dict), f"Frame {i} is not an object")
        t = frame.get("t")
        _require(_num(t) and t >= 0 and (not times or t > times[-1]),
                 f"Frame {i}: timestamps must be finite and strictly increasing")
        times.append(float(t))
    return frames, times


def _case(case: dict[str, Any]) -> tuple[str, float, str | None]:
    _require(isinstance(case, dict), "Case must be an object")
    cid = case.get("case_id", case.get("decision_case_id"))
    t0 = case.get("t0", case.get("decision_time_s"))
    focus = case.get("focus_player_id")
    if focus is None and isinstance(case.get("focus_player"), dict):
        focus = case["focus_player"].get("id")
    _require(isinstance(cid, str) and bool(cid.strip()), "Case requires case_id")
    _require(_num(t0) and t0 >= 0, f"{cid}: invalid t0")
    _require(focus is None or (isinstance(focus, str) and bool(focus.strip())),
             f"{cid}: invalid focus_player_id")
    return cid, float(t0), focus


def _signature(state: Any) -> tuple | None:
    """Identical resampled values are a diagnostic, NOT proof of stale packets."""
    if not isinstance(state, dict):
        return None
    pos = (state.get("x"), state.get("y"), state.get("z"))
    if not all(_num(v) for v in pos):
        return None
    velocity = state.get("velocity")
    if not isinstance(velocity, list) or len(velocity) < 3 or not all(
        _num(v) for v in velocity[:3]
    ):
        return None
    rotation = state.get("rotation")
    if rotation is not None and (not isinstance(rotation, list)
                                 or len(rotation) < 3
                                 or not all(_num(v) for v in rotation[:3])):
        return None
    return pos + tuple(velocity[:3]) + (tuple(rotation[:3]) if rotation else ())


def _state(frame: dict, actor: str) -> Any:
    if actor == "ball":
        return frame.get("ball")
    return (frame.get("cars") or {}).get(actor)


def _repeat_run(frames: list[dict], at: int, actor: str, *, cap: int = 24) -> int:
    sig = _signature(_state(frames[at], actor))
    if sig is None:
        return 0
    count = 1
    for i in range(at - 1, max(-1, at - cap), -1):
        if _signature(_state(frames[i], actor)) != sig:
            break
        count += 1
    return count


def _actor_row(
    frames: list[dict],
    at: int | None,
    actor: str,
    t0: float,
    max_sample_age_s: float,
) -> dict[str, Any]:
    if at is None:
        return {
            "actor": actor, "sample_at_s": None, "sample_age_s": None,
            "sample_status": "no_sample_at_or_before_t0",
            "native_packet_freshness": "unverifiable",
            "reported_native_update_age_s": None,
            "reported_native_update_hint": "not_available",
            "identical_sample_run_length": 0,
        }
    frame = frames[at]
    ft = float(frame["t"])
    age = t0 - ft
    state = _state(frame, actor)
    status = "sampled_state_available"
    if age > max_sample_age_s + 1e-9:
        status = "row_too_old"
    elif not isinstance(state, dict):
        status = "actor_missing"
    elif state.get("demolished"):
        status = "actor_demolished"
    elif _signature(state) is None:
        status = "required_state_fields_missing"

    hint_age = None
    hint_status = "not_available"
    if isinstance(state, dict) and SOURCE_HINT_FIELD in state:
        hint = state[SOURCE_HINT_FIELD]
        if not _num(hint) or hint < 0:
            hint_status = "invalid_source_timestamp"
        elif hint > ft + 1e-6 or hint > t0 + 1e-6:
            hint_status = "future_timestamp_invalid"
        else:
            hint_age = round(t0 - hint, 4)
            hint_status = "reported_recent_unverified" if hint_age <= max_sample_age_s \
                else "reported_old_unverified"

    return {
        "actor": actor,
        "sample_at_s": round(ft, 4),
        "sample_age_s": round(age, 4),
        "sample_status": status,
        # Even the optional hint is self-reported by a future decoder and
        # must be independently audited before it is called verified.
        "native_packet_freshness": "unverifiable",
        "reported_native_update_age_s": hint_age,
        "reported_native_update_hint": hint_status,
        "identical_sample_run_length": _repeat_run(frames, at, actor),
    }


def audit_replay(
    payload: dict[str, Any],
    cases: list[dict[str, Any]],
    *,
    max_sample_age_s: float = 0.15,
) -> dict[str, Any]:
    """Audit time-bounded samples without treating resampled rows as native packets.

    Case inputs may be full decision cases, sanitized LLM case packets, or
    basic {case_id,t0,focus_player_id?} references. If focus is unknown, audit
    every roster member rather than guessing one. Future frames have no effect
    on the per-case results; even the global summary is based on these cases.
    """
    _require(isinstance(payload, dict), "Replay payload must be an object")
    _require(isinstance(cases, list) and cases, "Provide at least one case")
    _require(_num(max_sample_age_s) and 0 < max_sample_age_s <= 1,
             "max_sample_age_s must be finite in (0,1]")
    frames, times = _samples(payload)
    players = payload.get("players", [])
    _require(isinstance(players, list), "Replay players must be a list")
    pids = []
    for p in players:
        _require(isinstance(p, dict) and isinstance(p.get("id"), str)
                 and bool(p["id"].strip()), "Every player needs a stable string id")
        _require(p["id"] not in pids, "Duplicate player id")
        pids.append(p["id"])

    ids: set[str] = set()
    rows = []
    stats = Counter()
    for entry in cases:
        cid, t0, focus = _case(entry)
        _require(cid not in ids, f"Duplicate case_id {cid}")
        ids.add(cid)
        if focus is not None:
            _require(focus in pids, f"{cid}: focus player absent from replay roster")
        at = bisect.bisect_right(times, t0) - 1
        at = at if at >= 0 else None
        actors = ["ball", *( [focus] if focus is not None else pids )]
        actor_rows = [
            _actor_row(frames, at, actor, t0, max_sample_age_s) for actor in actors
        ]
        for a in actor_rows:
            stats[a["sample_status"]] += 1
            stats["native_packet_freshness_unverifiable"] += 1
            if a["identical_sample_run_length"] > 1:
                stats["identical_sample_runs_not_proof_of_staleness"] += 1
            if a["reported_native_update_hint"] == "future_timestamp_invalid":
                stats["invalid_future_source_timestamp_hints"] += 1
        rows.append({
            "case_id": cid, "t0": round(t0, 4),
            "focus_scope": "specified_player" if focus else "all_rostered_players",
            "actors": actor_rows,
            "safe_to_claim_packet_freshness": False,
        })

    return {
        "schema": SCHEMA,
        "replay_source": str(payload.get("source", "unspecified")),
        "case_count": len(rows),
        "max_sample_age_s": max_sample_age_s,
        "summary": dict(sorted(stats.items())),
        "rows": rows,
        "release_gate": "native_actor_packet_freshness_not_established",
        "interpretation": (
            "At most this audit proves the age of a selected output ARRAY ROW. "
            "subtr-actor's regular-fps NDArray may resample/hold actor states; "
            "the current normalized replay does not preserve each native actor "
            "update timestamp. An identical sequence can be stationary motion, "
            "not stale telemetry. No native freshness certificate is issued, even "
            "when a producer supplies an unaudited optional timestamp hint. "
            "Obtain actual raw-update provenance in a future extractor and "
            "validate it against event streams before certifying coaching inputs. "
            "Never use future frames to describe the information at t0."
        ),
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Audit decision-time resampled-frame recency; NOT native packet proof"
    )
    p.add_argument("--replay-json", type=Path, required=True)
    p.add_argument("--cases", type=Path, required=True)
    p.add_argument("--max-sample-age", type=float, default=0.15)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    replay = json.loads(a.replay_json.read_text(encoding="utf-8"))
    result = audit_replay(
        replay, _read_records(a.cases), max_sample_age_s=a.max_sample_age
    )
    rendered = json.dumps(result, indent=2) + "\n"
    if a.output:
        a.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()

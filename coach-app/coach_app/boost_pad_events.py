"""Conservative native boost-pad pickup matching for standard Soccar replays.

The 'boost_pickups' stream contains a pad class and player position, not an
authoritative pad index. Never invent a pad identity from boost level alone.
IDs share the current 2D/3D BOOST_PADS ordering. Non-standard arenas and
ambiguous pickups remain unmatched rather than silently becoming fake states.
"""
from __future__ import annotations

import math
from typing import Any

# x, y, big. Same deterministic ordering as static/viewer3d.js BOOST_PADS.
_COORDS = [
    (-3072, -4096, True), (3072, -4096, True),
    (-3584, 0, True), (3584, 0, True),
    (-3072, 4096, True), (3072, 4096, True),
    (0, -4240, False), (-1792, -4184, False), (1792, -4184, False),
    (-940, -3308, False), (940, -3308, False), (0, -2816, False),
    (-3584, -2484, False), (3584, -2484, False),
    (-1792, -2484, False), (1792, -2484, False),
    (-1024, 0, False), (0, -1024, False), (0, 1024, False),
    (1024, 0, False), (-1792, 2484, False), (1792, 2484, False),
    (-3584, 2484, False), (3584, 2484, False),
    (0, 2816, False), (-940, 3308, False), (940, 3308, False),
    (-1792, 4184, False), (1792, 4184, False), (0, 4240, False),
    (-2048, -1036, False), (2048, -1036, False),
    (-2048, 1036, False), (2048, 1036, False),
]
PADS = [
    {'id': i, 'x': x, 'y': y, 'big': big, 'respawnSeconds': 10 if big else 4}
    for i, (x, y, big) in enumerate(_COORDS)
]


def _point(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def _size(value: Any) -> bool | None:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in ('big', 'large', 'full', '100', 'fullboost'):
        return True
    if v in ('small', 'mini', 'little', '12', 'smallboost'):
        return False
    return None


def match_boost_pickup(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Match an observed pickup to a canonical pad only when unambiguous.

    Native player_position may be offset by car radius from the pad center.
    A true pad_position (if present) is permitted a much smaller error.
    """
    if not isinstance(payload, dict):
        return None
    big = _size(payload.get('pad_type'))
    if big is None:
        return None
    direct = _point(payload.get('pad_position'))
    position = direct or _point(payload.get('player_position'))
    if position is None:
        return None
    limit = 110.0 if direct else (390.0 if big else 270.0)
    distances = sorted(
        (math.hypot(position[0] - pad['x'], position[1] - pad['y']), pad['id'])
        for pad in PADS if pad['big'] == big
    )
    if not distances or distances[0][0] > limit:
        return None
    # Do not choose arbitrarily if native player position is equally near
    # two pads. Keep the source event but leave its pad identity unknown.
    if len(distances) > 1 and distances[1][0] - distances[0][0] < 90:
        return None
    distance, pid = distances[0]
    return {
        'padId': pid,
        'padType': 'big' if big else 'small',
        'padMatch': 'pad_position' if direct else 'player_position_nearest',
        'padDistance': round(distance, 1),
    }


def _timestamp(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def make_pad_timeline(events: list[dict], raw_events: list[dict],
                      start: float, end: float) -> dict[str, Any]:
    """Build a read-only, time-synchronized pad-state contract for both views."""
    pickups = []
    unmatched = 0
    count = 0
    for item in events:
        if item.get('type') != 'boost_pickups':
            continue
        count += 1
        if not isinstance(item.get('padId'), int):
            unmatched += 1
            continue
        pickups.append({
            't': item['t'], 'padId': item['padId'],
            'playerId': item.get('playerId'),
            'method': item['padMatch'],
        })

    # Recorded kickoff events and native kickoff-spawn events are reset
    # evidence. Dedupe per-player kickoff-spawn events for the same kickoff.
    candidates = [ev['t'] for ev in events if ev.get('type') == 'kickoff'
                  and _timestamp(ev.get('t')) is not None]
    for raw in raw_events:
        if raw.get('meta', {}).get('stream') != 'boost_respawn':
            continue
        payload = raw.get('payload', {}).get('payload', {})
        if payload.get('kind') != 'kickoff':
            continue
        timing = raw.get('meta', {}).get('timing', {})
        t = _timestamp(payload.get('time'))
        if t is None:
            t = _timestamp(timing.get('time'))
        if t is not None:
            candidates.append(t)
    resets = []
    for t in sorted(x for x in candidates if start - .25 <= x <= end + .25):
        if not resets or t - resets[-1] > .25:
            resets.append(round(t, 3))
    return {
        'schema': 'replay-lab/boost-pads-v1',
        'source': 'native-boost-pickups' if count else 'unavailable',
        'pads': PADS,
        'pickups': sorted(pickups, key=lambda x: x['t']),
        'resets': resets,
        'observedPickupCount': count,
        'unmatchedPickupCount': unmatched,
    }


def pad_state_at(timeline: dict, pad_id: int, time: float) -> dict[str, Any]:
    """Reference evaluator for UI implementations; scrub-safe and deterministic.

    Unknown native coverage must never be presented as a confirmed live pad.
    """
    if timeline.get('source') != 'native-boost-pickups':
        return {'available': None, 'remaining': None}
    pad = PADS[pad_id]
    recent = None
    for reset in timeline['resets']:
        if reset <= time and (recent is None or reset > recent):
            recent = reset
    last = None
    for pickup in timeline['pickups']:
        if pickup['padId'] == pad_id and pickup['t'] <= time:
            if recent is None or pickup['t'] >= recent:
                last = pickup['t']
    if last is None:
        if recent is None:
            return {'available': None, 'remaining': None}
        return {'available': True, 'remaining': 0.0}
    remaining = max(0.0, last + pad['respawnSeconds'] - time)
    return {'available': remaining <= 0.0, 'remaining': round(remaining, 3)}

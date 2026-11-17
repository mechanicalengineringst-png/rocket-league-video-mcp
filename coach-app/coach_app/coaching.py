"""Conservative, deterministic *review candidates* from sparse replay snapshots.

These are NOT ground-truth mistakes or a Rocket League physics simulation.
AI coaching, when enabled, separately critiques compressed state evidence.
"""
from __future__ import annotations

import math
from typing import Any


def _dist(a: dict, b: dict) -> float:
    return math.hypot(a['x'] - b['x'], a['y'] - b['y'])


def suggested_support_point(ball: dict, team: str, current_x: float) -> dict[str, float]:
    """Illustrative goal-side support position, not an optimal path predictor."""
    own_y = -5120 if team == 'blue' else 5120
    direction = 1 if own_y > ball['y'] else -1
    side = -1 if current_x < ball['x'] else 1
    x = max(-3500, min(3500, ball['x'] + 500 * side))
    y = max(-4400, min(4400, ball['y'] + 1100 * direction))
    return {'x': round(x), 'y': round(y)}


def find_review_candidates(replay: dict[str, Any], focus_id: str,
                           max_findings: int | None = None) -> list[dict[str, Any]]:
    """Scan the WHOLE match. The per-type cooldowns already bound the output; an
    early cut-off would silently ignore everything after the first few minutes."""
    players = {p['id']: p for p in replay['players']}
    if focus_id not in players:
        raise ValueError('Choose a player in the replay.')
    team = players[focus_id]['team']
    teammates = [p['id'] for p in replay['players'] if p['team'] == team and p['id'] != focus_id]
    findings: list[dict[str, Any]] = []
    last_type: dict[str, float] = {}

    for f in replay['frames']:
        current = f['cars'].get(focus_id)
        if not current or current.get('demolished'):
            continue  # no live car to evaluate at this sample
        ball = f['ball']
        t = f['t']
        target = suggested_support_point(ball, team, current['x'])
        # Only surface candidate overlap when both teammates are tight to the ball
        # and each other. At high level this can also be entirely appropriate.
        close_mates = [m for pid in teammates if (m := f['cars'].get(pid))
                       and not m.get('demolished')
                       and _dist(m, ball) < 900 and _dist(m, current) < 1300]
        if _dist(current, ball) < 900 and close_mates and t - last_type.get('overlap', -1e8) >= 18:
            findings.append({
                'id': f'overlap-{len(findings)}', 't': t, 'type': 'overlap',
                'title': 'Possible two-car commitment', 'confidence': 'low',
                'evidence': 'Both teammates are near the ball and near each other in this replay sample.',
                'advice': 'Review who had the next controlled touch. If your teammate was committing, consider holding an offset, goal-side support lane.',
                'target': target,
            })
            last_type['overlap'] = t
        # This is a resource-awareness checkpoint, not a claim the route was wrong.
        own_y = -5120 if team == 'blue' else 5120
        defensive_third = abs(current['y'] - own_y) < 2700
        ball_near = abs(ball['y'] - own_y) < 3500
        if current.get('boost') is not None and current['boost'] <= 12 and defensive_third and ball_near and t - last_type.get('boost', -1e8) >= 30:
            findings.append({
                'id': f'boost-{len(findings)}', 't': t, 'type': 'boost',
                'title': 'Low boost during a defensive phase', 'confidence': 'low',
                'evidence': f'Your car has about {current["boost"]:.0f} boost while you and the ball are near your goal.',
                'advice': 'Inspect the previous rotation. Could a small-pad route have kept you goal-side without abandoning coverage?',
                'target': target,
            })
            last_type['boost'] = t
        if max_findings is not None and len(findings) >= max_findings:
            break
    return findings


def compact_game_states(replay: dict[str, Any], focus_id: str, max_frames: int = 240) -> str:
    """Produce bounded sparse numerical evidence for a single optional Gemini request."""
    players = {p['id']: p for p in replay['players']}
    if focus_id not in players:
        raise ValueError('Unknown player.')
    fs = replay['frames']
    stride = max(1, math.ceil(len(fs) / max_frames))
    # Short aliases instead of platform ids: fewer tokens, no account ids sent to the
    # model, and - crucially - the roster tells the model who is on which team.
    alias = {p['id']: f'P{i + 1}' for i, p in enumerate(replay['players'])}
    # Some decoded frames may include a track not present in the metadata roster.
    # Do not leak that unrecognized raw platform ID into the Gemini prompt.
    # Number unknown tracks deterministically by their first observed occurrence.
    for frame in fs:
        for pid in frame['cars']:
            if pid not in alias:
                alias[pid] = f'U{sum(value.startswith("U") for value in alias.values()) + 1}'
    roster = ', '.join(f'{alias[p["id"]]}={p["team"]}' for p in replay['players'])
    lines = [
        f'Focus={alias[focus_id]} ({players[focus_id]["team"]})',
        f'Players: {roster}',
        'Coordinates: blue goal y=-5120, orange goal y=+5120; field x=+-4096.',
        'Columns: time | ball x,y,z | cars player:x,y,z,boostPercent. Sampled positions, not frames of video.',
    ]
    for f in fs[::stride][:max_frames]:
        b = f['ball']
        def v(n: float | None) -> str:
            return '?' if n is None else str(round(n))
        cs = '; '.join(f'{alias[pid]}:{v(car["x"])},{v(car["y"])},{v(car.get("z"))},{v(car.get("boost"))}'
                       + (' DEMOLISHED' if car.get('demolished') else '')
                       for pid, car in f['cars'].items())
        lines.append(f'{f["t"]:.1f} | {v(b["x"])},{v(b["y"])},{v(b.get("z"))} | {cs}')
    return '\n'.join(lines)

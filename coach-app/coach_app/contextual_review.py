"""Selective, evidence-first review leads from native Rocket League telemetry.

These are *questions to verify in the replay*, never verdicts that a decision was
wrong. A normal goal, 50/50, bump or touch is not in itself a coaching insight.
No model scores, future-goal labels or physics counterfactuals are assumed.
"""
from __future__ import annotations

from bisect import bisect_left
from math import hypot, isfinite
from typing import Any

MAX_REVIEWS = 4


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _xy(a: dict, b: dict) -> float:
    return hypot(a['x'] - b['x'], a['y'] - b['y'])


def _alive(car: Any) -> bool:
    return isinstance(car, dict) and not car.get('demolished') and all(_num(car.get(k)) for k in ('x', 'y', 'z'))


def _speed(car: dict) -> float | None:
    v = car.get('velocity')
    return hypot(v[0], v[1]) if isinstance(v, (tuple, list)) and len(v) >= 2 and _num(v[0]) and _num(v[1]) else None


def _nearest(frames: list[dict], times: list[float], at: float, tolerance: float = 0.2) -> dict | None:
    pos = bisect_left(times, at)
    options = [i for i in (pos - 1, pos) if 0 <= i < len(times)]
    if not options:
        return None
    best = min(options, key=lambda i: abs(times[i] - at))
    return frames[best] if abs(times[best] - at) <= tolerance else None


def _near_kickoff(at: float, kickoffs: list[float], window: float = 4.0) -> bool:
    return any(abs(at - k) <= window for k in kickoffs)


def _line_distance(p: dict, a: dict, b: dict) -> float:
    dx, dy = b['x'] - a['x'], b['y'] - a['y']
    denom = dx * dx + dy * dy
    if denom < 1:
        return _xy(p, a)
    t = max(0.0, min(1.0, ((p['x'] - a['x']) * dx + (p['y'] - a['y']) * dy) / denom))
    return hypot(p['x'] - (a['x'] + t * dx), p['y'] - (a['y'] + t * dy))


def _lead(key: str, at: float, title: str, evidence: str, advice: str, uncertainty: str, priority: int, kind: str) -> dict:
    return {
        'id': key, 't': round(at, 3), 'type': 'contextual', 'kind': kind,
        'title': title, 'confidence': 'experimental', 'evidence': evidence,
        'advice': advice, 'uncertainty': uncertainty, 'target': None,
        'source': 'deterministic-telemetry-check-v1', 'priority': priority,
    }


def _shot_window(frame: dict, focus_id: str, opponents: list[str], team: str, t: float) -> dict | None:
    ball, cars = frame['ball'], frame['cars']
    focus = cars.get(focus_id)
    if not _alive(focus) or not all(_num(ball.get(k)) for k in ('x', 'y', 'z')):
        return None
    attack = 1 if team == 'blue' else -1
    opponent_goal_y = 5120 * attack
    goal_distance = (opponent_goal_y - ball['y']) * attack
    if not 1000 < goal_distance < 4500 or abs(ball['x']) > 1650 or ball['z'] > 350:
        return None
    if _xy(focus, ball) > 650 or focus['z'] > 160:
        return None
    forward = focus.get('forward')
    if not isinstance(forward, (list, tuple)) or len(forward) < 2 or not _num(forward[1]) or forward[1] * attack < 0.4:
        return None  # Facing away from goal: cannot claim a quick-shot opportunity.

    candidates = []
    for pid in opponents:
        keeper = cars.get(pid)
        if not _alive(keeper):
            continue
        speed = _speed(keeper)
        if speed is None or not _num(keeper.get('boost')):
            continue
        if abs(keeper['y'] - opponent_goal_y) <= 1350 and abs(keeper['x']) <= 1400 and keeper['boost'] <= 15 and speed <= 350:
            candidates.append((pid, keeper, speed))
    if not candidates:
        return None
    _, keeper, speed = min(candidates, key=lambda row: abs(row[1]['y'] - opponent_goal_y))
    goal_center = {'x': 0, 'y': opponent_goal_y}
    for pid in opponents:
        other = cars.get(pid)
        if not _alive(other) or other is keeper:
            continue
        if _xy(other, ball) < 1700 or _line_distance(other, ball, goal_center) < 550:
            return None  # Other defender could plausibly block or challenge immediately.

    return _lead(f'shot-window-{focus_id}-{t:.2f}', t,
        'Possible quick-shot window',
        f'At your touch, the near-net defender had about {keeper["boost"]:.0f} boost and was moving at roughly {speed:.0f} u/s. The ball was {goal_distance:.0f} units from goal.',
        'Replay this touch: was a direct, fast shot mechanically available before another possession touch? Compare the actual ball angle and the keeper\'s recovery.',
        'A low-boost stationary keeper does not guarantee a goal. Shot speed, contact angle, the other defender and unseen inputs can change the outcome.',
        priority=95, kind='shot_window')


def _second_man(frame: dict, later: dict, focus_id: str, mate_id: str, opponents: list[str], team: str, t: float) -> dict | None:
    ball, cars = frame['ball'], frame['cars']
    focus, mate = cars.get(focus_id), cars.get(mate_id)
    if not _alive(focus) or not _alive(mate) or not all(_num(ball.get(k)) for k in ('x', 'y', 'z')) or ball['z'] > 320:
        return None
    if _xy(mate, ball) > 480 or _xy(focus, mate) > 1250:
        return None
    # With blue goal at -Y, positive Y is advancing. Goal-side depth is how
    # far behind your teammate the focus car is along the field axis.
    attack = 1 if team == 'blue' else -1
    goal_side_depth = (mate['y'] - focus['y']) * attack
    if goal_side_depth >= 450:
        return None
    closest = min((_xy(car, ball) for pid in opponents if _alive(car := cars.get(pid))), default=float('inf'))
    if closest > 1600:
        return None
    later_ball, later_cars = later['ball'], later['cars']
    if not _alive(later_cars.get(mate_id)) or not _alive(later_cars.get(focus_id)):
        return None
    if _xy(later_cars[mate_id], later_ball) > 660:
        return None  # Must remain near the ball after the touch; not a one-frame overlap.
    if _xy(later_cars[focus_id], later_cars[mate_id]) > 1550:
        return None
    # Decision point is the later observation, so touch confirmation and
    # current positions are known; do not backdate a future-derived label.
    decision_t = later['t']
    return _lead(f'support-compression-{focus_id}-{decision_t:.2f}', decision_t,
        'Second-man recovery lane to inspect',
        f'At your teammate\'s preceding touch, you were {_xy(focus, mate):.0f} units away and {goal_side_depth:.0f} units behind them. An opponent was about {closest:.0f} units from the ball; your teammate was still near it a moment later.',
        'Watch the following challenge. If your teammate is dunked, do you still have time and space to cover your net? Consider whether a wider or deeper support lane was possible.',
        'Close support can be correct for a planned pass, an intentional 50/50 or immediate follow-up. This is a recovery question, not a double-commit verdict.',
        priority=83, kind='second_man_support')


def _defensive_pressure(frame: dict, focus_id: str, mates: list[str], opponents: list[str], team: str, t: float) -> dict | None:
    focus, ball, cars = frame['cars'].get(focus_id), frame['ball'], frame['cars']
    if not _alive(focus) or not all(_num(ball.get(k)) for k in ('x', 'y')) or not _num(focus.get('boost')):
        return None
    v = ball.get('velocity')
    if not isinstance(v, (tuple, list)) or len(v) < 2 or not _num(v[1]):
        return None
    own_goal_y = -5120 if team == 'blue' else 5120
    toward_own_goal = -1 if team == 'blue' else 1
    if abs(ball['y'] - own_goal_y) > 2500 or abs(focus['y'] - own_goal_y) > 2450:
        return None
    if focus['boost'] > 12 or v[1] * toward_own_goal < 500:
        return None
    if not any(_alive(m := cars.get(pid)) and (m['y'] - focus['y']) * (-toward_own_goal) > 950 for pid in mates):
        return None
    nearby_opponents = [_xy(cars[pid], ball) for pid in opponents if _alive(cars.get(pid))]
    if not nearby_opponents or min(nearby_opponents) > 1200:
        return None
    return _lead(f'defensive-pressure-{focus_id}-{t:.2f}', t,
        'Last-back, low-boost pressure',
        f'You had about {focus["boost"]:.0f} boost near your goal, the ball was moving goalward at {abs(v[1]):.0f} u/s, and your teammate was upfield.',
        'Inspect the last few seconds of your recovery. Could a small-pad route have preserved more defensive coverage without making you late to the play?',
        'This could be a forced defensive position. The snapshot does not prove a boost-management mistake or that another route was feasible.',
        priority=65, kind='defensive_pressure')


def build_contextual_reviews(replay: dict[str, Any], focus_id: str, max_reviews: int = MAX_REVIEWS) -> list[dict]:
    """Return at most a handful of conservative, replay-verifiable hypotheses.

    Requirements: native parser, known player identity mapping, timestamped
    native touch events, and finite relevant telemetry. No model call or quota.
    """
    if not isinstance(max_reviews, int) or isinstance(max_reviews, bool) or not 0 <= max_reviews <= 8:
        raise ValueError('max_reviews must be an integer from 0 to 8')
    players = {p.get('id'): p for p in replay.get('players', []) if isinstance(p, dict)}
    if focus_id not in players:
        raise ValueError('Unknown focus player')
    if not max_reviews or replay.get('playerMappingVerified') is False or replay.get('source') != 'subtr-actor-native-replay':
        return []
    frames = replay.get('frames') or []
    events = replay.get('events') or []
    if not frames or not events:
        return []
    times = [f.get('t') for f in frames]
    if not all(_num(t) for t in times) or any(a >= b for a, b in zip(times, times[1:])):
        return []
    team = players[focus_id].get('team')
    if team not in ('blue', 'orange'):
        return []
    mates = [pid for pid, p in players.items() if pid != focus_id and p.get('team') == team]
    opponents = [pid for pid, p in players.items() if p.get('team') != team]
    kickoffs = [ev['t'] for ev in events if ev.get('type') == 'kickoff' and _num(ev.get('t'))]
    candidates = []
    for e in events:
        if e.get('type') != 'touch' or not _num(e.get('t')) or e.get('playerId') not in players:
            continue
        at, actor = e['t'], e['playerId']
        if _near_kickoff(at, kickoffs):
            continue
        frame = _nearest(frames, times, at)
        if frame is None:
            continue
        if actor == focus_id:
            lead = _shot_window(frame, focus_id, opponents, team, at)
            if lead:
                candidates.append(lead)
        elif actor in mates:
            later = _nearest(frames, times, at + 0.35, 0.2)
            if later:
                lead = _second_man(frame, later, focus_id, actor, opponents, team, at)
                if lead:
                    candidates.append(lead)
        elif actor in opponents:
            # One defensive checkpoint per attack, anchored to an opponent touch
            # instead of reporting a low-boost warning every replay frame.
            lead = _defensive_pressure(frame, focus_id, mates, opponents, team, at)
            if lead:
                candidates.append(lead)
    # Rank by situational specificity, avoid repeated notices about the same play,
    # and keep different kinds visible. The final UI uses chronological order.
    selected = []
    per_kind: dict[str, int] = {}
    for lead in sorted(candidates, key=lambda c: (-c['priority'], c['t'], c['kind'])):
        if per_kind.get(lead['kind'], 0) >= 2:
            continue
        if any(abs(lead['t'] - kept['t']) < 9.0 for kept in selected):
            continue
        selected.append(lead)
        per_kind[lead['kind']] = per_kind.get(lead['kind'], 0) + 1
        if len(selected) >= max_reviews:
            break
    for lead in selected:
        lead.pop('priority', None)
    return sorted(selected, key=lambda lead: lead['t'])

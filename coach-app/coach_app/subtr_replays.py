"""Modern native replay ingest. subtr-actor parses original network frames.

Important: ndarray rows are RESAMPLED; native event.frame values are NOT row
indices. Join events to physics only by replay time, never by frame number.
"""
from __future__ import annotations

import bisect
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

FPS = 30.0
GLOBAL_FEATURES = ['BallRigidBody', 'CurrentTime', 'SecondsRemaining']
PLAYER_FEATURES = ['PlayerRigidBody', 'PlayerBoost', 'PlayerAnyJump']
TRACKED_EVENTS = {'touch', 'goal_context', 'kickoff', 'fifty_fifty',
                  'boost_pickups', 'whiff', 'bump', 'speed_flip', 'shadow_defense'}


class SubtrReplayError(ValueError):
    """The uploaded replay could not be normalized safely."""


def _header_id(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', str(value).lower())


def _column(headers: list[str], *names: str) -> int:
    indexed = {_header_id(h): i for i, h in enumerate(headers)}
    for name in names:
        if _header_id(name) in indexed:
            return indexed[_header_id(name)]
    raise SubtrReplayError(f'Missing replay field: {names[0]}')


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def _player_key(remote_id: Any) -> str | None:
    if isinstance(remote_id, dict) and len(remote_id) == 1:
        platform, identifier = next(iter(remote_id.items()))
        return f'{platform}:{identifier}'
    return None


def _payload(event: dict) -> dict:
    return event.get('payload', {}).get('payload', {})


def _event_time(event: dict) -> float | None:
    content = _payload(event)
    timing = event.get('meta', {}).get('timing', {})
    for candidate in (content.get('time'), timing.get('time'), timing.get('start_time')):
        value = _finite(candidate)
        if value is not None:
            return value
    return None


def _players(meta: dict, events: list[dict], data: Any, globals_count: int,
             per_player: int, x_offset: int, y_offset: int) -> tuple[list[dict], bool]:
    source = meta['replay_meta']
    candidates = []
    for group, team in (('team_zero', 'blue'), ('team_one', 'orange')):
        for info in source.get(group, []):
            key = _player_key(info.get('remote_id'))
            if not key:
                raise SubtrReplayError('A replay player has no usable player identifier.')
            candidates.append({'id': key, 'name': str(info.get('name') or key)[:80],
                               'team': team})
    if len(candidates) < 2 or len({p['id'] for p in candidates}) != len(candidates):
        raise SubtrReplayError('Replay has missing or duplicate player identities.')

    # Identify the actual numeric player column blocks from kickoff spawns, not
    # from names/assumptions about order in the ndarray.
    spawns = {}
    for ev in events:
        if ev.get('meta', {}).get('stream') != 'boost_respawn':
            continue
        content = _payload(ev)
        if content.get('kind') != 'kickoff':
            continue
        key = _player_key(content.get('player_id'))
        point = content.get('player_position')
        if key and isinstance(point, list) and len(point) >= 2:
            spawns.setdefault(key, point)

    mapped = []
    used = set()
    verified = len(spawns) >= len(candidates)
    for i in range(len(candidates)):
        base = globals_count + i * per_player
        x = _finite(data[0, base + x_offset]); y = _finite(data[0, base + y_offset])
        distances = []
        if x is not None and y is not None:
            for p in candidates:
                if p['id'] in used or p['id'] not in spawns:
                    continue
                pos = spawns[p['id']]
                distances.append((math.hypot(x - pos[0], y - pos[1]), p))
        distances.sort(key=lambda pair: pair[0])
        if distances and distances[0][0] < 180:
            chosen = distances[0][1]
        else:
            verified = False
            # Never present an uncertain player name/team as confirmed.
            chosen = candidates[i] if i < len(candidates) else None
            if chosen and chosen['id'] in used:
                raise SubtrReplayError('Cannot reliably associate player tracks.')
        if chosen is None:
            raise SubtrReplayError('Cannot associate player tracks.')
        used.add(chosen['id'])
        mapped.append(chosen)
    return mapped, verified


def _events(event_data: dict, players: list[dict], times: list[float]) -> tuple[list[dict], dict]:
    known = {p['id'] for p in players}
    normalized = []
    counts = Counter()
    for ev in event_data.get('events', []):
        kind = ev.get('meta', {}).get('stream')
        counts[kind] += 1
        if kind not in TRACKED_EVENTS:
            continue
        t = _event_time(ev)
        if t is None or t < times[0] - 1.0 or t > times[-1] + 1.0:
            continue
        content = _payload(ev)
        raw_key = (content.get('player') or content.get('player_id')
                   or content.get('scorer') or ev.get('meta', {}).get('primary_player'))
        pid = _player_key(raw_key)
        timing = ev.get('meta', {}).get('timing', {})
        frame = content.get('frame', timing.get('frame', timing.get('start_frame')))
        idx = bisect.bisect_left(times, t)
        if idx >= len(times) or (idx > 0 and abs(times[idx - 1] - t) < abs(times[idx] - t)):
            idx -= 1
        item = {'type': kind, 't': round(t, 3), 'nativeFrame': frame,
                'sampleIndex': idx, 'playerId': pid if pid in known else None}
        if kind == 'touch':
            tags = content.get('tags', [])
            tags = tags if isinstance(tags, list) else []
            safe_tags = {}
            for tag in tags[:14]:
                if not isinstance(tag, dict):
                    continue
                group, value = tag.get('group'), tag.get('value')
                if isinstance(group, str) and isinstance(value, str):
                    safe_tags[group[:32]] = value[:64]
            item['touchKind'] = safe_tags.get('kind')
            item['touchHeightBand'] = safe_tags.get('height_band')
            item['touchDodgeState'] = safe_tags.get('dodge_state')
            change = _finite(content.get('ball_speed_change'))
            item['ballSpeedChange'] = round(change, 1) if change is not None else None
        if kind == 'goal_context':
            item['scorerId'] = _player_key(content.get('scorer'))
            item['scoringTeam'] = 'blue' if content.get('scoring_team_is_team_0') else 'orange'
        elif kind == 'fifty_fifty':
            winner = content.get('winning_team_is_team_0')
            if isinstance(winner, bool):
                item['winningTeam'] = 'blue' if winner else 'orange'
        elif kind == 'kickoff':
            item['outcome'] = str(content.get('outcome', 'unknown'))[:50]
        elif kind == 'whiff':
            item['classification'] = str(content.get('kind', 'unclassified'))[:50]
        normalized.append(item)
    normalized.sort(key=lambda e: e['t'])
    return normalized, dict(counts)


def normalize_subtr_replay(meta: dict, data: Any, event_data: dict,
                           title: str = 'Rocket League replay') -> dict:
    """Validate and align subtr-actor's typed arrays and native event stream."""
    import numpy as np
    arr = np.asarray(data)
    headers = meta.get('column_headers', {})
    gh = headers.get('global_headers', []); ph = headers.get('player_headers', [])
    ng, npcols = len(gh), len(ph)
    if arr.ndim != 2 or arr.shape[0] < 2 or not ng or not npcols:
        raise SubtrReplayError('Replay did not contain usable physics samples.')
    if (arr.shape[1] - ng) % npcols:
        raise SubtrReplayError('Replay player data does not match its column headers.')

    bx = _column(gh, 'Ball - position x'); by = _column(gh, 'Ball - position y')
    bz = _column(gh, 'Ball - position z')
    bt = _column(gh, 'current time', 'time')
    clock = _column(gh, 'seconds remaining')
    px = _column(ph, 'position x'); py = _column(ph, 'position y')
    pz = _column(ph, 'position z'); pb = _column(ph, 'boost level (raw replay units)')
    try:
        pj = _column(ph, 'any_jump_active')
    except SubtrReplayError:
        pj = None  # Support older fixture schemas without a jump signal.
    # Rotation and velocity are preserved, not discarded, for future analysis.
    ball_velocity = [_column(gh, f'Ball - linear velocity {axis}') for axis in 'xyz']
    player_velocity = [_column(ph, f'linear velocity {axis}') for axis in 'xyz']
    player_rotation = [_column(ph, f'rotation {axis}') for axis in 'xyz']
    nplayers = (arr.shape[1] - ng) // npcols
    events = event_data.get('events', [])
    if not isinstance(events, list):
        raise SubtrReplayError('Replay event stream has an invalid format.')
    players, verified = _players(meta, events, arr, ng, npcols, px, py)
    if nplayers != len(players):
        raise SubtrReplayError('Replay track count does not match player metadata.')

    times = []
    frames = []
    for row in arr:
        t = _finite(row[bt]); x = _finite(row[bx]); y = _finite(row[by]); z = _finite(row[bz])
        if None in (t, x, y, z) or (times and t <= times[-1]):
            continue
        cars = {}
        for i, player in enumerate(players):
            base = ng + i * npcols
            pos = [_finite(row[base + off]) for off in (px, py, pz)]
            if any(v is None for v in pos):
                continue
            raw_boost = _finite(row[base + pb])
            car = {'x': round(pos[0], 2), 'y': round(pos[1], 2),
                   'z': round(pos[2], 2), 'boost': round(min(100., max(0., raw_boost / 255 * 100)), 1)
                   if raw_boost is not None else None}
            if pj is not None:
                jump = _finite(row[base + pj])
                if jump is not None:
                    car['jumpActive'] = jump >= 0.5
            velocity = [_finite(row[base + off]) for off in player_velocity]
            rotation = [_finite(row[base + off]) for off in player_rotation]
            if all(v is not None for v in velocity):
                car['velocity'] = [round(v, 1) for v in velocity]
            if all(v is not None for v in rotation):
                car['rotation'] = [round(v, 4) for v in rotation]
            cars[player['id']] = car
        if len(cars) < 2:
            continue
        velocity = [_finite(row[off]) for off in ball_velocity]
        ball = {'x': round(x, 2), 'y': round(y, 2), 'z': round(z, 2)}
        if all(v is not None for v in velocity):
            ball['velocity'] = [round(v, 1) for v in velocity]
        remaining = _finite(row[clock])
        frames.append({'t': round(t, 4), 'ball': ball, 'cars': cars,
                       'secondsRemaining': remaining})
        times.append(t)
    if not frames:
        raise SubtrReplayError('No physics samples with both cars and the ball were found.')
    aligned_events, counts = _events(event_data, players, times)
    if not verified:
        # Unknown identity mapping is a serious accuracy limit, not a coaching fact.
        notes = ['Player identities inferred from metadata order; verify against footage.']
    else:
        notes = ['Player identities checked against kickoff spawn events.']
    notes += ['Event nativeFrame and sampled physics indices are different timelines; aligned by replay time.',
              'Event labels are parser observations, not verified tactical mistakes.']
    header_pairs = meta.get('replay_meta', {}).get('all_headers', [])
    header_values = dict(pair for pair in header_pairs if isinstance(pair, (list, tuple)) and len(pair) == 2 and isinstance(pair[0], str))
    recording_name = header_values.get('PlayerName')
    primary_matches = [p['id'] for p in players if p['name'] == recording_name]
    primary_id = primary_matches[0] if len(primary_matches) == 1 else None
    return {'schema': 'rl-coach/0.2', 'title': title[:128],
            'mode': f'{sum(p["team"] == "blue" for p in players)}v{sum(p["team"] == "orange" for p in players)}',
            'duration': frames[-1]['t'], 'players': players, 'primaryPlayerId': primary_id, 'frames': frames,
            'events': aligned_events, 'eventCounts': counts,
            'playerMappingVerified': verified, 'telemetrySampleCount': len(frames),
            'source': 'subtr-actor-native-replay', 'samplingSeconds': 1 / FPS, 'notes': notes}


def parse_subtr_replay(path: Path) -> dict:
    try:
        import subtr_actor
    except ImportError as error:
        raise SubtrReplayError('Replay decoder unavailable: install coach-app requirements.') from error
    try:
        meta, data = subtr_actor.get_ndarray_with_info_from_replay_filepath(
            str(path), global_feature_adders=GLOBAL_FEATURES,
            player_feature_adders=PLAYER_FEATURES, fps=FPS, dtype='float32')
        event_data = subtr_actor.get_stats_events(str(path), include_expected_goals=False)
        return normalize_subtr_replay(meta, data, event_data, title=path.stem)
    except SubtrReplayError:
        raise
    except Exception as error:
        raise SubtrReplayError('Cannot decode this replay with subtr-actor. The file may use an unsupported format.') from error

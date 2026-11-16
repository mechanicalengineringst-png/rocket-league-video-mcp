"""Convert a parsed Rocket League replay into a compact, timeline-aligned field model.

RLGym Tools uses carball to decode native .replay files into indexed Parquet data.
No Gemini calls are involved in parsing or scrubbing the replay.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any


FIELD_X = 4096
FIELD_Y = 5120
MAX_FRAMES = 1600
SAMPLE_INTERVAL_SECONDS = 0.5


class ReplayParseError(Exception):
    """Native replay conversion failed or did not contain usable game-state data."""


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return round(result, 2) if math.isfinite(result) else None


def _physics(row: Any, *, car: bool = False) -> dict[str, float | None] | None:
    if row is None:
        return None
    x = _number(row.get('pos_x'))
    y = _number(row.get('pos_y'))
    z = _number(row.get('pos_z'))
    if x is None or y is None:
        return None
    result: dict[str, float | None] = {'x': x, 'y': y, 'z': z}
    if car:
        boost = _number(row.get('boost_amount'))
        # RLGym/carball represents boost as a fraction from zero to one.
        result['boost'] = (round(min(100, max(0, boost * 100)), 1)
                           if boost is not None else None)
    return result


def _select_samples(game_df: Any) -> list[Any]:
    last = -1e12
    selected = []
    for frame_index, time_value in game_df['time'].items():
        t = _number(time_value)
        if t is None or t < 0:
            continue
        if t >= last + SAMPLE_INTERVAL_SECONDS or not selected:
            selected.append(frame_index)
            last = t
    if len(selected) > MAX_FRAMES:
        stride = math.ceil(len(selected) / MAX_FRAMES)
        selected = selected[::stride]
    return selected


def normalize_parsed_replay(replay: Any, title: str = 'Rocket League replay') -> dict[str, Any]:
    """Normalize a ParsedReplay instance; accepts test doubles with pandas DataFrames."""
    game_df = replay.game_df.sort_index()
    ball_df = replay.ball_df.sort_index()
    if 'time' not in game_df or not len(game_df):
        raise ReplayParseError('Replay did not include a readable timeline.')
    selected = _select_samples(game_df)
    if not selected:
        raise ReplayParseError('Replay had no usable game-time samples.')

    raw_players = replay.metadata.get('players', [])
    raw_by_id = {str(p.get('unique_id')): p for p in raw_players if p.get('unique_id') is not None}
    ids = list(replay.player_dfs.keys())
    players = []
    for key in ids:
        pid = str(key)
        info = raw_by_id.get(pid, {})
        players.append({
            'id': pid,
            'name': str(info.get('name') or f'Player {pid}')[:80],
            'team': 'orange' if info.get('is_orange') else 'blue',
        })
    if len(players) < 2:
        raise ReplayParseError('Replay contains fewer than two readable player tracks.')

    ball_rows = ball_df.reindex(selected, method='ffill').to_dict('index')
    player_rows = {
        str(key): df.sort_index().reindex(selected, method='ffill').to_dict('index')
        for key, df in replay.player_dfs.items()
    }
    frames = []
    for idx in selected:
        t = _number(game_df.at[idx, 'time'])
        ball = _physics(ball_rows.get(idx))
        if t is None or ball is None:
            continue
        cars = {}
        for pid, per_frame in player_rows.items():
            car = _physics(per_frame.get(idx), car=True)
            if car is not None:
                cars[pid] = car
        if len(cars) >= 2:
            frames.append({'t': t, 'ball': ball, 'cars': cars})
    if not frames:
        raise ReplayParseError('Replay contained no frames with a ball and two cars.')

    return {
        'schema': 'rl-coach/0.1',
        'title': title[:128],
        'mode': f'{sum(p["team"] == "blue" for p in players)}v{sum(p["team"] == "orange" for p in players)}',
        'duration': frames[-1]['t'],
        'players': players,
        'frames': frames,
        'source': 'native-replay',
        'samplingSeconds': SAMPLE_INTERVAL_SECONDS,
        'notes': ['Positions are replay observations, sampled approximately twice per second.',
                  'A proposed coaching path is an illustration, not a simulated outcome.'],
    }


def parse_replay_file(path: Path) -> dict[str, Any]:
    """Parse an uploaded .replay using RLGym Tools (and its bundled carball decoder)."""
    try:
        from rlgym_tools.rocket_league.replays.parsed_replay import ParsedReplay
    except ImportError as error:
        raise ReplayParseError(
            'Replay parser is not installed. Install coach-app/requirements.txt.'
        ) from error
    try:
        return normalize_parsed_replay(ParsedReplay.load(str(path)), path.stem)
    except ReplayParseError:
        raise
    except Exception as error:
        raise ReplayParseError(
            'This replay could not be decoded. Try a replay from the current game version.'
        ) from error

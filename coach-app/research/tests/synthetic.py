"""Deterministic synthetic matches for unit tests.

These exercise code paths only. Nothing produced from them is a gameplay result.
"""
from __future__ import annotations

import numpy as np

from research.tactical_intel.frames import Match


def make_match(match_id: str = "m1", n: int = 600, sizes=(2, 2), goals=(), seed: int = 0,
               threat: bool = True) -> Match:
    rng = np.random.default_rng(seed)
    p = sum(sizes)
    t = np.arange(n) * 0.1
    ball = np.zeros((n, 6))
    ball[:, 0] = 800 * np.sin(t / 7.0)
    ball[:, 1] = 3000 * np.sin(t / 11.0)
    ball[:, 2] = 93 + 200 * np.abs(np.sin(t / 3.0))
    ball[1:, 3:5] = np.diff(ball[:, :2], axis=0) / 0.1
    cars = np.zeros((n, p, 6))
    for k in range(p):
        side = -1 if k < sizes[0] else 1
        cars[:, k, 0] = 1500 * np.sin(t / (5.0 + k)) + rng.normal(0, 5, n)
        cars[:, k, 1] = side * 2500 + 1500 * np.sin(t / (6.0 + k))
        cars[:, k, 2] = 17.0
        cars[1:, k, 3:5] = np.diff(cars[:, k, :2], axis=0) / 0.1
    bt = None
    if threat:
        bt = np.stack([np.clip(0.02 + 0.05 * np.sin(t / 4), 0, 1),
                       np.clip(0.02 + 0.05 * np.cos(t / 4), 0, 1)], axis=1)
    return Match(
        match_id=match_id, source=f"{match_id}.replay", team_sizes=tuple(sizes), t=t,
        live=np.ones(n, bool), ball=ball, cars=cars, boost=np.full((n, p), 50.0),
        present=np.ones((n, p), bool), car_team=np.array([0] * sizes[0] + [1] * sizes[1], np.int8),
        seconds_remaining=np.clip(300 - t, 0, 300), goals=tuple(goals),
        player_keys=tuple(f"{match_id}_p{k}" for k in range(p)), builtin_threat=bt,
    )


def rotated_copy(m: Match, match_id: str = "rot") -> Match:
    """The same match with the field rotated 180 degrees and the team labels swapped."""
    def rot(a):
        a = a.copy()
        a[..., 0] *= -1
        a[..., 1] *= -1
        a[..., 3] *= -1
        a[..., 4] *= -1
        return a
    order = np.concatenate([np.flatnonzero(m.car_team == 1), np.flatnonzero(m.car_team == 0)])
    return Match(
        match_id=match_id, source=m.source, team_sizes=(m.team_sizes[1], m.team_sizes[0]), t=m.t,
        live=m.live, ball=rot(m.ball), cars=rot(m.cars)[:, order], boost=m.boost[:, order],
        present=m.present[:, order], car_team=np.array([0] * m.team_sizes[1] + [1] * m.team_sizes[0], np.int8),
        seconds_remaining=m.seconds_remaining, goals=tuple((g, 1 - tm) for g, tm in m.goals),
        builtin_threat=None if m.builtin_threat is None else m.builtin_threat[:, ::-1],
    )


def defence_scene(choice: str, match_id: str = "d1") -> Match:
    """Team 0 defends -y. An attacker carries the ball through our half; our defender
    either charges the ball or retreats toward goal. Hand-built, 4 seconds long."""
    n = 40
    t = np.arange(n) * 0.1
    ball = np.zeros((n, 6))
    ball[:, 1] = -1500 - 300 * t
    ball[:, 2] = 93.0
    ball[:, 4] = -300
    cars = np.zeros((n, 4, 6))
    cars[:, 2, 1] = ball[:, 1] + 300   # attacker just behind the ball (team 1)
    cars[:, 2, 4] = -300
    cars[:, 3, 1] = 2500               # second attacker far away
    cars[:, 1, 1] = -4800              # teammate in net
    cars[:, 1, 0] = 300
    d_y = np.full(n, -3200.0)          # our defender, goal-side
    if choice == "challenge":
        d_y[11:] = -3200 + 1700 * (t[11:] - t[10])
        d_y = np.minimum(d_y, ball[:, 1] - 120)
    elif choice == "shadow":
        d_y[11:] = -3200 - 450 * (t[11:] - t[10])
    cars[:, 0, 1] = d_y
    cars[:, 0, 0] = 200
    cars[1:, 0, 4] = np.diff(d_y) / 0.1
    for k in range(4):
        cars[:, k, 2] = 17.0
    # Gate the situation so it starts at frame 10: attacker far before that.
    cars[:10, 2, 1] = 4000
    return Match(
        match_id=match_id, source=f"{match_id}.replay", team_sizes=(2, 2), t=t, live=np.ones(n, bool),
        ball=ball, cars=cars, boost=np.full((n, 4), 40.0), present=np.ones((n, 4), bool),
        car_team=np.array([0, 0, 1, 1], np.int8), seconds_remaining=np.full(n, 200.0), goals=(),
        player_keys=("a", "b", "c", "d"), builtin_threat=np.full((n, 2), 0.05),
    )

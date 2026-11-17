"""Team-perspective, strictly causal state features and short-horizon labels.

Every feature for frame ``i`` uses frames ``<= i`` only. The view is rotated so
the perspective team always attacks +y (a 180-degree rotation about z, not a
reflection, so left and right are preserved).
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .frames import Match

GOAL_Y = 5120.0
GOAL_Z = 320.0
LAGS_S = (0.5, 1.0)

BALL_FEATURES = [
    "ball_x_abs", "ball_y", "ball_z", "ball_vx_abs", "ball_vy", "ball_vz", "ball_speed",
    "ball_dist_opp_goal", "ball_dist_own_goal", "team_size", "score_diff", "seconds_remaining",
]
ON_BALL_FEATURES = [
    "own_min_dist", "opp_min_dist", "own_min_ttb", "opp_min_ttb", "ttb_adv",
    "own_near_boost", "opp_near_boost",
]
OFF_BALL_FEATURES = [
    "own_goalside", "opp_goalside", "own_last_back_dist", "opp_last_back_dist",
    "own_second_ttb", "opp_second_ttb", "own_boost_mean", "opp_boost_mean",
    "own_present", "opp_present",
]
LAG_FEATURES = [f"d{lag}s_{k}" for lag in LAGS_S for k in ("ball_y", "ball_vy", "ttb_adv")]
FEATURE_GROUPS = {
    "ball_only": BALL_FEATURES + [f for f in LAG_FEATURES if "ttb" not in f],
    "on_ball": BALL_FEATURES + ON_BALL_FEATURES + LAG_FEATURES,
    "full": BALL_FEATURES + ON_BALL_FEATURES + OFF_BALL_FEATURES + LAG_FEATURES,
}
ALL_FEATURES = FEATURE_GROUPS["full"]


def time_to_ball(car_pos: np.ndarray, car_vel: np.ndarray, ball_pos: np.ndarray) -> np.ndarray:
    """Crude arrival-time estimate in seconds: distance over an effective approach speed.

    An approximation, not physics: it rewards speed already pointed at the ball and
    caps at supersonic. Good enough to rank who arrives first; not a reachability check.
    """
    d = ball_pos - car_pos
    dist = np.linalg.norm(d, axis=-1)
    unit = d / np.maximum(dist[..., None], 1.0)
    closing = np.sum(car_vel * unit, axis=-1)
    speed = np.clip(closing + 1000.0, 500.0, 2300.0)
    return dist / speed


def rotate(team: int, xyz: np.ndarray) -> np.ndarray:
    """World -> perspective coordinates. Team 1 is rotated 180 degrees about z."""
    if team == 0:
        return xyz
    out = xyz.copy()
    out[..., 0] *= -1.0
    out[..., 1] *= -1.0
    return out


def team_features(m: Match, team: int) -> pd.DataFrame:
    """One row per frame from ``team``'s perspective. Causal by construction."""
    ball_p = rotate(team, m.ball[:, :3])
    ball_v = rotate(team, m.ball[:, 3:])
    cars_p = rotate(team, m.cars[:, :, :3])
    cars_v = rotate(team, m.cars[:, :, 3:])
    own = m.car_team == team
    opp = ~own
    pres = m.present

    dist = np.linalg.norm(cars_p - ball_p[:, None, :], axis=2)
    ttb = time_to_ball(cars_p, cars_v, ball_p[:, None, :])
    dist = np.where(pres, dist, np.nan)
    ttb = np.where(pres, ttb, np.nan)
    boost = np.where(pres, m.boost, np.nan)

    def side(mask: np.ndarray, arr: np.ndarray, fn) -> np.ndarray:
        sub = arr[:, mask]
        if sub.shape[1] == 0 or np.all(np.isnan(sub)):
            return np.full(arr.shape[0], np.nan)
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-absent rows -> NaN, by design
            return fn(sub)

    def nanmin(a):
        with np.errstate(all="ignore"):
            out = np.full(a.shape[0], np.nan)
            ok = ~np.all(np.isnan(a), axis=1)
            out[ok] = np.nanmin(a[ok], axis=1)
            return out

    def nth_smallest(a, n):
        s = np.sort(np.where(np.isnan(a), np.inf, a), axis=1)
        if s.shape[1] <= n:
            return np.full(a.shape[0], np.nan)
        v = s[:, n]
        return np.where(np.isinf(v), np.nan, v)

    def boost_of_nearest(mask):
        d = np.where(np.isnan(dist[:, mask]), np.inf, dist[:, mask])
        if d.shape[1] == 0:
            return np.full(d.shape[0], np.nan)
        idx = np.argmin(d, axis=1)
        b = boost[:, mask][np.arange(d.shape[0]), idx]
        return np.where(np.isinf(d.min(axis=1)), np.nan, b)

    own_goal = np.array([0.0, -GOAL_Y, GOAL_Z])
    opp_goal = np.array([0.0, GOAL_Y, GOAL_Z])
    own_goal_d = np.where(pres, np.linalg.norm(cars_p - own_goal, axis=2), np.nan)
    opp_goal_d = np.where(pres, np.linalg.norm(cars_p - opp_goal, axis=2), np.nan)
    goalside = cars_p[:, :, 1] < ball_p[:, None, 1]      # between ball and own goal (own side)
    opp_goalside = cars_p[:, :, 1] > ball_p[:, None, 1]  # opponents between ball and their goal

    score = m.score_before()
    f = pd.DataFrame({
        "ball_x_abs": np.abs(ball_p[:, 0]),
        "ball_y": ball_p[:, 1],
        "ball_z": ball_p[:, 2],
        "ball_vx_abs": np.abs(ball_v[:, 0]),
        "ball_vy": ball_v[:, 1],
        "ball_vz": ball_v[:, 2],
        "ball_speed": np.linalg.norm(ball_v, axis=1),
        "ball_dist_opp_goal": np.linalg.norm(ball_p - opp_goal, axis=1),
        "ball_dist_own_goal": np.linalg.norm(ball_p - own_goal, axis=1),
        "team_size": float(m.team_sizes[team]),
        "score_diff": (score[:, team] - score[:, 1 - team]).astype(float),
        "seconds_remaining": np.clip(m.seconds_remaining, 0, 300),
        "own_min_dist": side(own, dist, lambda a: nanmin(a)),
        "opp_min_dist": side(opp, dist, lambda a: nanmin(a)),
        "own_min_ttb": side(own, ttb, lambda a: nanmin(a)),
        "opp_min_ttb": side(opp, ttb, lambda a: nanmin(a)),
        "own_second_ttb": nth_smallest(ttb[:, own], 1),
        "opp_second_ttb": nth_smallest(ttb[:, opp], 1),
        "own_near_boost": boost_of_nearest(own),
        "opp_near_boost": boost_of_nearest(opp),
        "own_goalside": np.sum(goalside[:, own] & pres[:, own], axis=1).astype(float),
        "opp_goalside": np.sum(opp_goalside[:, opp] & pres[:, opp], axis=1).astype(float),
        "own_last_back_dist": side(own, own_goal_d, lambda a: nanmin(a)),
        "opp_last_back_dist": side(opp, opp_goal_d, lambda a: nanmin(a)),
        "own_boost_mean": side(own, boost, lambda a: np.nanmean(a, axis=1)),
        "opp_boost_mean": side(opp, boost, lambda a: np.nanmean(a, axis=1)),
        "own_present": np.sum(pres[:, own], axis=1).astype(float),
        "opp_present": np.sum(pres[:, opp], axis=1).astype(float),
    })
    f["ttb_adv"] = f["opp_min_ttb"] - f["own_min_ttb"]
    for lag in LAGS_S:
        steps = int(round(lag / max(np.median(np.diff(m.t)) if m.n_frames > 1 else 0.1, 1e-3)))
        for k in ("ball_y", "ball_vy", "ttb_adv"):
            prev = f[k].shift(steps)
            f[f"d{lag}s_{k}"] = f[k] - prev
    return f[ALL_FEATURES]


def next_goal_labels(m: Match, team: int, horizon_s: float) -> tuple[np.ndarray, np.ndarray]:
    """``y[i] = 1`` if ``team`` scores in ``(t_i, t_i + horizon]``.

    ``valid[i]`` is False where the label cannot be resolved: the frame is not live,
    or the window runs past the last live frame without any goal (end of match).
    """
    t = m.t
    y = np.zeros(m.n_frames, dtype=np.int8)
    any_goal = np.zeros(m.n_frames, dtype=bool)
    for gt, tm in m.goals:
        win = (t < gt) & (gt <= t + horizon_s)
        any_goal |= win
        if tm == team:
            y[win] = 1
    last_live = t[m.live].max() if m.live.any() else -np.inf
    censored = (~any_goal) & (t + horizon_s > last_live)
    valid = m.live & ~censored
    return y, valid


def frame_table(matches: list[Match], horizon_s: float = 5.0) -> pd.DataFrame:
    """Stack both teams' perspectives for every match into one modelling table."""
    parts = []
    for m in matches:
        for team in (0, 1):
            f = team_features(m, team)
            y, valid = next_goal_labels(m, team, horizon_s)
            f["y"] = y
            f["valid"] = valid
            f["t"] = m.t
            f["team"] = team
            f["match_id"] = m.match_id
            f["source"] = m.source
            f["mode"] = m.mode
            if m.builtin_threat is not None:
                f["builtin_v"] = m.builtin_threat[:, team]
                f["builtin_v_opp"] = m.builtin_threat[:, 1 - team]
            else:
                f["builtin_v"] = np.nan
                f["builtin_v_opp"] = np.nan
            parts.append(f[f["valid"]].drop(columns="valid"))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

"""Decision points for one situation class: first defender facing opponent control.

``t0`` is chosen by a rule that ignores what the defender did next, so the set
of situations is not selected by the choice (see the habit blueprint, section 2).

Situation (perspective team defends -y):
- live play, ball in own half;
- an opponent is within ``OPP_NEAR`` of the ball and arrives before any of us;
- the focal player is our nearest present car to the ball and is goal-side of it.

Choice, read from movement in ``(t0, t0 + CHOICE_WINDOW]``:
- ``challenge``: closes on the ball by more than ``CLOSE_IN``;
- ``shadow``: retreats toward own goal without closing by more than ``HOLD``;
- ``unclear``: anything else. Unclear is a real label, not an error.

Pre-decision fields never use frames after ``t0``. Outcome fields live under
``retrospective`` and must never feed a feature, a situation or a choice label.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .features import rotate, time_to_ball
from .frames import Match

OPP_NEAR = 900.0
CHOICE_WINDOW = 1.0
CLOSE_IN = 600.0
HOLD = 250.0
RETREAT_VY = -200.0
COOLDOWN = 3.0
OUTCOME_S = 3.0
CHOICES = ("challenge", "shadow", "unclear")
DETECTOR_VERSION = "first_defender_vs_control@v1"


@dataclass
class DecisionPoint:
    decision_id: str
    match_id: str
    source: str
    mode: str
    team: int
    focal_index: int
    focal_key: str
    t0: float
    tactical: dict
    geometric: dict
    choice: str
    detector: str = DETECTOR_VERSION
    retrospective: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


TACTICAL_KEYS = (
    "focal_ttb", "opp_ttb", "ttb_adv", "focal_boost", "opp_near_boost", "focal_speed",
    "mate_depth_rel_ball", "mate_goalside", "mate_dist_own_goal", "ball_dist_own_goal",
    "ball_vy", "ball_z", "score_diff", "seconds_remaining", "team_size",
)
GEOMETRIC_KEYS = (
    "ball_x", "ball_y", "ball_z", "ball_vx", "ball_vy", "ball_vz",
    "focal_x", "focal_y", "focal_vx", "focal_vy",
)


def _team_value(m: Match, team: int, i: int) -> float:
    if m.builtin_threat is None:
        return float("nan")
    v = m.builtin_threat[i]
    return float(v[team] - v[1 - team])


def extract_decisions(m: Match) -> list[DecisionPoint]:
    out: list[DecisionPoint] = []
    dt = float(np.median(np.diff(m.t))) if m.n_frames > 1 else 0.1
    win = max(1, int(round(CHOICE_WINDOW / dt)))
    horizon = max(1, int(round(OUTCOME_S / dt)))
    score = m.score_before()
    for team in (0, 1):
        own_idx = np.flatnonzero(m.car_team == team)
        opp_idx = np.flatnonzero(m.car_team != team)
        ball_p = rotate(team, m.ball[:, :3])
        ball_v = rotate(team, m.ball[:, 3:])
        cars_p = rotate(team, m.cars[:, :, :3])
        cars_v = rotate(team, m.cars[:, :, 3:])
        dist = np.where(m.present, np.linalg.norm(cars_p - ball_p[:, None, :], axis=2), np.inf)
        ttb = np.where(m.present, time_to_ball(cars_p, cars_v, ball_p[:, None, :]), np.inf)
        last_t0 = -np.inf
        prev_cond = False
        for i in range(m.n_frames):
            cond = False
            focal = -1
            if m.live[i] and ball_p[i, 1] < 0 and len(own_idx) and len(opp_idx):
                own_t = ttb[i, own_idx]
                opp_t = ttb[i, opp_idx]
                opp_d = dist[i, opp_idx]
                if np.isfinite(own_t).any() and np.isfinite(opp_t).any():
                    focal = int(own_idx[np.argmin(dist[i, own_idx])])
                    cond = (opp_d.min() < OPP_NEAR and opp_t.min() < own_t.min()
                            and cars_p[i, focal, 1] < ball_p[i, 1])
            rising = cond and not prev_cond
            prev_cond = cond
            if not rising or m.t[i] - last_t0 < COOLDOWN or i + win >= m.n_frames:
                continue
            last_t0 = m.t[i]

            mates = [p for p in own_idx if p != focal and m.present[i, p]]
            mate = min(mates, key=lambda p: dist[i, p]) if mates else None
            opp_near = int(opp_idx[np.argmin(dist[i, opp_idx])])
            own_goal = np.array([0.0, -5120.0, 320.0])
            to_ball = ball_p[i] - cars_p[i, focal]
            closing = float(np.dot(cars_v[i, focal], to_ball) / max(np.linalg.norm(to_ball), 1.0))
            tactical = {
                # Momentum at t0. Kept out of TACTICAL_KEYS so retrieval does not use it;
                # the momentum baseline uses it to test whether the choice was already made.
                "focal_closing_speed": closing,
                "focal_vy": float(cars_v[i, focal, 1]),
                "focal_ttb": float(ttb[i, focal]),
                "opp_ttb": float(ttb[i, opp_idx].min()),
                "ttb_adv": float(ttb[i, opp_idx].min() - ttb[i, focal]),
                "focal_boost": float(m.boost[i, focal]),
                "opp_near_boost": float(m.boost[i, opp_near]),
                "focal_speed": float(np.linalg.norm(cars_v[i, focal])),
                "mate_depth_rel_ball": float(cars_p[i, mate, 1] - ball_p[i, 1]) if mate is not None else 0.0,
                "mate_goalside": float(cars_p[i, mate, 1] < ball_p[i, 1]) if mate is not None else 0.0,
                "mate_dist_own_goal": float(np.linalg.norm(cars_p[i, mate] - own_goal)) if mate is not None else 0.0,
                "ball_dist_own_goal": float(np.linalg.norm(ball_p[i] - own_goal)),
                "ball_vy": float(ball_v[i, 1]),
                "ball_z": float(ball_p[i, 2]),
                "score_diff": float(score[i, team] - score[i, 1 - team]),
                "seconds_remaining": float(np.clip(m.seconds_remaining[i], 0, 300)),
                "team_size": float(m.team_sizes[team]),
            }
            geometric = {
                "ball_x": float(ball_p[i, 0]), "ball_y": float(ball_p[i, 1]), "ball_z": float(ball_p[i, 2]),
                "ball_vx": float(ball_v[i, 0]), "ball_vy": float(ball_v[i, 1]), "ball_vz": float(ball_v[i, 2]),
                "focal_x": float(cars_p[i, focal, 0]), "focal_y": float(cars_p[i, focal, 1]),
                "focal_vx": float(cars_v[i, focal, 0]), "focal_vy": float(cars_v[i, focal, 1]),
            }

            # Choice window: allowed to look ahead, by definition of a choice label.
            seg = slice(i + 1, i + win + 1)
            d_seg = dist[seg, focal]
            closed = float(dist[i, focal] - np.min(d_seg[np.isfinite(d_seg)])) if np.isfinite(d_seg).any() else 0.0
            vy_mean = float(np.mean(cars_v[seg, focal, 1]))
            if closed > CLOSE_IN:
                choice = "challenge"
            elif vy_mean < RETREAT_VY and closed < HOLD:
                choice = "shadow"
            else:
                choice = "unclear"

            j = min(i + horizon, m.n_frames - 1)
            v0, v1 = _team_value(m, team, i), _team_value(m, team, j)
            conceded = any(tm != team and m.t[i] < gt <= m.t[i] + 5.0 for gt, tm in m.goals)
            out.append(DecisionPoint(
                decision_id=f"{m.match_id[:12]}:{team}:{m.t[i]:.2f}", match_id=m.match_id,
                source=m.source, mode=m.mode, team=team, focal_index=focal,
                focal_key=m.player_keys[focal] if m.player_keys else f"car{focal}",
                t0=float(m.t[i]), tactical=tactical, geometric=geometric, choice=choice,
                retrospective={"value_t0": v0, "value_after": v1, "value_change": v1 - v0,
                               "value_horizon_s": OUTCOME_S, "value_source": "subtr_actor_builtin_threat",
                               "conceded_within_5s": bool(conceded)},
            ))
    return out


def as_matrix(points: list[DecisionPoint], keys: tuple[str, ...], attr: str) -> np.ndarray:
    return np.array([[getattr(p, attr)[k] for k in keys] for p in points], dtype=float)

"""Replay -> canonical per-frame arrays.

The decoder sits behind ``load_match`` so every downstream module can be tested
with synthetic ``Match`` objects and never needs a real replay.

Conventions (checked against subtr-actor-py 1.5.1 on real replays):
- Team 0 spawns at -y and attacks +y.
- ndarray player columns are ordered team_zero players, then team_one players.
- ndarray ``current time`` and stats-timeline/event ``time`` share one clock.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

FPS = 10.0
BOOST_RAW_MAX = 255.0


@dataclass(frozen=True)
class Match:
    """One replay, resampled to a fixed frame rate.

    Arrays are indexed by frame ``i``. ``cars`` is (N, P, 6): position xyz then
    velocity xyz, in world coordinates. ``boost`` is (N, P) on a 0-100 scale.
    ``builtin_threat`` is (N, 2): the decoder's five-second scoring threat for
    team 0 and team 1, held from its last update (causal), NaN where unknown.
    """

    match_id: str
    source: str
    team_sizes: tuple[int, int]
    t: np.ndarray
    live: np.ndarray
    ball: np.ndarray
    cars: np.ndarray
    boost: np.ndarray
    present: np.ndarray
    car_team: np.ndarray
    seconds_remaining: np.ndarray
    goals: tuple[tuple[float, int], ...]
    player_keys: tuple[str, ...] = ()
    builtin_threat: np.ndarray | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def n_frames(self) -> int:
        return int(self.t.shape[0])

    @property
    def mode(self) -> str:
        a, b = self.team_sizes
        return f"{a}v{b}"

    def score_before(self) -> np.ndarray:
        """(N, 2) goals scored strictly before each frame's time."""
        out = np.zeros((self.n_frames, 2), dtype=np.int16)
        for gt, team in self.goals:
            out[self.t > gt, team] += 1
        return out


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def anonymize(name: str) -> str:
    return "p_" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:10]


def dedupe(matches: list[Match]) -> tuple[list[Match], list[str]]:
    """Drop byte-identical replays. A duplicate in two folds leaks the test set."""
    seen: set[str] = set()
    kept, dropped = [], []
    for m in matches:
        if m.match_id in seen:
            dropped.append(m.source)
            continue
        seen.add(m.match_id)
        kept.append(m)
    return kept, dropped


MAX_HOLD_S = 0.5


def _step_hold(src_t: np.ndarray, src_v: np.ndarray, dst_t: np.ndarray,
               max_age: float = MAX_HOLD_S) -> np.ndarray:
    """Value of the most recent source sample at or before each destination time.

    Samples older than ``max_age`` are not carried forward. Without this cap the
    last threat value before a goal (often near 1.0) leaks into the next kickoff.
    """
    out = np.full(dst_t.shape, np.nan)
    if src_t.size == 0:
        return out
    order = np.argsort(src_t, kind="stable")
    st, sv = src_t[order], src_v[order]
    idx = np.searchsorted(st, dst_t, side="right") - 1
    ok = idx >= 0
    ok[ok] = (dst_t[ok] - st[idx[ok]]) <= max_age
    out[ok] = sv[idx[ok]]
    return out


def load_match(path: str | Path, cache_dir: str | Path | None = None, fps: float = FPS) -> Match:
    """Decode one replay with subtr-actor and return a canonical ``Match``.

    Results are cached as ``<sha256>.npz`` so experiments do not re-run the decoder.
    """
    path = Path(path)
    sha = file_sha256(path)
    if cache_dir is not None:
        cache = Path(cache_dir) / f"{sha}.npz"
        if cache.exists():
            return _from_npz(cache, path.name)

    import subtr_actor  # imported lazily: tests never need the decoder

    meta, arr = subtr_actor.get_ndarray_with_info_from_replay_filepath(
        str(path),
        ["BallRigidBody", "CurrentTime", "SecondsRemaining"],
        ["PlayerRigidBody", "PlayerBoost"],
        fps,
    )
    gh = meta["column_headers"]["global_headers"]
    ph = meta["column_headers"]["player_headers"]
    rm = meta["replay_meta"]
    n0, n1 = len(rm["team_zero"]), len(rm["team_one"])
    n_players = n0 + n1
    g = len(gh)
    if arr.shape[1] != g + len(ph) * n_players:
        raise ValueError(f"unexpected column count {arr.shape[1]} for {n_players} players")

    def gcol(name: str) -> np.ndarray:
        return arr[:, gh.index(name)].astype(np.float64)

    t = gcol("current time")
    ball = np.stack([gcol(f"Ball - {k}") for k in (
        "position x", "position y", "position z",
        "linear velocity x", "linear velocity y", "linear velocity z")], axis=1)
    sec_rem = gcol("seconds remaining")
    pcols = {k: ph.index(k) for k in ph}
    cars = np.zeros((arr.shape[0], n_players, 6))
    boost = np.zeros((arr.shape[0], n_players))
    for p in range(n_players):
        base = g + len(ph) * p
        for j, k in enumerate(("position x", "position y", "position z",
                               "linear velocity x", "linear velocity y", "linear velocity z")):
            cars[:, p, j] = arr[:, base + pcols[k]]
        boost[:, p] = arr[:, base + pcols["boost level (raw replay units)"]] * 100.0 / BOOST_RAW_MAX
    # The decoder places absent (demolished / not yet spawned) cars at the origin.
    present = ~np.all(np.abs(cars[:, :, :3]) < 1e-3, axis=2)
    car_team = np.array([0] * n0 + [1] * n1, dtype=np.int8)
    names = [str(x.get("name", f"player{i}")) for i, x in enumerate(rm["team_zero"] + rm["team_one"])]

    timeline = subtr_actor.get_stats_timeline(str(path), None, 1.0 / fps, True)
    tl_frames = timeline["frames"]
    tl_t = np.array([f["time"] for f in tl_frames], dtype=np.float64)
    tl_live = np.array([bool(f.get("is_live_play")) for f in tl_frames])
    tl_fn = np.array([f["frame_number"] for f in tl_frames], dtype=np.float64)
    nearest = np.clip(np.searchsorted(tl_t, t), 0, len(tl_t) - 1)
    live = tl_live[nearest]

    threat = np.full((t.shape[0], 2), np.nan)
    for team_track in timeline.get("expected_goals_tracks", {}).get("teams", []):
        col = 0 if team_track.get("is_team_0") else 1
        pts = [(p["frame"], p["stats"].get("current_threat")) for p in team_track.get("points", [])]
        pts = [(fr, v) for fr, v in pts if v is not None]
        if pts:
            fr = np.array([p[0] for p in pts], dtype=np.float64)
            vals = np.array([p[1] for p in pts], dtype=np.float64)
            src_t = np.interp(fr, tl_fn, tl_t)
            threat[:, col] = _step_hold(src_t, vals, t)

    events = subtr_actor.get_stats_events(str(path))["events"]
    goals = tuple(sorted(
        (float(e["meta"]["timing"]["time"]), 0 if e["meta"].get("team_is_team_0") else 1)
        for e in events if e["meta"]["stream"] == "goal_context"
    ))
    notes = []
    headers = dict(rm["all_headers"]) if rm.get("all_headers") else {}
    for team, key in ((0, "Team0Score"), (1, "Team1Score")):
        reported = headers.get(key)
        found = sum(1 for _, tm in goals if tm == team)
        if reported is not None and int(reported) != found:
            notes.append(f"team{team}: header score {reported} but {found} goal events")

    m = Match(
        match_id=sha, source=path.name, team_sizes=(n0, n1), t=t, live=live, ball=ball,
        cars=cars, boost=boost, present=present, car_team=car_team,
        seconds_remaining=sec_rem, goals=goals,
        player_keys=tuple(anonymize(n) for n in names), builtin_threat=threat, notes=tuple(notes),
    )
    if cache_dir is not None:
        _to_npz(m, Path(cache_dir) / f"{sha}.npz")
    return m


def _to_npz(m: Match, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "match_id": m.match_id, "team_sizes": list(m.team_sizes), "goals": [list(g) for g in m.goals],
        "player_keys": list(m.player_keys), "notes": list(m.notes),
    }
    np.savez_compressed(
        out, header=np.array(json.dumps(header)), t=m.t, live=m.live, ball=m.ball, cars=m.cars,
        boost=m.boost, present=m.present, car_team=m.car_team,
        seconds_remaining=m.seconds_remaining,
        builtin_threat=m.builtin_threat if m.builtin_threat is not None else np.empty((0, 2)),
    )


def _from_npz(path: Path, source: str) -> Match:
    z = np.load(path, allow_pickle=False)
    h = json.loads(str(z["header"]))
    bt = z["builtin_threat"]
    return Match(
        match_id=h["match_id"], source=source, team_sizes=tuple(h["team_sizes"]), t=z["t"],
        live=z["live"].astype(bool), ball=z["ball"], cars=z["cars"], boost=z["boost"],
        present=z["present"].astype(bool), car_team=z["car_team"],
        seconds_remaining=z["seconds_remaining"],
        goals=tuple((float(a), int(b)) for a, b in h["goals"]),
        player_keys=tuple(h["player_keys"]), builtin_threat=bt if bt.size else None,
        notes=tuple(h["notes"]),
    )

"""Tests for physics-based commitment window detector."""
import math
import pytest

from coach_app.commitment_detector import (
    CommitmentWindow,
    detect_commitment_window,
    MAX_BRAKING_DECEL,
)
from tests.test_decision_cases_real_replay import get_replay_dir


def test_synthetic_commitment_window_with_jump():
    """Verify that jumping into a challenge establishes an irreversible commitment."""
    frames = [
        # Neutral cruising at 1000 cm/s
        {"t": 10.0, "cars": {"p1": {"x": 0, "y": -2000, "z": 17, "velocity": [0, 1000, 0], "boost": 80}}, "ball": {"x": 0, "y": 0, "z": 92}},
        {"t": 10.2, "cars": {"p1": {"x": 0, "y": -1800, "z": 17, "velocity": [0, 1000, 0], "boost": 80}}, "ball": {"x": 0, "y": 0, "z": 92}},
        # t=10.4: Accelerates and boosts into challenge (intention onset)
        {"t": 10.4, "cars": {"p1": {"x": 0, "y": -1580, "z": 17, "velocity": [0, 1400, 0], "boost": 78}}, "ball": {"x": 0, "y": 0, "z": 92}},
        {"t": 10.6, "cars": {"p1": {"x": 0, "y": -1280, "z": 17, "velocity": [0, 1600, 0], "boost": 75}}, "ball": {"x": 0, "y": 0, "z": 92}},
        # t=10.8: Executes jump (ballistic lock)
        {"t": 10.8, "cars": {"p1": {"x": 0, "y": -940, "z": 35, "jumpActive": True, "velocity": [0, 1700, 300], "boost": 70}}, "ball": {"x": 0, "y": 0, "z": 92}},
        {"t": 11.0, "cars": {"p1": {"x": 0, "y": -580, "z": 70, "jumpActive": True, "velocity": [0, 1800, 200], "boost": 65}}, "ball": {"x": 0, "y": 0, "z": 92}},
    ]

    window = detect_commitment_window(frames, "p1", t_contest_start=11.2)
    assert window.t_earliest <= 10.4
    assert window.t_latest == 10.8
    assert window.primary_constraint == "jump_airborne_lock"
    assert window.t_earliest <= window.t_latest


def test_synthetic_stopping_distance_commitment():
    """Verify ground point-of-no-return when distance < v^2 / (2 * a_brake)."""
    # At speed 2000 cm/s, stopping distance is 2000^2 / 7000 = 571 cm
    frames = [
        {"t": 5.0, "cars": {"p1": {"x": 0, "y": -1500, "z": 17, "velocity": [0, 1800, 0], "boost": 50}}, "ball": {"x": 0, "y": 0, "z": 92}},
        # At t=5.3, dist=600 > 571 (can still brake and stop before ball)
        {"t": 5.3, "cars": {"p1": {"x": 0, "y": -600, "z": 17, "velocity": [0, 2000, 0], "boost": 45}}, "ball": {"x": 0, "y": 0, "z": 92}},
        # At t=5.5, dist=300 < 571 (impossible to stop before ball: physical commitment)
        {"t": 5.5, "cars": {"p1": {"x": 0, "y": -300, "z": 17, "velocity": [0, 2000, 0], "boost": 40}}, "ball": {"x": 0, "y": 0, "z": 92}},
    ]

    window = detect_commitment_window(frames, "p1", t_contest_start=5.6)
    assert window.t_latest <= 5.5
    assert window.primary_constraint == "stopping_distance_exceeded"


def test_real_replay_commitment_window_vs_fixed_offset():
    """Verify that on real match replays, commitment window identifies earlier decisions than naive t_contact - 0.4s."""
    replay_dir = get_replay_dir()
    replay_path = replay_dir / "23A661D44DBC5964B0718DBC5F956A33.replay"
    if not replay_path.exists():
        pytest.skip(f"Real replay not found at {replay_path}")

    from coach_app.subtr_replays import parse_subtr_replay
    rep = parse_subtr_replay(replay_path)
    frames = rep["frames"]

    fifties = [e for e in rep["events"] if e.get("type") == "fifty_fifty" and not e.get("isKickoff")]
    assert len(fifties) > 5

    deltas = []
    for f in fifties[:10]:
        t_contest = f.get("startTime") or f.get("t")
        p0 = f.get("teamZeroPlayerId")
        if not p0:
            continue
        window = detect_commitment_window(frames, p0, t_contest)
        fixed_t0 = round(t_contest - 0.4, 3)

        assert window.t_earliest <= window.t_latest
        assert window.t_latest <= t_contest + 0.05
        # The true decision point (earliest agency) should be earlier than or equal to fixed offset
        deltas.append(fixed_t0 - window.t_earliest)

    avg_earlier_s = sum(deltas) / len(deltas)
    # On average, commitment window identifies decisions 0.3s to 1.5s earlier than naive retrospective offset!
    assert avg_earlier_s >= 0.2, f"Expected earlier commitment detection, got {avg_earlier_s:.3f}s"

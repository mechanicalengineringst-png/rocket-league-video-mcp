"""Test camera interpolation ablation mathematics and discontinuity gating."""
from __future__ import annotations

import math
import numpy as np
import pytest

from scripts.benchmark_camera_interpolation import (
    euler_to_quaternion,
    quat_slerp,
    quat_to_euler,
    hermite_cubic,
    compute_shortest_arc_angular_metrics,
    compute_vector_jerk,
)


def test_euler_to_quaternion_and_back():
    pitch, yaw, roll = 15.0, 45.0, -30.0
    q = euler_to_quaternion(pitch, yaw, roll)
    norm = np.linalg.norm(q)
    assert abs(norm - 1.0) < 1e-6

    p_out, y_out, r_out = quat_to_euler(q)
    assert abs(p_out - pitch) < 1e-4
    assert abs(y_out - yaw) < 1e-4
    assert abs(r_out - roll) < 1e-4


def test_quat_slerp_halfway():
    q0 = euler_to_quaternion(0.0, 0.0, 0.0)
    q1 = euler_to_quaternion(0.0, 90.0, 0.0)
    q_mid = quat_slerp(q0, q1, 0.5)

    p, y, r = quat_to_euler(q_mid)
    assert abs(p - 0.0) < 1e-4
    assert abs(y - 45.0) < 1e-4
    assert abs(r - 0.0) < 1e-4


def test_shortest_arc_angular_metrics():
    # Rotate around Z by 90 deg over 1 second (4 steps of 0.25s)
    dt = 0.25
    quats = [
        euler_to_quaternion(0.0, 0.0, 0.0),
        euler_to_quaternion(0.0, 22.5, 0.0),
        euler_to_quaternion(0.0, 45.0, 0.0),
        euler_to_quaternion(0.0, 67.5, 0.0),
        euler_to_quaternion(0.0, 90.0, 0.0),
    ]
    quats = np.array(quats)
    metrics = compute_shortest_arc_angular_metrics(quats, dt)
    assert abs(metrics["mean_ang_vel_deg_s"] - 90.0) < 1e-2
    assert metrics["anomalous_gimbal_inversions"] == 0


def test_hermite_cubic_smoothness():
    p0 = np.array([0.0, 0.0, 0.0])
    v0 = np.array([100.0, 0.0, 0.0])
    p1 = np.array([100.0, 0.0, 0.0])
    v1 = np.array([100.0, 0.0, 0.0])
    dt = 1.0

    # At t=0, pos is p0
    assert np.allclose(hermite_cubic(p0, v0, p1, v1, dt, 0.0), p0)
    # At t=1, pos is p1
    assert np.allclose(hermite_cubic(p0, v0, p1, v1, dt, 1.0), p1)
    # At t=0.5, pos is exactly midpoint under constant velocity
    assert np.allclose(hermite_cubic(p0, v0, p1, v1, dt, 0.5), [50.0, 0.0, 0.0])

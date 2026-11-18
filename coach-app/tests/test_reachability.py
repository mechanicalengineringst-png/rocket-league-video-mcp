"""Kinematic reachability engine (Round 5, checkpoint 2). Synthetic fixtures only.

These check physical sanity and honesty rules. Real-replay accuracy is measured
separately by scripts/benchmark_reachability.py against held-out touch events.
"""
from __future__ import annotations

from coach_app.reachability import baseline_reach, climb_time, estimate_reach, max_curvature, throttle_accel

BALL = {"x": 0.0, "y": 0.0, "z": 93.0, "velocity": [0.0, 0.0, 0.0]}


def car(x=0.0, y=-2000.0, fx=0.0, fy=1.0, vx=0.0, vy=0.0, boost=50.0, z=17.0, fz=0.0):
    return {"x": x, "y": y, "z": z, "velocity": [vx, vy, 0.0], "forward": [fx, fy, fz], "boost": boost}


def test_published_constants():
    assert throttle_accel(0) == 1600 and throttle_accel(1410) == 0
    assert max_curvature(0) == 0.0069 and abs(max_curvature(2300) - 0.00088) < 1e-9


def test_standing_start_with_boost_is_realistic():
    r = estimate_reach(car(), BALL)
    assert r.status == "ok" and 1.2 <= r.t_min <= 1.7          # ~1850 uu from rest with boost
    assert r.approach == "drive"


def test_fast_car_facing_away_gets_a_bounded_time_not_the_baseline_cap():
    """Round 4's failure: a fast car pointing away got an absurd arrival time."""
    c = car(fy=-1.0, vy=-2200.0)
    assert baseline_reach(c, BALL) >= 4.0
    r = estimate_reach(c, BALL)
    assert r.status == "ok" and r.t_min < 3.5


def test_no_boost_is_slower_and_farther_is_not_faster():
    assert estimate_reach(car(boost=0.0), BALL).t_min > estimate_reach(car(boost=60.0), BALL).t_min
    assert estimate_reach(car(y=-4000.0), BALL).t_min >= estimate_reach(car(y=-2000.0), BALL).t_min


def test_ball_rolling_toward_the_car_is_reached_sooner():
    toward = dict(BALL, velocity=[0.0, -1000.0, 0.0])
    assert estimate_reach(car(), toward).t_min < estimate_reach(car(), BALL).t_min


def test_unknown_boost_is_reported_not_assumed():
    r = estimate_reach(car(boost=None), BALL)
    assert r.status == "ok" and any("boost unknown" in u for u in r.unknowns)
    assert r.t_max is None or r.t_max >= r.t_min


def test_cars_on_walls_demolished_or_without_orientation_abstain():
    assert estimate_reach(car(x=4050.0, z=600.0), BALL).status == "abstain"
    assert estimate_reach(dict(car(), demolished=True), BALL).reason == "car demolished at t0"
    no_heading = car()
    no_heading.pop("forward")
    assert estimate_reach(no_heading, BALL).reason == "car orientation unknown at t0"
    assert estimate_reach(car(), {"x": 0, "y": 0, "z": 93}).reason == "ball velocity unknown at t0"


def test_airborne_car_gets_an_interval():
    r = estimate_reach(car(z=400.0, fz=0.5, vy=800.0), dict(BALL, z=600.0))
    assert r.status == "ok" and r.t_min is not None
    assert r.t_max is None or r.t_max >= r.t_min
    assert any("Airborne" in a for a in r.assumptions)


def test_raised_balls_need_a_jump_and_high_ones_need_boost():
    assert climb_time(120, 0)[1] == "ground"
    t, how = climb_time(300, 0)
    assert how in ("single jump", "double jump") and t < 0.5
    assert climb_time(900, 0) == (None, "aerial needs boost")
    assert climb_time(900, 50)[1] == "aerial"


def test_car_touching_the_ball_now_is_zero():
    r = estimate_reach(car(y=-150.0), BALL)
    assert r.t_min == 0.0 and r.approach == "already at the ball"


def test_only_the_given_t0_state_is_read():
    """The estimator takes single-frame dicts; identical inputs give identical outputs."""
    a, b = estimate_reach(car(), BALL).to_dict(), estimate_reach(car(), dict(BALL)).to_dict()
    assert a == b

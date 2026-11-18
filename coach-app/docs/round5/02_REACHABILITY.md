# Round 5, checkpoint 2: kinematic reachability engine

`coach_app/reachability.py` replaces Round 4's "distance over a clamped closing speed". For one car at t0 it asks: what is the earliest moment this car could touch the ball, by which approach, and under what assumptions?

## What it models

- **Car state at t0 only:** position, velocity, heading (from the rotation-derived forward vector), boost, and an inferred mode (ground / air / wall).
- **Ground physics:** throttle curve, boost, braking, maximum curvature by speed.
- **Several approaches per car, fastest wins:** drive, brake-and-turn, powerslide turn, forward dodge, half-flip.
- **Raised balls:** single jump, double jump or boosted aerial; the lower bound assumes the climb is timed to finish on arrival.
- **Airborne cars:** an interval between "keep flying at the ball" and "land on the ballistic arc, then drive".
- **The ball moves:** gravity, drag and bounces; the answer is the earliest time T at which the car can be where the ball is at T.
- **Unknowns stay unknown:** unknown boost gives both bounds; missing orientation, demolished cars and cars on walls abstain.

## How it was measured

On the 15 real 2v2 replays, every 1 s of live play, for every car: the estimate uses the t0 frame only. The **held-out label** is the time until that car's next decoder `touch` event (within 4 s, excluding resets). A car cannot touch the ball sooner than physically possible, so a correct estimate is a **lower bound** on the label. Three measures follow: how often the bound is broken (a violation, beyond a 0.1 s tolerance), how loose it is, and whether the smallest estimate picks the car that touched first.

Command: `python scripts/benchmark_reachability.py REPLAY_DIR docs/round5/results/reachability_benchmark.json CACHE_DIR` (80 s for 18,132 car-moments).

| Measure (5,783 car-moments with a touch label and an estimate) | Round 4 baseline | New engine |
|---|---|---|
| Lower bound broken (car touched sooner than "possible") | 1,596 (27.6%) | **332 (5.7%)** |
| Baseline-style absurd estimates: over 4 s while the car touched within 2 s | 96 | **0** |
| Label minus estimate, all: p10 / median / p90 | −1.51 / 0.27 / 2.11 s | **−0.02** / 0.42 / 1.97 s |
| Same, touches within 1.5 s: p10 / median / p90, mean abs | −0.51 / 0.06 / 0.74, 0.43 s | **−0.05** / 0.11 / 0.52, **0.23 s** |
| Picks the first car to touch (2,493 moments, 4 cars, chance 25%) | 59.6% | **67.4%** |

Abstentions: 1,333 car-moments on a wall, 120 demolished. 51 cars touched the ball although no modelled approach reached it within 4 s (mostly passive touches and wall plays).

**Turning-limit check against the replays.** Over 0.2 s windows, ground cars turned tighter than the published no-slide limit in 8–18% of windows depending on speed (p95 ratio 1.13–1.36). That is powerslide, so a powerslide approach at 1.35× curvature was added; violations dropped from 401 to 332 when it was.

## Where it is still wrong

- **Violations by approach:** brake-and-turn 10/13, land-and-drive 4/6, half-flip 6/52, drive 143/2,208, powerslide 98/1,211, aerial continuation 43/1,525, dodge 28/336, already-at-ball 0/432. The brake-and-turn and landing models are the weakest.
- **Touch labels include passive contacts** (the ball hitting a car that wasn't trying), so some "violations" are not the model's fault. They are reported anyway.
- **The bound is loose when players aren't hurrying** (median 0.42 s). That's expected for a feasibility bound, but it means "could have reached" is not "should have gone".
- **Not modelled:** wall driving, aerial steering, speed lost in powerslides, bumps and blocking by other cars. 30 Hz frames repeat network states, so t0 states can be up to ~0.07 s stale.
- **All 15 replays are the decoder's public test files** of unknown rank. GC/SSL mechanics (faster recoveries, flip resets) will break the bound more often; that must be re-measured on high-rank replays.

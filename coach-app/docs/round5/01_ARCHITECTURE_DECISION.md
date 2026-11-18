# Round 5, checkpoint 1: how should the coach get more realistic?

Five candidate architectures were compared on four questions: can it be built now, what data does it need, where does uncertainty enter, and what small experiment could prove it wrong. Each claim below is checked in this session or comes from earlier measured work (PR #17); none is from expert ratings, because there are none yet.

## What was checked before deciding

- **RocketSim is installable but can't run a real arena here.** `pip install rocketsim` (2.2.1, MIT, 0.6 MB) works, but `Arena(GameMode.SOCCAR)` fails: *"No arena meshes found… should be in ./collision_meshes/"*. The meshes are dumped from a local Rocket League install (RLArenaCollisionDumper) and can't be redistributed. `THE_VOID` mode runs but has no floor: a car fell from z=36 to z=−292 in one second. So **simulation needs a one-time mesh dump on Sam's PC**; it can't be the cloud default.
- **The replay frames carry what a kinematic model needs:** position, velocity, a forward vector from rotation, boost and a jump flag, at 30 Hz (`subtr_replays.py`). Angular velocity and wheel contact are not exported, so "on ground" must be inferred.
- **The decoder emits `touch` events per player** (185 in one 2v2 match), which give held-out arrival labels without hand annotation. It also emits its own `shadow_defense` events (56 in that match), useful as an outside comparison for Part D.
- **PR #17 already measured the learned and retrieval options** on 36 decoder test matches (14 2v2): the decoder's built-in threat model beat a LightGBM trained here (Brier skill 0.278 vs 0.186); retrieval neighbours predicted *what players chose*, not *what happened next* (R² ≈ 0); 0 of 11,628 player pairs were statistically distinguishable at a median of 6 decisions per player.

## Comparison

| Approach | Buildable now? | Data it needs / has | Where uncertainty enters | Experiment that could disprove it |
|---|---|---|---|---|
| **1. Kinematic feasibility** (turn radius by speed, throttle/boost curves, braking, jump and dodge timing, several approaches per car) | Yes, pure Python | Frames at t0 (have); touch events as labels (have) | Ignores powerslide fine control, wall driving, aerial control, bumps; "on ground" inferred | If its arrival bound is **violated** (car arrives faster than the bound) as often as the distance/speed baseline, or it ranks first-to-ball no better, it adds nothing. |
| **2. RocketSim forward simulation** | Only with meshes from Sam's PC | Valid initial states need angular velocity and wheel contact, which the frames lack; must be reconstructed | Initial-state error grows fast; control inputs are unknown, so you simulate a *policy*, not the player | Replay a real 1.0 s clip from its t0 state with inputs inferred from the next frames; if position error at 0.5 s exceeds a car length most of the time, it can't validate counterfactuals either. |
| **3. Retrieval against high-level situations** | Code exists (PR #17) | Needs a licensed corpus of GC/SSL/pro 2v2 replays with ranks; we have 15 unranked 2v2 matches | Situation similarity ≠ tactical similarity (37% vs 58% context match in #17) | #17 already did: neighbours don't predict outcomes. It can still show "what players like you usually do", which is a description, not a judgement. |
| **4. Learned policy/value model** | Value: yes, the decoder's; policy: no | Policy needs thousands of labelled decisions per situation type | Learns outcome correlations, so it inherits the "goal followed, therefore good" fallacy | #17: our trained model lost to the decoder's own. A policy trained on 15 matches would fail grouped-by-match validation. |
| **5. Hybrid**: measured state + feasibility envelope + human-calibrated interpretation | Yes, incrementally | Feasibility from (1), later (2); interpretation thresholds from #16 blind ratings | Concentrated in one place: interpretation, which is exactly what experts rate | If experts rating the same clips disagree with each other as much as with the coach (#16's two-rater overlap), no interpretation layer can be calibrated, and the coach should only describe. |

## Decision

**Build the hybrid (5), with kinematic feasibility (1) as its physical layer now and RocketSim (2) as a drop-in backend later.**

- The feasibility layer answers *what was possible* with an interval and the approach that achieves it, never a single number. It is testable right now against touch labels, and the same benchmark will judge a RocketSim backend when meshes exist.
- *What the player chose* comes from retrospective classifiers kept apart from t0 evidence (Round 4 invariant).
- *Whether it was good* stays a labelled hypothesis until #16 ratings exist. Thresholds come from those ratings, not from hand-tuning.
- Retrieval (3) is kept for one narrow, honest use: "how often players in similar spots chose X", with counts. A learned value model (4) is limited to the decoder's validated threat model.

**What would change this decision:** RocketSim reproducing real 1 s trajectories within a car length (then it replaces the kinematic layer for ground play), or a licensed high-rank replay corpus of several hundred matches (then retrieval can be revisited as a calibration source).

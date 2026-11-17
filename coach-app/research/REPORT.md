# Tactical intelligence: research report and prototypes

Branch `research/claude-tactical-intelligence-20261117`, based on `integration/replay-lab-unified-test-20261117` (2cc5852).
Everything lives in `coach-app/research/`. No backend or evaluation file was edited.

Labels used throughout: **Measured** = produced by code in this branch on real replays this session.
**Reported** = a number another project publishes, which I did not reproduce. **Inference** = my judgement.

## 0. Measured results

**Corpus.** The decoder's own MIT-licensed test replays: 46 files, of which 4 fail to decode, 1 is a byte-identical
duplicate, 4 are 1v0 training drills and 1 is a private match whose 21 goal events do not reconcile with its 6–4 header
score. That leaves **36 matches: 14 in 2v2, 6 in 1v1, 16 in 3v3**, and 210,748 team-perspective live frames at 10 Hz.
A pilot, not a training set. Every number below is grouped by match: five-fold out-of-fold predictions, and 95%
intervals from 500 match-level bootstrap resamples. Full outputs are in [`results/`](results/).

### Prototype 1: who predicts a goal in the next 5 seconds?

Head to head on identical rows: the 2v2 matches, 82,292 frames, 4,932 positive. The built-in model only exists for 2v2.

| System | Brier skill vs base rate (95% CI) | AUC | Calibration error |
|---|---|---|---|
| **subtr-actor built-in threat model, as shipped** | **0.278** (0.249–0.305) | **0.893** | 0.009 |
| Same, recalibrated on our training folds | 0.275 (0.239–0.306) | 0.892 | 0.003 |
| LightGBM trained here, full features | 0.186 (0.148–0.217) | 0.859 | 0.007 |
| Logistic regression trained here | 0.182 (0.148–0.212) | 0.850 | 0.009 |
| Rule-based danger heuristic, isotonic-calibrated | 0.112 (0.085–0.138) | 0.806 | 0.005 |
| Base rate | 0 | n/a | 0.006 |

- **The shipped model wins clearly** (Brier gap to our LightGBM 0.0037–0.0064, interval excludes zero). **Measured.**
  Its AUC here, 0.89, is close to the 0.91 its authors **report** on their own held-out set, and it is well calibrated
  without any adjustment: its 0.9–1.0 bin predicts 0.964 and observes 0.991.
- **The rule heuristic captures less than half of the shipped model's skill.** That is the ceiling of rule-style
  coaching on this target. **Measured.**
- **Off-ball features help a little.** Adding goal-side counts, last-defender depth, second-man arrival and team boost
  to ball-only features lifts skill from 0.149 to 0.186; the Brier difference interval (−0.0034 to −0.0008) excludes
  zero. **Measured.**
- **Outside 2v2 there is no shipped model.** Ours is the only calibrated option: Brier skill 0.284 (0.264–0.299) in
  1v1 over 6 matches and 0.120 (0.080–0.150) in 3v3 over 16. Six 1v1 matches is far too few to ship.
- **A bug worth knowing about.** My first adapter held the last pre-goal threat value across the stoppage into the next
  kickoff, which produced 0.998 "false alarms" at centre field. Capping the hold at 0.5 s fixed it (test included).
  Anyone reading `current_threat` must do the same.
- **Failure cases now look like the game, not artifacts**: top false alarms are balls within 1,500 uu of goal that were
  saved; top misses are goals that started in the scorer's own half, which a 5-second horizon cannot foresee.
  Listed with replay and time in `results/failure_cases.json` for human review.

### Prototype 2: does "comparable" mean anything?

2,066 decision points for "first defender facing an attacker in control" across 36 matches; 784 in 2v2. The movement
rule read **52% of choices as unclear** (1,066 of 2,066). Leave-one-match-out, k = 15. 2v2 figures shown; all-mode
figures in `results/retrieval.json` point the same way.

| Representation | Choice log-loss gain vs base rate (95% CI) | Accuracy on readable choices | Neighbours share the query's tactical context | Predicts value change (R², 95% CI) |
|---|---|---|---|---|
| Geometric (ball + defender position, velocity) | **0.216** (0.174–0.249) | **0.775** | 0.373 | 0.024 (−0.033–0.079) |
| Tactical (arrival times, cover, boost, score) | 0.127 (0.097–0.160) | 0.640 | **0.577** | −0.013 (−0.078–0.055) |
| Learned metric (NCA on both) | 0.127 (0.086–0.168) | 0.659 | 0.552 | −0.011 (−0.065–0.044) |
| Diagnostic: defender velocity only | 0.107 (0.081–0.134) | 0.643 | 0.242 | −0.060 (−0.098 to −0.033) |
| Majority choice | 0 | 0.627 | 0.169 if random | 0 |
| App-style rule: "challenge if you arrive within 0.3 s" | n/a | 0.376 | n/a | n/a |

What this shows. **Measured**, with interpretation marked:

1. **Retrieval predicts what players do, not what happens next.** No representation's neighbours predict the query's
   value change better than the mean. Single outcomes are too noisy, which is the habit argument again.
2. **The two jobs need two representations.** Geometry predicts the choice best but returns tactically different
   situations: neighbours share the query's context 37% of the time, against 58% for tactical features. Use geometry
   for a behaviour model and tactical features for showing a player comparable clips.
3. **Much of the choice is set before the trigger fires.** The defender's velocity alone predicts the choice as well as
   the whole tactical feature set. *Inference:* players commit before the moment this detector calls a decision.
4. **The arrival-time rule describes players worse than guessing the majority.** Either the rule is wrong about how
   strong players defend, or my time-to-ball estimate is too crude to support it. Both are reasons not to coach from it.
5. **The learned metric did not beat hand-built tactical features** at this sample size.

### Contract and blind evaluation

All 784 exported 2v2 cases and predictions pass PR #16's own scorer (`replay-lab-blind-benchmark-v1`) unmodified,
with 0 citation errors. Every prediction **abstains**: 406 because the choice was unreadable, 378 because fewer than 30
comparable decisions existed for an alternative. That is the correct output for single moments at this sample size.

### Personal adaptation

153 anonymized players, median 6 readable decisions each, only 3 with 20 or more (maximum 37). The fitted prior hits
its strength cap of 200: between-player variation in challenge share is too small to see at these sample sizes.
**0 of 11,628 player pairs are distinguishable.** A language model given one player's 6 decisions would still
produce a confident description of their style. This is the measured case for statistical profiles.

## 1. Ranked architecture candidates

| Rank | Architecture | Status in this branch | Why it ranks here |
|---|---|---|---|
| 1 | **Validated threat model + matched habit comparisons.** The decoder's threat model scores every frame; decisions are compared by the value change that follows, aggregated over many matched cases | Prototype 1 validates the model; `decisions.py` produces the value change per decision | Best measured predictor here, free, already in our decoder, runs in the browser via WASM. Turns "was that good?" into a testable average over cases |
| 2 | **Human behaviour model**: a distribution over what high-level players choose in a situation | Prototype 2 approximates it with retrieval; a learned policy needs the 445 GB corpus | The only component that can say "strong players split 60/40 here", which is how style disagreement becomes visible instead of being called a mistake |
| 3 | **Retrieval of comparable human decisions** with a tactical representation | Prototype 2 | Measured to find context-matched situations far better than geometry. Its teaching value is unmeasured until humans rate the clips |
| 4 | **Physics-bounded feasibility checks** (RocketSim, about 1 s) | Not built | Needed before any alternative is suggested. Answers "could you have got there", not "should you have" |
| 5 | **Learned spatiotemporal encoders** (graph networks, transformers) | Rejected for now | The built-in model already is a permutation-invariant entity network. A bigger encoder needs the large corpus and has no target that is known to improve coaching |
| 6 | **Offline action-value estimation** (Q-learning from observational replays) | Rejected for now | Velocity alone predicts the choice as well as all tactical features (section 0), so the action is entangled with the state at t0. Single-moment action values would be confidently wrong |
| 7 | **Simulated rollouts with a trained bot** | Rejected for now | No open human-like high-rank bot; bot continuations are not human continuations (earlier report, section 6) |
| 8 | **Language or vision-language model as judge** | Rejected as judge | Its jobs: narrate `explanation_payload()` without adding facts, and interview the player about intent. A vision model has one unique job: what was on the player's screen |

## 2. What the current design cannot do

The app's rules decide from distances at one frame. Each distinction in the brief needs something the rules do not have:

| Distinction | What it actually needs | Available now? |
|---|---|---|
| Clever vs unnecessary challenge | The value change that follows each choice, averaged over matched situations | Yes, with the threat model, at habit level only |
| Deliberate 50/50 loss vs mechanical failure | Intent | No. Only the player can say. Team possession after the 50/50 is measurable, intent is not |
| Aggressive support vs double commit | Teammate positions and the value change that followed, over many cases | Partly. Single cases are not judgeable |
| Strong positioning vs merely behind the ball | A target that credits prevented chances. Goal-based targets barely see off-ball play (section 4) | No |
| Decision vs execution | A choice label plus the expected value of that choice; execution is the residual | Only once choice labels are reliable. Today 52% are unreadable |
| Justified risk vs preventable mistake | The spread of outcomes for each choice, not just its mean | Yes in principle; sample sizes are the limit |
| Valid styles vs universal errors | The human behaviour model, to see where strong players split | Approximated by retrieval |

## 3. Personal adaptation

**Recommendation: a statistical profile, not language-model personalisation.** *Inference, backed by a measurement.*
`profile.py` shrinks every per-player rate toward the population with an empirical-Bayes beta prior. The prior's
strength says how many attempts a player needs before their own record dominates. The measured profile in section 0 shows why
this matters: most players in the corpus have fewer than 20 readable decisions, so their raw rates are noise.

How each requested trait can be measured, and what it needs:

| Trait | Measurement | Source | Needs |
|---|---|---|---|
| Recovery speed | Time from landing, demolition or a whiff to moving toward play at speed | Frames | A new detector; dozens of events per player |
| Aerial reliability | Aerial touches that reach an intended region, over attempts | Decoder `wall_aerial`, touch events | An attempt detector. Failed attempts are the hard part, and the decoder's `whiff` stream is experimental |
| Challenge success | Team possession 2 s after a 50/50, by player | Decoder `fifty_fifty` | Checking the 50/50 detector against hand labels |
| Boost habits | Time at 0, starved time, big-pad share | Decoder `boost.*` (rated high confidence) | Nothing; available now |
| Shadow comfort | Shadow share in this situation class | `decisions.py` | Reliable choice labels |
| Preferred rotations | Role time shares and rotation transitions | Decoder `rotation_role` (definition pending upstream) | Verifying the detector |
| Aggression | Challenge share, matched by situation | `decisions.py` + `profile.py` | 30+ readable decisions |
| Improvement over time | The same shrunk rates per block of matches; report a change only when intervals separate | `profile.py` | Many matches |

Guards against overfitting: shrinkage toward the population; every rate reports its attempt count and interval;
`distinguishable()` only declares a difference when 90% intervals do not overlap; a change over time needs two
non-overlapping blocks, not one bad night.

## 4. Off-ball intelligence

*Measured ablation in section 0; inference below.*

Adding off-ball features (goal-side counts, last-defender depth, second-man arrival time, team boost) lifts Brier skill
from 0.165 (ball and nearest players) to 0.186 in 2v2: a small gain in predicting goals within 5 s. rl-xg reports the
same pattern on pro replays: pressure and possession context did not improve short-horizon goal probability.

That does not mean off-ball play is unimportant. It means **goals in the next 5 s are the wrong target for it**. Good
positioning works by preventing chances that never happen, so it leaves almost no trace in a goal label. Off-ball
quality needs its own target, for example:

- the opponent's threat over the next 5 to 10 s given the current state, credited to the defending positions;
- whether the opponent's next touch is a controlled one;
- the time the defending team needs to get a player goal-side after losing the ball.

**Recommendation:** not a separate neural model yet. First define and validate one of these targets on hand-checked
clips, then train against it.

## 5. The most promising alternative architecture

**A human decision model trained on the high-level corpus, evaluated by the threat model.** *Inference.*

1. Use rlgym-tools to turn the high-level corpus (or its `smol` config) into states and inferred actions.
2. Train a policy that predicts, from the state before a decision, the distribution of what GC+ players do next,
   at the level of coarse options (challenge, shadow, rotate out, boost), conditioned on rank band.
3. Score each option by the threat model's value change that follows it in the corpus, matched on state.

This is the Maia idea transferred to Rocket League: a model of what strong humans do, kept separate from a model of
what works. It respects style because its output is a distribution, and it can flag choices that are both rare among
strong players and worse in matched outcomes. The velocity result is the warning: the policy must be trained on states
from before the commitment, which means the decision time has to move earlier than today's trigger.

## 6. Reasons to reject the weaker options

- **Training our own value model now.** Measured in section 0: a model trained on our data is clearly worse than the shipped one.
  Revisit only for 1v1 and 3v3, where nothing calibrated exists, and only with hundreds of matches.
- **signal-neural-index weights.** The shipped models were trained on 4 to 5 replays; one has a gradient norm of 1e-20.
- **rlcoach's xG.** Hand-tuned constants, not a model.
- **Geometric similarity for showing "similar plays".** It predicts choices best, but its neighbours share the query's
  tactical context only 37% of the time against 58% for tactical features (section 0). Keep it for the behaviour model only.
- **Per-moment verdicts.** The contract abstains on all 784 exported cases. That is the correct output at this sample size.

## What Would I Build Differently If Replay Lab Started From Zero Today?

*Inference throughout, anchored to what was measured here.*

**1. Start with the measurement, not the viewer.** Week one would be a 60-moment blind benchmark and an outcome-masked
clip exporter, before any 3D work. Replay Lab built three viewers before anyone could say whether a single piece of
advice was right. PR #16 is the right instinct, arriving late.

**2. One state model, borrowed.** I would adopt subtr-actor's threat model on day one and spend effort validating
it rather than building rules. It runs in Rust and WASM, so the browser viewer could show live threat for both teams
with no server. Every coaching claim would be phrased as a change in that number.

**3. Rebuild the decision definition around commitment, not proximity.** The velocity result says players have largely
committed by the moment our trigger detects. The decision point should be the last frame at which more than one option was
physically available, found by asking a short-horizon reachability check which options were still open. That is a
better use of RocketSim than counterfactual rollouts.

**4. A player loop that produces labels.** Every review session would end with the player answering one or two
intent questions about their own clips and predicting what strong players did in one reference clip. Each answer is a
labelled example the project currently has no way to get. After a few hundred sessions, that is a dataset no
competitor has.

**5. Habits as the product surface, moments as evidence.** The home screen would be a short list of habit cards with
sample sizes and intervals, each linking to its clips. Individual moments would never carry a verdict.

**6. Three engines, cleanly separated.** A facts engine (decoder events, each checked against hand labels), a value
engine (the threat model plus matched comparisons), and a behaviour engine (what strong players choose). A language
model would sit outside all three and could only restate their output.

**7. Fewer features.** I would drop the AI review route as a judge, every proximity-based mistake rule, and any
claim about intent that the player did not supply. I would keep the 2D board, the masked clips and the habit cards.

**8. Doubles first, properly.** The only calibrated value model is for 2v2. I would ship 2v2 coaching only, say so,
and add 1v1 and 3v3 when there is data to validate a model for each.

**9. Data rights before data.** Two of the three most useful external repositories have no licence, and the main
corpus's terms need checking. I would settle that before building on any of them.

## Reproduce

```bash
cd coach-app
pip install -r requirements.txt -r research/requirements.txt
python -m pytest research/tests -q                         # 23 tests; one needs real replays (below)
COACH_SAMPLE_REPLAY_DIR=/path/to/replays python -m pytest research/tests -q
python -m research.tactical_intel.run --replays /path/to/replays --cache /tmp/rl-cache --out research/results
```

The replays used here are the decoder's own MIT-licensed test assets: clone
[rlrml/subtr-actor](https://github.com/rlrml/subtr-actor) and copy its `*.replay` files into one folder. The full run
takes about 10 minutes on one CPU core, most of it the match bootstrap. No GPU, no network, no paid API.

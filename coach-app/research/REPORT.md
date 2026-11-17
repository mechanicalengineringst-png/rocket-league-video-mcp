# Tactical intelligence: research report and prototypes

Branch `research/claude-tactical-intelligence-20261117`, based on `integration/replay-lab-unified-test-20261117` (2cc5852).
Everything lives in `coach-app/research/`. No backend or evaluation file was edited.

Labels used throughout: **Measured** = produced by code in this branch on real replays this session.
**Reported** = a number another project publishes, which I did not reproduce. **Inference** = my judgement.

<!-- RESULTS -->

## 1. Ranked architecture candidates

| Rank | Architecture | Status in this branch | Why it ranks here |
|---|---|---|---|
| 1 | **Validated threat model + matched habit comparisons.** The decoder's threat model scores every frame; decisions are compared by the value change that follows, aggregated over many matched cases | Prototype 1 validates the model; `decisions.py` produces the value change per decision | Best measured predictor here, free, already in our decoder, runs in the browser via WASM. Turns "was that good?" into a testable average over cases |
| 2 | **Human behaviour model**: a distribution over what high-level players choose in a situation | Prototype 2 approximates it with retrieval; a learned policy needs the 445 GB corpus | The only component that can say "strong players split 60/40 here", which is how style disagreement becomes visible instead of being called a mistake |
| 3 | **Retrieval of comparable human decisions** with a tactical representation | Prototype 2 | Measured to find context-matched situations far better than geometry. Its teaching value is unmeasured until humans rate the clips |
| 4 | **Physics-bounded feasibility checks** (RocketSim, about 1 s) | Not built | Needed before any alternative is suggested. Answers "could you have got there", not "should you have" |
| 5 | **Learned spatiotemporal encoders** (graph networks, transformers) | Rejected for now | The built-in model already is a permutation-invariant entity network. A bigger encoder needs the large corpus and has no target that is known to improve coaching |
| 6 | **Offline action-value estimation** (Q-learning from observational replays) | Rejected for now | The momentum result below shows choices are largely set before the detectable decision time, so the action is confounded with the state. Single-moment action values would be confidently wrong |
| 7 | **Simulated rollouts with a trained bot** | Rejected for now | No open human-like high-rank bot; bot continuations are not human continuations (earlier report, section 6) |
| 8 | **Language or vision-language model as judge** | Rejected as judge | Its jobs: narrate `explanation_payload()` without adding facts, and interview the player about intent. A vision model has one unique job: what was on the player's screen |

## 2. What the current design cannot do

The app's rules decide from distances at one frame. Each distinction in the brief needs something the rules do not have:

| Distinction | What it actually needs | Available now? |
|---|---|---|
| Clever vs unnecessary challenge | The value change that follows each choice, averaged over matched situations | Yes, with the threat model, at habit level only |
| Deliberate 50/50 loss vs mechanical failure | Intent | No. Only the player can say. Team possession after the 50/50 is measurable, intent is not |
| Aggressive support vs double commit | Teammate positions and the value change that followed, over many cases | Partly. Single cases are not judgeable |
| Strong positioning vs merely behind the ball | A target that credits prevented chances. Goal-based targets barely see off-ball play (section 5) | No |
| Decision vs execution | A choice label plus the expected value of that choice; execution is the residual | Only once choice labels are reliable. Today 52% are unreadable |
| Justified risk vs preventable mistake | The spread of outcomes for each choice, not just its mean | Yes in principle; sample sizes are the limit |
| Valid styles vs universal errors | The human behaviour model, to see where strong players split | Approximated by retrieval |

## 3. Personal adaptation

**Recommendation: a statistical profile, not language-model personalisation.** *Inference, backed by a measurement.*
`profile.py` shrinks every per-player rate toward the population with an empirical-Bayes beta prior. The prior's
strength says how many attempts a player needs before their own record dominates. The measured profile below shows why
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

Adding off-ball features (goal-side counts, last-defender depth, second-man arrival time, team boost) to a model that
already sees the ball and the nearest players gives a small gain in predicting goals within 5 s. rl-xg reports the
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
strong players and worse in matched outcomes. The momentum result is the warning: the policy must be trained on states
from before the commitment, which means the decision time has to move earlier than today's trigger.

## 6. Reasons to reject the weaker options

- **Training our own value model now.** Measured below: a model trained on our data is clearly worse than the shipped one.
  Revisit only for 1v1 and 3v3, where nothing calibrated exists, and only with hundreds of matches.
- **signal-neural-index weights.** The shipped models were trained on 4 to 5 replays; one has a gradient norm of 1e-20.
- **rlcoach's xG.** Hand-tuned constants, not a model.
- **Geometric similarity for "similar plays".** Measured below: it predicts choices well only by reading momentum,
  and it retrieves tactically different situations more often than tactical features do.
- **Per-moment verdicts.** The contract abstains on all 784 exported cases. That is the correct output at this sample size.

## What Would I Build Differently If Replay Lab Started From Zero Today?

*Inference throughout, anchored to what was measured here.*

**1. Start with the measurement, not the viewer.** Week one would be a 60-moment blind benchmark and an outcome-masked
clip exporter, before any 3D work. Replay Lab built three viewers before anyone could say whether a single piece of
advice was right. PR #16 is the right instinct, arriving late.

**2. One state model, borrowed.** I would adopt subtr-actor's threat model on day one and spend effort validating
it rather than building rules. It runs in Rust and WASM, so the browser viewer could show live threat for both teams
with no server. Every coaching claim would be phrased as a change in that number.

**3. Rebuild the decision definition around commitment, not proximity.** The momentum result says players commit
before the moment our trigger detects. The decision point should be the last frame at which more than one option was
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
python -m pytest research/tests -q                         # 22 tests; one needs real replays (below)
COACH_SAMPLE_REPLAY_DIR=/path/to/replays python -m pytest research/tests -q
python -m research.tactical_intel.run --replays /path/to/replays --cache /tmp/rl-cache --out research/results
```

The replays used here are the decoder's own MIT-licensed test assets: clone
[rlrml/subtr-actor](https://github.com/rlrml/subtr-actor) and copy its `*.replay` files into one folder. The full run
takes about 10 minutes on one CPU core, most of it the match bootstrap. No GPU, no network, no paid API.

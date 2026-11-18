# Round 10: TacticalDecisionStateV1, a calibrated, branch-aware decision state

`coach_app/decision_state_v1.py` adds `analyze_decision_state(stage1_episode_packet, *, focus_node_id=None, include_v0=False)`, a new versioned output (`TacticalDecisionStateV1`). `TacticalOptionsV0` is unchanged and still used by `tactical_coach_adapter`.

## 1. What was wrong with V0, measured rather than assumed

- **Its "who arrives first" bands were overconfident.** V0 called the focus player "first" when ahead by 0.15 s, and a "genuine fifty-fifty" within 0.30 s. `scripts/calibrate_contest_margin.py` scored kinematic arrival order against which car actually touched first, on 15 real replays split by match (10 fit, 5 held out):

| Pairs scored | Margin needed for ≥ 90% correct order (fit) | Held-out accuracy at that margin |
|---|---|---|
| All opposing pairs where one touched first (7,039) | > 1.0 s (only 0.90 at 1.0 s) | 0.914 |
| "Raced" pairs, where both cars touched within 3 s (1,098) | **0.55 s** | **0.965** (226 resolved pairs) |

  At V0's 0.30 s band, raced-pair order was right only about 84% of the time. The *all-pairs* curve is worse because many players choose not to go for the ball, so their order mixes choice with capability. V1 uses the raced calibration, which isolates capability, and reports the order as *ambiguous* inside 0.55 s.
- **It was a menu, not an assessment.** V0 judged each action from one-sided supports and limits. It gave 3–7 "defensible" options per real episode, and it couldn't express "you win the ball, but the loose ball goes to their second player and nobody covers".

## 2. Approaches compared

| Approach | What it would add | Data we have | Main risk | Decision |
|---|---|---|---|---|
| A. More rules and actions on V0 | Coverage of more named situations | Same | Threshold sprawl, a style bias baked into rules, no robustness | Rejected |
| B. Interval-valued feasibility with a **data-calibrated** ordering margin | Honest "ambiguous" instead of false precision | 1,098 raced pairs | Margin is specific to public replays of unknown rank | **Implemented** |
| C. Structured scenario classification (ball state, shared roles, decision profile) | Context the coach can name; conditions the stance on the situation | Same intervals | Labels can look more authoritative than they are | **Implemented**, labelled as estimates |
| D. Opponent-response branching (first-contact branches → loose-ball race and cover) | Judges an action by whether it holds up across the outcomes the timing allows | Reach intervals + cover | No ball-destination model; branch reachability isn't a probability | **Implemented**, with no probabilities |
| E. Forward simulation (RocketSim) of outcomes | Real trajectories per action | Needs meshes from the owner's install and unknown inputs | Simulates an assumed policy, not the player | Deferred |
| F. Learned policy or value from replays | Data-driven judgement | 15 public matches | Learns outcome correlations (good decision ≠ good result); PR #17 found tiny models lose to the decoder's own | Rejected at this data size |
| G. LLM judge over the packet | Fluent reasoning | Same | Confident prose without new evidence | Out of scope (ChatGPT owns the model layer) |

## 3. What V1 computes (Stage 1 only, t0 evidence only)

- **Reach intervals** per car: `[t_min, t_max]` from reachability, widened by the margin when boost is unknown.
- **Order** between any two cars: first, second, *ambiguous* (within the calibrated margin, or the pessimistic bounds disagree) or *unknown*.
- **Scenario:**
  - ball state: own team first / opponent first / contested / loose / unknown;
  - roles per team, with "ambiguous" when shared;
  - loose-ball race: teammate vs the other opponent;
  - cover: covered / uncovered / ambiguous / unknown;
  - focus recovery as a true physics lower bound (distance to the own goal mouth ÷ 2,300 uu/s);
  - ball momentum toward the own goal.
- **Decision profile:** pressure window, forced contest, restraint window, teammate's ball, transition, mixed or unknown.
- **Branches** for committing actions: focus touches first, carrier touches first, simultaneous contact.
  - Each is marked *primary*, *possible* or *only if execution fails* by the calibrated order.
  - Each carries its consequence: who is ahead for a loose ball, and whether the team is exposed if the focus player is beaten. No probabilities, and no ball destination.
- **Stances by robustness across the reachable branches:**
  - `robustly_defensible`: no reachable branch leaves the team exposed.
  - `defensible_gamble`: exposure only in a branch the timing leaves open. Legitimate aggression; the downside is named.
  - `defensible_tradeoff`: sound, but gives something up, e.g. delaying concedes a ball the player could have won.
  - `questionable`: the branch the timing makes primary leaves the team exposed with no cover.
  - `undetermined` / `not_available`.
- **Delaying actions** are affirmed as *intelligent restraint* when committing would be questionable or the opponent is clearly first.
- **Claims** are in `claim_verifier` format. Every number has a predicate.

**Migration:** `to_v0_stances(result)` maps V1 stances onto V0's vocabulary. `include_v0=True` embeds the unchanged V0 result. The adapter can switch by checking `schema == "TacticalDecisionStateV1"` and `policy.version == "decision-state-policy/1.0"`.

## 4. Results

### Tests

`tests/test_decision_state_v1.py`: 20 tests, synthetic fixtures through the real pipeline.
- The calibration file and the module agree.
- A covered aggressive first-man challenge is robustly defensible, and delaying there is a named tradeoff.
- A covered deliberate fifty-fifty is robust, and several choices coexist.
- An uncovered even contest is a *named gamble*, not a mistake.
- A late uncovered challenge is questionable, and restraint is affirmed.
- Winning the ball first is **not** automatically safe when the loose ball favours their second player and nobody covers. Keeping possession is the safer commit.
- The teammate's position changes stances without blame words.
- Unknown boost widens the interval and is never a fact.
- An opponent on a wall makes the decision abstain; unknown cover makes commit actions undetermined.
- Conceded goals and missed shots after t0 never change the output (three scenarios).
- Retrospective input is refused.
- All claims pass the existing verifier.
- V0 still runs, and the V1→V0 mapping is complete.

### Real replays

See §5.

## 5. Real-replay evaluation (public, unknown-rank; not expert validation)

625 episodes from 15 public replays (nodes at t−8, t−4 and t around first-defender candidates). Retrospective data is used **only for scoring**.

**Engineering checks**
- The existing claim verifier rejected **0 of 5,371** claims.
- **127 of 127** sampled episodes were identical after deleting every frame and event after t0.
- Status: 455 ok, 149 partial (teammate cover unknown), 21 abstain (opponent reach unknown).

**What the scenario layer sees.** The candidate rule selects defensive moments: an opponent can touch within 0.5 s. So the sample contains no "own team first" or pressure-window cases.
- Profiles: forced contest 394, mixed 168, restraint window 42.
- Ball state: contested 394, opponent first 210.

**Held-out check of ball state.** The own team made the next touch in 42% of *contested* moments (161 of 383) and in 21% of *opponent first* moments (42 of 199). The ball-state label separates the two in the expected direction.

**Held-out consequence check.** Among players who actually challenged, I measured how often the opponents strung two touches together, or scored, within 4 s. This proxy mixes decision, execution and later play.

| V1 challenge stance | Challenges | Opponents regained | 95% interval |
|---|---|---|---|
| questionable | 21 | 29% | 0.14–0.5 |
| undetermined | 86 | 26% | 0.18–0.36 |
| robustly defensible | 124 | 23% | 0.16–0.31 |
| defensible gamble | 115 | 19% | 0.13–0.27 |

**There is no measurable separation yet.** "Questionable" is highest, but its interval overlaps the others, and "gamble" is lower than "robust". V0's stances showed the same lack of separation (questionable 25%, defensible 22%). This sample cannot show that the branch stances predict danger. The proxy is weak, and expert ratings are the real test.

Players who delayed saw the opponents regain about 40% of the time in every profile. Delaying concedes the ball by definition, so this proxy cannot judge restraint.

**Distribution of choices.**
- V1 marks 0 actions robust in 256 episodes, 3 in 275 and 4 in 73. It names 60 restraint-affirming windows (42 questionable challenges) and 202 gambles with their downside.
- Counting tradeoffs and gambles as "supported", V1 is *not* narrower than V0: 1–8 per episode against V0's 3–7. The gain is gradation (robust / gamble / tradeoff / questionable) and named branch consequences, not fewer options.

Full output: `decision_state_v1_real_replays.json`.

## 6. Weaknesses, stated plainly

- **The calibration is narrow.** It uses 1,098 raced pairs from 15 public replays of unknown rank. High-rank mechanics (faster recoveries, flip resets) may change the margin.
- **Branches are coarse.** No ball direction, contact angle, spin or second-touch modelling. "Loose-ball race" approximates the contact area by the ball's position.
- **The decision table is a hypothesis.** It encodes "exposure if beaten" as the main risk. Pressure value, such as forcing a rushed touch, is not modelled beyond timing.
- **Unknowns are common.** Teammate cover is unknown when the teammate is airborne or on a wall, and those decisions become partial or undetermined.
- **Everything is still uncalibrated against experts.** Stance names are deliberately cautious. None should be shown to players as a grade until #16-style expert merit ratings exist.

## 6.5 Recommended next integration steps

1. ChatGPT: add V1 to `tactical_coach_adapter` behind a flag, with the schema and policy-version check. Show the `scenario.profile` and branch consequences. Keep V0 as the comparison baseline.
2. Use `defensible_gamble` and `questionable` cases as the **first strata for the expert tactical-merit study**. That is where V1 makes its riskiest claims.
3. Recalibrate the order margin on the owner's own high-rank replays with the same script, before trusting it at GC/SSL level.

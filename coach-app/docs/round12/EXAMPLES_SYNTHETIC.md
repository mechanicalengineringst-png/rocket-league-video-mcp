# Round 12 coaching examples - SYNTHETIC scenarios

**Every example on this page is synthetic**: a hand-built replay run through the real pipeline (`coach_report.coach_moment`). They show how the reasoning handles difficult cases; they are not real gameplay and not evidence of tactical accuracy. Where a scenario has several futures, Stage A is identical across them (tested); only the retrospective part changes.

# Scenario: backboard_benchmark_ground (SYNTHETIC)

An opponent has the ball under control by our backboard corner; the teammate is up-field, their second player waits at the far post area. Challenge, shadow, or hold?

## backboard_benchmark_ground / future: challenge_then_their_goal - 0:11.0 - First defender: first to the ball in your half with an opponent able to contest

*Why this moment:* chosen by the user. The first defender's choice decides whether the opponent gets a free play and whether the teammate is left alone.

**What the situation was (at decision time)**

- You had 45 boost
- The nearest opponent was already on the ball
- The nearest opponent had the ball under control
- The nearest opponent could touch the ball first (0.3 s vs your 1.3 s)
- You were goal-side of the ball
- You were on the ground
- For a loose ball their second player was ahead of your teammate (2.7 s vs 3.6 s)
- The ball was 2780 uu from your goal: room to give ground
- Your teammate needed 3.6 s to get goal-side, too late if you were beaten
- You were your team's last player back
- You were your team's first player to the ball (1.3 s vs 3.6 s)

**Interpretation (clear read).** At decision time the evidence supports shadow and delay / fake challenge / hold goal-side, because the nearest opponent could touch the ball first (0.3 s vs your 1.3 s), you were goal-side of the ball and the ball was 2780 uu from your goal: room to give ground. It argues against clear or pass to space: the nearest opponent could touch the ball before you (0.3 s vs 1.3 s) and the ball was 2780 uu from your goal: room to give ground. It argues against controlled 50/50: one side was clearly first to the ball (1.3 s vs 0.3 s) and your teammate needed 3.6 s to get goal-side, too late if you were beaten.

**Options**

| Option | At t0 | Gains / preserves | Sacrifices / risks |
|---|---|---|---|
| Shadow and delay | supported | time for your teammate to recover; forces the opponent in control to make the first move; your goal-side position; your boost and flip for the save | pressure on the ball; a well-timed shot or pass from the carrier |
| Fake challenge | supported | can force a rushed touch without committing; your goal-side position; your flip | a little speed if they do not react; a patient carrier simply gets more time |
| Hold goal-side | supported | a safe last line; net coverage and boost | any pressure on the ball; an opponent in control gets free time to set up |
| Clear or pass to space | refuted | distance between the ball and your goal; time for both of you to reset | possession; the clear lands with their second player while you are out of position |
| Controlled 50/50 | refuted | neutralises their touch without over-committing; a ball that stays near you after a soft contact | control of the ball's direction: it is shared, not chosen; the ball pops toward their second player; a bad bounce with nobody behind |
| Take it with a controlled touch | refuted | possession and the next decision | tempo: the opponents get time to recover goal-side; a heavy touch hands the loose ball to their second player; they arrive first and the touch never happens |
| Challenge now | refuted | takes time from the opponent before they settle it | your goal-side position for the next seconds; the opponent touches first (0.3 s vs 1.3 s) and can go past you; if beaten, your teammate needs 3.6 s to get goal-side; a rebound favours their second player (2.7 s vs your teammate 3.6 s) |
| Rotate through small pads | refuted | boost without leaving the play | immediate presence on the ball; nobody on the ball while you refill |
| Leave it to your teammate | refuted | no double commit; cover behind your teammate | a quick second touch; if your teammate is beaten you are the last defender |

**Assumptions the replay cannot settle**

- Not observable at all: contact away from second opponent, teammate will rotate, flip available

**Takeaway (practice).** Read: the nearest opponent could touch the ball first (0.3 s vs your 1.3 s), you were goal-side of the ball and the ball was 2780 uu from your goal: room to give ground. In that picture, shadow and delay is the sound option (time for your teammate to recover). Clear or pass to space would risk this: the clear lands with their second player while you are out of position.

**What you did (retrospective):** The decision-time read argued against it. You chose to challenge now, which the decision-time evidence argues against (the nearest opponent could touch the ball before you (0.3 s vs 1.3 s); your teammate needed 3.6 s to get goal-side, too late if you were beaten); shadow and delay was supported.
Next 5 s: focus +0.9 s; goal by opponents +3.2 s. *The assessment below uses only the decision-time ledger and the observed action; the outcome is shown for context and does not change it.*

<sub>Evidence: 16 decision-time claims (valid); numbers traced to E.ball.position, E.cover.teammate, E.focus.boost, E.reach.focus, E.reach.opponent_1, E.reach.opponent_2, E.reach.teammate.</sub>



**Alternative future `hold_then_save`** (Stage A unchanged): You chose to shadow and delay, which the decision-time evidence supports. Reason: the opponent is first; stay goal-side and give ground. Outcome: no goal within 5 s.

# Scenario: backboard_benchmark_aerial (SYNTHETIC)

Same corner, but the ball is high on the backboard and the opponent is in the air: aerial/backboard mechanics are not modelled, so the coach must abstain from judgment.

## backboard_benchmark_aerial - 0:11.0 - Aerial or wall situation

*Why this moment:* chosen by the user. Aerial and wall mechanics are not modelled, so only observations are given.

**Observation only.** Aerial and wall mechanics are not modelled; only observations are given.

- Your teammate needed 3.13 s to get goal-side, too late if you were beaten
- You were not goal-side of the ball
- You were on the ground
- You had 45 boost
- You were your team's last player back



# Scenario: restraint_then_conceded (SYNTHETIC)

An opponent dribbles at us with support; we are low on boost, the teammate is far up-field. We shadow and they score anyway. The shadow should not be criticised for the goal.

## restraint_then_conceded / future: shadow_then_their_goal - 0:11.0 - First defender: first to the ball in your half with an opponent able to contest

*Why this moment:* chosen by the user. The first defender's choice decides whether the opponent gets a free play and whether the teammate is left alone.

**What the situation was (at decision time)**

- You had only 12 boost
- The nearest opponent was already on the ball
- The nearest opponent had the ball under control
- The nearest opponent could touch the ball first (0.3 s vs your 2.2 s)
- You were goal-side of the ball
- You were on the ground
- For a loose ball their second player was ahead of your teammate (1.1 s vs 1.8 s)
- The ball was 4120 uu from your goal: room to give ground
- Your teammate needed 2.33 s to get goal-side, too late if you were beaten
- You were your team's last player back
- Unclear whether your teammate could reach the ball first (1.8 s vs your 2.2 s) *(within error)*

**Interpretation (clear read).** At decision time the evidence supports shadow and delay / fake challenge / hold goal-side, because the nearest opponent could touch the ball first (0.3 s vs your 2.2 s), you were goal-side of the ball and the ball was 4120 uu from your goal: room to give ground. It argues against clear or pass to space: the nearest opponent could touch the ball before you (0.3 s vs 2.2 s) and the ball was 4120 uu from your goal: room to give ground. It argues against controlled 50/50: one side was clearly first to the ball (2.2 s vs 0.3 s) and your teammate needed 2.33 s to get goal-side, too late if you were beaten. What would change the read: whether your teammate could reach the ball first (1.8 s vs your 2.2 s) (currently within error).

**Options**

| Option | At t0 | Gains / preserves | Sacrifices / risks |
|---|---|---|---|
| Shadow and delay | supported | time for your teammate to recover; forces the opponent in control to make the first move; your goal-side position; your boost and flip for the save | pressure on the ball; a well-timed shot or pass from the carrier |
| Fake challenge | supported | can force a rushed touch without committing; your goal-side position; your flip | a little speed if they do not react; a patient carrier simply gets more time |
| Hold goal-side | supported | a safe last line; net coverage and boost | any pressure on the ball; an opponent in control gets free time to set up |
| Leave it to your teammate | conditional | no double commit; cover behind your teammate | a quick second touch; if your teammate is beaten you are the last defender |
| Clear or pass to space | refuted | distance between the ball and your goal; time for both of you to reset | possession; the clear lands with their second player while you are out of position |
| Controlled 50/50 | refuted | neutralises their touch without over-committing; a ball that stays near you after a soft contact | control of the ball's direction: it is shared, not chosen; the ball pops toward their second player; a bad bounce with nobody behind |
| Take it with a controlled touch | refuted | possession and the next decision | tempo: the opponents get time to recover goal-side; a heavy touch hands the loose ball to their second player; they arrive first and the touch never happens |
| Challenge now | refuted | takes time from the opponent before they settle it | your goal-side position for the next seconds; a quick recovery: you have 12 boost; the opponent touches first (0.3 s vs 2.2 s) and can go past you; if beaten, your teammate needs 2.33 s to get goal-side; a rebound favours their second player (1.1 s vs your teammate 1.8 s) |
| Rotate through small pads | refuted | boost without leaving the play | immediate presence on the ball; nobody on the ball while you refill |

**Assumptions the replay cannot settle**

- whether your teammate could reach the ball first (1.8 s vs your 2.2 s) (within error; resolve with a better physical model (e.g. RocketSim) or expert review of the clip)
- Not observable at all: contact away from second opponent, teammate will rotate, flip available

**Takeaway (practice).** Read: the nearest opponent could touch the ball first (0.3 s vs your 2.2 s), you were goal-side of the ball and the ball was 4120 uu from your goal: room to give ground. In that picture, shadow and delay is the sound option (time for your teammate to recover). Clear or pass to space would risk this: the clear lands with their second player while you are out of position.

**What you did (retrospective):** Consistent with the decision-time read. You chose to hold goal-side, which the decision-time evidence supports. Reason: you are the last line; hold it. The goal that followed does not make the choice wrong.
Next 5 s: opponent +0.5 s; goal by opponents +3.5 s. *The assessment below uses only the decision-time ledger and the observed action; the outcome is shown for context and does not change it.*

<sub>Evidence: 15 decision-time claims (valid); numbers traced to E.ball.position, E.cover.teammate, E.focus.boost, E.reach.focus, E.reach.opponent_1, E.reach.opponent_2, E.reach.teammate.</sub>



**Alternative future `shadow_then_save`** (Stage A unchanged): You chose to hold goal-side, which the decision-time evidence supports. Reason: you are the last line; hold it. Outcome: no goal within 5 s.

# Scenario: challenge_works_anyway (SYNTHETIC)

Same state, but we dive in and it happens to work (we win it and our team scores). The decision-time read still argued against it; the outcome must not turn that into praise.

## challenge_works_anyway / future: challenge_then_our_goal - 0:11.0 - First defender: first to the ball in your half with an opponent able to contest

*Why this moment:* chosen by the user. The first defender's choice decides whether the opponent gets a free play and whether the teammate is left alone.

**What the situation was (at decision time)**

- You had only 12 boost
- The nearest opponent was already on the ball
- The nearest opponent had the ball under control
- The nearest opponent could touch the ball first (0.3 s vs your 2.2 s)
- You were goal-side of the ball
- You were on the ground
- For a loose ball their second player was ahead of your teammate (1.1 s vs 1.8 s)
- The ball was 4120 uu from your goal: room to give ground
- Your teammate needed 2.33 s to get goal-side, too late if you were beaten
- You were your team's last player back
- Unclear whether your teammate could reach the ball first (1.8 s vs your 2.2 s) *(within error)*

**Interpretation (clear read).** At decision time the evidence supports shadow and delay / fake challenge / hold goal-side, because the nearest opponent could touch the ball first (0.3 s vs your 2.2 s), you were goal-side of the ball and the ball was 4120 uu from your goal: room to give ground. It argues against clear or pass to space: the nearest opponent could touch the ball before you (0.3 s vs 2.2 s) and the ball was 4120 uu from your goal: room to give ground. It argues against controlled 50/50: one side was clearly first to the ball (2.2 s vs 0.3 s) and your teammate needed 2.33 s to get goal-side, too late if you were beaten. What would change the read: whether your teammate could reach the ball first (1.8 s vs your 2.2 s) (currently within error).

**Options**

| Option | At t0 | Gains / preserves | Sacrifices / risks |
|---|---|---|---|
| Shadow and delay | supported | time for your teammate to recover; forces the opponent in control to make the first move; your goal-side position; your boost and flip for the save | pressure on the ball; a well-timed shot or pass from the carrier |
| Fake challenge | supported | can force a rushed touch without committing; your goal-side position; your flip | a little speed if they do not react; a patient carrier simply gets more time |
| Hold goal-side | supported | a safe last line; net coverage and boost | any pressure on the ball; an opponent in control gets free time to set up |
| Leave it to your teammate | conditional | no double commit; cover behind your teammate | a quick second touch; if your teammate is beaten you are the last defender |
| Clear or pass to space | refuted | distance between the ball and your goal; time for both of you to reset | possession; the clear lands with their second player while you are out of position |
| Controlled 50/50 | refuted | neutralises their touch without over-committing; a ball that stays near you after a soft contact | control of the ball's direction: it is shared, not chosen; the ball pops toward their second player; a bad bounce with nobody behind |
| Take it with a controlled touch | refuted | possession and the next decision | tempo: the opponents get time to recover goal-side; a heavy touch hands the loose ball to their second player; they arrive first and the touch never happens |
| Challenge now | refuted | takes time from the opponent before they settle it | your goal-side position for the next seconds; a quick recovery: you have 12 boost; the opponent touches first (0.3 s vs 2.2 s) and can go past you; if beaten, your teammate needs 2.33 s to get goal-side; a rebound favours their second player (1.1 s vs your teammate 1.8 s) |
| Rotate through small pads | refuted | boost without leaving the play | immediate presence on the ball; nobody on the ball while you refill |

**Assumptions the replay cannot settle**

- whether your teammate could reach the ball first (1.8 s vs your 2.2 s) (within error; resolve with a better physical model (e.g. RocketSim) or expert review of the clip)
- Not observable at all: contact away from second opponent, teammate will rotate, flip available

**Takeaway (practice).** Read: the nearest opponent could touch the ball first (0.3 s vs your 2.2 s), you were goal-side of the ball and the ball was 4120 uu from your goal: room to give ground. In that picture, shadow and delay is the sound option (time for your teammate to recover). Clear or pass to space would risk this: the clear lands with their second player while you are out of position.

**What you did (retrospective):** The decision-time read argued against it. You chose to challenge now, which the decision-time evidence argues against (the nearest opponent could touch the ball before you (0.3 s vs 2.2 s); your teammate needed 2.33 s to get goal-side, too late if you were beaten); shadow and delay was supported. It worked out this time, but the read at decision time still argued against it.
Next 5 s: focus +0.5 s; goal by own team +4.0 s. *The assessment below uses only the decision-time ledger and the observed action; the outcome is shown for context and does not change it.*

<sub>Evidence: 15 decision-time claims (valid); numbers traced to E.ball.position, E.cover.teammate, E.focus.boost, E.reach.focus, E.reach.opponent_1, E.reach.opponent_2, E.reach.teammate.</sub>



# Scenario: level_contest_with_cover (SYNTHETIC)

We and the nearest opponent reach the ball at about the same time; the teammate is deep. Several choices should be presented as defensible.

## level_contest_with_cover - 0:11.0 - First defender: first to the ball in your half with an opponent able to contest

*Why this moment:* chosen by the user. The first defender's choice decides whether the opponent gets a free play and whether the teammate is left alone.

**What the situation was (at decision time)**

- You had 60 boost
- The nearest opponent was not driving at the ball (closing at only 0 uu/s)
- No opponent had the ball under control
- Arrival order could not be separated (earliest touches 0.8 s vs 0.8 s, allowing for model error and approach uncertainty): a genuine contest
- You were goal-side of the ball
- You were on the ground
- For a loose ball your teammate was ahead of their second player (2.1 s vs 2.9 s)
- The ball was 4120 uu from your goal: room to give ground
- Your teammate was already goal-side
- Your teammate was deeper than you
- You were your team's first player to the ball (0.8 s vs 2.1 s)
- Arrival order was inside the model error (0.8 s vs 0.8 s) *(within error)*

**Interpretation (clear read).** At decision time the evidence supports controlled 50/50 / take it with a controlled touch / challenge now, because arrival order could not be separated (earliest touches 0.8 s vs 0.8 s, allowing for model error and approach uncertainty): a genuine contest and your teammate was already goal-side. It argues against clear or pass to space: the ball was 4120 uu from your goal: room to give ground. It argues against fake challenge: no opponent had the ball under control. What would change the read: whether the nearest opponent could touch the ball first (0.8 s vs your 0.8 s) (currently within error); whether you could touch the ball first (0.8 s vs 0.8 s) (currently within error).

**Options**

| Option | At t0 | Gains / preserves | Sacrifices / risks |
|---|---|---|---|
| Controlled 50/50 | supported | neutralises their touch without over-committing; coverage behind you; a ball that stays near you after a soft contact | control of the ball's direction: it is shared, not chosen |
| Take it with a controlled touch | supported | possession and the next decision; your shape: your teammate stays back | tempo: the opponents get time to recover goal-side; they arrive first and the touch never happens (possible) |
| Challenge now | supported | takes time from the opponent before they settle it; arriving first lets you choose the contact (possible); your teammate stays as the last line | your goal-side position for the next seconds; the opponent touches first (0.8 s vs 0.8 s) and can go past you (possible) |
| Shadow and delay | conditional | time for your teammate to recover; your goal-side position; your boost and flip for the save | pressure on the ball; a ball you could reach first (possible); a well-timed shot or pass from the carrier |
| Clear or pass to space | refuted | distance between the ball and your goal; time for both of you to reset | possession |
| Fake challenge | refuted | can force a rushed touch without committing; your goal-side position; your flip | a little speed if they do not react; a patient carrier simply gets more time |
| Hold goal-side | refuted | a safe last line; net coverage and boost | any pressure on the ball; a winnable ball (possible) |
| Rotate through small pads | refuted | boost without leaving the play; your teammate covers the ball | immediate presence on the ball |
| Leave it to your teammate | refuted | no double commit; cover behind your teammate | a quick second touch; if your teammate is beaten you are the last defender (possible) |

**Assumptions the replay cannot settle**

- whether the nearest opponent could touch the ball first (0.8 s vs your 0.8 s) (within error; resolve with a better physical model (e.g. RocketSim) or expert review of the clip)
- whether you could touch the ball first (0.8 s vs 0.8 s) (within error; resolve with a better physical model (e.g. RocketSim) or expert review of the clip)
- Not observable at all: contact away from second opponent, teammate will rotate, flip available

**Takeaway (practice).** Read: arrival order could not be separated (earliest touches 0.8 s vs 0.8 s, allowing for model error and approach uncertainty): a genuine contest, your teammate was already goal-side and no opponent had the ball under control. In that picture, controlled 50/50 is the sound option (neutralises their touch without over-committing). Fake challenge would risk this: a patient carrier simply gets more time.

**What you did (retrospective):** Defensible under an assumption. You chose to shadow and delay. It is defensible if the nearest opponent could touch the ball first (0.8 s vs your 0.8 s), which the replay cannot confirm.
Next 5 s: no touches. *The assessment below uses only the decision-time ledger and the observed action; the outcome is shown for context and does not change it.*

<sub>Evidence: 14 decision-time claims (valid); numbers traced to E.ball.position, E.focus.boost, E.reach.focus, E.reach.opponent_1, E.reach.opponent_2, E.reach.teammate, Q.carrier_closing_speed.</sub>



# Scenario: covered_first_man_aggression (SYNTHETIC)

We are clearly first to a loose ball with the teammate deep behind us. Challenging is supported; the coach should recognise it rather than suggest caution.

## covered_first_man_aggression / future: challenge_then_their_goal - 0:11.0 - First defender: first to the ball in your half with an opponent able to contest

*Why this moment:* chosen by the user. The first defender's choice decides whether the opponent gets a free play and whether the teammate is left alone.

**What the situation was (at decision time)**

- You had 60 boost
- The nearest opponent was not driving at the ball (closing at only 0 uu/s)
- No opponent had the ball under control
- You could touch the ball before the nearest opponent (0.5 s vs 1.5 s)
- You were goal-side of the ball
- You were on the ground
- For a loose ball your teammate was ahead of their second player (2.1 s vs 2.9 s)
- The ball was 4120 uu from your goal: room to give ground
- Your teammate was already goal-side
- Your teammate was deeper than you
- You were your team's first player to the ball (0.5 s vs 2.1 s)

**Interpretation (clear read).** At decision time the evidence supports take it with a controlled touch / challenge now, because you could touch the ball first (0.5 s vs 1.5 s) and no opponent had the ball under control. It argues against clear or pass to space: the ball was 4120 uu from your goal: room to give ground. It argues against controlled 50/50: one side was clearly first to the ball (0.5 s vs 1.5 s).

**Options**

| Option | At t0 | Gains / preserves | Sacrifices / risks |
|---|---|---|---|
| Take it with a controlled touch | supported | possession and the next decision; your shape: your teammate stays back | tempo: the opponents get time to recover goal-side |
| Challenge now | supported | takes time from the opponent before they settle it; arriving first lets you choose the contact; your teammate stays as the last line | your goal-side position for the next seconds |
| Clear or pass to space | refuted | distance between the ball and your goal; time for both of you to reset | possession |
| Controlled 50/50 | refuted | neutralises their touch without over-committing; coverage behind you; a ball that stays near you after a soft contact | control of the ball's direction: it is shared, not chosen |
| Fake challenge | refuted | can force a rushed touch without committing; your goal-side position; your flip | a little speed if they do not react; a patient carrier simply gets more time |
| Hold goal-side | refuted | a safe last line; net coverage and boost | any pressure on the ball; a winnable ball |
| Rotate through small pads | refuted | boost without leaving the play; your teammate covers the ball | immediate presence on the ball |
| Shadow and delay | refuted | time for your teammate to recover; your goal-side position; your boost and flip for the save | pressure on the ball; a ball you could reach first; a well-timed shot or pass from the carrier |
| Leave it to your teammate | refuted | no double commit; cover behind your teammate | a quick second touch |

**Assumptions the replay cannot settle**

- Not observable at all: contact away from second opponent, teammate will rotate, flip available

**Takeaway (practice).** Read: you could touch the ball first (0.5 s vs 1.5 s) and no opponent had the ball under control. In that picture, take it with a controlled touch is the sound option (possession and the next decision). Fake challenge would risk this: a patient carrier simply gets more time.

**What you did (retrospective):** Consistent with the decision-time read. You chose to challenge now, which the decision-time evidence supports. Reason: get there first with a teammate behind. The goal that followed does not make the choice wrong.
Next 5 s: focus +0.4 s; goal by opponents +4.5 s. *The assessment below uses only the decision-time ledger and the observed action; the outcome is shown for context and does not change it.*

<sub>Evidence: 16 decision-time claims (valid); numbers traced to E.ball.position, E.focus.boost, E.reach.focus, E.reach.opponent_1, E.reach.opponent_2, E.reach.teammate, Q.carrier_closing_speed.</sub>



# Scenario: second_man_low_boost (SYNTHETIC)

The teammate is about to play the ball in midfield; we are behind with little boost. Support close, support deep, or take a pad on the way back?

## second_man_low_boost / future: took_pads - 0:11.0 - Second man while the teammate plays the ball

*Why this moment:* chosen by the user. Second-man position decides whether your teammate's play can be followed up or covered if it fails.

**What the situation was (at decision time)**

- The small pad route still reached goal-side in 1.43 s, in time to cover
- The nearest opponent could touch the ball first (1 s vs your 2.6 s)
- You were not driving at the ball your teammate was playing
- You were already goal-side
- You had only 8 boost
- Your teammate could reach the ball first (0.4 s vs your 2.6 s)
- An opponent could reach the ball in 1 s (borderline) *(within error)*

**Interpretation (several defensible).** At decision time the evidence supports support close for a follow-up / collect boost while your teammate plays it / support from behind, because your teammate could reach the ball first (0.4 s vs your 2.6 s), you were already goal-side and you were not driving at the ball your teammate was playing. It argues against challenge as well: your teammate could reach the ball first (0.4 s vs your 2.6 s) and one side was clearly first to the ball (2.6 s vs 1 s).

**Options**

| Option | At t0 | Gains / preserves | Sacrifices / risks |
|---|---|---|---|
| Support close for a follow-up | supported | a second touch if their clear is weak; both opponents are far from the ball (possible) | defensive depth |
| Collect boost while your teammate plays it | supported | boost for your next role (you have 8); a full rotation: the small pad route still reaches goal-side in 1.43 s; cover behind your teammate | support for your teammate's play; an opponent wins the ball while you are away |
| Support from behind | supported | cover if your teammate is beaten; your boost and a clean rotation | a quick follow-up on a weak clear |
| Challenge as well | refuted | - | all coverage behind; a double commit on a ball your teammate already has |

**Takeaway (recognition).** More than one choice holds up: support close for a follow-up or collect boost while your teammate plays it. What makes both reasonable: your teammate could reach the ball first (0.4 s vs your 2.6 s), you were already goal-side and you were not driving at the ball your teammate was playing. What was not on: challenge as well (risk: a double commit on a ball your teammate already has).

**What you did (retrospective):** Consistent with the decision-time read. You chose to collect boost while your teammate plays it, which the decision-time evidence supports. Reason: a pad on the way still lets you cover: top up for the next rotation. Other choices were also defensible here.
Next 5 s: no touches. *The assessment below uses only the decision-time ledger and the observed action; the outcome is shown for context and does not change it.*

<sub>Evidence: 17 decision-time claims (valid); numbers traced to E.ball.position, E.focus.boost, E.reach.focus, E.reach.opponent_1, E.reach.opponent_2, E.reach.teammate, Q.boost_route_pad, Q.boost_then_cover_s, Q.focus_closing_speed.</sub>



# Scenario: teammate_cover_borderline (SYNTHETIC)

The opponent will reach the ball first; whether the teammate can get goal-side in time is borderline. The coach should name that as the deciding unknown instead of picking a side.

## teammate_cover_borderline - 0:11.0 - First defender: first to the ball in your half with an opponent able to contest

*Why this moment:* chosen by the user. The first defender's choice decides whether the opponent gets a free play and whether the teammate is left alone.

**What the situation was (at decision time)**

- You had 50 boost
- The nearest opponent was not driving at the ball (closing at only 0 uu/s)
- No opponent had the ball under control
- The nearest opponent could touch the ball first (0.7 s vs your 1.3 s)
- You were goal-side of the ball
- You were on the ground
- For a loose ball your teammate was ahead of their second player (1.2 s vs 2.7 s)
- The ball was 4220 uu from your goal: room to give ground
- You were your team's last player back
- Whether your teammate could cover in time was inside the model error *(within error)*
- Unclear whether your teammate could reach the ball first (1.2 s vs your 1.3 s) *(within error)*

**Interpretation (clear read).** At decision time the evidence supports hold goal-side / shadow and delay, because you were goal-side of the ball and you were your team's last player back. It argues against clear or pass to space: the nearest opponent could touch the ball before you (0.7 s vs 1.3 s) and the ball was 4220 uu from your goal: room to give ground. It argues against controlled 50/50: one side was clearly first to the ball (1.3 s vs 0.7 s). What would change the read: whether your teammate could be goal-side in 1.3 s, in time if you were beaten (currently within error); whether your teammate could reach the ball first (1.2 s vs your 1.3 s) (currently within error).

**Options**

| Option | At t0 | Gains / preserves | Sacrifices / risks |
|---|---|---|---|
| Hold goal-side | supported | a safe last line; net coverage and boost | any pressure on the ball |
| Shadow and delay | supported | time for your teammate to recover; your goal-side position; your boost and flip for the save | pressure on the ball; a well-timed shot or pass from the carrier |
| Take it with a controlled touch | conditional | possession and the next decision; your shape: your teammate stays back (possible) | tempo: the opponents get time to recover goal-side; they arrive first and the touch never happens |
| Challenge now | conditional | takes time from the opponent before they settle it; your teammate stays as the last line (possible) | your goal-side position for the next seconds; the opponent touches first (0.7 s vs 1.3 s) and can go past you; if beaten, your teammate needs 1.3 s to get goal-side (possible) |
| Leave it to your teammate | conditional | no double commit; cover behind your teammate | a quick second touch; if your teammate is beaten you are the last defender |
| Clear or pass to space | refuted | distance between the ball and your goal; time for both of you to reset | possession |
| Controlled 50/50 | refuted | neutralises their touch without over-committing; coverage behind you (possible); a ball that stays near you after a soft contact | control of the ball's direction: it is shared, not chosen; a bad bounce with nobody behind (possible) |
| Fake challenge | refuted | can force a rushed touch without committing; your goal-side position; your flip | a little speed if they do not react; a patient carrier simply gets more time |
| Rotate through small pads | refuted | boost without leaving the play; your teammate covers the ball (possible) | immediate presence on the ball; nobody on the ball while you refill (possible) |

**Assumptions the replay cannot settle**

- whether your teammate could be goal-side in 1.3 s, in time if you were beaten (within error; resolve with a better physical model (e.g. RocketSim) or expert review of the clip)
- whether your teammate could reach the ball first (1.2 s vs your 1.3 s) (within error; resolve with a better physical model (e.g. RocketSim) or expert review of the clip)
- Not observable at all: contact away from second opponent, teammate will rotate, flip available

**Takeaway (practice).** Read: you were goal-side of the ball, you were your team's last player back and the nearest opponent could touch the ball before you (0.7 s vs 1.3 s). In that picture, hold goal-side is the sound option (a safe last line).

**What you did (retrospective):** Consistent with the decision-time read. You chose to shadow and delay, which the decision-time evidence supports. Reason: the opponent is first; stay goal-side and give ground.
Next 5 s: no touches. *The assessment below uses only the decision-time ledger and the observed action; the outcome is shown for context and does not change it.*

<sub>Evidence: 14 decision-time claims (valid); numbers traced to E.ball.position, E.cover.teammate, E.focus.boost, E.reach.focus, E.reach.opponent_1, E.reach.opponent_2, E.reach.teammate, Q.carrier_closing_speed.</sub>



# Scenario: missing_focus_telemetry (SYNTHETIC)

The focus car is absent from the frames around the decision (e.g. demolished or not sampled). The coach must abstain.

**Result: abstained.** The frame does not match a supported decision situation (or a car or reach estimate is missing).

# Scenario: recovery_route (SYNTHETIC)

We are deep in their half after a challenge with little boost; an opponent is coming at our goal and the teammate is back. Direct, small pads, or the big pad?

## recovery_route / future: big_boost - 0:11.0 - Recovering back into play

*Why this moment:* chosen by the user. The route back decides how soon you are useful again and with how much boost.

**What the situation was (at decision time)**

- The big-boost detour cost only 0.47 s more than returning directly (4.03 s)
- The nearest big pad was up
- You had only 10 boost
- 3 available small pads lay on the direct route
- Your teammate was already goal-side
- An opponent was first to a ball in or heading into your half

**Interpretation (several defensible).** At decision time the evidence supports return through small pads / detour for big boost, because you had only 10 boost and 3 available small pads lay on the direct route. It argues against return directly: your teammate was already goal-side.

**Options**

| Option | At t0 | Gains / preserves | Sacrifices / risks |
|---|---|---|---|
| Return through small pads | supported | refill on the way: 3 available small pads lie on the line back; near-direct timing | small detours from the straight line; any detour while an opponent is attacking |
| Detour for big boost | supported | a full tank for the next challenge or save | time: 0.47 s longer than returning directly; being out of the play while an opponent attacks |
| Return directly | refuted | the fastest way back: 4.03 s to the goal-side point; defensive coverage | boost: you arrive with 10 and cannot challenge strongly |

**Takeaway (recognition).** More than one choice holds up: return through small pads or detour for big boost. What makes both reasonable: you had only 10 boost, 3 available small pads lay on the direct route and your teammate was already goal-side. What was not on: return directly.

**What you did (retrospective):** Consistent with the decision-time read. You chose to detour for big boost, which the decision-time evidence supports. Reason: covered, low on boost, and the big pad costs little extra time. Other choices were also defensible here.
Next 5 s: no touches. *The assessment below uses only the decision-time ledger and the observed action; the outcome is shown for context and does not change it.*

<sub>Evidence: 17 decision-time claims (valid); numbers traced to E.ball.position, E.focus.boost, E.reach.focus, E.reach.opponent_1, E.reach.opponent_2, E.reach.teammate, Q.big_boost_detour_extra_s, Q.big_pad_status, Q.direct_return_s, Q.small_pads_on_route.</sub>



**Alternative future `direct`** (Stage A unchanged): You chose to return directly; the evidence does not clearly support or rule it out. Outcome: no goal within 5 s.

# Scenario: possession_open_lane (SYNTHETIC)

We have the ball under control in their half, in range, with both defenders out of the lane. Shoot, keep it, or pass?

## possession_open_lane / future: shot - 0:11.0 - In possession of the ball

*Why this moment:* chosen by the user. What you do with the ball decides whether the possession turns into pressure or into a turnover with nobody back.

**What the situation was (at decision time)**

- The ball was in their half
- The ball was 2528 uu from their goal, in shooting range
- Your teammate could cover if you lost the ball
- 9 of 9 lines to goal were open and no defender could reach the shot line first
- Your teammate was not placed to receive a pass
- No opponent could touch the ball for 1.9 s

**Interpretation (several defensible).** At decision time the evidence supports keep it and build / shoot now, because no opponent could touch the ball for 1.9 s and your teammate could cover if you lost the ball. It argues against clear to space: the ball was in their half and no opponent could touch the ball for 1.9 s. It argues against pass or centre to your teammate: your teammate was not placed to receive a pass and no opponent could touch the ball for 1.9 s.

**Options**

| Option | At t0 | Gains / preserves | Sacrifices / risks |
|---|---|---|---|
| Keep it and build | supported | time to choose: no opponent can touch it for 1.9 s; your shape: your teammate can be goal-side if you lose it | tempo: defenders recover while you carry |
| Shoot now | supported | an open lane: 9 of 9 lines to goal unblocked | possession: a saved shot usually hands them the ball |
| Clear to space | refuted | - | a possession you already have; clearing a controlled ball usually gives it back |
| Pass or centre to your teammate | refuted | attacking momentum | control: your teammate must win the next touch; with nobody to receive, a pass is a clear to the opponents |
| Push it forward to keep pressure | refuted | keeps the attack moving past an arriving defender; field position in their half | control of the ball; nobody follows up, so the defender collects it |
| Slow down and wait for support | refuted | time for your teammate to join; possession | tempo |

**Takeaway (recognition).** More than one choice holds up: keep it and build or shoot now. What makes both reasonable: no opponent could touch the ball for 1.9 s, your teammate could cover if you lost the ball and the ball was in their half. What was not on: clear to space (risk: clearing a controlled ball usually gives it back).

**What you did (retrospective):** Consistent with the decision-time read. You chose to shoot now, which the decision-time evidence supports. Reason: in range with an open lane. Other choices were also defensible here.
Next 5 s: focus +0.3 s. *The assessment below uses only the decision-time ledger and the observed action; the outcome is shown for context and does not change it.*

<sub>Evidence: 19 decision-time claims (valid); numbers traced to E.ball.position, E.focus.boost, E.reach.focus, E.reach.opponent_1, E.reach.opponent_2, E.reach.teammate, Q.ball_to_opponent_goal_uu, Q.pressure_time_s, Q.shot_defender_margin_s, Q.shot_open_lines.</sub>



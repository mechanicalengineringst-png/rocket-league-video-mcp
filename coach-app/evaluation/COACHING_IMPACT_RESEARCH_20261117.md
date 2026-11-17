# Replay Lab: from tactical analysis to actual learning
Independent research note — ChatGPT workstream, 17 November 2026

## The new design question

"What can our analysis infer?" is different from "Which feedback changes how
a person plays?" A coach must be evaluated on (1) factual and tactical support,
(2) actionable advice, and eventually (3) improved decisions on unseen
situations. A calibrated five-second goal-threat predictor can do well at
forecasting while remaining incapable of judging an individual decision.

**Hypothesis, not yet proven in Rocket League:** players might learn more
from first judging an outcome-masked replay situation, explaining their own
reasoning, comparing several *defensible* alternatives, and later answering
another unfamiliar situation than from passively reading an AI criticism.

## Verified research motivating tests

- Sahli et al. (2026), DOI 10.1186/s13102-026-01694-w:
  https://pubmed.ncbi.nlm.nih.gov/41987028/
  A four-week, three-arm soccer experiment with 84 young amateur male
  players (7v7) compared human-led tactical debate, AI-generated guidance
  and passive control. The human-led group had stronger gains on several
  reported tactical/problem-solving outcomes. This is *not* direct evidence
  for a particular Rocket League user interface.
- Xarles et al., "Action Valuation in Sports: A Survey" (CVPR 2025 Workshop):
  https://openaccess.thecvf.com/content/CVPR2025W/CVSPORTS/papers/Xarles_Action_Valuation_in_Sports_A_Survey_CVPRW_2025_paper.pdf
  Research limitations include lack of direct ground truth for action quality,
  hard off-ball credit attribution, player-specific skill/feasibility, and
  problems evaluating causal alternatives. Scoring threat is useful *context*,
  not a causal estimate of the value of an unchosen action.
- Sutherland et al., "Uncertainty Herding" (ICLR 2025):
  https://openreview.net/pdf/0b53a1002679bae2e0fe9413650fffef50d01b4d.pdf
  Supports investigating diverse/uncertain case acquisition when annotations
  are expensive. Keep this adaptive development pool separate from a frozen
  representative evaluation holdout, otherwise selection biases the numbers.
- "The analytics-practice gap" (2026):
  https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2026.1866960/full
  Conceptual guidance: connect a useful observation to a feasible training
  intervention and then examine whether the intended behavior changed.

## Experiment A — uncover the cases detectors overlook

Build a 60-case blind pilot from at least three competitive 2v2 matches:
20 kickoff-support, 20 first-man, 20 last-back. Within each family, compare
10 detector-selected events with 10 independently sampled eligible live-play
moments. Independently time-sampled moments must be chosen before running
the detector or reading the later outcome, and situation labels must be
assigned from the predecision state. Two blinded independent reviewers
judge decision soundness, risk, tradeoff or uncertainty before seeing outcomes.

Important: this stratified 50/50 pilot is NOT a prevalence estimate for all
play unless eligible windows and weighting are specified. Measure missed
interesting decisions, missed good plays, unsupported criticisms, and rater
disagreement. Compare to an abstaining baseline and keep reviewer identities,
random-selection provenance, source replay IDs, and later outcomes separate.

New companion module: evaluation/pilot.py, invoked through
python -m evaluation.pilot. It can balance and select candidate cases from
multiple matches; it CANNOT generate genuinely random eligible moments from
native replays. Source generation/provenance requires separate decoder work.

## Experiment B — does decision-first coaching teach transferable skill?

Prototype a simple training drill using a correct replay state view, rather
than waiting for perfect photorealistic 3D:

1. Freeze the moment before a verified, defensible commitment window.
2. Ask what the user would do: challenge, fake, shadow/delay, rotate/leave,
   or insufficient information. Permit multiple defensible approaches.
3. Ask for confidence and a short tactical rationale.
4. Show a separately reviewed high-level reference decision and at least
   one reasonable alternative, highlighting physical constraints and
   the specific cue the learner should notice next time.
5. Only then show the actual outcome, emphasizing that it does not certify
   the earlier decision as good or bad.
6. Later test the learner on novel matched situations without giving clues.

Test decision-first drills versus passive explanations on separate randomly
assigned clip sets; use held-out clips and a later recall/transfer check.
Measure defensibility of choices judged by independent experts, confidence
calibration, time, user engagement, and revisions. An N=1 feasibility test
cannot establish general causal learning effects, but can reveal usability
problems before scaling.

Reject or revise if experts systematically disagree on the proposed best
choice, players cannot interpret the frozen scene, or delayed responses
do not look more useful than simpler explanations.

## Experiment C — positive coaching is a distinct skill

Existing heuristic baselines tend to emit risk/tradeoff/abstain and few
positively supported sound decisions. Ask whether we can reliably recognize
a sound play with a cited predecision cue and uncertainty. Have human raters
measure false praise as carefully as false blame.

Avoid endorsing plays merely because the team scored afterward. An
unlucky mechanical failure can follow a sound decision; a lucky goal can
follow a tactical error.

## Engineering and research gates

- Verify the actual t0 and raw event finalization provenance first.
- Run the coverage-first pilot with random controls and separate reviewers.
- Try a small decision-first drill that requires no additional trained AI.
- Add specialized models only when they solve a measured limitation on
  held-out matches and independently reviewed decisions.
- Keep optional features modular; do not merge draft branches automatically.

Defer expensive multi-billion-parameter world-model deployment, training an
entire RL policy, model swarms and strong individualized habit diagnoses
from six readable decisions per player.

A good replay review is not automatically a good teaching intervention;
reviewer agreement is provisional, not perfect tactical ground truth;
source timestamps do not prove the semantic claim was knowable at t0;
and pilot case counts do not guarantee precise false-criticism error rates.

**Architecture selection principle:** build the least complicated experiment
that could falsify a proposed coaching improvement before scaling it.

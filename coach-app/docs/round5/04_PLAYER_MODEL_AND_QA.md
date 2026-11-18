# Round 5, checkpoint 4: player model and evidence-bound natural questions

## Player model (`player_model.py`)

The model keeps four things separate:

| Dimension | What it counts | What it never means |
|---|---|---|
| Preferences | How often the player challenges vs delays as first defender, overall and in two situations: contest-and-cover, late-and-uncovered | Good or bad |
| Decision consistency | Share of judged moments flagged as a concern, per situation | Ability, or a fixed trait |
| Mechanical execution | Decoder `whiff` events per attempted touch | Decision quality |
| Team context | How often the teammate could cover when this player was first defender | The teammate's fault |

**How each rate is computed.** Every rate is a Beta posterior shrunk toward the pooled rate of all players in the dataset, with a 90% interval.

**When something counts as a pattern.** A *pattern* needs **8 or more moments across 3 or more matches** and an interval that **excludes** the pooled rate. Otherwise the status is `insufficient` or `consistent_with_pool`, however striking the raw count. The profile always carries the note: *"Rates describe these matches only and say nothing about ability to improve."*

**Real-replay check (15 matches, 51 player identities, 1,655 reviewed moments):**

| Result | Count |
|---|---|
| Players seen in only 1 match | 46 |
| Players seen in 2 matches | 4 |
| Players seen in 6 matches | 1 |
| Rates that are `insufficient` | 348 of 356 |
| Players with an established pattern | **0** |

The one player seen in 6 matches has 175 moments:
- Challenges as first defender: 43 of 61, the same as the pool (0.705).
- Concern rate in first-defender moments: 3 of 44, **below** the pool (90% interval 0.03–0.15 vs pool 0.15).
- Whiffs: 37 of 284 attempts, consistent with the pool.

So the model tells nobody they have a recurring problem on this data. That is the correct answer for this sample size, and it agrees with PR #17's finding that 0 of 11,628 player pairs were distinguishable.

**Unexpected finding: the cover-first principle may be wrong for these players.** When a challenge would be late *and* uncovered, the pooled players still challenged **59%** of the time. So the cover-first principle in checkpoint 3 flags something most players here do. That is either a common mistake or a sign the principle doesn't fit how these players win. Only expert ratings (PR #16) can tell which, so the verdict stays a hypothesis.

## Natural questions (`coaching_qa.answer_natural`)

Each supported question routes to a deterministic packet type. The model-free answerer and the validator are unchanged from Round 4, with two new rejection rules.

| Question | Packet | What makes it honest |
|---|---|---|
| "Why was that challenge bad?" | `why_flagged` | If the engine did not flag it, the answer starts with a **premise correction** citing the engine's reading |
| "What could I have done differently?" | `alternative_feasibility` | Alternatives with feasibility from t0 arrival times |
| "Was my teammate actually covered?" | `teammate_actions` | Cover time and the cover factor, or "unknown" |
| "Would a higher-ranked player necessarily choose differently?" | `higher_rank_comparison` | States that no higher-rank reference data is loaded and that styles differ; lists the alternatives |
| "Is this a recurring problem for me?" | `recurring_patterns` | Counts, interval and pool from the profile; "not established" below the threshold |
| "What should I practice first?" | `practice_priority` | Only established patterns, ordered by margin above the pool; otherwise says none is established yet |

Questions the evidence can't answer get an explicit abstention listing the supported types.

**New validator rules.** A model answer is now also rejected for:
- a **comparison with other players** (GC, SSL, pros, "higher-ranked") that the evidence doesn't contain;
- **certainty words** ("definitely", "always"…).

The test `test_invented_opinion_from_a_model_is_rejected` checks that "A GC player would definitely have challenged here" is replaced by the deterministic answer.

## Example on a real moment (anonymized; deterministic answerer, no language model)

**Late challenge, t=21.0 s.** Display: *concern, hypothesis*, "Late challenge with no cover behind".

- **Why was that challenge bad?**
  - [E2] Earliest feasible touch at t0: the ball carrier 0.50 s, this defender 0.90 s.
  - [E3] The teammate could be goal-side in 1.73 s.
  - [E5] The defender would arrive after the carrier's touch.
  - [E6] If this defender is beaten, the teammate is unlikely to be goal-side in time.
- **What would change the verdict?**
  - [E11] If 'contest in time' were True, the verdict would be tradeoff.
  - [E12] Same if 'teammate can cover' were True.
- **Would a higher-ranked player choose differently?**
  - [E11] Not established: no higher-rank reference is loaded, and styles differ.
  - Alternatives: shadow (plausible), retreat or boost (plausible), challenge (implausible).

**Shadow, t=55.0 s.** Display: *support, hypothesis*, "Held back when a challenge would have been late or uncovered".

- **"Why was that challenge bad?"** → premise correction: *"The engine did not judge this as bad…"*

## Limitations

- **Not enough repeat observations.** Personalisation needs many matches per player. The public test set has one player with 6 matches, so it can't yet show what an established pattern looks like on real data. The synthetic tests can.
- **Whiffs are unvalidated.** `whiff` is the decoder's definition and hasn't been checked here.
- **The router is pattern-matching.** Rephrasings it doesn't recognise abstain rather than guess. A language model can be added *only* as a router or rephraser over these packets; it never answers outside them.

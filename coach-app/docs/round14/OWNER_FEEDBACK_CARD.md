# Replay Lab — Round 14.5 first-owner feedback card

**Purpose:** 1 real ranked 2v2 replay, a small number of high-information decisions, and useful evidence for the next development round. Adapted from Gemini's proposed rubric; its six situation pairs are **hypothetical tests**, not observations of the owner's matches. Claude's statistical control model came from 15 public replays of unknown rank without expert labels.

## Start with a local no-spend diagnostic

Run `coach-app\start-windows.cmd` on the eventual **final combined integration branch**, then in a separate terminal opened inside `coach-app`:

```cmd
.venv\Scripts\python.exe -m scripts.round14_owner_preflight --replay "C:\replays\your-match.replay"
```

Only statuses/check names appear in the output. It does not decode your replay, contact an AI provider, issue native Rocket League commands, open a browser, send telemetry, expose account IDs, or print paths/secrets. A result of `prerequisites_present_not_verified` means **start the real app test**, NOT that any feature is known to work. If missing packages/HD files are reported, resolve setup first; do not label that as a tactical coaching failure.

## Five useful moments from one match

| Moment to find | Replay evidence to examine | How to challenge the app |
|---|---|---|
| A defensible positive play | Covered aggressive 1st-man challenge, useful 50/50 or aborted challenge | Does the report recognize context rather than force a passive rotation lecture? |
| A questionable choice | Second man overextended, boost-hungry aerial, unsupported challenge | Does it explain rebound ownership and teammate isolation rather than merely next-touch rank? |
| Defensive restraint | Goal-side shadow and small-pad recovery, including if opponent scores | Do V2's separate touch/danger model heads call restraint or tradeoff without outcome blame? |
| Important unflagged moment | A last-man dive or credible fake challenge the automatic shortlist missed | **Manually pin this in Decision Lens** to get a LOCAL deterministic lesson; do not claim the manual pin automatically runs V2 or adds it to the V2 match report |
| Earlier contributing decision | A real risky boost detour before a later impossible save, versus harmless boost pickup | Does the report distinguish chronological association from demonstrated cause? |

If no suitable example exists in the replay, record **not observed**, rather than manufacture a scenario. For outcome-blind comparison, pause at t0, write a brief personal judgment first, then read V1 and V2 and reveal the later result.

## Score once after five moments (0–2 per dimension)

| Dimension | 0 = serious failure | 1 = limited but inspectable | 2 = strong evidence in this test |
|---|---|---|---|
| Replay fidelity & timing | Wrong car/ball/camera or meaningful seek divergence | Playback works but visual/timing roughness | Important actions and clocks line up closely |
| Factual accuracy | Invented boost, role, timestamp, position or future leaked into Stage A | Minor qualifiers/rounding need checking | Inspected source measurements match recorded state |
| Tactical fairness | False blame on good pressure/restraint, unjustified "bad habit" | Some overly cautious/generic reads | Fair to context-dependent aggression and restraint |
| Useful alternatives | Generic filler or claimed guaranteed outcomes | Accurate but obvious tactical options | Specific pre-t0 cue and feasible conditional alternative |
| Source trust | Pretend model success, hide stale/unknown fields or confuse causal credit | Source linked but uncertainty hard to understand | Observed and inferred facts clearly distinguished |

**Interpretation:** 0–10 is a small feedback index, not a scientific validation or a certification of Grand Champion-level coaching. In particular, a 2 in one category means **good in the checked moments**, not perfect fidelity or 100% correctness. Do not silently assume 50 ms or 100 ms is a verified technical threshold: record *observed* clock offsets with playback/seek context and use them to decide whether the mismatch matters.

## Three fast questions for each report card

1. Could its main takeaway be pasted onto a completely different clip? If yes, its specificity may be poor.
2. Hiding the future, would the same choice still be defensible? If yes, a retrospective goal is not proof of a mistake.
3. After the first touch, who likely owns the rebound and who can recover? If the model only reasons about reaching the ball first, note the missing second action.

**Important scope distinction:** V1 is a local deterministic experimental report, V2 is a local experimental statistical match report, and a genuine external AI coach needs an owner-configured provider and separate explicit opt-in. All three can differ. A manual pin gets local source-backed review, **not a V2 rerun on that pinned moment**. For multi-match V2 habit inference, use the separate multi-replay CLI with several real matches; one match must not produce a rank-calibrated habit verdict.

## Copy per problem

```text
Replay: private local nickname only; do not upload raw player IDs
T0: MM:SS.s (replay-relative seconds)
Mode: HD / HD+2D / V1 / V2 / local manual / actual opt-in AI
What the replay visibly shows, as of t0:
Exact coaching claim or visual defect:
Decision-time evidence that supports/challenges it:
Better GC-level interpretation, including the competing action:
Outcome already known when judging? yes / no
Error category: factual / unfair criticism / generic / missed moment / root cause / time sync / source uncertainty / UI / other
Severity: blocker / major / minor
Scorecard dimension affected:
Anonymized local feedback export / screenshot:
```

## Post-test prioritization, not a preset verdict

Investigate first whichever *observed* trust-breaker is most severe: (i) fabricated/hindsight/unfair coaching, (ii) wrong player, telemetry or 3D/2D sync, (iii) first-touch bias or missed high-leverage decisions. This ordering is a hypothesis from Gemini; reorder from actual user feedback. Do not add another feature round before reviewing recorded issues.

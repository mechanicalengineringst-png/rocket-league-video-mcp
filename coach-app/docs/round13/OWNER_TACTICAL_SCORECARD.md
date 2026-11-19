# Round 13 — former-GC full-match coaching acceptance scorecard

**Use after the technical smoke gates.** A passing renderer/build is necessary but not sufficient: the user needs useful and fair tactical coaching in real 2v2 matches. This is a **human evaluation form**, not a claim any labels have been collected. Keep raw replays/private player IDs local.

## Replay selection

Use three authentic 2v2 ranked replays if available: one close win, one close loss, and one overtime/comeback or unusual matchup. Do NOT cherry-pick only clean highlight plays. Mark the player's identity explicitly. The HD browser replay, map and backend are the same integration SHA. Set `REPLAY_LAB_REPLAY_PATH` on the Windows tester for the strict browser harness; the custom owner-judgment cards below remain manual.

## Six high-information moments to judge

Select at least six distinct situations across the three matches, mixing **automatic** and **unflagged/manual** selection. Try to include:

- Sound aggression with teammate cover (positive play; *not* automatically a mistake)
- Sound shadow/delay or aborted challenge even if the outcome is bad
- Questionable last-man dive or boost detour (record circumstances that make it conditional)
- Second-man spacing/coverage around a teammate's possession or 50/50
- Recovery with direct, small-pad and big-boost route alternatives
- One clearly important missed early contributor from `t0 - 3s` to `t0 - 6s`

Do **not** fabricate examples if a match lacks a class. A quota of positive *labels* can cause false praise just as a negative-only model causes false criticism. Prefer recording a missing class honestly.

## Evaluate each moment BEFORE seeing advice

For each moment save **replay-relative t0**, selected player's role, whether the detector auto-flagged it, and a 1–2 sentence owner judgment about defensible actions and teammate coverage. Use the built-in blind review Stage A as much as possible, acknowledging if the user already knows the outcome. Then reveal the source-backed report or optional AI and record:

- Was the source geometry/boost/heading/timestamp factually correct?
- Did it fairly recognize an important alternative? What tradeoff/uncertainty mattered?
- Did it confuse a good decision with an unlucky outcome, or a lucky goal with a good decision?
- Was its takeaway *specific* enough that it could not be pasted onto any unrelated 2v2 match?
- Was it worth an experienced 2v2 player's time, or generic noise?
- Which useful play was **missed**, if any? Does manual review understand it?

Use the existing local JSON exports; do not upload private replay telemetry without intending to.

## Scorecard (0 = blocked, 1 = partly usable, 2 = good; N/A for untested)

| Dimension | 0 — blocker | 1 — limited | 2 — usable and credible |
|---|---|---|---|
| Replay identity/ingestion | wrong player or match; decode fails | works with identity warning | correct player, complete replay |
| HD pitch and vehicle | wrong car/ball/teleport artifact | mostly correct but visual roughness | credible pitch/wheels/ball, no teleport streaks |
| Camera and mechanics readability | cannot judge play | some ballcam/camera limitations | can inspect critical rotations and aerials |
| HD/map/episode time | material seek or event mismatch | occasional recoverable drift | correct times on forward and backward seek |
| Automatic moment selection | mostly generic goals, missed roots | some useful and some noise | small high-value shortlist, includes good decisions when present |
| Tactical fairness | obvious false blame, dogmatism | tradeoffs occasionally missed | sound decisions respected and conditions distinguished |
| Options and teachability | generic or fictitious guarantees | modestly actionable alternatives | contextual options with genuine costs/unknowns |
| Evidence and time firewall | incorrect source facts or hindsight | rare reviewable omissions | telemetry correct, unknowns explicit, Stage A independent of future |
| **Actual opt-in AI model** | provider failed or fake fallback | runs with caveats | real provider gave useful source-cited suggestions |

Treat **N/A** as not evaluated, never as 2. A model that was not configured **cannot** be called fully accepted. The first eight rows can be evaluated without an AI provider. Do not collapse all rows into a single score that hides a critical blocker. One demonstrable false numeric fact, severe temporal leak, wrong-player attribution or false claim of provider use should block release until resolved.

## Issue template for every defect

```text
Replay: private local identifier (do not include public account IDs)
Integration branch and commit:
T0 (replay-relative seconds):
Mode: HD + Map / 3D / 2D / Native companion (if enabled)
Selection: automatic / manual
Observed issue:
What the replay actually shows:
What the coach claimed:
Alternative(s) and decisive unknowns:
Classification: factual error / false criticism / missed moment /
                temporal leak / generic teaching / renderer or sync
Severity: blocker / major / minor
Owner screenshot or local anonymized export:
```

## Boundaries

CI source checks cannot prove strategy. Estimated reachability is not proven intent; unrecorded voice communication, camera visibility and opponent fakes remain unknown. The experimental situation-aware report is deterministic and uncalibrated. An actual AI provider is separately opt-in and uses source-backed `CoachDraftV0` proposals. Native Rocket League commands are a separate owner-controlled test and not proof of the standalone renderer.

**Next development round should prioritize the most severe timestamped tactical false claims, missed high-value opportunities and visual trust failures**, rather than adding more overlays for their own sake.

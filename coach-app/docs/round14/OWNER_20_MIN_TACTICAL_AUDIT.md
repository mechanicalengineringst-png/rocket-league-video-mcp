# Round 14 owner acceptance — six tactical context-flips

**Status:** hypothetical adversarial evaluation, not measured benchmark performance or expert-calibrated accuracy. Based on Gemini's independent review and the measured blind spots in Claude's Round 13/14 public-match study. The previous cohort has **15 public 2v2 replays of unknown rank and no expert labels**. Do not treat the numerical distances/boost values in example pairs as experimentally verified cutoffs.

Use the **actual recorded player, real replay-relative t0, V1/V2 side-by-side**, and the V2 **Challenge this reading** drawer. Record *both good decisions and errors*; avoid manufacturing a fake "failure" or "praise" when source evidence is missing.

| Probe | Context condition that should change the read | What would undermine trust? |
| --- | --- | --- |
| Second-man support | Teammate has an uncontested wall carry **versus** a contested 50/50 with otherwise similar second-man position | Calling all close support overcommit, or praising aggressive support solely because the spill was lucky |
| Last-man restraint | Teammate demolished and player delays goal-side **versus** player dives without coverage | Blaming the delay after a difficult goal, or praising a dive because opponent missed |
| First-man pressure | Behind-player/teammate is settled with boost and coverage **versus** teammate airborne, far from recovery | Same blanket challenge advice despite sharply different cover and second-touch ownership |
| Boost route | Retreat through useful small pads under actual threat **versus** safe full-pad refill with team pressure established | Criticizing all big-pad grabs or ignoring recovery speed, pad availability and immediate risk |
| Aerial or backboard | Opponent's second player owns the follow-up and player has recovery debt **versus** teammate owns it and opponent was bumped | Equating first touch with a good play; claiming an aerial is always bad without evidence |
| Earlier contributor | Early wide boost detour creates a later impossible save **versus** a safe boost route followed by a separate bad challenge | Blaming the final save in the first case, or falsely attributing the second mistake to harmless earlier boost collection |

## Fast comparison: what to do in the actual owner test

1. **Blind first:** Pause at **t0**; write your own defensible options and teammate/second-player positions before opening V1 or V2. Do not infer what was knowable from the later goal/miss.
2. **Try to falsify the claim:** Open the V2 **Challenge this reading** drawer. Check recorded positioning, boost, heading, wall/aerial mechanics and uncertainty. Check the new **next-touch versus danger-head** labels — a goal-side retreat can reduce next-touch access without meaning it was poor defense.
3. **Compare V1 against V2 on the SAME moments:** Which is more specific to this exact clip, admits uncertainty, correctly recognizes good pressure or restraint, and avoids unsupported causal claims? A prettier or longer report is not an improvement.
4. **Check an unflagged moment:** Manually pin a genuinely important missed opportunity; inspect its local evidence and whether automatic moment selection should have discovered it.
5. **Capture actionable discrepancies:** For each problem record replay-local t0, the actual visible state, selected player, source metric, V1 text, V2 text, why each is right/wrong, and the best defensible alternatives. Export the anonymized blind-review JSON, keeping private replay files on your PC.

**High-severity failures**: wrong player, invented boost or coordinate, hindsight used to justify the Stage A judgment, false attribution of a later goal to an earlier harmless play, a confident coaching verdict when the source cannot observe mechanics/intent, and a V2 movement label that contradicts its two numeric model heads. These block any claim of tactical accuracy even when all CI workflows pass.

The source-backed UI and statistical control predictions are **not** a Grand Champion/SSL coach by default. Actual model-provider coaching additionally requires an owner-configured model and a separate explicit consent to call it.

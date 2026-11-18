# Replay Lab — Round 6 Cross-Agent Strategy Meeting (Preliminary)

**Research reviewed 17 November 2026. NOT final product decisions or permission to edit the game.** This document synthesizes the Gemini, Claude and Antigravity research reports provided in conversation with ChatGPT's independent investigation. It preserves decisions without committing private user-uploaded reports or Windows paths to the public repository. Read alongside the [Project Compass](replay-lab-project-compass.md), [independent report](REPLAY_LAB_ROUND6_INDEPENDENT_RESEARCH.md) and [deep-dive addendum](REPLAY_LAB_ROUND6_DEEP_DIVE_ADDENDUM.md).

## A. Core conclusion: coach tactical EPISODES, not just touches

Our purpose is expert 2v2 coaching. A replay's observed contact, immediate threat, and actual goal are not equivalent to a strategically sound decision. Many important causes lie 5–20 seconds before the decisive touch: earlier rotation, overusing boost, teammate cover, field awareness or giving up possession. An expert coach needs to distinguish decision selection, mechanical execution, teammate responsibility and an opponent's excellent play. Good aggression and unconventional plays must be recognized.

**Recommended experimental pipeline:** 5–20s tactical episode with 1–3 decisive commitment points -> precommitment evidence and possible player visibility -> physically feasible alternatives -> 2–3 bounded consequence branches per action -> teammate cover, possession, pressure, boost and recovery -> grounded concise explanation and follow-up -> expert comparison. The independent replay/2D map and native game are visual support for those explanations.

The central missing component remains **next controlled possession / opportunity value** after a challenge or forced 50/50. Time to FIRST touch alone is not enough.

## B. What each researcher contributed

- **Claude:** Consequence sets for each feasible decision, who reaches the likely resulting spill, pressure value beyond possession, team responsibility, and the possibility that judging isolated t0 choices is the wrong unit. Proposes a small 12-case/two-rater diagnostic with valid and invalid user pushback. Do not burden Claude with another exhaustive pass while usage is constrained.
- **Gemini:** Strict pre-t0 evidence firewall; bounded multi-action/opponent-response options; conditional high-rank exemplars; expert-ranked action sets and player-perception context. Proposes a short-horizon physics-response matrix and conformal action sets. These remain **unproven proposals**, not ready algorithms or statistical guarantees.
- **Antigravity:** An audit of existing official Rocket League Stats API PR #20, possible native two-window desktop companion, later Windows Graphics Capture, truthful private video clips, and interim mobile 2D+recorded video. Report says a locally found API config contained PacketSendRate=0 while game was closed; **no actual game handshake or capture test was run**. Independent docs report: https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/blob/docs/native-game-integration-and-visualization-architecture-20261117/docs/research/NATIVE_GAME_INTEGRATION_AND_VISUALIZATION_ARCHITECTURE.md
- **ChatGPT:** MIT-licensed replicar v2 may offer packet-update provenance and strong retrospective reconstruction; curated 49,658-match 2v2 dataset and existing possession/value research offer candidate features but no expert merit labels; existing optional Gemini review likely samples whole-match frames despite a named local decision. Test LLM tools against deterministic baseline with real blinded ratings rather than simply adding richer prompts.

## C. Five critical corrections to the reports

1. **Gemini's exact 1.2-second RocketSim 4-by-3 action matrix, exact 50/50 exit cones and sub-15ms performance are not demonstrated on Replay Lab.** Unknown real controls, opponent choices, available boosts and wall physics prevent exact alternate futures. Represent outcome cones/ranges and assumptions; never call them ground truth.
2. **High-ranked action popularity is not a wisdom label.** A proposal to automatically suppress criticism if 20% of comparable SSL players choose an action can preserve common errors, ignore hidden comms and misclassify superficially similar positions. Reference replays are exemplars and candidate-generation data, not an automatic fault immunity rule.
3. **Conformal 90% set coverage does NOT guarantee at most 10% false criticism of sound plays across ranks/styles.** Standard marginal coverage needs exchangeability and a well-defined true label. GC2/SSL historical action distribution has no expert-best-action labels; conditional coverage for uncommon playstyles and distribution shifts is not guaranteed. See https://proceedings.mlr.press/v306/braun26c.html.
4. **Actual player camera/awareness cannot be proven by reconstruction alone.** The game may not record continuous eye swivel, comms, audio perception or camera settings, so a reconstructed frustum is a possible visibility bound, not proof the player saw or ignored a teammate. An exemplary JSON packet's fixed 110-degree field of view and exact time-since-seen are illustrative, not observed.
5. **Native game control is not video streaming, and capture is not free.** Antigravity's claims of 100% native visuals with zero GPU rendering overhead and flawless low-latency capture are unsupported: game and capture/encoding cost GPU resources. Windows Graphics Capture requires supported OS/device and local permission; Microsoft's Win32 sample explicitly says minimized windows cannot be captured. Source: https://github.com/microsoft/Windows.UI.Composition-Win32-Samples/blob/master/cpp/ScreenCaptureforHWND/README.md

Additional engineering cautions:
- Official Rocket League config documentation locates TAStatsAPI.ini in the **GAME INSTALL DIRECTORY**, but Antigravity's permission request names a different **Documents/My Games** path. Verify which file is actually loaded before editing anything. Source: https://www.rocketleague.com/developer/stats-api.
- Official UpdateState has both Players[].PrimaryId and Shortcut. Runtime identity matching may solve player-focus mapping more simply than guessing index order.
- HUD hidden does NOT guarantee anonymous clips. Inspect whether nametags, scoreboard or later outcomes remain. The 40-clip choice/timing study may show post-t0 evidence to label observed action; blinded tactical-merit clips must end at t0.
- **Owner explicitly wants interactive standalone 3D on phone eventually.** Antigravity's preference for native clips + 2D can be an optional interim mobile presentation, NOT a silent replacement of that requirement.
- The Gemini reports' numerical PCEP examples, theoretical odds, GPU runtimes, suggested 90-second labeling rates and threshold values are **illustrative hypotheses**, not measurements.
- Pearl player-masking/next-goal score differences do not causally assign teammate fault. Outcome prediction and optimal action valuation are different problems.

## D. What is documented versus verified

**Official documented:** Rocket League Stats API supports LoadReplay, SeekReplay, ChangePOV, SetGameSpeed, SetMatchPaused, and HUD visibility, after opt-in config. UpdateState exposes player spectator shortcuts and replay elapsed/frame. It does not directly export native video. https://www.rocketleague.com/developer/stats-api.

**External source claims:** replicar v2 offers update-age, raw network columns and 120Hz fitted trajectories, but fits omitted controls from later replay packets. Do not use future-fitted values as information available at decision time. https://github.com/Rolv-Arild/replicar

**External source claims:** the high-rank dataset reports 49,658 2v2 matches; no independent sample quality, license or tactical optimality labels verified. https://github.com/Rolv-Arild/rl-high-level-dataset

**Model API documented:** Google's Gemini Decisions API can score bounded questions, but its probabilities are not verified Rocket League tactical confidence. https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/

**Not verified on owner's PC:** game Stats API end-to-end, any live window capture, 1080p60 clips, true mobile playback parity, expert-agreeing coaching output, trained local tactical LLM.

## E. Proposed research-to-development gates (owner approval required)

**Gate 1: 12-case diagnostic, not a misleading accuracy claim.** Select a balanced set of important 2v2 situations from at least 3–4 independent replay matches, including good aggression, good restraint, flawed challenges with lucky outcomes, good challenges with bad outcomes, intentional lost 50s, double commits and unknown boost. Freeze selection criteria BEFORE expert labeling. At least two experienced independent reviewers watch pre-t0 evidence, rank acceptable actions and note the most important earlier root cause. Preserve legitimate disagreements. Their detailed comments become the first quality target.

**Gate 2: reliable data and bounded consequences.** In a small local read-only test, compare raw source/unknowns against replicar updates/network and current parser rows; reject any field whose t0 value changes when later packets are deleted. On a few difficult episodes, enumerate 2–4 realistic actions, a few opponent responses, follow-up controlled touch, teammate cover and boost/recovery, with uncertainty. Do NOT claim a perfect dynamic game solver.

**Gate 3: does a language model truly help?** Only with owner's approval for API spend/telemetry uploads, compare a deterministic evidence brief, one model receiving an immutable pre-t0 packet, and a read-only tool-using model using identical cases. Blindly score factual support, false blame of sound play, insight/teaching quality, valid alternatives, sensible abstention, and resistance to outcome-based pushback. If tools only increase rhetorical confidence, keep the model as a conversational tutor, NOT the tactical judge.

**Gate 4: optional native-game local proof.** Verify the active Rocket League install and config with the owner, request permission BEFORE editing PacketSendRate or controlling the actual game. Load/seek/pause/speed/focus; match Players[].PrimaryId/Shortcut with parsed replay and verify clock. If successful, test WGC and real honest clips as a separate experiment. Keep browser HD fallback.

**Gate 5: train small specialists only if justified.** Audit a small rights-permitted high-rank sample, an existing possession model and independent expert preference labels. A local large language model is not the initial obstacle. Preference/rank/possession specialists can be tested later against withheld complete matches; outcome labels alone cannot establish correctness.

**Quality measure:** can a highly skilled player learn something specific and defensible about a sequence, especially why an earlier choice shaped the later play, without being falsely criticized for smart aggression? One excellent grounded teaching episode is better than dozens of generic findings.

## F. Open decisions for owner

1. Approve an **episode-first, coaching-first 12-case proof**, with independent tactical-merit reviewers and a model comparison. Suggested YES.
2. When at Windows PC, approve an opt-in **native API test**, but check the actual installation config path first. Suggested YES after clear permission.
3. Decide whether sanitized telemetry and selected genuine frames may leave the PC for Gemini API testing and set a budget cap. Default NO until explicitly allowed.
4. Retain the explicit requirement for **independent interactive 3D mobile playback**, with private native clips as optional supplements. This is already a standing requirement.
5. For strategic advice, require multi-choice nuance and conditional tradeoffs rather than a single authoritative false certainty. Suggested YES.

**Branch memory:** This synthesis is documentation in draft PR #25, not merged. The project compass must link here; no code, permissions, installs, training, paid calls or production changes result automatically.

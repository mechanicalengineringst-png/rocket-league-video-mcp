# Replay Lab — Round 6 Deep-Dive Addendum: What We Were Missing

**Research only, 17 November 2026.** Companion to [initial independent report](REPLAY_LAB_ROUND6_INDEPENDENT_RESEARCH.md) and [Project Compass](replay-lab-project-compass.md). No architecture selected, code changed, samples downloaded, paid API calls made, local game commands sent, or tests run. External performance measurements are **author-reported**, not independently reproduced.

## 1. Executive verdict

Our strategic bottleneck is **validated decision quality**, not merely accurate geometry, next toucher prediction, replay smoothness, or elaborate language-model prose.

Five opportunities worth explicitly investigating before building more code:

1. Reuse an existing **provenance-aware reconstruction pipeline**, possibly replicar v2, while separating retroactively fitted states from causally available evidence at decision time.
2. Benchmark **actual alternative replay viewers** and native-game integration before investing in another 3D rebuild.
3. Address the **player visibility/perception gap**: omniscient replay positions are not the information the human could see or infer during play.
4. Use **2v2-specific tactical geometry** rather than static teammate distance; recent large observational research provides a promising, not causal, feature list.
5. Compare a human-calibrated, **conditional action-preference dataset** with Gemini tool reasoning, a narrow calibrated possession/value model and the new Gemini Decisions API, rather than rushing into local LLM training.

## 2. The most dangerous missing distinction: what the player could know

A replay lets a post-match coach see all four cars and the ball. The actual player at decision time may not have seen an opponent behind the camera, the other cars' boosts, teammate comms, or a ball path after the commitment.

Three state regimes must NEVER be silently merged:

- **Decision-time global state**: world observations that are available by t0 from recorded packets without later fitting or backfill. This can support general tactical risk.
- **Player-perceivable state**: own camera FOV, last known locations, possible rear-view/swivel, audible cues and comms; some values and POV controls may not be recorded. This controls whether we blame the player for awareness.
- **Retrospective state**: reconstructed exact trajectories, eventual impacts/goals, and inverse-fitted controller inputs, possibly using future packets. Useful to explain what later occurred, not for judging what the player knew or could guarantee.

Strongest proposed additional schema fields: physical event time, last native observed update, packet actually available by, source of sampled/interpolated state, last source frame used in an inference, real decision commitment interval, camera/visibility evidence, teammate-communication status, player execution ability, and whether any claim is retrospective.

**Counterexample:** If the opponent had a free lane behind the player's back but the opponent was outside possible camera visibility, the coach may explain why the commitment exposed the team and suggest checking surroundings before committing, but must not assert "you ignored the obvious second opponent." The latter infers visibility and mental state from an omniscient postmatch trace.

Official Rocket League camera supports adjustable FOV, height, angle, distance, stiffness and swivel; absence of the exact player look history reduces observability. Source: https://www.epicgames.com/help/c-37599050/c-32343914/a14443106

Formal research motivates caution. Off-policy evaluation with latent confounders can be nonidentifiable under realistic assumptions; multiplayer decisions are partially observed:
https://proceedings.mlr.press/v238/kausik24a.html
https://proceedings.neurips.cc/paper_files/paper/2022/hash/743459dae9b2c5d2904e5432d5298128-Abstract-Conference.html

**Mandatory invariance test:** Keep every pre-t0 native packet identical; mutate future goals and touches. A t0 merit verdict must remain the same. Fitted historical poses that change on future deletion are not admissible as observed t0 facts.

## 3. Potential data pipeline shortcut: replicar v2

Primary repository, MIT licensed:
https://github.com/Rolv-Arild/replicar
https://github.com/Rolv-Arild/replicar/blob/master/docs/v2-guide.md
https://github.com/Rolv-Arild/replicar/blob/master/docs/v2-file-format.md

Upstream describes RocketSim replay reconstruction as 120Hz simulation ticks or native frame rows in a Parquet file. It contains ball and player motion, boost/pad state, event/contact data and information on state provenance. The optional network group includes raw decoded values and last-change frame fields; updates includes update flags/age. **This is worth auditing before we create another custom packet-freshness and binary data format.**

However its fitted controls and between-packet simulation may use later packets. The upstream additional future group is outright outcome/lookahead material. A last-change-frame or inferred source tick does not automatically prove information was already available to an actual in-game player at a particular timestamp. Need distinguish physical event time, original publication time and time of reconstruction.

The authors report position error med/p90/p99 around 0.03/3/35 UU on a 60-replay sample, not independently validated here; local RocketSim arena collision mesh availability, resource use, wall behavior and true native camera equivalence remain blockers.

**Decisive low-cost evaluation:** with a user-approved replay, compare raw native actor updates vs our normalized 30Hz frames vs replicar original network/updates/fitted state on 50 t0 cases, then delete later packets. Audit any predecision field whose value changes retrospectively, plus conversion time/memory/size on the user's machine. Independently compare car/ball visual fidelity. Do not adopt if the provenance benefit or performance is not actually demonstrated.

## 4. Recovering player controls does not recover intent or causal alternatives

https://github.com/Rolv-Arild/replay-pretraining

This inverse-dynamics approach estimates likely human controller inputs using before/after motion. It may help with mechanical reconstruction, human action priors and a narrowed trained controller policy. It cannot establish the actual button presses or what the opponent would have done under a different action.

The research has nuanced parser dependence: historical academic work reports some input signals (throttle, steer, handbrake, jump, boost) were available in some replay-processing datasets, while analog pitch/yaw/roll needed imputation. The blanket claim "NO controls are ever present in a replay" is insufficiently precise; inspect actual fields and distinguish parser inference from recorded values. Some upstream inverse-dynamics code is GPL, so do not incorporate without checking obligations.

Source: https://nevillewalo.ch/assets/docs/MA_Neville_Walo_Seer_RLRL.pdf ; https://github.com/Rolv-Arild/replay-pretraining

## 5. Public high-rank data: scale exists, tactical preference labels do not

Original high-rank project reports **49,658 curated 2v2 matches** plus 1v1/3v3:
https://github.com/Rolv-Arild/rl-high-level-dataset
https://www.kaggle.com/datasets/rolvarild/high-level-rocket-league-replay-dataset

A second source already publishes parsed rlgym-tools ReplayFrame numpy arrays with explicit train/validation/test and smaller "smol" split:
https://huggingface.co/datasets/Rolv-Arild/hlrlrd-parsed
https://huggingface.co/datasets/Rolv-Arild/hlrlrd-parsed/raw/main/README.md

**Source review result:** GitHub API metadata showed the public source repository has no declared license; dataset card contains file path splits but no demonstrated expert decision-merit annotations. Reuse/redistribution/training rights need checking, and a 400+ GB parsed corpus is not a rational initial download. No files were downloaded here.

Suggested sample-level audit: exact replay and content ID, duplicate-upload detection, rank/playlist, patch/season, map, four actor traces, missing packets/boost, team identities, duration, play interruptions, datatypes, action availability, per-game source provenance. **Verify hashed splits are match-group-separated** rather than assuming a file-prefix hash guarantees no duplicate matches across splits. Keep all player identities and original replay content out of public GitHub.

Human imitation learns "how high-ranked players acted" — including their mistakes, partial information and individual intent — not automatically which other action would have been strategically better. Evaluate on unseen matches and styles.

Related research:
https://github.com/Rolv-Arild/Pearl — next-goal prediction, player masking and Shapley-style contribution are not proven alternate-action causality.
https://github.com/Rolv-Arild/EARL-pytorch — entity-based next-goal representation is not a human coaching ground truth.
https://github.com/mira-wm/mira — 5B 2v2 video world model trained on bots, not demonstrated GC/SSL decision coaching.

## 6. 2v2-specific empirical geometry: a serious challenge to naive heuristics

The Pacifist Labs 2026 Spacing Study:
https://pacifist.ac/rocket-league-spacing-study/
https://pacifist.ac/rocket-league-2v2-research/

Its author reports 10,882 raw files, 10,698 match-GUID deduplicated games and 10,488 main 2026 2v2 matches, with separate Platinum, Diamond, Champion, GC, SSL and professional cohorts.

In paired winner/loser comparisons, the team with higher **overall teammate distance** won about 50.1% of SSL cases (not a useful discriminator). The team with greater **longitudinal second-man depth behind first man** won 63.2% of SSL and 64.3% professional matches. After matching teams within two percentage points of attacking-half time, higher depth won 61.4% of 1,484 matches (reported 95% CI 58.9–63.8). The author explicitly warns: these are **observational associations**, not evidence adding a specific UU separation causes winning.

Their reported professional play had different second-man depth distributions across defense/midfield/attack, and two elite players (Zen/Nass) displayed similar total teammate distance with very different depth. The author's commercial relationship to the associated coaching program and lack of our own raw replication require independent caution.

**Design implication:** do not restore "teammates close => mistake" or replace it with "deeper always correct". Candidate features should be team-frame longitudinal depth, lateral separation, teammate heading and recovery vector, cover **time** against plausible opponent exits, possession security, field area, ball threat, speed/boost and tactical style. Ask which situations justify compressing aggressively, not only spreading out.

**Falsifier:** blinded experienced players on a held-out decision cohort find full contextual reach/cover analysis no more useful than raw distance/depth metrics. Do not promote a correlation to an expert rule without a comparison.

The same research group reports within-rank speed being a weak predictor of winners in its earlier cohort; further warning against simplistic "play faster" coaching:
https://pacifist.ac/rocket-league-2v2-data-study/

## 7. Replay technology competition: why we should compare rather than rebuild blindly

**Other projects already attempt browser replay viewing and native-game live replay control.** Their existence does not prove superior visuals, but the user's rejection of our reconstruction makes head-to-head testing urgent.

| Candidate | Relevant claim | Known blocker |
| --- | --- | --- |
| Official Rocket League game + Stats API | Native graphics/cameras and documented load/seek/POV/pause/speed | PR #20 is schema-corrected but has NO live in-game round trip; browser embedding/capture separate |
| https://ballcam.tv/ | Hosted shared browser 3D replays, cinematic clips, mobile support | No public embeddable SDK or reused source license verified; upload/share privacy |
| https://github.com/intraducine/rl-replay-web | Rust/WASM, local files, camera state, Champions Field assets, IndexedDB, tests | GitHub API shows license null; rendered quality unverified; asset provenance and permissions |
| https://github.com/manucabral/rl-replay-viewer | Browser-local replay, multiple camera modes, xG retraining, motion/e2e benchmarks | GitHub API license null; small/young project, unverified claims |
| https://lndrlndr.github.io/ (CARL2) | Claims synchronized actual game replay control alongside local tactical views | Advertised live mode, but installation instructions call for BakkesMod; transport and EAC compliance unverified |
| https://replaylabs.app/ | Hosted 3D and replay analytics, optional developer API | Proprietary hosting/API license and cost, no SDK verified |
| https://ballchasing.com/doc/getting-started | Mature web 3D replay/stats support | Cloud/privacy, embedding and source rights need checking |
| https://github.com/Drogebot/RocketRP | MIT C# replay and custom training parser/writer, current version support | Parser/serializer, not a drop-in viewer |

**Verification done:** queried GitHub public repo metadata for intraducine/rl-replay-web (May 2026, 142 commits per UI, license null) and manucabral/rl-replay-viewer (July 2026, 11 commits per UI, license null), as well as dataset repository (September 2026, license null). Public repository does not automatically authorize code reuse. CARL2 is self-reported, no actual program run.

**Necessary benchmark:** with an owner-approved replay and native screenshot, compare low- and high-speed ground, aerial, wall, demolition, goal reset, Ball/Car Cam, focus switches, camera shake, depth, stadium materials, ball contact and frame interpolation, timed seek/load and CPU/GPU/heap on same machine. Include at least one phone browser. Owner's usability rating is crucial. If official game controls reliably, prioritize it on desktop and keep independent renderer as phone fallback.

Native control source: https://www.rocketleague.com/developer/stats-api

## 8. Convert coaching into practice (future differentiator, not current blocker)

The product's stated goal is **teaching**, so it is worth investigating how a useful lesson becomes deliberate practice instead of another chart.

RocketRP documents reading/writing custom training files and JSON:
https://github.com/Drogebot/RocketRP

Rocket League's 2026 Season 23 update added more training starting conditions such as car velocity, pitch and boost:
https://www.rocketleague.com/news/rocket-league-patch-notes-v270-season-23-live/

Potential future: coach identifies a specific *mechanical* failure, proposes safe repeatable ball/car setup, exports optional drill, then tests repeat improvement. This is NOT a full recreation of a strategic 2v2 scene; standard training packs cannot reproduce intelligent opponent decisions and teammate communication. Verify format support and only change local game files with user's approval. This is a promising later learning loop, not priority before the first genuinely sound coaching explanation.

## 9. The model landscape changed in November 2026

Official Google Decision API:
https://aistudio.google.com/docs/decisions-api

Announced November 11 2026: Gemini Decision 1 returns typed no/yes, fixed-choice and rubric-score probabilities over shared multimodal input, not natural-language explanations. Google reports no generated output tokens, about 150–250 ms typical service latency and $0.10/M input tokens at launch. Its documentation emphasizes independent atomic questions; it is NOT a conversation agent or physics planner. Its probabilities must be **calibrated on our domain** before being called risk/merit confidence.

New generative choices: Gemini 3.8 Flash, Gemini 4 Hydrogen (Nov 12) and Gemini 4 Carbon (Nov 10). Compare on identical evidence under a fixed schema and cost budget, not by prose length or provider reputation. New models are not guaranteed to understand GC/SSL play.

Crucial privacy setting: Google's official pricing document says free-tier API material can be used to improve products, while paid-tier material is not used for that purpose subject to detailed terms:
https://aistudio.google.com/docs/pricing

Human replay identity/voice/camera content requires opt-in and pseudonymization; no real user replay should be uploaded without explicit approval. The existing old app calls Gemini with a strided whole-match sample even though the prompt claims a selected ±3s time window — fix this *before any legitimate model comparison*. Its one-shot response is not an expert coach.

**Decision 1 experiment**: independent binary checks for unknown boost, whether teammate cover established, whether a 50 outcome could favor teammate, whether current state is too ambiguous. Compare scores with deterministic checks and blinded experts. Model "confidence" cannot be trusted as calibrated chance of an optimal challenge.

## 10. Why offline RL and big local LLM training are premature

A high-rank replay collection is rich in **observed actions and outcomes** but poor in *counterfactual truth*. There is no actual replay of the unchosen shadow route. Players choose actions based on latent factors (comms, camera visibility, opponent expectations, their mechanical ability). Matching apparently similar game states does not remove these confounders.

General formal research:
https://proceedings.mlr.press/v238/kausik24a.html
https://proceedings.mlr.press/v130/bennett21a.html

A strong opponent policy could potentially make a limited physical stress-test, but opponent choice and control are not reliably observed in human replays. A simulation of one alternative branch is a **scenario**, not the history that would have occurred.

More tractable initial objective: **pairwise, conditional action preferences** from experienced coaches. For the SAME frozen pre-t0 evidence, ask if A or B is preferable, under what teammate cover/boost/skill conditions the ordering flips, which branch is robust to plausible opponent responses, and when neither can be judged. Preserve expert disagreement and validate on separate matches. This can create a later specialized ranker without training a giant local language model.

## 11. A practical coaching-value representation

Avoid a fabricated "87% chance your rotation wins" scalar. Instead make a bounded vector for feasible actions:

- control: is the next touch controlled, not just a contact?
- pressure: which opponent exits are restricted or offered?
- teammate coverage: can second man actually intercept the high-danger follow-up in time?
- boost budget/recovery: cost, landing, pad routes, return distance and speed;
- territory/continuity: whether favorable, neutral or bad 50 directions allow a subsequent controlled attack;
- execution risk: human player's demonstrated mechanical ability rather than perfect bot capabilities;
- uncertainty/robustness: at least two plausible opponent responses and distinct successful aggressive vs restrained paths.

Output an evidence-bounded statement and alternate conditions. Example: "An immediate challenge appears to expose a 1v2 IF opponent beats your near-side approach, because teammate could not cover the central exit on present kinematics; a forced low 50 toward teammate may still be sound if that angle was reachable." Not "you definitely caused a goal by challenging."

## 12. Experiments with explicit stop/go conditions

### E1 — Causal replay provenance audit (no model spend)

Input: user-permitted actual replay, at least 50 t0 moments. Compare decoder 30Hz sampled row, raw native actor data, replicar v2 network/updates/fitted data. Track sample freshness, missingness, future-fitting sensitivity, replay time vs physical event time, actual resource cost on Windows.

STOP: if a proposed t0 observed field changes when later packets are deleted, quarantine it; don't use in merit reasoning. PASS for coaching only when source fields and time availability are justified, or uncertainty explicitly shown.

### E2 — Choose desktop and mobile viewer by real measured experience (no AI spend)

Compare user's running HD branch PR #24 to actual Rocket League replay via official PR #20 and one or two browser alternatives. Same replay/timestamps/selected player. Test ground, aerial, wall, reset, Ball/Car Cam, camera height, graphics, sync, CPU/GPU, desktop/phone. Respect license and privacy; no unsupported game mods. User reports whether each is clearer than native and acceptable for 2D+coach integration.

STOP: if native game control works and consistently beats a browser clone on desktop, freeze parity rewrites there. Preserve standalone independent renderer for mobile.

### E3 — Human-blinded model comparison (small but genuinely informative)

Prepare 12–20 varied cases from at least 4 complete replays: excellent aggressive decisions, correct restraint, weak recoveries, successful bad challenges, smart failures, forced 50s, unknown boost, off-camera opponents. Experienced reviewers independently label t0 sound/risk/tradeoff/indeterminate *before outcome*, and action-pair preferences.

Compare fixed deterministic reach/coverage brief, a simple fixed-packet Gemini baseline, tool-using Gemini, optionally Gemini Decision 1 or another provider, with equal source evidence and explicit token/tool budget. Require claim-level source support, uncertainty, no fake intent and a useful follow-up. Shuffle anonymous outputs. Split by entire match, no tuning on holdout.

GO: model improves expert-rated usefulness AND unsupported-claim/false-blame measures vs baseline. STOP if it only sounds more convincing. Pilot is small and not a population accuracy percentage.

### E4 — Contextual team geometry

On blinded 30-case first/second man positions compare distance only, longitudinal/lateral geometry, then reach/cover/boost context. Test defense/attack/transitions, intentional compression, fast pressure, fake challenges. Validate against human-preferred reasons, not retrospective winners. Discard static new heuristics if they create false blame.

### E5 — High-rank data/value audit

Inspect a small rights-permitted sample of parsed dataset (smol), metadata/rank/split/duplicate integrity, and sab-rl-metrics pre-shot possession/goal risk. Check that goals and future source data do not leak into t0. Benchmark on unseen complete 2v2 matches; remove learned value feature if no improvement beyond time-to-touch/cover baselines.

### E6 — Optional coach-to-practice trainer (future)

In a separate safe local test, round-trip one training file through RocketRP without touching actual game files. Determine whether user can load a mechanically plausible targeted drill. Do not promise full 2v2 opponent or teammate recreation.

**All experiment thresholds must be agreed before opening results; a single impressive backboard explanation does not prove general expertise.**

## 13. How this interacts with active branches

- PR #22 Claude: valuable reachability, decision candidates, t0 vs retrospective layering, but uncalibrated strategic thresholds, unknown/finite boost and missing telemetry faults.
- PR #16 ChatGPT: separate 40-clip commitment-timing study and independent tactical-merit review, match-level comparison, FFprobe rejection of fake one-frame videos.
- PR #20: official native command protocol work existed **before** this research, real game test still missing.
- PR #23: UI camera improvements but bad first-player-only binary 200× comparison and dummy WebM exporter, not ready for expert footage.
- PR #24: user-directed uncluttered HD+2D, not yet integrated with advanced coach.
- PR #25: project compass + this research. Docs-only, no automatic merges.

The next strategic meeting must choose whether to invest in the tool-using LLM, the preference-model path, calibrated advantage features, data reconstruction, native desktop viewer and independent mobile fallback **based on evidence and user constraints**.

## 14. Meeting decision table

| Decision | Provisional path to test | Falsifier |
| --- | --- | --- |
| Coaching judge | Evidence-frozen expert-calibrated tool-LLM plus physical/action features | LLM no more correct/useful than deterministic evidence |
| Local model training | No full LLM; later small skill/possession/preference specialist | High-rank corpus and labels unreliable or no holdout benefit |
| Telemetry | Benchmark replicar network/provenance vs existing parser | Future-fit leakage or heavy local cost |
| Native desktop | Optional Stats API and native game if actual game round trip works | Failed focus/timing, unsupported capture |
| Standalone mobile | Compare current HD and other browsers; keep independent mode | Competitors fail quality, rights or performance tests |
| Tactical spacing | Time to cover and context-aware longitudinal depth | Expert disagreements / spurious correlations |
| Value model | Limited, calibrated proxy, not counterfactual causal oracle | Unreliable on 2v2 holdout |
| Gemini Decision 1 | Narrow independent scorer after human calibration | Incorrect confidence or failure on unknowns |
| Coaching practice | Later custom training for repeatable physical weaknesses | Cannot represent required mechanics / not useful |

## 15. Sources and explicit evidence levels

Official:
- https://www.rocketleague.com/developer/stats-api
- https://www.rocketleague.com/news/rocket-league-patch-notes-v270-season-23-live/
- https://aistudio.google.com/docs/decisions-api
- https://aistudio.google.com/docs/pricing

Project sources and author reports:
- https://github.com/Rolv-Arild/replicar
- https://github.com/Rolv-Arild/replicar/blob/master/docs/v2-file-format.md
- https://github.com/Rolv-Arild/replicar/blob/master/docs/v2-guide.md
- https://github.com/Rolv-Arild/replay-pretraining
- https://github.com/Rolv-Arild/rl-high-level-dataset
- https://huggingface.co/datasets/Rolv-Arild/hlrlrd-parsed/raw/main/README.md
- https://github.com/Rolv-Arild/Pearl
- https://github.com/ch-lum/sab-rl-metrics
- https://pacifist.ac/rocket-league-spacing-study/
- https://github.com/intraducine/rl-replay-web
- https://github.com/manucabral/rl-replay-viewer
- https://ballcam.tv/
- https://lndrlndr.github.io/
- https://github.com/Drogebot/RocketRP

Status distinction: **documented by primary source** is not **verified on our machine**. **Authors report** is not **replicated by us**. **Research hypothesis** is not **implemented**. **Experiment proposed** is not **run**. **No new code or training** in this research addendum.

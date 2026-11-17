# Reusable technology survey

Checked on 17 November 2026 by cloning each repository and reading code, not READMEs alone.
"Weights" means trained parameters a project actually ships.

## Ranked by usefulness to Replay Lab

| Rank | Project | What actually exists | Weights | Licence | Verdict |
|---|---|---|---|---|---|
| 1 | [subtr-actor](https://github.com/rlrml/subtr-actor) `scripts/threat_model/` (already our decoder, pinned 1.5.1) | A five-second scoring-threat model and a 10-second touch xG model. Entity network: shared per-player layers pooled within each team, invariant to player order, averaged with its left/right reflection. Trained on 2,540 ranked-doubles replays with date-partitioned splits. Reported held-out frame AUC 0.909, log loss 0.121 on 381 test replays ([EVALUATION.md](https://github.com/rlrml/subtr-actor/blob/master/scripts/threat_model/EVALUATION.md)). Runs natively in Rust and WASM | Yes, compiled into the decoder | MIT | **Use it. Validate it, do not retrain it.** Trained on doubles only. |
| 2 | [ch-lum/sab-rl-metrics](https://github.com/ch-lum/sab-rl-metrics) (rl-xg) | The most careful independent work found. Strictly causal possession, pre-shot xG, goal-probability and win-probability models, split by game. Measured on 135 EWC 2026 pro replays: pre-shot xG AUC 0.763 to 0.773. It documents four silent carball bugs. Its finding that sustained-pressure and possession features **did not** improve short-horizon goal probability (5 s skill 0.140 vs 0.142) is directly relevant. | No (training scripts only) | **None stated** | Read its ARCHITECTURE.md and its bug list. Do not copy code without a licence. |
| 3 | [RLGym/rlgym-tools](https://github.com/RLGym/rlgym-tools) | Replay to RLGym `GameState` conversion, **action inference from replays** (`pick_action.py`), training-pack parsing, reward functions | No | Apache-2.0 | Use for imitation-learning data prep if Replay Lab ever trains a policy. |
| 4 | [Rolv-Arild/rl-high-level-dataset](https://github.com/Rolv-Arild/rl-high-level-dataset) | Curation code (anomaly filters, bot detection, player encounters). Data on Kaggle; a parsed copy in rlgym-tools format is on [Hugging Face](https://huggingface.co/datasets/Rolv-Arild/hlrlrd-parsed) at **445 GB** with a smaller `smol` config | Data only | Not stated on the HF page | The training corpus for any model we build. Check terms before use. |
| 5 | [ZealanL/RocketSim](https://github.com/ZealanL/RocketSim) | Fast C++ physics simulator, Python bindings | n/a | MIT | Only for short, physically bounded what-if checks. Not cloned this session. |
| 6 | [projectsignal-team/signal-neural-index](https://github.com/projectsignal-team/signal-neural-index) | Code for xG (XGBoost), an action-conditioned Deep Sets "OnBDA" model and a trajectory "OffBDA" model | Shipped `.pt` files are **smoke-test artifacts** trained on 4 to 5 replays. The OnBDA training gradient norm is 1.3e-20, so it did not learn | None stated | Interesting design, no usable model. Reject as a dependency. |
| 7 | [treygoff24/rlcoach](https://github.com/treygoff24/rlcoach) | Large local analysis app with 14 rule-based analysers. Its xG is **hand-tuned constants** (`base_xg_ground = 0.12`, and so on), not trained | No | None found | A competitor's feature list, not intelligence to reuse. |

Also found: [SaltieRL/ReplayModels](https://github.com/SaltieRL/ReplayModels) (older ML on carball output), [Rolv-Arild/replay-pretraining](https://github.com/Rolv-Arild/replay-pretraining) (inverse-dynamics action labels, cited in the earlier report), and [owensingh38/rocket_league_neural_index](https://github.com/owensingh38/rocket_league_neural_index), a transformer next-goal model whose README overlaps signal-neural-index. I could not open it this session (rate limit).

## What this changes

- **A strong value model already exists and is free.** The open questions are calibration on our data, behaviour outside doubles, and how to use it. They are not whether one can be trained.
- **Nobody has public trained weights for a human decision policy** at high rank, as far as I found. That is the real gap, and the one with the most coaching value.
- **Licences are missing on three of the most relevant repos.** Treat them as reading material until the owners add one.

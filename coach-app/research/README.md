# coach-app/research

Experimental tactical-intelligence prototypes. **Not imported by the app**, not exposed by any route, and safe to delete.

| File | Purpose |
|---|---|
| [REPORT.md](REPORT.md) | Measured results, ranked architectures, recommendations |
| [SURVEY.md](SURVEY.md) | What public Rocket League ML projects actually ship |
| `tactical_intel/frames.py` | Replay to canonical arrays via subtr-actor; dedupe by file hash; reads the built-in threat model |
| `tactical_intel/features.py` | Team-perspective causal features; next-goal labels with censoring |
| `tactical_intel/value_model.py` | Prototype 1: state-value comparison, grouped by match |
| `tactical_intel/decisions.py` | Decision points for "first defender facing control", pre-decision and retrospective fields apart |
| `tactical_intel/retrieval.py` | Prototype 2: comparable-decision retrieval, three representations, rule and momentum baselines |
| `tactical_intel/contract.py` | `TacticalAssessment` schema and adapters to the PR #16 blind evaluator |
| `tactical_intel/profile.py` | Empirical-Bayes player profiles for small samples |
| `tactical_intel/run.py` | One command that runs everything and writes `results/` |
| `results/` | Outputs from the run described in REPORT.md |
| `tests/` | 23 tests; synthetic data checks code paths only |

Rules this module keeps: nothing after `t0` reaches a feature, situation or choice label; folds and bootstraps are
grouped by match; duplicate replays are removed by hash; every skipped replay is listed with a reason; per-moment
verdicts abstain.

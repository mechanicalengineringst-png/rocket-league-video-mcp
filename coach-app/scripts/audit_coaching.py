"""Real-replay audit for checkpoint 3: tactical verdicts on the kinematic engine, truncation
invariance, reconciliation agreement, and first-defender readings by observed choice.

Usage (from coach-app/): python scripts/audit_coaching.py PAYLOAD_CACHE_DIR OUT.json
"""
from __future__ import annotations

import glob
import json
import pickle
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app.choices import classify_choice, find_defender_candidates  # noqa: E402
from coach_app.coaching_view import reconcile  # noqa: E402
from coach_app.decision_cases import extract_all_decision_cases  # noqa: E402
from coach_app.decision_evaluation import evaluate_decision_case_heuristics  # noqa: E402
from coach_app.defender_decisions import assess_defender  # noqa: E402
from coach_app.strategic_state import build_state  # noqa: E402
from coach_app.tactical_analysis import analyze_case  # noqa: E402


def main(cache: Path, out: Path) -> dict:
    random.seed(0)
    verdicts, pairs, shown, trunc = Counter(), Counter(), Counter(), Counter()
    defender, defender_shown = Counter(), Counter()
    for f in sorted(glob.glob(str(cache / "*.pkl"))):
        d = pickle.loads(Path(f).read_bytes())
        for c in extract_all_decision_cases(d):
            fnd = analyze_case(c, d)
            verdicts[f"{c.situation_type}|{fnd.verdict}"] += 1
            rec = reconcile(fnd, evaluate_decision_case_heuristics(c))
            pairs[f"{c.situation_type}|rule={rec['baselines']['rule_v1']['stance']}|reading={rec['primary']['stance']}"] += 1
            shown[f"{c.situation_type}|{rec['agreement']}|{rec['display']['stance']}"] += 1
            if random.random() < 0.25:
                cut = dict(d, frames=[fr for fr in d["frames"] if fr["t"] <= c.t0])
                trunc["checked"] += 1
                trunc["identical"] += analyze_case(c, cut).to_dict() == fnd.to_dict()
        for cand in find_defender_candidates(d):
            st = build_state(d, cand.t0, cand.player_id)
            lab = classify_choice(d, cand.t0, cand.player_id)
            fnd = assess_defender(st, lab, "x")
            defender[f"{lab.choice}|{fnd.verdict}"] += 1
            defender_shown[reconcile(fnd, None)["display"]["stance"]] += 1
            cut = dict(d, frames=[fr for fr in d["frames"] if fr["t"] <= cand.t0])
            trunc["defender_checked"] += 1
            trunc["defender_identical"] += assess_defender(build_state(cut, cand.t0, cand.player_id), lab, "x").to_dict() == fnd.to_dict()
    report = {"case_verdicts": dict(sorted(verdicts.items())), "rule_vs_reading_stance": dict(sorted(pairs.items())),
              "displayed": dict(sorted(shown.items())), "defender_choice_by_verdict": dict(sorted(defender.items())),
              "defender_displayed": dict(defender_shown), "truncation": dict(trunc)}
    out.write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]), Path(sys.argv[2])), indent=1))

"""Export a clean, anonymized 40-60 case evaluation cohort compatible with ChatGPT PR #16."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add coach-app root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import subtr_actor

from coach_app.subtr_replays import parse_subtr_replay
from coach_app.decision_cases import extract_all_decision_cases
from coach_app.decision_evaluation import evaluate_decision_case_heuristics
from tests.test_decision_cases_real_replay import get_replay_dir


def export_cohort():
    replay_dir = get_replay_dir()
    replay_path = replay_dir / "23A661D44DBC5964B0718DBC5F956A33.replay"
    if not replay_path.exists():
        print(f"Fixture not found at {replay_path}")
        return

    # Parse replay
    normalized_replay = parse_subtr_replay(replay_path)
    all_cases = extract_all_decision_cases(normalized_replay)

    # Anonymize player mappings
    player_anon_map = {}
    for i, p in enumerate(normalized_replay["players"], 1):
        team = p["team"]
        anon_label = f"player_{team}_{i}"
        player_anon_map[p["id"]] = anon_label
        if p.get("name"):
            player_anon_map[p["name"]] = anon_label

    cases_out = []
    predictions_out = []

    # Select 50 representative cases across all 3 situation types
    # Group by situation type
    by_type = {}
    for c in all_cases:
        by_type.setdefault(c.situation_type, []).append(c)

    selected = []
    # Take up to 16 kickoffs, 20 challenges, 14 last_man
    for sit, limit in [("kickoff_support", 16), ("first_man_challenge", 20), ("last_man_defense", 14)]:
        cases_pool = by_type.get(sit, [])
        # Stride evenly across match
        if len(cases_pool) > limit:
            step = len(cases_pool) / limit
            cases_pool = [cases_pool[int(i * step)] for i in range(limit)]
        selected.extend(cases_pool)

    selected.sort(key=lambda c: c.t0)

    for i, c in enumerate(selected, 1):
        anon_case_id = f"eval-case-{i:03d}"
        
        # Build PR #16 compatible case dict
        pre_ev = []
        for e in c.pre_decision_evidence():
            # scrub any names
            claim = e.claim
            for orig, anon in player_anon_map.items():
                claim = claim.replace(orig, anon)
            pre_ev.append({
                "key": e.key,
                "claim": claim,
                "event_time_s": round(e.event_time_s, 3),
                "finalized_through_s": round(e.finalized_through_s, 3),
                "source": e.source,
                "source_quality": e.source_quality,
            })

        case_dict = {
            "case_id": anon_case_id,
            "replay_group": "competitive-2v2-fixture-a",
            "mode": "2v2",
            "situation_type": c.situation_type,
            "t0": round(c.t0, 3),
            "pre_decision_evidence": pre_ev,
        }
        cases_out.append(case_dict)

        # Build baseline heuristic prediction
        eval_res = evaluate_decision_case_heuristics(c)
        if eval_res:
            assessment = eval_res.get("assessment", "abstain")
            if assessment not in ("sound", "risk", "tradeoff", "abstain"):
                # Map to PR #16 accepted assessments
                if "risk" in assessment:
                    assessment = "risk"
                elif "hypothesis" in assessment or "tradeoff" in assessment:
                    assessment = "tradeoff"
                elif "sound" in assessment or "positioning" in assessment:
                    assessment = "sound"
                else:
                    assessment = "abstain"

            predictions_out.append({
                "case_id": anon_case_id,
                "system_id": "heuristic-baseline-v1",
                "assessment": assessment,
                "cited_evidence": eval_res.get("cited_evidence", []),
                "title": eval_res.get("title", ""),
                "advice": eval_res.get("advice", ""),
            })
        else:
            predictions_out.append({
                "case_id": anon_case_id,
                "system_id": "heuristic-baseline-v1",
                "assessment": "abstain",
                "cited_evidence": [],
                "title": "Uncertain Telemetry",
                "advice": "Insufficient telemetry to verify decision quality.",
            })

    out_dir = Path(__file__).parent
    cases_file = out_dir / "eval_cohort_50_cases.json"
    pred_file = out_dir / "eval_cohort_50_predictions.json"

    cases_file.write_text(json.dumps(cases_out, indent=2), encoding="utf-8")
    pred_file.write_text(json.dumps(predictions_out, indent=2), encoding="utf-8")
    print(f"Exported {len(cases_out)} cases to {cases_file} and {len(predictions_out)} predictions to {pred_file}")


if __name__ == "__main__":
    export_cohort()

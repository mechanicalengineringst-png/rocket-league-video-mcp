"""Export a clean, anonymized 50-case evaluation cohort across 3 distinct competitive matches.

Compatible with ChatGPT PR #16 blind evaluation schema.
Uses the physics-based commitment window detector to establish genuine pre-decision t0
and verified ball trajectory toward the goal mouth.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add coach-app root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from coach_app.subtr_replays import parse_subtr_replay
from coach_app.decision_cases import extract_all_decision_cases
from coach_app.decision_evaluation import evaluate_decision_case_heuristics
from tests.test_decision_cases_real_replay import get_replay_dir

TARGET_MATCHES = [
    ("422F278B4AD49635016485882B38DC10.replay", "competitive-2v2-match-01"),
    ("23A661D44DBC5964B0718DBC5F956A33.replay", "competitive-2v2-match-02"),
    ("48E14DCC41A24985B9C925884AA83BBE.replay", "competitive-2v2-match-03"),
]


def export_multi_match_cohort():
    replay_dir = get_replay_dir()

    cases_by_match = []
    cases_out = []
    predictions_out = []

    for match_filename, group_label in TARGET_MATCHES:
        replay_path = replay_dir / match_filename
        if not replay_path.exists():
            print(f"Match fixture missing at {replay_path}")
            continue

        rep = parse_subtr_replay(replay_path)
        cases = extract_all_decision_cases(rep)

        player_anon = {}
        for i, p in enumerate(rep.get("players", []), 1):
            team = p.get("team", "blue")
            anon_token = f"player_{team}_{i}"
            player_anon[p["id"]] = anon_token
            if p.get("name"):
                player_anon[p["name"]] = anon_token

        cases_by_match.append((group_label, cases, player_anon))

    # Balance 50 cases across the available matches
    total_matches = len(cases_by_match)
    if total_matches == 0:
        print("No matches available for export.")
        return

    per_match_quota = 50 // total_matches
    selected_cases = []

    for idx, (group_label, cases, player_anon) in enumerate(cases_by_match):
        quota = per_match_quota if idx < total_matches - 1 else (50 - len(selected_cases))
        by_type = {}
        for c in cases:
            by_type.setdefault(c.situation_type, []).append(c)

        match_selected = []
        # Target balanced slice per match
        for sit in ("kickoff_support", "first_man_challenge", "last_man_defense"):
            pool = by_type.get(sit, [])
            sub_quota = max(1, quota // 3)
            if len(pool) > sub_quota:
                step = len(pool) / sub_quota
                pool = [pool[int(i * step)] for i in range(sub_quota)]
            match_selected.extend(pool)

        # Trim or pad to exact match quota
        if len(match_selected) > quota:
            match_selected = match_selected[:quota]
        elif len(match_selected) < quota:
            remaining = [c for c in cases if c not in match_selected]
            match_selected.extend(remaining[:quota - len(match_selected)])

        for c in match_selected:
            selected_cases.append((group_label, c, player_anon))

    for i, (group_label, c, player_anon) in enumerate(selected_cases[:50], 1):
        anon_case_id = f"eval-case-{i:03d}"

        pre_ev = []
        for e in c.pre_decision_evidence():
            claim = e.claim
            for orig, anon in player_anon.items():
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
            "replay_group": group_label,
            "mode": "2v2",
            "situation_type": c.situation_type,
            "t0": round(c.t0, 3),
            "pre_decision_evidence": pre_ev,
        }
        cases_out.append(case_dict)

        # Baseline evaluation prediction
        eval_res = evaluate_decision_case_heuristics(c)
        if eval_res:
            assessment = eval_res.get("assessment", "abstain")
            if assessment not in ("sound", "risk", "tradeoff", "abstain"):
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
    print(f"Exported {len(cases_out)} multi-match cases across {len(cases_by_match)} matches.")


if __name__ == "__main__":
    export_multi_match_cohort()

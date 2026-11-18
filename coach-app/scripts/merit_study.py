"""Two-stage blind tactical-merit study: prepare -> (experts rate Stage A) -> lock -> reveal -> (Stage B) -> score.

  prepare CACHE_DIR PRIVATE_MANIFEST_DIR OUT_DIR [--per-stratum N] [--seed S]
      Builds episodes for every first-defender candidate, runs ActionRationaleV0, DecisionStateV1 and
      TacticalOptionsV0 on the Stage 1 packet, assigns a pre-registered stratum, and writes:
        stage_a_packets.json        (public: give to raters; clips end at t0)
        exporter_rows.json          (for the clip exporter: Stage A windows)
        PRIVATE_study.json          (sealed: system labels, strata, retrospective; never give to raters)
        stage_a_response_TEMPLATE.json, rationale_real_replay_summary.json
  lock    OUT_DIR STAGE_A_RESPONSES.json            -> OUT_DIR/stage_a_lock.json
  reveal  OUT_DIR STAGE_A_RESPONSES.json            -> OUT_DIR/stage_b_packets.json (needs the lock)
  score   OUT_DIR STAGE_A_RESPONSES.json [STAGE_B_RESPONSES.json] -> OUT_DIR/score.json

No expert labels are created by this script.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import pickle
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app import merit_study as ms  # noqa: E402
from coach_app.action_rationale import analyze_action_rationale  # noqa: E402
from coach_app.claim_verifier import verify_stage1_claims  # noqa: E402
from coach_app.decision_state_v1 import analyze_decision_state  # noqa: E402
from coach_app.episode_evidence import build_episode_evidence  # noqa: E402
from coach_app.episode_stage1 import build_stage1_episode_packet  # noqa: E402
from coach_app.tactical_options import analyze_tactical_options  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_decision_state_v1 import opponent_regained  # noqa: E402


def prepare(cache: Path, mdir: Path, out: Path, per_stratum: int, seed: str) -> dict:
    rows = {r["case_id"]: r for r in json.loads((mdir / "PRIVATE_candidate_manifest.json").read_text())}
    side = json.loads((mdir / "PRIVATE_candidate_provenance.json").read_text())
    files = {"match-" + hashlib.sha256(Path(f).stem.encode()).hexdigest()[:8]: f for f in glob.glob(str(cache / "*.pkl"))}
    loaded: dict = {}
    cases, stats = [], Counter()
    status_counts = {"supported": Counter(), "conditional": Counter(), "contested": Counter(), "refuted": Counter()}
    decisive, n_reasonable = Counter(), Counter()
    for k, s in enumerate(side):
        r = rows[s["case_id"]]
        d = loaded.setdefault(r["replay_group"], pickle.loads(Path(files[r["replay_group"]]).read_bytes()))
        t, pid = r["source_t0_s"], s["player_id"]
        times = [round(t - 8, 3), round(t - 4, 3), t]
        if times[0] - 1 < d["frames"][0]["t"]:
            continue
        ep = build_episode_evidence(d, pid, times, t - 9, t)
        packet = build_stage1_episode_packet(ep)
        rat = analyze_action_rationale(packet)
        stats["episodes"] += 1
        stats[f"judgment_{rat['judgment']}"] += 1
        node = next(n for n in packet["nodes"] if n["node_id"] == rat["node_id"])["packet"]
        stats["claims"] += len(rat["claims"])
        stats["claims_rejected"] += sum(x["status"] == "rejected" for x in verify_stage1_claims(node, rat["claims"])["results"])
        if k % 5 == 0:
            cut = dict(d, frames=[f for f in d["frames"] if f["t"] <= t], events=[e for e in d["events"] if e.get("t", 0) <= t])
            again = analyze_action_rationale(build_stage1_episode_packet(build_episode_evidence(cut, pid, times, t - 9, t)))
            stats["truncation_checked"] += 1
            stats["truncation_identical"] += again == rat
        if rat["judgment"] == "available":
            for a, v in rat["actions"].items():
                status_counts[v["status"]][a] += 1
            n_reasonable[len(rat["reasonable_choices"])] += 1
            for dd in rat["decisive_information"]:
                decisive[dd["condition"]] += 1
        retro = ep["retrospective"]["nodes"][rat["node_id"]]
        choice = retro["observed_action"]["label"]
        team = next(p["team"] for p in d["players"] if p["id"] == pid)
        cases.append({
            "case_id": s["case_id"], "replay_group": r["replay_group"], "team": team, "source_t0_s": t,
            "stratum": ms.assign_stratum(rat, choice),
            "systems": {"action_rationale_v0": ms.rationale_labels(rat),
                        "action_rationale_v0_evidence_only": ms.rationale_evidence_only_labels(rat),
                        "decision_state_v1": ms.decision_state_v1_labels(analyze_decision_state(packet)),
                        "tactical_options_v0": ms.tactical_options_v0_labels(analyze_tactical_options(packet))},
            "rationale_summary": ms.summarise_rationale(rat),
            "retrospective": {"observed_action": choice, "outcome": {"opponents_regained": opponent_regained(d, t, pid)}},
        })
    study = ms.prepare_study(cases, seed=seed, per_stratum=per_stratum)
    out.mkdir(parents=True, exist_ok=True)
    (out / "stage_a_packets.json").write_text(json.dumps(study["stage_a_packets"], indent=1))
    (out / "exporter_rows.json").write_text(json.dumps(study["exporter_rows"], indent=1))
    (out / "PRIVATE_study.json").write_text(json.dumps(study, indent=1))
    template = [{"review_id": study["stage_a_packets"][0]["review_id"], "rater_id": "YOUR-ID",
                 "ratings": {a: "good|acceptable|poor|cannot_judge" for a in ms.ACTIONS},
                 "confidence": "low|medium|high", "preferred": [], "other_action": "", "missing_info": ""}]
    (out / "stage_a_response_TEMPLATE.json").write_text(json.dumps(template, indent=1))
    summary = {**stats, "candidate_cases": len(cases), "strata_available": dict(Counter(c["stratum"] for c in cases)),
               "strata_sampled": study["strata_counts"],
               "action_status_counts": {k: dict(v) for k, v in status_counts.items()},
               "reasonable_choices_per_judged_episode": dict(sorted(n_reasonable.items())),
               "decisive_conditions": dict(decisive.most_common())}
    (out / "rationale_real_replay_summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("cache", type=Path)
    p.add_argument("manifest_dir", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--per-stratum", type=int, default=6)
    p.add_argument("--seed", default="merit-pilot-1")
    for name in ("lock", "reveal"):
        q = sub.add_parser(name)
        q.add_argument("out", type=Path)
        q.add_argument("stage_a", type=Path)
    q = sub.add_parser("score")
    q.add_argument("out", type=Path)
    q.add_argument("stage_a", type=Path)
    q.add_argument("stage_b", type=Path, nargs="?")
    a = ap.parse_args()
    if a.cmd == "prepare":
        print(json.dumps(prepare(a.cache, a.manifest_dir, a.out, a.per_stratum, a.seed), indent=1))
        return
    study = json.loads((a.out / "PRIVATE_study.json").read_text())
    resp = json.loads(a.stage_a.read_text())
    if a.cmd == "lock":
        lock = ms.lock_stage_a(resp, study["stage_a_packets"])
        (a.out / "stage_a_lock.json").write_text(json.dumps(lock, indent=1))
        print(json.dumps(lock, indent=1))
    elif a.cmd == "reveal":
        lock = json.loads((a.out / "stage_a_lock.json").read_text())
        packets = ms.build_stage_b(study, resp, lock)
        (a.out / "stage_b_packets.json").write_text(json.dumps(packets, indent=1))
        print(f"{len(packets)} Stage B packets written")
    else:
        stage_b = json.loads(a.stage_b.read_text()) if a.stage_b else None
        if stage_b:
            ms.validate_stage_b(stage_b, json.loads((a.out / "stage_b_packets.json").read_text()))
        rep = ms.score(study, resp, stage_b)
        (a.out / "score.json").write_text(json.dumps(rep, indent=1))
        print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()

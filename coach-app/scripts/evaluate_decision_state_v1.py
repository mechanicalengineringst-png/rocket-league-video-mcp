"""Real-replay evaluation of TacticalDecisionStateV1 against TacticalOptionsV0 (Round 10).

Episodes: nodes at t-8, t-4, t around each first-defender candidate t (fixed offsets, not chosen tactically).
The analysis reads only the Stage 1 packet. Retrospective data (observed action, later touches, goals) is
read from the full replay ONLY to score the analysis after the fact:

- ball-state check: which team touched the ball next, per V1 ball state;
- consequence check: among players who actually challenged, how often the opponents strung two touches
  together before the defending team touched again, or scored, within 4 s ("opponent regained"), per V1
  challenge stance. This is a crude danger proxy with confounders (execution, later decisions), not a
  measure of decision quality;
- permissiveness: supported choices per episode, V1 vs V0.

Usage (from coach-app/): python scripts/evaluate_decision_state_v1.py CACHE_DIR PRIVATE_MANIFEST_DIR OUT.json
"""
from __future__ import annotations

import glob
import hashlib
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app.claim_verifier import verify_stage1_claims  # noqa: E402
from coach_app.decision_state_v1 import analyze_decision_state  # noqa: E402
from coach_app.episode_evidence import build_episode_evidence  # noqa: E402
from coach_app.episode_stage1 import build_stage1_episode_packet  # noqa: E402
from coach_app.tactical_options import analyze_tactical_options  # noqa: E402


def opponent_regained(d: dict, t0: float, pid: str, window: float = 4.0) -> bool:
    team = {p["id"]: p["team"] for p in d["players"]}
    mine = team[pid]
    evs = sorted(((e["t"], i, e) for i, e in enumerate(d["events"]) if e.get("type") in ("touch", "goal_context") and t0 < e["t"] <= t0 + window), key=lambda x: (x[0], x[1]))
    run = 0
    for _, _, e in evs:
        if e["type"] == "goal_context":
            if team.get(e.get("scorerId")) not in (None, mine):
                return True
            continue
        if team.get(e.get("playerId")) == mine:
            run = 0
        else:
            run += 1
            if run >= 2:
                return True
    return False


def rate(c: Counter) -> dict:
    n = c["n"]
    return {"n": n, "hits": c["hit"], "rate": round(c["hit"] / n, 3) if n else None}


def main(cache: Path, mdir: Path, out: Path) -> dict:
    rows = {r["case_id"]: r for r in json.loads((mdir / "PRIVATE_candidate_manifest.json").read_text())}
    side = json.loads((mdir / "PRIVATE_candidate_provenance.json").read_text())
    files = {"match-" + hashlib.sha256(Path(f).stem.encode()).hexdigest()[:8]: f for f in glob.glob(str(cache / "*.pkl"))}
    loaded: dict = {}
    c = Counter()
    profile, ball_state, stance_v1 = Counter(), Counter(), defaultdict(Counter)
    next_team = defaultdict(Counter)
    regain_by_stance = defaultdict(Counter)
    regain_by_v0 = defaultdict(Counter)
    delay_regain = defaultdict(Counter)
    supported_v1, supported_v0, robust_v1 = Counter(), Counter(), Counter()
    for k, s in enumerate(side):
        r = rows[s["case_id"]]
        d = loaded.setdefault(r["replay_group"], pickle.loads(Path(files[r["replay_group"]]).read_bytes()))
        t, pid = r["source_t0_s"], s["player_id"]
        times = [round(t - 8, 3), round(t - 4, 3), t]
        if times[0] - 1 < d["frames"][0]["t"]:
            continue
        ep = build_episode_evidence(d, pid, times, t - 9, t)
        packet = build_stage1_episode_packet(ep)
        v1 = analyze_decision_state(packet)
        v0 = analyze_tactical_options(packet)
        c["episodes"] += 1
        c[f"status_{v1['status']}"] += 1
        node = next(n for n in packet["nodes"] if n["node_id"] == v1["node_id"])["packet"]
        c["claims"] += len(v1["claims"])
        c["claims_rejected"] += sum(x["status"] == "rejected" for x in verify_stage1_claims(node, v1["claims"])["results"])
        if k % 5 == 0:
            cut = dict(d, frames=[f for f in d["frames"] if f["t"] <= t], events=[e for e in d["events"] if e.get("t", 0) <= t])
            again = analyze_decision_state(build_stage1_episode_packet(build_episode_evidence(cut, pid, times, t - 9, t)))
            c["truncation_checked"] += 1
            c["truncation_identical"] += again == v1
        if v1["status"] == "abstain":
            continue
        sc = v1["scenario"]
        profile[sc["profile"]] += 1
        ball_state[sc["ball_state"]] += 1
        for a in v1["actions"]:
            stance_v1[a["action"]][a["stance"]] += 1
        supported_v1[len(v1["supported_choices"])] += 1
        robust_v1[len(v1["robust_choices"])] += 1
        supported_v0[len(v0["defensible_options"])] += 1
        # ---- evaluation only: retrospective ----
        retro = ep["retrospective"]["nodes"][v1["node_id"]]
        nt = retro["next_touch"]["slot"]
        if nt:
            next_team[sc["ball_state"]]["n"] += 1
            next_team[sc["ball_state"]]["hit"] += nt in ("focus", "teammate")
        chose = retro["observed_action"]["label"]
        regained = opponent_regained(d, t, pid)
        if chose == "challenge":
            st = next(a["stance"] for a in v1["actions"] if a["action"] == "immediate_challenge")
            regain_by_stance[st]["n"] += 1
            regain_by_stance[st]["hit"] += regained
            st0 = next(o["strategic_stance"] for o in v0["options"] if o["action"] == "immediate_challenge")
            regain_by_v0[st0]["n"] += 1
            regain_by_v0[st0]["hit"] += regained
        elif chose in ("shadow", "retreat"):
            delay_regain[sc["profile"]]["n"] += 1
            delay_regain[sc["profile"]]["hit"] += regained
    report = {
        **c,
        "profile": dict(profile), "ball_state": dict(ball_state),
        "stance_by_action_v1": {a: dict(v) for a, v in stance_v1.items()},
        "supported_choices_per_episode_v1": dict(sorted(supported_v1.items())),
        "robust_choices_per_episode_v1": dict(sorted(robust_v1.items())),
        "defensible_options_per_episode_v0": dict(sorted(supported_v0.items())),
        "eval_next_touch_own_team_by_ball_state": {k: rate(v) for k, v in next_team.items()},
        "eval_opponent_regained_after_actual_challenge_by_v1_stance": {k: rate(v) for k, v in regain_by_stance.items()},
        "eval_opponent_regained_after_actual_challenge_by_v0_stance": {k: rate(v) for k, v in regain_by_v0.items()},
        "eval_opponent_regained_after_actual_delay_by_v1_profile": {k: rate(v) for k, v in delay_regain.items()},
        "caveat": "Public unknown-rank replays; retrospective fields used only for scoring; the regain proxy "
                  "mixes decision, execution and later play and is not a measure of decision quality.",
    }
    out.write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])), indent=1))

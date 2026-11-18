"""Real-replay demonstration of TacticalOptionsV0.

For each first-defender candidate t in a private manifest: episode with nodes t-8, t-4, t (window t-9..t),
-> Stage1EpisodePacketV0 -> TacticalOptionsV0 at the primary node. Reports option stances, abstentions,
claim-verifier results, future-deletion invariance (every 5th episode) and a held-out check of the
contest-band representation: how often the focus player made the next touch, per band. The next touch
comes from the episode's retrospective section and is used ONLY for this evaluation, never as input.

Usage (from coach-app/): python scripts/demo_tactical_options.py CACHE_DIR PRIVATE_MANIFEST_DIR OUT.json [EXAMPLE.json]
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
from coach_app.episode_evidence import build_episode_evidence  # noqa: E402
from coach_app.episode_stage1 import build_stage1_episode_packet  # noqa: E402
from coach_app.tactical_options import analyze_tactical_options  # noqa: E402


def main(cache: Path, mdir: Path, out: Path, example: Path | None) -> dict:
    rows = {r["case_id"]: r for r in json.loads((mdir / "PRIVATE_candidate_manifest.json").read_text())}
    side = json.loads((mdir / "PRIVATE_candidate_provenance.json").read_text())
    files = {"match-" + hashlib.sha256(Path(f).stem.encode()).hexdigest()[:8]: f for f in glob.glob(str(cache / "*.pkl"))}
    loaded: dict = {}
    c, stance, abstain, ndef, band_eval = Counter(), defaultdict(Counter), Counter(), Counter(), defaultdict(Counter)
    shown = None
    for k, s in enumerate(side):
        r = rows[s["case_id"]]
        d = loaded.setdefault(r["replay_group"], pickle.loads(Path(files[r["replay_group"]]).read_bytes()))
        t = r["source_t0_s"]
        times = [round(t - 8, 3), round(t - 4, 3), t]
        if times[0] - 1 < d["frames"][0]["t"]:
            continue
        ep = build_episode_evidence(d, s["player_id"], times, t - 9, t)
        packet = build_stage1_episode_packet(ep)
        res = analyze_tactical_options(packet)
        c["episodes"] += 1
        c[f"status_{res['status']}"] += 1
        for why in res["abstain_reasons"]:
            abstain[why] += 1
        for o in res["options"]:
            stance[o["action"]][o["strategic_stance"]] += 1
        ndef[len(res["defensible_options"])] += 1
        node = next(n for n in packet["nodes"] if n["node_id"] == res["node_id"])["packet"]
        rep = verify_stage1_claims(node, res["claims"])
        c["claims"] += len(res["claims"])
        c["claims_rejected"] += sum(x["status"] == "rejected" for x in rep["results"])
        if k % 5 == 0:
            cut = dict(d, frames=[f for f in d["frames"] if f["t"] <= t], events=[e for e in d["events"] if e.get("t", 0) <= t])
            again = analyze_tactical_options(build_stage1_episode_packet(build_episode_evidence(cut, s["player_id"], times, t - 9, t)))
            c["truncation_checked"] += 1
            c["truncation_identical"] += again == res
        band = res["state"].get("contest_band")
        nxt = ep["retrospective"]["nodes"][res["node_id"]]["next_touch"]["slot"]     # evaluation only
        if band and nxt:
            band_eval[band]["focus_touched_next"] += nxt == "focus"
            band_eval[band]["n"] += 1
        if shown is None and res["status"] == "ok" and res["multiple_defensible"] and res["earlier_contributors"]:
            shown = res
    report = {**c, "abstain_reasons": dict(abstain),
              "stance_by_action": {a: dict(v) for a, v in stance.items()},
              "defensible_options_per_episode": dict(sorted(ndef.items())),
              "held_out_contest_band_check": {b: {**v, "rate": round(v["focus_touched_next"] / v["n"], 3)}
                                              for b, v in band_eval.items()}}
    out.write_text(json.dumps(report, indent=1))
    if example and shown:
        example.write_text(json.dumps(shown, indent=1))
    return report


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]),
                          Path(sys.argv[4]) if len(sys.argv) > 4 else None), indent=1))

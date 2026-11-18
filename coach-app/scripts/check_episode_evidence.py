"""Real-replay check for EpisodeEvidenceV0: for each first-defender candidate t, build an episode with nodes at
t-8, t-4 and t (window t-9..t), delete every frame and event after t, and confirm stage1_view is unchanged,
ids are unique and the record is valid JSON (no NaN/inf). Nodes are fixed offsets, not tactically chosen.

Usage (from coach-app/): python scripts/check_episode_evidence.py CACHE_DIR PRIVATE_MANIFEST_DIR
"""
from __future__ import annotations

import glob
import hashlib
import json
import pickle
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app.episode_evidence import all_ids, build_episode_evidence, stage1_view  # noqa: E402


def main(cache: Path, mdir: Path) -> dict:
    rows = {r["case_id"]: r for r in json.loads((mdir / "PRIVATE_candidate_manifest.json").read_text())}
    side = json.loads((mdir / "PRIVATE_candidate_provenance.json").read_text())
    files = {"match-" + hashlib.sha256(Path(f).stem.encode()).hexdigest()[:8]: f for f in glob.glob(str(cache / "*.pkl"))}
    loaded: dict = {}
    c, status = Counter(), Counter()
    for s in side:
        r = rows[s["case_id"]]
        d = loaded.setdefault(r["replay_group"], pickle.loads(Path(files[r["replay_group"]]).read_bytes()))
        t = r["source_t0_s"]
        times = [round(t - 8, 3), round(t - 4, 3), t]
        if times[0] - 1 < d["frames"][0]["t"]:
            continue
        ep = build_episode_evidence(d, s["player_id"], times, t - 9, t)
        cut = dict(d, frames=[f for f in d["frames"] if f["t"] <= t], events=[e for e in d["events"] if e.get("t", 0) <= t])
        c["episodes"] += 1
        c["stage1_identical_after_deleting_future"] += stage1_view(build_episode_evidence(cut, s["player_id"], times, t - 9, t)) == stage1_view(ep)
        ids = all_ids(ep)
        c["unique_ids"] += len(ids) == len(set(ids))
        json.dumps(ep, allow_nan=False)
        c["valid_json"] += 1
        c["hypothesis_prompts"] += len(ep["possible_earlier_contributors"])
        c["change_items"] += len(ep["changes"])
        c["change_unknowns"] += sum(u["id"].startswith("UD.") for u in ep["unknowns"])
        status[ep["status"]] += 1
    return {**c, "status": dict(status)}


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]), Path(sys.argv[2])), indent=1))

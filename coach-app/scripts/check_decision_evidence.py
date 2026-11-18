"""Real-replay check for DecisionEvidenceV0: build a record for every first-defender candidate in a
private manifest, delete every frame and event after t0, and confirm the pre-decision part is unchanged.

Usage (from coach-app/): python scripts/check_decision_evidence.py CACHE_DIR PRIVATE_MANIFEST_DIR [EXAMPLE_OUT.json]
"""
from __future__ import annotations

import glob
import hashlib
import json
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app.decision_evidence import build_decision_evidence  # noqa: E402

PRE = ("evidence", "unknowns", "context", "frame_time_s", "status")


def main(cache: Path, mdir: Path, example: Path | None) -> dict:
    rows = {r["case_id"]: r for r in json.loads((mdir / "PRIVATE_candidate_manifest.json").read_text())}
    side = json.loads((mdir / "PRIVATE_candidate_provenance.json").read_text())
    payloads = {"match-" + hashlib.sha256(Path(f).stem.encode()).hexdigest()[:8]: f for f in glob.glob(str(cache / "*.pkl"))}
    loaded: dict = {}
    stats, unknown_kinds, prov = Counter(), Counter(), Counter()
    t = time.time()
    chosen = None
    for s in side:
        row = rows[s["case_id"]]
        if row["replay_group"] not in loaded:
            loaded[row["replay_group"]] = pickle.loads(Path(payloads[row["replay_group"]]).read_bytes())
        d, t0, pid = loaded[row["replay_group"]], row["source_t0_s"], s["player_id"]
        sel = {"rule": s["eligibility_rule"], "values": s["eligibility_values"]}
        full = build_decision_evidence(d, t0, pid, selection=sel)
        cut = dict(d, frames=[f for f in d["frames"] if f["t"] <= t0], events=[e for e in d["events"] if e.get("t", 0) <= t0])
        trunc = build_decision_evidence(cut, t0, pid, selection=sel)
        stats["records"] += 1
        stats["pre_decision_identical_after_deleting_future"] += all(full[k] == trunc[k] for k in PRE)
        for u in full["unknowns"]:
            unknown_kinds[u["id"]] += 1
        for e in full["evidence"]:
            if "stale_possible" in e["provenance"] and e["id"].endswith(".position"):
                prov["stale_possible_positions"] += 1
            if e["id"].endswith(".position"):
                prov["positions"] += 1
        if chosen is None and full["retrospective"]["observed_action"]["label"] == "challenge" and not full["unknowns"]:
            chosen = full
    report = {"records": stats["records"], "pre_decision_identical_after_deleting_future": stats["pre_decision_identical_after_deleting_future"],
              "unknowns_by_kind": dict(unknown_kinds), **prov, "runtime_s": round(time.time() - t, 1)}
    if example and chosen:
        example.write_text(json.dumps(chosen, indent=1, default=str))
    return report


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) > 3 else None), indent=1))

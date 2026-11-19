"""Run CoachingReviewV1 over a cached cohort: moments per report, categories, abstention, size, runtime, repetition.

Usage (from coach-app/): python scripts/evaluate_round15_review.py CACHE_DIR OUT.json
"""
from __future__ import annotations

import glob
import json
import pickle
import re
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach_app.coaching_review import build_review  # noqa: E402

NUM = re.compile(r"\d+(?:\.\d+)?")


def one(path: str, pi: int) -> dict:
    d = pickle.loads(Path(path).read_bytes())
    pid = d["players"][pi]["id"]
    t = time.time()
    r = build_review(d, pid)
    blob = json.dumps(r)
    return {"seconds": round(time.time() - t, 1), "bytes": len(blob), "moments": len(r["moments"]),
            "categories": [m["category"] for m in r["moments"]], "classes": [m["situation_class"] for m in r["moments"]],
            "assessment_templates": [NUM.sub("#", m["assessment"]) for m in r["moments"]],
            "analysed": r["coverage"]["situations_analysed"], "abstained": r["coverage"]["abstained"],
            "leak": any(p["id"] in blob or (len(p.get("name") or "") > 3 and p["name"] in blob) for p in d["players"])}


def main(cache: Path, out: Path):
    files = sorted(glob.glob(str(cache / "*.pkl")))
    jobs = [(f, i) for f in files for i in range(4)]
    with ProcessPoolExecutor(2) as ex:
        rows = list(ex.map(one, *zip(*jobs)))
    tpl = Counter(t for r in rows for t in r["assessment_templates"])
    res = {"player_reports": len(rows), "replays": len(files), "note": "public 2v2 replays, unknown rank; no expert labels",
           "moments_per_report": dict(Counter(r["moments"] for r in rows)),
           "categories": dict(Counter(c for r in rows for c in r["categories"])),
           "situation_classes": dict(Counter(c for r in rows for c in r["classes"])),
           "abstention_share": round(sum(r["abstained"] for r in rows) / max(1, sum(r["analysed"] for r in rows)), 3),
           "reports_with_zero_moments": sum(r["moments"] == 0 for r in rows),
           "max_bytes": max(r["bytes"] for r in rows), "mean_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 1),
           "max_seconds": max(r["seconds"] for r in rows),
           "assessment_templates_total": sum(tpl.values()), "assessment_templates_distinct": len(tpl),
           "most_repeated_assessment_template_across_cohort": tpl.most_common(1)[0][1] if tpl else 0,
           "duplicate_templates_within_a_report": sum(len(r["assessment_templates"]) - len(set(r["assessment_templates"])) for r in rows),
           "privacy_leaks": sum(r["leak"] for r in rows)}
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))

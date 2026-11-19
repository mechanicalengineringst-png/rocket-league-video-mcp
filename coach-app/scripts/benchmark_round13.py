"""Round 13 benchmark: CoachingReportV2 vs CoachingReportV1 (Round 12) on the cached public cohort.

Per player-match: verdict distributions, how often V2's r13 ledger changed a status, turning-point
balance (gains vs losses), how stable the leave-one-player-out attribution is when the window shifts
by 0.5 s, which decision classes turning points link to, privacy, runtime, and Stage A invariance of
V2 decision findings when the replay is cut at t0.
Usage (from coach-app/): python scripts/benchmark_round13.py CACHE_DIR OUT.json
"""
from __future__ import annotations

import glob
import json
import pickle
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach_app.coach_report import build_coaching_report, prefix  # noqa: E402
from coach_app.coach_report_v2 import build_coaching_report_v2  # noqa: E402
from coach_app.control_timeline import attribute  # noqa: E402
from coach_app.value_model import FutureControlModel  # noqa: E402


def one(path: str, pi: int) -> dict:
    d = pickle.loads(Path(path).read_bytes())
    pid = d["players"][pi]["id"]
    team = d["players"][pi]["team"]
    t = time.time()
    v1 = build_coaching_report(d, pid, max_findings=6)
    t1 = time.time() - t
    t = time.time()
    v2 = build_coaching_report_v2(d, pid, max_findings=6)
    t2 = time.time() - t
    blob = json.dumps(v2, default=str)
    m = v2["matches"][0]
    model = FutureControlModel.load()
    stab = []
    for tp in m["turning_points"]:
        a = attribute(d, team, tp["t_start"] + 0.5, tp["t_end"] + 0.5, model)
        if a and pid in a.get("player_contribution", {}):
            stab.append((tp["your_movement_effect"], a["player_contribution"][pid]))
    inv = []
    for f in m["decision_findings"][:2]:
        full = {k: v for k, v in f.items() if k not in ("retrospective", "situation")}
        cut = build_coaching_report_v2(prefix(d, f["t0"] + 0.01), pid, max_findings=6)
        g = next((x for x in cut["matches"][0]["decision_findings"] if abs(x["t0"] - f["t0"]) < 1e-6), None)
        inv.append(None if g is None else full == {k: v for k, v in g.items() if k not in ("retrospective", "situation")})
    return {
        "v1_verdicts": dict(Counter(x.get("retrospective", {}).get("assessment", {}).get("verdict") for x in v1["findings"])),
        "v2_verdicts": dict(Counter(x["retrospective"]["assessment"].get("verdict_v2") for x in m["decision_findings"])),
        "v1_classes": dict(Counter(x["situation"]["class"] for x in v1["findings"])),
        "v2_classes": dict(Counter(x["situation"]["class"] for x in m["decision_findings"])),
        "r13_adjustments": sum(len(x.get("ledger_adjustments", [])) for x in m["decision_findings"]),
        "turning_points": [{"direction": tp["direction"], "share": tp["your_share_of_attributed_change"],
                            "linked": (tp.get("decision_time_reading") or {}).get("class"),
                            "has_context": bool((tp.get("decision_time_reading") or {}).get("commitment_context"))}
                           for tp in m["turning_points"]],
        "attribution_shift_pairs": stab,
        "stage_a_prefix_identical": inv,
        "privacy_leak": any(p["id"] in blob or (len(p.get("name") or "") > 3 and p["name"] in blob) for p in d["players"]),
        "seconds": {"v1": round(t1, 1), "v2": round(t2, 1)},
        "habits_flagged": sum(h["standout"] is not None for h in v2["habit_profile"]["habits"]),
        "habits_would_flag_if_reliable": sum(h["standout_if_reliable"] is not None for h in v2["habit_profile"]["habits"]),
    }


def main(cache: Path, out: Path):
    files = sorted(glob.glob(str(cache / "*.pkl")))
    jobs = [(f, i) for f in files for i in range(4)]
    with ProcessPoolExecutor(2) as ex:
        rows = list(ex.map(one, *zip(*jobs)))
    agg = {"player_reports": len(rows)}
    for k in ("v1_verdicts", "v2_verdicts", "v1_classes", "v2_classes"):
        c = Counter()
        for r in rows:
            c.update(r[k])
        agg[k] = dict(c)
    tps = [t for r in rows for t in r["turning_points"]]
    agg["turning_points"] = {"n": len(tps), "gains": sum(t["direction"] == "gain" for t in tps),
                             "losses": sum(t["direction"] == "loss" for t in tps),
                             "median_your_share": round(float(np.median([t["share"] for t in tps])), 3) if tps else None,
                             "linked_class": dict(Counter(t["linked"] for t in tps)),
                             "aerial_links_with_context": sum(t["has_context"] for t in tps)}
    pairs = [p for r in rows for p in r["attribution_shift_pairs"]]
    if pairs:
        a, b = np.array(pairs).T
        agg["attribution_window_shift"] = {"n": len(pairs), "pearson": round(float(np.corrcoef(a, b)[0, 1]), 3),
                                           "same_sign_share": round(float(np.mean(np.sign(a) == np.sign(b))), 3)}
    inv = [x for r in rows for x in r["stage_a_prefix_identical"] if x is not None]
    agg["v2_stage_a_prefix_identical"] = f"{sum(inv)}/{len(inv)}"
    agg["r13_adjustments_in_selected_findings"] = sum(r["r13_adjustments"] for r in rows)
    agg["privacy_leaks"] = sum(r["privacy_leak"] for r in rows)
    agg["mean_seconds"] = {k: round(float(np.mean([r["seconds"][k] for r in rows])), 1) for k in ("v1", "v2")}
    agg["habits_flagged_single_match"] = sum(r["habits_flagged"] for r in rows)
    agg["habits_that_would_flag_without_reliability_gate"] = sum(r["habits_would_flag_if_reliable"] for r in rows)
    out.write_text(json.dumps(agg, indent=1))
    print(json.dumps(agg, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))

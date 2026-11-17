"""Run both prototypes on a folder of replays and write reproducible results.

    cd coach-app
    python -m research.tactical_intel.run --replays DIR --out research/results

Outputs (all deterministic for a fixed input set):
- ``value_model.json``: Prototype 1 metrics, by mode, with match-bootstrap intervals.
- ``failure_cases.json``: the built-in model's most confident misses and false alarms.
- ``retrieval.json``: Prototype 2 metrics for three representations and a rule baseline.
- ``decision_points.jsonl``: every extracted decision, pre-decision and retrospective parts apart.
- ``profiles.json``: shrunk per-player challenge rates, to show personal adaptation on tiny samples.
- ``blind_cases.json`` / ``blind_predictions.json``: inputs for PR #16's evaluator.
- ``inventory.json``: which replays were used, skipped or deduplicated, and why.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import contract, profile
from .decisions import extract_decisions
from .features import frame_table
from .frames import dedupe, load_match
from .retrieval import Retriever, evaluate_retrieval
from .value_model import run_value_experiment


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, np.integer):
        return int(o)
    return o


def _scrub(msg: str) -> str:
    """Decoder errors can quote player account IDs; keep the reason, drop the IDs."""
    return re.split(r"Expected:", msg)[0].strip()


def load_corpus(replay_dir: Path, cache: Path | None) -> tuple[list, dict]:
    inv = {"loaded": [], "failed": [], "duplicates": [], "excluded": []}
    matches = []
    for path in sorted(replay_dir.glob("*.replay")):
        try:
            m = load_match(path, cache)
        except Exception as e:  # report every skip; never drop silently
            inv["failed"].append({"source": path.name, "error": _scrub(str(e))[:160]})
            continue
        if min(m.team_sizes) == 0:
            inv["excluded"].append({"source": m.source, "reason": f"{m.mode}: a drill, not a match"})
            continue
        if m.notes:
            inv["excluded"].append({"source": m.source, "reason": "; ".join(m.notes)})
            continue
        matches.append(m)
    matches, dups = dedupe(matches)
    inv["duplicates"] = dups
    for m in matches:
        inv["loaded"].append({"source": m.source, "mode": m.mode, "frames": m.n_frames,
                              "live_fraction": round(float(m.live.mean()), 3), "goals": len(m.goals),
                              "builtin_threat_live_coverage": round(float(np.isfinite(m.builtin_threat[m.live]).mean()), 3)
                              if m.builtin_threat is not None else 0.0})
    return matches, inv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--replays", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--horizon", type=float, default=5.0)
    ap.add_argument("--boot", type=int, default=500)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    matches, inv = load_corpus(args.replays, args.cache)
    (args.out / "inventory.json").write_text(json.dumps(_jsonable(inv), indent=2))
    if len(matches) < 3:
        print(f"Only {len(matches)} usable matches; need at least 3 for grouped evaluation.", file=sys.stderr)
        return 2

    table = frame_table(matches, args.horizon)
    vr = run_value_experiment(table, n_boot=args.boot)
    vr.summary["horizon_s"] = args.horizon
    (args.out / "value_model.json").write_text(json.dumps(_jsonable(vr.summary), indent=2))
    (args.out / "failure_cases.json").write_text(json.dumps(_jsonable(vr.failures), indent=2))

    points = [p for m in matches for p in extract_decisions(m)]
    with open(args.out / "decision_points.jsonl", "w") as f:
        for p in points:
            f.write(json.dumps(_jsonable(p.to_dict())) + "\n")
    rr = {"all_modes": evaluate_retrieval(points, n_boot=args.boot)}
    p2 = [p for p in points if p.mode == "2v2"]
    if len({p.match_id for p in p2}) >= 3:
        rr["2v2_only"] = evaluate_retrieval(p2, n_boot=args.boot)
    (args.out / "retrieval.json").write_text(json.dumps(_jsonable(rr), indent=2))

    # Personal adaptation: challenge rate among readable choices, per anonymized player.
    tally = defaultdict(lambda: [0, 0])
    for p in points:
        if p.choice != "unclear":
            tally[p.focal_key][1] += 1
            tally[p.focal_key][0] += p.choice == "challenge"
    keys = sorted(tally)
    prior = profile.fit_prior(np.array([tally[k][0] for k in keys]), np.array([tally[k][1] for k in keys]))
    prof = {"trait": "challenge share when first defender facing control",
            "prior": {"mean": prior.mean, "strength": prior.strength},
            "players": sorted((dict(player=k, **profile.shrink(*tally[k], prior).__dict__) for k in keys),
                              key=lambda d: -d["trials"])}
    (args.out / "profiles.json").write_text(json.dumps(_jsonable(prof), indent=2))

    # Blind-evaluation export: every 2v2 decision, assessed with neighbours from other matches.
    cases, preds = [], []
    h2h = vr.summary.get("head_to_head", {}).get("systems", {}).get("builtin_raw", {})
    calib = {"value_model": "subtr-actor builtin threat v7", "evaluated_on": "2v2 replays in this run",
             "brier": h2h.get("brier"), "ece": h2h.get("ece"), "auc": h2h.get("auc")}
    groups = {m: f"anonymous-match-{i:02d}" for i, m in enumerate(sorted({p.match_id for p in p2}))}
    for mid, group in groups.items():
        train = [p for p in p2 if p.match_id != mid]   # same mode only: no 1v1/3v3 references
        test = [p for p in p2 if p.match_id == mid]
        if len(train) < 15 or not test:
            continue
        r = Retriever("tactical").fit(train)
        for q, idx in zip(test, r.query(test)):
            a = contract.assess(q, [train[j] for j in idx], calib)
            cid = f"{group}-{q.t0:07.2f}-t{q.team}"
            cases.append(contract.to_blind_case(q, cid, group))
            preds.append(contract.to_blind_prediction(a, cid))
    (args.out / "blind_cases.json").write_text(json.dumps(cases, indent=2))
    (args.out / "blind_predictions.json").write_text(json.dumps(preds, indent=2))
    print(f"matches={len(matches)} frames={len(table)} decisions={len(points)} blind_cases={len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

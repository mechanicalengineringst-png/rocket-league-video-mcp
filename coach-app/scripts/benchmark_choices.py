"""Real-replay checks for checkpoint 3: candidates, choice labels, representation value, manifest.

Usage (from coach-app/): python scripts/benchmark_choices.py PAYLOAD_CACHE_DIR OUT.json [MANIFEST_OUT_DIR]
PAYLOAD_CACHE_DIR holds pickled parse_subtr_replay payloads (see benchmark_reachability.py).
"""
from __future__ import annotations

import bisect
import glob
import hashlib
import json
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app.choices import build_commitment_manifest, classify_choice, find_defender_candidates  # noqa: E402
from coach_app.strategic_state import build_state, distance_margin  # noqa: E402


def auc(scores_labels):
    pos = [s for s, y in scores_labels if y]
    neg = [s for s, y in scores_labels if not y]
    if not pos or not neg:
        return None
    ranked = sorted(scores_labels, key=lambda x: x[0])
    r, i = {}, 0
    while i < len(ranked):
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        for k in range(i, j):
            r[k] = (i + j + 1) / 2
        i = j
    s_pos = sum(r[k] for k, (_, y) in enumerate(ranked) if y)
    return round((s_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)), 3)


def main(cache: Path, out: Path, manifest_dir: Path | None) -> dict:
    t_start = time.time()
    choices, agree, trunc = Counter(), Counter(), Counter()
    rep_rows = []
    manifest, sidecar = [], []
    for f in sorted(glob.glob(str(cache / "*.pkl"))):
        d = pickle.loads(Path(f).read_bytes())
        group = "match-" + hashlib.sha256(Path(f).stem.encode()).hexdigest()[:8]
        cands = find_defender_candidates(d)
        shadow_ev = [(e["t"], e["playerId"]) for e in d["events"] if e.get("type") == "shadow_defense"]
        for c in cands:
            lab = classify_choice(d, c.t0, c.player_id)
            choices[lab.choice] += 1
            dec = any(p == c.player_id and c.t0 - 0.5 <= t <= c.t0 + 1.5 for t, p in shadow_ev)
            agree[(lab.choice, dec)] += 1
            # truncation: delete every frame after t0 and re-decide eligibility
            cut = dict(d, frames=[fr for fr in d["frames"] if fr["t"] <= c.t0])
            again = [x for x in find_defender_candidates(cut, start=c.t0, end=c.t0) if x.player_id == c.player_id]
            trunc["checked"] += 1
            trunc["identical"] += bool(again) and again[0].eligibility == c.eligibility and again[0].state == c.state
        goals = [e["t"] for e in d["events"] if e.get("type") == "goal_context"]
        rows, side = build_commitment_manifest(group, d, cands, goals)
        manifest += rows
        sidecar += side
        # representation: which team touches next within 3 s, from the t0 state of a blue player
        frames, times = d["frames"], [fr["t"] for fr in d["frames"]]
        touches = sorted((e["t"], e["playerId"]) for e in d["events"] if e.get("type") == "touch")
        team_of = {p["id"]: p["team"] for p in d["players"]}
        blue = next(p for p, tm in team_of.items() if tm == "blue")
        t0 = times[0] + 2
        while t0 < times[-1] - 3:
            fr = frames[bisect.bisect_right(times, t0) - 1]
            nxt = next(((t, p) for t, p in touches if t0 < t <= t0 + 3), None)
            b = fr["ball"]
            if nxt and len(fr["cars"]) == 4 and not (b["x"] == 0 and b["y"] == 0):
                st = build_state(d, t0, blue)
                dm = distance_margin(d, t0, blue)
                if st and st.margin_s is not None and dm is not None:
                    rep_rows.append((st.margin_s, dm, team_of.get(nxt[1]) == "blue"))
            t0 += 1.0
    n_rep = len(rep_rows)
    report = {
        "runtime_s": round(time.time() - t_start, 1),
        "candidates": sum(choices.values()),
        "choice_labels": dict(choices),
        "decoder_shadow_defense_overlap": {f"{k[0]}|decoder_shadow={k[1]}": v for k, v in sorted(agree.items())},
        "truncation_check": dict(trunc),
        "next_touch_team_auc": {"rows": n_rep,
                                "time_margin_reachability": auc([(m, y) for m, _, y in rep_rows]),
                                "distance_margin_baseline": auc([(dm, y) for _, dm, y in rep_rows])},
        "manifest": {"rows": len(manifest), "by_detector_choice": dict(Counter(r["detector_choice"] for r in manifest)),
                     "matches": len({r["replay_group"] for r in manifest})},
    }
    out.write_text(json.dumps(report, indent=1))
    if manifest_dir:
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "PRIVATE_candidate_manifest.json").write_text(json.dumps(manifest, indent=1))
        (manifest_dir / "PRIVATE_candidate_provenance.json").write_text(json.dumps(sidecar, indent=1, default=str))
    return report


if __name__ == "__main__":
    r = main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) > 3 else None)
    print(json.dumps(r, indent=1))

"""Round 12 evaluation on the public cached cohort (unknown rank; NOT an expert benchmark).

For every replay and every player: CoachingReportV1 (new) and the Round 9-11 default path (old:
EpisodeCandidatesV0 + CoachLessonV0 + ActionRationaleV0). Measures what can be measured without human
labels: coverage, abstention, validation failures, stage separation (truncation and future-rewrite
invariance), outcome dependence of verdicts, specificity of takeaways, generic-advice phrases, privacy,
and the sensitivity of the ledger to every documented threshold. Writes an aggregate JSON (no names/IDs).

Usage (from coach-app/): python scripts/evaluate_round12.py CACHE_DIR OUT.json [--workers 2]
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import glob
import hashlib
import json
import pickle
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app import action_rationale as ar  # noqa: E402
from coach_app import decision_state_v1 as v1  # noqa: E402
from coach_app import situation_rationale as sr  # noqa: E402
from coach_app.action_rationale import analyze_action_rationale  # noqa: E402
from coach_app.coach_lesson import build_lesson_from_episode  # noqa: E402
from coach_app.coach_report import analyze_moment, build_coaching_report, coach_moment, prefix  # noqa: E402
from coach_app.episode_discovery import discover_episode_candidates  # noqa: E402
from coach_app.episode_evidence import build_episode_evidence  # noqa: E402
from coach_app.episode_stage1 import build_stage1_episode_packet  # noqa: E402
from coach_app.situations import classify_frame, discover_situations  # noqa: E402

GENERIC = re.compile(r"\b(rotate back|save boost|don'?t double commit|challenge earlier|be patient|play safer)\b", re.I)
NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
THRESHOLDS = [  # (module, attribute or dict key, label)
    (sr, "PRESSURE_S", "possession: pressure time"), (sr, "DETOUR_OK_S", "recovery: acceptable detour"),
    (sr, "LOW_BOOST", "low boost (situation classes)"), (sr, "SMALL_PAD_CORRIDOR_UU", "small-pad corridor"),
    (sr, "CLOSING_COMMIT_UU_S", "opponent closing speed = committing"), (ar, "LOW_BOOST", "boost for recovery"),
    (ar, "ROOM_UU", "room to delay"), (v1.POLICY, "cover_window_s", "cover window"),
]


def _stage_a(f):
    return {k: v for k, v in f.items() if k not in ("retrospective",)}


def _match_id(path: str) -> str:
    return "match-" + hashlib.sha256(Path(path).stem.encode()).hexdigest()[:8]


def evaluate_player(path: str, pi: int) -> dict:
    d = pickle.loads(Path(path).read_bytes())
    pid = d["players"][pi]["id"]
    out: dict = {"match": _match_id(path), "player_index": pi}
    t = time.time()
    rep = build_coaching_report(d, pid, max_findings=6)
    out["seconds_new"] = round(time.time() - t, 1)
    blob = json.dumps(rep, default=str)
    out["privacy_leak"] = any(p["id"] in blob or (p.get("name") and len(p["name"]) > 3 and p["name"] in blob)
                              for p in d["players"])
    out["coverage"] = rep["coverage"]
    out["patterns"] = rep["patterns"]
    fs = rep["findings"]
    out["findings"] = []
    for f in fs:
        rb = f.get("retrospective", {})
        o = rb.get("outcome", {})
        take = f["takeaway"].get("text") or ""
        out["findings"].append({
            "class": f["situation"]["class"], "kind": f["kind"], "status": f["status"],
            "n_alternatives": len(f.get("alternatives", [])),
            "n_supported_families": len({a["family"] for a in f.get("alternatives", []) if a["status"] == "supported"}),
            "n_decisive": len(f.get("assumptions", {}).get("decisive", [])) if isinstance(f.get("assumptions"), dict) else 0,
            "takeaway_kind": f["takeaway"].get("kind"), "takeaway_numbers": len(NUM.findall(take)),
            "takeaway_len": len(take), "takeaway_hash": hashlib.sha256(re.sub(NUM, "#", take).encode()).hexdigest()[:10],
            "generic_phrases": len(GENERIC.findall(json.dumps(_stage_a(f)))),
            "untraced_numbers": len(f["validation"]["untraced_numbers"]),
            "rejected_claims": len(f["validation"]["rejected_claims"]),
            "observed": rb.get("observed_action", {}).get("label"),
            "verdict": rb.get("assessment", {}).get("verdict"),
            "goal_within_5s": (o.get("goal") or {}).get("scored_by"),
            "opponent_next_touch": bool(o.get("touch_sequence")) and o["touch_sequence"][0]["by"] == "opponent",
        })
    # stage separation on real data: recompute Stage A from a t0 prefix, and with the future rewritten
    inv = Counter()
    for f in fs[:3]:
        t0 = f["t0"]
        a = _stage_a(coach_moment(d, pid, t0, include_retrospective=False))
        b = _stage_a(coach_moment(prefix(d, t0), pid, t0, include_retrospective=False))
        d2 = copy.deepcopy(d)
        for fr in d2["frames"]:
            if fr["t"] > t0:
                fr["ball"]["x"] = -fr["ball"]["x"]
        d2["events"] = [e for e in d2["events"] if not (isinstance(e.get("t"), (int, float)) and e["t"] > t0)] + \
                       [{"type": "goal_context", "t": t0 + 1.0, "scoringTeam": "orange"}]
        c = _stage_a(coach_moment(d2, pid, t0, include_retrospective=False))
        inv["checked"] += 1
        inv["prefix_identical"] += a == b
        inv["future_rewrite_identical"] += a == c
    out["invariance"] = dict(inv)
    # old default path on the same match/player
    t = time.time()
    old = Counter()
    try:
        cands = discover_episode_candidates(d, pid, max_candidates=8)["candidates"]
    except Exception:  # noqa: BLE001
        cands = []
    for cnd in cands:
        old["candidates"] += 1
        fr = [x for x in d["frames"] if x["t"] <= cnd["primary_t0"] + 1e-9]
        sit = classify_frame(fr[-1], d["players"], pid) if fr else None
        old["candidate_class_" + (sit.situation_class if sit else "none")] += 1
        try:
            ep = build_episode_evidence(d, pid, cnd["decision_times"], cnd["episode_start_s"], cnd["primary_t0"])
            lesson = build_lesson_from_episode(ep)
            rat = analyze_action_rationale(build_stage1_episode_packet(ep))
        except Exception:  # noqa: BLE001
            old["lesson_error"] += 1
            continue
        old["lessons"] += 1
        old["lesson_grade_" + lesson["assessment"]["grade"]] += 1
        old["lesson_has_takeaway"] += int(bool(lesson.get("takeaway")))
        old["rationale_judgment_" + rat["judgment"]] += 1
        old["generic_phrases"] += len(GENERIC.findall(json.dumps(lesson)))
        old["first_defender_vocabulary_on_non_first_defender"] += int(sit is None or sit.situation_class != "first_defender")
    out["old"] = dict(old)
    out["seconds_old"] = round(time.time() - t, 1)
    return out


def sensitivity(path: str, pi: int, max_items: int = 40) -> dict:
    """Scale each threshold by 0.7 and 1.3; count ledgers whose supported/refuted sets change."""
    d = pickle.loads(Path(path).read_bytes())
    pid = d["players"][pi]["id"]
    sits = [s for s in discover_situations(d, pid) if s.situation_class != "aerial_or_wall"][:max_items]

    def sig(it):
        r = it["rationale"]
        return (tuple(sorted(r.get("supported", []))), tuple(sorted(r.get("refuted", []))), r.get("judgment"))

    base = {}
    for s in sits:
        it = analyze_moment(d, pid, s.to_dict())
        if it:
            base[s.t0] = sig(it)
    res = {}
    for mod, attr, label in THRESHOLDS:
        orig = mod[attr] if isinstance(mod, dict) else getattr(mod, attr)
        ch = Counter()
        for k in (0.7, 1.3):
            with _patched(mod, attr, orig * k):
                for s in sits:
                    if s.t0 not in base:
                        continue
                    it = analyze_moment(d, pid, s.to_dict())
                    ch[f"x{k}_n"] += 1
                    ch[f"x{k}_changed"] += sig(it) != base[s.t0]
        res[label] = {"value": orig, **dict(ch)}
    return {"match": _match_id(path), "situations": len(base), "thresholds": res}


@contextlib.contextmanager
def _patched(mod, attr, value):
    if isinstance(mod, dict):
        old = mod[attr]
        mod[attr] = value
        try:
            yield
        finally:
            mod[attr] = old
    else:
        old = getattr(mod, attr)
        setattr(mod, attr, value)
        try:
            yield
        finally:
            setattr(mod, attr, old)


def aggregate(rows: list[dict], sens: list[dict]) -> dict:
    F = [f for r in rows for f in r["findings"]]
    by = lambda key: dict(Counter(f[key] for f in F))  # noqa: E731
    cov = Counter()
    for r in rows:
        cov.update(r["coverage"]["by_class"])
    inv = Counter()
    for r in rows:
        inv.update(r["invariance"])
    old = Counter()
    for r in rows:
        old.update(r["old"])
    vt = defaultdict(Counter)
    for f in F:
        vt[f["verdict"]]["n"] += 1
        vt[f["verdict"]]["goal_against_5s"] += f["goal_within_5s"] == "opponents"
        vt[f["verdict"]]["opponent_next_touch"] += f["opponent_next_touch"]
    pat = Counter()
    tend = 0
    for r in rows:
        for cls, c in r["patterns"]["by_class"].items():
            for k, v in c.items():
                pat[f"{cls}:{k}"] += v
        tend += len(r["patterns"]["tendencies"])
    ok = [f for f in F if f["status"] == "ok"]
    sens_tot = defaultdict(Counter)
    for s in sens:
        for label, v in s["thresholds"].items():
            for k, x in v.items():
                if k != "value":
                    sens_tot[label][k] += x
            sens_tot[label]["value"] = v["value"]
    return {
        "cohort": {"replays": len({r["match"] for r in rows}), "player_reports": len(rows),
                   "note": "Public 2v2 replays of unknown rank; no human labels; this is not an accuracy benchmark."},
        "new": {
            "situations_analysed_by_class": dict(cov), "findings": len(F), "findings_by_class": by("class"),
            "findings_by_kind": by("kind"), "findings_status": by("status"),
            "takeaway_kinds": by("takeaway_kind"),
            "takeaways_with_numbers": sum(f["takeaway_numbers"] > 0 for f in ok), "ok_findings": len(ok),
            "distinct_takeaway_templates": len({f["takeaway_hash"] for f in ok}),
            "mean_alternatives": round(sum(f["n_alternatives"] for f in ok) / max(1, len(ok)), 2),
            "findings_with_two_or_more_defensible_families": sum(f["n_supported_families"] >= 2 for f in ok),
            "findings_with_decisive_unknowns": sum(f["n_decisive"] > 0 for f in ok),
            "generic_phrase_hits": sum(f["generic_phrases"] for f in F),
            "untraced_numbers": sum(f["untraced_numbers"] for f in F), "rejected_claims": sum(f["rejected_claims"] for f in F),
            "verdicts": by("verdict"),
            "verdict_vs_outcome": {k: dict(v) for k, v in vt.items()},
            "invariance": dict(inv),
            "privacy_leaks": sum(r["privacy_leak"] for r in rows),
            "pattern_counts": dict(pat), "tendencies_reported": tend,
            "mean_seconds_per_report": round(sum(r["seconds_new"] for r in rows) / max(1, len(rows)), 1),
        },
        "old": dict(old),
        "threshold_sensitivity": {k: dict(v) for k, v in sens_tot.items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cache", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--players", type=int, default=4)
    ap.add_argument("--sensitivity-matches", type=int, default=5)
    a = ap.parse_args()
    files = sorted(glob.glob(str(a.cache / "*.pkl")))
    jobs = [(f, i) for f in files for i in range(a.players)]
    with ProcessPoolExecutor(a.workers) as ex:
        rows = list(ex.map(evaluate_player, *zip(*jobs)))
        sens = list(ex.map(sensitivity, files[:a.sensitivity_matches], [0] * a.sensitivity_matches))
    res = aggregate(rows, sens)
    a.out.write_text(json.dumps(res, indent=1, default=str))
    (a.out.with_suffix(".rows.json")).write_text(json.dumps(rows, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()

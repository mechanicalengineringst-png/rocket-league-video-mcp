"""Round 15 truthfulness probe: call every coaching endpoint the UI uses with real decoded replays.

Records, per endpoint: HTTP status, latency, payload size, and content signals that decide whether the
feature is usable (how many moments, whether timestamps are real frame times, whether there is a decision
assessment, how repetitive the text is). Writes a JSON summary; no names or IDs are written.
Usage (from coach-app/): python scripts/audit_round15.py CACHE_DIR OUT.json [N_REPLAYS]
"""
from __future__ import annotations

import glob
import json
import pickle
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402

from coach_app.main import app  # noqa: E402

NUM = re.compile(r"\d+(?:\.\d+)?")


def _texts(o, out):
    if isinstance(o, str):
        if len(o) > 40:
            out.append(o)
    elif isinstance(o, dict):
        for v in o.values():
            _texts(v, out)
    elif isinstance(o, list):
        for v in o:
            _texts(v, out)
    return out


def _repetition(obj) -> dict:
    ts = _texts(obj, [])
    tpl = [NUM.sub("#", t) for t in ts]
    c = Counter(tpl)
    return {"long_strings": len(ts), "distinct_templates": len(c),
            "most_repeated_template_count": c.most_common(1)[0][1] if c else 0}


def probe(c: TestClient, d: dict, pid: str) -> dict:
    out = {}
    frame_ts = {round(f["t"], 3) for f in d["frames"]}

    def call(name, method, url, body=None):
        t = time.time()
        r = c.get(url) if method == "GET" else c.post(url, json=body)
        rec = {"status": r.status_code, "seconds": round(time.time() - t, 2), "bytes": len(r.content)}
        try:
            rec["json"] = r.json()
        except ValueError:
            rec["json"] = None
        out[name] = rec
        return rec

    call("capabilities", "GET", "/api/coach/capabilities")
    call("model_readiness", "GET", "/api/coach/model-readiness")
    b = call("review_bundle", "POST", "/api/coach/review-bundle",
             {"replay": d, "player_id": pid, "max_candidates": 8, "preview_count": 4})
    cand = call("candidates", "POST", "/api/coach/candidates", {"replay": d, "player_id": pid, "max_candidates": 6})
    call("decision_cases", "POST", "/api/decision-cases", {"replay": d, "player_id": pid, "evaluate": True, "analyze": True})
    cl = (cand["json"] or {}).get("candidates") or []
    if cl:
        x = cl[0]
        body = {"replay": d, "player_id": pid, "decision_times": x["decision_times"], "episode_start_s": x["episode_start_s"],
                "primary_t0": x["primary_t0"]}
        call("lesson", "POST", "/api/coach/lesson", body)
        call("scene_relations", "POST", "/api/coach/scene-relations", body)
        call("followup", "POST", "/api/coach/followup", {**body, "question": "Why was this moment selected?"})
        call("evidence", "POST", "/api/coach/evidence", {**body, "evidence_refs": ["E.focus.position"]})
    call("report_v1", "POST", "/api/coach/coaching-report-v1", {"replay": d, "player_id": pid, "max_findings": 6})
    call("report_v2", "POST", "/api/coach/coaching-report-v2", {"replay": d, "player_id": pid, "max_findings": 6})
    call("ai_review", "POST", "/api/ai-review", {"replay": d, "player_id": pid, "t": d["frames"][len(d["frames"]) // 2]["t"]})
    call("companion_status", "GET", "/api/companion/status")
    # content signals
    sig = {}
    bj = b["json"] or {}
    sig["review_bundle"] = {
        "schema": bj.get("schema"), "candidates": len(bj.get("candidates", []) or []),
        "previews": len(bj.get("lessons", bj.get("previews", [])) or []),
        "lesson_grades": dict(Counter((l.get("assessment") or {}).get("grade") for l in (bj.get("lessons") or bj.get("previews") or [])
                                      if isinstance(l, dict))),
        "candidate_t0_is_frame_time": _share([round(x.get("primary_t0", -1), 3) in frame_ts
                                              for x in bj.get("candidates", []) or []]),
        "repetition": _repetition(bj)}
    lj = (out.get("lesson") or {}).get("json") or {}
    sig["lesson"] = {"grade": (lj.get("assessment") or {}).get("grade"), "has_takeaway": bool(lj.get("takeaway")),
                     "keys": sorted(lj)[:30]}
    v2 = (out["report_v2"]["json"] or {})
    m = (v2.get("matches") or [{}])[0]
    sig["report_v2"] = {"decision_findings": len(m.get("decision_findings", [])), "turning_points": len(m.get("turning_points", [])),
                        "habits": len((v2.get("habit_profile") or {}).get("habits", [])),
                        "habit_standouts": sum(1 for h in (v2.get("habit_profile") or {}).get("habits", []) if h.get("standout")),
                        "repetition": _repetition(m)}
    v1 = out["report_v1"]["json"] or {}
    sig["report_v1"] = {"findings": len(v1.get("findings", [])), "repetition": _repetition(v1.get("findings", []))}
    dc = out["decision_cases"]["json"] or {}
    sig["decision_cases"] = {"cases": len(dc.get("cases", []) or []), "keys": sorted(dc)[:15]}
    for k in out:
        out[k].pop("json", None)
    return {"endpoints": out, "signals": sig}


def _share(xs):
    return round(sum(xs) / len(xs), 3) if xs else None


def main(cache: Path, dest: Path, n: int = 2):
    c = TestClient(app, raise_server_exceptions=False)
    files = sorted(glob.glob(str(cache / "*.pkl")))[:n]
    res = []
    for f in files:
        d = pickle.loads(Path(f).read_bytes())
        res.append(probe(c, d, d["players"][0]["id"]))
    dest.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 2)

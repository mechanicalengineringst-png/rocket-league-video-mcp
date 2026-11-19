"""CoachingReportV2 for one player across one or more local replays (no upload, no model call).

Usage (from coach-app/):
  python scripts/coach_replays_v2.py A.replay B.replay --player NAME --md report.md [--json report.json]
  python scripts/coach_replays_v2.py A.replay                       # list players
The player is matched by name (case-insensitive) in each replay; replays without that name are skipped.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from coach_replay import load  # noqa: E402

from coach_app.coach_report_v2 import build_coaching_report_v2  # noqa: E402
from coach_app.coach_report_v2_render import render_markdown_v2  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("replays", type=Path, nargs="+")
    ap.add_argument("--player")
    ap.add_argument("--md", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--max-findings", type=int, default=4)
    a = ap.parse_args(argv)
    data = [load(p) for p in a.replays]
    if not a.player:
        for path, d in zip(a.replays, data):
            print(path.name, [(p.get("name"), p.get("team")) for p in d.get("players", [])])
        return 0
    reps, ids = [], []
    for path, d in zip(a.replays, data):
        p = next((x for x in d.get("players", []) if (x.get("name") or "").lower() == a.player.lower() or x["id"] == a.player), None)
        if p is None or d.get("mode") not in (None, "2v2"):
            print(f"skipping {path.name}: player not found or not 2v2", file=sys.stderr)
            continue
        reps.append(d)
        ids.append(p["id"])
    if not reps:
        print("No replay contains that player.", file=sys.stderr)
        return 2
    t = time.time()
    rep = build_coaching_report_v2(reps, ids, max_findings=a.max_findings)
    md = render_markdown_v2(rep, player_label=a.player)
    if a.md:
        a.md.write_text(md)
    else:
        print(md)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=1, default=str))
    print(f"[{len(reps)} replays in {time.time() - t:.0f} s]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

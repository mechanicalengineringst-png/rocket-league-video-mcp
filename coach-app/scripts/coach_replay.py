"""Run the Round 12 coaching pipeline on a local replay (no upload, no model call).

Usage (from coach-app/):
  python scripts/coach_replay.py MATCH.replay                 # list players
  python scripts/coach_replay.py MATCH.replay --player NAME   # report for that player
  python scripts/coach_replay.py payload.json --player 0 --md report.md --json report.json

Accepts a native .replay (decoded locally with subtr-actor, as the app does) or a decoded payload (.json/.pkl).
The output contains no player names unless you print them yourself; the JSON omits names and IDs.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app.coach_report import build_coaching_report  # noqa: E402
from coach_app.coach_report_render import render_markdown  # noqa: E402


def load(path: Path) -> dict:
    if path.suffix == ".replay":
        from coach_app.replays import parse_replay_file
        return parse_replay_file(path)
    if path.suffix == ".pkl":
        return pickle.loads(path.read_bytes())
    return json.loads(path.read_text())


def pick(players: list[dict], sel: str) -> dict | None:
    if sel.isdigit() and int(sel) < len(players):
        return players[int(sel)]
    return next((p for p in players if p.get("name", "").lower() == sel.lower() or p["id"] == sel), None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("replay", type=Path)
    ap.add_argument("--player", help="name, id or index from the player list")
    ap.add_argument("--max-findings", type=int, default=6)
    ap.add_argument("--no-retrospective", action="store_true", help="Stage A only (no observed action or outcome)")
    ap.add_argument("--md", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    d = load(a.replay)
    players = d.get("players", [])
    if not a.player:
        for i, p in enumerate(players):
            print(f"{i}: {p.get('name', '?')} ({p.get('team')})")
        print("Choose one with --player.")
        return 0
    p = pick(players, a.player)
    if p is None:
        print("Player not found.", file=sys.stderr)
        return 2
    t = time.time()
    rep = build_coaching_report(d, p["id"], max_findings=a.max_findings, include_retrospective=not a.no_retrospective)
    md = render_markdown(rep, player_label=p.get("name", "focus player"))
    if a.md:
        a.md.write_text(md)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=1, default=str))
    if not a.md:
        print(md)
    print(f"[{len(rep['findings'])} findings from {rep['coverage']['situations_analysed']} situations in {time.time() - t:.0f} s]",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

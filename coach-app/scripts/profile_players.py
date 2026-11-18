"""Build cross-match player profiles from real replays and report what is (not) established.

Usage (from coach-app/): python scripts/profile_players.py PAYLOAD_CACHE_DIR OUT.json
Player identities are hashed in the output.
"""
from __future__ import annotations

import glob
import hashlib
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app.choices import classify_choice, find_defender_candidates  # noqa: E402
from coach_app.decision_cases import extract_all_decision_cases  # noqa: E402
from coach_app.defender_decisions import assess_defender  # noqa: E402
from coach_app.player_model import build_profile, execution_counts, observations_from, practice_priority  # noqa: E402
from coach_app.strategic_state import build_state  # noqa: E402
from coach_app.tactical_analysis import analyze_case  # noqa: E402


def anon(pid: str) -> str:
    return "player-" + hashlib.sha256(pid.encode()).hexdigest()[:8]


def main(cache: Path, out: Path) -> dict:
    obs, execution = [], defaultdict(list)
    for f in sorted(glob.glob(str(cache / "*.pkl"))):
        d = pickle.loads(Path(f).read_bytes())
        match = hashlib.sha256(Path(f).stem.encode()).hexdigest()[:8]
        by_player = defaultdict(list)
        for c in extract_all_decision_cases(d):
            by_player[c.focus_player_id].append(analyze_case(c, d))
        for cand in find_defender_candidates(d):
            st = build_state(d, cand.t0, cand.player_id)
            by_player[cand.player_id].append(assess_defender(st, classify_choice(d, cand.t0, cand.player_id), "x"))
        for p in d["players"]:
            obs += observations_from(by_player.get(p["id"], []), p["id"], match)
            w, t = execution_counts(d["events"], p["id"])
            execution[p["id"]].append((match, w, t))
    players = sorted({o.player_id for o in obs})
    profiles = {pid: build_profile(pid, obs, execution) for pid in players}
    matches_per_player = Counter(len({o.match_id for o in obs if o.player_id == p}) for p in players)
    status = Counter()
    for prof in profiles.values():
        for sec in ("decision_consistency", "preferences", "execution", "team_context"):
            for r in prof[sec].values():
                status[f"{sec}|{r['status']}"] += 1
    with_pattern = {anon(p): practice_priority(pr) for p, pr in profiles.items() if pr["patterns"]}
    report = {"players": len(players), "observations": len(obs),
              "players_by_matches_observed": dict(sorted(matches_per_player.items())),
              "rate_status_counts": dict(sorted(status.items())),
              "players_with_an_established_pattern": len(with_pattern),
              "established_patterns": with_pattern,
              "example_profile": {k: v for k, v in profiles[max(players, key=lambda p: profiles[p]["moments"])].items()
                                  if k != "player_id"}}
    out.write_text(json.dumps(report, indent=1, default=str))
    return report


if __name__ == "__main__":
    r = main(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps({k: v for k, v in r.items() if k != "example_profile"}, indent=1, default=str))

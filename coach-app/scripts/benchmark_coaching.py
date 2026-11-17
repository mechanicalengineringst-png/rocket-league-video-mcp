"""Benchmark script for Replay Lab coaching backend.
Profiles replay decoding, native event generation, candidate extraction, and LLM payload sizes.
"""
from __future__ import annotations

import json
import os
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

# Ensure coach_app is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import subtr_actor
from coach_app.subtr_replays import parse_subtr_replay
from coach_app.contextual_review import build_contextual_reviews
from coach_app.coaching import find_review_candidates, compact_game_states


REPLAY_DIR = Path(r"D:\Users\Sam Meyer\Documents\My Games\Rocket League\TAGame\DemosEpic")
PRIMARY_REPLAY = REPLAY_DIR / "23A661D44DBC5964B0718DBC5F956A33.replay"
BENCHMARK_REPLAYS = [
    PRIMARY_REPLAY,
    REPLAY_DIR / "03F49B8045D8B49A8C69A2A2EB011C95.replay",
    REPLAY_DIR / "022B278F4EA6E1C6B9E7C8BDC7256FE9.replay",
]


def benchmark_replay(replay_path: Path) -> dict[str, Any]:
    print(f"\n--- Benchmarking: {replay_path.name} ---")
    if not replay_path.exists():
        print(f"File not found: {replay_path}")
        return {"error": "not found"}

    file_size_bytes = replay_path.stat().st_size

    # 1. Native subtr-actor full stats extraction
    tracemalloc.start()
    t0 = time.perf_counter()
    full_events_data = subtr_actor.get_stats_events(str(replay_path))
    t_full_decode = time.perf_counter() - t0
    peak_full_mem = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
    tracemalloc.stop()

    full_events = full_events_data.get("events", [])
    event_counts_by_type: dict[str, int] = {}
    for ev in full_events:
        stream = ev.get("meta", {}).get("stream", "unknown")
        event_counts_by_type[stream] = event_counts_by_type.get(stream, 0) + 1

    # 2. Existing coach-app parse_subtr_replay
    tracemalloc.start()
    t0 = time.perf_counter()
    payload = parse_subtr_replay(replay_path)
    t_app_load = time.perf_counter() - t0
    peak_app_mem = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
    tracemalloc.stop()

    frames = payload.get("frames", [])
    app_events = payload.get("events", [])
    players = payload.get("players", [])
    primary_player_id = payload.get("primaryPlayerId") or (players[0]["id"] if players else "")

    # 3. Contextual review candidates per player
    t0 = time.perf_counter()
    contextual_reviews_by_player = {}
    for p in players:
        pid = p["id"]
        try:
            reviews = build_contextual_reviews(payload, pid)
            contextual_reviews_by_player[pid] = reviews
        except Exception as e:
            contextual_reviews_by_player[pid] = {"error": str(e)}
    t_contextual = time.perf_counter() - t0

    # 4. Coaching rule analysis (find_review_candidates)
    t0 = time.perf_counter()
    candidates_by_player = {}
    for p in players:
        pid = p["id"]
        candidates_by_player[pid] = find_review_candidates(payload, pid)
    t_coaching = time.perf_counter() - t0

    # 5. LLM prompt size estimation (compact_game_states)
    compact_text = compact_game_states(payload, primary_player_id, max_frames=90)
    instruction = (
        "You are a skeptical Rocket League replay coach. "
        "Analyze ONLY the supplied numerical replay positions and velocities.\n\n"
        + compact_text
    )
    estimated_tokens = len(instruction) // 4

    res = {
        "filename": replay_path.name,
        "file_size_kb": round(file_size_bytes / 1024, 2),
        "duration_seconds": round(payload.get("duration", 0.0), 2),
        "total_frames_30hz": len(frames),
        "player_count": len(players),
        "players": [{"id": p.get("id"), "name": p.get("name"), "team": p.get("team")} for p in players],
        "native_decode_time_s": round(t_full_decode, 4),
        "native_peak_memory_mb": round(peak_full_mem, 2),
        "native_total_events": len(full_events),
        "native_event_types_count": len(event_counts_by_type),
        "native_event_distribution": dict(sorted(event_counts_by_type.items(), key=lambda x: x[1], reverse=True)[:20]),
        "app_load_time_s": round(t_app_load, 4),
        "app_peak_memory_mb": round(peak_app_mem, 2),
        "app_retained_events": len(app_events),
        "app_retained_ratio": round(len(app_events) / max(len(full_events), 1), 4),
        "contextual_extraction_time_s": round(t_contextual, 4),
        "contextual_reviews_count": {pid: len(revs) if isinstance(revs, list) else 0 for pid, revs in contextual_reviews_by_player.items()},
        "contextual_reviews_detail": contextual_reviews_by_player,
        "legacy_candidates_time_s": round(t_coaching, 4),
        "legacy_candidates_count": {pid: len(cands) for pid, cands in candidates_by_player.items()},
        "legacy_candidates_categories": {
            pid: {cat: sum(1 for c in cands if c.get("type") == cat) for cat in set(c.get("type") for c in cands)}
            for pid, cands in candidates_by_player.items()
        },
        "llm_prompt_chars": len(instruction),
        "llm_prompt_estimated_tokens": estimated_tokens,
    }
    return res


def main():
    results = []
    for replay in BENCHMARK_REPLAYS:
        if replay.exists():
            res = benchmark_replay(replay)
            results.append(res)

    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)
    for r in results:
        print(f"Replay: {r['filename']} ({r['file_size_kb']} KB, {r['duration_seconds']}s, {r['total_frames_30hz']} frames)")
        print(f"  Native: {r['native_decode_time_s']}s, {r['native_peak_memory_mb']} MB, {r['native_total_events']} events ({r['native_event_types_count']} types)")
        print(f"  App Load: {r['app_load_time_s']}s, {r['app_peak_memory_mb']} MB, {r['app_retained_events']} events ({r['app_retained_ratio']*100:.1f}% retained)")
        print(f"  Contextual Reviews: {r['contextual_reviews_count']}")
        print(f"  Legacy Candidates: {r['legacy_candidates_count']}")
        print(f"  LLM Prompt Size: {r['llm_prompt_chars']} chars (~{r['llm_prompt_estimated_tokens']} tokens)")

    out_file = Path(__file__).parent / "benchmark_results.json"
    out_file.write_text(json.dumps(results, indent=2))
    print(f"\nSaved benchmark results to {out_file}")


if __name__ == "__main__":
    main()

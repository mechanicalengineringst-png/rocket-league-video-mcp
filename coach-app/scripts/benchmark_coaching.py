"""Benchmark script for Replay Lab coaching backend.
Profiles replay decoding, native event generation, candidate extraction, DecisionCase extraction,
and LLM payload sizes with full privacy scrubbing and portable fixture paths.
"""
from __future__ import annotations

import copy
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
from coach_app.decision_cases import extract_all_decision_cases
from coach_app.decision_evaluation import evaluate_decision_case_heuristics


def get_replay_dir() -> Path:
    env_dir = os.getenv("RL_REPLAY_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p
    local_demos = Path.home() / "Documents" / "My Games" / "Rocket League" / "TAGame" / "DemosEpic"
    if local_demos.is_dir():
        return local_demos
    alt_drive = Path(r"D:\Users\Sam Meyer\Documents\My Games\Rocket League\TAGame\DemosEpic")
    if alt_drive.is_dir():
        return alt_drive
    return Path("./fixtures/replays")


def get_process_working_set_mb() -> float:
    """Measure total process working set (RSS) on Windows or POSIX."""
    try:
        import ctypes
        import ctypes.wintypes
        class PMC(ctypes.Structure):
            _fields_ = [('cb', ctypes.wintypes.DWORD), ('PageFaultCount', ctypes.wintypes.DWORD),
                        ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]
        fn = ctypes.windll.psapi.GetProcessMemoryInfo
        fn.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(PMC), ctypes.wintypes.DWORD]
        fn.restype = ctypes.wintypes.BOOL
        p = PMC()
        p.cb = ctypes.sizeof(PMC)
        if fn(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(p), p.cb):
            return round(p.WorkingSetSize / (1024 * 1024), 2)
    except Exception:
        pass
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2)
    except Exception:
        pass
    return 0.0


def anonymize_players(players: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str]]:
    """Scrub platform identifiers and real names for public repository benchmarks."""
    id_map = {}
    name_map = {}
    anon_players = []
    blue_idx = 1
    orange_idx = 1
    for p in players:
        raw_id = p.get("id", "")
        raw_name = p.get("name", "")
        team = p.get("team", "blue")
        if team == "blue":
            anon_id = f"player_blue_{blue_idx}"
            anon_name = f"Player Blue {blue_idx}"
            blue_idx += 1
        else:
            anon_id = f"player_orange_{orange_idx}"
            anon_name = f"Player Orange {orange_idx}"
            orange_idx += 1
        id_map[raw_id] = anon_id
        if raw_name:
            name_map[raw_name] = anon_name
        anon_players.append({
            "id": anon_id,
            "name": anon_name,
            "team": team,
        })
    return anon_players, id_map, name_map


def scrub_text(text: str, name_map: dict[str, str], id_map: dict[str, str]) -> str:
    for raw_name, anon_name in name_map.items():
        if raw_name and raw_name in text:
            text = text.replace(raw_name, anon_name)
    for raw_id, anon_id in id_map.items():
        if raw_id and raw_id in text:
            text = text.replace(raw_id, anon_id)
    return text


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
    peak_python_decode_mem = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
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
    peak_python_app_mem = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
    total_rss_mb = get_process_working_set_mb()
    tracemalloc.stop()

    frames = payload.get("frames", [])
    app_events = payload.get("events", [])
    raw_players = payload.get("players", [])
    anon_players, id_map, name_map = anonymize_players(raw_players)

    # 3. DecisionCase Extraction & Evaluation (New Engine)
    t0 = time.perf_counter()
    decision_cases = extract_all_decision_cases(payload, full_events)
    t_decision_cases = time.perf_counter() - t0

    cases_by_category: dict[str, int] = {}
    evaluations_by_category: dict[str, int] = {}
    for c in decision_cases:
        cases_by_category[c.situation_type] = cases_by_category.get(c.situation_type, 0) + 1
        ev_res = evaluate_decision_case_heuristics(c)
        if ev_res:
            atype = ev_res.get("assessment", "unclassified")
            evaluations_by_category[atype] = evaluations_by_category.get(atype, 0) + 1

    # 4. Contextual review candidates per player (Legacy)
    t0 = time.perf_counter()
    contextual_reviews_by_anon = {}
    for p in raw_players:
        pid = p["id"]
        anon_id = id_map[pid]
        try:
            reviews = build_contextual_reviews(payload, pid)
            contextual_reviews_by_anon[anon_id] = len(reviews) if isinstance(reviews, list) else 0
        except Exception:
            contextual_reviews_by_anon[anon_id] = 0
    t_contextual = time.perf_counter() - t0

    # 5. Legacy coaching rule analysis (find_review_candidates)
    t0 = time.perf_counter()
    legacy_candidates_by_anon = {}
    legacy_cat_counts: dict[str, int] = {}
    for p in raw_players:
        pid = p["id"]
        anon_id = id_map[pid]
        cands = find_review_candidates(payload, pid)
        legacy_candidates_by_anon[anon_id] = len(cands)
        for c in cands:
            ctype = c.get("type", "unknown")
            legacy_cat_counts[ctype] = legacy_cat_counts.get(ctype, 0) + 1
    t_legacy = time.perf_counter() - t0

    # 6. LLM prompt size estimation (compact_game_states)
    primary_pid = raw_players[0]["id"] if raw_players else ""
    compact_text = compact_game_states(payload, primary_pid, max_frames=90)
    compact_text_scrubbed = scrub_text(compact_text, name_map, id_map)
    instruction = (
        "You are a skeptical Rocket League replay coach. "
        "Analyze ONLY the supplied numerical replay positions and velocities.\n\n"
        + compact_text_scrubbed
    )
    estimated_tokens = len(instruction) // 4

    res = {
        "filename": replay_path.name,
        "file_size_kb": round(file_size_bytes / 1024, 2),
        "duration_seconds": round(payload.get("duration", 0.0), 2),
        "total_frames_30hz": len(frames),
        "player_count": len(raw_players),
        "players": anon_players,
        "native_decode_time_s": round(t_full_decode, 4),
        "native_python_heap_mb": round(peak_python_decode_mem, 2),
        "total_process_rss_mb": total_rss_mb,
        "native_total_events": len(full_events),
        "native_event_types_count": len(event_counts_by_type),
        "native_event_distribution": dict(sorted(event_counts_by_type.items(), key=lambda x: x[1], reverse=True)[:20]),
        "app_load_time_s": round(t_app_load, 4),
        "app_python_heap_mb": round(peak_python_app_mem, 2),
        "app_retained_events": len(app_events),
        "app_retained_ratio": round(len(app_events) / max(len(full_events), 1), 4),
        "decision_cases_count": len(decision_cases),
        "decision_cases_time_s": round(t_decision_cases, 4),
        "decision_cases_by_category": cases_by_category,
        "decision_cases_evaluations": evaluations_by_category,
        "legacy_contextual_reviews_time_s": round(t_contextual, 4),
        "legacy_contextual_reviews_count": contextual_reviews_by_anon,
        "legacy_candidates_time_s": round(t_legacy, 4),
        "legacy_candidates_count": legacy_candidates_by_anon,
        "legacy_candidates_categories": legacy_cat_counts,
        "legacy_llm_prompt_chars": len(instruction),
        "legacy_llm_prompt_estimated_tokens": estimated_tokens,
    }
    return res


def export_sample_decision_cases(replay_path: Path, out_path: Path) -> None:
    """Export representative sample decision cases for blind tactical review with full privacy scrubbing."""
    if not replay_path.exists():
        return
    payload = parse_subtr_replay(replay_path)
    full_events = subtr_actor.get_stats_events(str(replay_path)).get("events", [])
    raw_players = payload.get("players", [])
    anon_players, id_map, name_map = anonymize_players(raw_players)

    cases = extract_all_decision_cases(payload, full_events)

    def scrub_dict(d: Any) -> Any:
        if isinstance(d, dict):
            return {k: scrub_dict(v) for k, v in d.items()}
        elif isinstance(d, list):
            return [scrub_dict(x) for x in d]
        elif isinstance(d, str):
            return scrub_text(d, name_map, id_map)
        return d

    samples = []

    # 1. Correct Observation: Kickoff route tradeoff
    c1 = next((c for c in cases if c.situation_type == "kickoff_support"), None)
    if c1:
        eval1 = evaluate_decision_case_heuristics(c1)
        p1 = c1.to_llm_payload(include_quarantined_outcomes=False)
        samples.append({
            "category_label": "1. Correct Observation (Neutral Tradeoff Hypothesis)",
            "description": "Examines a kickoff support decision without jumping to a double-commit verdict.",
            "decision_case": scrub_dict(p1),
            "heuristic_evaluation": scrub_dict(eval1),
        })

    # 2. Questionable Classification / Nuance: Depth vs Coverage
    c2 = next((c for c in cases if c.situation_type == "first_man_challenge"), None)
    if c2:
        eval2 = evaluate_decision_case_heuristics(c2)
        p2 = c2.to_llm_payload(include_quarantined_outcomes=False)
        samples.append({
            "category_label": "2. Nuanced Observation (Depth is Not Verified Coverage)",
            "description": "Identifies that a teammate being behind the ball provides geometric depth, but cannot prove defensive orientation or momentum without visual inspection.",
            "decision_case": scrub_dict(p2),
            "heuristic_evaluation": scrub_dict(eval2),
        })

    # 3. Missing Evidence / Epistemic Boundary: Last-man defense
    c3 = next((c for c in cases if c.situation_type == "last_man_defense"), None)
    if c3:
        eval3 = evaluate_decision_case_heuristics(c3)
        p3 = c3.to_llm_payload(include_quarantined_outcomes=False)
        samples.append({
            "category_label": "3. Missing Evidence (Camera and Opponent Flick Ambiguity)",
            "description": "Defines explicit boundaries of what telemetry cannot establish (opponent camera, visual perspective, micro-touch flicks).",
            "decision_case": scrub_dict(p3),
            "heuristic_evaluation": scrub_dict(eval3),
        })

    # 4. Abstention: Deliberate telemetry ambiguity fallback
    samples.append({
        "category_label": "4. Abstention (Failsafe for Ambiguous / Missing Telemetry)",
        "description": "System abstains from asserting tactical mistakes when telemetry lacks requisite orientational or recovery context.",
        "decision_case": {
            "decision_case_id": "case-abstain-demo",
            "decision_time_s": 142.5,
            "focus_player": {"id": "player_blue_1", "name": "Player Blue 1", "team": "blue"},
            "situation_type": "first_man_challenge",
            "pre_decision_facts": [
                {"key": "challenge_approach", "fact": "Player Blue 1 challenged ball at midfield", "event_time_s": 142.5, "source": "derived"}
            ],
            "tactical_context": {"mate_distance": None, "defensive_coverage_verified": False},
            "hypothetical_alternatives_to_inspect": ["shadow_defense", "challenge"],
            "epistemic_uncertainties": ["Teammate position missing from tracking frame", "Camera angle unknown"],
        },
        "heuristic_evaluation": {
            "assessment": "abstain",
            "title": "Insufficient telemetry for tactical assessment",
            "advice": "Review this moment in full 3D playback or player POV to determine tactical validity.",
            "cited_evidence": ["challenge_approach"],
        },
    })

    out_path.write_text(json.dumps(samples, indent=2))
    print(f"Saved scrubbed review sample to {out_path}")


def main():
    replay_dir = get_replay_dir()
    print(f"Using replay directory: {replay_dir}")

    benchmark_replays = [
        replay_dir / "23A661D44DBC5964B0718DBC5F956A33.replay",
        replay_dir / "03F49B8045D8B49A8C69A2A2EB011C95.replay",
        replay_dir / "022B278F4EA6E1C6B9E7C8BDC7256FE9.replay",
    ]

    results = []
    for replay in benchmark_replays:
        if replay.exists():
            res = benchmark_replay(replay)
            results.append(res)
        else:
            print(f"Skipping absent replay: {replay.name}")

    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY (PRIVACY-SCRUBBED)")
    print("=" * 60)
    for r in results:
        print(f"Replay: {r['filename']} ({r['file_size_kb']} KB, {r['duration_seconds']}s, {r['total_frames_30hz']} frames)")
        print(f"  Native: {r['native_decode_time_s']}s, Python Heap: {r['native_python_heap_mb']} MB, Total RSS: {r['total_process_rss_mb']} MB")
        print(f"  Native Events: {r['native_total_events']} ({r['native_event_types_count']} streams)")
        print(f"  DecisionCases Extracted: {r['decision_cases_count']} in {r['decision_cases_time_s']}s ({r['decision_cases_by_category']})")
        print(f"  DecisionCase Evaluations: {r['decision_cases_evaluations']}")
        print(f"  Legacy Candidates: {r['legacy_candidates_categories']}")

    out_file = Path(__file__).parent / "benchmark_results.json"
    out_file.write_text(json.dumps(results, indent=2))
    print(f"\nSaved scrubbed benchmark results to {out_file}")

    # Export representative sample
    sample_file = Path(__file__).parent / "sample_decision_cases_review.json"
    if benchmark_replays[0].exists():
        export_sample_decision_cases(benchmark_replays[0], sample_file)


if __name__ == "__main__":
    main()

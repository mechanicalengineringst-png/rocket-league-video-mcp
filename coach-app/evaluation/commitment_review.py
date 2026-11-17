"""Prepare blind commitment-timing clips and compare human temporal annotations.

Keep this independent of the coaching and HD replay branches. The original
event trigger/choice/fixture identifiers stay PRIVATE; reviewers see only
anonymous video clips. Video content itself must be inspected to remove goals,
winner banners, player names and other post-outcome information.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import shutil
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

CHOICES = ("challenge", "shadow", "fake", "other", "unclear")
DETECTOR_CHOICES = ("challenge", "shadow", "unclear")
CONFIDENCES = ("low", "medium", "high")
STRATA = {"challenge": 15, "shadow": 15, "unclear": 10}
SECONDARY_STRATA = {"challenge": 8, "shadow": 7, "unclear": 5}
SCHEMA = "replay-lab-commitment-review-v1"
ANONYMOUS_REVIEW_ID = re.compile(r"^T[0-9]{5}$")
PLATFORM_ID = re.compile(r"\b(?:Steam|Epic|PSN|PsyNet|Xbox):[A-Za-z0-9_-]{7,}\b", re.I)


def _need(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def validate_manifest(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Strict private manifest; video extraction must come from another tool."""
    _need(isinstance(rows, list) and len(rows) > 0, "Expected a nonempty case manifest")
    indexed: dict[str, dict[str, Any]] = {}
    filenames: set[str] = set()
    allowed = {
        "case_id", "replay_group", "detector_choice", "source_t0_s",
        "clip_start_s", "clip_end_s", "clip_file", "focus_hint",
    }
    for row in rows:
        _need(isinstance(row, dict) and set(row) == allowed,
              "Manifest entry must have exactly the documented fields")
        cid = row["case_id"]
        _need(isinstance(cid, str) and 1 <= len(cid) <= 160,
              "Case ID must be a nonempty bounded string")
        _need(cid not in indexed, f"Duplicate case ID: {cid}")
        group = row["replay_group"]
        _need(isinstance(group, str) and 1 <= len(group) <= 160,
              f"{cid}: missing or too-long replay group")
        _need(row["detector_choice"] in DETECTOR_CHOICES,
              f"{cid}: detector choice must be challenge/shadow/unclear")
        t0, start, end = (
            row["source_t0_s"], row["clip_start_s"], row["clip_end_s"]
        )
        _need(all(_finite(v) for v in (t0, start, end))
              and 0 <= start <= t0 <= end and 0 < end - start <= 30,
              f"{cid}: invalid clip time interval")
        name = row["clip_file"]
        _need(isinstance(name, str) and name == Path(name).name
              and "/" not in name and "\\" not in name
              and name.lower().endswith((".mp4", ".webm")) and len(name) < 150,
              f"{cid}: clip_file must be a simple .mp4/.webm filename")
        _need(name not in filenames, f"Duplicate clip file: {name}")
        filenames.add(name)
        hint = row["focus_hint"]
        _need(isinstance(hint, str) and 0 < len(hint) <= 160
              and not PLATFORM_ID.search(hint),
              f"{cid}: focus_hint must be short and anonymized")
        indexed[cid] = row
    return indexed


def prepare_packets(
    candidates: list[dict[str, Any]],
    *,
    seed: int = 20261117,
    min_replay_groups: int = 3,
    min_gap_s: float = 5,
) -> dict[str, Any]:
    """Return 40 anonymous packets, 20 overlapping secondary and private map.

    The initial 15/15/10 strata correspond to detector *claims*, not truth.
    Greedy match balancing is a practical pilot heuristic, not independence.
    """
    source = validate_manifest(candidates)
    _need(isinstance(min_replay_groups, int) and not isinstance(min_replay_groups, bool)
          and min_replay_groups >= 3, "At least 3 distinct matches required")
    _need(_finite(min_gap_s) and min_gap_s >= 0, "min_gap_s must be nonnegative")
    all_groups = {c["replay_group"] for c in source.values()}
    _need(len(all_groups) >= min_replay_groups,
          f"Need at least {min_replay_groups} replay groups, got {len(all_groups)}")
    rng = random.Random(seed)
    available = {key: [c for c in source.values() if
                       c["detector_choice"] == key] for key in DETECTOR_CHOICES}
    for label, count in STRATA.items():
        _need(len(available[label]) >= count,
              f"Not enough {label} candidates for the 40-clip pilot")
        rng.shuffle(available[label])
    chosen: list[dict[str, Any]] = []
    match_use: Counter[str] = Counter()
    used_times: dict[str, list[float]] = defaultdict(list)
    # Interleave labels; otherwise a dense early stratum can monopolize times.
    for i in range(max(STRATA.values())):
        families = list(DETECTOR_CHOICES)
        rng.shuffle(families)
        for label in families:
            if i >= STRATA[label]:
                continue
            eligible = [
                c for c in available[label]
                if all(abs(c["source_t0_s"] - prior) >= min_gap_s
                       for prior in used_times[c["replay_group"]])
            ]
            _need(bool(eligible), f"Could not satisfy {label} temporal diversity; "
                  "provide more clips from independent times/matches")
            pick = min(eligible, key=lambda c: match_use[c["replay_group"]])
            chosen.append(pick)
            match_use[pick["replay_group"]] += 1
            used_times[pick["replay_group"]].append(pick["source_t0_s"])
            available[label].remove(pick)
    _need(len(chosen) == 40, "Expected exactly 40 pilot clips")
    _need(len({c["replay_group"] for c in chosen}) >= min_replay_groups,
          "Selected cohort did not represent enough matches")
    rng.shuffle(chosen)

    mappings = {}
    packets = []
    for i, case in enumerate(chosen, 1):
        ident = f"T{i:05d}"
        extension = Path(case["clip_file"]).suffix.lower()
        blinded_file = ident + extension
        mappings[ident] = {
            "case_id": case["case_id"], "replay_group": case["replay_group"],
            "source_t0_s": case["source_t0_s"],
            "clip_start_s": case["clip_start_s"],
            "clip_end_s": case["clip_end_s"],
            "detector_choice": case["detector_choice"],
            "source_clip_file": case["clip_file"], "blinded_clip_file": blinded_file,
        }
        packets.append({
            "review_id": ident, "clip_file": blinded_file,
            "clip_duration_s": round(case["clip_end_s"]-case["clip_start_s"], 5),
            "focus_hint": case["focus_hint"],
        })
    # Overlap 20 clips, approximately preserving detector-label proportions
    # without exposing any label to a reviewer.
    second = []
    for label, target in SECONDARY_STRATA.items():
        subset = [p for p in packets if mappings[p["review_id"]]
                  ["detector_choice"] == label]
        rng.shuffle(subset)
        second.extend(subset[:target])
    rng.shuffle(second)
    return {
        "primary_packets": packets,
        "secondary_packets": second,
        "private_map": {
            "schema": SCHEMA,
            "seed": seed,
            "cases": mappings,
        },
    }


def validate_reviews(
    reviews: list[dict[str, Any]],
    mapping: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Fail closed on duplicate, mismatched, non-finite and out-of-clip marks."""
    _need(isinstance(reviews, list), "Review export must be a JSON array")
    _need(mapping.get("schema") == SCHEMA and isinstance(mapping.get("cases"), dict),
          "Unexpected private commitment mapping")
    checked: dict[str, dict[str, Any]] = {}
    reviewer_ids: set[str] = set()
    for entry in reviews:
        _need(isinstance(entry, dict), "Review record must be an object")
        allowed = {"review_id", "rater_id", "choice", "mark_type",
                   "earliest_s", "latest_s", "confidence", "note"}
        _need(set(entry) == allowed, "Review record has missing or unexpected fields")
        rid, who = entry["review_id"], entry["rater_id"]
        _need(isinstance(rid, str) and ANONYMOUS_REVIEW_ID.fullmatch(rid)
              and rid in mapping["cases"], f"Unknown review ID {rid}")
        _need(rid not in checked, f"Duplicate review ID in one submission: {rid}")
        _need(isinstance(who, str) and re.fullmatch(r"[A-Za-z0-9_-]{2,60}", who),
              "Reviewer code must contain 2–60 simple characters")
        reviewer_ids.add(who)
        _need(entry["choice"] in CHOICES, f"{rid}: invalid choice")
        _need(entry["confidence"] in CONFIDENCES, f"{rid}: invalid confidence")
        _need(isinstance(entry["note"], str) and len(entry["note"]) <= 2000,
              f"{rid}: note too long")
        _need(entry["mark_type"] in ("interval", "unobservable"),
              f"{rid}: invalid mark_type")
        earliest, latest = entry["earliest_s"], entry["latest_s"]
        if entry["mark_type"] == "interval":
            dur = mapping["cases"][rid]["clip_end_s"] - mapping["cases"][rid]["clip_start_s"]
            _need(_finite(earliest) and _finite(latest)
                  and 0 <= earliest <= latest <= dur + 0.001,
                  f"{rid}: invalid commitment interval")
        else:
            _need(earliest is None and latest is None,
                  f"{rid}: unobservable must not contain false timestamps")
        checked[rid] = entry
    _need(len(reviewer_ids) <= 1, "One review file must contain only one reviewer")
    return checked


def evaluate_timings(
    private_map: dict[str, Any],
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
) -> dict[str, Any]:
    """Agreement and lateness diagnostics, not evidence of tactical quality."""
    a = validate_reviews(primary, private_map)
    b = validate_reviews(secondary, private_map)
    _need(a and b, "Both reviewers must submit reviews")
    _need(next(iter(a.values()))["rater_id"] != next(iter(b.values()))["rater_id"],
          "Independent review requires different reviewer codes")
    reference = private_map["cases"]
    # The primary reviewer should cover the complete 40; secondary exactly
    # the agreed 20 subset is encouraged but not enforced by evaluator.
    _need(set(a) == set(reference), "Primary reviewer must cover all 40 cases")
    overlap = sorted(set(a).intersection(b))
    _need(bool(overlap), "No cases reviewed by both raters")
    _need(set(b).issubset(reference), "Secondary includes unknown review IDs")
    leads = []
    readable = []
    detector_matches = []
    observed_count = 0
    for rid, review in a.items():
        case = reference[rid]
        if review["choice"] != "unclear" and case["detector_choice"] != "unclear":
            readable.append(rid)
            detector_matches.append(review["choice"] == case["detector_choice"])
        if review["mark_type"] == "interval":
            observed_count += 1
            latest_world_s = case["clip_start_s"] + review["latest_s"]
            leads.append(case["source_t0_s"] - latest_world_s)
    pair_interval = [
        rid for rid in overlap
        if a[rid]["mark_type"] == b[rid]["mark_type"] == "interval"
    ]
    within = [
        rid for rid in pair_interval
        if max(
            abs(a[rid]["earliest_s"] - b[rid]["earliest_s"]),
            abs(a[rid]["latest_s"] - b[rid]["latest_s"])
        ) <= 0.3
    ]
    choice_agreement = sum(a[rid]["choice"] == b[rid]["choice"] for rid in overlap)
    median_lead = statistics.median(leads) if leads else None
    decision = (
        "insufficient_observable_windows" if len(leads) < 20 else
        "fixed_offset_probably_late" if median_lead >= 0.5 else
        "fixed_offset_consistent" if median_lead < 0.25 else "inconclusive"
    )
    return {
        "schema": "replay-lab-commitment-report-v1",
        "primary_reviews": len(a),
        "secondary_reviews": len(b),
        "shared_reviews": len(overlap),
        "shared_choice_agreement": choice_agreement,
        "shared_choice_agreement_rate": round(choice_agreement/len(overlap), 4),
        "shared_both_observable": len(pair_interval),
        "both_observable_endpoints_within_0_3s": len(within),
        "both_observable_endpoints_within_0_3s_rate": (
            round(len(within) / len(pair_interval), 4) if pair_interval else None
        ),
        "both_observable_endpoints_within_0_3s_among_all_shared": round(
            len(within) / len(overlap), 4
        ),
        "primary_observable": observed_count,
        "primary_unobservable": len(a) - observed_count,
        "primary_detector_readable_choice_compared": len(readable),
        "primary_detector_choice_matches": sum(detector_matches),
        "primary_detector_choice_agreement": (
            round(sum(detector_matches)/len(readable), 4) if readable else None
        ),
        "median_detector_t0_minus_human_latest_s": (
            round(median_lead, 5) if median_lead is not None else None
        ),
        "candidate_interpretation": decision,
        "warning": (
            "These are pilot diagnostics, not proven commitment or coaching "
            "accuracy. Labels were sampled conditional on detector choices; "
            "rater independence, true ability to abort and temporal leakage "
            "must be audited separately. The original event trigger and "
            "detector label are never shown during human review."
        ),
    }


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare/score blind timing review")
    subs = parser.add_subparsers(dest="action", required=True)
    make = subs.add_parser("prepare")
    make.add_argument("--manifest", type=Path, required=True)
    make.add_argument("--clips-dir", type=Path, required=True)
    make.add_argument("--output-dir", type=Path, required=True)
    make.add_argument("--seed", type=int, default=20261117)
    score = subs.add_parser("analyze")
    score.add_argument("--private-map", type=Path, required=True)
    score.add_argument("--primary", type=Path, required=True)
    score.add_argument("--secondary", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        packets = prepare_packets(_load(args.manifest), seed=args.seed)
        source_dir = args.clips_dir.resolve()
        source_files = []
        for row in packets["private_map"]["cases"].values():
            f = source_dir / row["source_clip_file"]
            _need(f.is_file() and f.resolve().parent == source_dir,
                  f"Clip missing from source directory: {f.name}")
            source_files.append((f, row["blinded_clip_file"]))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        target_dir = args.output_dir / "clips"
        target_dir.mkdir(exist_ok=True)
        for src, dst_name in source_files:
            shutil.copy2(src, target_dir / dst_name)
        _write(args.output_dir / "primary_packets.json", packets["primary_packets"])
        _write(args.output_dir / "secondary_packets.json", packets["secondary_packets"])
        _write(args.output_dir / "PRIVATE_DO_NOT_COMMIT_commitment_mapping.json",
               packets["private_map"])
        print("Reviewer clip files copied; keep the original mapping PRIVATE.")
    else:
        _write(args.output, evaluate_timings(
            _load(args.private_map), _load(args.primary), _load(args.secondary)
        ))


if __name__ == "__main__":
    main()

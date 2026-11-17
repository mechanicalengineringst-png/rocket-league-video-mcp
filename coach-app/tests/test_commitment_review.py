"""Blind commitment review: no future-outcome/trigger leakage in reviewer packets."""
import copy
from collections import Counter

import pytest

from evaluation.commitment_review import (
    evaluate_timings, prepare_packets, validate_manifest, validate_reviews,
)


def manifest(groups=("m1", "m2", "m3", "m4"), count_per_group=12):
    rows = []
    for g in groups:
        for fam_idx, label in enumerate(("challenge", "shadow", "unclear")):
            for i in range(count_per_group):
                # Separate all moments on the same replay by >=12 s.
                t0 = 100 + fam_idx * 1000 + i * 12
                rows.append({
                    "case_id": f"{g}-{label}-{i}",
                    "replay_group": g,
                    "detector_choice": label,
                    "source_t0_s": t0,
                    "clip_start_s": t0 - 3,
                    "clip_end_s": t0 + 1.5,
                    "clip_file": f"{g}-{label}-{i}.mp4",
                    "focus_hint": "Follow the outlined blue car",
                })
    return rows


def test_40_case_blinded_packets_and_20_shared_withheld_trigger_labels():
    rows = manifest()
    p = prepare_packets(rows)
    assert p == prepare_packets(rows)
    assert len(p["primary_packets"]) == 40
    assert len(p["secondary_packets"]) == 20
    assert p["private_map"]["secondary_ids"] == sorted(
        q["review_id"] for q in p["secondary_packets"]
    )
    assert len({q["review_id"] for q in p["primary_packets"]}) == 40
    assert {q["review_id"] for q in p["secondary_packets"]}.issubset(
        {q["review_id"] for q in p["primary_packets"]}
    )
    mapping = p["private_map"]["cases"]
    assert Counter(m["detector_choice"] for m in mapping.values()) == {
        "challenge": 15, "shadow": 15, "unclear": 10
    }
    assert len({m["replay_group"] for m in mapping.values()}) >= 3
    for pkt in p["primary_packets"]:
        assert set(pkt) == {
            "review_id", "clip_file", "clip_duration_s", "focus_hint"
        }
        assert pkt["clip_file"].startswith(pkt["review_id"] + ".")
        assert "source_t0_s" not in str(pkt)
        assert "detector_choice" not in str(pkt)
        assert "replay_group" not in str(pkt)
    # Blind reviewer cannot infer trigger location or rule choice from IDs.
    assert all(row["source_t0_s"] != 0 for row in rows)


def test_rejects_single_replay_and_insufficient_choice_strata():
    with pytest.raises(ValueError, match="Need at least 3 replay groups"):
        prepare_packets(manifest(groups=("only",)))
    rows = [x for x in manifest() if x["detector_choice"] != "unclear"]
    with pytest.raises(ValueError, match="Not enough unclear"):
        prepare_packets(rows)


def test_rejects_temporally_dense_cases_despite_enough_raw_rows():
    rows = manifest(groups=("m1", "m2", "m3"))
    for row in rows:
        row["source_t0_s"] = 99
        row["clip_start_s"] = 96
        row["clip_end_s"] = 100.5
    with pytest.raises(ValueError, match="temporal diversity"):
        prepare_packets(rows)


def test_rejects_duplicate_ids_invalid_video_paths_and_future_clip():
    rows = manifest()
    rows[1]["case_id"] = rows[0]["case_id"]
    with pytest.raises(ValueError, match="Duplicate case ID"):
        validate_manifest(rows)
    rows = manifest()
    rows[0]["clip_file"] = "../private.mp4"
    with pytest.raises(ValueError, match="simple"):
        prepare_packets(rows)
    rows = manifest()
    rows[0]["clip_start_s"] = rows[0]["source_t0_s"] + 0.1
    with pytest.raises(ValueError, match="invalid clip"):
        validate_manifest(rows)


def annotations(p, reviewer, ids=None, shift=0.0):
    if ids is None:
        ids = [x["review_id"] for x in p["primary_packets"]]
    return [{
        "review_id": cid, "rater_id": reviewer,
        "choice": "challenge",
        "mark_type": "interval", "earliest_s": 2.1 + shift,
        "latest_s": 2.5 + shift, "confidence": "medium",
        "note": "Could still turn before the final frame",
    } for cid in ids]


def test_human_interval_agreement_detector_lead_and_separate_reviewers():
    p = prepare_packets(manifest())
    b_ids = [x["review_id"] for x in p["secondary_packets"]]
    a = annotations(p, "rater-a")
    b = annotations(p, "rater-b", b_ids, shift=0.1)
    report = evaluate_timings(p["private_map"], a, b)
    assert report["primary_reviews"] == 40
    assert report["shared_reviews"] == 20
    assert report["shared_choice_agreement_rate"] == 1.0
    assert report["both_observable_endpoints_within_0_3s"] == 20
    assert report["median_detector_t0_minus_human_latest_s"] == 0.5
    assert report["candidate_interpretation"] == "fixed_offset_probably_late"
    assert report["primary_detector_readable_choice_compared"] == 30
    assert report["primary_detector_choice_agreement"] == 0.5
    assert report["primary_detector_unclear_recovered_by_human"] == 10
    assert report["primary_detector_unclear_total"] == 10
    assert report["median_detector_lead_by_choice_s"] == {
        "challenge": 0.5, "shadow": 0.5, "unclear": 0.5
    }


def test_indeterminate_marks_cannot_manufacture_timing_agreement():
    p = prepare_packets(manifest())
    a = annotations(p, "rater-a")
    b = annotations(p, "rater-b",
                    [x["review_id"] for x in p["secondary_packets"]])
    for i in range(30):
        a[i]["mark_type"] = "unobservable"
        a[i]["earliest_s"] = None
        a[i]["latest_s"] = None
    result = evaluate_timings(p["private_map"], a, b)
    assert result["primary_unobservable"] == 30
    assert result["candidate_interpretation"] == "insufficient_observable_windows"
    assert result["both_observable_endpoints_within_0_3s"] <= 10


def test_future_mark_invalid_conflicting_reviewer_ids_or_duplicate_id():
    p = prepare_packets(manifest())
    a = annotations(p, "rater-a")
    invalid = copy.deepcopy(a)
    invalid[0]["latest_s"] = 8
    with pytest.raises(ValueError, match="invalid commitment interval"):
        validate_reviews(invalid, p["private_map"])
    invalid = copy.deepcopy(a)
    invalid[0]["earliest_s"] = float("nan")
    with pytest.raises(ValueError, match="invalid commitment interval"):
        validate_reviews(invalid, p["private_map"])
    with pytest.raises(ValueError, match="Duplicate review ID"):
        validate_reviews([a[0], a[0]], p["private_map"])
    with pytest.raises(ValueError, match="only one reviewer"):
        validate_reviews([a[0], {**a[1], "rater_id": "rater-b"}],
                         p["private_map"])
    with pytest.raises(ValueError, match="different reviewer codes"):
        evaluate_timings(p["private_map"], a, annotations(p, "rater-a"))


def test_secondary_rater_cannot_silently_switch_to_cherry_picked_twenty_clips():
    p = prepare_packets(manifest())
    a = annotations(p, "rater-a")
    chosen = {x["review_id"] for x in p["secondary_packets"]}
    unassigned = next(x["review_id"] for x in p["primary_packets"]
                      if x["review_id"] not in chosen)
    b = annotations(p, "rater-b", sorted(chosen))
    b[-1]["review_id"] = unassigned
    with pytest.raises(ValueError, match="predefined 20"):
        evaluate_timings(p["private_map"], a, b)

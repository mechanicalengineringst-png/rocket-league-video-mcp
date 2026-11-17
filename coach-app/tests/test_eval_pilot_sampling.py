"""Keep coverage-first pilot honest about missed situations and match dependence."""
import copy
from collections import Counter, defaultdict

import pytest

from evaluation.pilot import DEFAULT_SITUATIONS, select_pilot


def candidate(group, situation, origin, idx):
    # All events spaced generously; offset group to avoid same time across
    # groups being accidentally conflated as the same play.
    t0 = 100.0 + idx * 7.0 + DEFAULT_SITUATIONS.index(situation) * 1050
    cid = f"{group}-{situation}-{origin}-{idx}"
    case = {
        "case_id": cid, "replay_group": group, "mode": "2v2",
        "situation_type": situation, "t0": t0,
        "pre_decision_evidence": [{
            "key": "car_pos",
            "claim": "Observed player position; tactical context otherwise unknown.",
            "event_time_s": t0 - 0.03,
            "finalized_through_s": t0 - 0.03,
            "source": "replay", "source_quality": "high",
        }],
    }
    return case, {"case_id": cid, "origin": origin}


def pool(groups=("m1", "m2", "m3", "m4"), each=5):
    cases, origins = [], []
    for group in groups:
        for situation in DEFAULT_SITUATIONS:
            for origin in ("detector", "independent_time_sample"):
                for idx in range(each):
                    a, b = candidate(group, situation, origin, idx)
                    # Avoid the same frame for two kinds of samples.
                    if origin == "independent_time_sample":
                        a["t0"] += 3.0
                        for ev in a["pre_decision_evidence"]:
                            ev["event_time_s"] += 3.0
                            ev["finalized_through_s"] += 3.0
                    cases.append(a)
                    origins.append(b)
    return cases, origins


def test_selects_60_balanced_cases_across_multiple_matches_and_origins():
    cases, manifest = pool()
    result = select_pilot(cases, manifest, per_situation=20)
    assert result["total"] == 60
    assert len(result["case_ids"]) == 60
    assert len(set(result["case_ids"])) == 60
    assert len(result["match_groups"]) >= 3
    assert sum(result["cases_per_group"].values()) == 60
    assert all(result["per_situation"][family] ==
               {"detector": 10, "independent_time_sample": 10}
               for family in DEFAULT_SITUATIONS)

    by_id = {c["case_id"]: c for c in cases}
    by_group = defaultdict(list)
    for cid in result["case_ids"]:
        row = by_id[cid]
        by_group[row["replay_group"]].append(row["t0"])
    for times in by_group.values():
        sorted_times = sorted(times)
        assert all(b - a >= 5 for a, b in zip(sorted_times, sorted_times[1:]))

    assert result == select_pilot(cases, manifest, per_situation=20)


def test_one_replay_does_not_qualify_as_a_multi_match_coaching_benchmark():
    cases, manifest = pool(groups=("only-match",), each=15)
    with pytest.raises(ValueError, match="Insufficient distinct replay groups"):
        select_pilot(cases, manifest, per_situation=20)


def test_detector_only_selection_is_rejected_not_silently_treated_as_coverage():
    cases, manifest = pool()
    for entry in manifest:
        entry["origin"] = "detector"
    with pytest.raises(ValueError, match="independent_time_sample"):
        select_pilot(cases, manifest, per_situation=20)


def test_missing_independent_selection_provenance_fails_closed():
    cases, manifest = pool()
    with pytest.raises(ValueError, match="Missing selection provenance"):
        select_pilot(cases, manifest[:-1], per_situation=20)


def test_malformed_provenance_and_bad_sample_settings_fail_closed():
    cases, manifest = pool()
    manifest[0] = {"case_id": manifest[0]["case_id"], "origin": "manual"}
    with pytest.raises(ValueError, match="invalid selection origin"):
        select_pilot(cases, manifest)
    cases, manifest = pool()
    with pytest.raises(ValueError, match="positive even integer"):
        select_pilot(cases, manifest, per_situation=19)
    with pytest.raises(ValueError, match="min_replay_groups"):
        select_pilot(cases, manifest, min_replay_groups=1)


def test_temporally_duplicate_cases_not_counted_as_independent_decisions():
    cases, manifest = pool(groups=("m1", "m2", "m3"), each=4)
    # Collapse all the moments within each match to the same timestamp.
    for case in cases:
        case["t0"] = 300.0
        case["pre_decision_evidence"][0]["event_time_s"] = 299.95
        case["pre_decision_evidence"][0]["finalized_through_s"] = 299.95
    with pytest.raises(ValueError, match="Temporal de-duplication exhausted"):
        select_pilot(cases, manifest, per_situation=6)


def test_candidate_cannot_contain_future_observations_even_if_marked_control():
    cases, manifest = pool()
    cases[0] = copy.deepcopy(cases[0])
    cases[0]["pre_decision_evidence"][0]["finalized_through_s"] = cases[0]["t0"] + 1
    with pytest.raises(ValueError, match="post-decision-derived"):
        select_pilot(cases, manifest)


def test_provenance_stays_coordinator_only_not_in_reviewer_packets():
    cases, manifest = pool()
    result = select_pilot(cases, manifest)
    assert "selection_manifest" not in result
    assert "labels" not in result
    assert not any("origin" in str(cid) for cid in result["case_ids"])

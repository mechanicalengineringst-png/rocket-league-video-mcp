"""Test DecisionCase extraction and evaluation against real match replay."""
import os
from pathlib import Path
import pytest

from coach_app.subtr_replays import parse_subtr_replay
from coach_app.decision_cases import (
    extract_kickoff_decision_cases,
    extract_first_man_challenge_cases,
    extract_last_man_defense_cases,
    extract_all_decision_cases,
)
from coach_app.decision_evaluation import (
    evaluate_decision_case_heuristics,
    evaluate_decision_case_llm_mock,
)


def get_replay_dir() -> Path:
    env_dir = os.getenv("RL_REPLAY_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p
    # Standard local gaming directory fallback
    local_demos = Path.home() / "Documents" / "My Games" / "Rocket League" / "TAGame" / "DemosEpic"
    if local_demos.is_dir():
        return local_demos
    return Path("./fixtures/replays")


def test_real_replay_decision_case_extraction_and_evaluation():
    replay_dir = get_replay_dir()
    replay_path = replay_dir / "23A661D44DBC5964B0718DBC5F956A33.replay"
    if not replay_path.exists():
        pytest.skip(f"Real replay fixture not found at {replay_path}. Set RL_REPLAY_DIR to run real-replay tests.")

    # The native decoder is optional in standard GitHub CI. Only require it
    # when the actual binary .replay fixture exists for this integration test.
    subtr_actor = pytest.importorskip("subtr_actor", reason="native replay decoder unavailable")
    # Extract native raw events from subtr-actor
    raw_event_data = subtr_actor.get_stats_events(str(replay_path))
    raw_events = raw_event_data.get("events", [])
    assert len(raw_events) > 1000

    # Parse normalized replay payload
    payload = parse_subtr_replay(replay_path)
    assert len(payload["players"]) == 4

    # 1. Kickoff decision cases
    kickoff_cases = extract_kickoff_decision_cases(payload, raw_events)
    assert len(kickoff_cases) >= 5, f"Expected at least 5 kickoff cases, got {len(kickoff_cases)}"

    for kc in kickoff_cases:
        pre_ev = kc.pre_decision_evidence()
        assert len(pre_ev) >= 2
        # Check that post-decision outcome is quarantined
        outcomes = kc.post_decision_outcomes()
        for o in outcomes:
            assert o.kind == "post_decision_outcome"

        # Evaluate with Approach A
        finding = evaluate_decision_case_heuristics(kc)
        if finding:
            assert finding["type"] == "tradeoff_consideration"
            assert finding["assessment"] == "tactical_hypothesis"
            # Admissibility check: cited evidence must be strictly pre-decision
            kc.validate_admissibility(finding["cited_evidence"])

    # 2. First-man challenge decision cases
    challenge_cases = extract_first_man_challenge_cases(payload, raw_events)
    assert len(challenge_cases) >= 5, f"Expected at least 5 challenge cases, got {len(challenge_cases)}"

    for cc in challenge_cases:
        pre_ev = cc.pre_decision_evidence()
        assert len(pre_ev) >= 1
        finding = evaluate_decision_case_heuristics(cc)
        if finding:
            assert finding["type"] in ("depth_observation", "tactical_risk")
            cc.validate_admissibility(finding["cited_evidence"])

    # 3. Last-man defense decision cases
    lastman_cases = extract_last_man_defense_cases(payload, raw_events)
    assert len(lastman_cases) >= 1, f"Expected at least 1 last-man defense case, got {len(lastman_cases)}"

    for lmc in lastman_cases:
        pre_ev = lmc.pre_decision_evidence()
        assert len(pre_ev) >= 2
        finding = evaluate_decision_case_heuristics(lmc)
        if finding:
            assert finding["type"] in ("contextual_advice", "tactical_positioning")
            lmc.validate_admissibility(finding["cited_evidence"])

    # 4. Approach B: LLM mock evaluation on a sampled case
    sample_case = kickoff_cases[0]
    llm_res = evaluate_decision_case_llm_mock(sample_case)
    assert llm_res["mode"] == "llm_structured_evaluation"
    assert llm_res["prompt_token_estimate"] > 50
    assert len(llm_res["verified_evidence_citations"]) >= 1

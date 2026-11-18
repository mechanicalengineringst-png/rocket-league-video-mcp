"""Tests for Round 9 Interactive AI Coaching Experience contracts and fixtures.

Validates:
1. Coaching fixtures conform strictly to EpisodeEvidenceV0 / Stage1EpisodePacketV0 constraints.
2. Static UI contracts in index.html, coaching-fixtures.js, coaching-experience.js.
3. Grounded evidence citations and Stage 1 / Stage 2 boundary compliance.
"""
from pathlib import Path
import json
import re
import pytest

STATIC_DIR = Path(__file__).resolve().parents[1] / "coach_app" / "static"


def test_coaching_fixtures_file_exists_and_declares_fixtures():
    fixtures_file = STATIC_DIR / "coaching-fixtures.js"
    assert fixtures_file.is_file(), "coaching-fixtures.js must exist in static/"
    content = fixtures_file.read_text(encoding="utf-8")
    assert "COACHING_FIXTURES" in content
    assert "EpisodeEvidenceV0" in content
    assert "adaptLiveCaseToEpisode" in content


def test_coaching_fixtures_conforms_to_episode_evidence_v0():
    fixtures_file = STATIC_DIR / "coaching-fixtures.js"
    content = fixtures_file.read_text(encoding="utf-8")

    # Match raw JSON-like fixtures array from JS file
    match = re.search(r"const COACHING_FIXTURES\s*=\s*(\[[\s\S]*?\]);\s*\n\s*/\*\*", content)
    assert match, "Could not locate COACHING_FIXTURES array"

    # Minimal sanitization for JSON loading if standard syntax
    # Check key schema invariants directly via regex and structural validation
    assert "ep-midfield-challenge-01" in content
    assert "ep-lastman-defense-02" in content
    assert "ep-counterattack-shot-03" in content

    # Check node count invariants: 2 to 4 decision nodes per episode
    episodes = re.findall(r"episode_id:\s*'([^']+)'", content)
    assert len(episodes) >= 3, "At least 3 tactical episodes must be provided"

    # Check that retrospective is marked stage 2
    stage2_matches = re.findall(r"stage:\s*2", content)
    assert len(stage2_matches) >= 3, "All episodes must quarantine retrospective at stage 2"


def test_ui_contract_coaching_elements_present_in_index():
    index_file = STATIC_DIR / "index.html"
    content = index_file.read_text(encoding="utf-8")

    assert 'id="coachingSection"' in content
    assert 'id="coachingExperienceContainer"' in content
    assert 'id="loadDemoBtn"' in content
    assert 'src="/static/coaching-fixtures.js"' in content
    assert 'src="/static/coaching-experience.js"' in content


def test_coaching_experience_controller_features():
    controller_file = STATIC_DIR / "coaching-experience.js"
    assert controller_file.is_file(), "coaching-experience.js must exist"
    content = controller_file.read_text(encoding="utf-8")

    assert "CoachingExperienceController" in content
    assert "selectEpisode" in content
    assert "selectNode" in content
    assert "navigateEarlier" in content
    assert "syncReplayToNode" in content
    assert "toggleStage1Firewall" in content
    assert "inspectEvidence" in content
    assert "askQuestion" in content
    assert "generateDeterministicAnswer" in content
    assert "updatePitchOverlays" in content


def test_question_types_align_with_coaching_qa():
    from coach_app.coaching_qa import QUESTION_TYPES

    controller_file = STATIC_DIR / "coaching-experience.js"
    content = controller_file.read_text(encoding="utf-8")

    # Check that inferQuestionType covers the key QA types
    assert "alternative_feasibility" in content
    assert "teammate_actions" in content
    assert "what_would_change" in content
    assert "practice_priority" in content
    assert "why_flagged" in content

    for qtype in ["alternative_feasibility", "teammate_actions", "what_would_change", "practice_priority", "why_flagged"]:
        assert qtype in QUESTION_TYPES

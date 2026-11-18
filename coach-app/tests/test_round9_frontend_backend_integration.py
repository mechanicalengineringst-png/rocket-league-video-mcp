"""Round 9 live/fixture separation and endpoint contract regressions."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "coach_app" / "static"


def test_live_replay_uses_stage1_lesson_not_synthetic_episode_adapter():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "fetch('/api/coach/lesson'" in app
    assert "makeCoachLessonRequest" in app
    assert "addVerifiedLesson(lesson, payload, c)" in app
    assert "resetForReplay(Boolean(opts.demo))" in app
    assert "adaptLiveCaseToEpisode(c, replay)" not in app


def test_followup_is_local_evidence_navigation_not_made_up_chat():
    ui = (STATIC / "coaching-experience.js").read_text(encoding="utf-8")
    assert "fetch('/api/coach/followup'" in ui
    assert "CoachFollowupV0" in ui
    assert "local_evidence_navigation" in ui
    assert "not AI conversation" in ui
    assert "fetch('/api/coach-question'" not in ui
    assert "const fallback = this.generateDeterministicAnswer" not in ui
    assert "With 24 boost" not in ui


def test_evidence_inspector_fetches_verified_sources_fail_closed():
    ui = (STATIC / "coaching-experience.js").read_text(encoding="utf-8")
    assert "fetch('/api/coach/evidence'" in ui
    assert "CoachEvidenceLookupV0" in ui
    assert "retrospective_exposed !== false" in ui
    assert "Citation missing from reconstructed episode" in ui
    assert "value:'Unavailable'" in ui
    assert "value: 'Telemetric constraint'" not in ui


def test_lesson_backend_is_uncalibrated_and_demo_explicit():
    ui = (STATIC / "coaching-experience.js").read_text(encoding="utf-8")
    assert "SIMULATED DEMONSTRATION" in ui
    assert "No expert-calibrated takeaway yet" in ui
    assert "Server evidence is limited to decision-time data" in ui
    assert "if (!this.isDemo) return;" in ui
    assert "escapeHTML(text)" in ui

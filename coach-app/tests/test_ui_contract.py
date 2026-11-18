"""Small static contract checks for the browser UI.

These tests do not substitute for real browser QA; they catch missing controls
before a branch with new JavaScript selectors is released.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / "coach_app" / "static"


def test_browser_controls_exist_for_all_js_id_references():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "app.js").read_text(encoding="utf-8")

    page_ids = set(re.findall(r'\bid="([a-zA-Z][a-zA-Z0-9_-]*)"', html))
    script_refs = set(re.findall(r"\$\('([a-zA-Z][a-zA-Z0-9_-]*)'\)", js))

    assert script_refs <= page_ids, f"Missing HTML IDs: {script_refs - page_ids}"


def test_replay_view_discloses_inference_limits_and_keeps_player_selector():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="playerSelect"' in html
    assert "Who are we coaching?" in html
    assert 'id="showFacing"' in html
    assert 'id="showTrail"' in html
    assert 'id="showBallTrail"' in html
    assert 'id="sceneInspector"' in html
    assert "not car facing" not in html.lower()  # white yaw tip and velocity now differ
    assert "playerMappingVerified" in js
    assert "videoAligned:false" in js


def test_video_panel_never_claims_replay_contains_video():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "A .replay contains game data, not video" in html
    assert 'type="file" accept="video/mp4,video/webm,video/ogg"' in html
    assert 'id="alignVideo"' in html
    assert 'id="videoOffset"' in html


def test_native_replay_load_and_seek_are_explicit_and_not_websocket_probe_driven():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'id="companionReplaySelector"' in html
    assert 'id="companionLoadBtn"' in html
    assert 'id="companionMatchConfirmed"' in html
    assert 'id="companionCommandStatus"' in html
    assert 'id="companionOptIn"' in html
    assert "tcp_command_port_open" in js
    assert "websocket_probe_port_open" in js
    assert "nativeTcpPortReady" in js
    assert "sendNativeCompanionCommand('LoadReplay'" in js
    assert "sendNativeCompanionCommand('SeekReplay'" in js
    assert "companionMatchConfirmed" in js
    assert "A new browser replay is NOT proof" in js
    assert "transmission is NOT execution" in js


def test_decision_lens_is_real_interactive_review_not_a_fake_tactical_verdict():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    source = (ROOT / "decision-lens.js").read_text(encoding="utf-8")
    coach = (ROOT / "coaching-experience.js").read_text(encoding="utf-8")

    assert '<script src="/static/decision-lens.js"></script>' in html
    assert '<details class="panel decision-lens" id="decisionLensPanel">' in html
    for control in (
        "lensPinBtn", "lensApproachBtn", "lensDecisionBtn",
        "lensLoopBtn", "lensRevealBtn", "lensAfterBtn",
        "lensClearBtn", "lensMetrics", "lensStatus",
    ):
        assert f'id="{control}"' in html
        assert control in js
    assert 'replay-lab:coaching-moment' in coach
    assert 'replay-lab:coaching-moment' in js
    assert 'pinDecisionLens' in js
    assert 'loopNext' in js
    assert 'renderDecisionLensOverlay' in js
    assert "lens.revealed&&w.after" in js
    assert "last recorded" in source.lower() or "last recorded" in source[:800].lower()
    assert "predictionsMade:false" in source
    assert "coachingGradeAssigned:false" in source
    assert 'future_recording_separate' in source
    assert "outcome" not in html.split('id="decisionLensPanel">',1)[1].split('</details>',1)[0].lower()


def test_real_model_coaching_ui_has_explicit_consent_and_no_fake_fallback():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    model = (ROOT / "model-coaching.js").read_text(encoding="utf-8")
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    coach = (ROOT / "coaching-experience.js").read_text(encoding="utf-8")
    assert '<script src="/static/model-coaching.js"></script>' in html
    for name in (
        "modelCoachPanel", "modelCoachRunBtn", "modelCoachConsent",
        "modelCoachRefreshBtn", "modelCoachStatus", "modelCoachReadiness",
        "modelCoachSelected", "modelCoachResults", "modelCoachEvidence",
        "modelCoachExportBtn",
    ):
        assert f'id="{name}"' in html
    assert "ReplayLabModelCoaching.ModelCoachingController" in app
    assert "mode:'model', experimental_tactical_v1:false" in model
    assert "future_outcomes_used !== false" in model
    assert "semantic_tactical_accuracy_verified !== false" in model
    assert "No model request has been made" in model
    assert "source" in model.lower() and "evidence_refs" in model
    assert "model_coaching_reviews" in coach
    assert "candidate_id" in coach and "episodeRequest" in coach


def test_manual_overlooked_moment_can_be_requested_without_a_model():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    manual = (ROOT / "manual-review.js").read_text(encoding="utf-8")
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    coach = (ROOT / "coaching-experience.js").read_text(encoding="utf-8")
    assert '<script src="/static/manual-review.js"></script>' in html
    assert 'id="lensManualReviewBtn"' in html
    assert 'id="lensManualReviewStatus"' in html
    assert "ReplayLabManualReview.ManualReviewController" in app
    assert "buildManualRequest" in manual
    assert "mode:'deterministic',experimental_tactical_v1:false" in manual
    assert "ManualReviewController" in manual
    assert "This selection is not a confirmed mistake." in manual
    assert "selection_source: manuallySelected ? 'manual' : 'automatic'" in coach
    assert "defer_activation: true" in coach
    assert "ownerPinOpen" in coach
    assert "manual" in coach
    # A manual source-only review must never automatically pay a provider.
    assert "mode:'model'" not in manual
    assert "mode: 'model'" not in manual

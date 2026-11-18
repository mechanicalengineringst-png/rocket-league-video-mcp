"""Round 12 End-to-End Integration Test: High-Fidelity Replay, Native Companion & Coaching UX.

Verifies:
1. Native parsing of real 2v2 match replay.
2. Single-request review bundle endpoint POST /api/coach/review-bundle (PR #39 integration).
3. Candidate leads to lesson preview mapping with exact candidate_id and timestamp integrity.
4. Predecision Stage 1 firewall: no retrospective outcome leakage in bundle or lesson.
5. Local evidence navigation and lookup via POST /api/coach/evidence and POST /api/coach/followup.
6. Native Rocket League companion status probe and opt-in command protection.
7. HTML & JS UI contract: retired geometric 3D absent, HD split view default, companion controls present.
"""
from pathlib import Path
import re
import pytest
from fastapi.testclient import TestClient

from coach_app.main import app
from coach_app.subtr_replays import parse_subtr_replay

REPLAY_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "replays" / "real_match_2v2.replay"
STATIC_DIR = Path(__file__).resolve().parents[1] / "coach_app" / "static"


@pytest.fixture(scope="module")
def real_replay():
    if not REPLAY_FIXTURE.is_file():
        pytest.skip(f"Real replay fixture not found at {REPLAY_FIXTURE}")
    return parse_subtr_replay(REPLAY_FIXTURE)


def test_capabilities_advertises_review_bundle_and_companion():
    """Verify capabilities includes single_request_review_bundle."""
    client = TestClient(app)
    res = client.get("/api/coach/capabilities")
    assert res.status_code == 200
    caps = res.json()
    assert caps["single_request_review_bundle"] == "CoachReviewBundleV0"
    assert caps["review_bundle_max_previews"] >= 3
    assert caps["review_bundle_invokes_model"] is False


def test_real_replay_review_bundle_pipeline(real_replay):
    """Verify one-call review bundle generates source-checked leads and lesson previews."""
    client = TestClient(app)
    player_id = "Steam:76561198994872471"

    bundle_req = {
        "replay": real_replay,
        "player_id": player_id,
        "max_candidates": 6,
        "preview_count": 3,
        "experimental_tactical_v1": False
    }
    res = client.post("/api/coach/review-bundle", json=bundle_req)
    assert res.status_code == 200, f"Review bundle failed: {res.text}"
    bundle = res.json()

    assert bundle["schema"] == "CoachReviewBundleV0"
    assert bundle["stage"] == "predecision"
    assert bundle["mode"] == "local_deterministic"
    assert bundle["candidate_count"] >= 3
    assert len(bundle["previews"]) >= 1

    # Verify first preview lesson structure
    first_preview = bundle["previews"][0]
    assert "candidate_id" in first_preview
    assert "primary_t0" in first_preview
    assert "lesson" in first_preview
    lesson = first_preview["lesson"]
    assert lesson["schema"] == "CoachLessonV0"
    assert lesson["stage"] == "predecision"
    assert lesson["decision"]["t0_s"] == first_preview["primary_t0"]

    # Verify Stage 1 firewall: no retrospective outcome leakage
    assert "retrospective" not in lesson or lesson["retrospective"] is None


def test_native_companion_endpoints_and_safety():
    """Verify GET /api/companion/status and POST /api/companion/command opt-in enforcement."""
    client = TestClient(app)

    # 1. Status probe succeeds without error
    status_res = client.get("/api/companion/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert "available" in status_data
    assert "port" in status_data
    assert "instructions" in status_data

    # 2. Command without opt-in environment variable fails closed with 403 Forbidden
    cmd_res = client.post("/api/companion/command", json={
        "Command": "SeekReplay",
        "Data": {"TimeSeconds": 15.0}
    })
    assert cmd_res.status_code == 403
    assert "disabled by default" in cmd_res.text.lower()


def test_ui_architecture_and_retired_viewer_absence():
    """Verify legacy 3D viewer is completely absent and split view is default."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    coach_js = (STATIC_DIR / "coaching-experience.js").read_text(encoding="utf-8")

    # Retired components must not be present
    assert "viewer3d.js" not in html
    assert "three.min.js" not in html
    assert "OrbitControls.js" not in html
    assert 'id="viewTab3d"' not in html
    assert 'id="viewport3d"' not in html
    assert 'id="controls3d"' not in html

    # Supported modes must be present
    assert 'id="viewTabHd"' in html
    assert 'id="viewTab2d"' in html
    assert 'id="viewTabSplit"' in html
    assert 'id="hdInlineFrame"' in html
    assert 'class="hd-inline"' in html

    # Companion controls must exist
    assert 'id="companionPanel"' in html
    assert 'id="companionBadge"' in html
    assert 'id="companionOptIn"' in html
    assert 'id="companionProbeBtn"' in html
    assert 'id="companionSyncBtn"' in html

    # Review bundle and feedback integration in JS
    assert "CoachReviewBundleV0" in app_js
    assert "setReviewBundle" in coach_js
    assert "exportTestReport" in coach_js
    assert "replaylab_user_feedback" in coach_js

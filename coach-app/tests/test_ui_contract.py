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

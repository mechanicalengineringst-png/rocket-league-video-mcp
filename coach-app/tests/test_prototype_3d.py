"""Tests for Replay Lab 3D interactive viewer prototype and tactical improvements."""
import re
from pathlib import Path
import pytest

from coach_app.coaching import find_review_candidates
from coach_app.subtr_replays import normalize_subtr_replay

STATIC_DIR = Path(__file__).resolve().parents[1] / "coach_app" / "static"


def test_3d_static_assets_exist():
    assert (STATIC_DIR / "vendor" / "three.min.js").is_file()
    assert (STATIC_DIR / "vendor" / "OrbitControls.js").is_file()
    assert (STATIC_DIR / "viewer3d.js").is_file()

    viewer_js = (STATIC_DIR / "viewer3d.js").read_text(encoding="utf-8")
    assert "class Viewer3D" in viewer_js
    assert "BOOST_PADS" in viewer_js
    assert "global.Viewer3D = Viewer3D;" in viewer_js


def test_boost_pad_counts_and_coordinates():
    viewer_js = (STATIC_DIR / "viewer3d.js").read_text(encoding="utf-8")
    # Extract boost pads array
    pads = re.findall(r'\{\s*x:\s*(-?\d+),\s*y:\s*(-?\d+),\s*z:\s*(-?\d+),\s*big:\s*(true|false)', viewer_js)
    assert len(pads) == 34, f"Expected 34 pads, found {len(pads)}"

    big_count = sum(1 for p in pads if p[3] == "true")
    small_count = sum(1 for p in pads if p[3] == "false")
    assert big_count == 6
    assert small_count == 28

    for x_s, y_s, z_s, _ in pads:
        x, y, z = float(x_s), float(y_s), float(z_s)
        assert -4096 <= x <= 4096
        assert -5120 <= y <= 5120
        assert 0 <= z <= 100


def test_kickoff_cheat_is_not_flagged_as_accidental_overlap():
    players = [
        {'id': 'p1', 'name': 'Player 1', 'team': 'blue'},
        {'id': 'p2', 'name': 'Player 2', 'team': 'blue'},
        {'id': 'opp', 'name': 'Opponent', 'team': 'orange'}
    ]
    # At t = 4.0: Kickoff event occurs.
    # At t = 5.0 (1s after kickoff): Teammates are close to each other & ball (kickoff cheat).
    # At t = 25.0: Teammates are close again (mid-game accidental overlap).
    frames = [
        {'t': 4.0, 'ball': {'x': 0, 'y': 0, 'z': 93}, 'cars': {
            'p1': {'x': -256, 'y': -3840, 'z': 17, 'boost': 33},
            'p2': {'x': 0, 'y': -4600, 'z': 17, 'boost': 33},
            'opp': {'x': 0, 'y': 4600, 'z': 17, 'boost': 33}
        }},
        {'t': 5.0, 'ball': {'x': 0, 'y': 200, 'z': 93}, 'cars': {
            'p1': {'x': 0, 'y': 100, 'z': 17, 'boost': 50},
            'p2': {'x': 100, 'y': 0, 'z': 17, 'boost': 50}, # close cheat!
            'opp': {'x': 0, 'y': 1000, 'z': 17, 'boost': 50}
        }},
        {'t': 25.0, 'ball': {'x': -1000, 'y': 500, 'z': 93}, 'cars': {
            'p1': {'x': -900, 'y': 450, 'z': 17, 'boost': 50},
            'p2': {'x': -850, 'y': 400, 'z': 17, 'boost': 50}, # mid-game double commit!
            'opp': {'x': 0, 'y': 3000, 'z': 17, 'boost': 50}
        }}
    ]
    events = [
        {'type': 'kickoff', 't': 4.0}
    ]
    replay = {'players': players, 'frames': frames, 'events': events, 'duration': 30.0}

    findings = find_review_candidates(replay, 'p1')
    # The cheat at t = 5.0 should be excluded; only the mid-game overlap at t = 25.0 should be present.
    overlap_times = [f['t'] for f in findings if f['type'] == 'overlap']
    assert 5.0 not in overlap_times, "Kickoff cheat was incorrectly flagged as an overlap!"
    assert 25.0 in overlap_times, "Legitimate mid-game double commit was not flagged."


def test_ui_contract_uses_hd_replay_as_primary_3d_viewer():
    """The old geometric renderer stays archived, not mounted in the live UI."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    bridge = (STATIC_DIR / "hd-bridge.js").read_text(encoding="utf-8")
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'id="hdInlineFrame"' in html
    assert 'src="/hd?embedded=1"' in html
    assert 'id="viewTabHd"' in html
    assert 'id="viewTab2d"' in html
    assert 'id="viewTabSplit"' in html
    assert 'id="viewport3d"' not in html
    assert 'id="viewTab3d"' not in html
    assert 'id="controls3d"' not in html
    assert 'viewer3d.js' not in html
    assert 'id="boostPadsLayer"' in html
    assert 'id="showBoostPads"' in html
    assert 'replay-lab:sync-state' in bridge and 'replay-lab:sync-state' in app
    assert 'replay-lab:replay-ready' in bridge and 'replay-lab:replay-ready' in app

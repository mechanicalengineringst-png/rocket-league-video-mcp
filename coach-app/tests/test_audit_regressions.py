"""Regression tests for defects found in the 2026-11-16 audit.

Every synthetic case below mirrors something observed in real replays decoded with
subtr-actor-py 1.5.1. The last test runs the real decoder when sample replays are
available: set COACH_SAMPLE_REPLAY_DIR to a folder of .replay files.
"""
import json
import math
import os
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from coach_app import main
from coach_app.coaching import compact_game_states, find_review_candidates
from coach_app.subtr_replays import _forward, _player_key, normalize_subtr_replay, parse_subtr_replay

GH = ['Ball - position x', 'Ball - position y', 'Ball - position z',
      'Ball - linear velocity x', 'Ball - linear velocity y', 'Ball - linear velocity z',
      'current time', 'seconds remaining']
PH = ['position x', 'position y', 'position z',
      'linear velocity x', 'linear velocity y', 'linear velocity z',
      'rotation x', 'rotation y', 'rotation z',
      'boost level (raw replay units)', 'any_jump_active']
BLUE, ORANGE = {'Epic': 'blue-1'}, {'Epic': 'orange-1'}
ZERO_CAR = [0.] * 11  # what subtr-actor emits when the car does not exist


def car(x, y, z=17., vel=(100., 0., 0.), rot=(0., 0., 0.), boost=85.):
    return [x, y, z, *vel, *rot, boost, 0.]


def build(rows, extra_events=(), headers=None, clock=None):
    """rows: list of (time, blue_car, orange_car). Blue is the first ndarray block."""
    meta = {'column_headers': {'global_headers': GH, 'player_headers': PH},
            'replay_meta': {'team_zero': [{'name': 'Blue', 'remote_id': BLUE}],
                            'team_one': [{'name': 'Orange', 'remote_id': ORANGE}],
                            'all_headers': headers or []}}
    matrix = np.array([[0., 0., 93., 0., 0., 0., t, (clock[i] if clock else 300.)] + b + o
                       for i, (t, b, o) in enumerate(rows)], dtype=np.float32)
    spawn = lambda pid, pos, t: {'meta': {'stream': 'boost_respawn', 'timing': {'time': t}},
                                 'payload': {'payload': {'kind': 'kickoff', 'player_id': pid,
                                                         'player_position': pos, 'time': t}}}
    events = [spawn(BLUE, [-256, -3840, 17], 4.0), spawn(ORANGE, [256, 3840, 17], 4.1), *extra_events]
    return meta, matrix, {'events': events}


def test_absent_car_is_omitted_instead_of_drawn_at_midfield():
    live_b, live_o = car(-256, -3840), car(256, 3840)
    rows = [(4.0, live_b, live_o), (4.1, live_b, live_o),
            (4.2, ZERO_CAR, ZERO_CAR),      # between a goal and the next kickoff
            (4.3, live_b, live_o)]
    r = normalize_subtr_replay(*build(rows))
    assert len(r['frames']) == 4            # the timeline keeps the stoppage sample...
    assert r['frames'][2]['cars'] == {}     # ...but no car is invented at (0, 0, 0)
    assert r['startTime'] == 4.0


def test_late_first_spawn_still_verifies_player_mapping():
    rows = [(4.0, car(-256, -3840), ZERO_CAR),     # orange has not spawned yet
            (4.1, car(-256, -3840), car(256, 3840)),
            (4.2, car(-250, -3800), car(250, 3800))]
    r = normalize_subtr_replay(*build(rows))
    assert r['playerMappingVerified'] is True
    assert [p['team'] for p in r['players']] == ['blue', 'orange']


def test_forward_vector_is_true_heading_not_euler_z():
    assert _forward(0., 0., math.pi / 2) == [0., 1., 0.]          # flat car: Z is yaw
    # Rolled 180 degrees (upside down, e.g. ceiling or mid-flip) with Euler Z = 90 degrees:
    # the nose actually points the opposite way along Y from what cos/sin(Z) would draw.
    fx, fy, fz = _forward(math.pi, 0., math.pi / 2)
    assert (round(fx, 2), round(fy, 2)) == (0., -1.)
    rows = [(4.0, car(-256, -3840, rot=(math.pi, 0., math.pi / 2)), car(256, 3840)),
            (4.1, car(-256, -3840, rot=(math.pi, 0., math.pi / 2)), car(256, 3840))]
    r = normalize_subtr_replay(*build(rows))
    assert r['frames'][0]['cars']['Epic:blue-1']['forward'][1] == pytest.approx(-1., abs=0.01)


def test_overtime_clock_is_flagged_and_new_match_is_not():
    b, o = car(-256, -3840), car(256, 3840)
    rows = [(float(t), b, o) for t in range(4, 12)]
    r = normalize_subtr_replay(*build(rows, clock=[2, 1, 0, 0, 1, 2, 3, 4]))
    assert [bool(f.get('overtime')) for f in r['frames']] == [False] * 4 + [True] * 4
    r = normalize_subtr_replay(*build(rows, clock=[12, 11, 300, 299, 298, 297, 296, 295]))
    assert not any(f.get('overtime') for f in r['frames'])


def test_demolished_car_is_flagged_until_it_moves_again():
    dead = car(-400, -4700, vel=(0., 0., 0.))
    b, o = car(-256, -3840), car(256, 3840)
    rows = [(4.0, b, o), (4.1, b, o), (5.0, dead, o), (6.0, dead, o), (7.0, dead, o),
            (9.0, car(-256, -3840), o)]
    demo = {'meta': {'stream': 'demolition', 'timing': {'time': 5.0}, 'primary_player': ORANGE},
            'payload': {'payload': {'time': 5.0, 'attacker': ORANGE, 'victim': BLUE}}}
    r = normalize_subtr_replay(*build(rows, [demo]))
    flags = [bool(f['cars'].get('Epic:blue-1', {}).get('demolished')) for f in r['frames']]
    assert flags == [False, False, True, True, True, False]
    event = next(e for e in r['events'] if e['type'] == 'demolition')
    assert (event['attackerId'], event['victimId']) == ('Epic:orange-1', 'Epic:blue-1')
    assert all('_still' not in c for f in r['frames'] for c in f['cars'].values())


def test_struct_platform_ids_become_short_stable_keys():
    ps = {'PlayStation': {'name': 'Some-Player', 'online_id': '4464720935336384714', 'unknown1': [98, 51]}}
    assert _player_key(ps) == 'PlayStation:4464720935336384714'
    assert _player_key({'PlayStation': {'name': 'Old-Player', 'online_id': '0'}}) == 'PlayStation:Old-Player'
    assert _player_key({'Steam': '7656'}) == 'Steam:7656'


def test_primary_player_from_team_header_in_1v1():
    rows = [(4.0, car(-256, -3840), car(256, 3840)), (4.1, car(-256, -3840), car(256, 3840))]
    r = normalize_subtr_replay(*build(rows, headers=[['PrimaryPlayerTeam', 1], ['TeamSize', 1]]))
    assert (r['primaryTeam'], r['primaryPlayerId']) == ('orange', 'Epic:orange-1')
    r = normalize_subtr_replay(*build(rows))
    assert (r['primaryTeam'], r['primaryPlayerId']) == (None, None)   # never guess silently


def _match(duration=400, dead_teammate=False):
    players = [{'id': 'a', 'name': 'A', 'team': 'blue'}, {'id': 'b', 'name': 'B', 'team': 'blue'},
               {'id': 'c', 'name': 'C', 'team': 'orange'}]
    mate = {'x': 100, 'y': 0, 'z': 17, 'boost': 50, **({'demolished': True} if dead_teammate else {})}
    frames = [{'t': float(t), 'ball': {'x': 0, 'y': 0, 'z': 93},
               'cars': {'a': {'x': 0, 'y': -100, 'z': 17, 'boost': 50}, 'b': mate,
                        'c': {'x': 0, 'y': 3000, 'z': 17, 'boost': 50}}} for t in range(duration)]
    return {'players': players, 'frames': frames, 'duration': duration}


def test_candidates_cover_the_whole_match_and_ignore_demolished_cars():
    found = find_review_candidates(_match(), 'a')
    assert len(found) > 8 and found[-1]['t'] > 350          # used to stop after 8 (~2.5 min)
    assert len(find_review_candidates(_match(), 'a', max_findings=8)) == 8
    assert find_review_candidates(_match(dead_teammate=True), 'a') == []
    assert 'DEMOLISHED' in compact_game_states(_match(dead_teammate=True), 'a', max_frames=2)


client = TestClient(main.app)


def test_cross_origin_writes_and_unknown_hosts_are_rejected(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key-never-sent')
    body = json.dumps({'replay': {}, 'player_id': 'x'})
    # Another website cannot POST here, and a text/plain "simple request" is refused outright.
    r = client.post('/api/ai-review', content=body, headers={'Content-Type': 'text/plain', 'Origin': 'https://evil.example'})
    assert r.status_code == 403
    assert client.post('/api/ai-review', content=body, headers={'Content-Type': 'text/plain'}).status_code == 415
    assert client.post('/api/ai-review', content=body, headers={'Content-Type': 'application/json', 'Origin': 'http://testserver'}).status_code == 422
    assert client.get('/api/health', headers={'Host': 'attacker.example'}).status_code == 400


@pytest.mark.parametrize('model_text', ['[1, 2, 3]', '{"findings": ["oops"]}', '"just a string"', 'not json'])
def test_malformed_model_output_never_becomes_a_500(monkeypatch, model_text):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'candidates': [{'content': {'parts': [{'text': model_text}]}}]}

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return Response()

    import httpx
    monkeypatch.setattr(httpx, 'AsyncClient', Client)
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key-never-sent')
    r = client.post('/api/ai-review', json={'replay': _match(3), 'player_id': 'a'})
    assert r.status_code in (200, 502), r.text


def test_ai_selected_time_uses_only_predecision_window_in_actual_request(monkeypatch):
    # No real Gemini request: inspect the exact body sent by our local endpoint.
    sent_prompts = []

    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'candidates': [{'content': {'parts': [{'text': '{"findings": []}'}]}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def post(self, *args, **kwargs):
            sent_prompts.append(kwargs['json']['contents'][0]['parts'][0]['text'])
            return Response()

    import httpx
    monkeypatch.setattr(httpx, 'AsyncClient', FakeClient)
    monkeypatch.setenv('GEMINI_API_KEY', 'fake-key-not-sent')

    req = {'replay': _match(10), 'player_id': 'a', 'selected_time': 5.0}
    response = client.post('/api/ai-review', json=req)
    assert response.status_code == 200, response.text
    assert response.json()['findings'] == []
    assert len(sent_prompts) == 1
    prompt = sent_prompts[0]
    assert 'three seconds BEFORE and through this time' in prompt
    assert '2.0 |' in prompt and '5.0 |' in prompt
    assert '1.0 |' not in prompt and '6.0 |' not in prompt
    assert '7.0 |' not in prompt and '9.0 |' not in prompt

    # No recent t0 sample: reject *before* making a model call.
    req['selected_time'] = 5.5
    response = client.post('/api/ai-review', json=req)
    assert response.status_code == 422, response.text
    assert len(sent_prompts) == 1


def test_percent_encoded_replay_name_is_decoded(monkeypatch):
    monkeypatch.setattr(main, 'parse_replay_file', lambda path: _match(3) | {'schema': 'rl-coach/0.2'})
    r = client.post('/api/replays', content=b'x' * 64, headers={
        'Content-Type': 'application/octet-stream', 'X-Replay-Name': '%E8%A9%A6%E5%90%88%E2%80%94final.replay'})
    assert r.status_code == 200 and r.json()['replay']['title'] == '\u8a66\u5408\u2014final'


SAMPLES = os.getenv('COACH_SAMPLE_REPLAY_DIR')


@pytest.mark.skipif(not SAMPLES, reason='set COACH_SAMPLE_REPLAY_DIR to run the real decoder')
def test_real_replays_have_no_phantom_cars_and_sane_timelines():
    checked = 0
    for path in sorted(Path(SAMPLES).glob('*.replay')):
        try:
            r = parse_subtr_replay(path)
        except ValueError:
            continue  # training drills / roster changes are rejected explicitly
        checked += 1
        assert r['startTime'] == r['frames'][0]['t'] <= r['duration']
        for f in r['frames']:
            for c in f['cars'].values():
                assert (c['x'], c['y'], c['z']) != (0, 0, 0), (path.name, f['t'])
                assert abs(math.hypot(*c['forward']) - 1) < 0.01
        for p in r['players']:
            assert len(p['id']) < 60 and '{' not in p['id']
    assert checked > 0

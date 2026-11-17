from fastapi.testclient import TestClient
from coach_app.main import app

client=TestClient(app)


def test_health_and_ui():
    assert client.get('/api/health').json()['status']=='ok'
    html=client.get('/')
    assert html.status_code==200
    assert 'REPLAY LAB' in html.text
    assert client.get('/static/app.js').status_code==200


def test_upload_validations():
    r=client.post('/api/replays',headers={'Content-Type':'application/octet-stream','X-Replay-Name':'wrong.txt'},content=b'0'*100)
    assert r.status_code==415
    r=client.post('/api/replays',headers={'Content-Type':'application/octet-stream','X-Replay-Name':'match.replay'},content=b'0'*2)
    assert r.status_code==400


def test_ai_requires_key():
    r=client.post('/api/ai-review',json={'replay':{},'player_id':'foo'})
    assert r.status_code in (503, 422)


def test_original_replay_upload_invokes_parser_without_manual_exports(monkeypatch):
    from coach_app import main

    received = []
    replay = {
        'schema': 'rl-coach/0.2', 'title': 'from-adapter', 'duration': 4,
        'players': [{'id': 'blue', 'name': 'Blue', 'team': 'blue'},
                    {'id': 'orange', 'name': 'Orange', 'team': 'orange'}],
        'frames': [{'t': 4, 'ball': {'x': 0, 'y': 0, 'z': 93},
                    'cars': {'blue': {'x': 0, 'y': -3000, 'z': 17, 'boost': 33},
                             'orange': {'x': 0, 'y': 3000, 'z': 17, 'boost': 33}}}],
    }

    def fake_parser(path):
        received.append(path.read_bytes())
        return replay

    monkeypatch.setattr(main, 'parse_replay_file', fake_parser)
    payload = b'fake-native-replay-test-data' * 4
    response = client.post(
        '/api/replays', headers={
            'Content-Type': 'application/octet-stream',
            'X-Replay-Name': 'my-match.replay',
        }, content=payload,
    )
    assert response.status_code == 200, response.text
    assert received == [payload]
    assert response.json()['replay']['title'] == 'my-match'


def test_native_replay_upload_populates_bounded_contextual_reviews(monkeypatch):
    """All player views are cached during upload; no remote model is called."""
    from coach_app import main

    blue_touch = {
        'source': 'subtr-actor-native-replay', 'playerMappingVerified': True,
        'title': 'match', 'duration': 1.35, 'mode': '2v2',
        'players': [
            {'id': 'a', 'team': 'blue', 'name': 'Blue 1'},
            {'id': 'b', 'team': 'blue', 'name': 'Blue 2'},
            {'id': 'c', 'team': 'orange', 'name': 'Orange 1'},
            {'id': 'd', 'team': 'orange', 'name': 'Orange 2'},
        ],
        'events': [{'type': 'touch', 't': 1.0, 'playerId': 'a'}],
        'frames': [
            {'t': t, 'ball': {'x': 0, 'y': 2100, 'z': 100}, 'cars': {
                'a': {'x': 0, 'y': 1800, 'z': 17, 'boost': 60,
                      'forward': [0, 1, 0], 'velocity': [0, 0, 0]},
                'b': {'x': -1800, 'y': 900, 'z': 17, 'boost': 60},
                'c': {'x': 0, 'y': 4600, 'z': 17, 'boost': 4,
                      'velocity': [120, 0, 0]},
                'd': {'x': 2300, 'y': 3600, 'z': 17, 'boost': 60},
            }} for t in [1.0, 1.35]
        ],
    }
    monkeypatch.setattr(main, 'parse_replay_file', lambda path: blue_touch.copy())
    response = client.post('/api/replays',
        headers={'Content-Type': 'application/octet-stream', 'X-Replay-Name': 'test.replay'},
        content=b'mock-replay-data'*4)
    assert response.status_code == 200, response.text
    reviews = response.json()['replay']['contextualReviews']
    assert set(reviews) == {'a', 'b', 'c', 'd'}
    assert len(reviews['a']) == 1
    assert reviews['a'][0]['kind'] == 'shot_window'
    assert reviews['a'][0]['type'] == 'contextual'
    assert all(len(notes) <= 4 for notes in reviews.values())
    assert response.json()['replay']['title'] == 'test'

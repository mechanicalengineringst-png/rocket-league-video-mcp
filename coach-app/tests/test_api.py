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

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

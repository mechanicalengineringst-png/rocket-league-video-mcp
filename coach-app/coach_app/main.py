"""Local-first FastAPI app. Does not change or expose the existing Cloudflare MCP Worker."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .coaching import compact_game_states, find_review_candidates
from .replays import ReplayParseError, parse_replay_file

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_COACH_BYTES = 2 * 1024 * 1024
STATIC = Path(__file__).parent / 'static'
app = FastAPI(title='Rocket League Replay Coach', version='0.1.0')
app.mount('/static', StaticFiles(directory=STATIC), name='static')


@app.get('/')
def index():
    return FileResponse(STATIC / 'index.html', media_type='text/html')


@app.get('/api/health')
def health():
    return {'status': 'ok', 'mode': 'local-first', 'geminiConfigured': bool(os.getenv('GEMINI_API_KEY'))}


@app.post('/api/replays')
async def upload_replay(request: Request):
    """Validate bounded raw .replay upload; delete it after parsing in a private temp dir."""
    filename = Path(request.headers.get('x-replay-name', 'match.replay')).name
    if not filename.lower().endswith('.replay'):
        raise HTTPException(415, 'Choose a Rocket League .replay file.')
    if request.headers.get('content-type', '').split(';')[0] != 'application/octet-stream':
        raise HTTPException(415, 'Upload the raw replay file (application/octet-stream).')
    size = 0
    with tempfile.TemporaryDirectory(prefix='rl-coach-') as folder:
        path = Path(folder) / 'upload.replay'
        with path.open('wb') as fp:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, 'Replay exceeds the 20 MB upload limit.')
                fp.write(chunk)
        if size < 32:
            raise HTTPException(400, 'Replay file is empty or too small.')
        try:
            result = parse_replay_file(path)
        except ReplayParseError as e:
            raise HTTPException(422, str(e)) from e
    result['title'] = Path(filename).stem[:128]
    return {'replay': result, 'candidates': find_review_candidates(result, result['players'][0]['id'])}


class ReviewRequest(BaseModel):
    replay: dict
    player_id: str


@app.post('/api/review-candidates')
async def review_candidates(request: ReviewRequest):
    try:
        return {'candidates': find_review_candidates(request.replay, request.player_id)}
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(422, 'Invalid replay or player selection.') from e


@app.post('/api/ai-review')
async def ai_review(request: Request):
    """Only called after explicit user action; sends sampled positions to Gemini, never raw file."""
    key = os.getenv('GEMINI_API_KEY')
    if not key:
        raise HTTPException(503, 'Set GEMINI_API_KEY on the server to enable optional AI review.')
    raw = await request.body()
    if len(raw) > MAX_COACH_BYTES:
        raise HTTPException(413, 'Replay JSON too large for AI review.')
    try:
        payload = ReviewRequest.model_validate_json(raw)
        compact = compact_game_states(payload.replay, payload.player_id)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(422, 'Invalid replay or player selection.') from e

    instruction = (
        'You are a Rocket League replay analyst, not a narrator. Analyze the following sparse '
        '0.5s-ish time-sampled numerical replay states. Without video or inputs, you CANNOT '
        'know exact intent, camera perception, hits between samples, or hypothetical outcomes. '
        'Provide up to three specific, time-coded game-sense REVIEW HYPOTHESES about the focus '
        'player, each with observed evidence, alternatives and uncertainties. Be conservative. '
        'Do not claim a different path would guarantee a goal or save. No fabricated event details. '
        'Return ONLY JSON with this shape: {"findings": [{"t": 12.5, "title": "...", '
        '"evidence": "...", "advice": "...", "uncertainty": "..."}]}.'
        '\n\n' + compact
    )
    try:
        import httpx
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent',
                headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
                json={'contents': [{'parts': [{'text': instruction}]}],
                      'generationConfig': {'responseMimeType': 'application/json', 'maxOutputTokens': 1800}},
            )
            response.raise_for_status()
            body = response.json()
        text = body['candidates'][0]['content']['parts'][0]['text']
        findings = json.loads(text).get('findings', [])
        if not isinstance(findings, list):
            raise ValueError('Model returned invalid findings.')
        # Keep only bounded safe fields; never trust model-defined coordinates or markup.
        clean = []
        for item in findings[:3]:
            t = float(item['t'])
            if t < 0 or t > float(payload.replay['duration']):
                continue
            clean.append({
                'id': f'ai-{len(clean)}', 't': round(t, 2), 'type': 'ai',
                'title': str(item.get('title', 'Review this decision'))[:120],
                'confidence': 'requires-verification',
                'evidence': str(item.get('evidence', ''))[:600],
                'advice': str(item.get('advice', ''))[:600],
                'uncertainty': str(item.get('uncertainty', ''))[:600],
                'target': None,
            })
        return {'findings': clean, 'mode': 'sparse-position-analysis',
                'warning': 'AI suggestions are hypotheses, not verified mistakes.'}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
        # Never echo a secret or raw upstream error payload to the browser.
        raise HTTPException(502, 'Gemini analysis did not complete. Check server logs/quota and retry later.') from e

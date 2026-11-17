"""Local-first FastAPI app. Does not change or expose the existing Cloudflare MCP Worker."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .coaching import compact_game_states, find_review_candidates
from .contextual_review import build_contextual_reviews
from .replays import ReplayParseError, parse_replay_file

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_COACH_BYTES = 2 * 1024 * 1024
STATIC = Path(__file__).parent / 'static'
# The server has no authentication, so it must only answer the local browser tab.
# Host allow-list stops DNS rebinding; the Origin check below stops other websites
# from POSTing to the API (which could otherwise spend the Gemini quota).
# 'testserver' is Starlette's TestClient host name.
ALLOWED_HOSTS = [h.strip() for h in os.getenv(
    'COACH_ALLOWED_HOSTS', '127.0.0.1,localhost,[::1],testserver').split(',') if h.strip()]
app = FastAPI(title='Rocket League Replay Coach', version='0.3.0')
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.mount('/static', StaticFiles(directory=STATIC), name='static')


@app.middleware('http')
async def same_origin_writes_only(request: Request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin is not None and urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail': 'Cross-origin requests are not allowed.'}, status_code=403)
    return await call_next(request)


@app.get('/')
def index():
    return FileResponse(STATIC / 'index.html', media_type='text/html')


@app.get('/api/health')
def health():
    return {'status': 'ok', 'mode': 'local-first', 'decoder': 'subtr-actor', 'geminiConfigured': bool(os.getenv('GEMINI_API_KEY'))}


@app.post('/api/replays')
async def upload_replay(request: Request):
    """Validate bounded raw .replay upload; delete it after parsing in a private temp dir."""
    # The browser percent-encodes the name: HTTP headers cannot carry non-Latin-1 text.
    filename = Path(unquote(request.headers.get('x-replay-name', 'match.replay'))).name
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
            # Decoding is CPU-bound (seconds); keep it off the event loop.
            result = await run_in_threadpool(parse_replay_file, path)
        except ReplayParseError as e:
            raise HTTPException(422, str(e)) from e
    result['title'] = Path(filename).stem[:128]
    # Generate all player-specific review leads once, while the decoded telemetry
    # is in memory. Switching the selected player needs no second large upload.
    # A failure here must never prevent the replay itself from being viewed.
    try:
        result['contextualReviews'] = {
            p['id']: build_contextual_reviews(result, p['id'])
            for p in result['players']
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        result['contextualReviews'] = {}
        result.setdefault('notes', []).append(
            'Contextual review unavailable; replay playback is unaffected.'
        )
    return {
        'replay': result,
        # Backward compatibility for existing API consumers; these are raw
        # positional observations, not the new coaching shortlist.
        'candidates': find_review_candidates(
            result, result.get('primaryPlayerId') or result['players'][0]['id']
        ),
    }


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
    # Requiring JSON forces a CORS preflight, so another site cannot fire this
    # endpoint as a "simple" text/plain form post.
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise HTTPException(415, 'Send the review request as application/json.')
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
        'time-sampled numerical replay states. Without video or inputs, you CANNOT '
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
        parsed = json.loads(text)
        findings = parsed.get('findings', []) if isinstance(parsed, dict) else None
        if not isinstance(findings, list):
            raise ValueError('Model returned invalid findings.')
        batch = uuid.uuid4().hex[:8]  # ids must stay unique across repeated requests
        # Keep only bounded safe fields; never trust model-defined coordinates or markup.
        clean = []
        for item in findings[:3]:
            if not isinstance(item, dict):
                continue
            t = float(item['t'])
            if t < 0 or t > float(payload.replay['duration']):
                continue
            clean.append({
                'id': f'ai-{batch}-{len(clean)}', 't': round(t, 2), 'type': 'ai',
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

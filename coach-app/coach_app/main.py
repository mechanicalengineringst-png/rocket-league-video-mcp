"""Local-first FastAPI app. Does not change or expose the existing Cloudflare MCP Worker."""
from __future__ import annotations

import json
import math
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
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


@app.get('/hd')
def high_fidelity_player():
    """Optional built browser renderer; original app remains fully operational.

    Build from coach-app/setup-high-fidelity.cmd once on the user's machine.
    Never serve unbuilt local node_modules or replay files to the network.
    """
    entry = STATIC / 'hd-player' / 'index.html'
    if entry.is_file():
        return FileResponse(entry, media_type='text/html')
    return HTMLResponse(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Set up Replay Lab HD</title><body style="background:#071420;'
        'color:#dcefff;font:16px Segoe UI,sans-serif;max-width:650px;'
        'margin:12vh auto;padding:30px;line-height:1.6">'
        '<h1>High-Fidelity 3D viewer is not built yet</h1>'
        '<p>Install Node.js 22 or newer, then double-click '
        '<code>coach-app\\setup-high-fidelity.cmd</code> once. '
        'The script installs @rlrml/player and builds the HD viewer locally.</p>'
        '<p>Restart is not required: refresh this page when setup finishes. '
        '<a style="color:#76d8ff" href="/">Back to Replay Lab</a></p>'
        '<p style="font-size:12px;color:#90a4b8">Your original Replay Lab '
        'and coaching are unaffected. The HD renderer parses .replay files '
        'locally in the browser.</p></body></html>',
        status_code=200,
    )


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
    selected_time: float | None = None


@app.post('/api/review-candidates')
async def review_candidates(request: ReviewRequest):
    try:
        return {'candidates': find_review_candidates(request.replay, request.player_id)}
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(422, 'Invalid replay or player selection.') from e


MAX_CASE_FRAMES = 30_000
MAX_CASE_DURATION = 1800.0  # 30 minutes
MAX_CASE_PLAYERS = 8


class DecisionCaseRequest(BaseModel):
    replay: dict[str, Any]
    player_id: str | None = None
    evaluate: bool = False

    @field_validator('replay')
    @classmethod
    def validate_replay_structure(cls, v: Any) -> dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError('Replay payload must be a JSON object.')
        frames = v.get('frames')
        if not isinstance(frames, list):
            raise ValueError("Replay payload missing 'frames' list.")
        if len(frames) > MAX_CASE_FRAMES:
            raise ValueError(f'Replay frames ({len(frames)}) exceed maximum allowed limit of {MAX_CASE_FRAMES}.')
        dur = v.get('duration')
        if dur is not None and isinstance(dur, (int, float)) and dur > MAX_CASE_DURATION:
            raise ValueError(f'Replay duration ({dur}s) exceeds maximum allowed limit of {MAX_CASE_DURATION}s.')
        players = v.get('players')
        if not isinstance(players, list) or len(players) < 1 or len(players) > MAX_CASE_PLAYERS:
            raise ValueError(f'Replay must contain between 1 and {MAX_CASE_PLAYERS} players.')
        return v


DecisionCaseRequest.model_rebuild()


@app.post('/api/decision-cases')
async def decision_cases_endpoint(request: DecisionCaseRequest):
    """Opt-in endpoint for evidence-safe DecisionCase extraction and evaluation.

    Preserves existing /api/review-candidates and /api/ai-review without breaking changes.
    """
    try:
        from .decision_cases import extract_all_decision_cases
        from .decision_evaluation import evaluate_decision_case_heuristics

        cases = extract_all_decision_cases(request.replay)
        if request.player_id:
            cases = [c for c in cases if c.focus_player_id == request.player_id]

        output = []
        for c in cases:
            item = c.to_llm_payload(include_quarantined_outcomes=False)
            if request.evaluate:
                eval_res = evaluate_decision_case_heuristics(c)
                item['evaluation'] = eval_res
            output.append(item)
        return {'cases': output, 'count': len(output), 'mode': 'opt_in_decision_engine'}
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(422, f'Could not process decision cases: {e}') from e


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
        selected_time = payload.selected_time
        if selected_time is not None:
            if not math.isfinite(selected_time) or selected_time < 0 or selected_time > float(payload.replay['duration']):
                raise ValueError('Selected time is outside replay range.')
        compact = compact_game_states(payload.replay, payload.player_id, max_frames=90)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(422, 'Invalid replay or player selection.') from e

    scope = (
        f'This is a user-selected replay moment at {selected_time:.2f}s, with only '
        'approximately three seconds of observations on either side. '
        if selected_time is not None else 'This is sparse match telemetry. '
    )
    instruction = (
        'You are a skeptical Rocket League replay coach. ' + scope +
        'Analyze ONLY the supplied numerical replay positions and velocities. '
        'This is NOT rendered footage; you cannot see button inputs, player camera, '
        'intent, exact car hitboxes, mechanic execution, or hypothetical future outcomes. '
        'Only if specific observed conditions create a genuinely actionable question, '
        'return at most ONE short, time-coded review hypothesis about the focus player. '
        'Explicitly quote the observed numbers or teammate/opponent locations, '
        'say what alternative to inspect and explain what cannot be established. '
        'Do not label ordinary 50/50s, nearby teammates, low boost or goals as mistakes. '
        'A deliberate soft 50/50, fake challenge, pass support or kickoff cheat may be correct. '
        'If the evidence is not sufficient for a meaningful insight, return an empty list. '
        'Do not invent a goal, touch, mechanical mistake, intent, or probable success rate. '
        'Return ONLY JSON: {"findings": [{"t": 12.5, "title": "...", '
        '"evidence": "...", "advice": "...", "uncertainty": "..."}]}. '
        'The findings array MAY BE EMPTY.\n\n' + compact
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
        for item in findings[:1]:
            if not isinstance(item, dict):
                continue
            t = float(item['t'])
            if not math.isfinite(t) or t < 0 or t > float(payload.replay['duration']):
                continue
            if selected_time is not None and abs(t - selected_time) > 3.5:
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
        return {'findings': clean, 'mode': 'selected-moment-telemetry-review',
                'warning': 'AI suggestions are hypotheses, not verified mistakes.'}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
        # Never echo a secret or raw upstream error payload to the browser.
        raise HTTPException(502, 'Gemini analysis did not complete. Check server logs/quota and retry later.') from e


@app.get('/api/companion/status')
def get_companion_status():
    from dataclasses import asdict
    from coach_app.companion import RocketLeagueCompanion
    comp = RocketLeagueCompanion()
    status = comp.get_status()
    return asdict(status)


@app.post('/api/companion/command')
def post_companion_command(payload: dict):
    # This route can control a running game; never enable it merely because a
    # local socket is listening. User must explicitly opt in for the session.
    if os.getenv('REPLAY_LAB_ENABLE_NATIVE_COMMANDS') != '1':
        raise HTTPException(403, 'Native game commands are disabled by default.')
    from coach_app.companion import RocketLeagueCompanion, CompanionConnectionError, CompanionProtocolError
    cmd = payload.get('Command')
    data = payload.get('Data', {})
    if not cmd:
        raise HTTPException(400, 'Command field is required')
    comp = RocketLeagueCompanion()
    try:
        res = comp.send_command(cmd, data, wait_response=False)  # Sent does not mean executed
        return res
    except CompanionConnectionError as e:
        raise HTTPException(503, str(e)) from e
    except CompanionProtocolError as e:
        raise HTTPException(400, str(e)) from e

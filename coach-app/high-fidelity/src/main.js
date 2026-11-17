import {
  createPlayer, createCameraPlugin, createNameTagPlugin,
  createBoostPadsPlugin, createScoredTextPlugin,
  createFpsOverlayPlugin, createBoostPickupAnimationPlugin,
  fromReplayPlayerPlugin, setPlayerAssetBase,
} from '@rlrml/player';
import { formatTime, clampTime, timelineMarkers } from './time.js';
import './style.css';

const $ = id => document.getElementById(id);
const shell = $('dropZone');
const surface = $('loadingSurface');
const upload = $('fileInput');
const viewer = $('viewport');

const assetBase = import.meta.env.DEV ? '/' : import.meta.env.BASE_URL;
setPlayerAssetBase(assetBase);

let player = null;
let cameraPlugin = null;
let unsubscribe = null;
let loadSequence = 0;
let loading = false;
let scrubbing = false;
let resumeAfterScrub = false;
let preferredPlayer = null;
let lastHudUpdate = -Infinity;

function setStatus(message, isError = false) {
  $('statusText').textContent = message;
  $('statusText').style.color = isError ? '#ffb19f' : '#a1e9e0';
}
function setLoading(visible, heading, hint = '') {
  surface.classList.toggle('hidden', !visible);
  if (visible) {
    surface.querySelector('h1').textContent = heading;
    surface.querySelector('p').textContent = hint;
    $('loadError').textContent = '';
  }
}
function enableControls(enabled) {
  for (const id of [
    'stepBackBtn','backBtn','playBtn','forwardBtn','stepForwardBtn',
    'seek','speedSelect','playerSelect','ballCamSelect',
    'interpolation','hitboxToggle','trailToggle'
  ]) $(id).disabled = !enabled;
  for (const button of document.querySelectorAll('.cam')) button.disabled = !enabled;
}

function currentPlayer() {
  return player?.adapter?.playerList?.find(p => p.id === $('playerSelect').value) ?? null;
}
function switchCamera(mode) {
  if (!cameraPlugin || !player) return;
  const available = new Set(['follow', 'orbit', 'ballOrbit', 'free']);
  if (!available.has(mode)) return;
  const picked = currentPlayer();
  if (mode === 'follow') {
    if (picked) cameraPlugin.follow(picked.name);
  } else if (mode === 'orbit') {
    cameraPlugin.release();
  } else {
    cameraPlugin.setMode(mode);
  }
  for (const button of document.querySelectorAll('.cam')) {
    const active = button.dataset.camera === mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  }
  $('ballCamSelect').disabled = mode !== 'follow';
  $('cameraLabel').textContent = ({
    follow: 'PLAYER CAM',
    orbit: 'ORBIT CAM',
    ballOrbit: 'BALL ORBIT',
    free: 'FLY CAM',
  })[mode];
  $('playerHud').textContent = mode === 'follow' && picked ? picked.name : 'FREE CAMERA';
}

function applyBallCam(value) {
  if (!cameraPlugin) return;
  cameraPlugin.setBallCam(value === 'recorded' ? null : value === 'ball');
  $('ballCamSelect').value = value;
}

function fillPlayers(players, preferredName = null) {
  const select = $('playerSelect');
  select.replaceChildren();
  for (const p of players) {
    const option = document.createElement('option');
    option.value = p.id;
    option.textContent = p.name + (p.team === 0 ? ' • BLUE' : ' • ORANGE');
    select.append(option);
  }
  const wanted = preferredName && players.find(p => p.name.toLowerCase() === preferredName.toLowerCase());
  select.value = (wanted || players[0])?.id ?? '';
}

function refreshEvents() {
  const list = $('eventList');
  list.replaceChildren();
  const markers = timelineMarkers(player?.replay, 35);
  if (!markers.length) {
    const text = document.createElement('span');
    text.className = 'muted';
    text.textContent = 'No supported goal/save/demo markers decoded.';
    list.append(text);
    return;
  }
  for (const event of markers) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = event.kind.toUpperCase() + ' · ' + formatTime(event.time);
    btn.title = event.label;
    btn.addEventListener('click', () => {
      player?.pause();
      player?.seek(clampTime(event.time,player.duration));
      updateHud(true);
    });
    list.append(btn);
  }
}

function updateHud(force = false) {
  if (!player || loading) return;
  const now = performance.now();
  if (!force && now - lastHudUpdate < 60) return; // UI work is not in WebGL render tick
  lastHudUpdate = now;
  const state = player.getState();
  $('currentTime').textContent = formatTime(state.currentTime);
  $('durationTime').textContent = formatTime(state.duration);
  if (!scrubbing) $('seek').value = String(state.currentTime);
  $('playBtn').textContent = state.playing ? '❚❚' : '▶';
  $('playBtn').setAttribute('aria-label', state.playing ? 'Pause replay' : 'Play replay');
}

async function loadFile(file, preferredName = null) {
  if (!file || !String(file.name || '').toLowerCase().endsWith('.replay')) {
    setStatus('Choose a .replay file.', true);
    return;
  }
  if (file.size > 20 * 1024 * 1024) {
    setStatus('Replay file exceeds the 20 MB local limit.', true);
    return;
  }
  const seq = ++loadSequence;
  loading = true;
  enableControls(false);
  setStatus('Reading replay bytes locally…');
  setLoading(true, 'Decoding native match…', 'Using subtr-actor WebAssembly. The replay file stays in your browser.');
  try {
    if (unsubscribe) { unsubscribe(); unsubscribe = null; }
    player?.pause();
    player?.dispose?.();
    player = null;
    viewer.replaceChildren();
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (seq !== loadSequence) return;
    cameraPlugin = createCameraPlugin({mode:'orbit'});
    setStatus('Building stadium, cars and replay timeline…');
    const next = await createPlayer(viewer, bytes, {
      autoplay: false,
      loop: false,
      motionInterpolation: 'hermite',
      motionSmoothing: true,
      initialSkipPostGoalTransitionsEnabled: false,
      initialSkipKickoffsEnabled: false,
      assetBase,
      plugins: [
        createNameTagPlugin(),
        createBoostPadsPlugin(),
        createScoredTextPlugin(),
        createFpsOverlayPlugin(),
        fromReplayPlayerPlugin(createBoostPickupAnimationPlugin()),
        cameraPlugin,
      ],
    });
    if (seq !== loadSequence) { next.dispose?.(); return; }
    player = next;
    preferredPlayer = preferredName;
    const roster = next.adapter.playerList || [];
    if (!roster.length) throw new Error('Replay has no readable player tracks.');
    fillPlayers(roster, preferredName);
    next.setPlaybackRate(Number($('speedSelect').value) || 1);
    next.setMotionInterpolation($('interpolation').value);
    applyBallCam($('ballCamSelect').value);
    switchCamera('follow');
    $('seek').max = String(next.duration);
    $('seek').value = '0';
    $('replayName').textContent = file.name;
    refreshEvents();
    // GLB loading is asynchronous; do not call this complete until ready.
    setStatus('Loading 3D arena and vehicle assets…');
    await next.ready;
    if (seq !== loadSequence) return;
    // ArenaManager falls back to a single flat mesh on asset load failure.
    const meshes = next.arenaManager?.arenaMeshes?.length ?? 0;
    setStatus(meshes > 1
      ? 'High-fidelity stadium loaded • native replay engine'
      : 'Replay decoded, but stadium assets may be missing. Check setup / browser console.', meshes <= 1);
    enableControls(true);
    $('ballCamSelect').disabled = false;
    $('hitboxToggle').checked = false;
    $('trailToggle').checked = true;
    setLoading(false);
    updateHud(true);
    next.play();
  } catch (error) {
    if (seq !== loadSequence) return;
    console.error('[Replay Lab HD] Replay failed to load', error);
    const message = error instanceof Error ? error.message : String(error);
    setStatus('Failed to open replay • ' + message, true);
    setLoading(true, 'Replay could not be loaded', 'Try another .replay or inspect the browser console for a parsing/asset error.');
    $('loadError').textContent = message;
  } finally {
    if (seq === loadSequence) loading = false;
  }
}

for (const button of document.querySelectorAll('.cam')) {
  button.addEventListener('click', () => switchCamera(button.dataset.camera));
}
$('playerSelect').addEventListener('change', () => switchCamera('follow'));
$('ballCamSelect').addEventListener('change', e => applyBallCam(e.target.value));
$('speedSelect').addEventListener('change', e => player?.setPlaybackRate(Number(e.target.value)));
$('interpolation').addEventListener('change', e => player?.setMotionInterpolation(e.target.value));
$('hitboxToggle').addEventListener('change', e => player?.setHitboxWireframesEnabled(e.target.checked));
$('trailToggle').addEventListener('change', e => { 
  // The bridged native pickup particle plugin observes this state.
  player?.setBoostPickupAnimationEnabled(e.target.checked);
});
$('playBtn').addEventListener('click', () => {
  if (!player) return;
  if (player.getState().playing) player.pause(); else player.play();
  updateHud(true);
});
$('backBtn').addEventListener('click', () => {
  player?.seek(clampTime((player?.getState().currentTime || 0) - 5,player?.duration));
  updateHud(true);
});
$('forwardBtn').addEventListener('click', () => {
  player?.seek(clampTime((player?.getState().currentTime || 0) + 5,player?.duration));
  updateHud(true);
});
$('stepBackBtn').addEventListener('click', () => { player?.stepBackwardFrame(); updateHud(true); });
$('stepForwardBtn').addEventListener('click', () => { player?.stepForwardFrame(); updateHud(true); });
$('seek').addEventListener('pointerdown', () => {
  scrubbing = true;
  resumeAfterScrub = !!player?.getState().playing;
  player?.pause();
});
$('seek').addEventListener('input', e => {
  const t = Number(e.target.value);
  player?.seek(t);
  $('currentTime').textContent = formatTime(t);
});
function finishScrub() {
  if (!scrubbing) return;
  scrubbing = false;
  if (resumeAfterScrub) player?.play();
  updateHud(true);
}
$('seek').addEventListener('pointerup', finishScrub);
$('seek').addEventListener('change', finishScrub);
$('fullscreenBtn').addEventListener('click', () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else shell.requestFullscreen?.();
});
$('replaceFileBtn').addEventListener('click', () => upload.click());
upload.addEventListener('change', e => {
  const file = e.target.files?.[0];
  upload.value = '';
  if (file) void loadFile(file);
});
for (const eventName of ['dragenter','dragover']) {
  shell.addEventListener(eventName,e => {e.preventDefault();shell.classList.add('dragging');});
}
shell.addEventListener('dragleave', e => {
  if (!shell.contains(e.relatedTarget)) shell.classList.remove('dragging');
});
shell.addEventListener('drop', e => {
  e.preventDefault(); shell.classList.remove('dragging');
  const file = e.dataTransfer?.files?.[0];
  if (file) void loadFile(file);
});
document.addEventListener('keydown', e => {
  const typing = ['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName);
  if (typing || e.ctrlKey || e.altKey || e.metaKey || !player) return;
  if (e.code === 'Space') {
    if (cameraPlugin?.getMode() === 'free') return; // Space flies upward in free cam
    e.preventDefault();
    if (player.getState().playing) player.pause(); else player.play();
  } else if (e.code === 'ArrowLeft' || e.code === 'ArrowRight') {
    e.preventDefault();
    player.seek(clampTime(player.getState().currentTime +
      (e.code === 'ArrowLeft' ? -5 : 5),player.duration));
  } else if (e.code === 'KeyB') {
    e.preventDefault();
    switchCamera('follow');
    const value = $('ballCamSelect').value === 'ball' ? 'car' : 'ball';
    applyBallCam(value);
  } else if (e.code === 'KeyF') {
    e.preventDefault();
    $('fullscreenBtn').click();
  }
});

// The parent Replay Lab can transfer an already-selected File without
// uploading it again, using a strict same-origin postMessage handshake.
window.addEventListener('message', event => {
  if (event.origin !== location.origin || event.source !== window.opener) return;
  if (event.data?.type !== 'replay-lab:hd-load') return;
  const file = event.data.file;
  if (!(file instanceof File)) return;
  void loadFile(file, typeof event.data.preferredPlayer === 'string'
    ? event.data.preferredPlayer : null);
});
if (window.opener && window.opener !== window) {
  window.opener.postMessage({ type:'replay-lab:hd-ready' }, location.origin);
}

function hudLoop() {
  updateHud();
  requestAnimationFrame(hudLoop);
}
hudLoop();

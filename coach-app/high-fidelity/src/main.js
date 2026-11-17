import {
  createPlayer, createCameraPlugin, createNameTagPlugin,
  createBoostPadsPlugin, createScoredTextPlugin,
  createBoostPickupAnimationPlugin,
  fromReplayPlayerPlugin, setPlayerAssetBase,
} from '@rlrml/player';
import { formatTime, clampTime, timelineMarkers } from './time.js';
import {
  findCameraTrack, recordedCameraAt, cameraEvidence,
  cameraSwitchMoments, displayCameraMode,
} from './camera-timeline.js';
import { createCameraPolishPlugin } from './camera-polish.js';
import {
  applySceneQuality, createEffectRefiner, createVisualEffectsPlugin,
} from './visual-quality.js';
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
let cameraPolish = null;
let effectRefiner = null;
let loadSequence = 0;
let loading = false;
let scrubbing = false;
let resumeAfterScrub = false;
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
    'interpolation','hitboxToggle','trailToggle','replayLookToggle',
    'qualitySelect','fxStyle'
  ]) $(id).disabled = !enabled;
  for (const button of document.querySelectorAll('.cam')) button.disabled = !enabled;
}

function currentPlayer() {
  return player?.adapter?.playerList?.find(p => p.id === $('playerSelect').value) ?? null;
}
function currentCameraTrack() {
  const p=currentPlayer();
  return p ? findCameraTrack(player?.replay,p.id,p.name) : null;
}
function invalidateCamera() { cameraPolish?.invalidate(); }
function switchCamera(mode) {
  if (!cameraPlugin || !player) return;
  if (!['follow','orbit','ballOrbit','free'].includes(mode)) return;
  const picked=currentPlayer();
  if(mode==='follow'){
    // Use the *public* parity API, not plugin.follow alone. Keeping the
    // attached player in the engine state lets applyReplayBallCam reproduce
    // per-player native Ball Cam toggles during seeking and playback.
    if(picked) player.setAttachedPlayer(picked.id);
  }else{
    player.setCameraViewMode('free');
    if(mode==='orbit') cameraPlugin.release();
    else cameraPlugin.setMode(mode);
  }
  invalidateCamera();
  for(const button of document.querySelectorAll('.cam')){
    const active=button.dataset.camera===mode;
    button.classList.toggle('active',active);
    button.setAttribute('aria-pressed',String(active));
  }
  $('ballCamSelect').disabled=mode!=='follow';
  $('playerHud').textContent=mode==='follow'&&picked?picked.name:
    mode==='free'?'FREE FLY CAMERA':mode==='ballOrbit'?'BALL ORBIT':'ORBIT CAMERA';
  updateHud(true);
}
function applyBallCam(value) {
  if(!player)return;
  // null means use replay-authored camera changes, not "ball cam always on".
  player.setBallCamEnabled(value==='recorded'?null:value==='ball');
  $('ballCamSelect').value=value;
  invalidateCamera();
  updateHud(true);
}
function updateCameraEvidence(){
  const evidence=cameraEvidence(currentCameraTrack());
  const el=$('cameraEvidence');
  if(!evidence.events){
    el.classList.add('unknown');
    el.textContent='This player has no replicated Ball Cam switch events. Recorded state is unknown; use Force Car Cam or Force Ball Cam for comparison.';
  }else{
    el.classList.remove('unknown');
    el.textContent='Native camera events: '+evidence.events+
      ' • Ball Cam OFF: '+evidence.ballOff+
      ' • Ball Cam ON: '+evidence.ballOn+
      ' • Rear view: '+evidence.rear+
      ' • Manual-look samples: '+(evidence.hasSwivel?'present':'not replicated')+
      '. The game does not store a literal camera-world transform.';
  }
}
function refreshCameraEvents() {
  const list=$('cameraEventList');
  list.replaceChildren();
  const moments=cameraSwitchMoments(player?.replay,currentCameraTrack(),60);
  if(!moments.length){
    const span=document.createElement('span');
    span.className='muted';
    span.textContent='No recorded camera switches for this player.';
    list.append(span);
    return;
  }
  for(const moment of moments){
    const btn=document.createElement('button');
    btn.type='button';
    btn.classList.toggle('off',moment.label==='Ball Cam off');
    btn.textContent=moment.label+' · '+formatTime(moment.time);
    btn.addEventListener('click',()=>{
      player?.pause();invalidateCamera();
      player?.seek(clampTime(moment.time,player.duration));
      updateHud(true);
    });
    list.append(btn);
  }
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
      invalidateCamera();
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
  const mode=cameraPlugin?.getMode()||'orbit';
  const recorded=recordedCameraAt(currentCameraTrack(),state.frameIndex);
  const override=$('ballCamSelect').value;
  const label=displayCameraMode(recorded,override,cameraPlugin?.getBallCam?.(),mode==='follow');
  $('cameraLabel').textContent=mode==='follow'?label:
    mode==='free'?'FLY CAM':mode==='ballOrbit'?'BALL ORBIT':'ORBIT CAM';
  $('cameraSource').textContent=mode!=='follow'?'VIEWER CONTROL':
    override!=='recorded'?'FORCED VIEW':
    recorded.hasRecordedSwitch?'REPLAY TELEMETRY':'NO RECORDED SWITCH';
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
    player?.pause();
    player?.dispose?.();
    player = null;
    cameraPolish=null;
    effectRefiner=null;
    lastHudUpdate=-Infinity;
    viewer.replaceChildren();
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (seq !== loadSequence) return;
    cameraPlugin = createCameraPlugin({mode:'orbit',useRecordedSettings:true});
    cameraPolish=createCameraPolishPlugin({
      getCameraPlugin:()=>cameraPlugin,
      getFollowId:()=>currentPlayer()?.id,
      getReplayLook:()=>$('replayLookToggle').checked,
    });
    effectRefiner=createEffectRefiner(()=>$('fxStyle').value);
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
        fromReplayPlayerPlugin(createBoostPickupAnimationPlugin()),
        cameraPlugin,
        cameraPolish, // must run AFTER native camera plugin
        createVisualEffectsPlugin(effectRefiner),
      ],
    });
    if (seq !== loadSequence) { next.dispose?.(); return; }
    player = next;
    const roster = next.adapter.playerList || [];
    if (!roster.length) throw new Error('Replay has no readable player tracks.');
    fillPlayers(roster, preferredName);
    updateCameraEvidence();
    refreshCameraEvents();
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
    const sceneQA=applySceneQuality(next,$('qualitySelect').value);
    $('fpsHint').textContent='3D meshes '+sceneQA.meshes+
      ' · filtered textures '+sceneQA.textures;
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
$('playerSelect').addEventListener('change', () => {
  switchCamera('follow');
  updateCameraEvidence();
  refreshCameraEvents();
});
$('ballCamSelect').addEventListener('change', e => applyBallCam(e.target.value));
$('speedSelect').addEventListener('change', e => player?.setPlaybackRate(Number(e.target.value)));
$('interpolation').addEventListener('change', e => player?.setMotionInterpolation(e.target.value));
$('replayLookToggle').addEventListener('change', invalidateCamera);
$('qualitySelect').addEventListener('change', e => {
  if(player) applySceneQuality(player,e.target.value);
});
$('fxStyle').addEventListener('change', () => {
  if(player) effectRefiner?.update(player);
});
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
  invalidateCamera();
  player?.seek(clampTime((player?.getState().currentTime || 0) - 5,player?.duration));
  updateHud(true);
});
$('forwardBtn').addEventListener('click', () => {
  invalidateCamera();
  player?.seek(clampTime((player?.getState().currentTime || 0) + 5,player?.duration));
  updateHud(true);
});
$('stepBackBtn').addEventListener('click', () => { invalidateCamera(); player?.stepBackwardFrame(); updateHud(true); });
$('stepForwardBtn').addEventListener('click', () => { invalidateCamera(); player?.stepForwardFrame(); updateHud(true); });
$('seek').addEventListener('pointerdown', () => {
  scrubbing = true;
  invalidateCamera();
  resumeAfterScrub = !!player?.getState().playing;
  player?.pause();
});
$('seek').addEventListener('input', e => {
  const t = Number(e.target.value);
  invalidateCamera();
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
    if (cameraPlugin?.getMode() === 'free') return; // arrows move fly camera
    e.preventDefault();
    invalidateCamera();
    player.seek(clampTime(player.getState().currentTime +
      (e.code === 'ArrowLeft' ? -5 : 5),player.duration));
  } else if (e.code === 'KeyB') {
    e.preventDefault();
    switchCamera('follow');
    const value = $('ballCamSelect').value === 'ball' ? 'car' : 'ball';
    applyBallCam(value);
  } else if (e.code === 'KeyR') {
    e.preventDefault();
    switchCamera('follow');
    applyBallCam('recorded');
  } else if (e.code === 'KeyF') {
    e.preventDefault();
    $('fullscreenBtn').click();
  }
});

// The parent Replay Lab can transfer an already-selected File without
// uploading it again, using a strict same-origin postMessage handshake.
window.addEventListener('message', event => {
  if (event.origin !== location.origin || event.source !== window.opener) return;
  if (event.data?.type === 'replay-lab:hd-ping') {
    window.opener?.postMessage({ type:'replay-lab:hd-ready' }, location.origin);
    return;
  }
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

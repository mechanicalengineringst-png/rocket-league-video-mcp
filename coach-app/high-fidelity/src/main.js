import {
  createPlayer, createCameraPlugin, createNameTagPlugin,
  createBoostPadsPlugin, createScoredTextPlugin,
  createBoostPickupAnimationPlugin,
  fromReplayPlayerPlugin, setPlayerAssetBase,
} from '@rlrml/player';
import * as THREE from 'three';
import { formatTime, clampTime, timelineMarkers } from './time.js';
import {
  findCameraTrack, recordedCameraAtTime, cameraEvidence,
  cameraSwitchMoments, displayCameraMode,
} from './camera-timeline.js';
import { createCameraPolishPlugin } from './camera-polish.js';
import { createRecordedCameraSwitchPlugin } from './recorded-camera-switch.js';
import {
  applySceneQuality, setFieldDecorStyle, createEffectRefiner, createVisualEffectsPlugin,
} from './visual-quality.js';
import './style.css';

const $ = id => document.getElementById(id);
const shell = $('dropZone');
const surface = $('loadingSurface');
const upload = $('fileInput');
const viewer = $('viewport');

const assetBase = import.meta.env.DEV ? '/' : import.meta.env.BASE_URL;
setPlayerAssetBase(assetBase);

// Disable the upstream skybox's artificial 2-degree/second rotation, which
// can read as background camera shake while reviewing stationary gameplay.
const STILL_HDR={
  id:'replay-lab-stable-stadium',
  skyboxUrl:`${assetBase.replace(/\/+$/, '')}/skyboxes/PlanetaryEarth4k.hdr`,
  exposure:1.20,
  rotation:{x:8,y:0,z:28},
  animation:{enabled:false,speed:0}
};

let player = null;
let cameraPlugin = null;
let cameraPolish = null;
let effectRefiner = null;
let loadSequence = 0;
let loading = false;
let scrubbing = false;
let resumeAfterScrub = false;
let lastHudUpdate = -Infinity;
// Optional QA-only mesh probe, only enabled by ?qa=1 on this same-origin page.
// It reports what the renderer really draws under a pixel, to locate oversized
// black field decorations without guessing at material names.
if(new URLSearchParams(location.search).get('qa')==='1'){
  window.__rlReplayLabQA={
    effectiveCameraState(){
      if(!player)return null;
      const state=player.getState();
      return {
        attached:state.attachedPlayerId,
        viewMode:state.cameraViewMode,
        useReplayBallCam:state.useReplayBallCam,
        effectiveBallCamEnabled:state.effectiveBallCamEnabled,
        pluginBallCam:cameraPlugin?.getBallCam?.(),
        pluginMode:cameraPlugin?.getMode?.(),
        time:state.currentTime
      };
    },
    hitsAt(clientX,clientY){
      if(!player?.scene||!player?.camera)return [];
      const bounds=viewer.getBoundingClientRect();
      const mouse=new THREE.Vector2(
        ((clientX-bounds.left)/bounds.width)*2-1,
        -((clientY-bounds.top)/bounds.height)*2+1
      );
      const ray=new THREE.Raycaster();
      ray.setFromCamera(mouse,player.camera);
      return ray.intersectObjects(player.scene.children,true)
        .filter(hit=>hit.distance>10 && hit.object?.isMesh &&
          hit.object.visible &&
          hit.object.parent?.visible !== false)
        .slice(0,18).map(hit=>{
          const mat=Array.isArray(hit.object.material)?
            hit.object.material[0]:hit.object.material;
          return {
            name:hit.object.name||'(unnamed)',
            parent:hit.object.parent?.name||'(unnamed)',
            geometry:hit.object.geometry?.type||'',
            material:mat?.name||'(unnamed)',
            color:mat?.color?.getHexString?.()??null,
            point:hit.point.toArray().map(x=>Math.round(x)),
            distance:Math.round(hit.distance),
            pad:hit.object.userData?.padId??null,
            visible:hit.object.visible,
            opacity:mat?.opacity??null,
            renderOrder:hit.object.renderOrder,
          };
        });
    },
    arenaMeshes(){
      return (player?.arenaManager?.arenaMeshes||[]).map(mesh=>({
        name:mesh.name,material:mesh.material?.name||'',
        visible:mesh.visible,castShadow:mesh.castShadow,
      }));
    },
    setArenaMeshVisible(name,visible){
      let count=0;
      for(const mesh of player?.arenaManager?.arenaMeshes||[]){
        if(mesh.name===name){mesh.visible=!!visible;count++;}
      }
      return count;
    },
    setBoostMeshesVisible(visible){
      let count=0;
      for(const child of player?.scene?.children||[]){
        if(Number.isInteger(child.userData?.padId)){
          child.visible=!!visible;count++;
        }
      }
      return count;
    },
    setSceneShadows(enabled){
      const renderer=player?.renderer;
      if(renderer?.shadowMap)renderer.shadowMap.enabled=!!enabled;
      return renderer?.shadowMap?.enabled??null;
    },
    freezeAt(t){
      player?.pause();player?.seek(t);
    },
  };
}


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
    'qualitySelect','fxStyle','lightingSelect','fieldDecorSelect'
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
  // Native 2v2 camera tracks can contain hundreds of toggles; limiting the
  // strip to the first 60 prevented seeking to legitimate later Car Cam OFF
  // moments. The list has a fixed-height scroll container in style.css.
  const moments=cameraSwitchMoments(player?.replay,currentCameraTrack(),500);
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
  const recorded=recordedCameraAtTime(currentCameraTrack(),player?.replay,state.currentTime);
  const override=$('ballCamSelect').value;
  const label=displayCameraMode(recorded,override,cameraPlugin?.getBallCam?.(),mode==='follow',$('replayLookToggle').checked);
  $('cameraLabel').textContent=mode==='follow'?label:
    mode==='free'?'FLY CAM':mode==='ballOrbit'?'BALL ORBIT':'ORBIT CAM';
  $('cameraSource').textContent=mode!=='follow'?'VIEWER CONTROL':
    override!=='recorded'?'FORCED VIEW':
    recorded.hasRecordedSwitch?'REPLAY TELEMETRY':'NO RECORDED SWITCH';

  // Live selected-player boost gauge
  const focus = currentPlayer();
  const boostHud = $('boostHud');
  if (boostHud) {
    if (mode === 'follow' && focus) {
      boostHud.classList.remove('hidden');
      const pData = player?.adapter?.getPlayer(focus.id);
      const boostVal = Math.round(Math.max(0, Math.min(100, pData?.boost ?? 0)));
      const isBoosting = !!pData?.isBoosting;
      const team = focus.team === 0 ? 'blue' : 'orange';
      $('boostNum').textContent = String(boostVal);
      const bar = $('boostBar');
      if (bar) {
        const maxOffset = 251.327;
        const offset = maxOffset * (1 - boostVal / 100);
        bar.style.strokeDashoffset = String(offset);
        bar.setAttribute('class', `boost-bar ${team}-team` + (isBoosting ? ' boosting' : ''));
      }
    } else {
      boostHud.classList.add('hidden');
    }
  }
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
    const cameraStateSource=createRecordedCameraSwitchPlugin({
      getCameraPlugin:()=>cameraPlugin,
      getFollowId:()=>currentPlayer()?.id,
      getCameraOverride:()=>$('ballCamSelect').value,
    });
    effectRefiner=createEffectRefiner(()=>$('fxStyle').value);
    setStatus('Building stadium, cars and replay timeline…');
    const next = await createPlayer(viewer, bytes, {
      autoplay: false,
      loop: false,
      motionInterpolation: 'hermite',
      motionSmoothing: true,
      environment: $('lightingSelect').value==='neutral'?false:STILL_HDR,
      initialSkipPostGoalTransitionsEnabled: false,
      initialSkipKickoffsEnabled: false,
      assetBase,
      plugins: [
        createNameTagPlugin(),
        createBoostPadsPlugin(),
        createScoredTextPlugin(),
        fromReplayPlayerPlugin(createBoostPickupAnimationPlugin()),
        cameraStateSource, // native source overrides stale adapter BEFORE camera renders
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
    setFieldDecorStyle(next,$('fieldDecorSelect').value);
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
$('lightingSelect').addEventListener('change', e=>{
  player?.setEnvironment(e.target.value==='neutral'?false:STILL_HDR);
});
$('qualitySelect').addEventListener('change', e => {
  if(player) applySceneQuality(player,e.target.value);
});
$('fieldDecorSelect').addEventListener('change', e => {
  if(player) setFieldDecorStyle(player,e.target.value);
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

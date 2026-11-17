/* Explicit, same-origin bridge between Replay Lab's tactical UI and HD replay.
 *
 * The parent UI is the authority for focus, playback speed and the replay
 * clock. No raw replay file or telemetry leaves these two same-origin tabs.
 * The HD viewer can still run alone with its own file picker.
 */
(function () {
  'use strict';
  const button = document.getElementById('openHdReplay');
  const upload = document.getElementById('fileInput');
  const select = document.getElementById('playerSelect');
  const dropZone = document.getElementById('uploadZone');
  if (!button || !upload) return;

  let replayFile = null;
  let hdWindow = null;
  let sessionId = null;
  let loaded = false;
  let loadInFlight = false;
  let hdInstanceId = null;
  let seq = 0;
  let lastState = null;
  let awaitingReplayReady = false;
  let lastPost = null;
  let lastPostAt = 0;

  function newSession() {
    if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
    // Identity token is a defensive session discriminator, not a secret.
    const a = new Uint32Array(4);
    if (globalThis.crypto?.getRandomValues) crypto.getRandomValues(a);
    else return 'session-' + Date.now().toString(36) +
      '-' + Math.random().toString(36).slice(2);
    return 'session-' + Array.from(a,x=>x.toString(16).padStart(8,'0')).join('');
  }
  function linked() {
    return hdWindow && !hdWindow.closed;
  }
  function preferredName() {
    const selected = select?.selectedOptions?.[0]?.textContent || '';
    return lastState?.focusName || selected.split(' — ')[0].trim();
  }
  function sendLoad() {
    if (!linked() || !replayFile || loadInFlight || loaded) return;
    sessionId = newSession();
    seq = 0;
    loaded = false;
    loadInFlight = true;
    lastPost = null;
    hdWindow.postMessage({
      type:'replay-lab:hd-load', sessionId,
      file:replayFile, preferredPlayer:preferredName(),
    },location.origin);
  }
  function forward(force = false) {
    if (!linked() || !loaded || !sessionId || !lastState || lastState.synthetic)
      return;
    const time = Number(lastState.time), speed = Number(lastState.speed);
    if (!Number.isFinite(time) || time < 0 ||
        !Number.isFinite(speed) || speed < 0.25 || speed > 2 ||
        typeof lastState.focusName !== 'string' ||
        !['blue','orange'].includes(lastState.focusTeam)) return;

    const now = performance.now();
    const prev = lastPost;
    const otherChange = !prev || prev.focusName !== lastState.focusName ||
      prev.focusTeam !== lastState.focusTeam ||
      prev.playing !== lastState.playing || prev.speed !== speed;
    const seek = !lastState.playing && (!prev || Math.abs(time - prev.time) > 0.03);
    if (!force && !otherChange && !seek && now - lastPostAt < 200) return;

    seq += 1;
    const packet = {
      type:'replay-lab:hd-control', sessionId, seq,
      time, playing:!!lastState.playing, speed,
      focusName:lastState.focusName, focusTeam:lastState.focusTeam,
    };
    hdWindow.postMessage(packet,location.origin);
    lastPost = packet;
    lastPostAt = now;
  }
  function captureFile(file) {
    if (!file || !String(file.name||'').toLowerCase().endsWith('.replay')) return;
    // Opening HD is always a user click. A later upload to an already-open
    // HD window may update it, but never launches or focuses a new window.
    replayFile = file;
    // The old replay's focus/time must never be applied to this new file
    // before its own upload and player mapping have completed.
    lastState = null;
    awaitingReplayReady = true;
    loaded = false;
    loadInFlight = false;
    if (linked()) sendLoad();
  }
  // Capture phase: legacy app clears input.value before its own load completes.
  upload.addEventListener('change',e=>captureFile(e.target?.files?.[0]),true);
  dropZone?.addEventListener('drop',e=>captureFile(e.dataTransfer?.files?.[0]),true);

  button.addEventListener('click',()=>{
    hdWindow = window.open('/hd','replay-lab-high-fidelity');
    if (!linked()) return;
    hdWindow.focus();
    // Ready is sent both on page creation and when pinging an existing tab.
    hdWindow.postMessage({type:'replay-lab:hd-ping'},location.origin);
  });
  window.addEventListener('replay-lab:replay-ready',e=>{
    // Only trust state created AFTER current upload was fully parsed.
    awaitingReplayReady = !!e.detail?.synthetic;
    if (awaitingReplayReady) lastState = null;
  });
  window.addEventListener('replay-lab:sync-state',e=>{
    if (awaitingReplayReady) return;
    lastState = e.detail;
    forward();
  });
  window.addEventListener('message',e=>{
    if (e.origin !== location.origin || !linked() || e.source !== hdWindow ||
        !e.data || typeof e.data !== 'object') return;
    if (e.data.type === 'replay-lab:hd-ready') {
      // A freshly reloaded HD window has a new page instance ID. Previous
      // in-flight session messages cannot be trusted for the new instance.
      if (typeof e.data.instanceId === 'string' &&
          e.data.instanceId.length >= 12 &&
          e.data.instanceId !== hdInstanceId) {
        hdInstanceId = e.data.instanceId;
        loadInFlight = false;
        loaded = false;
        sessionId = null;
      }
      sendLoad();
    } else if (e.data.type === 'replay-lab:hd-loaded' &&
               e.data.sessionId === sessionId) {
      loaded = true;
      loadInFlight = false;
      forward(true);
    } else if (e.data.type === 'replay-lab:hd-load-error' &&
               e.data.sessionId === sessionId) {
      loaded = false;
      loadInFlight = false;
      // The standalone HD window presents the detailed load error.
    }
  });
})();

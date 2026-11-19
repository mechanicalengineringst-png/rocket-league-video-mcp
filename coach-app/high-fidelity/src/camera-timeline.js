/** Grounded camera data in the normalized @rlrml/player ReplayModel.
 * A replay contains switch events and optional swivel bytes, NOT an actual
 * camera-world transform. Unknown is always different from "ball cam on".
 */
const finite = x => Number.isFinite(x);
const bool = x => typeof x === 'boolean' ? x : null;

export function findCameraTrack(replay, id, name = '') {
  const players = Array.isArray(replay?.players) ? replay.players : [];
  const byId = players.filter(p => p.id === id);
  if (byId.length === 1) return byId[0];
  // Duplicate identifiers/names can occur in malformed or anonymized
  // replays. Never silently follow a different player's camera track.
  if (byId.length > 1 || !name) return null;
  const byName = players.filter(p => p.name === name);
  return byName.length === 1 ? byName[0] : null;
}

// The renderer calls recordedCameraAtTime() on EVERY rendered frame. On a
// replay with hundreds of Ball/Car Cam switches, rescanning all events at
// 144 Hz needlessly competes with camera rendering and causes frame spikes.
// ReplayModel cameraEvents is immutable after decoding, so compile once per
// track and use O(log n) binary lookups at every seek and playback frame.
//
// Use WeakMap: no permanent replay retention, including when a new match is
// loaded. Replacing cameraEvents or appending a new event rebuilds the index.
// In-place edits that preserve the same array identity and length are not
// supported; decoded ReplayModel data is not live-mutated.
const cameraIndexCache = new WeakMap();

function cameraEventIndex(track) {
  const events = Array.isArray(track?.cameraEvents) ? track.cameraEvents : [];
  if (track && typeof track === 'object') {
    const prior = cameraIndexCache.get(track);
    if (prior?.events === events && prior.length === events.length) return prior;
  }
  const ball = [], rear = [], driving = [], all = [];
  let hasRecordedSwitch = false;
  for (let order = 0; order < events.length; order++) {
    const event = events[order];
    const ballState = bool(event?.ballCamActive);
    if (ballState !== null) hasRecordedSwitch = true;
    const frame = event?.frame;
    if (!Number.isSafeInteger(frame) || frame < 0) continue;
    all.push(frame);
    // Stable ties preserve the source's last event at the same frame,
    // matching the old linear scanner's >= semantics.
    if (ballState !== null) ball.push([frame, ballState, order]);
    const rearState = bool(event.behindViewActive);
    if (rearState !== null) rear.push([frame, rearState, order]);
    const drivingState = bool(event.driving);
    if (drivingState !== null) driving.push([frame, drivingState, order]);
  }
  const byFrame = (a, b) => a[0] - b[0] || a[2] - b[2];
  for (const entries of [ball, rear, driving]) entries.sort(byFrame);
  all.sort((a,b) => a - b);
  const result = {events, length:events.length, ball, rear, driving, all, hasRecordedSwitch};
  if (track && typeof track === 'object') cameraIndexCache.set(track, result);
  return result;
}
function latestIndex(entries, frame) {
  let lo = 0, hi = entries.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((Array.isArray(entries[mid]) ? entries[mid][0] : entries[mid]) <= frame) lo = mid + 1;
    else hi = mid;
  }
  return lo - 1;
}
function lastValue(entries, frame) {
  const i = latestIndex(entries, frame);
  return i < 0 ? null : entries[i][1];
}

export function recordedCameraAt(track, frameIndex) {
  const frames = Array.isArray(track?.frames) ? track.frames : [];
  const index = Number.isFinite(frameIndex) ? Math.max(0, Math.floor(frameIndex)) : 0;
  const timeline = cameraEventIndex(track);
  const lastSwitchIndex = latestIndex(timeline.all, index);
  const sample = frames[Math.min(index, Math.max(0, frames.length - 1))] || {};
  return {
    ballCam: lastValue(timeline.ball, index),
    behind: lastValue(timeline.rear, index),
    driving: lastValue(timeline.driving, index),
    lastSwitchFrame: lastSwitchIndex < 0 ? -1 : timeline.all[lastSwitchIndex],
    yaw: finite(sample.cameraYaw) ? sample.cameraYaw : null,
    pitch: finite(sample.cameraPitch) ? sample.cameraPitch : null,
    events: timeline.length,
    hasRecordedSwitch: timeline.hasRecordedSwitch,
  };
}

/** Camera events use indexes in ReplayModel.frames, which can differ from
 * the renderer adapter's current frame index around seeks or adjusted
 * timelines. Resolve from the exact ReplayModel clock, with a tiny epsilon
 * for Float32 native-frame time rounding. A logged switch takes effect at
 * its recorded frame time, even when the viewer seeks backwards.
 */
export function replayFrameAtTime(replay,time) {
  const frames=Array.isArray(replay?.frames)?replay.frames:[];
  if(!frames.length||!finite(time))return 0;
  let lo=0,hi=frames.length;
  const at=time+0.0001;
  while(lo<hi){
    const mid=(lo+hi)>>>1;
    if(finite(frames[mid]?.time) && frames[mid].time<=at)lo=mid+1;
    else hi=mid;
  }
  return Math.max(0,lo-1);
}

export function recordedCameraAtTime(track,replay,time) {
  return recordedCameraAt(track,replayFrameAtTime(replay,time));
}

export function cameraEvidence(track) {
  const events = Array.isArray(track?.cameraEvents) ? track.cameraEvents : [];
  const frames = Array.isArray(track?.frames) ? track.frames : [];
  let ballOff = 0, ballOn = 0, rear = 0;
  for (const event of events) {
    if (event.ballCamActive === false) ballOff++;
    if (event.ballCamActive === true) ballOn++;
    if (event.behindViewActive === true) rear++;
  }
  // Sampling to avoid walking every sample on each UI tick; this is for status.
  let lookSamples = 0;
  for (let i=0; i<frames.length; i+=Math.max(1, Math.ceil(frames.length/2000))) {
    const s=frames[i];
    if (finite(s?.cameraYaw) || finite(s?.cameraPitch)) lookSamples++;
  }
  return {events:events.length,ballOff,ballOn,rear,lookSamples,hasSwivel:lookSamples>0};
}

export function cameraSwitchMoments(replay, track, limit = 80) {
  const events = Array.isArray(track?.cameraEvents) ? track.cameraEvents : [];
  const frames = Array.isArray(replay?.frames) ? replay.frames : [];
  return events
    .filter(e => Number.isInteger(e?.frame) && e.frame >= 0 && e.frame < frames.length)
    .flatMap(event => {
      const result = [];
      const time = Number(frames[event.frame]?.time);
      if (!finite(time)) return result;
      if (bool(event.ballCamActive) !== null) result.push({
        time, kind:'camera',
        label: event.ballCamActive ? 'Ball Cam on' : 'Ball Cam off',
      });
      if (event.behindViewActive === true) result.push({
        time, kind:'camera', label:'Rear look',
      });
      return result;
    })
    .sort((a,b) => a.time - b.time)
    .slice(0,limit);
}

export function displayCameraMode(recorded, override, pluginEffective, following=true, rearLookEnabled=true) {
  if (!following) return 'FREE / ORBIT';
  // The engine falls back to Ball Cam when the telemetry stream is absent,
  // but that is NOT evidence that the real player left Ball Cam on.
  if(override==='ball')return 'BALL CAM';
  if(override==='car')return 'CAR CAM';
  if(typeof recorded?.ballCam!=='boolean')return 'CAMERA UNKNOWN';
  if(recorded.behind===true && rearLookEnabled)return 'REAR LOOK';
  return recorded.ballCam ? 'BALL CAM' : 'CAR CAM';
}

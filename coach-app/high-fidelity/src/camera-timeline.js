/** Grounded camera data in the normalized @rlrml/player ReplayModel.
 * A replay contains switch events and optional swivel bytes, NOT an actual
 * camera-world transform. Unknown is always different from "ball cam on".
 */
const finite = x => Number.isFinite(x);
const bool = x => typeof x === 'boolean' ? x : null;

export function findCameraTrack(replay, id, name = '') {
  const players = Array.isArray(replay?.players) ? replay.players : [];
  return players.find(p => p.id === id) ||
    players.find(p => p.name === name) || null;
}

export function recordedCameraAt(track, frameIndex) {
  const events = Array.isArray(track?.cameraEvents) ? track.cameraEvents : [];
  const frames = Array.isArray(track?.frames) ? track.frames : [];
  const index = Number.isFinite(frameIndex) ? Math.max(0, Math.floor(frameIndex)) : 0;
  let ballCam = null;
  let behind = null;
  let driving = null;
  let lastSwitchFrame = -1;
  for (const event of events) {
    if (!Number.isFinite(event?.frame) || event.frame > index) continue;
    if (bool(event.ballCamActive) !== null) ballCam = event.ballCamActive;
    if (bool(event.behindViewActive) !== null) behind = event.behindViewActive;
    if (bool(event.driving) !== null) driving = event.driving;
    lastSwitchFrame = Math.max(lastSwitchFrame, event.frame);
  }
  const sample = frames[Math.min(index, Math.max(0, frames.length - 1))] || {};
  return {
    ballCam, behind, driving, lastSwitchFrame,
    yaw: finite(sample.cameraYaw) ? sample.cameraYaw : null,
    pitch: finite(sample.cameraPitch) ? sample.cameraPitch : null,
    events: events.length,
    hasRecordedSwitch: events.some(e => bool(e.ballCamActive) !== null),
  };
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

export function displayCameraMode(recorded, override, pluginEffective, following=true) {
  if (!following) return 'FREE / ORBIT';
  const rear = recorded?.behind === true && override === 'recorded';
  const effective = override === 'ball' ? true : override === 'car' ? false :
    typeof recorded?.ballCam === 'boolean' ? recorded.ballCam : pluginEffective;
  if (rear) return 'REAR LOOK';
  if (typeof effective !== 'boolean') return 'CAMERA UNKNOWN';
  return effective ? 'BALL CAM' : 'CAR CAM';
}

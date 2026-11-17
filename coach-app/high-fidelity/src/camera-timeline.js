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

export function recordedCameraAt(track, frameIndex) {
  const events = Array.isArray(track?.cameraEvents) ? track.cameraEvents : [];
  const frames = Array.isArray(track?.frames) ? track.frames : [];
  const index = Number.isFinite(frameIndex) ? Math.max(0, Math.floor(frameIndex)) : 0;
  let ballCam = null, behind = null, driving = null;
  let lastSwitchFrame = -1;
  let lastBallCamFrame = -1, lastBehindFrame = -1, lastDrivingFrame = -1;
  for (const event of events) {
    const frame = event?.frame;
    if (!Number.isInteger(frame) || frame < 0 || frame > index) continue;
    // Native camera events are not guaranteed to arrive chronologically.
    // Choose the latest preceding event *for each signal* by frame number,
    // not whichever record happens to be last in the source array.
    const ball = bool(event.ballCamActive);
    const rear = bool(event.behindViewActive);
    const drive = bool(event.driving);
    if (ball !== null && frame >= lastBallCamFrame) {
      ballCam = ball; lastBallCamFrame = frame;
    }
    if (rear !== null && frame >= lastBehindFrame) {
      behind = rear; lastBehindFrame = frame;
    }
    if (drive !== null && frame >= lastDrivingFrame) {
      driving = drive; lastDrivingFrame = frame;
    }
    lastSwitchFrame = Math.max(lastSwitchFrame, frame);
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

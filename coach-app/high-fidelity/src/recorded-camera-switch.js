import { findCameraTrack, recordedCameraAtTime } from './camera-timeline.js';

/** Synchronize the ACTUAL camera renderer from native camera event times.
 * The renderer's adjusted frame index can disagree with ReplayModel.frames
 * at a recorded switch. Also respond to seeks immediately instead of
 * requiring a subsequent rAF tick while paused.
 *
 * This plugin runs BEFORE the upstream camera plugin. It never changes the
 * ReplayPlayer's public recorded/forced selection or emits a state update.
 */
export function createRecordedCameraSwitchPlugin({
  getCameraPlugin, getFollowId, getCameraOverride,
}) {
  let lastReplay=null,lastFocus=null,track=null;

  function sync(player,time,viewMode) {
    if(!player?.replay||viewMode!=='follow'||getCameraOverride()!=='recorded')return;
    const focusId=getFollowId();
    if(!focusId)return;
    if(player.replay!==lastReplay||focusId!==lastFocus){
      lastReplay=player.replay;lastFocus=focusId;
      const roster=player.adapter?.playerList||[];
      const p=roster.find(item=>item.id===focusId);
      track=findCameraTrack(lastReplay,focusId,p?.name||'');
    }
    const observed=recordedCameraAtTime(track,lastReplay,time);
    // When the replay has no trustworthy state *at this time*, use a
    // deterministic neutral Car Cam view. Otherwise a backwards seek or
    // player change can inherit a stale Ball Cam ON state from the last
    // player, incorrectly making Ball Cam appear permanently enabled.
    // The UI still says CAMERA UNKNOWN; this fallback is not replay truth.
    const ballCam=typeof observed.ballCam==='boolean'?observed.ballCam:false;
    const camera=getCameraPlugin();
    if(camera && camera.getBallCam()!==ballCam){
      // Set plugin only. Calling player.setBallCamEnabled() would replace
      // the user's "recorded" mode with a forced manual override.
      camera.setBallCam(ballCam);
    }
  }

  return {
    id:'replay-lab-recorded-camera-source',
    onStateChange(ctx) {
      // Seeking, frame stepping, and selecting player all update now.
      sync(ctx.player,ctx.state?.currentTime,ctx.state?.cameraViewMode);
    },
    beforeRender(ctx) {
      sync(ctx.player,ctx.time??ctx.state?.currentTime,
        ctx.state?.cameraViewMode);
    },
    teardown(){lastReplay=null;lastFocus=null;track=null;},
  };
}

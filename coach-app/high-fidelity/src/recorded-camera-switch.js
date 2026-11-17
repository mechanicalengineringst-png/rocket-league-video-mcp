import { findCameraTrack, recordedCameraAt } from './camera-timeline.js';

/** Correct the upstream adapter edge case in which the ReplayModel has
 * replicated camera-switch events but its mutable player entity can retain
 * a stale Ball Cam state after a backward seek. This plugin runs BEFORE the
 * upstream camera renderer and sets its actual mode from the normalized
 * ReplayModel's native event stream, not from our HUD label.
 */
export function createRecordedCameraSwitchPlugin({
  getCameraPlugin, getFollowId, getCameraOverride,
}) {
  let lastReplay=null,lastFocus=null,track=null;
  return {
    id:'replay-lab-recorded-camera-source',
    beforeRender(ctx) {
      if(!ctx?.player || ctx.state?.cameraViewMode!=='follow')return;
      if(getCameraOverride()!=='recorded')return;
      const focusId=getFollowId();
      if(!focusId)return;
      if(ctx.player.replay!==lastReplay||focusId!==lastFocus) {
        lastReplay=ctx.player.replay;
        lastFocus=focusId;
        const roster=ctx.player.adapter?.playerList||[];
        const p=roster.find(p=>p.id===focusId);
        track=findCameraTrack(lastReplay,focusId,p?.name||'');
      }
      const observed=recordedCameraAt(track,ctx.frameIndex);
      if(typeof observed.ballCam === 'boolean'){
        // Do NOT call player.setBallCamEnabled() from a render callback:
        // it emits a state-change event and would override recorded mode.
        // Setting the camera plugin directly before its own frame pass
        // ensures the real camera, not just the UI, follows the replay.
        const camera=getCameraPlugin();
        if(camera && camera.getBallCam()!==observed.ballCam)
          camera.setBallCam(observed.ballCam);
      }
    },
    teardown(){lastReplay=null;lastFocus=null;track=null;},
  };
}

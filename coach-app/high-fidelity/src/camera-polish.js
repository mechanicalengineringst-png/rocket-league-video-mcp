import * as THREE from 'three';
import {findCameraTrack,recordedCameraAt} from './camera-timeline.js';

const UP=new THREE.Vector3(0,1,0);
const relative=new THREE.Vector3();
const right=new THREE.Vector3();
const anchor=new THREE.Vector3();
const prevPosition=new THREE.Vector3();
const prevQuaternion=new THREE.Quaternion();

/** Follow-camera second-stage stabilization. Unlike a simple fixed LERP, the
 * exponential coefficient is elapsed-time based, so 60/144Hz have similar
 * damping. Seeking and player switches snap instead of gliding over the field.
 * The upstream camera plugin still computes the underlying RL-style view.
 */
export function createCameraPolishPlugin({getCameraPlugin,getFollowId,getReplayLook}) {
  let frameAt=null, replayAt=null, lastFocus=null, lastMode=null, reset=true;
  let attached=false;
  const api={
    id:'replay-lab-camera-polish',
    invalidate(){reset=true;},
    beforeRender(ctx){
      const cp=getCameraPlugin();
      const mode=cp?.getMode?.();
      const state=ctx.player.getState();
      const focus=getFollowId();
      const time=state.currentTime;
      const now=performance.now();
      if(mode!=='follow'||!focus){
        attached=false;reset=true;lastMode=mode;lastFocus=focus;
        return;
      }
      const cam=ctx.camera;
      const track=findCameraTrack(ctx.player.replay,focus);
      const recorded=recordedCameraAt(track,state.frameIndex);
      // Free-look angles are replicated per player, but the WORLD camera
      // transform isn't. This is optional reconstruction, not ground truth.
      // A rear-view toggle flips the offset around the car. It only modifies
      // forced/recorded Car Cam; Ball Cam remains driven by its ball target.
      const isBallCam=cp.getBallCam();
      if(getReplayLook() && !isBallCam) {
        const car=ctx.cars.find(c=>c.id===focus)?.object3d;
        if(car) {
          car.getWorldPosition(anchor);
          relative.copy(cam.position).sub(anchor);
          const yaw=recorded.yaw ?? 0;
          const rear=recorded.behind===true;
          const pitch=recorded.pitch ?? 0;
          if(rear || Math.abs(yaw)>0.002 || Math.abs(pitch)>0.002) {
            relative.applyAxisAngle(UP,THREE.MathUtils.clamp(yaw,-Math.PI,Math.PI)+(rear?Math.PI:0));
            right.crossVectors(UP,relative);
            if(right.lengthSq()>0.0001)
              relative.applyAxisAngle(right.normalize(),THREE.MathUtils.clamp(pitch,-0.55,0.55));
            cam.position.copy(anchor).add(relative);
            cam.position.y=THREE.MathUtils.clamp(cam.position.y,45,1970);
            cam.position.x=THREE.MathUtils.clamp(cam.position.x,-4035,4035);
            cam.position.z=THREE.MathUtils.clamp(cam.position.z,-5055,5055);
            cam.lookAt(anchor);
          }
        }
      }

      const dt=frameAt===null?1/60:Math.max(0,Math.min(.10,(now-frameAt)/1000));
      const jumped=replayAt!==null && Math.abs(time-replayAt)>Math.max(0.20,dt*5*Math.max(1,state.speed||1));
      const needSnap=reset||!attached||jumped||focus!==lastFocus||mode!==lastMode;
      if(!needSnap){
        const alpha=1-Math.exp(-32*dt);
        // Moderate stabilization, not enough lag to alter gameplay analysis.
        cam.position.lerpVectors(prevPosition,cam.position,alpha);
        cam.quaternion.copy(prevQuaternion).slerp(cam.quaternion,alpha);
      }
      prevPosition.copy(cam.position);
      prevQuaternion.copy(cam.quaternion);
      frameAt=now;replayAt=time;lastMode=mode;lastFocus=focus;
      reset=false;attached=true;
    },
    teardown(){reset=true;attached=false;frameAt=null;replayAt=null;},
  };
  return api;
}

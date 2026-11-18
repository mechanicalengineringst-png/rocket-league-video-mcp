import * as THREE from 'three';
import {findCameraTrack,recordedCameraAtTime} from './camera-timeline.js';

const UP=new THREE.Vector3(0,1,0);
const relative=new THREE.Vector3();
const right=new THREE.Vector3();
const anchor=new THREE.Vector3();
const prevPosition=new THREE.Vector3();
const prevQuaternion=new THREE.Quaternion();
const lastCarPos=new THREE.Vector3();

// Arena coordinate limits in Three.js world space:
// Unreal space: X = Length (+-5120), Y = Width (+-4096), Z = Height (0 - 2044)
// Three.js space: X = Length (+-5050), Y = Height (45 - 2000), Z = Width (+-4030)
const ARENA_X_LIMIT = 5050; // Goal-to-Goal limit
const ARENA_Z_LIMIT = 4030; // Sidewall-to-Sidewall limit
const ARENA_Y_MIN = 45;    // Ground floor clearance
const ARENA_Y_MAX = 2000;  // Ceiling clearance

/** Follow-camera second-stage stabilization. Unlike a simple fixed LERP, the
 * exponential coefficient is elapsed-time based, so 60/144Hz have similar
 * damping. Seeking, player switches, goal resets, and demolitions snap instead
 * of gliding over the field.
 */
export function createCameraPolishPlugin({getCameraPlugin,getFollowId,getReplayLook}) {
  let frameAt=null, replayAt=null, lastFocus=null, lastMode=null;
  let lastBallCam=null, lastRearView=null, lastCarVisible=null, reset=true;
  let attached=false, hasCarPos=false;
  const api={
    id:'replay-lab-camera-polish',
    invalidate(){reset=true;hasCarPos=false;},
    beforeRender(ctx){
      const cp=getCameraPlugin();
      const mode=cp?.getMode?.();
      const state=ctx.player.getState();
      const focus=getFollowId();
      const time=state.currentTime;
      const now=performance.now();
      if(mode!=='follow'||!focus){
        attached=false;reset=true;hasCarPos=false;lastMode=mode;lastFocus=focus;
        lastBallCam=null;lastRearView=null;lastCarVisible=null;
        return;
      }
      const cam=ctx.camera;
      const track=findCameraTrack(ctx.player.replay,focus);
      const recorded=recordedCameraAtTime(track,ctx.player.replay,time);
      const isBallCam=cp.getBallCam();
      const rearView=recorded.behind===true;

      // Locate followed vehicle in frame render context
      const carEntry=ctx.cars?.find(c=>c.id===focus);
      const carObj=carEntry?.object3d;
      const carVisible=carEntry?.visible!==false;

      if(carObj) {
        carObj.getWorldPosition(anchor);
      }

      // Check for vehicle teleport / goal reset / demolition respawn
      let carTeleported=false;
      if(hasCarPos && carObj) {
        const dist=anchor.distanceTo(lastCarPos);
        // Supersonic limit is ~2300 UU/s. Any jump > 1500 units or > 3500*dt is an actor lifecycle discontinuity.
        const dtReplay = replayAt !== null ? Math.abs(time - replayAt) : 0;
        if(dist > Math.max(1500, dtReplay * 3500)) {
          carTeleported=true;
        }
      }
      if(carObj) {
        lastCarPos.copy(anchor);
        hasCarPos=true;
      }

      const carRespawned = lastCarVisible !== null && !lastCarVisible && carVisible;

      // Free-look / rear-view optional reconstruction
      if(getReplayLook() && (!isBallCam || rearView)) {
        if(carObj) {
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
            cam.lookAt(anchor);
          }
        }
      }

      // Enforce floor and arena bounds
      cam.position.x=THREE.MathUtils.clamp(cam.position.x,-ARENA_X_LIMIT,ARENA_X_LIMIT);
      cam.position.z=THREE.MathUtils.clamp(cam.position.z,-ARENA_Z_LIMIT,ARENA_Z_LIMIT);
      const minFloor = carObj ? Math.max(ARENA_Y_MIN, anchor.y + 35) : ARENA_Y_MIN;
      cam.position.y=THREE.MathUtils.clamp(cam.position.y,minFloor,ARENA_Y_MAX);

      // Keep follow-camera horizon strictly upright (prevent disorienting camera roll during aerial flips and wall rides)
      const forward = new THREE.Vector3();
      cam.getWorldDirection(forward);
      right.crossVectors(forward, UP);
      if(right.lengthSq() > 0.001) {
        right.normalize();
        const correctedUp = new THREE.Vector3().crossVectors(right, forward).normalize();
        cam.up.copy(correctedUp);
        const rotMat = new THREE.Matrix4();
        rotMat.makeBasis(right, correctedUp, forward.clone().negate());
        cam.quaternion.setFromRotationMatrix(rotMat);
      } else {
        cam.up.set(0,1,0);
      }

      const dt=frameAt===null?1/60:Math.max(0,Math.min(.10,(now-frameAt)/1000));
      const jumped=replayAt!==null && Math.abs(time-replayAt)>Math.max(0.20,dt*5*Math.max(1,state.speed||1));

      // Native Ball Cam ON/OFF, rear-view changes, player switches, goal resets,
      // and demolition respawns are genuine cuts. NEVER smooth across them!
      const needSnap=reset||!attached||jumped||carTeleported||carRespawned||
        focus!==lastFocus||mode!==lastMode||isBallCam!==lastBallCam||rearView!==lastRearView;

      if(!needSnap){
        const alpha=1-Math.exp(-32*dt);
        cam.position.lerpVectors(prevPosition,cam.position,alpha);
        cam.quaternion.copy(prevQuaternion).slerp(cam.quaternion,alpha);
      }
      prevPosition.copy(cam.position);
      prevQuaternion.copy(cam.quaternion);
      frameAt=now;replayAt=time;lastMode=mode;lastFocus=focus;
      lastBallCam=isBallCam;lastRearView=rearView;lastCarVisible=carVisible;
      reset=false;attached=true;
    },
    teardown(){reset=true;attached=false;hasCarPos=false;frameAt=null;replayAt=null;
      lastBallCam=null;lastRearView=null;lastCarVisible=null;},
  };
  return api;
}

import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {createCameraPolishPlugin} from '../src/camera-polish.js';

// This tests the actual camera object, not just a HUD label or mode enum.
// Native Ball/Car camera switches are immediate discontinuities; smoothing
// between them would temporarily show an impossible viewpoint.
test('recorded Ball Cam switch snaps rather than gliding between camera poses',()=>{
  let ballCam=false;
  const cameraPlugin={getMode:()=> 'follow',getBallCam:()=>ballCam};
  const polish=createCameraPolishPlugin({
    getCameraPlugin:()=>cameraPlugin,
    getFollowId:()=> 'player-a',
    getReplayLook:()=>false,
  });
  const camera=new THREE.PerspectiveCamera();
  const model={frames:[{time:0}],players:[{id:'player-a',frames:[{}],cameraEvents:[]}]};
  const state={currentTime:0,speed:1};
  const ctx={
    camera,cars:[],
    player:{replay:model,getState:()=>state},
  };
  camera.position.set(0,100,0);
  polish.beforeRender(ctx);
  ballCam=true;
  camera.position.set(500,200,300);
  polish.beforeRender(ctx);
  assert.ok(camera.position.distanceTo(new THREE.Vector3(500,200,300)) < 1e-6,
    'a native Ball Cam switch must cut to the new camera pose');
  camera.position.set(1000,200,300);
  polish.beforeRender(ctx);
  assert.ok(camera.position.x>=500 && camera.position.x<1000,
    'subsequent same-mode motion should still stabilize, not hard-snap');
  polish.teardown();
});

test('vehicle teleport across goal reset cuts immediately instead of gliding across arena',()=>{
  const cameraPlugin={getMode:()=>'follow',getBallCam:()=>true};
  const polish=createCameraPolishPlugin({
    getCameraPlugin:()=>cameraPlugin,
    getFollowId:()=>'player-a',
    getReplayLook:()=>false,
  });
  const camera=new THREE.PerspectiveCamera();
  const carObj=new THREE.Object3D();
  carObj.position.set(2800, 20, -200);
  const model={frames:[{time:0}],players:[{id:'player-a',frames:[{}],cameraEvents:[]}]};
  const state={currentTime:15.0,speed:1};
  const ctx={
    camera,
    cars:[{id:'player-a',visible:true,object3d:carObj}],
    player:{replay:model,getState:()=>state},
  };
  camera.position.set(2500, 100, -200);
  polish.beforeRender(ctx);

  // Goal scored / kickoff respawn: car jumps 5,000 units across map
  carObj.position.set(-2000, 20, -2500);
  camera.position.set(-2300, 100, -2500);
  state.currentTime=15.033; // Normal tick increment, but car jumped
  polish.beforeRender(ctx);

  assert.ok(camera.position.distanceTo(new THREE.Vector3(-2300, 100, -2500)) < 1e-4,
    'camera must snap immediately to respawn location rather than gliding across midfield');
  polish.teardown();
});

test('camera bounds enforce correct goal-to-goal and sidewall dimensions',()=>{
  const cameraPlugin={getMode:()=>'follow',getBallCam:()=>true};
  const polish=createCameraPolishPlugin({
    getCameraPlugin:()=>cameraPlugin,
    getFollowId:()=>'player-a',
    getReplayLook:()=>false,
  });
  const camera=new THREE.PerspectiveCamera();
  const carObj=new THREE.Object3D();
  carObj.position.set(0, 20, 0);
  const model={frames:[{time:0}],players:[{id:'player-a',frames:[{}],cameraEvents:[]}]};
  const state={currentTime:1.0,speed:1};
  const ctx={
    camera,
    cars:[{id:'player-a',visible:true,object3d:carObj}],
    player:{replay:model,getState:()=>state},
  };

  // Test X goal limit (+-5050)
  camera.position.set(6000, 100, 0);
  polish.beforeRender(ctx);
  assert.equal(camera.position.x, 5050, 'X must clamp to 5050 goal limit');

  // Test Z sidewall limit (+-4030)
  polish.invalidate();
  camera.position.set(0, 100, 5000);
  polish.beforeRender(ctx);
  assert.equal(camera.position.z, 4030, 'Z must clamp to 4030 sidewall limit');

  // Test floor height limit (>= 45)
  polish.invalidate();
  camera.position.set(0, -100, 0);
  polish.beforeRender(ctx);
  assert.ok(camera.position.y >= 45, 'Y must not penetrate floor');
  polish.teardown();
});

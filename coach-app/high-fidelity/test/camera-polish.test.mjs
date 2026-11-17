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

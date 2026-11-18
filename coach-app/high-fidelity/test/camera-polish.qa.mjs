import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {createCameraPolishPlugin,makeUsableChasePose} from '../src/camera-polish.js';

// This tests the actual camera object, not just a HUD label or mode enum.
const MIN_TEST_CHASE_HEIGHT=225;
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
  assert.ok(camera.position.distanceTo(new THREE.Vector3(500,200,300))<1e-6,
    'a native camera switch must cut without interpolating when no car anchor exists');
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

  assert.ok(camera.position.x<-2500 && camera.position.z===-2500,
    'camera should immediately take the new elevated chase position at respawn');
  assert.ok(camera.position.y>=carObj.position.y+MIN_TEST_CHASE_HEIGHT,
    'follow camera is elevated enough to see the car and field');
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

test('follow camera maintains upright horizon during aerial flips and wall driving',()=>{
  const cameraPlugin={getMode:()=>'follow',getBallCam:()=>true};
  const polish=createCameraPolishPlugin({
    getCameraPlugin:()=>cameraPlugin,
    getFollowId:()=>'player-a',
    getReplayLook:()=>false,
  });
  const camera=new THREE.PerspectiveCamera();
  const carObj=new THREE.Object3D();
  carObj.position.set(0, 500, 0); // Airborne
  // Inverted upside-down car roll (e.g. ceiling shot or flip reset)
  carObj.rotation.set(0, 0, Math.PI);
  const model={frames:[{time:0}],players:[{id:'player-a',frames:[{}],cameraEvents:[]}]};
  const state={currentTime:2.0,speed:1};
  const ctx={
    camera,
    cars:[{id:'player-a',visible:true,object3d:carObj}],
    player:{replay:model,getState:()=>state},
  };

  // Position camera behind and below inverted car, looking forward
  camera.position.set(-250, 480, 0);
  camera.lookAt(carObj.position);
  // Apply a disorienting roll to camera
  camera.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI * 0.8));
  
  polish.beforeRender(ctx);

  // Measure camera right vector in world space:
  const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion);
  // An upright horizon requires the right vector to lie in the horizontal plane (Y == 0)
  assert.ok(Math.abs(right.y) < 1e-4, `camera right vector Y must be zero for level horizon, got ${right.y}`);
  
  // Camera up vector must point upward in world space (Y > 0)
  const up = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion);
  assert.ok(up.y > 0.5, `camera up vector must point upward, got ${up.y}`);
  polish.teardown();
});

test('low back-tire follow camera is elevated and backed off before rendering',()=>{
  const camera=new THREE.PerspectiveCamera();
  const a=new THREE.Vector3(0,17,0);
  camera.position.set(-120,36,60);
  camera.lookAt(0,20,0);
  makeUsableChasePose(camera,a);
  assert.ok(camera.position.y>=242,'eye must be higher than the tire line');
  assert.ok(Math.hypot(camera.position.x,camera.position.z)>=600,
    'minimum horizontal distance keeps the vehicle from filling the view');
  const dir=new THREE.Vector3();camera.getWorldDirection(dir);
  assert.ok(dir.y<0,'elevated chase eye should look down toward the field');
});
test('ball orbit camera is leveled rather than left at an arbitrary roll',()=>{
  const mode={getMode:()=> 'ballOrbit',getBallCam:()=>true};
  const polish=createCameraPolishPlugin({getCameraPlugin:()=>mode,getFollowId:()=>null,getReplayLook:()=>false});
  const camera=new THREE.PerspectiveCamera();
  camera.position.set(100,550,750);camera.lookAt(0,0,0);
  camera.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1),0.4));
  polish.beforeRender({camera,player:{getState:()=>({currentTime:0}),replay:{}}});
  const right=new THREE.Vector3(1,0,0).applyQuaternion(camera.quaternion);
  assert.ok(Math.abs(right.y)<0.0001,'ball orbit horizon must stay horizontal');
});

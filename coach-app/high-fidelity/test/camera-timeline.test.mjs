import test from 'node:test';
import assert from 'node:assert/strict';
import {createRecordedCameraSwitchPlugin} from '../src/recorded-camera-switch.js';
import {
  findCameraTrack,recordedCameraAt,cameraEvidence,
  cameraSwitchMoments,displayCameraMode,
} from '../src/camera-timeline.js';
const replay={
  frames:[{time:0},{time:.1},{time:.2},{time:.3},{time:.4},{time:.5}],
  players:[{
    id:'epic:1',name:'Quarts',frames:[
      {cameraYaw:null,cameraPitch:null},
      {cameraYaw:0,cameraPitch:0},
      {cameraYaw:.2,cameraPitch:-.1},
      {cameraYaw:null,cameraPitch:null},
      {cameraYaw:-.35,cameraPitch:.1},
      {cameraYaw:0,cameraPitch:0}
    ],
    cameraEvents:[
      {frame:0,ballCamActive:true,behindViewActive:null},
      {frame:2,ballCamActive:false,behindViewActive:false},
      {frame:4,ballCamActive:null,behindViewActive:true},
      {frame:5,ballCamActive:true,behindViewActive:false}
    ],
  }]
};
const track=replay.players[0];
test('camera timeline carries real Ball Cam OFF state and rear look at exact frames',()=>{
  assert.equal(recordedCameraAt(track,0).ballCam,true);
  assert.equal(recordedCameraAt(track,2).ballCam,false);
  assert.equal(recordedCameraAt(track,3).ballCam,false);
  assert.equal(recordedCameraAt(track,4).behind,true);
  assert.equal(recordedCameraAt(track,4).ballCam,false);
  assert.equal(recordedCameraAt(track,5).ballCam,true);
  assert.equal(recordedCameraAt(track,2).yaw,.2);
  assert.equal(recordedCameraAt(track,3).yaw,null);
});
test('native camera events map to clock times and stay sorted',()=>{
  const moments=cameraSwitchMoments(replay,track);
  assert.deepEqual(moments.map(x=>x.label),[
    'Ball Cam on','Ball Cam off','Rear look','Ball Cam on'
  ]);
  assert.deepEqual(moments.map(x=>x.time),[0,.2,.4,.5]);
});
test('camera status distinguishes native, forced and unavailable',()=>{
  assert.equal(displayCameraMode(recordedCameraAt(track,2),'recorded',true),'CAR CAM');
  assert.equal(displayCameraMode(recordedCameraAt(track,2),'ball',false),'BALL CAM');
  assert.equal(displayCameraMode(recordedCameraAt(track,4),'recorded',false),'REAR LOOK');
  assert.equal(displayCameraMode(recordedCameraAt(track,4),'recorded',false,true,false),'CAR CAM');
  assert.equal(displayCameraMode(recordedCameraAt(track,3),'recorded',null,false),'FREE / ORBIT');
  assert.equal(displayCameraMode(recordedCameraAt(null,0),'recorded',null),'CAMERA UNKNOWN');
  assert.equal(displayCameraMode(recordedCameraAt(null,0),'recorded',true),'CAMERA UNKNOWN');
});
test('unknown or missing replay camera data must not be called Ball Cam ON',()=>{
  const missing={id:'other',name:'None',frames:[{}],cameraEvents:[]};
  assert.equal(findCameraTrack(replay,'bad','Quarts'),track);
  assert.equal(findCameraTrack(replay,'bad','bad'),null);
  assert.equal(recordedCameraAt(missing,0).ballCam,null);
  assert.equal(cameraEvidence(missing).events,0);
  assert.equal(cameraSwitchMoments(replay,missing).length,0);
});
test('replicated swivel and switching events are counted accurately',()=>{
  assert.deepEqual(cameraEvidence(track),{
    events:4,ballOff:1,ballOn:2,rear:1,lookSamples:4,hasSwivel:true
  });
});

test('recorded Ball Cam ON/OFF updates camera renderer, including backward seek',()=>{
  let current=false,override='recorded',focus='epic:1';
  const applied=[];
  const cam={getBallCam:()=>current,setBallCam:next=>{current=next;applied.push(next);}};
  const plugin=createRecordedCameraSwitchPlugin({
    getCameraPlugin:()=>cam,getFollowId:()=>focus,getCameraOverride:()=>override,
  });
  const ctx={player:{replay,adapter:{playerList:[{id:'epic:1',name:'Quarts'}]}},
    state:{cameraViewMode:'follow'},frameIndex:0};
  plugin.beforeRender(ctx);
  assert.equal(current,true,'frame-zero recorded ON cannot inherit false fallback');
  ctx.frameIndex=2;plugin.beforeRender(ctx);
  assert.equal(current,false,'native Car Cam OFF must actually update plugin');
  ctx.frameIndex=5;plugin.beforeRender(ctx);
  assert.equal(current,true,'backward/forward scrubbing must restore native ON state');
  assert.deepEqual(applied,[true,false,true]);
  override='car';ctx.frameIndex=2;plugin.beforeRender(ctx);
  assert.deepEqual(applied,[true,false,true],'forced mode should be respected');
  ctx.state.cameraViewMode='free';override='recorded';plugin.beforeRender(ctx);
  assert.deepEqual(applied,[true,false,true],'free camera must not be overridden');
});

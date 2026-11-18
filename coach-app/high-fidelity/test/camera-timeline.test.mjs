import test from 'node:test';
import assert from 'node:assert/strict';
import {createRecordedCameraSwitchPlugin} from '../src/recorded-camera-switch.js';
import {
  findCameraTrack,recordedCameraAt,recordedCameraAtTime,replayFrameAtTime,cameraEvidence,
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
test('camera event boundary lookup uses ReplayModel clock, independent of renderer index',()=>{
  assert.equal(replayFrameAtTime(replay,0),0);
  assert.equal(replayFrameAtTime(replay,.19999998),2); // native Float32 rounding
  assert.equal(replayFrameAtTime(replay,.15),1);
  assert.equal(recordedCameraAtTime(track,replay,.20).ballCam,false);
  assert.equal(recordedCameraAtTime(track,replay,.49999998).ballCam,true);
  assert.equal(recordedCameraAtTime(track,replay,.30).ballCam,false);
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

test('recorded Ball Cam ON/OFF updates actual plugin at event boundaries and seeks',()=>{
  let current=false,override='recorded',focus='epic:1';
  const applied=[];
  const cam={getBallCam:()=>current,setBallCam:next=>{current=next;applied.push(next);}};
  const plugin=createRecordedCameraSwitchPlugin({
    getCameraPlugin:()=>cam,getFollowId:()=>focus,getCameraOverride:()=>override,
  });
  const ctx={player:{replay,adapter:{playerList:[{id:'epic:1',name:'Quarts'}]}},
    state:{cameraViewMode:'follow',currentTime:0},time:0,frameIndex:0};
  plugin.beforeRender(ctx);
  assert.equal(current,true,'frame-zero recorded ON cannot inherit false fallback');
  // Even a renderer-adapter frame index lagging behind the model must not
  // suppress a native event at its precise replay time.
  ctx.frameIndex=1;
  ctx.time=.19999998;
  plugin.beforeRender(ctx);
  assert.equal(current,false,'native OFF is applied using event timestamp');
  ctx.state.currentTime=.49999998;
  plugin.onStateChange(ctx);
  assert.equal(current,true,'backward seek/native ON updates immediately');
  assert.deepEqual(applied,[true,false,true]);
  override='car';ctx.time=.2;plugin.beforeRender(ctx);
  assert.deepEqual(applied,[true,false,true],'forced mode is respected');
  ctx.state.cameraViewMode='free';override='recorded';plugin.onStateChange(ctx);
  assert.deepEqual(applied,[true,false,true],'free camera is never overridden');
});

test('unsorted native events cannot overwrite a newer recorded camera state',()=>{
  const scrambled={
    ...track,
    cameraEvents:[
      {frame:5,ballCamActive:true,behindViewActive:false},
      {frame:2,ballCamActive:false,behindViewActive:false},
      {frame:4,ballCamActive:null,behindViewActive:true},
      {frame:0,ballCamActive:true,behindViewActive:null},
    ],
  };
  assert.equal(recordedCameraAt(scrambled,3).ballCam,false);
  assert.equal(recordedCameraAt(scrambled,4).ballCam,false);
  assert.equal(recordedCameraAt(scrambled,4).behind,true);
  assert.equal(recordedCameraAt(scrambled,5).ballCam,true);
  assert.equal(recordedCameraAt(scrambled,5).behind,false);
});

test('ambiguous camera tracks are not silently attributed to another player',()=>{
  const ambiguous={players:[
    {id:'same',name:'Alpha'},
    {id:'same',name:'Beta'},
    {id:'unique1',name:'Dup'},
    {id:'unique2',name:'Dup'},
  ]};
  assert.equal(findCameraTrack(ambiguous,'same'),null);
  assert.equal(findCameraTrack(ambiguous,'missing','Dup'),null);
  assert.equal(findCameraTrack(ambiguous,'unique1'),ambiguous.players[2]);
});

test('recorded camera without known events uses a neutral non-claimed fallback',()=>{
  let current=true,override='recorded',focus='unknown';
  const camera={getBallCam:()=>current,setBallCam:v=>{current=v;}};
  const plugin=createRecordedCameraSwitchPlugin({
    getCameraPlugin:()=>camera,getFollowId:()=>focus,
    getCameraOverride:()=>override,
  });
  const player={replay,adapter:{playerList:[{id:'unknown',name:'NoData'}]}};
  plugin.beforeRender({player,time:.5,state:{cameraViewMode:'follow',currentTime:.5}});
  assert.equal(current,false,'unknown recorded view must not inherit stale Ball Cam ON');
  assert.equal(displayCameraMode({ballCam:null},'recorded',current),'CAMERA UNKNOWN');
  override='ball';
  camera.setBallCam(true);
  plugin.beforeRender({player,time:0,state:{cameraViewMode:'follow',currentTime:0}});
  assert.equal(current,true,'explicit forced Ball Cam still works');
});

test('long native camera histories support many smooth seeks without rescanning every event',()=>{
  const frames=Array.from({length:1500},(_,i)=>({time:i/60,cameraYaw:0,cameraPitch:0}));
  const cameraEvents=Array.from({length:1200},(_,i)=>({
    frame:i,ballCamActive:i%2===0,behindViewActive:i%5===0
  }));
  let reads=0;
  // Instrument event *entries*. Linear per-frame scans trigger 1200 reads
  // for every camera render; indexed binary lookup never touches them again.
  const observedEvents=new Proxy(cameraEvents,{
    get(target,key,receiver){
      if(typeof key==='string' && /^(0|[1-9][0-9]*)$/.test(key))reads++;
      return Reflect.get(target,key,receiver);
    }
  });
  const player={frames,cameraEvents:observedEvents};
  assert.equal(recordedCameraAt(player,0).ballCam,true);
  const initialReads=reads;
  assert.ok(initialReads>=1200);
  for(let timeIndex=1499;timeIndex>=0;timeIndex-=3){
    const frame=Math.min(timeIndex,1199);
    const got=recordedCameraAt(player,timeIndex);
    assert.equal(got.ballCam,frame%2===0, 'same historical state on backwards seek');
    assert.equal(got.behind,frame%5===0, 'latest rear toggle remains accurate');
  }
  assert.equal(reads,initialReads,'per-render lookup must not rescan source event array');
});

test('unsorted same-frame camera signals preserve source-order tie precedence',()=>{
  const custom={frames:[{}, {}, {}, {}, {}],cameraEvents:[
    {frame:3,ballCamActive:true},
    {frame:1,ballCamActive:true},
    {frame:3,ballCamActive:false},
    {frame:3,behindViewActive:true},
    {frame:0,behindViewActive:false},
    {frame:3,behindViewActive:false},
    {frame:4,driving:true},
  ]};
  assert.equal(recordedCameraAt(custom,2).ballCam,true);
  assert.equal(recordedCameraAt(custom,3).ballCam,false);
  assert.equal(recordedCameraAt(custom,3).behind,false);
  assert.equal(recordedCameraAt(custom,3).lastSwitchFrame,3);
  assert.equal(recordedCameraAt(custom,4).driving,true);
  assert.equal(recordedCameraAt(custom,0).driving,null);
});

test('replacing or appending decoded camera timeline invalidates cache, but old replay does not contaminate new',()=>{
  const one={frames:[{}, {}, {}],cameraEvents:[{frame:0,ballCamActive:true}]};
  const another={frames:[{}, {}, {}],cameraEvents:[{frame:0,ballCamActive:false}]};
  assert.equal(recordedCameraAt(one,2).ballCam,true);
  assert.equal(recordedCameraAt(another,2).ballCam,false);
  one.cameraEvents.push({frame:2,ballCamActive:false});
  assert.equal(recordedCameraAt(one,1).ballCam,true);
  assert.equal(recordedCameraAt(one,2).ballCam,false);
  one.cameraEvents=[{frame:0,ballCamActive:false}];
  assert.equal(recordedCameraAt(one,0).ballCam,false);
});

test('future camera toggles remain unavailable at pre-switch frames and missing switches remain unknown',()=>{
  const onlyFuture={frames:Array.from({length:20},()=>({})),cameraEvents:[
    {frame:18,ballCamActive:true,behindViewActive:true},
    {frame:19,ballCamActive:false},
    {frame:-1,ballCamActive:false},
    {frame:NaN,ballCamActive:true},
  ]};
  const atTen=recordedCameraAt(onlyFuture,10);
  assert.equal(atTen.ballCam,null);
  assert.equal(atTen.behind,null);
  assert.equal(atTen.lastSwitchFrame,-1);
  assert.equal(atTen.hasRecordedSwitch,true);
  assert.equal(recordedCameraAt(onlyFuture,18).ballCam,true);
  assert.equal(recordedCameraAt(onlyFuture,19).ballCam,false);
});

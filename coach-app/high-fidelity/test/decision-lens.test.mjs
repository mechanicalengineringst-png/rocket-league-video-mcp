import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

// Run the same browser classic script in a clean VM. Node 22's automatic
// ESM detection can otherwise make require() of a browser IIFE return an
// empty namespace. The VM verifies the actual window-global integration.
const scope={};
scope.globalThis=scope;
const source=readFileSync(new URL('../../coach_app/static/decision-lens.js',import.meta.url),'utf8');
runInNewContext(source,scope,{filename:'decision-lens.js'});
const lens=scope.ReplayLabDecisionLens;
assert.equal(typeof lens?.buildWindow,'function');
const players=[
  {id:'p1',team:'blue'},
  {id:'p2',team:'blue'},
  {id:'p3',team:'orange'},
  {id:'p4',team:'orange'}
];

function observedReplay(){
  const frames=[];
  for(let i=0;i<=100;i++){
    const t=+(i/10).toFixed(3);
    frames.push({
      t,
      ball:{x:1000+20*t,y:0,z:100+t},
      cars:{
        p1:{x:100*t,y:1000,z:17,boost:Math.max(0,100-i),velocity:[100,0,0]},
        p2:{x:0,y:1000,z:17,boost:40,velocity:[0,0,0]},
        p3:{x:0,y:0,z:17,boost:50,velocity:[0,0,0]},
        p4:{x:4000,y:0,z:17,boost:50,velocity:[0,0,0]}
      }
    });
  }
  return {players,frames,source:'native-replay',duration:10};
}

test('records only last frame at/before t0 and bounds an actual two-second followthrough',()=>{
  const replay=observedReplay();
  const original=JSON.stringify(replay);
  const w=lens.buildWindow(replay,'p1',5.05);
  assert.equal(w.schema,'ReplayDecisionLensV0');
  assert.equal(w.t0,5.05);
  assert.equal(w.start,2.05);
  assert.equal(w.end,7.05);
  assert.equal(w.anchor.sampleTime,5.0);
  assert.equal(w.anchor.ageMs,50);
  assert.equal(w.after.sampleTime,7.0);
  assert.equal(w.predictionsMade,false);
  assert.equal(w.coachingGradeAssigned,false);
  assert.equal(w.anchor.dots.length,5);
  assert.equal(w.anchor.complete,true);
  assert.equal(w.anchor.metrics.focusBoost,50);
  assert.equal(w.anchor.metrics.focusSpeed,100);
  assert.equal(w.anchor.metrics.ballHeight,105);
  assert.equal(w.anchor.metrics.teammateSeparation2D,500);
  assert.equal(w.anchor.metrics.opponentBallNearest2D,1100);
  assert.ok(w.recordedAfterTrace.focus.length>0);
  assert.ok(w.recordedAfterTrace.focus.every(p=>p.t>5.05 && p.t<=7.05));
  assert.ok(w.recordedAfterTrace.ball.every(p=>p.t>5.05 && p.t<=7.05));
  assert.equal(JSON.stringify(replay),original,'read-only view must not mutate replay');
});

test('future outcome rewrites leave every predecision metric and position unchanged',()=>{
  const replay=observedReplay();
  const a=lens.buildWindow(replay,'p1',5.0);
  for(const frame of replay.frames){
    if(frame.t>5){
      frame.ball.x=-4000;
      frame.ball.y=4400;
      frame.cars.p1.boost=0;
      frame.cars.p3.x=4000;
      frame.cars.p4.y=-4000;
    }
  }
  const b=lens.buildWindow(replay,'p1',5.0);
  assert.deepEqual(a.anchor,b.anchor);
  assert.notDeepEqual(a.after,b.after);
  assert.notDeepEqual(a.recordedAfterTrace,b.recordedAfterTrace);
  assert.equal(b.temporalBoundary,'anchor_at_or_before_t0_future_recording_separate');
});

test('missing data abstains, rather than displaying stale or fabricated context',()=>{
  const replay=observedReplay();
  assert.equal(lens.buildWindow(replay,'not-rostered',5),null);
  assert.equal(lens.buildWindow(replay,'p1',-1),null);
  assert.equal(lens.buildWindow(replay,'p1',11),null);
  assert.equal(lens.buildWindow(replay,'p1',Number.NaN),null);
  assert.equal(lens.buildWindow(replay,'p1',5,99,1),null);
  const sparse={
    players,frames:[replay.frames[0],replay.frames[10],replay.frames[20]]
  };
  assert.equal(lens.buildWindow(sparse,'p1',1.48),null);
  const missing=observedReplay();
  delete missing.frames[50].ball.z;
  assert.equal(lens.buildWindow(missing,'p1',5).anchor.metrics.ballHeight,null);
  assert.equal(lens.buildWindow(missing,'p1',5).anchor.complete,false);
});

test('all four car observations required for a complete two-versus-two snapshot',()=>{
  const replay=observedReplay();
  replay.frames[50].cars.p4.demolished=true;
  const w=lens.buildWindow(replay,'p1',5);
  assert.equal(w.anchor.complete,false);
  assert.equal(w.anchor.dots.length,4);
  assert.equal(w.anchor.metrics.opponentBallNearest2D,1100);
  replay.frames[50].cars.p2=null;
  const w2=lens.buildWindow(replay,'p1',5);
  assert.equal(w2.anchor.metrics.teammateSeparation2D,null);
  assert.equal(w2.anchor.complete,false);
});

test('t0 near end clips safely and never synthesizes future positions',()=>{
  const replay=observedReplay();
  const final=lens.buildWindow(replay,'p1',10.0);
  assert.equal(final.end,10.0);
  assert.equal(final.after,null);
  assert.deepEqual(final.recordedAfterTrace,{focus:[],ball:[]});
  const early=lens.buildWindow(replay,'p1',0.2);
  assert.equal(early.start,0);
  assert.equal(early.anchor.sampleTime,0.2);
  assert.equal(early.after.sampleTime,2.2);
});

test('loop playback wraps bounded source time and rejects malformed input',()=>{
  const w=lens.buildWindow(observedReplay(),'p1',5.0);
  assert.ok(w);
  assert.ok(Math.abs(lens.loopNext(w.end-0.04,0.1,1,w)- (w.start+0.06))<1e-8);
  assert.ok(Math.abs(lens.loopNext(w.start,0.25,2,w)-(w.start+0.5))<1e-8);
  assert.ok(Math.abs(lens.loopNext(10,0.1,1,w)-(w.start+0.1))<1e-8);
  assert.equal(lens.loopNext(w.start,-2,1,w),null);
  assert.equal(lens.loopNext(w.start,0.1,0,w),null);
  assert.equal(lens.loopNext(w.start,0.1,1,{start:4,end:4}),null);
});

test('future recorded path uses actual samples only and caps high-frequency traces',()=>{
  const replay=observedReplay();
  const superdense=[];
  for(let i=0;i<=3000;i++){
    const sample=replay.frames[Math.min(100,Math.floor(i/30))];
    superdense.push({...sample,t:i/300});
  }
  replay.frames=superdense;
  const w=lens.buildWindow(replay,'p1',5);
  assert.ok(w);
  assert.ok(w.recordedAfterTrace.focus.length<=101);
  assert.ok(w.recordedAfterTrace.ball.length<=101);
  assert.equal(w.recordedAfterTrace.focus.at(-1).x,
    superdense.filter(f=>f.t>5&&f.t<=7).at(-1).cars.p1.x);
});

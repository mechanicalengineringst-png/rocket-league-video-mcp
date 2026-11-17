'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
require('../coach_app/static/viewer3d-math.js');
const M=globalThis.ReplayLabViewMath;

const close=(actual,expected,eps=1e-5)=>{
  assert.ok(Math.abs(actual-expected)<eps, String(actual)+' != '+String(expected));
};
const vectorClose=(actual,expected)=>{
  assert.equal(actual.length,expected.length);
  actual.forEach((x,i)=>close(x,expected[i]));
};
const cross=(a,b)=>[
  a[1]*b[2]-a[2]*b[1],
  a[2]*b[0]-a[0]*b[2],
  a[0]*b[1]-a[1]*b[0]
];

test('Rocket League coordinates convert without mirroring height',()=>{
  vectorClose(M.rlToThree([4096,-5120,2044]),[-4096,2044,5120]);
  vectorClose(M.replayPosition({x:400,y:200,z:150}),[-4,1.5,-2]);
});

test('a level car faces the true replay nose and preserves world up',()=>{
  const a=M.basisFromRotation([0,0,0]);
  vectorClose(a.forward,[-1,0,0]);
  vectorClose(a.right,[0,0,1]);
  vectorClose(a.up,[0,1,0]);
  vectorClose(cross(a.right,a.up),a.forward);
});

test('recorded yaw changes the car nose without confusing +Y and -Y',()=>{
  const a=M.basisFromRotation([0,0,Math.PI/2]);
  vectorClose(a.forward,[0,0,-1]);
  vectorClose(cross(a.right,a.up),a.forward);
});

test('full roll and pitch preserve orthonormal aerial attitude',()=>{
  const a=M.basisFromRotation([Math.PI/3,Math.PI/5,-Math.PI/4]);
  const length=v=>Math.hypot(...v);
  const dot=(a,b)=>a.reduce((n,v,i)=>n+v*b[i],0);
  for(const v of [a.right,a.up,a.forward])close(length(v),1);
  close(dot(a.right,a.up),0);
  close(dot(a.up,a.forward),0);
  close(dot(a.right,a.forward),0);
  vectorClose(cross(a.right,a.up),a.forward);
  assert.notDeepEqual(a.up,[0,1,0]); // Old lookAt discarded roll.
});

test('close chase stays behind the car instead of inside the body',()=>{
  const car={x:0,y:0,z:17,rotation:[0,0,0]};
  const p=M.planCamera('pov',car,{x:250,y:0,z:93});
  assert.ok(p);
  assert.ok(Math.hypot(...p.position.map((v,i)=>v-M.replayPosition(car)[i]))>3.5);
  assert.ok(p.position[1]>=.85);
  assert.equal(p.fov,94);
});

test('Ball Cam is car-anchored and cannot sit inside the ball',()=>{
  const car={x:100,y:0,z:17,rotation:[0,0,0]};
  const center=M.replayPosition(car);
  // Ball at camera's natural position is a real dribble / bounce edge case.
  const ball={x:-540,y:0,z:327};
  const p=M.planCamera('ball',car,ball);
  const b=M.replayPosition(ball);
  assert.ok(p);
  const distance=Math.hypot(...p.position.map((v,i)=>v-b[i]));
  assert.ok(distance>=2.99, 'Ball clips camera');
  assert.ok(Math.hypot(...p.position.map((v,i)=>v-center[i]))>2);
});

test('camera can follow aerials but never crosses the ceiling or floor',()=>{
  const car={x:0,y:0,z:2020,rotation:[0,0,Math.PI/2]};
  const p=M.planCamera('follow',car,{x:0,y:0,z:2000});
  assert.ok(p.position[1]<=19.2);
  assert.ok(M.planCamera('not-a-mode',car)===null);
  assert.ok(M.planCamera('pov',{x:0,y:0,z:17})===null);
});

test('missing Euler roll uses explicit forward-only fallback',()=>{
  const a=M.basisFromRotation(null,[0,1,0]);
  assert.equal(a.source,'forward-only');
  vectorClose(a.forward,[0,0,-1]);
  assert.equal(M.basisFromRotation(null,null),null);
});

test('ten-second large pads and four-second small pads distinguish respawn',()=>{
  const a=M.padCountdown(4.5,1,true);
  const b=M.padCountdown(4.5,1,false);
  assert.equal(a.available,false);
  assert.equal(b.available,false);
  close(a.remaining,6.5);
  close(b.remaining,0.5);
  assert.equal(M.padCountdown(11,1,true).available,true);
});

test('quatFromBasis and quatSlerp provide smooth continuous attitude',()=>{
  const b0=M.basisFromRotation([0,0,Math.PI/2]);
  const b1=M.basisFromRotation([-Math.PI/2,0,Math.PI/2]);
  const q0=M.quatFromBasis(b0.right,b0.up,b0.forward);
  const q1=M.quatFromBasis(b1.right,b1.up,b1.forward);
  const qMid=M.quatSlerp(q0,q1,0.5);
  const bMid=M.basisFromQuat(qMid);
  // Halfway through a forward flip from kickoff, nose dips 45 deg down
  close(bMid.forward[1], -Math.SQRT1_2, 0.05);
  close(bMid.forward[2], -Math.SQRT1_2, 0.05);
});

test('sampleReplayState interpolates positions using Hermite spline with velocity',()=>{
  const frames=[
    {t:1.0,ball:{x:0,y:0,z:100,velocity:[0,0,1000]},cars:{p1:{x:0,y:0,z:17,velocity:[0,1000,0],rotation:[0,0,Math.PI/2]}}},
    {t:2.0,ball:{x:0,y:0,z:1100,velocity:[0,0,1000]},cars:{p1:{x:0,y:1000,z:17,velocity:[0,1000,0],rotation:[0,0,Math.PI/2]}}}
  ];
  const sample=M.sampleReplayState(frames, 1.5);
  assert.ok(sample);
  close(sample.t, 1.5);
  close(sample.ball.z, 600, 1.0);
  close(sample.cars.p1.y, 500, 1.0);
  assert.ok(Array.isArray(sample.cars.p1.quaternion));
});

test('padStateAt matches contract resets and cooldowns',()=>{
  const timeline={
    pads:[{id:0,x:0,y:0,big:true,respawnSeconds:10}],
    resets:[4.0, 20.0],
    pickups:[{t:5.0,padId:0,playerId:'test'}]
  };
  // Before pickup: available
  assert.equal(M.padStateAt(timeline, 0, 4.5).available, true);
  // Right after pickup: cooling down
  const p1=M.padStateAt(timeline, 0, 8.0);
  assert.equal(p1.available, false);
  close(p1.remaining, 7.0);
  // After cooldown: available
  assert.equal(M.padStateAt(timeline, 0, 15.1).available, true);
  // After kickoff reset: immediately reset to available even if within cooldown
  const timeline2={
    pads:[{id:0,x:0,y:0,big:true,respawnSeconds:10}],
    resets:[4.0, 10.0],
    pickups:[{t:8.0,padId:0}]
  };
  assert.equal(M.padStateAt(timeline2, 0, 9.0).available, false);
  assert.equal(M.padStateAt(timeline2, 0, 10.1).available, true);
});


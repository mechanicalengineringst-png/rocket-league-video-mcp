'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const M=require('../coach_app/static/viewer3d-math.js');

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

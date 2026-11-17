'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
require('../coach_app/static/boost-pad-state.js');
const pads=globalThis.ReplayLabBoostPadState;
const sample=()=>({
  schema:'replay-lab/boost-pads-v1',
  source:'native-boost-pickups',
  pads:Array.from({length:34},(_,i)=>({id:i,x:0,y:i,big:i<6,respawnSeconds:i<6?10:4})),
  resets:[4,50],
  pickups:[
    {t:8.11,padId:0,playerId:'Epic:123',method:'player_position_nearest'},
    {t:8.25,padId:7,playerId:'Epic:123',method:'player_position_nearest'},
    {t:50.3,padId:7,playerId:'Epic:456',method:'player_position_nearest'}
  ],
  observedPickupCount:4,unmatchedPickupCount:1
});

test('compile rejects missing or incorrectly indexed Soccar pads',()=>{
  assert.equal(pads.compile(null),null);
  const d=sample();d.pads[2].id=29;
  assert.equal(pads.compile(d),null);
});

test('native kickoff reset establishes available pads',()=>{
  const model=pads.compile(sample());
  assert.equal(pads.at(model,0,3.9).known,false);
  assert.equal(pads.at(model,0,4).known,true);
  assert.equal(pads.at(model,0,4).available,true);
  assert.equal(pads.at(model,0,4).remaining,0);
});

test('large pickup stays unavailable for ten seconds and can be scrubbed backward',()=>{
  const model=pads.compile(sample());
  assert.equal(pads.at(model,0,8.10).available,true);
  assert.equal(pads.at(model,0,8.11).available,false);
  assert.ok(Math.abs(pads.at(model,0,15.11).remaining-3)<1e-8);
  assert.equal(pads.at(model,0,18.11).available,true);
  assert.equal(pads.at(model,0,18.10).available,false);
  assert.equal(pads.at(model,0,8.10).available,true);
});

test('small pad respawns after four seconds',()=>{
  const model=pads.compile(sample());
  assert.equal(pads.at(model,7,8.25).available,false);
  assert.ok(Math.abs(pads.at(model,7,10.25).progress-.5)<1e-8);
  assert.equal(pads.at(model,7,12.24).available,false);
  assert.equal(pads.at(model,7,12.25).available,true);
});

test('kickoff reset clears previous cooldown and later pickup applies independently',()=>{
  const d=sample();d.pickups[0].t=48;
  const model=pads.compile(d);
  assert.equal(pads.at(model,0,49).available,false);
  assert.equal(pads.at(model,0,50).available,true);
  assert.equal(pads.at(model,7,50.31).available,false);
});

test('missing event stream means unknown, not active',()=>{
  const d=sample();d.source='unavailable';
  const model=pads.compile(d);
  assert.equal(pads.at(model,0,8.2).known,false);
  assert.equal(pads.at(model,0,8.2).available,null);
  assert.match(pads.describe(model),/unknown/);
  assert.equal(pads.at(null,0,0).available,null);
});

test('incomplete mapping is disclosed rather than treated as fully verified',()=>{
  const model=pads.compile(sample());
  assert.match(pads.describe(model),/3\/4/);
  assert.match(pads.describe(model),/some states uncertain/);
  assert.match(pads.describe(model),/inferred from pickup location/);
});

test('per-pad events are sorted for deterministic out-of-order native streams',()=>{
  const d=sample();d.pickups=[{t:12,padId:0},{t:8,padId:0}];
  const model=pads.compile(d);
  assert.equal(pads.at(model,0,10).remaining,8);
  assert.equal(pads.at(model,0,15).remaining,7);
});

test('without kickoff, only observed pad has a defensible state',()=>{
  const d=sample();d.resets=[];d.pickups=[{t:8,padId:2}];
  const model=pads.compile(d);
  assert.equal(pads.at(model,2,9).available,false);
  assert.equal(pads.at(model,1,9).known,false);
  assert.equal(pads.at(model,2,7).known,false);
});


test('an unmatched native small-pad pickup makes availability uncertain until expiry',()=>{
  const d=sample();
  d.unmatchedPickups=[{t:7.5,padType:'small'}];
  const model=pads.compile(d);
  assert.equal(pads.at(model,7,8).available,false); // matched known pickup
  assert.equal(pads.at(model,6,8).known,false); // possible unknown consumed
  assert.equal(pads.at(model,0,8).available,true); // only small pads affected
  assert.equal(pads.at(model,6,11.5).available,true);
});

test('an unknown-size native pickup affects both sizes, but never overrides a proven cooldown',()=>{
  const d=sample();
  d.unmatchedPickups=[{t:8.5,padType:null}];
  const model=pads.compile(d);
  assert.equal(pads.at(model,7,9).available,false);
  assert.equal(pads.at(model,2,9).known,false);
  assert.equal(pads.at(model,0,9).available,false); // known 8.11 large cooldown
  assert.equal(pads.at(model,0,19).available,true);
});

test('a reset clears uncertainty from earlier unmapped pickups',()=>{
  const d=sample(); d.unmatchedPickups=[{t:49,padType:'small'}];
  const model=pads.compile(d);
  assert.equal(pads.at(model,6,49.5).known,false);
  assert.equal(pads.at(model,6,50).available,true);
});

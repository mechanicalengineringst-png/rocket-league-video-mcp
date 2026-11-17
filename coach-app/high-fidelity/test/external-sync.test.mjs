import test from 'node:test';
import assert from 'node:assert/strict';
import {
  validateExternalControl, resolveFocusedPlayer,
  shouldCorrectReplayTime, safeSessionId,
} from '../src/external-sync.js';

const session = 'session-test-012345';
const base = Object.freeze({
  type:'replay-lab:hd-control',
  sessionId:session,
  seq:1,
  time:91.25,
  speed:1,
  playing:false,
  focusName:'Tester',
  focusTeam:'blue',
});

test('same-session ordered control passes; stale, invalid or foreign controls are dropped', () => {
  assert.deepEqual(validateExternalControl(base,session,0,200),{
    seq:1,time:91.25,speed:1,playing:false,
    focusName:'Tester',focusTeam:'blue',
  });
  assert.equal(validateExternalControl(base,'foreign-session',0,200),null);
  assert.equal(validateExternalControl(base,session,1,200),null);
  assert.equal(validateExternalControl({...base,seq:0},session,0,200),null);
  assert.equal(validateExternalControl({...base,seq:1.5},session,0,200),null);
  assert.equal(validateExternalControl({...base,time:Infinity},session,0,200),null);
  assert.equal(validateExternalControl({...base,time:-1},session,0,200),null);
  assert.equal(validateExternalControl({...base,time:201},session,0,200),null);
  assert.equal(validateExternalControl({...base,speed:-2},session,0,200),null);
  assert.equal(validateExternalControl({...base,speed:3},session,0,200),null);
  assert.equal(validateExternalControl({...base,playing:'true'},session,0,200),null);
  assert.equal(validateExternalControl({...base,focusTeam:'unknown'},session,0,200),null);
  assert.equal(validateExternalControl({...base,focusName:'x'.repeat(200)},session,0,200),null);
  assert.equal(validateExternalControl({...base,type:'evil'},session,0,200),null);
});

test('match HD player by verified name AND team; ambiguous names abstain', () => {
  const roster=[
    {id:'car-blue',name:'Tester',team:0},
    {id:'car-orange',name:'Tester',team:1},
    {id:'car-teammate',name:'Friend',team:0},
  ];
  assert.equal(resolveFocusedPlayer(roster,'tester','blue').id,'car-blue');
  assert.equal(resolveFocusedPlayer(roster,'Tester','orange').id,'car-orange');
  assert.equal(resolveFocusedPlayer(roster,'friend','blue').id,'car-teammate');
  assert.equal(resolveFocusedPlayer(roster,'friend','orange'),null);
  assert.equal(resolveFocusedPlayer([...roster,roster[0]],'Tester','blue'),null);
  assert.equal(resolveFocusedPlayer([],'Tester','blue'),null);
  assert.equal(resolveFocusedPlayer(roster,'unknown','blue'),null);
});

test('correct large playing drift but never aggressively jitter-seek for 30-100 ms offsets',()=>{
  assert.equal(shouldCorrectReplayTime(15,14.93,true),false);
  assert.equal(shouldCorrectReplayTime(15,14.5,true),false);
  assert.equal(shouldCorrectReplayTime(15,14.2,true),true);
  assert.equal(shouldCorrectReplayTime(15,14.93,false),true);
  assert.equal(shouldCorrectReplayTime(15,14.97,false),false);
  assert.equal(shouldCorrectReplayTime(15,NaN,false),false);
});

test('session IDs are bounded to opaque simple tokens',()=>{
  assert.equal(safeSessionId('session-test-012345'),true);
  assert.equal(safeSessionId('<script>'),false);
  assert.equal(safeSessionId('abc'),false);
  assert.equal(safeSessionId('x'.repeat(101)),false);
});

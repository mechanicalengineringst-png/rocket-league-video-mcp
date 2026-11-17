import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const directory=path.dirname(fileURLToPath(import.meta.url));
const source=fs.readFileSync(
  path.resolve(directory,'../../coach_app/static/hd-bridge.js'),'utf8'
);
const mainSource=fs.readFileSync(
  path.resolve(directory,'../../coach_app/static/app.js'),'utf8'
);

function setup(){
  const handlers=new Map(), sent=[];
  const target={
    postMessage(value,origin){sent.push({value,origin});},
    focus(){},closed:false,
  };
  let clock=1000;
  const button={addEventListener(name,fn){handlers.set('button:'+name,fn);}};
  const upload={addEventListener(name,fn){handlers.set('upload:'+name,fn);}};
  const select={selectedOptions:[{textContent:'Blue — BLUE'}]};
  const dropZone={addEventListener(name,fn){handlers.set('drop:'+name,fn);}};
  const document={getElementById(id){
    return {
      openHdReplay:button,fileInput:upload,
      playerSelect:select,uploadZone:dropZone,
    }[id] || null;
  }};
  const window={
    open(){return target;},
    addEventListener(name,fn){handlers.set('window:'+name,fn);},
  };
  let nonce=0;
  const crypto={randomUUID(){
    return 'session-12345678-abcdef-'+String(++nonce).padStart(4,'0');
  }};
  const context=vm.createContext({
    document,window,location:{origin:'http://127.0.0.1:8000'},
    crypto,performance:{now(){return clock;}},console,
  });
  vm.runInContext(source,context,{filename:'hd-bridge.js'});
  const emit=(scope,event,value)=>handlers.get(scope+':'+event)(value);
  return{emit,sent,target,advance(delta){clock+=delta;}};
}

test('real main app publishes required sync fields after seek and focus changes',()=>{
  for(const text of [
    "function publishReplaySyncState()",
    "replay-lab:sync-state",
    "time:state.time, playing:state.playing, speed:state.speed",
    "focusName:p.name, focusTeam:p.team",
    "publishReplaySyncState();",
  ])assert.ok(mainSource.includes(text),text);
});

test('same-origin file transfer, ready/loaded handshake, and selected-player sync',()=>{
  const {emit,sent,target,advance}=setup();
  const file={name:'real-match.replay'};
  emit('upload','change',{target:{files:[file]}});
  emit('window','replay-lab:replay-ready',{detail:{synthetic:false}});
  const state={
    time:30.5,playing:false,speed:1,
    focusName:'Blue',focusTeam:'blue',synthetic:false,
  };
  emit('window','replay-lab:sync-state',{detail:state});
  emit('button','click',{});
  assert.equal(sent[0].value.type,'replay-lab:hd-ping');
  // Ignore an unrelated or cross-origin tab, even if it forges a ready event.
  emit('window','message',{
    origin:'https://unrelated.example',source:target,
    data:{type:'replay-lab:hd-ready'},
  });
  assert.equal(sent.length,1);
  emit('window','message',{
    origin:'http://127.0.0.1:8000',source:target,
    data:{type:'replay-lab:hd-ready'},
  });
  assert.equal(sent.length,2);
  assert.equal(sent[1].value.type,'replay-lab:hd-load');
  assert.equal(sent[1].value.file,file);
  const sessionId=sent[1].value.sessionId;
  // Reject wrong-session load acknowledgement.
  emit('window','message',{
    origin:'http://127.0.0.1:8000',source:target,
    data:{type:'replay-lab:hd-loaded',sessionId:'foreign-session'},
  });
  assert.equal(sent.length,2);
  emit('window','message',{
    origin:'http://127.0.0.1:8000',source:target,
    data:{type:'replay-lab:hd-loaded',sessionId},
  });
  assert.equal(sent.length,3);
  assert.equal(sent[2].value.type,'replay-lab:hd-control');
  assert.equal(sent[2].value.focusName,'Blue');
  assert.equal(sent[2].value.time,30.5);
  assert.equal(sent[2].value.playing,false);
  assert.equal(sent[2].value.seq,1);
  assert.equal(sent[2].origin,'http://127.0.0.1:8000');

  // New focus, speed and play state get an immediate control even if <200ms.
  emit('window','replay-lab:sync-state',{detail:{
    ...state,time:31,speed:1.5,playing:true,
    focusName:'Orange',focusTeam:'orange',
  }});
  assert.equal(sent.length,4);
  assert.equal(sent[3].value.focusName,'Orange');
  assert.equal(sent[3].value.seq,2);

  // Ticking while playing doesn't flood the HD tab with 60Hz seek commands.
  emit('window','replay-lab:sync-state',{detail:{
    ...state,time:31.05,speed:1.5,playing:true,
    focusName:'Orange',focusTeam:'orange',
  }});
  assert.equal(sent.length,4);
  advance(250);
  emit('window','replay-lab:sync-state',{detail:{
    ...state,time:31.3,speed:1.5,playing:true,
    focusName:'Orange',focusTeam:'orange',
  }});
  assert.equal(sent.length,5);
  assert.equal(sent[4].value.seq,3);
});

test('synthetic demo never controls a real replay; wrong-origin messages are ignored',()=>{
  const {emit,sent,target}=setup();
  emit('upload','change',{target:{files:[{name:'real.replay'}]}});
  emit('button','click',{});
  emit('window','message',{
    origin:'http://127.0.0.1:8000',source:target,
    data:{type:'replay-lab:hd-ready'},
  });
  const sessionId=sent[1].value.sessionId;
  emit('window','replay-lab:sync-state',{detail:{
    time:30,playing:true,speed:1,
    focusName:'Demo',focusTeam:'blue',synthetic:true,
  }});
  emit('window','message',{
    origin:'http://127.0.0.1:8000',source:target,
    data:{type:'replay-lab:hd-loaded',sessionId},
  });
  assert.equal(sent.length,2);
});

test('duplicate ready does not decode twice, but HD tab reload begins a new session',()=>{
  const {emit,sent,target}=setup();
  emit('upload','change',{target:{files:[{name:'real.replay'}]}});
  emit('button','click',{});
  const ready=instanceId=>({
    origin:'http://127.0.0.1:8000',
    source:target,
    data:{type:'replay-lab:hd-ready',instanceId},
  });
  emit('window','message',ready('page-instance-first'));
  assert.equal(sent.length,2);
  const before=sent[1].value.sessionId;
  emit('window','message',ready('page-instance-first'));
  assert.equal(sent.length,2);
  emit('window','message',ready('page-instance-second'));
  assert.equal(sent.length,3);
  const after=sent[2].value.sessionId;
  assert.notEqual(after,before);
  emit('window','message',{
    origin:'http://127.0.0.1:8000',source:target,
    data:{type:'replay-lab:hd-loaded',sessionId:before},
  });
  assert.equal(sent.length,3);
  emit('window','message',{
    origin:'http://127.0.0.1:8000',source:target,
    data:{type:'replay-lab:hd-loaded',sessionId:after},
  });
  assert.equal(sent.length,3); // no local focus/time state received yet
});

test('switching replay clears previous focused-player and timeline payload',()=>{
  const {emit,sent,target}=setup();
  const first={name:'old.replay'},second={name:'new.replay'};
  emit('upload','change',{target:{files:[first]}});
  emit('window','replay-lab:replay-ready',{detail:{synthetic:false}});
  emit('window','replay-lab:sync-state',{detail:{
    time:105,playing:true,speed:1,focusName:'Old',
    focusTeam:'orange',synthetic:false,
  }});
  emit('button','click',{});
  const ready={origin:'http://127.0.0.1:8000',
    source:target,data:{type:'replay-lab:hd-ready'}};
  emit('window','message',ready);
  const sessionId=sent[1].value.sessionId;
  emit('window','message',{origin:ready.origin,source:target,
    data:{type:'replay-lab:hd-loaded',sessionId}});
  assert.equal(sent.length,3);
  assert.equal(sent[2].value.focusName,'Old');
  emit('upload','change',{target:{files:[second]}});
  // Any delayed update from the previous replay must be ignored while the
  // new file is being decoded asynchronously.
  emit('window','replay-lab:sync-state',{detail:{
    time:108,playing:true,speed:1,focusName:'Old',
    focusTeam:'orange',synthetic:false,
  }});
  assert.equal(sent[3].value.type,'replay-lab:hd-load');
  assert.equal(sent[3].value.file,second);
  const nextSession=sent[3].value.sessionId;
  emit('window','message',{origin:ready.origin,source:target,
    data:{type:'replay-lab:hd-loaded',sessionId:nextSession}});
  // Old focused-player, time and score must not apply to the new replay.
  assert.equal(sent.length,4);
});

test('new replay state is accepted only after main parser emits replay-ready',()=>{
  const {emit,sent,target}=setup();
  const file={name:'parsed.replay'};
  emit('upload','change',{target:{files:[file]}});
  const status={time:40,playing:false,speed:1,focusName:'New',
    focusTeam:'orange',synthetic:false};
  emit('window','replay-lab:sync-state',{detail:status});
  emit('button','click',{});
  emit('window','message',{
    origin:'http://127.0.0.1:8000',source:target,
    data:{type:'replay-lab:hd-ready'},
  });
  const sessionId=sent[1].value.sessionId;
  emit('window','message',{
    origin:'http://127.0.0.1:8000',source:target,
    data:{type:'replay-lab:hd-loaded',sessionId},
  });
  assert.equal(sent.length,2); // stale pre-parse state ignored
  emit('window','replay-lab:replay-ready',{detail:{synthetic:false}});
  emit('window','replay-lab:sync-state',{detail:status});
  assert.equal(sent.length,3);
  assert.equal(sent[2].value.focusName,'New');
  assert.equal(sent[2].value.time,40);
});

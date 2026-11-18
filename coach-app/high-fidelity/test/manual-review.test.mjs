import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source=readFileSync(
  new URL('../../coach_app/static/manual-review.js',import.meta.url),'utf8');

function load() {
  const elements=new Map();
  const make=id=>({
    id,disabled:true,textContent:'',onclick:null,checked:false
  });
  for(const name of ['lensManualReviewBtn','lensManualReviewStatus'])
    elements.set(name,make(name));
  const root={document:{getElementById:id=>elements.get(id)??null},
    AbortController,fetch(){throw Error('unauthorized network request');}};
  root.globalThis=root;
  runInNewContext(source,root,{filename:'manual-review.js'});
  return {api:root.ReplayLabManualReview,elements};
}
const roster=[
  {id:'b1',team:'blue'}, {id:'b2',team:'blue'},
  {id:'o1',team:'orange'}, {id:'o2',team:'orange'}
];
function replay() {
  const frames=[];
  for(let i=0;i<=13*30;i++){
    const t=Number((i/30).toFixed(4));
    frames.push({
      t,
      ball:{x:200+t*6,y:-400+t*80,z:93,velocity:[6,80,0]},
      cars:{
        b1:{x:t*60,y:1200,z:17,boost:60,velocity:[60,0,0]},
        b2:{x:-400,y:500,z:17,boost:40,velocity:[0,0,0]},
        o1:{x:1000,y:1700,z:17,boost:30,velocity:[0,0,0]},
        o2:{x:-1900,y:2400,z:17,boost:80,velocity:[0,0,0]},
      }
    });
  }
  return {source:'native-replay',title:'private',players:roster,frames,
    events:[],duration:13};
}
function context(r=replay(),t0=10.04) {
  return {replay:r,focusId:'b1',focusConfirmed:true,
    pinned:{source:'manual',window:{t0}}};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const clean=x=>JSON.parse(JSON.stringify(x));

test('owner-selected t0 becomes a real 5–20s episode with three historical recorded frames',()=>{
  const {api}=load();
  const r=replay();
  const original=JSON.stringify(r);
  const req=api.buildManualRequest(r,'b1',10.04);
  assert.ok(req);
  assert.equal(req.mode,'deterministic');
  assert.equal(req.experimental_tactical_v1,false);
  assert.equal(req.replay,r);
  assert.equal(req.player_id,'b1');
  assert.equal(req.primary_t0,10.033);
  assert.equal(req.episode_start_s,3.033);
  assert.equal(req.decision_times.length,3);
  assert.equal(req.decision_times[2],req.primary_t0);
  assert.ok(req.decision_times[0]>req.episode_start_s);
  assert.ok(req.decision_times[1]>req.decision_times[0]);
  assert.ok(req.decision_times[1]<req.primary_t0);
  assert.ok(req.primary_t0-req.episode_start_s>=5);
  assert.deepEqual(clean(req.decision_times),
    clean([...req.decision_times].sort((a,b)=>a-b)));
  assert.equal(JSON.stringify(r),original,'must not alter original decoded replay');
});

test('future replay changes cannot change pinned episode selection or early context',()=>{
  const {api}=load();
  const r=replay();
  const before=clean(api.buildManualRequest(r,'b1',10.04));
  const cloned=replay();
  for(const f of cloned.frames) {
    if(f.t>10.04) {
      f.ball.x=4000;f.cars.b1.boost=0;
      f.cars.o1.y=-5000;
    }
  }
  const after=clean(api.buildManualRequest(cloned,'b1',10.04));
  assert.deepEqual(after,before);
  assert.ok(after.decision_times.every(t=>t<=10.04));
});

test('bad identities, synthetic data, missing physics, sparse time and kickoff abstain',()=>{
  const {api}=load();
  let r=replay();
  assert.equal(api.buildManualRequest(r,'b1',4.9),null,
    'needs five seconds prior evidence; cannot invent earlier match');
  assert.equal(api.buildManualRequest(r,'b1',-1),null);
  assert.equal(api.buildManualRequest(r,'b1',14),null);
  assert.equal(api.buildManualRequest(r,'ghost',10.02),null);
  assert.equal(api.buildManualRequest(r,'b1',NaN),null);
  r.source='synthetic';
  assert.equal(api.buildManualRequest(r,'b1',10.02),null);
  r=replay();
  r.players[3].team='blue';
  assert.equal(api.buildManualRequest(r,'b1',10.02),null);
  r=replay();
  r.frames[300].cars.b1.demolished=true;
  assert.equal(api.buildManualRequest(r,'b1',10.02),null);
  r=replay();
  delete r.frames[300].ball.z;
  assert.equal(api.buildManualRequest(r,'b1',10.02),null);
  r=replay();
  // Drop every frame except one every full second: a derived context
  // timestamp 7.1s after kickoff cannot be filled with a 1s-old sample.
  r.frames=r.frames.filter(f=>Math.abs(f.t-Math.round(f.t))<0.0001);
  assert.equal(api.buildManualRequest(r,'b1',10.04),null);
});

test('a local deterministic review is an explicit click and does not call a model',async()=>{
  const {api,elements}=load();
  const c=context();
  const got=[];
  const calls=[];
  const controller=new api.ManualReviewController(
    ()=>c,(lesson,request,meta)=>got.push({lesson,request,meta}),
    async(url,options)=>{
      calls.push({url,options});
      const req=JSON.parse(options.body);
      return {ok:true,json:async()=>({
        schema:'CoachLessonV0',mode:'deterministic_baseline',stage:'predecision',
        decision:{node_id:'N3',t0_s:req.primary_t0,
          episode_start_s:req.episode_start_s,status:'partial'},
        claims:[{author:'deterministic',text:'Measured position'}],
        validation:{accepted_model_claims:0,
          future_outcomes_used:false,semantic_tactical_accuracy_verified:false}
      })};
    }
  );
  controller.mount();
  assert.equal(calls.length,0,'mount must not issue a request');
  assert.equal(elements.get('lensManualReviewBtn').disabled,false);
  const success=await controller.reviewPinned();
  assert.equal(success,true);
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/api/coach/lesson');
  const submitted=JSON.parse(calls[0].options.body);
  assert.equal(submitted.mode,'deterministic');
  assert.equal(submitted.experimental_tactical_v1,false);
  assert.deepEqual(got.map(x=>x.meta.selection_source),['manual']);
  assert.equal(got[0].request.primary_t0,submitted.primary_t0);
  assert.match(elements.get('lensManualReviewStatus').textContent,
    /not a confirmed mistake/i);
});

test('changing replay/player/pin during a request discards stale local review',async()=>{
  const {api}=load();
  const state=context();
  const accepted=[];
  let reply;
  const controller=new api.ManualReviewController(
    ()=>state,(...data)=>accepted.push(data),
    async()=>new Promise(resolve=>reply=resolve));
  controller.mount();
  const pending=controller.reviewPinned();
  await tick();
  state.pinned.window.t0=9;
  reply({ok:true,json:async()=>({
    schema:'CoachLessonV0',stage:'predecision',
    mode:'deterministic_baseline',decision:{node_id:'N3',t0_s:10.033,
      episode_start_s:3.033},claims:[],
    validation:{accepted_model_claims:0,
      future_outcomes_used:false,semantic_tactical_accuracy_verified:false}
  })});
  assert.equal(await pending,false);
  assert.equal(accepted.length,0);
  controller.invalidate('New replay');
});

test('untrusted backend response or 422 never produces a fake manual lesson',async()=>{
  const {api,elements}=load();
  const accepted=[];
  const st=context();
  let serverData={ok:false,status:422};
  const controller=new api.ManualReviewController(
    ()=>st,(...p)=>accepted.push(p),async()=>serverData);
  controller.mount();
  assert.equal(await controller.reviewPinned(),false);
  assert.equal(accepted.length,0);
  assert.match(elements.get('lensManualReviewStatus').textContent,/No coaching verdict/i);
  serverData={ok:true,json:async()=>({
    schema:'CoachLessonV0',stage:'predecision',
    mode:'model_proposal',decision:{node_id:'N3',t0_s:10.033},
    claims:[],validation:{accepted_model_claims:0,
      future_outcomes_used:false,semantic_tactical_accuracy_verified:false}
  })};
  assert.equal(await controller.reviewPinned(),false);
  assert.equal(accepted.length,0);
});

test('review is disabled for automatically pinned coach moments and unconfirmed focus',()=>{
  const {api,elements}=load();
  const state=context();
  state.pinned.source='coaching';
  const ctrl=new api.ManualReviewController(()=>state,()=>{},async()=>{throw Error();});
  ctrl.mount();
  assert.equal(elements.get('lensManualReviewBtn').disabled,true);
  state.pinned.source='manual';
  state.focusConfirmed=false;
  ctrl.render();
  assert.equal(elements.get('lensManualReviewBtn').disabled,true);
});

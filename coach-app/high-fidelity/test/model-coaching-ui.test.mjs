import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source=readFileSync(
  new URL('../../coach_app/static/model-coaching.js',import.meta.url),'utf8');
function modelAPI(ids={}) {
  const elements=new Map();
  class Element {
    constructor(tag='div') {
      this.tagName=tag;this.children=[];this.className='';
      this.textContent='';this.value='';this.checked=false;
      this.disabled=false;this.style={};
    }
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=[...items];}
  }
  for(const id of ['modelCoachRunBtn','modelCoachRefreshBtn','modelCoachConsent',
      'modelCoachExportBtn','modelCoachReadiness','modelCoachSelected',
      'modelCoachStatus','modelCoachResults','modelCoachEvidence',
      'modelCoachSpatialBtn','modelCoachSpatialStatus','modelCoachSpatialResults']){
    elements.set(id,new Element(id));
  }
  for(const [k,v] of Object.entries(ids))Object.assign(elements.get(k),v);
  const root={
    document:{
      getElementById:id=>elements.get(id)||null,
      createElement:tag=>new Element(tag)
    },
    addEventListener:()=>{},
    AbortController,
    Blob,URL,setTimeout,
  };
  root.globalThis=root;
  runInNewContext(source,root,{filename:'model-coaching.js'});
  return {API:root.ReplayLabModelCoaching,elements,root};
}
function situation(){
  const replay={source:'native-replay',duration:100,frames:[],players:[]};
  const req={
    replay,player_id:'focus-id',
    decision_times:[20,21.1],episode_start_s:16,primary_t0:21.1,
    mode:'deterministic',experimental_tactical_v1:false
  };
  const node={node_id:'N2',t0:21.1,is_primary:true};
  const ep={episode_id:'candidate1',title:'Observed decision',backendRequest:req};
  return {replay,focusId:'focus-id',focusConfirmed:true,
    coach:{activeEpisode:ep,activeNode:node,isDemo:false}};
}
function validLesson(){
  return {schema:'CoachLessonV0',stage:'predecision',mode:'model_proposal',
    decision:{t0_s:21.1},assessment:{grade:'tradeoff'},
    validation:{accepted_model_claims:1,rejected_model_claims:[{reason:'missing source'}],
      semantic_tactical_accuracy_verified:false,future_outcomes_used:false},
    claims:[
      {author:'deterministic',text:'Baseline fact'},
      {author:'model_proposal',node_id:'N2',section:'alternative',
       epistemic_type:'HYPOTHETICAL_ALTERNATIVE',text:'Delaying may preserve defensive coverage.',
       evidence_refs:['N2/E.focus.boost'],review_status:'needs_semantic_review'},
    ]};
}
function response(json,status=200){
  return {ok:status===200,status,json:async()=>json};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('only a verified primary episode and confirmed player may be sent to the model',()=>{
  const {API}=modelAPI();
  const s=situation();
  const req=API.validRequest(s);
  assert.equal(req.mode,'model');
  assert.equal(req.experimental_tactical_v1,false);
  assert.deepEqual(Array.from(req.decision_times),[20,21.1]);
  assert.equal(req.replay,s.replay,'browser-to-local replay stays unchanged');
  s.coach.activeNode={...s.coach.activeNode,is_primary:false};
  assert.equal(API.validRequest(s),null,'earlier context must not be silently graded');
  s.coach.activeNode={node_id:'N2',t0:21.1,is_primary:true};
  s.coach.activeEpisode.backendRequest={replay:s.replay,player_id:'focus-id'};
  assert.equal(API.validRequest(s),null,'bundle-only payload is not a valid lesson request');
  s.coach.activeEpisode.backendRequest=req;
  s.focusConfirmed=false;
  assert.equal(API.validRequest(s),null);
  s.focusConfirmed=true;s.replay.source='synthetic';
  assert.equal(API.validRequest(s),null);
});

test('model accepted claims must have review status, original evidence refs and correct timestamp',()=>{
  const {API}=modelAPI();
  const request=API.validRequest(situation());
  const good=API.verifiedResponse(validLesson(),request);
  assert.equal(good.accepted,1);
  assert.equal(good.rejected,1);
  assert.equal(good.merit_verified,false);
  assert.equal(good.claims[0].text,'Delaying may preserve defensive coverage.');
  const mismatch=validLesson();
  mismatch.decision.t0_s=22;
  assert.equal(API.verifiedResponse(mismatch,request),null);
  const badGrade=validLesson();
  badGrade.assessment.grade='definitely_best';
  assert.equal(API.verifiedResponse(badGrade,request),null);
  const future=validLesson();
  future.validation.future_outcomes_used=true;
  assert.equal(API.verifiedResponse(future,request),null);
  const wrongCount=validLesson();
  wrongCount.validation.accepted_model_claims=2;
  assert.equal(API.verifiedResponse(wrongCount,request),null);
  const unsupported=validLesson();
  unsupported.claims[1].review_status='trusted';
  assert.equal(API.verifiedResponse(unsupported,request),null);
  const uncertain=validLesson();
  uncertain.claims=uncertain.claims.slice(0,1);
  uncertain.validation.accepted_model_claims=0;
  assert.equal(API.verifiedResponse(uncertain,request).claims.length,0);
});

test('initial render/readiness does not invoke a model; consent authorizes exactly one call',async()=>{
  const {API,elements}=modelAPI();
  const s=situation();let calls=[];
  const fetcher=async (url,options={})=>{
    calls.push({url,options});
    if(url.includes('readiness'))return response({schema:'CoachModelReadinessV0',status:'configured_unverified'});
    if(url.includes('lesson'))return response(validLesson());
    throw Error('Unexpected URL '+url);
  };
  const ui=new API.ModelCoachingController(()=>s,fetcher);
  ui.mount();
  await tick();
  assert.equal(ui.readiness,'configured_unverified');
  assert.equal(calls.filter(c=>c.url.includes('/lesson')).length,0);
  assert.equal(elements.get('modelCoachRunBtn').disabled,true,'no consent');
  await ui.generate();
  assert.equal(calls.filter(c=>c.url.includes('/lesson')).length,0);
  elements.get('modelCoachConsent').checked=true;ui.render();
  assert.equal(elements.get('modelCoachRunBtn').disabled,false);
  await ui.generate();
  assert.equal(calls.filter(c=>c.url.includes('/lesson')).length,1);
  assert.equal(elements.get('modelCoachConsent').checked,false,'one request consumes authorization');
  assert.equal(ui.exportSummary()[0].accepted_claims,1);
  const transmitted=JSON.parse(calls.find(c=>c.url.includes('/lesson')).options.body);
  assert.equal(transmitted.mode,'model');
  assert.equal(transmitted.experimental_tactical_v1,false);
  assert.equal(transmitted.primary_t0,21.1);
  assert.deepEqual(Array.from(transmitted.decision_times),[20,21.1]);
  const details=elements.get('modelCoachResults').children;
  assert.ok(details.some(c=>c.className==='model-claim'), 'accepted source-cited claim displayed');
  ui.setFeedback('incorrect');
  ui.updateNote('Opponent had possession and teammate could not cover.');
  const report=ui.exportSummary()[0];
  assert.equal(report.feedback,'incorrect');
  assert.match(report.tester_note,/Opponent had possession/);
  assert.equal(report.tactical_accuracy_expert_verified,false);
  assert.ok(!JSON.stringify(report).includes('api_key'));
});

test('in-flight responses from old match/player never appear on new selection',async()=>{
  const {API,elements}=modelAPI();
  let resolveDelayed,postCalls=0;
  const s=situation();
  const fetcher=async(url)=>{
    if(url.endsWith('/lesson')) {
      postCalls++;
      return new Promise(resolve=>{resolveDelayed=resolve;});
    }
    return response({schema:'CoachModelReadinessV0',status:'configured_unverified'});
  };
  const ui=new API.ModelCoachingController(()=>s,fetcher);
  ui.mount();await tick();
  elements.get('modelCoachConsent').checked=true;
  const pending=ui.generate();await tick();
  assert.equal(postCalls,1);
  s.focusId='teammate-id';
  ui.selectionChanged();
  resolveDelayed(response(validLesson()));
  await pending;
  assert.equal(ui.exportSummary().length,0,'stale model response discarded');
  assert.equal(elements.get('modelCoachRunBtn').disabled,true,'new player must get its own verified episode');
});

test('provider failures and invalid structured responses never create fake advice',async()=>{
  const {API,elements}=modelAPI();
  const s=situation();
  const ui=new API.ModelCoachingController(()=>s,async(url)=>{
    if(url.endsWith('/lesson'))return response({error:'bad response'},502);
    return response({schema:'CoachModelReadinessV0',status:'configured_unverified'});
  });
  ui.mount();await tick();
  elements.get('modelCoachConsent').checked=true;
  await ui.generate();
  assert.equal(ui.exportSummary().length,0);
  assert.match(ui.status,/no proposal was accepted/i);
  assert.equal(elements.get('modelCoachConsent').checked,false);
});

test('bundle exact candidate request is reconstructed instead of reusing bundle payload',()=>{
  const coachText=readFileSync(
    new URL('../../coach_app/static/coaching-experience.js',import.meta.url),'utf8');
  const root={document:{getElementById:()=>null},console};
  root.window=root;root.globalThis=root;
  runInNewContext(coachText,root);
  const controller=new root.CoachingExperienceController();
  const replay=situation().replay;
  const captured=[];
  controller.addVerifiedLesson=(lesson,req,info)=>captured.push({lesson,req,info});
  const candidate={
    candidate_id:'ec-real',primary_t0:21.1,episode_start_s:16,
    decision_times:[20,21.1]
  };
  const preview={
    candidate_id:'ec-real',primary_t0:21.1,
    lesson:{schema:'CoachLessonV0',decision:{t0_s:21.1},stage:'predecision'}
  };
  controller.setReviewBundle({schema:'CoachReviewBundleV0',
    discovery:{candidates:[candidate]},previews:[preview]},
    replay,'focus-id',{
      replay,player_id:'focus-id',max_candidates:8,preview_count:4
    });
  assert.equal(captured.length,1);
  assert.deepEqual(Array.from(captured[0].req.decision_times),[20,21.1]);
  assert.equal(captured[0].req.episode_start_s,16);
  assert.equal(captured[0].req.primary_t0,21.1);
  assert.equal(captured[0].req.player_id,'focus-id');
  assert.equal(captured[0].req.mode,'deterministic');
  const req=APIFromVM().validRequest({
    replay,focusId:'focus-id',focusConfirmed:true,
    coach:{activeEpisode:{backendRequest:captured[0].req,episode_id:'1'},
      activeNode:{is_primary:true,t0:21.1},isDemo:false}
  });
  assert.equal(req?.mode,'model');
});
function APIFromVM(){return modelAPI().API;}


test('source-linked local spatial inspector works when model is disabled, with zero provider calls',async()=>{
  const {API,elements}=modelAPI();
  const scene=situation();
  const calls=[];
  const fetcher=async(url,options={})=>{
    calls.push({url,options});
    if(url==='/api/coach/model-readiness')
      return response({schema:'CoachModelReadinessV0',status:'disabled'});
    if(url==='/api/coach/scene-relations'){
      const req=JSON.parse(options.body);
      assert.equal(req.mode,'deterministic');
      assert.equal(req.experimental_tactical_v1,false);
      assert.equal(req.primary_t0,21.1);
      return response({
        schema:'RelationalInvariantsV0',stage:'predecision',
        information_cutoff_s:21.1,uses_future:false,
        calculates_tactical_merit:false,expert_calibrated:false,
        nodes:[{node_id:'N1',t0_s:20,metrics:[],unknowns:[]},
          {node_id:'N2',t0_s:21.1,unknowns:[{metric:'nose_to_ball_angle',subject:'opponent_2'}],
            metrics:[
              {metric:'longitudinal_goal_side_of_ball',subject:'focus',
                value:'goalward',source_refs:['N2/E.focus.position','N2/E.ball.position']},
              {metric:'teammate_planar_separation',subject:'focus_and_teammate',
                value:1200.5,unit:'uu',
                source_refs:['N2/E.focus.position','N2/E.teammate.position']},
            ]}]
      });
    }
    throw Error('Unexpected remote call '+url);
  };
  const controller=new API.ModelCoachingController(()=>scene,fetcher);
  controller.mount();await tick();
  assert.equal(controller.readiness,'disabled');
  assert.equal(elements.get('modelCoachSpatialBtn').disabled,false);
  assert.equal(calls.some(x=>x.url==='/api/coach/lesson'),false);
  assert.equal(calls.some(x=>x.url==='/api/coach/scene-relations'),false);
  await controller.inspectSpatial();
  assert.equal(calls.filter(x=>x.url==='/api/coach/scene-relations').length,1);
  assert.equal(calls.filter(x=>x.url==='/api/coach/lesson').length,0);
  assert.match(controller.spatialStatus,/not possession/i);
  const rows=elements.get('modelCoachSpatialResults').children.filter(
    x=>x.className==='model-spatial-row');
  assert.equal(rows.length,2);
  assert.ok(rows.some(x=>x.children.some(y=>y.textContent==='goalward')));
  assert.ok(rows.some(x=>x.children.some(y=>y.textContent==='1200.5 uu')));
  assert.ok(rows.every(x=>x.children[2].children.length===2),
    'Each displayed geometry value must provide original clickable sources');
});

test('scene relations from a previous player must not appear under a new player',async()=>{
  const {API,elements}=modelAPI();
  const scene=situation();
  let complete,requests=0;
  const fetcher=async(url)=>{
    if(url==='/api/coach/model-readiness')
      return response({schema:'CoachModelReadinessV0',status:'disabled'});
    if(url==='/api/coach/scene-relations'){
      requests++;
      return new Promise(resolve=>complete=resolve);
    }
    throw Error('Unknown URL');
  };
  const controller=new API.ModelCoachingController(()=>scene,fetcher);
  controller.mount();await tick();
  const pending=controller.inspectSpatial();await tick();
  assert.equal(requests,1);
  scene.focusId='other';
  controller.selectionChanged();
  complete(response({
    schema:'RelationalInvariantsV0',stage:'predecision',
    uses_future:false,calculates_tactical_merit:false,expert_calibrated:false,
    information_cutoff_s:21.1,
    nodes:[{node_id:'N2',t0_s:21.1,
      metrics:[{metric:'planar_ball_distance',subject:'focus',value:500,
        source_refs:['N2/E.focus.position','N2/E.ball.position']}],unknowns:[]}]
  }));
  await pending;
  assert.equal(elements.get('modelCoachSpatialResults').children.length,0);
  assert.equal(elements.get('modelCoachSpatialBtn').disabled,true);
});


test('an active blind Stage A masks cached AI advice and blocks additional paid calls',async()=>{
  const {API,elements,root}=modelAPI();
  const selection=situation();
  let blinded=true,paidCalls=0;
  root.blindReviewUI={isPredecisionOpen:()=>blinded};
  const controller=new API.ModelCoachingController(()=>selection,async url=>{
    if(url==='/api/coach/model-readiness')return response({
      schema:'CoachModelReadinessV0',status:'configured_unverified'});
    if(url==='/api/coach/lesson'){paidCalls++;return response(validLesson());}
    throw Error('Unexpected endpoint '+url);
  });
  root.modelCoachingUI=controller;
  controller.mount();await tick();
  assert.equal(controller.readiness,'configured_unverified');
  const {key}=controller.getContext();
  controller.results.set(key,{grade:'risky',accepted:1,rejected:0,claims:[],
    t0:21.1,feedback:null,note:''});
  elements.get('modelCoachConsent').checked=true;
  controller.render();
  assert.equal(elements.get('modelCoachRunBtn').disabled,true);
  assert.ok(elements.get('modelCoachResults').children.every(x=>
    !String(x.children?.[0]?.textContent||x.textContent).includes('Model assessment:')));
  await controller.generate();
  assert.equal(paidCalls,0,'predecision evaluation must not silently consume model credits');
  blinded=false;controller.render();
  assert.equal(elements.get('modelCoachRunBtn').disabled,false);
  assert.ok(elements.get('modelCoachResults').children.some(x=>
    x.className==='model-result-heading'));
});

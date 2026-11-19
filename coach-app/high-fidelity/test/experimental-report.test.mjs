import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source=readFileSync(new URL('../../coach_app/static/experimental-report.js',import.meta.url),'utf8');
class MockEl {
  constructor(id='',name='div'){this.id=id;this.name=name;this.children=[];
    this.textContent='';this.hidden=false;this.disabled=false;this.className='';this.onclick=null;}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=[...items];}
}
const ids=['experimentalReportPanel','experimentalReportBtn','experimentalReportStatus',
  'experimentalReportResults'];
function setup(){
  const elements=new Map(ids.map(k=>[k,new MockEl(k)]));
  const listeners={};
  const root={
    document:{
      getElementById:id=>elements.get(id)||null,
      createElement:(name)=>new MockEl('',name),
    },
    addEventListener:(name,cb)=>{listeners[name]=cb;},
  };
  root.globalThis=root;
  runInNewContext(source,root,{filename:'experimental-report.js'});
  return {root,elements,listeners,api:root.ReplayLabExperimentalReport};
}
function scene(){
  const replay={source:'native-replay',duration:135,
    players:[{id:'b1',team:'blue'},{id:'b2',team:'blue'},
      {id:'o1',team:'orange'},{id:'o2',team:'orange'}],
    frames:[{t:0},{t:10},{t:70}]};
  return {replay,focusId:'b1',focusConfirmed:true};
}
const validFinding=(custom={})=>({
  schema:'CoachingFindingV1',
  finding_id:'F1',t0:31.12,status:'ok',
  kind:'several_defensible',
  situation:{class:'second_man_support',label:'Second-man support'},
  interpretation:{text:'Two approaches have plausible merits.'},
  takeaway:{text:'Watch teammate coverage before committing.'},
  validation:{claims_structurally_valid:true,future_frames_used:false,
    semantic_tactical_accuracy_verified:false,untraced_numbers:[],rejected_claims:[]},
  alternatives:[
    {label:'Cover behind teammate',status:'supported',
      gains:[{text:'Protect the middle',status:'applies'}],
      risks:[{text:'Give up pressure',status:'applies'}]}],
  decision_context:[{status:'holds',reading:'Teammate is ahead'}],
  assumptions:{decisive:[{question:'Will teammate recover?'}]},
  retrospective:{
    observed_action:{label:'Held middle'},
    assessment:{text:'Reasonable if the teammate was not recovered.'},
    outcome:{touch_sequence:[{by:'opponent',t_after_s:1.1}],goal:null},
    outcome_independence:'Actual outcome did not change the decision-time reading.'
  },
  ...custom
});
const report=(findings=[validFinding()])=>({
  schema:'CoachingReportV1',experimental:true,expert_validated:false,
  method:{model_called:false,ranking_uses_future:false,retrospective_included:true},
  findings
});
const response=(body,ok=true)=>({ok,json:async()=>body});
function flattenText(node){
  return [node.textContent,...node.children.flatMap(flattenText)].join(' | ');
}

test('report can run ONLY for a confirmed real 2v2 player selection',()=>{
  const {api}=setup();
  const a=scene();
  assert.ok(api.validSelection(a));
  a.focusConfirmed=false;
  assert.equal(api.validSelection(a),null);
  a.focusConfirmed=true;a.replay.source='synthetic';
  assert.equal(api.validSelection(a),null);
  a.replay.source='native-replay';a.replay.players[3].team='blue';
  assert.equal(api.validSelection(a),null);
  a.replay.players[3].team='orange';a.focusId='none';
  assert.equal(api.validSelection(a),null);
});

test('source validation refuses expert claims, future-based ranking and untraced numbers',()=>{
  const {api}=setup();
  assert.equal(api.verifyResponse({...report(),expert_validated:true}),null);
  assert.equal(api.verifyResponse({...report(),method:{
    model_called:false,ranking_uses_future:true,retrospective_included:true}}),null);
  assert.equal(api.verifyResponse({...report(),method:{
    model_called:true,ranking_uses_future:false,retrospective_included:true}}),null);
  const ok=api.verifyResponse(report([
    validFinding(),
    validFinding({finding_id:'F2',validation:{
      claims_structurally_valid:true,future_frames_used:false,
      semantic_tactical_accuracy_verified:false,
      untraced_numbers:['unsupported'],rejected_claims:[]}}),
    validFinding({finding_id:'F3',status:'withheld_validation_failed'})
  ]));
  assert.equal(ok.findings.length,1);
  assert.equal(ok.withheld,2);
});

test('aerial/wall observation-only report displays without inventing a verdict',()=>{
  const {api}=setup();
  const data=report([validFinding({
    kind:'observation_only',
    situation:{class:'aerial_or_wall',label:'Aerial or wall'},
    takeaway:{text:null},
    alternatives:[],
  })]);
  const result=api.verifyResponse(data);
  assert.equal(result.findings.length,1);
});

test('no automatic request; explicit click calls local API and keeps future in collapsed section',async()=>{
  const {api,elements}=setup(),s=scene(),calls=[],jumps=[];
  const ui=new api.ExperimentalReportController(()=>s,async(url,options)=>{
    calls.push({url,body:JSON.parse(options.body)});
    return response(report());
  },t=>jumps.push(t));
  ui.mount();
  assert.equal(calls.length,0);
  assert.equal(elements.get('experimentalReportBtn').disabled,false);
  assert.equal(await ui.run(),true);
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/api/coach/coaching-report-v1');
  assert.equal(calls[0].body.max_findings,6);
  assert.equal(calls[0].body.include_retrospective,true);
  assert.equal(calls[0].body.player_id,'b1');
  const panel=elements.get('experimentalReportResults');
  const cards=panel.children.filter(x=>x.className==='experimental-report-card');
  assert.equal(cards.length,1);
  const later=cards[0].children.find(x=>x.className==='experimental-report-outcome');
  assert.equal(later.name,'details','Retrospective cannot appear as initial Stage A prose');
  assert.equal(later.open,undefined,'Outcome drawer starts closed');
  assert.match(flattenText(cards[0]),/Watch teammate coverage/i);
  const seek=cards[0].children[0].children[1];
  seek.onclick();
  assert.deepEqual(jumps,[31.12]);
});

test('blind predecision masking disallows new analyses and hides previously cached findings',async()=>{
  const {api,root,elements}=setup(),s=scene();
  let blind=false,calls=0;
  root.blindReviewUI={isPredecisionOpen:()=>blind};
  const ui=new api.ExperimentalReportController(()=>s,async()=>{
    calls++;return response(report());
  });
  ui.mount();
  await ui.run();
  assert.equal(calls,1);
  blind=true;ui.render();
  assert.equal(elements.get('experimentalReportBtn').disabled,true);
  assert.equal(elements.get('experimentalReportResults').children.filter(
    x=>x.className==='experimental-report-card').length,0);
  assert.equal(await ui.run(),false);
  assert.equal(calls,1);
  blind=false;ui.render();
  assert.equal(elements.get('experimentalReportResults').children.filter(
    x=>x.className==='experimental-report-card').length,1);
});

test('switching matches or players during long analysis discards stale report response',async()=>{
  const {api,elements}=setup(),s=scene();
  let complete;
  const ui=new api.ExperimentalReportController(()=>s,async()=>new Promise(resolve=>{
    complete=resolve;
  }));
  ui.mount();
  const first=ui.run();
  await Promise.resolve();
  s.focusId='b2';
  ui.selectionChanged();
  complete(response(report()));
  assert.equal(await first,false);
  assert.equal(elements.get('experimentalReportResults').children.length,0);
  assert.equal(ui.cache.size,0);
});

test('UI is integrated with local route, honest capability flags and human blind stage',()=>{
  const app=readFileSync(new URL('../../coach_app/static/app.js',import.meta.url),'utf8');
  const html=readFileSync(new URL('../../coach_app/static/index.html',import.meta.url),'utf8');
  const blind=readFileSync(new URL('../../coach_app/static/blind-review.js',import.meta.url),'utf8');
  assert.match(app,/ReplayLabExperimentalReport\.ExperimentalReportController/);
  assert.match(app,/source:'experimental_not_expert_validated'/);
  assert.match(html,/id="experimentalReportPanel"/);
  assert.match(html,/id="experimentalReportBtn"/);
  assert.match(html,/src="\/static\/experimental-report\.js"/);
  assert.match(blind,/for\(const id of \['coachingSection','experimentalReportPanel'/);
});

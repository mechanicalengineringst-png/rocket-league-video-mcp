import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source=readFileSync(new URL('../../coach_app/static/report-v2.js',import.meta.url),'utf8');
class MockEl {
  constructor(tag='div'){
    this.tag=tag;this.className='';this.children=[];this.textContent='';
    this.hidden=false;this.disabled=false;this.onclick=null;this.open=undefined;
  }
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];}
}
function setup(){
  const ids=['reportV2Panel','reportV2Btn','reportV2Status','reportV2Results'];
  const elements=new Map(ids.map(id=>[id,new MockEl(id)]));
  const listeners={};
  const root={
    document:{
      getElementById:id=>elements.get(id)||null,
      createElement:tag=>new MockEl(tag),
    },
    addEventListener:(name,fn)=>{listeners[name]=fn;},
  };
  root.globalThis=root;
  runInNewContext(source,root,{filename:'report-v2.js'});
  return {root,elements,listeners,API:root.ReplayLabReportV2};
}
function selected(){
  return {focusConfirmed:true,focusId:'b1',
    replay:{source:'native-replay',duration:120,players:[
      {id:'b1',team:'blue'},{id:'b2',team:'blue'},
      {id:'o1',team:'orange'},{id:'o2',team:'orange'}
    ],frames:[{t:0},{t:20},{t:60},{t:120}]}};
}
function finding(custom={}){
  return {
    schema:'CoachingFindingV1',finding_id:'M1F1',t0:19,status:'ok',
    kind:'several_defensible',
    situation:{class:'first_defender',label:'Defensive delay'},
    interpretation:{text:'Goal-side cover is a plausible choice.'},
    takeaway:{text:'Check teammate cover before stepping in.'},
    validation:{claims_structurally_valid:true,future_frames_used:false,
      semantic_tactical_accuracy_verified:false,untraced_numbers:[],
      rejected_claims:[]},
    alternatives:[{label:'Hold goal-side',status:'supported',
      gains:[{text:'Protect net'}],risks:[{text:'Give space'}]}],
    decision_context:[{status:'holds',reading:'Last defender'}],
    retrospective:{
      observed_action:{label:'Challenged'},
      assessment:{verdict:'questionable',text:'You definitely made a terrible mistake',
        verdict_v2:'against_rule_read_unconfirmed',
        text_v2:'Went against the rule read; evidence does not prove a mistake.'},
      outcome:{goal:'opponent'},outcome_independence:'Outcomes do not grade choices.'
    },...custom,
  };
}
function report(custom={}){
  return {
    schema:'CoachingReportV2',version:'coach-report-v2/0.1',
    experimental:true,expert_validated:false,
    method:{model_called:false,ledger:'r13',
      stage_separation:'decision time uses only predecision evidence'},
    habit_profile:{schema:'HabitProfileV0',replays:1,habits:[
      {description:'Both near the ball',rate:.28,n:250,
       reliable_with_these_matches:false,standout:null,
       status:'needs about 2 matches before it describes a tendency',examples:[10,20]}
    ],reference:{note:'Unknown rank reference, not quality labels.'}},
    matches:[{match_index:0,team:'blue',situations_analysed:12,
      decision_findings:[finding()],
      turning_points:[{t_start:20,t_end:22,direction:'loss',
        team_control_change:-.25,your_movement_effect:-.14,
        your_share_of_attributed_change:.35,your_movement:'lowered',
        touches:[{t:21,by:'opponent'}],
        decision_time_reading:{t0:19,class:'first_defender',
          interpretation:'Holding might be useful at decision time.',
          takeaway:'Keep net coverage.'}
      }]}],
    evidence_status:[{component:'Counterfactual simulator',
      status:'failed validation',detail:'Not used for judgments.'}],
    limits:['Unknown-rank cohort; no expert merit labels.'],...custom
  };
}
function response(body,ok=true){return {ok,json:async()=>body};}
function flatten(node){return [node.textContent,...node.children.flatMap(flatten)].join(' ');}
const details=(node,cls)=>[
  ...(node.className===cls?[node]:[]),
  ...node.children.flatMap(x=>details(x,cls))
];

test('V2 validates a single truthful local report; rejects simulated and ambiguous players',()=>{
  const {API}=setup(),s=selected();
  assert.ok(API.validSelection(s));
  assert.ok(API.verifyResponse(report(),120));
  s.focusConfirmed=false;assert.equal(API.validSelection(s),null);
  s.focusConfirmed=true;s.replay.source='synthetic';
  assert.equal(API.validSelection(s),null);
  s.replay.source='native-replay';s.replay.players[3].team='blue';
  assert.equal(API.validSelection(s),null);
  s.replay.players[3].team='orange';s.focusId='unknown';
  assert.equal(API.validSelection(s),null);
});

test('V2 rejects fabricated expert validation, outbound AI, and premature habit standout',()=>{
  const {API}=setup();
  assert.equal(API.verifyResponse(report({expert_validated:true}),120),null);
  assert.equal(API.verifyResponse(report({method:{model_called:true,ledger:'r13'}}),120),null);
  const premature=report();
  premature.habit_profile.habits[0].standout='high';
  assert.equal(API.verifyResponse(premature,120),null);
  const badTiming=report();
  badTiming.matches[0].turning_points[0].t_end=400;
  assert.equal(API.verifyResponse(badTiming,120),null);
  const second=report();
  second.matches.push({...second.matches[0],match_index:1});
  assert.equal(API.verifyResponse(second,120),null);
});

test('V2 withholds source-invalid Stage A rather than turning it into coaching',()=>{
  const {API}=setup();
  const bad=finding({validation:{
    claims_structurally_valid:true,future_frames_used:true,
    semantic_tactical_accuracy_verified:false,untraced_numbers:[],rejected_claims:[]}});
  const r=report();
  r.matches[0].decision_findings=[finding(),bad];
  const outcome=API.verifyResponse(r,120);
  assert.equal(outcome.findings.length,1);
  assert.equal(outcome.withheld,1);
});

test('explicit V2 run is local, no automatic request, and V1 mistake verdict never rendered',async()=>{
  const {API,elements}=setup(),s=selected(),calls=[],jumps=[];
  const ui=new API.ReportV2Controller(()=>s,async(url,options)=>{
    calls.push({url,options});
    return response(report());
  },t=>jumps.push(t));
  ui.mount();
  assert.equal(calls.length,0);
  assert.equal(elements.get('reportV2Btn').disabled,false);
  assert.equal(await ui.run(),true);
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/api/coach/coaching-report-v2');
  const payload=JSON.parse(calls[0].options.body);
  assert.equal(payload.player_id,'b1');
  assert.equal(payload.max_findings,6);
  assert.equal(payload.replay,s.replay===undefined?null:payload.replay); // serialized by same-localhost fetch
  const holder=elements.get('reportV2Results');
  assert.match(flatten(holder),/One replay is insufficient/);
  assert.match(flatten(holder),/Turning points/);
  assert.match(flatten(holder),/No expert merit labels|Unknown-rank cohort/i);
  assert.doesNotMatch(flatten(holder),/You definitely made a terrible mistake/);
  assert.match(flatten(holder),/Went against the rule read; evidence does not prove a mistake/);
  const outcomes=details(holder,'experimental-report-outcome');
  assert.equal(outcomes.length,1);
  assert.equal(outcomes[0].tag,'details');
  assert.equal(outcomes[0].open,undefined,'Stage B starts closed');
  const buttons=details(holder,'button-mini');
  assert.ok(buttons.length>=2);
  buttons[0].onclick();
  assert.equal(jumps.length,1);
});

test('blind Stage A masks cached V2 output and prevents fresh analysis',async()=>{
  const {API,root,elements}=setup(),s=selected();
  let blind=false,n=0;
  root.blindReviewUI={isPredecisionOpen:()=>blind};
  const ui=new API.ReportV2Controller(()=>s,async()=>{
    n++;return response(report());
  });
  ui.mount();await ui.run();
  assert.equal(n,1);
  blind=true;ui.render();
  assert.equal(elements.get('reportV2Btn').disabled,true);
  assert.doesNotMatch(flatten(elements.get('reportV2Results')),/Turning points|Goal-side cover/);
  assert.equal(await ui.run(),false);
  assert.equal(n,1);
  blind=false;ui.render();
  assert.match(flatten(elements.get('reportV2Results')),/Turning points/);
});

test('long V2 request for previous selected player does not appear under new player',async()=>{
  const {API,elements}=setup(),s=selected();
  let finish;
  const ui=new API.ReportV2Controller(()=>s,
    async()=>new Promise(resolve=>{finish=resolve;}));
  ui.mount();
  const promise=ui.run();await Promise.resolve();
  s.focusId='b2';ui.selectionChanged();
  finish(response(report()));
  assert.equal(await promise,false);
  assert.equal(ui.cache.size,0);
  assert.equal(elements.get('reportV2Results').children.length,0);
});

test('browser integration exists and blind-review controller hides V2 panel',()=>{
  const html=readFileSync(new URL('../../coach_app/static/index.html',import.meta.url),'utf8');
  const app=readFileSync(new URL('../../coach_app/static/app.js',import.meta.url),'utf8');
  const blind=readFileSync(new URL('../../coach_app/static/blind-review.js',import.meta.url),'utf8');
  assert.match(html,/id="reportV2Panel"/);
  assert.match(html,/id="reportV2Btn"/);
  assert.match(html,/src="\/static\/report-v2.js"/);
  assert.match(app,/ReplayLabReportV2\.ReportV2Controller/);
  assert.match(app,/source:'round13_v2_experimental_unverified'/);
  assert.match(blind,/reportV2Panel/);
  assert.match(blind,/root\.reportV2UI\?\.render/);
});

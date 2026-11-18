import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source=readFileSync(new URL('../../coach_app/static/blind-review.js',
  import.meta.url),'utf8');
const ids=['blindReviewPanel','blindReviewSelection','blindReviewStatus',
  'blindStartControls','blindPriorExposure','blindStartBtn',
  'blindPreStage','blindPreAction','blindPreCoverage','blindPreConfidence',
  'blindPreRationale','blindLockBtn','blindPostStage',
  'blindPreLockedSummary','blindRevealBtn','blindOpenModelBtn',
  'blindPostDecision','blindPostExecution','blindPostModel','blindPostNotes',
  'blindFinishBtn','blindExportBtn','blindReportSummary',
  'coachingSection','modelCoachPanel','videoPanel','companionPanel',
  'lensRevealBtn','lensAfterBtn','lensLoopBtn'];

function setup(){
  const elements=new Map(ids.map(id=>[id,{
    id,hidden:false,disabled:false,textContent:'',value:'',
    checked:false,open:false,click(){},onclick:null,
  }]));
  elements.get('blindPriorExposure').value='unseen';
  const downloads=[];
  const root={
    document:{
      getElementById:id=>elements.get(id)||null,
      createElement:()=>({click(){downloads.push(true)}})
    },
    addEventListener:()=>{},
    setTimeout:cb=>cb(),
    Blob,URL:{createObjectURL:()=>'/test-report.json',revokeObjectURL:()=>{}}
  };
  root.globalThis=root;
  runInNewContext(source,root,{filename:'blind-review.js'});
  return {api:root.ReplayLabBlindReview,elements,downloads,root};
}
function scene(){
  const replay={
    source:'native-replay',duration:120,title:'PRIVATE_REPLAY_FILENAME_DO_NOT_EXPORT',
    players:[{id:'PRIVATE_focus',team:'blue'},{id:'teammate-id',team:'blue'},
      {id:'enemy-1',team:'orange'},{id:'enemy-2',team:'orange'}]
  };
  const request={replay,player_id:'PRIVATE_focus',decision_times:[12,17.5,21.1],
    primary_t0:21.1,episode_start_s:11.0};
  const ep={episode_id:'private-episode-1',selection_source:'automatic',
    backendRequest:request};
  return {replay,focusId:'PRIVATE_focus',focusConfirmed:true,
    coach:{isDemo:false,activeEpisode:ep,
      activeNode:{node_id:'N3',is_primary:true,t0:21.1}}};
}
function createReviewer(s,custom={}){
  const ui=setup();
  const calls={start:[],locked:[],reveals:[],model:0};
  const controller=new ui.api.BlindReviewController(()=>s,{
    onStart:t=>calls.start.push(t),
    onLocked:t=>calls.locked.push(t),
    onReveal:t=>{calls.reveals.push(t);return true;},
    onOpenModel:()=>{calls.model++;},
    modelSummary:()=>custom.modelSummary||null
  });
  ui.root.blindReviewUI=controller;
  controller.mount();
  return {...ui,controller,calls};
}
function validPre(elements){
  elements.get('blindPreAction').value='fake_pressure';
  elements.get('blindPreCoverage').value='exposed';
  elements.get('blindPreConfidence').value='4';
  elements.get('blindPreRationale').value='Teammate may not be recovered; avoid committing until they rotate.';
}
function validPost(elements,ai='not_tested'){
  elements.get('blindPostDecision').value='tradeoff';
  elements.get('blindPostExecution').value='mechanical_error';
  elements.get('blindPostModel').value=ai;
  elements.get('blindPostNotes').value='Outcome was bad despite defensible positioning.';
}
const clean=x=>JSON.parse(JSON.stringify(x));

test('starts only on confirmed real 2v2 source-backed primary episode, never demo',()=>{
  const s=scene();
  const {api,controller}=createReviewer(s);
  assert.equal(api.validSelection(s)?.t0,21.1);
  assert.equal(controller.playbackLimit(),null);
  s.focusConfirmed=false;
  assert.equal(api.validSelection(s),null);
  assert.equal(controller.start(),false);
  s.focusConfirmed=true;
  s.replay.source='synthetic';
  assert.equal(api.validSelection(s),null);
  s.replay.source='native-replay';
  s.coach.activeNode.is_primary=false;
  assert.equal(api.validSelection(s),null);
  s.coach.activeNode.is_primary=true;
  s.coach.activeEpisode.backendRequest.primary_t0=22;
  assert.equal(api.validSelection(s),null,'must not silently analyze a different timestamp');
});

test('start masks AI/coach/outcome/video and caps parent playback until Stage A is locked',()=>{
  const s=scene();
  const {controller,elements,calls}=createReviewer(s);
  assert.equal(controller.start(),true);
  assert.deepEqual(calls.start,[21.1]);
  assert.equal(controller.playbackLimit(),21.1);
  assert.equal(controller.isPredecisionOpen(),true);
  for(const id of ['coachingSection','modelCoachPanel','videoPanel',
      'companionPanel','lensRevealBtn','lensAfterBtn','lensLoopBtn'])
    assert.equal(elements.get(id).hidden,true,id+' should be masked');
  assert.equal(controller.report().reviews.length,0,'no unlocked opinions export as independent data');
  assert.equal(controller.requestOutcomeReveal(),false);
  assert.equal(controller.openModelPanel(),false);
  assert.equal(calls.model,0);
  assert.equal(controller.start(),false,'do not duplicate independent assessment');
  validPre(elements);
  assert.equal(controller.lockPredecision(),true);
  assert.equal(controller.playbackLimit(),null);
  for(const id of ['coachingSection','modelCoachPanel','lensRevealBtn'])
    assert.equal(elements.get(id).hidden,false,id+' should be restored');
  assert.deepEqual(calls.locked,[21.1]);
  assert.equal(controller.current().stage_a.preferred_action,'fake_pressure');
  elements.get('blindPreAction').value='challenge';
  assert.equal(controller.current().stage_a.preferred_action,'fake_pressure',
    'future response cannot rewrite previously locked predecision choice');
});

test('requires an independent action, coverage and confidence before postdecision',()=>{
  const s=scene();
  const {controller,elements}=createReviewer(s);
  assert.equal(controller.start(),true);
  assert.equal(controller.lockPredecision(),false);
  elements.get('blindPreAction').value='shadow_delay';
  elements.get('blindPreCoverage').value='unclear';
  elements.get('blindPreConfidence').value='0';
  assert.equal(controller.lockPredecision(),false);
  elements.get('blindPreConfidence').value='3';
  assert.equal(controller.lockPredecision(),true);
  assert.equal(controller.current().stage_a.teammate_coverage,'unclear');
  assert.equal(controller.current().stage_a.confidence_1_to_5,3);
});

test('Stage B reveals only on explicit click and judges decision versus execution separately',()=>{
  const s=scene();
  const {controller,elements,calls}=createReviewer(s);
  controller.start();validPre(elements);controller.lockPredecision();
  assert.equal(calls.reveals.length,0);
  assert.equal(controller.requestOutcomeReveal(),true);
  assert.deepEqual(calls.reveals,[21.1]);
  assert.equal(controller.openModelPanel(),true);
  assert.equal(calls.model,1);
  validPost(elements,'not_tested');
  assert.equal(controller.finish(),true);
  const r=controller.report();
  assert.equal(r.summary.completed_reviews,1);
  assert.equal(r.reviews[0].stage_a.preferred_action,'fake_pressure');
  assert.equal(r.reviews[0].stage_b.decision_quality_after_review,'tradeoff');
  assert.equal(r.reviews[0].stage_b.execution_quality_after_review,'mechanical_error');
  assert.equal(r.reviews[0].stage_b.ai_advice_quality,'not_tested');
  assert.equal(r.reviews[0].stage_b.outcome_reveal_button_used,true);
  assert.equal(controller.finish(),false,'cannot regrade completed evaluation');
});

test('no model response means false criticism cannot be fabricated',()=>{
  const s=scene();
  const {controller,elements}=createReviewer(s);
  controller.start();validPre(elements);controller.lockPredecision();
  validPost(elements,'false_criticism');
  assert.equal(controller.finish(),false);
  assert.match(controller.status,/No model proposal/);
  elements.get('blindPostModel').value='not_tested';
  assert.equal(controller.finish(),true);
  assert.equal(controller.report().summary.user_marked_false_criticism,0);
});

test('human can rate false criticism only when model proposal actually exists',()=>{
  const s=scene();
  const {controller,elements}=createReviewer(s,{
    modelSummary:{mode:'model_proposal',grade:'risky',accepted:2,rejected:1}
  });
  controller.start();validPre(elements);controller.lockPredecision();
  validPost(elements,'false_criticism');
  assert.equal(controller.finish(),true);
  const report=controller.report();
  assert.equal(report.summary.user_marked_false_criticism,1);
  assert.equal(report.reviews[0].stage_b.model_result_snapshot.model_grade_hypothesis,'risky');
  assert.equal(report.reviews[0].stage_b.model_result_snapshot.accepted_model_claims,2);
  assert.equal(report.reviews[0].stage_b.prior_exposure_self_reported_only,true);
  assert.equal(report.strategic_merit_expert_verified,false);
});

test('selection changes abandon unlocked Stage A, prevent data contamination and permit retry',()=>{
  const s=scene();
  const {controller,elements}=createReviewer(s);
  controller.start();validPre(elements);
  s.focusId='teammate-id';
  s.coach.activeEpisode.backendRequest.player_id='teammate-id';
  controller.selectionChanged();
  assert.equal(controller.playbackLimit(),null);
  assert.equal(controller.report().reviews.length,0);
  assert.equal(elements.get('coachingSection').hidden,false);
  s.focusId='PRIVATE_focus';
  s.coach.activeEpisode.backendRequest.player_id='PRIVATE_focus';
  controller.selectionChanged();
  assert.equal(controller.start(),true);
  assert.equal(controller.playbackLimit(),21.1);
});

test('report anonymizes user filenames/player IDs, tracks manual findings across matches',()=>{
  const s=scene();
  const {controller,elements,downloads}=createReviewer(s);
  controller.start();validPre(elements);controller.lockPredecision();
  validPost(elements);controller.finish();
  const another=scene();
  another.replay.title='SECRET_SECOND_MATCH';
  another.coach.activeEpisode.selection_source='manual';
  s.replay=another.replay;s.focusId=another.focusId;s.coach=another.coach;
  controller.selectionChanged();
  assert.equal(controller.start(),true);
  validPre(elements);controller.lockPredecision();
  validPost(elements);controller.finish();
  const report=clean(controller.report());
  assert.equal(report.summary.matches_with_locked_reviews,2);
  assert.equal(report.summary.manually_selected_moments,1);
  assert.deepEqual(report.reviews.map(x=>x.match_index),[1,2]);
  assert.equal(report.reviews[1].selection_source,'manual');
  assert.equal(report.summary.locked_predecision_judgments,2);
  assert.equal(report.summary.self_reported_unseen,2);
  const exported=JSON.stringify(report);
  for(const word of ['PRIVATE_REPLAY','PRIVATE_focus','teammate-id','enemy-1',
                       'private-episode','SECRET_SECOND_MATCH','replay.frames'])
    assert.ok(!exported.includes(word),word+' must not leak into report');
  controller.exportReport();
  assert.equal(downloads.length,1);
});

test('stateless Windows application integration has a real playback cutoff and actual reveal guard',()=>{
  const app=readFileSync(
    new URL('../../coach_app/static/app.js',import.meta.url),'utf8');
  const html=readFileSync(
    new URL('../../coach_app/static/index.html',import.meta.url),'utf8');
  const model=readFileSync(
    new URL('../../coach_app/static/model-coaching.js',import.meta.url),'utf8');
  assert.match(app,/const blindCutoff=window\.blindReviewUI\?\.playbackLimit\?\.\(\)/);
  assert.match(app,/Math\.min\(time,maxTime\)/);
  assert.match(app,/const predecisionEnd=window\.blindReviewUI\?\.playbackLimit\?\.\(\)/);
  assert.match(app,/function toggleDecisionLensLoop\(\)\{[\s\S]{0,300}isPredecisionOpen/);
  assert.match(app,/if\(window\.blindReviewUI\?\.isPredecisionOpen\?\.\(\)\)return;/);
  assert.match(app,/ReplayLabBlindReview\.BlindReviewController/);
  assert.match(html,/src="\/static\/blind-review\.js"/);
  assert.match(model,/if\(root\.blindReviewUI\?\.isPredecisionOpen\?\.\(\)\)/);
  assert.match(model,/const blindMasked=Boolean\(root\.blindReviewUI\?\.isPredecisionOpen\?\.\(\)\)/);
});

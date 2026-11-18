/* Round 12E — two-stage blind-ish coaching evaluation, local/browser-only.
 *
 * Explicit user judgments BEFORE advice and outcome reveal; then separately
 * assess decision, execution and AI. Never assert that an earlier clip was
 * genuinely unseen: prior exposure is explicitly self-reported. No provider
 * calls, native game commands, raw replay storage, or background uploads.
 *
 * App integration uses a playback cutoff on the parent clock while Stage A
 * is open. HD/2D inherit that parent timeline; external game/video windows,
 * previously seen replays, browser devtools and nonparent native controls
 * cannot be technically blinded. The UI states these limitations.
 */
(function(root){
  'use strict';
  const SCHEMA='ReplayLabBlindReviewReportV0';
  const EXPOSURE=new Set(['unseen','seen','unsure']);
  const ACTIONS=new Set(['challenge','force_fifty','fake_pressure','shadow_delay',
    'control_possession','rotate_abort','not_enough_information']);
  const COVERAGE=new Set(['covered','exposed','unclear']);
  const QUALITIES=new Set(['defensible','questionable','tradeoff','undetermined']);
  const EXECUTION=new Set(['clean','mechanical_error','opponent_adaptation','undetermined']);
  const MODEL=new Set(['helpful','false_criticism','missed_context','too_generic',
    'not_tested','uncertain']);
  const $=id=>root.document?.getElementById(id)||null;
  const finite=n=>typeof n==='number'&&Number.isFinite(n);
  function validSelection(s){
    const replay=s?.replay,coach=s?.coach,ep=coach?.activeEpisode;
    const node=coach?.activeNode,req=ep?.backendRequest;
    if(!replay||replay.source==='synthetic'||!s.focusConfirmed||
       !s.focusId||!ep||!node||!node.is_primary||coach.isDemo||
       !req||req.replay!==replay||req.player_id!==s.focusId||
       !Array.isArray(req.decision_times)||req.decision_times.length<2||
       req.decision_times.length>4||!req.decision_times.every(finite)||
       !finite(req.primary_t0)||req.primary_t0!==node.t0||
       !finite(req.episode_start_s)||req.episode_start_s>=req.primary_t0||
       !finite(replay.duration)||req.primary_t0>replay.duration||
       !Array.isArray(replay.players)||replay.players.length!==4||
       replay.players.filter(p=>p.team==='blue').length!==2||
       replay.players.filter(p=>p.team==='orange').length!==2||
       !replay.players.some(p=>p.id===s.focusId))return null;
    return {replay,focusId:s.focusId,episodeId:String(ep.episode_id),
      source:ep.selection_source==='manual'?'manual':'automatic',
      t0:req.primary_t0};
  }
  const short=(value,max)=>String(value||'').slice(0,max).trim();
  const prettyAction=(v)=>({
    challenge:'Challenge / commit',force_fifty:'Force a 50/50',
    fake_pressure:'Fake / pressure',shadow_delay:'Shadow / delay',
    control_possession:'Control possession',rotate_abort:'Abort / rotate',
    not_enough_information:'Insufficient information'
  }[v]||'Unselected');

  class BlindReviewController{
    constructor(getSelection,controls={}){
      this.getSelection=getSelection;
      this.controls=controls;
      this.entries=new Map();
      this.replayIds=new WeakMap();
      this.nextReplay=0;this.nextTrial=0;
      this.currentKey=null;
      this.status='Select a real source-backed primary coaching decision.';
    }
    context(){
      const info=validSelection(this.getSelection?.());
      if(!info)return null;
      let idx=this.replayIds.get(info.replay);
      if(!idx){idx=++this.nextReplay;this.replayIds.set(info.replay,idx);}
      // Private selection key is deliberately NOT included in user exports.
      const key=String(idx)+'|'+info.focusId+'|'+info.episodeId+'|'+info.t0;
      return {...info,key,matchIndex:idx};
    }
    current(){
      const ctx=this.context();
      return ctx ? this.entries.get(ctx.key)||null : null;
    }
    playbackLimit(){
      const trial=this.current();
      return trial?.phase==='predecision' ? trial.t0_s : null;
    }
    isPredecisionOpen(){
      return finite(this.playbackLimit());
    }
    mount(){
      if(!$('blindStartBtn'))return;
      $('blindStartBtn').onclick=()=>this.start();
      $('blindLockBtn').onclick=()=>this.lockPredecision();
      $('blindRevealBtn').onclick=()=>this.requestOutcomeReveal();
      $('blindOpenModelBtn').onclick=()=>this.openModelPanel();
      $('blindFinishBtn').onclick=()=>this.finish();
      $('blindExportBtn').onclick=()=>this.exportReport();
      root.addEventListener?.('replay-lab:coaching-moment',()=>this.selectionChanged());
      root.addEventListener?.('replay-lab:replay-ready',()=>this.selectionChanged());
      this.selectionChanged();
    }
    _mask(){
      const masked=this.isPredecisionOpen();
      // Hide automatic coach, AI suggestions, video and native companion
      // while the reviewer makes an independent PREdecision judgment.
      // This does NOT control external game/video windows or previous exposure.
      for(const id of ['coachingSection','modelCoachPanel','videoPanel',
                        'companionPanel','lensRevealBtn','lensAfterBtn','lensLoopBtn']){
        const el=$(id);
        if(el)el.hidden=masked;
      }
      if(root.modelCoachingUI?.render)root.modelCoachingUI.render();
    }
    selectionChanged(){
      const ctx=this.context();
      const key=ctx?.key??null;
      if(this.currentKey!==key){
        const old=this.entries.get(this.currentKey);
        if(old?.phase==='predecision'){
          // An unfinished, unrecorded first impression is not an
          // independent data point. A reviewer may try again after
          // accidentally switching away, without inflating the report.
          this.entries.delete(this.currentKey);
        }
        this.currentKey=key;
        this.status=ctx?'Ready for a new independent judgment.':
          'Select a real source-backed primary coaching decision and confirm the player.';
      }
      this._mask();this.render();
    }
    start(){
      const ctx=this.context();
      if(!ctx||this.entries.has(ctx.key)){
        this.status='A valid real primary decision is required. Each episode is evaluated only once per session.';
        this.render();return false;
      }
      const exposure=$('blindPriorExposure')?.value||'unsure';
      if(!EXPOSURE.has(exposure))return false;
      const trial={
        key:ctx.key,match_index:ctx.matchIndex,
        trial_index:++this.nextTrial,
        t0_s:ctx.t0,selection_source:ctx.source,
        self_reported_prior_outcome_exposure:exposure,
        phase:'predecision',
        stage_a:null,stage_b:null,
        outcome_reveal_requested:false,model_panel_opened:false,
      };
      this.entries.set(ctx.key,trial);
      this.currentKey=ctx.key;
      this.status='Stage A: review recorded gameplay up to t0; commit your own decision before revealing later events or model advice.';
      this._mask();
      this.controls.onStart?.(ctx.t0);
      this.render();
      return true;
    }
    lockPredecision(){
      const trial=this.current();
      if(!trial||trial.phase!=='predecision')return false;
      const action=$('blindPreAction')?.value;
      const coverage=$('blindPreCoverage')?.value;
      const confidence=Number($('blindPreConfidence')?.value);
      if(!ACTIONS.has(action)||!COVERAGE.has(coverage)||
        !Number.isInteger(confidence)||confidence<1||confidence>5){
        this.status='Select your intended action, perceived teammate coverage, and confidence before locking.';
        this.render();return false;
      }
      trial.stage_a={
        preferred_action:action,
        teammate_coverage:coverage,
        confidence_1_to_5:confidence,
        rationale:short($('blindPreRationale')?.value,1200),
        locked_before_in_app_outcome_reveal:true,
        actual_prior_exposure_not_verifiable:true,
      };
      trial.phase='postdecision';
      this.status='Stage A locked. You can now reveal recorded follow-through, examine the separate AI proposal, and judge execution independently.';
      this._mask();
      this.controls.onLocked?.(trial.t0_s);
      this.render();
      return true;
    }
    requestOutcomeReveal(){
      const trial=this.current();
      if(!trial||trial.phase!=='postdecision')return false;
      // The existing Decision Lens reveals *actual* recorded follow-through,
      // NOT a simulated alternative, and only on explicit user interaction.
      const success=this.controls.onReveal?.(trial.t0_s)===true;
      if(success)trial.outcome_reveal_requested=true;
      this.status=success?'Recorded follow-through explicitly revealed in Decision Lens.':'Recorded postdecision frames are unavailable or the current scene could not be synchronized.';
      this.render();return success;
    }
    openModelPanel(){
      const trial=this.current();
      if(!trial||trial.phase!=='postdecision')return false;
      trial.model_panel_opened=true;
      this.controls.onOpenModel?.();
      this.status='AI proposals remain optional and may incur provider charges. Model generation still requires separate one-request consent.';
      this.render();return true;
    }
    finish(){
      const trial=this.current();
      if(!trial||trial.phase!=='postdecision')return false;
      const decision=$('blindPostDecision')?.value;
      const execution=$('blindPostExecution')?.value;
      const advice=$('blindPostModel')?.value;
      if(!QUALITIES.has(decision)||!EXECUTION.has(execution)||!MODEL.has(advice)){
        this.status='Give a separate judgment for decision, execution and advice. Select undetermined/not tested where appropriate.';
        this.render();return false;
      }
      const availableModel=this.controls.modelSummary?.();
      if(!availableModel && !['not_tested','uncertain'].includes(advice)){
        this.status='No model proposal was generated for this decision. Choose Not tested or Cannot assess instead of grading nonexistent AI advice.';
        this.render();return false;
      }
      let m=null;
      try{
        const source=this.controls.modelSummary?.();
        if(source&&source.mode==='model_proposal'){
          m={model_proposal_generated:true,model_grade_hypothesis:source.grade,
            accepted_model_claims:source.accepted,rejected_model_claims:source.rejected};
        }
      }catch(_){}
      trial.stage_b={
        decision_quality_after_review:decision,
        execution_quality_after_review:execution,
        ai_advice_quality:advice,
        postdecision_notes:short($('blindPostNotes')?.value,1600),
        model_result_snapshot:m,
        outcome_reveal_button_used:trial.outcome_reveal_requested,
        prior_exposure_self_reported_only:true,
      };
      trial.phase='completed';
      this.status='Evaluation saved in this browser session. Export locally when ready; no data was uploaded.';
      this._mask();this.render();
      return true;
    }
    cancelOpen(){
      const trial=this.current();
      if(trial?.phase==='predecision'){
        this.entries.delete(trial.key);
        this._mask();this.render();
      }
    }
    report(){
      const entries=[...this.entries.values()]
        .filter(t=>t.stage_a && ['postdecision','completed'].includes(t.phase))
        .map(t=>({
          match_index:t.match_index,
          trial_index:t.trial_index,
          t0_s:t.t0_s,
          selection_source:t.selection_source,
          review_phase:t.phase,
          self_reported_prior_outcome_exposure:t.self_reported_prior_outcome_exposure,
          stage_a:{...t.stage_a},
          stage_b:t.stage_b?{...t.stage_b}:null,
        }));
      const complete=entries.filter(t=>t.review_phase==='completed');
      return {
        schema:SCHEMA,
        generated_at:new Date().toISOString(),
        anonymization:'match indices only; no replay names, player IDs, raw frames, provider details or credentials',
        study_design:'self-reported predecision observation; outside-game viewing and previous exposure cannot be verified',
        no_automated_ai_calls:true,
        strategic_merit_expert_verified:false,
        summary:{
          matches_with_locked_reviews:new Set(entries.map(t=>t.match_index)).size,
          locked_predecision_judgments:entries.length,
          completed_reviews:complete.length,
          self_reported_unseen:entries.filter(t=>
            t.self_reported_prior_outcome_exposure==='unseen').length,
          manually_selected_moments:entries.filter(t=>
            t.selection_source==='manual').length,
          user_marked_false_criticism:complete.filter(t=>
            t.stage_b?.ai_advice_quality==='false_criticism').length,
          positive_decision_reviews:complete.filter(t=>
            t.stage_b?.decision_quality_after_review==='defensible').length,
        },
        reviews:entries,
      };
    }
    exportReport(){
      // Only direct user action; no network and no persistent store.
      const data=this.report();
      const blob=new Blob([JSON.stringify(data,null,2)],
        {type:'application/json'});
      const url=URL.createObjectURL(blob);
      const link=root.document.createElement('a');
      link.href=url;link.download='replay-lab-blind-coaching-review.json';
      link.click();
      root.setTimeout?.(()=>URL.revokeObjectURL(url),1000);
      this.status='Anonymized session evaluation exported locally.';
      this.render();
    }
    render(){
      if(!$('blindStartBtn'))return;
      const context=this.context();
      const trial=this.current();
      const phase=trial?.phase;
      $('blindStartBtn').disabled=!context||!!trial;
      if($('blindReviewSelection'))
        $('blindReviewSelection').textContent=context?
          'Selected '+context.source+' decision at '+context.t0.toFixed(2)+'s · no source outcome shown by this tool':
          'Load a real 2v2 replay and select its primary coaching decision.';
      if($('blindPreStage'))$('blindPreStage').hidden=phase!=='predecision';
      if($('blindPostStage'))$('blindPostStage').hidden=
        phase!=='postdecision'&&phase!=='completed';
      if($('blindStartControls'))$('blindStartControls').hidden=!!trial;
      if($('blindLockBtn'))$('blindLockBtn').disabled=phase!=='predecision';
      if($('blindRevealBtn'))$('blindRevealBtn').disabled=phase!=='postdecision';
      if($('blindOpenModelBtn'))$('blindOpenModelBtn').disabled=phase!=='postdecision';
      if($('blindFinishBtn'))$('blindFinishBtn').disabled=phase!=='postdecision';
      if($('blindReviewStatus'))$('blindReviewStatus').textContent=this.status;
      if($('blindPreLockedSummary')){
        const item=trial?.stage_a;
        $('blindPreLockedSummary').textContent=item?
          'Locked predecision: '+prettyAction(item.preferred_action)+
          ' · teammate '+item.teammate_coverage+
          ' · confidence '+item.confidence_1_to_5+'/5'+
          (item.rationale?' · '+item.rationale:''):
          'No predecision judgment has been locked.';
      }
      if($('blindReportSummary')){
        const sum=this.report().summary;
        $('blindReportSummary').textContent=
          sum.locked_predecision_judgments+' locked · '+
          sum.completed_reviews+' completed · '+
          sum.manually_selected_moments+' owner-selected · '+
          sum.user_marked_false_criticism+' flagged false criticism';
      }
    }
  }
  root.ReplayLabBlindReview=Object.freeze({
    SCHEMA,validSelection,BlindReviewController,
  });
  if(typeof module!=='undefined'&&module.exports)
    module.exports=root.ReplayLabBlindReview;
})(typeof globalThis!=='undefined'?globalThis:this);

/* Replay Lab — model coaching proposal review (explicit opt-in).
 *
 * UI for the EXISTING /api/coach/lesson mode=model contract. Real AI model
 * quality has never been expert validated. A response may pass source
 * checks while being tactically wrong. No automatic calls, remote prompt
 * persistence, raw replay export, or secrets embedded in browser code.
 */
(function (root) {
  'use strict';

  const VALID_READINESS = new Set(['configured_unverified', 'enabled_unverified']);
  const GRADES = new Set(['undetermined','defensible','risky','tradeoff']);
  const SECTIONS = Object.freeze({
    observation:'Observed fact',
    tactical_context:'Tactical interpretation',
    alternative:'Possible alternative',
    earlier_factor:'Earlier context question',
    takeaway:'Practical takeaway',
    uncertainty:'Unknown or uncertainty',
  });
  const FEEDBACK = new Set(['useful','incorrect','missing_context']);
  const MAX_CLAIMS = 12;
  // Distinguish source-checked proposals from actual coaching success.
  // A clean HTTP response may contain only baseline facts or rejected claims.
  const MODEL_STATES = new Set([
    'model_claims_withheld', 'model_claims_without_tactical_grade',
    'model_tactical_hypothesis'
  ]);
  function verifiedProvenance(v,accepted,rejected,grade){
    const p=v?.response_provenance;
    if(p === undefined){
      // Compatibility with older local servers. Never call this verified.
      return {source:'legacy_provenance_unavailable',status:'legacy_counts_only',
        submitted:accepted+rejected,accepted,rejected,verified:false,
        tacticalHypothesis:accepted>0&&grade!=='undetermined'};
    }
    if(!p || p.source!=='model_draft_evidence_checked' ||
       !MODEL_STATES.has(p.status) ||
       !Number.isInteger(p.model_claims_submitted) ||
       !Number.isInteger(p.model_claims_accepted) ||
       !Number.isInteger(p.model_claims_rejected) ||
       p.model_claims_submitted!==accepted+rejected ||
       p.model_claims_accepted!==accepted ||
       p.model_claims_rejected!==rejected ||
       p.baseline_facts_only!==(accepted===0) ||
       p.tactical_hypothesis_emitted!==(grade!=='undetermined') ||
       p.semantic_accuracy_verified!==false)return null;
    const expected = accepted===0?'model_claims_withheld':
      grade==='undetermined'?'model_claims_without_tactical_grade':
      'model_tactical_hypothesis';
    if(p.status!==expected)return null;
    return {source:p.source,status:p.status,submitted:p.model_claims_submitted,
      accepted,rejected,verified:false,tacticalHypothesis:grade!=='undetermined'};
  }

  function validRequest(selection) {
    const {replay, focusId, focusConfirmed, coach} = selection || {};
    const episode = coach?.activeEpisode;
    const node = coach?.activeNode;
    const request = episode?.backendRequest;
    if (!replay || replay.source === 'synthetic' || coach?.isDemo ||
        !focusConfirmed || !focusId || !episode || !node ||
        !node.is_primary || !request || !Array.isArray(request.decision_times) ||
        request.decision_times.length < 2 || request.decision_times.length > 4 ||
        !request.decision_times.every(Number.isFinite) ||
        !Number.isFinite(request.primary_t0) ||
        !Number.isFinite(request.episode_start_s) ||
        !Number.isFinite(replay.duration) ||
        request.primary_t0 !== node.t0 ||
        request.primary_t0 > replay.duration ||
        request.episode_start_s > request.decision_times[0] ||
        request.player_id !== focusId || request.replay !== replay)
      return null;
    return {
      replay, player_id:focusId,
      decision_times:[...request.decision_times],
      episode_start_s:request.episode_start_s,
      primary_t0:request.primary_t0,
      // The server intentionally forbids experimental V1 input to the model.
      mode:'model', experimental_tactical_v1:false
    };
  }
  function verifiedResponse(raw, requested) {
    if (!raw || raw.schema !== 'CoachLessonV0' || raw.stage !== 'predecision' ||
        raw.mode !== 'model_proposal' ||
        !Number.isFinite(raw.decision?.t0_s) ||
        Math.abs(raw.decision.t0_s - requested.primary_t0) > 0.001 ||
        raw.validation?.future_outcomes_used !== false ||
        raw.validation?.semantic_tactical_accuracy_verified !== false ||
        !GRADES.has(raw.assessment?.grade) ||
        !Number.isInteger(raw.validation?.accepted_model_claims) ||
        raw.validation.accepted_model_claims < 0 ||
        !Array.isArray(raw.validation?.rejected_model_claims) ||
        !Array.isArray(raw.claims))
      return null;
    const modelClaims=raw.claims.filter(c=>c?.author === 'model_proposal');
    if (modelClaims.length !== raw.validation.accepted_model_claims ||
        modelClaims.length > MAX_CLAIMS ||
        raw.validation.rejected_model_claims.some(c=>
          !c || !Number.isInteger(c.index) || c.index<0 ||
          typeof c.reason!=='string' || c.reason.length>250) ||
        modelClaims.some(c=>
          c.review_status !== 'needs_semantic_review' ||
          typeof c.text !== 'string' || !c.text.trim() ||
          c.text.length > 900 || !SECTIONS[c.section] ||
          typeof c.node_id !== 'string' ||
          typeof c.epistemic_type !== 'string' ||
          !Array.isArray(c.evidence_refs) ||
          !c.evidence_refs.length || c.evidence_refs.length > 12 ||
          c.evidence_refs.some(id=>typeof id!=='string'||id.length>160)))
      return null;
    const rejected=raw.validation.rejected_model_claims.length;
    const provenance=verifiedProvenance(raw.validation,modelClaims.length,
      rejected,raw.assessment.grade);
    if(!provenance)return null;
    return {
      mode:'model_proposal',
      grade:raw.assessment.grade,
      provenance,
      rejectionReasons:raw.validation.rejected_model_claims.map(c=>
        'Claim '+String(c.index+1)+': '+c.reason),
      claims:modelClaims.map(c=>({
        claim_id:String(c.claim_id || ''),
        node_id:c.node_id,section:c.section,
        epistemic_type:c.epistemic_type,
        text:c.text.trim(),
        evidence_refs:[...c.evidence_refs]
      })),
      accepted:modelClaims.length,
      rejected,
      merit_verified:false,
      raw_replay_sent_to_provider:false,
      future_outcomes_used:false
    };
  }
  function readableError(code) {
    if (code === 403) return 'The local server has not enabled optional model calls. No proposal was accepted.';
    if (code === 422) return 'This decision could not be safely analyzed by the model. Confirm the player and select its primary decision.';
    if (code === 502) return 'The configured model failed or its structured claims could not pass verification. No proposal was accepted.';
    if (code === 503) return 'The model URL, model name, or provider credentials are not ready. No proposal was accepted.';
    if (code === 413) return 'The replay request is too large for the coaching endpoint.';
    return 'The model request failed. No suggestion was accepted.';
  }
  function readinessLabel(status) {
    return ({
      disabled:'Model disabled in local server',
      needs_configuration:'Model settings incomplete',
      invalid_configuration:'Invalid model settings',
      configured_unverified:'Configured · connection untested',
      enabled_unverified:'Server enabled · provider untested',
      unavailable:'Model status unavailable',
      checking:'Checking model settings'
    })[status] || 'Model status unavailable';
  }
  const $=id=>document.getElementById(id);
  function element(tag,cls,text){
    const e=document.createElement(tag);
    if(cls)e.className=cls;
    if(text!==undefined)e.textContent=String(text);
    return e;
  }
  function jsonSafe(value) {
    const s=JSON.stringify(value);
    return typeof s==='string' ? s : '';
  }
  class ModelCoachingController {
    constructor(getSelection, fetcher) {
      this.getSelection=getSelection;
      this.fetcher=fetcher||((...a)=>root.fetch(...a));
      this.readiness='checking';
      this.requestSeq=0;
      this.readinessSeq=0;
      this.activeKey=null;
      this.abortController=null;
      this.results=new Map();
      this.loading=false;
      this.status='No model request has been made.';
      this.evidenceSeq=0;
      this.spatialSeq=0;
      this.spatialLoading=false;
      this.spatialStatus='Inspect the selected decision using local source-backed geometry.';
    }
    mount(){
      if(!$('modelCoachRunBtn'))return;
      $('modelCoachRunBtn').onclick=()=>this.generate();
      $('modelCoachRefreshBtn').onclick=()=>this.refreshReadiness();
      $('modelCoachConsent').onchange=()=>this.render();
      $('modelCoachExportBtn').onclick=()=>this.exportReport();
      if($('modelCoachSpatialBtn'))$('modelCoachSpatialBtn').onclick=()=>this.inspectSpatial();
      root.addEventListener('replay-lab:coaching-moment',()=>this.selectionChanged());
      root.addEventListener('replay-lab:replay-ready',()=>this.resetForReplay());
      this.selectionChanged();
      this.refreshReadiness();
    }
    getContext(){
      const selection=this.getSelection?.();
      const request=validRequest(selection);
      const ep=selection?.coach?.activeEpisode;
      const key=request&&ep ? String(ep.episode_id)+'|'+String(request.player_id)+'|'+
        String(request.primary_t0) : null;
      return {selection,request,episode:ep,key};
    }
    resetForReplay(){
      this.requestSeq++;
      this.evidenceSeq++;
      this.spatialSeq++;
      this.spatialLoading=false;
      this.spatialStatus='Select a decision to inspect source-backed geometry.';
      $('modelCoachSpatialResults')?.replaceChildren();
      this.abortController?.abort();
      this.abortController=null;
      this.results.clear();
      this.activeKey=null;
      this.loading=false;
      this.status='No model request has been made for this replay.';
      if($('modelCoachConsent'))$('modelCoachConsent').checked=false;
      this.render();
    }
    selectionChanged(){
      const context=this.getContext();
      if(context.key!==this.activeKey){
        this.requestSeq++;
        this.evidenceSeq++;
        this.spatialSeq++;
        this.spatialLoading=false;
        this.spatialStatus='Inspect the selected decision using local source-backed geometry.';
        $('modelCoachSpatialResults')?.replaceChildren();
        this.abortController?.abort();
        this.abortController=null;
        this.loading=false;
        this.activeKey=context.key;
        this.status='No model request has been made for this selected decision.';
        if($('modelCoachConsent'))$('modelCoachConsent').checked=false;
        if($('modelCoachEvidence'))$('modelCoachEvidence').replaceChildren();
        this.render();
      }
    }
    async refreshReadiness(){
      // Checking configuration must never invalidate a paid model response.
      const seq=++this.readinessSeq;
      // This is a read-only preflight, never a model request.
      try{
        const res=await this.fetcher('/api/coach/model-readiness',
          {cache:'no-store'});
        if(res.ok){
          const data=await res.json();
          if(seq!==this.readinessSeq)return;
          this.readiness=data?.schema==='CoachModelReadinessV0' ?
            data.status : 'unavailable';
          this.render();
          return;
        }
        if(res.status!==404)throw Error('readiness unavailable');
      }catch(_){}
      try{
        // Pre-PR41 servers expose only optional_model_enabled.
        const res=await this.fetcher('/api/coach/capabilities',{cache:'no-store'});
        const data=res.ok?await res.json():null;
        if(seq!==this.readinessSeq)return;
        this.readiness=data?.optional_model_enabled===true ?
          'enabled_unverified' : 'disabled';
      }catch(_){
        if(seq===this.readinessSeq)this.readiness='unavailable';
      }
      this.render();
    }
    async generate(){
      const context=this.getContext();
      if(root.blindReviewUI?.isPredecisionOpen?.()){
        this.status='Blind evaluation is collecting your independent Stage A judgment. Lock it before requesting AI advice.';
        this.render();return;
      }
      if(this.loading || !context.request || !context.key ||
          context.key!==this.activeKey || !VALID_READINESS.has(this.readiness) ||
          !$('modelCoachConsent')?.checked){
        this.status='Select a verified primary decision, configure the server, and explicitly authorize one model request.';
        this.render();return;
      }
      const seq=++this.requestSeq;
      const {selection,request,key}=context;
      const replay=selection.replay;
      this.abortController?.abort();
      const controller=new AbortController();
      this.abortController=controller;
      this.loading=true;
      this.status='Sending one decision-time evidence packet to the configured model. Its tactical suggestions are not verified.';
      // One checkbox authorizes ONE request. Never auto-send another request.
      $('modelCoachConsent').checked=false;
      this.render();
      let outcome=null, failure=null;
      try{
        const response=await this.fetcher('/api/coach/lesson',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify(request),
          signal:controller.signal
        });
        if(!response.ok)throw {status:response.status};
        const body=await response.json();
        outcome=verifiedResponse(body,request);
        if(!outcome)throw {status:0};
      }catch(e){
        failure=e?.name==='AbortError'?'Request canceled after selection change.':readableError(e?.status);
      }
      if(seq!==this.requestSeq || this.activeKey!==key ||
          this.getSelection()?.replay!==replay ||
          this.getSelection()?.focusId!==request.player_id)return;
      this.loading=false;
      this.abortController=null;
      if(failure){
        this.status=failure;
      }else{
        this.results.set(key,{...outcome,t0:request.primary_t0,
          feedback:null,note:''});
        this.status=outcome.accepted ?
          'The server accepted '+outcome.accepted+' of '+outcome.provenance.submitted+
          ' model claims for source inspection. Strategic correctness is NOT verified.' :
          'The provider responded, but ALL '+outcome.provenance.submitted+
          ' proposed claims were withheld. Local deterministic evidence remains; NO model coaching was accepted.';
      }
      this.render();
    }
    async inspectSpatial(){
      const context=this.getContext();
      if(!context.request || !context.key || this.spatialLoading ||
         this.activeKey!==context.key)return;
      // Geometry is always local and deterministic, irrespective of model
      // settings or model consent. No provider request is made here.
      const request={...context.request, mode:'deterministic',
        experimental_tactical_v1:false};
      const seq=++this.spatialSeq, key=context.key, replay=context.selection.replay;
      this.spatialLoading=true;
      this.spatialStatus='Inspecting recorded pre-decision geometry locally…';
      this.render();
      let responseData=null;
      try{
        const res=await this.fetcher('/api/coach/scene-relations',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify(request)
        });
        if(!res.ok)throw Error('local scene relations unavailable');
        const body=await res.json();
        const primary=body?.nodes?.[body.nodes.length-1];
        if(body?.schema!=='RelationalInvariantsV0' ||
           body?.stage!=='predecision' ||
           body?.uses_future!==false ||
           body?.calculates_tactical_merit!==false ||
           body?.expert_calibrated!==false ||
           body?.information_cutoff_s!==request.primary_t0 ||
           primary?.t0_s!==request.primary_t0 ||
           !Array.isArray(primary?.metrics) || !Array.isArray(primary?.unknowns) ||
           primary.metrics.length>22 || primary.unknowns.length>24)throw Error('invalid geometry contract');
        responseData=primary;
      }catch(_){}
      if(seq!==this.spatialSeq || this.activeKey!==key ||
         this.getSelection()?.replay!==replay ||
         this.getSelection()?.focusId!==request.player_id)return;
      this.spatialLoading=false;
      const holder=$('modelCoachSpatialResults');
      holder?.replaceChildren();
      if(!responseData){
        this.spatialStatus='The local geometry request could not be verified. No positions or tactical verdicts were invented.';
        this.render();return;
      }
      const metrics=responseData.metrics.filter(m=>
        m && ['longitudinal_goal_side_of_ball','planar_ball_distance',
              'teammate_planar_separation','teammate_lateral_separation',
              'nose_to_ball_angle'].includes(m.metric) &&
        typeof m.subject==='string' && m.subject.length<40 &&
        (typeof m.value==='string' ||
         (typeof m.value==='number' && Number.isFinite(m.value))) &&
        Array.isArray(m.source_refs) && m.source_refs.length>=2 &&
        m.source_refs.length<=3 &&
        m.source_refs.every(r=>typeof r==='string' &&
          /^N[1-4][/](?:E[.])[a-zA-Z0-9_.-]+$/.test(r)));
      // Keep the visible panel compact. All model inputs use the same
      // measured data, and these labels make its limitations inspectable.
      for(const m of metrics){
        const row=element('div','model-spatial-row');
        const label=m.metric.replace(/_/g,' ');
        const value=typeof m.value==='number' ? String(m.value) : m.value;
        row.append(element('strong','',m.subject.replace(/_/g,' ')+': '+label));
        row.append(element('span','',value+(m.unit?' '+m.unit:'')));
        const refs=element('div','model-spatial-refs');
        for(const ref of m.source_refs){
          const b=element('button','button-mini model-source-btn',ref);
          b.type='button';b.onclick=()=>this.inspectEvidence(ref);
          refs.append(b);
        }
        row.append(refs);holder?.append(row);
      }
      if(responseData.unknowns.length){
        holder?.append(element('p','small-copy',
          String(responseData.unknowns.length)+' relationships could not be measured. Missing data is not a strategic conclusion.'));
      }
      this.spatialStatus=metrics.length ?
        'Recorded coordinate relations only · not possession, recovery, safety or a coaching grade.' :
        'This scene lacks fresh enough telemetry for trusted spatial relationships.';
      this.render();
    }
    async inspectEvidence(ref){
      const context=this.getContext();
      if(!context.request || !context.key || context.key!==this.activeKey)return;
      const el=$('modelCoachEvidence');if(!el)return;
      el.replaceChildren(element('p','small-copy','Retrieving the cited source locally…'));
      const seq=++this.evidenceSeq,key=context.key,selection=context.selection;
      const request={...context.request,mode:'deterministic',
        evidence_refs:[ref]};
      try{
        const response=await this.fetcher('/api/coach/evidence',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify(request)
        });
        if(!response.ok)throw Error();
        const data=await response.json();
        if(seq!==this.evidenceSeq||this.activeKey!==key||
            this.getSelection()?.replay!==selection.replay)return;
        const rec=Array.isArray(data.records)?data.records.find(r=>r?.id===ref):null;
        el.replaceChildren();
        if(!rec){el.append(element('p','small-copy','That source is not available for local inspection.'));return;}
        const summary=element('div','model-source-detail');
        summary.append(element('strong','',String(rec.id)));
        summary.append(element('span','',String(rec.category||rec.kind||'Recorded source')));
        const value=rec.value===undefined?String(rec.what||rec.why||'Unknown'):jsonSafe(rec.value);
        summary.append(element('code','',value.slice(0,500)));
        summary.append(element('small','',
          'Source value or unknown marker only. This does not verify the model’s interpretation.'));
        el.append(summary);
      }catch(_){
        if(seq===this.evidenceSeq&&this.activeKey===key)
          el.replaceChildren(element('p','small-copy','Source lookup failed locally. No evidence was invented.'));
      }
    }
    setFeedback(rating){
      const item=this.results.get(this.activeKey);
      if(!item||!FEEDBACK.has(rating))return;
      item.feedback=rating;
      this.render();
    }
    updateNote(note){
      const item=this.results.get(this.activeKey);
      if(item)item.note=String(note||'').slice(0,1000);
    }
    exportSummary(){
      // User-triggered local export only: no model prompts, API credentials,
      // filenames, provider URLs or full replay frames.
      return [...this.results.entries()].map(([key,item])=>({
        schema:'ModelCoachingReviewV0',
        t0_s:item.t0,
        assessment_hypothesis:item.grade,
        source_cited_claims:item.claims,
        accepted_claims:item.accepted,
        rejected_claims:item.rejected,
        model_claims_submitted:item.provenance?.submitted??item.accepted+item.rejected,
        response_provenance:item.provenance?.status??'legacy_provenance_unavailable',
        tactical_hypothesis_emitted:item.provenance?.tacticalHypothesis??false,
        rejection_reasons:item.rejectionReasons||[],
        tactical_accuracy_expert_verified:false,
        feedback:item.feedback,
        tester_note:item.note,
        mode:'explicit_opt_in_model_proposal'
      }));
    }
    exportReport(){
      const report={
        schema:'ReplayLabModelTesterReportV0',
        generated_at:new Date().toISOString(),
        provider_calls_user_authorized_only:true,
        tactical_accuracy_expert_verified:false,
        claims:this.exportSummary()
      };
      const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json'});
      const url=URL.createObjectURL(blob);
      const a=document.createElement('a');
      a.href=url;a.download='replay-lab-model-coaching-test.json';
      a.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
      this.status='Model coaching feedback exported locally.';
      this.render();
    }
    render(){
      if(!$('modelCoachRunBtn'))return;
      const {request,episode}=this.getContext();
      const ready=VALID_READINESS.has(this.readiness);
      const consent=$('modelCoachConsent')?.checked;
      const btn=$('modelCoachRunBtn');
      if($('modelCoachSpatialBtn')){
        $('modelCoachSpatialBtn').disabled=!request || this.spatialLoading;
        $('modelCoachSpatialBtn').textContent=this.spatialLoading ?
          'Measuring local geometry…':'Inspect source-backed geometry';
      }
      if($('modelCoachSpatialStatus'))$('modelCoachSpatialStatus').textContent=this.spatialStatus;
      const blindMasked=Boolean(root.blindReviewUI?.isPredecisionOpen?.());
      btn.disabled=!request || !ready || !consent || this.loading || blindMasked;
      btn.textContent=this.loading?'Evaluating one decision…':'Generate AI coaching for this decision';
      $('modelCoachReadiness').textContent=readinessLabel(this.readiness);
      const name=episode?.title || 'No source-backed primary decision selected';
      $('modelCoachSelected').textContent=request ?
        name+' · decision '+request.primary_t0.toFixed(2)+'s' :
        'Load a real 2v2 replay, confirm the player and select the primary coaching node.';
      $('modelCoachStatus').textContent=this.status;
      const holder=$('modelCoachResults');
      holder.replaceChildren();
      // Even a preexisting, cached model response must not be displayed
      // while the human's predecision judgment is still unlocked.
      if(blindMasked){
        holder.append(element('p','small-copy',
          'Blind review is active. Lock your own choice before seeing any AI suggestion.'));
        return;
      }
      const item=this.results.get(this.activeKey);
      if(!item){
        holder.append(element('p','small-copy',
          ready?'No AI analysis has been requested for this decision.':
          'The deterministic source-backed review remains available without any model.'));
        return;
      }
      const heading=element('div','model-result-heading');
      const state=item.provenance?.status||'legacy_provenance_unavailable';
      const title=state==='model_claims_withheld'?
        'All model claims withheld — deterministic evidence only':
        state==='model_claims_without_tactical_grade'?
        'Source-checked model claims — no tactical grade':
        state==='model_tactical_hypothesis'?
        'Model tactical hypothesis: '+item.grade:
        item.accepted&&item.grade!=='undetermined'?
        'Legacy model hypothesis: '+item.grade+' (provenance unavailable)':
        'Legacy model response (provenance unavailable)';
      heading.append(element('strong','',title));
      heading.append(element('small','',
        String(item.accepted)+' of '+
        String(item.provenance?.submitted??item.accepted+item.rejected)+
        ' model claims passed source checks; '+String(item.rejected)+
        ' rejected. Tactical correctness NOT verified.'));
      holder.append(heading);
      if(item.rejectionReasons?.length){
        const info=element('details','model-rejection-details');
        info.append(element('summary','',
          String(item.rejectionReasons.length)+' source-check rejection reason(s)'));
        for(const reason of item.rejectionReasons.slice(0,12))
          info.append(element('p','small-copy',reason));
        holder.append(info);
      }
      if(!item.claims.length){
        holder.append(element('p','small-copy',
          'No model recommendation passed validation. The replay review remains available without a verdict.'));
      }
      for(const claim of item.claims){
        const row=element('article','model-claim');
        row.append(element('span','model-claim-type',
          (SECTIONS[claim.section]||claim.section)+' · '+claim.node_id));
        row.append(element('p','model-claim-text',claim.text));
        const refs=element('div','model-claim-sources');
        refs.append(element('span','','Source refs:'));
        for(const ref of claim.evidence_refs){
          const b=element('button','button-mini model-source-btn',ref);
          b.type='button';b.title='Inspect this local source without calling a model';
          b.onclick=()=>this.inspectEvidence(ref);
          refs.append(b);
        }
        row.append(refs);
        holder.append(row);
      }
      const feedback=element('div','model-feedback');
      feedback.append(element('strong','','Was this model recommendation useful?'));
      for(const [rating,label] of [['useful','Useful & accurate'],
        ['incorrect','Incorrect advice'],['missing_context','Missing context']]){
        const b=element('button','button-mini'+(item.feedback===rating?' active':''),label);
        b.type='button';b.onclick=()=>this.setFeedback(rating);feedback.append(b);
      }
      const note=element('textarea','model-feedback-note');
      note.placeholder='What did the model miss? What would a better recommendation say?';
      note.rows=2;note.maxLength=1000;note.value=item.note;
      note.oninput=()=>this.updateNote(note.value);
      feedback.append(note);holder.append(feedback);
    }
  }
  const API=Object.freeze({validRequest,verifiedResponse,readinessLabel,
    ModelCoachingController});
  root.ReplayLabModelCoaching=API;
  if (typeof module!=='undefined' && module.exports)module.exports=API;
})(typeof globalThis!=='undefined'?globalThis:this);

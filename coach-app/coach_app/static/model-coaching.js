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
    return {
      mode:'model_proposal',
      grade:raw.assessment.grade,
      claims:modelClaims.map(c=>({
        claim_id:String(c.claim_id || ''),
        node_id:c.node_id,section:c.section,
        epistemic_type:c.epistemic_type,
        text:c.text.trim(),
        evidence_refs:[...c.evidence_refs]
      })),
      accepted:modelClaims.length,
      rejected:raw.validation.rejected_model_claims.length,
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
    }
    mount(){
      if(!$('modelCoachRunBtn'))return;
      $('modelCoachRunBtn').onclick=()=>this.generate();
      $('modelCoachRefreshBtn').onclick=()=>this.refreshReadiness();
      $('modelCoachConsent').onchange=()=>this.render();
      $('modelCoachExportBtn').onclick=()=>this.exportReport();
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
          'The server accepted '+outcome.accepted+' source-cited model statements. Strategic correctness remains unverified.' :
          'The provider responded, but no model suggestions passed the source checks. Do not treat this as a coaching verdict.';
      }
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
      btn.disabled=!request || !ready || !consent || this.loading;
      btn.textContent=this.loading?'Evaluating one decision…':'Generate AI coaching for this decision';
      $('modelCoachReadiness').textContent=readinessLabel(this.readiness);
      const name=episode?.title || 'No source-backed primary decision selected';
      $('modelCoachSelected').textContent=request ?
        name+' · decision '+request.primary_t0.toFixed(2)+'s' :
        'Load a real 2v2 replay, confirm the player and select the primary coaching node.';
      $('modelCoachStatus').textContent=this.status;
      const holder=$('modelCoachResults');
      holder.replaceChildren();
      const item=this.results.get(this.activeKey);
      if(!item){
        holder.append(element('p','small-copy',
          ready?'No AI analysis has been requested for this decision.':
          'The deterministic source-backed review remains available without any model.'));
        return;
      }
      const heading=element('div','model-result-heading');
      heading.append(element('strong','',
        'Model assessment: '+item.grade+' (hypothesis, NOT a validated grade)'));
      heading.append(element('small','',
        String(item.accepted)+' accepted citations · '+
        String(item.rejected)+' rejected claims · no expert quality validation'));
      holder.append(heading);
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

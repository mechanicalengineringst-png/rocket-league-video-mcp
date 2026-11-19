/* Local, explicitly requested experimental Claude CoachingReportV1 browser interface.
 * Does not call an AI provider. Stage A is displayed before a closed
 * retrospective drawer; neither outcome nor heuristic verdict is promoted
 * to verified expert truth. Blind reviewer Stage A masks this entire panel.
 */
(function(root){
  'use strict';
  const $=id=>root.document?.getElementById(id)||null;
  const el=(name,className,text)=>{
    const node=root.document.createElement(name);
    if(className)node.className=className;
    if(text!==undefined)node.textContent=String(text);
    return node;
  };
  const finite=n=>typeof n==='number'&&Number.isFinite(n);
  function validSelection(s){
    const r=s?.replay,players=r?.players,focus=s?.focusId;
    if(!r ||r.source==='synthetic'||!s.focusConfirmed||
       !Array.isArray(players)||players.length!==4||
       players.filter(p=>p.team==='blue').length!==2||
       players.filter(p=>p.team==='orange').length!==2||
       !players.some(p=>p.id===focus)||
       !Array.isArray(r.frames)||!r.frames.length||!finite(r.duration)){
      return null;
    }
    return {replay:r,focusId:focus};
  }
  const SAFE_CLASS=new Set(['first_defender','possession','offensive_first_man',
    'second_man_support','loose_ball','recovery_and_boost','aerial_or_wall']);
  function verifyResponse(res){
    if(!res ||res.schema!=='CoachingReportV1' ||
       res.experimental!==true||res.expert_validated!==false ||
       res.method?.model_called!==false||
       res.method?.ranking_uses_future!==false||
       res.method?.retrospective_included!==true ||
       !Array.isArray(res.findings)||res.findings.length>6)return null;
    const findings=res.findings.filter(f=>{
      const v=f?.validation;
      return f&&f.status==='ok'&&finite(f.t0)&&f.t0>=0&&
        SAFE_CLASS.has(f.situation?.situation_class)&&
        v?.claims_structurally_valid===true &&
        v?.future_frames_used===false &&
        v?.semantic_tactical_accuracy_verified===false &&
        Array.isArray(v?.untraced_numbers)&&v.untraced_numbers.length===0&&
        Array.isArray(v?.rejected_claims)&&v.rejected_claims.length===0&&
        typeof f.interpretation?.text==='string'&&
        typeof f.takeaway?.text==='string'&&
        Array.isArray(f.alternatives)&&Array.isArray(f.decision_context);
    });
    return {findings,withheld:res.findings.length-findings.length,
      coverage:res.coverage,patterns:res.patterns};
  }
  function valueLines(rows,limit=3){
    if(!Array.isArray(rows))return '';
    return rows.slice(0,limit).map(r=>typeof r==='string'?r:String(r?.text||'')).filter(Boolean).join(' · ');
  }

  class ExperimentalReportController {
    constructor(getSelection,fetcher,jump){
      this.getSelection=getSelection;
      this.fetcher=fetcher||((...a)=>root.fetch(...a));
      this.jump=jump||(()=>{});
      this.cache=new Map();
      this.replayIndex=new WeakMap();
      this.nextIndex=0;
      this.key=null;
      this.requestSeq=0;
      this.loading=false;
      this.status='The experimental report is not run automatically.';
    }
    context(){
      const sel=validSelection(this.getSelection?.());
      if(!sel)return null;
      let i=this.replayIndex.get(sel.replay);
      if(!i){i=++this.nextIndex;this.replayIndex.set(sel.replay,i);}
      return {...sel,key:i+'|'+sel.focusId};
    }
    isMasked(){return Boolean(root.blindReviewUI?.isPredecisionOpen?.());}
    mount(){
      if(!$('experimentalReportBtn'))return;
      $('experimentalReportBtn').onclick=()=>this.run();
      root.addEventListener?.('replay-lab:replay-ready',()=>this.selectionChanged());
      root.addEventListener?.('replay-lab:coaching-moment',()=>this.render());
      this.selectionChanged();
    }
    selectionChanged(){
      const ctx=this.context();
      if((ctx?.key||null)!==this.key){
        this.key=ctx?.key||null;
        this.requestSeq++;
        this.loading=false;
        this.status=ctx?
          'Ready: click once to run Claude’s rule-based experimental report locally.':
          'Load a real 2v2 replay and confirm who is being coached.';
      }
      this.render();
    }
    async run(){
      const ctx=this.context();
      if(!ctx||this.isMasked()||this.loading)return false;
      const seq=++this.requestSeq,key=ctx.key;
      this.loading=true;
      this.status='Analyzing this real replay locally; the experimental report may take time.';
      this.render();
      let found=null;
      try{
        // This path sends the decoded replay to the same localhost
        // application, never to a hosted model provider.
        const response=await this.fetcher('/api/coach/coaching-report-v1',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({replay:ctx.replay,player_id:ctx.focusId,
            max_findings:6,include_retrospective:true})
        });
        if(!response.ok)throw Error('local experimental API not available');
        found=verifyResponse(await response.json());
        if(!found)throw Error('untrusted or inconsistent experimental report');
      }catch(_){}
      if(seq!==this.requestSeq||key!==this.context()?.key)return false;
      this.loading=false;
      if(!found){
        this.status='Experimental report unavailable or rejected by its schema checks. Existing coaching is unaffected.';
        this.render();return false;
      }
      this.cache.set(key,found);
      this.status=found.findings.length+
        ' experimental source-checked findings · '+
        found.withheld+' withheld or invalid · no model called, no expert validation.';
      this.render();return true;
    }
    goTo(t0){
      if(this.isMasked()||!finite(t0))return;
      this.jump(t0);
    }
    render(){
      const run=$('experimentalReportBtn'),holder=$('experimentalReportResults');
      if(!run||!holder)return;
      const ctx=this.context(),masked=this.isMasked();
      run.disabled=!ctx||this.loading||masked;
      run.textContent=this.loading?'Building experimental report locally…':
        'Analyze this match locally (experimental)';
      const status=$('experimentalReportStatus');
      if(status)status.textContent=masked?
        'Blind evaluation Stage A is active. Lock your independent judgment before viewing experimental coaching.':this.status;
      holder.replaceChildren();
      if(masked){
        holder.append(el('p','small-copy',
          'Experimental findings are withheld until your independent judgment is locked.'));
        return;
      }
      const found=ctx?this.cache.get(ctx.key):null;
      if(!found)return;
      const n=el('p','small-copy',
        'Every finding below is an uncalibrated hypothesis. A structurally source-checked number does NOT prove a coaching verdict.');
      holder.append(n);
      for(const f of found.findings){
        const card=el('article','experimental-report-card');
        const header=el('div','experimental-report-head');
        header.append(el('strong','',
          String(f.finding_id||'Finding')+' · '+String(f.situation?.label||'Recorded situation')));
        const t=el('button','button-mini','Seek '+f.t0.toFixed(2)+'s');
        t.type='button';t.onclick=()=>this.goTo(f.t0);
        header.append(t);card.append(header);
        card.append(el('p','small-copy',
          'Unverified '+String(f.kind||'coaching')+' · '+
          String(f.situation?.situation_class||'unknown situation')));
        card.append(el('p','experimental-report-reading',f.interpretation.text));
        const facts=el('details','experimental-report-detail');
        facts.append(el('summary','','Observed decision-time conditions'));
        for(const item of f.decision_context.slice(0,8)){
          if(typeof item.reading==='string'){
            facts.append(el('p','small-copy',
              String(item.status||'unknown')+' · '+item.reading));
          }
        }
        card.append(facts);
        if(f.situation.situation_class==='aerial_or_wall'||
           f.kind==='observation_only'){
          card.append(el('p','small-copy',
            'Observation only: aerial and wall play are not judged by this engine.'));
        }else{
          for(const a of f.alternatives.slice(0,6)){
            const opt=el('div','experimental-report-option');
            opt.append(el('strong','',
              String(a.label||a.action||'Option')+' — '+String(a.status||'uncertain')));
            const positives=valueLines([...(a.gains||[]),...(a.preserves||[])]);
            if(positives)opt.append(el('p','small-copy','Possible gains / preserves: '+positives));
            const negatives=valueLines([...(a.sacrifices||[]),...(a.risks||[])]);
            if(negatives)opt.append(el('p','small-copy','Costs / risks: '+negatives));
            card.append(opt);
          }
        }
        if(f.assumptions?.decisive?.length){
          const note=el('details','experimental-report-detail');
          note.append(el('summary','','Decisive unknowns / assumptions'));
          for(const u of f.assumptions.decisive.slice(0,5))
            note.append(el('p','small-copy',String(u.question||u.condition||'Unknown')));
          card.append(note);
        }
        card.append(el('p','experimental-report-takeaway',
          'Practice hypothesis: '+f.takeaway.text));
        if(f.retrospective){
          const later=el('details','experimental-report-outcome');
          later.append(el('summary','','What you did & recorded outcome — open separately'));
          later.append(el('p','small-copy',
            'Movement-based observed action (not verified intent): '+
            String(f.retrospective.observed_action?.label||'unknown')));
          later.append(el('p','small-copy',
            'Experimental action assessment (not outcome-based): '+
            String(f.retrospective.assessment?.text||'Unknown')));
          later.append(el('p','small-copy',
            String(f.retrospective.outcome_independence||'Outcomes never establish decision quality.')));
          const outcome=f.retrospective.outcome;
          if(outcome){
            later.append(el('p','small-copy',
              'Observed postdecision contacts: '+
              (Array.isArray(outcome.touch_sequence)?outcome.touch_sequence.length:'unknown')+
              '. Goal observation: '+String(outcome.goal??'unknown')));
          }
          card.append(later);
        }
        holder.append(card);
      }
      if(found.withheld){
        holder.append(el('p','small-copy',found.withheld+
          ' findings were withheld because their evidence/validation did not pass the conservative UI gate.'));
      }
    }
  }
  const API=Object.freeze({validSelection,verifyResponse,ExperimentalReportController});
  root.ReplayLabExperimentalReport=API;
  if(typeof module!=='undefined'&&module.exports)module.exports=API;
})(typeof globalThis!=='undefined'?globalThis:this);

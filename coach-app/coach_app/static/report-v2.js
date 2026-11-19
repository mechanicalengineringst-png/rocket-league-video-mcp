/* Experimental Round 13 CoachingReportV2 browser journey.
 * Read-only LOCAL report, one explicit click, no LLM/network provider and
 * absolutely no claims of expert merit. V1 remains separately available.
 * Blind Stage A masks this report; later outcomes remain CLOSED by default.
 */
(function(root){
  'use strict';
  const $=id=>root.document?.getElementById(id)||null;
  const el=(tag,cls,text)=>{
    const n=root.document.createElement(tag);
    if(cls)n.className=cls;
    if(text!==undefined)n.textContent=String(text);
    return n;
  };
  const finite=n=>typeof n==='number'&&Number.isFinite(n);
  const safeTime=t=>finite(t)&&t>=0&&t<20000;
  const asText=(x,max=1200)=>String(x==null?'':x).slice(0,max);
  const fmt=t=>{
    if(!safeTime(t))return 'unknown';
    const mm=Math.floor(t/60),ss=(t%60).toFixed(1).padStart(4,'0');
    return mm+':'+ss;
  };
  function validSelection(s){
    const r=s?.replay,players=r?.players,id=s?.focusId;
    if(!r||r.source!=='native-replay'||s.focusConfirmed!==true||
       !Array.isArray(players)||players.length!==4||
       players.filter(p=>p.team==='blue').length!==2||
       players.filter(p=>p.team==='orange').length!==2||
       !players.some(p=>p.id===id)||!finite(r.duration)||
       !Array.isArray(r.frames)||r.frames.length===0)return null;
    return {replay:r,focusId:id};
  }
  const SAFE_CLASSES=new Set([
    'first_defender','possession','offensive_first_man',
    'second_man_support','loose_ball','recovery_and_boost','aerial_or_wall'
  ]);
  const SAFE_KINDS=new Set(['several_defensible','clear_read','observation_only',
    'disputed','unknown','supported','conditional']);
  const V2_VERDICTS=new Set(['consistent_with_rule_read','defensible_if',
    'against_rule_read_unconfirmed','unclear','not_assessed']);
  function checkFinding(f){
    const v=f?.validation,ret=f?.retrospective;
    return f?.status==='ok'&&safeTime(f.t0)&&
      SAFE_CLASSES.has(f.situation?.class)&&
      v?.claims_structurally_valid===true &&
      v?.future_frames_used===false &&
      v?.semantic_tactical_accuracy_verified===false &&
      Array.isArray(v.untraced_numbers)&&v.untraced_numbers.length===0 &&
      Array.isArray(v.rejected_claims)&&v.rejected_claims.length===0 &&
      typeof f.interpretation?.text==='string'&&
      f.interpretation.text.length<3500 &&
      Array.isArray(f.decision_context)&&f.decision_context.length<=40 &&
      Array.isArray(f.alternatives)&&f.alternatives.length<=10 &&
      (typeof f.takeaway?.text==='string'||f.takeaway?.text===null) &&
      ret?.assessment&&V2_VERDICTS.has(ret.assessment.verdict_v2)&&
      (ret.assessment.text_v2===undefined ||
        typeof ret.assessment.text_v2==='string') &&
      (f.ledger_adjustments===undefined||Array.isArray(f.ledger_adjustments));
  }
  const MODEL_MOVEMENT_READS=new Set([
    'supports','hurts','tradeoff','restraint','negligible'
  ]);
  // Round 14: describe EACH learned model head, never turn a single net
  // attribution or outcome into a judgment of the player's decision.
  function validHeadReading(h){
    if(!h||h.kind!=='model_association_not_cause'||
       !MODEL_MOVEMENT_READS.has(h.label)||
       !finite(h.next_touch_change)||!finite(h.danger_change)||
       Math.abs(h.next_touch_change)>1.01||Math.abs(h.danger_change)>1.01||
       !(h.moved_back_uu===null||
         (finite(h.moved_back_uu)&&Math.abs(h.moved_back_uu)<20000))||
       !(h.ended_goal_side===null||
         typeof h.ended_goal_side==='boolean'))return false;
    // Verify the whole two-head label against the numeric evidence. This
    // must mirror the conservative Round 14 backend classification, not
    // trust a text label that contradicts its own source quantities.
    const tu=h.next_touch_change>.02,td=h.next_touch_change<-.02;
    const gd=h.danger_change<-.02,gu=h.danger_change>.02;
    const expected=!(tu||td||gd||gu)?'negligible':
      td&&!gu&&h.moved_back_uu>500&&h.ended_goal_side===true?'restraint':
      (tu||gd)&&!(td||gu)?'supports':
      (td||gu)&&!(tu||gd)?'hurts':'tradeoff';
    return h.label===expected;
  }
  function movementReadout(point){
    const h=point?.your_movement_reading;
    if(!validHeadReading(h))return null;
    const meaning={
      supports:'Favorable model signals — increased touch access and/or reduced goal-area danger',
      hurts:'Unfavorable model signals — reduced touch access and/or increased goal-area danger',
      tradeoff:'Model tradeoff — an improvement in one signal came with a deterioration in the other',
      restraint:'Goal-side defensive restraint — gave up next-touch access without raising modeled danger',
      negligible:'Tiny model movement signal — not meaningful to interpret'
    }[h.label];
    const sign=n=>(n>0?'+':'')+n.toFixed(3);
    return {
      label:h.label,
      meaning,
      evidence:'Next-touch model signal '+sign(h.next_touch_change)+
        '; near-goal danger model signal '+sign(h.danger_change)+'.',
      caveat:'Association in a model fitted to unknown-rank matches, NOT cause, blame, or an expert tactical grade.'
    };
  }
  function checkPoint(p,duration){
    const link=p?.decision_time_reading;
    return p&&safeTime(p.t_start)&&safeTime(p.t_end)&&
      p.t_start<p.t_end&&p.t_end<=duration+2 &&
      (p.direction==='gain'||p.direction==='loss')&&
      (p.your_movement==='raised'||p.your_movement==='lowered')&&
      finite(p.team_control_change)&&finite(p.your_movement_effect)&&
      finite(p.your_share_of_attributed_change)&&
      p.your_share_of_attributed_change>=0&&p.your_share_of_attributed_change<=1 &&
      validHeadReading(p.your_movement_reading) &&
      typeof p.causal_status==='string'&&p.causal_status.startsWith('association') &&
      Array.isArray(p.touches)&&p.touches.length<=30 &&
      p.touches.every(t=>safeTime(t.t)&&['you','teammate','opponent'].includes(t.by)) &&
      (!link||(safeTime(link.t0)&&link.t0<=p.t_end &&
        typeof link.interpretation==='string'&&link.interpretation.length<3500 &&
        SAFE_CLASSES.has(link.class)));
  }
  function verifyResponse(rep,duration){
    if(!rep||rep.schema!=='CoachingReportV2' ||
       rep.version!=='coach-report-v2/0.1' ||
       rep.experimental!==true||rep.expert_validated!==false||
       rep.method?.model_called!==false||rep.method?.ledger!=='r13'||
       !Array.isArray(rep.matches)||rep.matches.length!==1||
       !Array.isArray(rep.evidence_status)||rep.evidence_status.length>16||
       !Array.isArray(rep.limits)||rep.limits.length>10)return null;
    const hp=rep.habit_profile,m=rep.matches[0];
    if(hp?.schema!=='HabitProfileV0'||hp.replays!==1||
       !Array.isArray(hp.habits)||hp.habits.length>16||
       !hp.habits.every(h=>
         typeof h.description==='string'&&h.description.length<220 &&
         (h.rate===null||(finite(h.rate)&&h.rate>=0&&h.rate<=1)) &&
         Number.isInteger(h.n)&&h.n>=0 &&
         (h.standout===null||['high','low'].includes(h.standout)) &&
         typeof h.reliable_with_these_matches==='boolean' &&
         (!h.standout||h.reliable_with_these_matches===true) &&
         Array.isArray(h.examples)&&h.examples.length<=4&&
         h.examples.every(safeTime))||
       m?.match_index!==0||!['blue','orange'].includes(m.team)||
       !Number.isInteger(m.situations_analysed)||m.situations_analysed<0||
       !Array.isArray(m.turning_points)||m.turning_points.length>8||
       !m.turning_points.every(p=>checkPoint(p,duration))||
       !Array.isArray(m.decision_findings)||m.decision_findings.length>12)return null;
    const findings=m.decision_findings.filter(checkFinding);
    return {
      habits:hp.habits,
      reference:asText(hp.reference?.note,500),
      turning:m.turning_points,
      findings,
      withheld:m.decision_findings.length-findings.length,
      situations:m.situations_analysed,
      evidence:rep.evidence_status.filter(e=>
        typeof e?.component==='string'&&typeof e?.status==='string'&&
        typeof e?.detail==='string').slice(0,12),
      limits:rep.limits.slice(0,8).filter(s=>typeof s==='string'),
    };
  }
  function statusLines(list,max){
    if(!Array.isArray(list))return '';
    return list.slice(0,max).map(x=>typeof x==='string'?asText(x,160):
      asText(x?.text||x?.reading||'',160)).filter(Boolean).join(' · ');
  }
  // A small falsifiability lens: these are only t0 conditions already
  // supplied by the locally validated Stage A finding. Never infer a new
  // counterfactual outcome, tactic, teammate intent, or confidence score.
  function decisionAudit(f){
    const assumptions=f?.assumptions;
    const decisive=(Array.isArray(assumptions?.decisive)?
      assumptions.decisive:[]).filter(d=>d&&typeof d==='object' &&
      typeof d.question==='string').slice(0,3);
    const unknown=(Array.isArray(assumptions?.unobservable)?
      assumptions.unobservable:[]).filter(d=>d&&typeof d==='object').slice(0,3);
    const context=(Array.isArray(f?.decision_context)?
      f.decision_context:[]).filter(d=>d&&typeof d==='object'&&
        typeof d.reading==='string').slice(0,10);
    return {decisive,unknown,context};
  }
  class ReportV2Controller{
    constructor(getSelection,fetcher,jump){
      this.getSelection=getSelection;
      this.fetcher=fetcher||((...a)=>root.fetch(...a));
      this.jump=jump||(()=>{});
      this.replayIds=new WeakMap();
      this.nextReplay=0;this.key=null;this.seq=0;
      this.loading=false;this.cache=new Map();
      this.status='Round 13 V2 has not been requested.';
    }
    context(){
      const s=validSelection(this.getSelection?.());
      if(!s)return null;
      let i=this.replayIds.get(s.replay);
      if(!i){i=++this.nextReplay;this.replayIds.set(s.replay,i);}
      return {...s,key:i+'|'+s.focusId};
    }
    isMasked(){return Boolean(root.blindReviewUI?.isPredecisionOpen?.());}
    mount(){
      if(!$('reportV2Btn'))return;
      $('reportV2Btn').onclick=()=>this.run();
      root.addEventListener?.('replay-lab:replay-ready',()=>this.selectionChanged());
      root.addEventListener?.('replay-lab:coaching-moment',()=>this.render());
      this.selectionChanged();
    }
    selectionChanged(){
      const ctx=this.context(),key=ctx?.key||null;
      if(key!==this.key){
        this.key=key;this.seq++;this.loading=false;
        this.status=ctx?
          'Ready. V2 uses local replay telemetry and a model trained on an unknown-rank public cohort.':
          'Select and confirm a real 2v2 player. Synthetic data is not accepted.';
      }
      this.render();
    }
    async run(){
      const ctx=this.context();
      if(!ctx||this.isMasked()||this.loading)return false;
      this.seq++;const seq=this.seq,key=ctx.key;
      this.loading=true;
      this.status='Building experimental V2 locally. This may take roughly a minute for a full replay; no model provider is contacted.';
      this.render();
      let payload=null;
      try{
        const response=await this.fetcher('/api/coach/coaching-report-v2',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({replay:ctx.replay,player_id:ctx.focusId,max_findings:6})
        });
        if(!response.ok)throw Error('V2 endpoint unavailable');
        payload=verifyResponse(await response.json(),ctx.replay.duration);
      }catch(_){}
      if(seq!==this.seq||key!==this.context()?.key)return false;
      this.loading=false;
      if(!payload){
        this.status='V2 report unavailable or rejected by safety/schema checks. V1 and standard coaching are unaffected.';
        this.render();return false;
      }
      this.cache.set(key,payload);
      this.status='V2: '+payload.habits.length+' descriptive habits; '+
        payload.turning.length+' turning points; '+payload.findings.length+
        ' source-checked decisions ('+payload.withheld+' withheld). No AI provider; no expert verdict.';
      this.render();return true;
    }
    goTo(t){
      if(this.isMasked()||!safeTime(t))return;
      this.jump(t);
    }
    seek(t,label){
      const b=el('button','button-mini',label+' '+fmt(t));
      b.type='button';b.onclick=()=>this.goTo(t);
      return b;
    }
    render(){
      const btn=$('reportV2Btn'),holder=$('reportV2Results');
      if(!btn||!holder)return;
      const ctx=this.context(),masked=this.isMasked();
      btn.disabled=!ctx||masked||this.loading;
      btn.textContent=this.loading?'Building V2 report locally…':'Analyze this match with V2 (experimental)';
      if($('reportV2Status'))$('reportV2Status').textContent=masked?
        'Blind Stage A is active; all V2 future-selected moments and interpretations are hidden.':this.status;
      holder.replaceChildren();
      if(masked){
        holder.append(el('p','small-copy',
          'V2 report is withheld until you lock your independent predecision judgment.'));
        return;
      }
      const rep=ctx?this.cache.get(ctx.key):null;
      if(!rep)return;
      holder.append(el('p','small-copy',
        'Local statistical hypotheses, not Grand Champion coaching verdicts. One replay is insufficient for reliable habit labels; the trained reference matches have unknown rank.'));
      const habits=el('section','experimental-report-section');
      habits.append(el('h4','','1. Measured habits — one match, do not label a tendency'));
      habits.append(el('p','small-copy',rep.reference));
      for(const h of rep.habits){
        const row=el('article','experimental-report-option');
        const rate=h.rate===null?'insufficient samples':(h.rate*100).toFixed(0)+'%';
        row.append(el('strong','',asText(h.description,200)));
        row.append(el('p','small-copy',
          rate+' of '+h.n+' measured opportunities · '+asText(h.status,180)));
        if(h.standout&&h.reliable_with_these_matches)
          row.append(el('p','small-copy','Unusual vs unknown-rank reference: '+h.standout+
            ' (NOT a quality assessment).'));
        for(const t of h.examples.slice(0,3))row.append(this.seek(t,'Example'));
        habits.append(row);
      }
      holder.append(habits);
      const points=el('section','experimental-report-section');
      points.append(el('h4','','2. Turning points — RETROSPECTIVE selection, not mistake labels'));
      points.append(el('p','small-copy',
        'These windows were selected using later events. The movement effect changes a statistical control score; it does not measure intent or prove blame. Each linked interpretation uses only its own earlier decision-time evidence.'));
      if(!rep.turning.length)
        points.append(el('p','small-copy','No supported turning points for this replay.'));
      for(const p of rep.turning){
        const card=el('article','experimental-report-card');
        const header=el('div','experimental-report-head');
        header.append(el('strong','',
          'Team control '+p.direction+' · '+fmt(p.t_start)+'–'+fmt(p.t_end)));
        header.append(this.seek(p.t_start,'Seek'));
        card.append(header);
        const head=movementReadout(p);
        card.append(el('strong','',head.meaning));
        card.append(el('p','small-copy',head.evidence));
        card.append(el('p','small-copy',
          Math.round(p.your_share_of_attributed_change*100)+
          '% of the sum of absolute player-attributed changes in this model. '+
          'This is NOT a percentage of responsibility or evidence of cause.'));
        card.append(el('p','small-copy',head.caveat));
        if(p.touches.length)
          card.append(el('p','small-copy','Recorded touches in this later window: '+
            p.touches.map(t=>t.by+' '+fmt(t.t)).slice(0,9).join(', ')));
        const reading=p.decision_time_reading;
        if(reading){
          const d=el('div','experimental-report-detail');
          d.append(this.seek(reading.t0,'Earlier decision'));
          d.append(el('p','small-copy',
            'Decision-time interpretation ('+reading.class.replaceAll('_',' ')+'): '+
            asText(reading.interpretation,2000)));
          if(typeof reading.takeaway==='string')
            d.append(el('p','small-copy','Question to investigate: '+asText(reading.takeaway,800)));
          card.append(d);
        }else{
          card.append(el('p','small-copy','No defensible source-linked earlier decision was available.'));
        }
        points.append(card);
      }
      holder.append(points);
      const decisions=el('section','experimental-report-section');
      decisions.append(el('h4','','3. Individual decisions — source-backed, no mistake verdicts'));
      for(const f of rep.findings){
        const card=el('article','experimental-report-card');
        const head=el('div','experimental-report-head');
        head.append(el('strong','',
          asText(f.finding_id||'Finding',50)+' · '+
          asText(f.situation?.label||'Decision-time situation',130)));
        head.append(this.seek(f.t0,'Seek'));
        card.append(head);
        card.append(el('p','small-copy','At decision time: '+asText(f.interpretation.text,2400)));
        if(f.takeaway?.text)card.append(el('p','experimental-report-takeaway',
          'Recognition cue: '+asText(f.takeaway.text,1600)));
        for(const a of f.alternatives.slice(0,6)){
          const choice=el('div','experimental-report-option');
          choice.append(el('strong','',
            asText(a.label||a.action||'Alternative',110)+' · '+asText(a.status||'uncertain',60)));
          const gains=statusLines([...(a.gains||[]),...(a.preserves||[])],4);
          if(gains)choice.append(el('p','small-copy','Possible gains: '+gains));
          const risks=statusLines([...(a.risks||[]),...(a.sacrifices||[])],4);
          if(risks)choice.append(el('p','small-copy','Tradeoffs: '+risks));
          card.append(choice);
        }
        // More than a list of preferred actions: give the owner an explicit
        // way to try to falsify the read using what the replay actually knew
        // BEFORE t0. Closed by default to keep the 3D replay uncluttered.
        const audit=decisionAudit(f);
        const review=el('details','experimental-report-detail');
        review.append(el('summary','','Challenge this reading — decision-time evidence & unknowns'));
        review.append(el('p','small-copy',
          'The statements below are historical observations or rule assumptions, not proof that any alternative would have scored or saved a goal.'));
        const relevant=audit.context.filter(x=>
          ['unknown','within_error','unobservable','uncertain'].includes(x.status));
        if(relevant.length){
          review.append(el('strong','','Uncertain or unavailable at decision time'));
          for(const item of relevant.slice(0,5)){
            review.append(el('p','small-copy',
              asText(item.status,35).replaceAll('_',' ')+' · '+
              asText(item.reading,330)));
          }
        }
        if(audit.decisive.length){
          review.append(el('strong','','What could change the choice'));
          for(const d of audit.decisive){
            review.append(el('p','small-copy',
              asText(d.question,350)+' · currently '+
              asText(d.current||'not established',60).replaceAll('_',' ') +
              (typeof d.how_to_resolve==='string'?
                ' · Check: '+asText(d.how_to_resolve,250):'')));
          }
        }else{
          review.append(el('p','small-copy',
            'The engine identified no decisive unresolved condition here. That does not establish a unique best play.'));
        }
        if(audit.unknown.length){
          review.append(el('strong','','What this replay cannot observe'));
          for(const d of audit.unknown){
            review.append(el('p','small-copy',
              asText(d.text||d.condition||'Unrecorded intent or mechanics',330)));
          }
        }
        if(audit.context.length){
          const measured=el('details','experimental-report-detail');
          measured.append(el('summary','','Show the recorded decision-time premises'));
          for(const item of audit.context.slice(0,8)){
            measured.append(el('p','small-copy',
              asText(item.status||'not assessed',32).replaceAll('_',' ')+' · '+
              asText(item.reading,350)));
          }
          review.append(measured);
        }
        card.append(review);
        if(f.kind==='observation_only'||f.situation?.class==='aerial_or_wall')
          card.append(el('p','small-copy',
            'Aerial/wall mechanics are not modelled; only positional context is supplied.'));
        const r=f.retrospective;
        if(r){
          const detail=el('details','experimental-report-outcome');
          detail.append(el('summary','','Stage B: recorded action and later outcome — reveal separately'));
          detail.append(el('p','small-copy','Observed movement label: '+
            asText(r.observed_action?.label||'unknown',150)));
          detail.append(el('p','small-copy',
            'Unverified decision-time rule comparison: '+
            asText(r.assessment?.verdict_v2||'not_assessed',120).replaceAll('_',' ')));
          // Never show the old R12 mistake verdict or text: only the
          // deliberately revised V2 language, when supplied.
          if(typeof r.assessment?.text_v2==='string')
            detail.append(el('p','small-copy',asText(r.assessment.text_v2,1600)));
          detail.append(el('p','small-copy',
            'This retrospective is context, not an assessment based on the outcome.'));
          card.append(detail);
        }
        decisions.append(card);
      }
      if(!rep.findings.length)
        decisions.append(el('p','small-copy',
          'No decision claims survived the conservative source-validation gate. No verdict was invented.'));
      if(rep.withheld)decisions.append(el('p','small-copy',
        rep.withheld+' decision findings withheld because source checks were incomplete.'));
      holder.append(decisions);
      const evidence=el('details','experimental-report-detail');
      evidence.append(el('summary','','Methods, evidence status and limitations'));
      evidence.append(el('p','small-copy',
        String(rep.situations)+' situations evaluated locally; selected turning points are retrospective.'));
      for(const row of rep.evidence)
        evidence.append(el('p','small-copy',
          asText(row.component,110)+': '+asText(row.status,130)+'. '+asText(row.detail,500)));
      for(const line of rep.limits)
        evidence.append(el('p','small-copy',asText(line,600)));
      holder.append(evidence);
    }
  }
  root.ReplayLabReportV2=Object.freeze({
    validSelection,verifyResponse,decisionAudit,movementReadout,ReportV2Controller
  });
  if(typeof module!=='undefined'&&module.exports)module.exports=root.ReplayLabReportV2;
})(typeof globalThis!=='undefined'?globalThis:this);

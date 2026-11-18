/* Replay Lab: Review a Moment the Auto-Coach Missed (ManualReviewV0).
 *
 * Construct a *manual*, source-constrained 5-20-second EpisodeEvidenceV0
 * request around a user-pinned replay timestamp. Anchors are actual recorded
 * frames, never invented actions, touches, or tactical conclusions.
 *
 * One deterministic localhost lesson request happens ONLY after a click.
 * The model coaching UI is separate and remains explicitly opt-in.
 * No automatic model calls, raw replay upload outside localhost, or
 * simulated future action comparisons.
 */
(function(root) {
  'use strict';
  const MAX_AGE_S=0.20;
  const round3=n=>Math.round(n*1000)/1000;
  const finite=Number.isFinite;
  const $=id=>root.document?.getElementById(id);
  function frameAtOrBefore(frames,t) {
    if(!Array.isArray(frames)||!frames.length||!finite(t))return null;
    let lo=0,hi=frames.length;
    while(lo<hi) {
      const mid=(lo+hi)>>1;
      if(finite(frames[mid]?.t) && frames[mid].t<=t)lo=mid+1;
      else hi=mid;
    }
    return lo>0?frames[lo-1]:null;
  }
  function freshFrame(frames,t) {
    const frame=frameAtOrBefore(frames,t);
    return frame && t-frame.t>=-0.0000001 && t-frame.t<=MAX_AGE_S ?
      frame : null;
  }
  function validPosition(p) {
    return p && [p.x,p.y,p.z].every(finite) && p.demolished!==true;
  }
  function validRoster(replay,playerId) {
    const players=replay?.players;
    if(!Array.isArray(players)||players.length!==4||
      !players.every(p=>p && typeof p.id==='string' && p.id.length>0 &&
        ['blue','orange'].includes(p.team)) ||
      new Set(players.map(p=>p.id)).size!==4 ||
      players.filter(p=>p.team==='blue').length!==2 ||
      players.filter(p=>p.team==='orange').length!==2 ||
      !players.some(p=>p.id===playerId))return false;
    return true;
  }
  function buildManualRequest(replay,playerId,pinnedT0) {
    if(!replay || replay.source==='synthetic' ||
      !validRoster(replay,playerId) || !finite(pinnedT0))return null;
    const frames=replay.frames;
    if(!Array.isArray(frames)||frames.length<10||frames.length>30000)return null;
    const first=frames[0]?.t, last=frames[frames.length-1]?.t;
    if(!finite(first)||!finite(last)||last-first<5 || pinnedT0<first ||
      pinnedT0>last+0.000001)return null;
    const primaryFrame=freshFrame(frames,pinnedT0);
    if(!primaryFrame || !validPosition(primaryFrame.ball) ||
      !validPosition(primaryFrame.cars?.[playerId]))return null;
    // Snapshot times may contain >3 decimal digits; the backend normalizes
    // EpisodeEvidenceV0 timestamps to milliseconds. Canonical rounded t0
    // is the decision cutoff, not the user's unsnapped playback cursor.
    const t0=round3(primaryFrame.t);
    if(t0<first+5.0-0.000001 || t0>last+0.001)return null;
    const start=round3(Math.max(first,t0-7));
    if(t0-start<5 || t0-start>20)return null;
    // Neutral earlier context samples. These are NOT independently proven
    // earlier player choices. Both are selected entirely before t0.
    const span=t0-start;
    const targets=[start+span*0.38,start+span*0.72];
    const earlier=[];
    for(const target of targets) {
      const frame=freshFrame(frames,target);
      if(!frame || !validPosition(frame.ball) ||
        !validPosition(frame.cars?.[playerId]))return null;
      const t=round3(frame.t);
      if(t<=start || t>=t0 || (earlier.length && t<=earlier[0]+0.25))
        return null;
      earlier.push(t);
    }
    if(t0-earlier[1]<0.25 || earlier[0]<start)return null;
    return {
      replay, player_id:playerId,
      decision_times:[earlier[0],earlier[1],t0],
      episode_start_s:start,primary_t0:t0,
      mode:'deterministic',experimental_tactical_v1:false
    };
  }
  function validLesson(lesson,request) {
    return !!lesson && lesson.schema==='CoachLessonV0' &&
      lesson.stage==='predecision' && lesson.mode==='deterministic_baseline' &&
      finite(lesson.decision?.t0_s) &&
      Math.abs(lesson.decision.t0_s-request.primary_t0)<0.001 &&
      Math.abs(lesson.decision.episode_start_s-request.episode_start_s)<0.001 &&
      lesson.decision.node_id==='N3' &&
      lesson.validation?.future_outcomes_used===false &&
      lesson.validation?.semantic_tactical_accuracy_verified===false &&
      lesson.validation?.accepted_model_claims===0 &&
      Array.isArray(lesson.claims) &&
      lesson.claims.every(c=>c && c.author==='deterministic');
  }
  class ManualReviewController {
    constructor(getContext,acceptLesson,fetcher) {
      this.getContext=getContext;
      this.acceptLesson=acceptLesson;
      this.fetcher=fetcher || ((...args)=>root.fetch(...args));
      this.generation=0;this.loading=false;this.abort=null;
      this.status='Pin a moment to review a possible missed coaching opportunity.';
    }
    mount(){
      const button=$('lensManualReviewBtn');
      if(!button)return;
      button.onclick=()=>this.reviewPinned();
      this.render();
    }
    context(){
      const data=this.getContext?.();
      if(!data || !data.focusConfirmed ||
        !data.pinned || !data.replay ||
        data.pinned.source!=='manual')return null;
      const request=buildManualRequest(
        data.replay,data.focusId,data.pinned.window?.t0);
      return request?{...data,request}:null;
    }
    invalidate(reason='Select a manual pin to review.') {
      this.generation++;
      this.abort?.abort();
      this.abort=null;this.loading=false;
      this.status=reason;
      this.render();
    }
    render(){
      const btn=$('lensManualReviewBtn'),status=$('lensManualReviewStatus');
      if(btn) {
        btn.disabled=this.loading||!this.context();
        btn.textContent=this.loading?'Building source-backed review…':
          'Review this overlooked moment (local)';
      }
      if(status)status.textContent=this.status;
    }
    async reviewPinned() {
      const ctx=this.context();
      if(this.loading || !ctx) {
        this.status='Select a real replay, confirm your player and manually pin a moment with 5–7 seconds of recorded history.';
        this.render();return false;
      }
      const id=++this.generation;
      const {replay,focusId,request}=ctx;
      const pinTime=ctx.pinned.window.t0;
      this.loading=true;this.abort?.abort();
      const controller=new AbortController();this.abort=controller;
      this.status='Checking recorded predecision context locally; no AI provider called.';
      this.render();
      let lesson=null,error=null;
      try {
        const response=await this.fetcher('/api/coach/lesson',{
          method:'POST',headers:{'Content-Type':'application/json'},
          signal:controller.signal,body:JSON.stringify(request)
        });
        if(!response.ok)throw Error('HTTP '+response.status);
        const result=await response.json();
        if(!validLesson(result,request))throw Error('Contract mismatch');
        lesson=result;
      }catch(_) {
        error='This moment could not be safely reconstructed from local replay evidence. No coaching verdict was invented.';
      }
      const latest=this.getContext?.();
      if(this.generation!==id ||
        latest?.replay!==replay || latest?.focusId!==focusId ||
        latest?.pinned?.window?.t0!==pinTime ||
        latest?.pinned?.source!=='manual' || !latest?.focusConfirmed)return false;
      this.loading=false;this.abort=null;
      if(error){this.status=error;this.render();return false;}
      // Only now is a manual observation added as a selectable source-backed
      // episode. The existing AI UI can analyze it AFTER another explicit
      // user consent and model click; no paid request occurs here.
      this.acceptLesson(lesson,request,{
        selection_source:'manual',
        title:'You selected this moment · '+request.primary_t0.toFixed(2)+'s',
        t0:request.primary_t0
      });
      this.status='Manual source-backed episode created. Review its context below, or separately opt in to AI coaching. This selection is not a confirmed mistake.';
      this.render();return true;
    }
  }
  const API=Object.freeze({
    buildManualRequest,frameAtOrBefore,freshFrame,validLesson,
    ManualReviewController,MAX_AGE_S
  });
  root.ReplayLabManualReview=API;
  if(typeof module!=='undefined' && module.exports)module.exports=API;
})(typeof globalThis!=='undefined'?globalThis:this);

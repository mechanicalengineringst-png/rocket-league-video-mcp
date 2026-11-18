'use strict';
const $ = id => document.getElementById(id);
const state = { replay: null, findings: [], focusId: null, selectedId: null, time: 0, playing: false, timer: null, overrides: new Map(), reviewFeedback: new Map(), view: {facing:true, travel:false, heights:false, trail:false, ballTrail:false, boostPads:true}, speed:1, momentFilter:'shortlist', videoUrl:null, videoOffset:0, videoAligned:false };
let viewer3d = null;
let currentViewMode = '2d';
function getViewer3d(){
  if(!viewer3d && typeof Viewer3D !== 'undefined'){
    const container = $('viewport3d');
    if(container) viewer3d = new Viewer3D(container);
  }
  return viewer3d;
}
const SVG_NS = 'http://www.w3.org/2000/svg';
// Rocket League uses Unreal's left-handed axes: seen from above with the orange goal (+Y)
// at the top, +X is on the LEFT. Drawing +X to the right mirrors the whole field.
const sx = x => 58 + ((4096 - Number(x)) / 8192) * 644;
const sy = y => 50 + ((5120 - Number(y)) / 10240) * 870;
const invx = x => 4096 - (x - 58) / 644 * 8192;
const invy = y => 5120 - (y - 50) / 870 * 10240;
const fmt = t => `${Math.floor(Math.max(0,t)/60).toString().padStart(2,'0')}:${Math.floor(Math.max(0,t)%60).toString().padStart(2,'0')}`;
const playerById = id => state.replay?.players.find(p => p.id === id);
const startTime = () => state.replay?.frames[0]?.t ?? 0;
const remembered = { get(){try{return localStorage.getItem('rl-coach:lastPlayerId');}catch(_){return null;}}, set(id){try{localStorage.setItem('rl-coach:lastPlayerId',id);}catch(_){}} };
const nearestIndex = time => { const fs=state.replay?.frames||[]; if(!fs.length)return -1; let lo=0, hi=fs.length-1; while(lo<hi){let mid=(lo+hi)>>1;if(fs[mid].t<time)lo=mid+1;else hi=mid;}return lo>0&&Math.abs(fs[lo-1].t-time)<Math.abs(fs[lo].t-time)?lo-1:lo; };
const currentFrame = () => state.replay ? (globalThis.ReplayLabViewMath?.sampleReplayState(state.replay.frames, state.time) || state.replay.frames[nearestIndex(state.time)]) : null;
const show = (message) => { $('toast').textContent=message; $('toast').classList.add('show'); clearTimeout(show.timer); show.timer=setTimeout(()=>$('toast').classList.remove('show'),3600); };
function el(tag, attrs={}, text) { const n=document.createElementNS(SVG_NS,tag); for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v)); if(text!==undefined)n.textContent=text; return n; }
function chooseTime(time){
  if(!state.replay)return;
  state.time=Math.max(startTime(),Math.min(time,state.replay.duration));
  $('timeRange').value=state.time;
  $('timeValue').textContent=fmt(state.time)+'.'+String(Math.floor((state.time%1)*100)).padStart(2,'0');
  const frame=currentFrame();
  const fc=frame?.cars?.[state.focusId];
  $('boostValue').textContent='BOOST '+(fc&&!fc.demolished&&Number.isFinite(fc.boost)?Math.round(fc.boost):'—');
  renderPitch();
  renderSceneInspector();
  if(state.replay.boostPadTimeline) renderBoostPads();
  if(viewer3d) {
    viewer3d.update(frame, state.focusId, state.replay.players);
    if(state.replay.boostPadTimeline) {
      viewer3d.updateBoostPads(state.replay.boostPadTimeline, state.time);
    }
  }
  syncVideoToReplay();
}
function setReplay(replay, opts={}){
  if(!replay || !Array.isArray(replay.players) || !Array.isArray(replay.frames) || !replay.frames.length)throw new Error('Invalid replay timeline.');
  stopPlay();removeVideo();state.replay=replay;state.findings=[];
  const boostPadModel = typeof ReplayLabBoostPadState !== 'undefined'
    ? ReplayLabBoostPadState.compile(replay.boostPadTimeline) : null;
  const padStatus=$('boostPadDataStatus');
  if(padStatus && typeof ReplayLabBoostPadState !== 'undefined')
    padStatus.textContent=ReplayLabBoostPadState.describe(boostPadModel);
  if($('recentActionsList'))$('recentActionsList').dataset.signature='';
  // Preference: the replay's recording player, then the player chosen last time, then a
  // player on the recording team. Anything weaker is a guess and is labelled as one.
  const has=id=>replay.players.some(p=>p.id===id), last=remembered.get();
  state.focusConfirmed=has(replay.primaryPlayerId)||has(last);
  state.focusId=has(replay.primaryPlayerId)?replay.primaryPlayerId:has(last)?last:(replay.players.find(p=>p.team===replay.primaryTeam)?.id||replay.players[0].id);
  state.selectedId=null;state.overrides.clear();state.reviewFeedback.clear();state.time=0;
  $('replayTitle').textContent=replay.title; $('modeValue').textContent=replay.mode; $('durationValue').textContent=fmt(replay.duration-startTime());
  $('playerSelect').replaceChildren(...replay.players.map(p=>{const o=document.createElement('option');o.value=p.id;o.textContent=`${p.name} — ${p.team.toUpperCase()}`;return o;}));
  $('playerSelect').value=state.focusId;
  for(const id of ['playerSelect','timeRange','playBtn','backBtn','forwardBtn','markBtn','exportBtn','aiBtn'])$(id).disabled=false;
  $('timeRange').min=startTime();$('timeRange').max=replay.duration;$('startTimeLabel').textContent=fmt(startTime());$('endTime').textContent=fmt(replay.duration);
  $('uploadStatus').textContent=opts.demo?'Simulated example loaded. This is NOT an actual match.':(replay.playerMappingVerified===false?'Replay decoded, but player identities could not be verified from kickoff spawns.':('Decoded '+(replay.telemetrySampleCount||replay.frames.length)+' physics samples; '+(replay.eventCounts?.touch||0)+' touches, '+(replay.eventCounts?.goal_context||0)+' goals. Events are review observations, not proven mistakes.'));
  if(!opts.demo&&!state.focusConfirmed)$('uploadStatus').textContent+=' The recording player could not be identified: confirm "Who are we coaching?".';
  // Demo fixtures are never attached to a user's real match.
  window.coachingController?.resetForReplay(Boolean(opts.demo));
  refreshFindings(opts.demo);renderBoostPads();
  const v = getViewer3d();
  if(v) v.update(currentFrame(), state.focusId, state.replay.players);
  chooseTime(0);
  if(!opts.demo && replay.source !== 'synthetic') {
    loadDecisionCasesForCoaching(replay, state.focusId);
  }
}
function makeCoachLessonRequest(replay, playerId, decisionCase) {
  // Source cases choose the primary moment; context nodes are explicitly selected
  // nearby timestamps, not automatically inferred prior mistakes.
  const t0 = Number(decisionCase.t0 ?? decisionCase.timestamp);
  const first = Number(replay.frames?.[0]?.t ?? 0);
  if (!Number.isFinite(t0) || t0 - first < 5.05 || t0 > replay.duration) return null;
  const episodeStart = +(t0 - 5).toFixed(3);
  const decisionTimes = [t0 - 3.2, t0 - 1.5, t0].map(t => +t.toFixed(3));
  if (decisionTimes.some(t => t < episodeStart || !Number.isFinite(t))) return null;
  return {
    replay, player_id: playerId, decision_times: decisionTimes,
    episode_start_s: episodeStart, primary_t0: +t0.toFixed(3),
    mode: 'deterministic'
  };
}

async function loadDecisionCasesForCoaching(replay, playerId) {
  if (!replay || !replay.frames || replay.source === 'synthetic') return;
  const coach = window.coachingController;
  if (!state.focusConfirmed) {
    coach?.setLiveStatus('Confirm the player being coached to request source-backed analysis.');
    return;
  }
  coach?.setLiveStatus('Inspecting candidate decisions with the local coaching backend...');
  try {
    const res = await fetch('/api/decision-cases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({replay, player_id: playerId, evaluate: true, analyze: true})
    });
    if (!res.ok) throw new Error('Candidate decision extraction unavailable (' + res.status + ').');
    const data = await res.json();
    let count = 0;
    for (const c of (data.cases || []).slice(0, 5)) {
      if (state.replay !== replay || state.focusId !== playerId) return;
      const payload = makeCoachLessonRequest(replay, playerId, c);
      if (!payload) continue;
      try {
        const lessonRes = await fetch('/api/coach/lesson', {
          method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify(payload)
        });
        if (!lessonRes.ok) continue;
        const lesson = await lessonRes.json();
        if (state.replay !== replay || state.focusId !== playerId) return;
        if (lesson.schema !== 'CoachLessonV0' || lesson.stage !== 'predecision') continue;
        coach?.addVerifiedLesson(lesson, payload, c);
        count += 1;
      } catch (err) {
        console.warn('An individual coaching lesson could not be loaded:', err);
      }
    }
    if (!count && state.replay === replay && state.focusId === playerId)
      coach?.setLiveStatus('No source-backed lessons could be constructed for this replay. Demo examples remain separate.');
  } catch (err) {
    console.warn('Could not load live coaching cases:', err);
    if (state.replay === replay && state.focusId === playerId)
      coach?.setLiveStatus('Source-backed coaching is unavailable: ' + err.message);
  }
}

function supportPoint(frame, focusId){let car=frame.cars[focusId];const team=playerById(focusId)?.team||'blue';const ownY=team==='blue'?-5120:5120;return {x:Math.max(-3500,Math.min(3500,frame.ball.x+(car.x<frame.ball.x?-500:500))),y:Math.max(-4400,Math.min(4400,frame.ball.y+(ownY>frame.ball.y?1100:-1100)))};}
function demoReplay(){const players=[{id:'self',name:'Your car',team:'blue'},{id:'mate',name:'Teammate',team:'blue'},{id:'opp1',name:'Opponent 1',team:'orange'},{id:'opp2',name:'Opponent 2',team:'orange'}];let frames=[];for(let i=0;i<=240;i++){
const t=i*.5, wave=Math.sin(t/13), bx=1200* Math.sin(t/16),by=3600*Math.sin(t/26),b={x:bx,y:by,z:110};
const defensive=t>65 && t<95;const overlap=t>29 && t<42;
const self={x:overlap?bx+120:1200*Math.sin(t/19)-450,y:overlap?by-250:defensive?-3630:1400*Math.sin(t/17)-900,z:17,boost:defensive?7:Math.round(45+25*Math.sin(t/10))};
const mate={x:overlap?bx-180:900*Math.cos(t/14)+700,y:overlap?by-200:1000*Math.cos(t/16)-750,z:17,boost:55};
const opp1={x:bx+1000,y:Math.min(4300,by+800),z:17,boost:68};const opp2={x:-1900,y:3500,z:17,boost:77};
frames.push({t,ball:b,cars:{self,mate,opp1,opp2}});
}return {schema:'rl-coach/0.1',title:'Simulated 2v2 match — interactive demo',mode:'2v2',duration:120,players,frames,source:'synthetic',samplingSeconds:.5};}
function refreshFindings(demo=false){if(!state.replay)return;
  // Manual markers are not about one player; AI findings belong to the player they were asked about.
  const findings=state.findings.filter(f=>f.type==='manual'||(f.type==='ai'&&f.focusId===state.focusId));
  // Server-side telemetry checks are small, focus-specific and independently
  // reproducible. They are questions to review, not proven mistakes.
  const contextual=state.replay.contextualReviews?.[state.focusId]||[];
  if(Array.isArray(contextual))findings.push(...contextual.filter(f=>f.type==='contextual'));
  const fs=state.replay.frames;const team=playerById(state.focusId)?.team;
  let seen={};for(const f of fs){const car=f.cars[state.focusId];if(!car||car.demolished)continue;const mate=state.replay.players.filter(p=>p.team===team&&p.id!==state.focusId).map(p=>f.cars[p.id]).find(c=>c&&!c.demolished);const dist=(p,q)=>Math.hypot(p.x-q.x,p.y-q.y);
    if(mate&&dist(car,f.ball)<900&&dist(mate,f.ball)<900&&dist(car,mate)<1300&&f.t-(seen.overlap??-100)>18){findings.push({id:'overlap'+f.t,t:f.t,title:'Two teammates near the ball',type:'overlap',confidence:'low',evidence:'Both teammates are within 900 units of the ball and 1300 units of each other.',advice:'Check who had priority for the next touch. Proximity alone does not prove a double commit.',target:null});seen.overlap=f.t;}
    let ownY=team==='blue'?-5120:5120;
    if(car.boost!==null&&car.boost!==undefined&&car.boost<=12&&Math.abs(car.y-ownY)<2700&&Math.abs(f.ball.y-ownY)<3500&&f.t-(seen.boost??-100)>30){findings.push({id:'boost'+f.t,t:f.t,title:'Low boost near own goal',type:'boost',confidence:'low',evidence:`Your car has approximately ${Math.round(car.boost)} boost near your goal.`,advice:'Check whether a small-pad route could have preserved boost and goal-side coverage. This may be unavoidable.',target:null});seen.boost=f.t;}
  }
  // Observed native events. Never label an outcome as a verified mistake.
  if(!demo && Array.isArray(state.replay.events)){
    for(let i=0;i<state.replay.events.length;i++){
      const e=state.replay.events[i];
      if(e.type!=='goal_context' && e.type!=='fifty_fifty')continue;
      const isGoal=e.type==='goal_context';
      const scorer=playerById(e.scorerId);
      const result=e.winningTeam||'undetermined';
      findings.push({
        id:'event-'+i+'-'+e.type,t:e.t,type:'event',
        eventType:e.type,confidence:'observed',
        title:isGoal?('Goal: '+(scorer?.name||e.scoringTeam||'unknown scorer')):('50/50: '+result+' outcome'),
        evidence:isGoal?('A goal was recorded for '+(e.scoringTeam||'an unknown team')+'.'):('The parser classified a 50/50, with a '+result+' result.'),
        advice:isGoal?'Examine the preceding two seconds: each car height, ball movement, last touch and defensive recovery.':'Compare both approaches, jump heights and the subsequent ball path. A lost 50/50 can still be the correct decision.',
        uncertainty:'An observed event is not a verified coaching mistake.',target:null
      });
    }
  }
  findings.sort((a,b)=>a.t-b.t);
  state.findings=findings;
  const shortlist=visibleFindings();
  if(!shortlist.some(f=>f.id===state.selectedId))state.selectedId=shortlist[0]?.id||null;
  // All native events are retained for navigation, not counted as coaching leads.
  $('flagsValue').textContent=findings.filter(f=>['manual','ai','contextual'].includes(f.type)).length;
  renderFindings();renderDetail();
}
function visibleFindings(){
  const filter=state.momentFilter;
  return state.findings.filter(f=>{
    if(filter==='shortlist')return f.type==='manual'||f.type==='ai'||f.type==='contextual';
    if(filter==='goals')return f.eventType==='goal_context';
    if(filter==='challenges')return f.eventType==='fifty_fifty';
    if(filter==='flags')return f.type==='boost'||f.type==='overlap';
    if(filter==='manual')return f.type==='manual'||f.type==='ai';
    return true;
  });
}
function renderFindings(){
  const list=$('findingsList'), items=visibleFindings();
  list.replaceChildren();
  $('issueCount').textContent=String(items.length);
  if(!items.length){
    const d=document.createElement('div');d.className='empty';
    d.textContent=state.momentFilter==='shortlist'
      ? 'No defensible review leads for this replay yet. Goals and 50/50s remain in the event filters; the model abstains when evidence is insufficient.'
      : 'No events in this category. This is not a judgment of gameplay quality.';
    list.append(d);return;
  }
  for(const f of items){
    const btn=document.createElement('button');btn.className='finding'+(f.id===state.selectedId?' active':'');btn.type='button';
    const time=document.createElement('div');time.className='time';time.textContent=fmt(f.t);
    const tag=document.createElement('span');tag.className='tag';
    tag.textContent=f.type==='ai'?'AI REVIEW':f.type==='contextual'?'CONTEXT CHECK':f.type==='manual'?'YOUR MARKER':f.type==='event'?'MATCH EVENT':'UNVERIFIED';
    time.append(tag);
    const title=document.createElement('strong');title.textContent=f.title;
    const summary=document.createElement('small');summary.textContent=f.evidence;
    btn.append(time,title,summary);
    btn.onclick=()=>{stopPlay();state.selectedId=f.id;chooseTime(Math.max(startTime(),f.t-1.5));renderFindings();renderDetail();};
    list.append(btn);
  }
}
function renderDetail(){
  const target=$('selectedDetail');target.replaceChildren();
  const f=state.findings.find(x=>x.id===state.selectedId);
  if(!f){
    const p=document.createElement('p');p.className='muted';p.textContent='Select an event or observation to inspect its evidence.';target.append(p);return;
  }
  const h=document.createElement('h3');h.className='detail-title';h.textContent=f.title;
  const tag=document.createElement('div');tag.className='detail-sub';
  tag.textContent=fmt(f.t)+' · '+String(f.confidence).toUpperCase()+' / '+(f.type==='event'?'EVENT':'HYPOTHESIS');
  target.append(h,tag);
  const lead=document.createElement('button');lead.className='button-mini leadin-btn';lead.type='button';
  lead.textContent='Watch the 2 seconds before this moment';
  lead.onclick=()=>{stopPlay();chooseTime(Math.max(0,f.t-2));};target.append(lead);
  for(const [k,val] of [['Observed evidence',f.evidence],['Question to investigate',f.advice],['Limits / uncertainty',f.uncertainty||'Replay positions alone cannot prove intent, camera perception, or a better alternative.']]){
    const section=document.createElement('div');section.className='detail-section';
    const heading=document.createElement('strong');heading.textContent=k;
    const paragraph=document.createElement('p');paragraph.textContent=val;
    section.append(heading,paragraph);target.append(section);
  }
  // Explicit player feedback is the only way to learn about unknown intention.
  // Keep it collapsed and local. Export it with the review JSON for human QA.
  const details=document.createElement('details');details.className='feedback-panel';
  const summary=document.createElement('summary');summary.textContent='Rate this insight / explain your intent';
  details.append(summary);
  const key=state.focusId+'|'+f.id;
  const saved=state.reviewFeedback.get(key)||{};
  const row=document.createElement('div');row.className='feedback-choices';
  const buttons=[];
  for(const [value,label] of [['useful','Helpful'],['wrong','Incorrect'],['unclear','Not sure']]){
    const btn=document.createElement('button');btn.type='button';btn.className='button-mini'+(saved.rating===value?' active':'');
    btn.textContent=label;
    btn.onclick=()=>{
      state.reviewFeedback.set(key,{...state.reviewFeedback.get(key),rating:value});
      for(const candidate of buttons)candidate.classList.toggle('active',candidate===btn);
    };
    buttons.push(btn);row.append(btn);
  }
  details.append(row);
  const note=document.createElement('textarea');note.rows=3;note.maxLength=1500;
  note.placeholder='What were you trying to do? What did this analysis miss?';
  note.value=saved.note||'';
  note.oninput=()=>state.reviewFeedback.set(key,{...state.reviewFeedback.get(key),note:note.value});
  details.append(note);target.append(details);
}
const xyDistance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
function recentPath(kind,focusId,seconds){
  const result=[], fs=state.replay?.frames||[];
  const index=nearestIndex(state.time);if(index<0)return result;
  for(let i=index;i>=0&&result.length<165;i--){
    const f=fs[i];if(f.t<state.time-seconds)break;
    const p=kind==='ball'?f.ball:f.cars[focusId];
    if(p&&Number.isFinite(p.x)&&Number.isFinite(p.y))result.push({t:f.t,x:p.x,y:p.y});
  }
  return result.reverse();
}
function renderBoostPads(){
  const parent=$('boostPadsLayer');
  if(!parent)return;
  parent.replaceChildren();
  if(!state.view.boostPads||typeof BOOST_PADS_2D==='undefined')return;
  for(let i=0; i<BOOST_PADS_2D.length; i++){
    const pad=BOOST_PADS_2D[i];
    const x=sx(pad.x),y=sy(pad.y);
    const timeline=state.replay?.boostPadTimeline;
    const st=timeline ? (globalThis.ReplayLabViewMath?.padStateAt(timeline, i, state.time) || {available:true}) : {available:true};
    const opacity=st.available ? '1.0' : '0.22';
    if(pad.big){
      const ring=el('circle',{cx:x,cy:y,r:13,fill:'none',stroke:'#ffca28','stroke-width':1.8,opacity:st.available?'.8':'.2'});
      const dot=el('circle',{cx:x,cy:y,r:8,class:'boost-big',opacity});
      parent.append(ring,dot);
    }else{
      const dot=el('circle',{cx:x,cy:y,r:4.5,class:'boost-small',opacity});
      parent.append(dot);
    }
  }
}
function setViewMode(mode){
  currentViewMode=mode;
  for(const [id,name] of [['viewTab2d','2d'],['viewTab3d','3d'],['viewTabSplit','split']]){
    const selected=mode===name;
    $(id).classList.toggle('active',selected);
    $(id).setAttribute('aria-selected',String(selected));
  }
  const shell=$('pitchShell'),field=$('field'),vp3d=$('viewport3d'),ctrl3d=$('controls3d'),badge=$('pitchBadge');
  shell.className = 'pitch-shell mode-'+mode;
  if(mode==='2d'){
    field.style.display='block';field.hidden=false;
    vp3d.style.display='none';vp3d.hidden=true;
    ctrl3d.style.display='none';ctrl3d.hidden=true;
    if(badge){badge.style.display='block';badge.textContent='REPLAY FIELD · 2D TOP-DOWN VIEW';}
    renderPitch();
  }else if(mode==='3d'){
    field.style.display='none';field.hidden=true;
    vp3d.style.display='block';vp3d.hidden=false;
    ctrl3d.style.display='flex';ctrl3d.hidden=false;
    if(badge)badge.style.display='none';
    const v=getViewer3d();v?.onResize();
    if(state.replay)v?.update(currentFrame(),state.focusId,state.replay.players);
  }else if(mode==='split'){
    shell.className = 'pitch-shell split-mode';
    field.style.display='block';field.hidden=false;
    vp3d.style.display='block';vp3d.hidden=false;
    ctrl3d.style.display='flex';ctrl3d.hidden=false;
    if(badge){badge.style.display='block';badge.textContent='REPLAY FIELD · SYNCHRONIZED 2D + 3D VIEW';}
    renderPitch();
    const v=getViewer3d();v?.onResize();
    if(state.replay)v?.update(currentFrame(),state.focusId,state.replay.players);
  }
}
function setCamMode(mode){
  for(const [id,m] of [['camOrbit','orbit'],['camTactical','tactical'],['camFollow','follow'],['camBall','ball'],['camPOV','pov']]){
    $(id)?.classList.toggle('active',m===mode);
  }
  getViewer3d()?.setCameraMode(mode);
}
function drawTrail(parent,points,color,thickness,dashed){
  if(points.length<2)return;
  const stride=Math.max(1,Math.ceil(points.length/70));
  const trace=points.filter((_,i)=>i%stride===0||i===points.length-1);
  for(let i=1;i<trace.length;i++){
    const before=trace[i-1],after=trace[i],gap=after.t-before.t;
    if(gap>0.45||gap<0||xyDistance(before,after)>1200)continue;
    const progress=i/(trace.length-1);
    const line=el('line',{x1:sx(before.x),y1:sy(before.y),x2:sx(after.x),y2:sy(after.y),
      stroke:color,'stroke-width':thickness,'stroke-linecap':'round',opacity:(0.09+progress*0.58).toFixed(2)});
    if(dashed)line.setAttribute('stroke-dasharray','4 7');
    parent.append(line);
  }
}
function renderPitch(){
  if(currentViewMode==='3d')return;
  const parent=$('dynamicLayers');parent.replaceChildren();
  const f=currentFrame();if(!f)return;
  const focus=f.cars[state.focusId], b=f.ball;
  if(state.view.ballTrail)drawTrail(parent,recentPath('ball',null,1.5),'#f6f8fd',3,true);
  if(state.view.trail && focus)drawTrail(parent,recentPath('car',state.focusId,2),'#7de2d7',5,false);

  // Coordinates are a genuine top-down projection. These symbols do NOT imply player POV.
  const bx=sx(b.x),by=sy(b.y);
  const elevated=Number.isFinite(b.z)&&b.z>280;
  if(elevated){
    parent.append(el('circle',{cx:bx,cy:by,r:24,fill:'none',stroke:'#daeefe','stroke-width':1.8,'stroke-dasharray':'5 6',opacity:'.7'}));
  }
  parent.append(el('circle',{cx:bx,cy:by,r:12,fill:'#f2fbff',stroke:'#62dee8','stroke-width':2.5,filter:'url(#glow)'}));
  const ballText=state.view.heights&&Number.isFinite(b.z)?('BALL · '+Math.round(b.z)+'u'):'BALL';
  parent.append(el('text',{x:bx+19,y:by-16,fill:'#d4f9ff','font-size':12,'font-weight':700,'paint-order':'stroke',stroke:'#0c2029','stroke-width':3},ballText));

  for(let i=0;i<state.replay.players.length;i++){
    const p=state.replay.players[i],car=f.cars[p.id];if(!car)continue;
    const x=sx(car.x),y=sy(car.y),isFocus=p.id===state.focusId;
    const color=p.team==='orange'?'#f6a56c':'#72b7fa';
    if(car.demolished){
      // The replay keeps a destroyed car frozen where it died until it respawns.
      parent.append(el('text',{x,y:y+6,'text-anchor':'middle',fill:color,'font-size':19,'font-weight':800,opacity:'.6'},'✕'));
      continue;
    }
    const group=el('g');
    if(isFocus)group.append(el('circle',{cx:x,cy:y,r:26,fill:'none',stroke:'#90f5e8','stroke-width':3,opacity:'.95'}));
    if(state.view.heights&&Number.isFinite(car.z)&&car.z>110){
      group.append(el('circle',{cx:x,cy:y,r:21,fill:'none',stroke:color,'stroke-width':1.6,'stroke-dasharray':'3 4',opacity:'.8'}));
    }
    const vx=car.velocity?.[0],vy=car.velocity?.[1];
    const speed=Number.isFinite(vx)&&Number.isFinite(vy)?Math.hypot(vx,vy):0;
    if(state.view.travel&&speed>=180){
      const ux=-vx/speed,uy=-vy/speed,scale=isFocus?36:29;
      const ex=x+ux*scale,ey=y+uy*scale;
      group.append(el('line',{x1:x,y1:y,x2:ex,y2:ey,stroke:color,'stroke-width':isFocus?4:3,'stroke-linecap':'round',opacity:'.92'}));
      const wing=7,back=8;
      group.append(el('polygon',{points:[
        [ex,ey],[ex-ux*back-uy*wing,ey-uy*back+ux*wing],
        [ex-ux*back+uy*wing,ey-uy*back-ux*wing]
      ].map(a=>a.join(',')).join(' '),fill:color,opacity:'.95'}));
    }
    group.append(el('circle',{cx:x,cy:y,r:isFocus?13:11,fill:color,stroke:isFocus?'#f4ffff':'#b9d7e4','stroke-width':isFocus?2.3:1.3}));
    // Nose direction comes from the car's real forward vector. Euler rotation Z only equals
    // yaw while the car is flat, so it is just the fallback for payloads without `forward`.
    const yaw=car.rotation?.[2];
    const fwd=Array.isArray(car.forward)?car.forward:(Number.isFinite(yaw)?[Math.cos(yaw),Math.sin(yaw),0]:null);
    const flat=fwd?Math.hypot(fwd[0],fwd[1]):0;
    // Below 0.25 the nose points almost straight up or down: no honest map direction exists.
    if(state.view.facing&&flat>=0.25){
      const fx=-fwd[0]/flat,fy=-fwd[1]/flat,tip=21,back=10,side=6;
      const tx=x+fx*tip,ty=y+fy*tip;
      const baseX=x+fx*back,baseY=y+fy*back;
      group.append(el('polygon',{points:[[tx,ty],[baseX-fy*side,baseY+fx*side],
        [baseX+fy*side,baseY-fx*side]].map(a=>a.join(',')).join(' '),
        fill:'#f3ffff',stroke:'#10202d','stroke-width':1.5}));
    }
    group.append(el('text',{x,y:y+4,'text-anchor':'middle',fill:'#091924','font-size':10,'font-weight':800},isFocus?'F':p.team==='blue'?'B':'O'));
    const name=p.name.slice(0,16);
    group.append(el('text',{x,y:y-31,fill:'#f1f8fa','font-size':isFocus?12:11,
      'text-anchor':'middle','font-weight':isFocus?700:500,'paint-order':'stroke',stroke:'#091924','stroke-width':3.5},name));
    if(state.view.heights&&Number.isFinite(car.z)&&car.z>110){
      group.append(el('text',{x,y:y+35,fill:color,'font-size':10,'text-anchor':'middle','font-weight':700,
        'paint-order':'stroke',stroke:'#091924','stroke-width':3},'Z '+Math.round(car.z)+'u'));
    }
    parent.append(group);
  }
  const near=state.replay.events?.find(e=>e.type==='touch'&&Math.abs(e.t-state.time)<0.075);
  if(near){
    const who=playerById(near.playerId);
    parent.append(el('text',{x:bx+18,y:by+26,fill:'#ffe5bb','font-size':11,'font-weight':700,
      'paint-order':'stroke',stroke:'#07131d','stroke-width':4},
    'TOUCH'+(who?' · '+who.name.slice(0,12):'')));
  }
}
function renderSceneInspector(){
  // Stable one-line clock. Rebuilding large dynamic cards 30 times per second
  // previously expanded the sidebar and caused page-scroll jitter.
  const holder=$('sceneInspector'),f=currentFrame();
  const message=!f?'No replay loaded.':
    'Replay '+fmt(state.time)+' · '+
    (Number.isFinite(f.secondsRemaining)
      ? (f.overtime?'Overtime +'+fmt(f.secondsRemaining):'Match clock '+fmt(f.secondsRemaining))
      : 'Game clock unavailable');
  let line=holder.firstElementChild;
  if(!line||!line.classList.contains('scene-time')){
    line=document.createElement('div');line.className='scene-time';
    holder.replaceChildren(line);
  }
  if(line.textContent!==message)line.textContent=message;
  renderRecentActions();
}
function renderRecentActions(){
  const panel=$('recentActionsPanel'),list=$('recentActionsList');
  if(!panel||!list||!panel.open)return; // No DOM churn for a closed panel.
  const actions=(state.replay?.events||[])
    .filter(e=>['touch','bump','whiff'].includes(e.type)
      && e.t<=state.time+0.03&&e.t>=state.time-3)
    .slice(-5).reverse();
  const signature=actions.map(e=>[e.t,e.type,e.playerId,e.touchKind,e.classification].join(':')).join('|');
  if(list.dataset.signature===signature)return;
  list.dataset.signature=signature;
  list.replaceChildren();
  if(!actions.length){
    const note=document.createElement('p');note.className='touch-empty';
    note.textContent='No recent detected touches.';list.append(note);return;
  }
  for(const e of actions){
    const player=playerById(e.playerId);
    const btn=document.createElement('button');btn.className='touch-link';btn.type='button';
    const action=e.type==='bump'?'Collision':e.type==='whiff'?'Possible missed touch':'Ball touch';
    const label=document.createElement('span');label.textContent=(player?.name||'Unknown player')+' · '+action;
    const stamp=document.createElement('small');stamp.textContent=fmt(e.t);
    btn.append(label,stamp);
    btn.onclick=()=>{stopPlay();chooseTime(e.t);};
    btn.onpointerdown=btn.onclick;
    list.append(btn);
  }
}
let playbackHandle=null;
let lastPlayTimestamp=0;

function stopPlay(){
  if(playbackHandle){
    cancelAnimationFrame(playbackHandle);
    playbackHandle=null;
  }
  if(state.timer){
    clearInterval(state.timer);
    state.timer=null;
  }
  state.playing=false;
  $('playBtn').textContent='▶';
  const video=$('gameVideo');
  if(state.videoUrl&&!video.paused)video.pause();
}

function playTick(timestamp){
  if(!state.playing||!state.replay){
    playbackHandle=null;
    return;
  }
  if(!lastPlayTimestamp)lastPlayTimestamp=timestamp;
  const delta=Math.min(0.1,(timestamp-lastPlayTimestamp)/1000);
  lastPlayTimestamp=timestamp;

  const next=state.time+delta*(state.speed||1);
  if(next>=state.replay.duration){
    chooseTime(state.replay.duration);
    stopPlay();
    return;
  }
  chooseTime(next);
  playbackHandle=requestAnimationFrame(playTick);
}

function togglePlay(){
  if(!state.replay)return;
  if(state.playing){stopPlay();return;}
  state.playing=true;
  $('playBtn').textContent='❚❚';
  lastPlayTimestamp=performance.now();

  const video=$('gameVideo');
  if(state.videoUrl&&state.videoAligned&&video.readyState>=1){
    video.playbackRate=state.speed;
    syncVideoToReplay(true);
    const target=state.time+state.videoOffset;
    if(target>=0&&target<video.duration)video.play().catch(()=>{});
  }
  playbackHandle=requestAnimationFrame(playTick);
}
function syncVideoToReplay(force=false){
  const video=$('gameVideo');
  if(!state.videoUrl||!state.videoAligned||video.readyState<1||!state.replay)return;
  const target=state.time+state.videoOffset;
  if(target<0||!Number.isFinite(video.duration)||target>video.duration){
    if(state.playing&&!video.paused)video.pause();
    return;
  }
  if(force||Math.abs(video.currentTime-target)>0.32){
    try{video.currentTime=target;}catch(_){}
  }
  // The clip may start after the point where playback began: start it once the playhead
  // enters its range (previously it stayed paused and only jumped between seeks).
  if(state.playing&&video.paused&&!video.ended){video.playbackRate=state.speed;video.play().catch(()=>{});}
}
// When the user presses play on the video's own controls, the video is the clock: follow it
// every animation frame instead of the ~4 Hz `timeupdate` event.
let followHandle=null;
function followVideo(){
  const video=$('gameVideo');
  if(state.playing||video.paused||!state.videoAligned||!state.replay){followHandle=null;return;}
  const t=video.currentTime-state.videoOffset;
  if(t>=startTime()&&t<=state.replay.duration)chooseTime(t);
  followHandle=requestAnimationFrame(followVideo);
}
function removeVideo(){
  const video=$('gameVideo');video.pause();video.removeAttribute('src');video.load();video.hidden=true;
  if(state.videoUrl){URL.revokeObjectURL(state.videoUrl);state.videoUrl=null;}
  $('videoFile').value='';state.videoOffset=0;state.videoAligned=false;$('videoOffset').value='0';
  $('clearVideo').disabled=true;$('alignVideo').disabled=true;
  $('videoStatus').textContent='Video synchronization requires a matching clip and a manually chosen offset.';
}
function loadVideo(file){
  if(!file)return;
  if(!file.type.startsWith('video/')){show('Choose a video file such as MP4 or WebM.');return;}
  removeVideo();
  state.videoUrl=URL.createObjectURL(file);
  const video=$('gameVideo');video.src=state.videoUrl;video.hidden=false;video.playbackRate=state.speed;
  $('clearVideo').disabled=false;$('alignVideo').disabled=false;
  $('videoStatus').textContent='Loading local recording. Align a known replay moment with the same video frame.';
  video.onloadedmetadata=()=>{
    $('videoStatus').textContent='Recording loaded ('+fmt(video.duration)+'). Video time = replay time + offset. Use Align at a matching moment.';
    // Do not move the replay playhead before explicit user alignment.
  };
}
function wireVideo(){
  $('videoFile').onchange=e=>loadVideo(e.target.files?.[0]);
  $('clearVideo').onclick=removeVideo;
  $('videoOffset').onchange=e=>{
    const number=Number(e.target.value);
    state.videoOffset=Number.isFinite(number)?number:0;
    state.videoAligned=true;
    syncVideoToReplay(true);
  };
  $('alignVideo').onclick=()=>{
    if(!state.videoUrl||!state.replay){show('Load a replay and a matching recording first.');return;}
    const video=$('gameVideo');
    state.videoOffset=Math.round((video.currentTime-state.time)*100)/100;
    state.videoAligned=true;
    $('videoOffset').value=state.videoOffset.toFixed(2);
    $('videoStatus').textContent='Aligned at replay '+fmt(state.time)+' / video '+fmt(video.currentTime)+'. Offset '+state.videoOffset.toFixed(2)+'s; check another event to verify.';
    show('Video alignment set. Compare another touch to verify synchronization.');
  };
  $('gameVideo').addEventListener('play',()=>{if(!state.playing&&!followHandle)followHandle=requestAnimationFrame(followVideo);});
  $('gameVideo').addEventListener('timeupdate',()=>{
    if(!state.replay||!state.videoUrl||!state.videoAligned||state.playing)return;
    const t=$('gameVideo').currentTime-state.videoOffset;
    if(t>=0&&t<=state.replay.duration&&Math.abs(state.time-t)>0.16)chooseTime(t);
  });
}

function exportReview(){const body=JSON.stringify({replay:{schema:state.replay.schema,title:state.replay.title,mode:state.replay.mode,source:state.replay.source,duration:state.replay.duration},focus:playerById(state.focusId),findings:state.findings.map(f=>({...f,target:state.overrides.get(f.id)||f.target})),feedback:Object.fromEntries(state.reviewFeedback)},null,2);const url=URL.createObjectURL(new Blob([body],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='rocket-league-review.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function loadFile(file){if(!file)return;if(!file.name.toLowerCase().endsWith('.replay'))return show('Select a Rocket League .replay file.');if(file.size>20*1024*1024)return show('File exceeds 20 MB.');$('uploadStatus').textContent='Processing native replay locally…';try{const r=await fetch('/api/replays',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Replay-Name':encodeURIComponent(file.name)},body:file});const body=await r.json().catch(()=>({}));if(!r.ok)throw new Error(body.detail||'Replay parser could not read file.');setReplay(body.replay);show('Replay loaded. Choose your player to start.');}catch(e){$('uploadStatus').textContent=e.message;show(e.message);}}
async function aiReview(){
  if(!state.replay)return;
  const selected=state.findings.find(f=>f.id===state.selectedId);
  const center=selected?.t??state.time;
  const windowFrames=state.replay.frames.filter(f=>Math.abs(f.t-center)<=3.0);
  if(!windowFrames.length)return show('No telemetry near the selected moment.');
  const stride=Math.max(1,Math.ceil(windowFrames.length/90));
  const samples=windowFrames.filter((_,i)=>i%stride===0).slice(0,90);
  if(!window.confirm('Analyze this 6-second replay window with Gemini? Anonymized car and ball telemetry, not your replay video, will be sent. This consumes your API quota.'))return;
  $('aiBtn').disabled=true;$('aiBtn').textContent='Checking this moment...';
  try{
    const r=await fetch('/api/ai-review',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        replay:{schema:state.replay.schema,title:state.replay.title,mode:state.replay.mode,
          duration:state.replay.duration,players:state.replay.players,frames:samples},
        player_id:state.focusId,selected_time:center
      })
    });
    const body=await r.json();
    if(!r.ok)throw new Error(body.detail||'AI analysis failed.');
    for(const f of body.findings||[])state.findings.push({...f,focusId:state.focusId});
    state.findings.sort((a,b)=>a.t-b.t);
    state.selectedId=body.findings?.[0]?.id||state.selectedId;
    $('flagsValue').textContent=state.findings.filter(f=>['manual','ai','contextual'].includes(f.type)).length;
    renderFindings();renderDetail();
    if(body.findings?.length){chooseTime(body.findings[0].t);show('Experimental hypothesis added. Verify it in the replay.');}
    else show('No defensible hypothesis from this window. No review note added.');
  }catch(e){show(e.message);}
  finally{$('aiBtn').textContent='Ask Gemini about selected moment';$('aiBtn').disabled=false;}
}
function addManualMarker(){if(!state.replay)return;const f=currentFrame();const id='manual-'+Date.now();const finding={id,t:f.t,type:'manual',title:'Review this decision',confidence:'unverified',evidence:'Manual marker at the current replay timestamp.',advice:'Inspect the opponent, ball height, timing and recent touches. A marker records a question, not a mistaken decision.',target:null};state.findings.push(finding);state.findings.sort((a,b)=>a.t-b.t);state.selectedId=id;$('flagsValue').textContent=state.findings.filter(f=>['manual','ai','contextual'].includes(f.type)).length;renderFindings();renderDetail();renderPitch();}
function wire(){
  const zone=$('uploadZone'),input=$('fileInput');
  zone.onclick=()=>input.click();
  zone.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();input.click();}};
  // Clear the control so choosing the same file again still fires `change`.
  input.onchange=()=>{const file=input.files?.[0];input.value='';loadFile(file);};
  zone.ondragover=e=>{e.preventDefault();zone.classList.add('dragging');};
  zone.ondragleave=()=>zone.classList.remove('dragging');
  zone.ondrop=e=>{e.preventDefault();zone.classList.remove('dragging');loadFile(e.dataTransfer.files[0]);};
  $('playerSelect').onchange=e=>{state.focusId=e.target.value;state.focusConfirmed=true;if(state.replay?.source!=='synthetic')remembered.set(state.focusId);state.overrides.clear();refreshFindings();chooseTime(state.time);window.coachingController?.resetForReplay(state.replay?.source==='synthetic');if(state.replay?.source!=='synthetic')loadDecisionCasesForCoaching(state.replay,state.focusId);};
  $('timeRange').oninput=e=>{stopPlay();chooseTime(Number(e.target.value));};
  $('playBtn').onclick=togglePlay;
  $('backBtn').onclick=()=>{stopPlay();chooseTime(state.time-2);};
  $('forwardBtn').onclick=()=>{stopPlay();chooseTime(state.time+2);};
  $('playSpeed').onchange=e=>{
    const speed=Number(e.target.value);state.speed=Number.isFinite(speed)&&speed>0?speed:1;
    if(state.videoUrl&&state.videoAligned)$('gameVideo').playbackRate=state.speed;
    if(state.playing){stopPlay();togglePlay();}
  };
  for(const [id,key] of [['showFacing','facing'],['showTrail','trail'],['showBallTrail','ballTrail']]){
    $(id).onchange=e=>{state.view[key]=e.target.checked;renderPitch();};
  }
  $('showBoostPads').onchange=e=>{state.view.boostPads=e.target.checked;renderBoostPads();};
  $('recentActionsPanel').ontoggle=renderRecentActions;
  $('viewTab2d').onclick=()=>setViewMode('2d');
  $('viewTab3d').onclick=()=>setViewMode('3d');
  $('viewTabSplit').onclick=()=>setViewMode('split');
  $('camOrbit').onclick=()=>setCamMode('orbit');
  $('camTactical').onclick=()=>setCamMode('tactical');
  $('camFollow').onclick=()=>setCamMode('follow');
  $('camPOV').onclick=()=>setCamMode('pov');
  $('camBall').onclick=()=>setCamMode('ball');
  $('camReset').onclick=()=>{setCamMode('orbit');getViewer3d()?.resetCamera();};
  $('momentFilter').onchange=e=>{
    state.momentFilter=e.target.value;
    const shown=visibleFindings();
    if(!shown.some(f=>f.id===state.selectedId))state.selectedId=shown[0]?.id||null;
    renderFindings();renderDetail();
    if(state.selectedId&&shown.length)chooseTime(shown.find(f=>f.id===state.selectedId)?.t??shown[0].t);
  };
  $('markBtn').onclick=addManualMarker;
  $('exportBtn').onclick=exportReview;
  $('aiBtn').onclick=aiReview;
  if($('loadDemoBtn')){
    $('loadDemoBtn').onclick=()=>setReplay(demoReplay(), {demo: true});
  }
  wireVideo();
  window.chooseTime = chooseTime;
  window.stopPlay = stopPlay;
  window.setReplay = setReplay;
  window.demoReplay = demoReplay;
  if (typeof CoachingExperienceController !== 'undefined') {
    window.coachingController = new CoachingExperienceController();
    window.coachingController.mount('coachingExperienceContainer');
  }
}

wire();

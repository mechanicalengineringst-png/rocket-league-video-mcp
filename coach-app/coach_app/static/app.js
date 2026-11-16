'use strict';
const $ = id => document.getElementById(id);
const state = { replay: null, findings: [], focusId: null, selectedId: null, time: 0, playing: false, timer: null, overrides: new Map(), view: {travel:true, heights:true, trail:false, ballTrail:false}, speed:1, momentFilter:'all', videoUrl:null, videoOffset:0 };
const SVG_NS = 'http://www.w3.org/2000/svg';
const sx = x => 58 + ((Number(x) + 4096) / 8192) * 644;
const sy = y => 50 + ((5120 - Number(y)) / 10240) * 870;
const invx = x => (x - 58) / 644 * 8192 - 4096;
const invy = y => 5120 - (y - 50) / 870 * 10240;
const fmt = t => `${Math.floor(Math.max(0,t)/60).toString().padStart(2,'0')}:${Math.floor(Math.max(0,t)%60).toString().padStart(2,'0')}`;
const playerById = id => state.replay?.players.find(p => p.id === id);
const nearestIndex = time => { const fs=state.replay?.frames||[]; if(!fs.length)return -1; let lo=0, hi=fs.length-1; while(lo<hi){let mid=(lo+hi)>>1;if(fs[mid].t<time)lo=mid+1;else hi=mid;}return lo>0&&Math.abs(fs[lo-1].t-time)<Math.abs(fs[lo].t-time)?lo-1:lo; };
const currentFrame = () => state.replay?.frames[nearestIndex(state.time)] || null;
const show = (message) => { $('toast').textContent=message; $('toast').classList.add('show'); clearTimeout(show.timer); show.timer=setTimeout(()=>$('toast').classList.remove('show'),3600); };
function el(tag, attrs={}, text) { const n=document.createElementNS(SVG_NS,tag); for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v)); if(text!==undefined)n.textContent=text; return n; }
function chooseTime(time){if(!state.replay)return;state.time=Math.max(0,Math.min(time,state.replay.duration));$('timeRange').value=state.time;$('timeValue').textContent=fmt(state.time)+'.'+String(Math.floor((state.time%1)*100)).padStart(2,'0');renderPitch();renderSceneInspector();syncVideoToReplay();}
function setReplay(replay, opts={}){
  if(!replay || !Array.isArray(replay.players) || !Array.isArray(replay.frames) || !replay.frames.length)throw new Error('Invalid replay timeline.');
  stopPlay();removeVideo();state.replay=replay;state.focusId=replay.players.some(p=>p.id===replay.primaryPlayerId)?replay.primaryPlayerId:replay.players[0].id;state.selectedId=null;state.overrides.clear();state.time=0;
  $('replayTitle').textContent=replay.title; $('modeValue').textContent=replay.mode; $('durationValue').textContent=fmt(replay.duration);
  $('playerSelect').replaceChildren(...replay.players.map(p=>{const o=document.createElement('option');o.value=p.id;o.textContent=`${p.name} — ${p.team.toUpperCase()}`;return o;}));
  $('playerSelect').value=state.focusId;
  for(const id of ['playerSelect','timeRange','playBtn','backBtn','forwardBtn','markBtn','exportBtn','aiBtn'])$(id).disabled=false;
  $('timeRange').max=replay.duration;$('endTime').textContent=fmt(replay.duration);
  $('uploadStatus').textContent=opts.demo?'Simulated example loaded. This is NOT an actual match.':(replay.playerMappingVerified===false?'Replay decoded, but player identities could not be verified from kickoff spawns.':('Decoded '+(replay.telemetrySampleCount||replay.frames.length)+' physics samples; '+(replay.eventCounts?.touch||0)+' touches, '+(replay.eventCounts?.goal_context||0)+' goals. Events are review observations, not proven mistakes.'));
  refreshFindings(opts.demo);chooseTime(0);
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
  const findings=[];const fs=state.replay.frames;const team=playerById(state.focusId)?.team;
  let seen={};for(const f of fs){const car=f.cars[state.focusId];if(!car)continue;const mate=state.replay.players.filter(p=>p.team===team&&p.id!==state.focusId).map(p=>f.cars[p.id]).find(Boolean);const dist=(p,q)=>Math.hypot(p.x-q.x,p.y-q.y);
    if(mate&&dist(car,f.ball)<900&&dist(mate,f.ball)<900&&dist(car,mate)<1300&&f.t-(seen.overlap??-100)>18){findings.push({id:'overlap'+f.t,t:f.t,title:'Two teammates near the ball',type:'overlap',confidence:'low',evidence:'Both teammates are within 900 units of the ball and 1300 units of each other.',advice:'Check who had priority for the next touch. Proximity alone does not prove a double commit.',target:null});seen.overlap=f.t;}
    let ownY=team==='blue'?-5120:5120;
    if(car.boost!==null&&car.boost!==undefined&&car.boost<=12&&Math.abs(car.y-ownY)<2700&&Math.abs(f.ball.y-ownY)<3500&&f.t-(seen.boost??-100)>30){findings.push({id:'boost'+f.t,t:f.t,title:'Low boost near own goal',type:'boost',confidence:'low',evidence:`Your car has approximately ${Math.round(car.boost)} boost near your goal.`,advice:'Check whether a small-pad route could have preserved boost and goal-side coverage. This may be unavoidable.',target:null});seen.boost=f.t;}
    if(findings.length>=8)break;
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
  state.findings=findings;state.selectedId=findings[0]?.id||null;
  $('flagsValue').textContent=findings.length;renderFindings();renderDetail();
}
function visibleFindings(){
  const filter=state.momentFilter;
  return state.findings.filter(f=>{
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
  $('issueCount').textContent=items.length===state.findings.length?String(items.length):(items.length+' / '+state.findings.length);
  if(!items.length){
    const d=document.createElement('div');d.className='empty';
    d.textContent='No moments in this category. This is not a judgment of gameplay quality.';
    list.append(d);return;
  }
  for(const f of items){
    const btn=document.createElement('button');btn.className='finding'+(f.id===state.selectedId?' active':'');btn.type='button';
    const time=document.createElement('div');time.className='time';time.textContent=fmt(f.t);
    const tag=document.createElement('span');tag.className='tag';
    tag.textContent=f.type==='ai'?'AI REVIEW':f.type==='manual'?'YOUR MARKER':f.type==='event'?'MATCH EVENT':'OBSERVATION';
    time.append(tag);
    const title=document.createElement('strong');title.textContent=f.title;
    const summary=document.createElement('small');summary.textContent=f.evidence;
    btn.append(time,title,summary);
    btn.onclick=()=>{stopPlay();state.selectedId=f.id;chooseTime(f.t);renderFindings();renderDetail();};
    list.append(btn);
  }
}
function renderDetail(){const target=$('selectedDetail');target.replaceChildren();let f=state.findings.find(x=>x.id===state.selectedId);if(!f){const p=document.createElement('p');p.className='muted';p.textContent='Select a moment to inspect its evidence and alternative.';target.append(p);return;}
const h=document.createElement('h3');h.className='detail-title';h.textContent=f.title;const tag=document.createElement('div');tag.className='detail-sub';tag.textContent=`${fmt(f.t)} · ${f.confidence.toUpperCase()} CONFIDENCE`;target.append(h,tag);
for(const [k,val] of [['Observed evidence',f.evidence],['Coaching hypothesis',f.advice],['Uncertainty',f.uncertainty||'This is a sparse replay-data observation. Verify the threat and teammate recovery before treating it as a mistake.']]){const section=document.createElement('div');section.className='detail-section';const heading=document.createElement('strong');heading.textContent=k;const paragraph=document.createElement('p');paragraph.textContent=val;section.append(heading,paragraph);target.append(section);}}
function renderPitch(){const parent=$('dynamicLayers');parent.replaceChildren();const f=currentFrame();if(!f)return;const ci=nearestIndex(state.time);const focus=f.cars[state.focusId];
if(focus){$('boostValue').textContent=`BOOST ${focus.boost==null?'—':Math.round(focus.boost)+'%'}`;const trailLength=Math.min(500,Math.ceil(5/(state.replay.samplingSeconds||.5)));const trail=state.replay.frames.slice(Math.max(0,ci-trailLength),ci+1).map(a=>a.cars[state.focusId]).filter(Boolean);if(trail.length>1)parent.append(el('polyline',{points:trail.map(c=>`${sx(c.x)},${sy(c.y)}`).join(' '),fill:'none',stroke:'#7de2d7','stroke-width':6,'stroke-linecap':'round','stroke-linejoin':'round',opacity:'.88'}));
const selected=state.findings.find(q=>q.id===state.selectedId);if(selected&&selected.type!=='event'){const key=selected.id;const target=state.overrides.get(key)||selected.target||supportPoint(f,state.focusId);const atf=state.replay.frames[nearestIndex(selected.t)];const start=atf?.cars[state.focusId]||focus;
parent.append(el('line',{x1:sx(start.x),y1:sy(start.y),x2:sx(target.x),y2:sy(target.y),stroke:'#f0c57f','stroke-width':5,'stroke-dasharray':'13 12','stroke-linecap':'round'}));parent.append(el('circle',{cx:sx(target.x),cy:sy(target.y),r:17,stroke:'#ffd48e','stroke-width':3,fill:'#deb06a','fill-opacity':'.16'}));parent.append(el('text',{x:sx(target.x)+23,y:sy(target.y)-15,fill:'#ffe0aa','font-size':14},'OPTION'));}
}
parent.append(el('circle',{cx:sx(f.ball.x),cy:sy(f.ball.y),r:16,fill:'#f2fbff',stroke:'#62dee8','stroke-width':3,filter:'url(#glow)'}));parent.append(el('text',{x:sx(f.ball.x)+22,y:sy(f.ball.y)+6,fill:'#d4f9ff','font-size':13},f.ball.z!=null?`BALL · ${Math.round(f.ball.z)}u`:'BALL'));
for(const p of state.replay.players){const car=f.cars[p.id];if(!car)continue;const x=sx(car.x),y=sy(car.y),isFocus=p.id===state.focusId;const group=el('g');if(isFocus)group.append(el('circle',{cx:x,cy:y,r:29,fill:'none',stroke:'#8cf2e5','stroke-width':3,opacity:'.75'}));group.append(el('circle',{cx:x,cy:y,r:isFocus?19:14,fill:p.team==='orange'?'#e99b65':'#68aaff',stroke:'#e7faff','stroke-width':isFocus?3:1.4}));group.append(el('text',{x,y:y+4,fill:'#0c2029','text-anchor':'middle','font-size':12,'font-weight':700},isFocus?'YOU':p.team==='blue'?'B':'O'));group.append(el('text',{x,y:y-29,fill:'#edf8fa','text-anchor':'middle','font-size':12,'paint-order':'stroke',stroke:'#0c2029','stroke-width':4},p.name.slice(0,14)));parent.append(group);}
}
function stopPlay(){if(state.timer)clearInterval(state.timer);state.timer=null;state.playing=false;$('playBtn').textContent='▶';}
function togglePlay(){if(!state.replay)return;if(state.playing){stopPlay();return;}state.playing=true;$('playBtn').textContent='❚❚';state.timer=setInterval(()=>{const next=state.time+0.05;if(next>=state.replay.duration){chooseTime(state.replay.duration);stopPlay();return;}chooseTime(next);},50);}
function exportReview(){const body=JSON.stringify({replay:{schema:state.replay.schema,title:state.replay.title,mode:state.replay.mode,source:state.replay.source,duration:state.replay.duration},focus:playerById(state.focusId),findings:state.findings.map(f=>({...f,target:state.overrides.get(f.id)||f.target}))},null,2);const url=URL.createObjectURL(new Blob([body],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='rocket-league-review.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function loadFile(file){if(!file)return;if(!file.name.toLowerCase().endsWith('.replay'))return show('Select a Rocket League .replay file.');if(file.size>20*1024*1024)return show('File exceeds 20 MB.');$('uploadStatus').textContent='Processing native replay locally…';try{const r=await fetch('/api/replays',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Replay-Name':file.name},body:file});const body=await r.json();if(!r.ok)throw new Error(body.detail||'Replay parser could not read file.');setReplay(body.replay);show('Replay loaded. Choose your player to start.');}catch(e){$('uploadStatus').textContent=e.message;show(e.message);}}
async function aiReview(){if(!state.replay)return;if(!window.confirm('Send time-sampled car and ball positions (including player IDs/names) to Gemini? This uses your API quota; the raw .replay file is not sent.'))return;
$('aiBtn').disabled=true;$('aiBtn').textContent='Analyzing positions…';try{const r=await fetch('/api/ai-review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({replay:{schema:state.replay.schema,title:state.replay.title,mode:state.replay.mode,duration:state.replay.duration,players:state.replay.players,frames:state.replay.frames.filter((_,i)=>i%Math.max(1,Math.ceil(state.replay.frames.length/240))===0).slice(0,240)},player_id:state.focusId})});const body=await r.json();if(!r.ok)throw new Error(body.detail||'AI analysis failed.');for(const f of body.findings||[])state.findings.push(f);state.selectedId=body.findings?.[0]?.id||state.selectedId;$('flagsValue').textContent=state.findings.length;renderFindings();renderDetail();if(body.findings?.length)chooseTime(body.findings[0].t);show('Gemini findings received. Verify each observation before trusting it.');}catch(e){show(e.message);}finally{$('aiBtn').textContent='✦ Ask Gemini for coaching';$('aiBtn').disabled=false;}}
function addManualMarker(){if(!state.replay)return;const f=currentFrame();const id='manual-'+Date.now();const finding={id,t:f.t,type:'manual',title:'Review this decision',confidence:'unverified',evidence:'Manual marker at the current replay timestamp.',advice:'Inspect the ball threat, teammate recovery, and next touch. Drag the suggested target by clicking the field.',target:supportPoint(f,state.focusId)};state.findings.unshift(finding);state.selectedId=id;$('flagsValue').textContent=state.findings.length;renderFindings();renderDetail();renderPitch();}
function wire(){const zone=$('uploadZone');const input=$('fileInput');zone.onclick=()=>input.click();zone.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();input.click();}};input.onchange=()=>loadFile(input.files?.[0]);zone.ondragover=e=>{e.preventDefault();zone.classList.add('dragging');};zone.ondragleave=()=>zone.classList.remove('dragging');zone.ondrop=e=>{e.preventDefault();zone.classList.remove('dragging');loadFile(e.dataTransfer.files[0]);};
$('demoBtn').onclick=()=>{setReplay(demoReplay(),{demo:true});show('Illustrative demo loaded; upload a real replay for real positions.');};$('playerSelect').onchange=e=>{state.focusId=e.target.value;state.overrides.clear();refreshFindings();renderPitch();};$('timeRange').oninput=e=>{stopPlay();chooseTime(Number(e.target.value));};$('playBtn').onclick=togglePlay;$('markBtn').onclick=addManualMarker;$('exportBtn').onclick=exportReview;$('aiBtn').onclick=aiReview;
$('field').onclick=e=>{if(!state.replay||!state.selectedId)return;let svg=$('field');let p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;let ctm=svg.getScreenCTM();if(!ctm)return;let pt=p.matrixTransform(ctm.inverse());if(pt.x<58||pt.x>702||pt.y<50||pt.y>920)return;state.overrides.set(state.selectedId,{x:Math.round(invx(pt.x)),y:Math.round(invy(pt.y))});renderPitch();show('Illustrative target updated (not a simulated outcome).');};
}
wire();

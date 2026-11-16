'use strict';
const $ = id => document.getElementById(id);
const state = { replay: null, findings: [], focusId: null, selectedId: null, time: 0, playing: false, timer: null, overrides: new Map(), view: {facing:true, travel:false, heights:true, trail:false, ballTrail:false}, speed:1, momentFilter:'all', videoUrl:null, videoOffset:0, videoAligned:false };
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
    const group=el('g');
    if(isFocus)group.append(el('circle',{cx:x,cy:y,r:26,fill:'none',stroke:'#90f5e8','stroke-width':3,opacity:'.95'}));
    if(state.view.heights&&Number.isFinite(car.z)&&car.z>110){
      group.append(el('circle',{cx:x,cy:y,r:21,fill:'none',stroke:color,'stroke-width':1.6,'stroke-dasharray':'3 4',opacity:'.8'}));
    }
    const vx=car.velocity?.[0],vy=car.velocity?.[1];
    const speed=Number.isFinite(vx)&&Number.isFinite(vy)?Math.hypot(vx,vy):0;
    if(state.view.travel&&speed>=180){
      const ux=vx/speed,uy=-vy/speed,scale=isFocus?36:29;
      const ex=x+ux*scale,ey=y+uy*scale;
      group.append(el('line',{x1:x,y1:y,x2:ex,y2:ey,stroke:color,'stroke-width':isFocus?4:3,'stroke-linecap':'round',opacity:'.92'}));
      const wing=7,back=8;
      group.append(el('polygon',{points:[
        [ex,ey],[ex-ux*back-uy*wing,ey-uy*back+ux*wing],
        [ex-ux*back+uy*wing,ey-uy*back-ux*wing]
      ].map(a=>a.join(',')).join(' '),fill:color,opacity:'.95'}));
    }
    group.append(el('circle',{cx:x,cy:y,r:isFocus?13:11,fill:color,stroke:isFocus?'#f4ffff':'#b9d7e4','stroke-width':isFocus?2.3:1.3}));
    // The source's rotation Z is yaw in radians (validated against opposite kickoff spawns).
    // The white nose indicates facing; the optional colored arrow indicates travel velocity.
    const yaw=car.rotation?.[2];
    if(state.view.facing&&Number.isFinite(yaw)){
      const fx=Math.cos(yaw),fy=-Math.sin(yaw),tip=21,back=10,side=6;
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
  const holder=$('sceneInspector');holder.replaceChildren();
  const f=currentFrame();
  if(!f){const p=document.createElement('p');p.className='muted';p.textContent='No replay data at the current time.';holder.append(p);return;}
  const focus=f.cars[state.focusId],player=playerById(state.focusId);
  const time=document.createElement('div');time.className='scene-time';
  time.textContent='Replay '+fmt(state.time)+' · '+(Number.isFinite(f.secondsRemaining)?('Clock '+fmt(f.secondsRemaining)):'game clock unavailable');
  holder.append(time);
  const grid=document.createElement('div');grid.className='scene-grid';
  const addStat=(label,value,note)=>{
    const d=document.createElement('div');d.className='scene-stat';
    const a=document.createElement('span');a.textContent=label;
    const b=document.createElement('strong');b.textContent=value;
    const c=document.createElement('small');c.textContent=note;
    d.append(a,b,c);grid.append(d);
  };
  const round=n=>Number.isFinite(n)?Math.round(n)+'u':'—';
  addStat('Ball center Z',round(f.ball.z),'Top-down view hides height');
  if(focus){
    addStat('Selected car Z',round(focus.z),'Boost '+(Number.isFinite(focus.boost)?Math.round(focus.boost)+'%':'unknown')+(focus.jumpActive===true?' · jump flag active':''));
    addStat('Ball separation',round(Math.hypot(f.ball.x-focus.x,f.ball.y-focus.y,f.ball.z-focus.z)),
      '3D distance, not just map spacing');
    const opponent=state.replay.players.filter(p=>p.team!==player?.team&&f.cars[p.id])
      .map(p=>({p,car:f.cars[p.id],distance:xyDistance(focus,f.cars[p.id])}))
      .sort((a,b)=>a.distance-b.distance)[0];
    if(opponent)addStat('Nearest opponent',round(opponent.distance),
      opponent.p.name.slice(0,25)+' · car Z '+round(opponent.car.z));
  } else addStat('Selected player','Not tracked','No car observation at this sample');
  holder.append(grid);
  const heading=document.createElement('div');heading.className='touch-heading';heading.textContent='Recent touches (last 3 seconds)';
  holder.append(heading);
  const touches=(state.replay.events||[]).filter(e=>e.type==='touch'&&e.t<=state.time+0.03&&e.t>=state.time-3).slice(-4).reverse();
  if(!touches.length){
    const hint=document.createElement('p');hint.className='touch-empty';hint.textContent='No detected ball contact in this interval.';holder.append(hint);return;
  }
  const list=document.createElement('div');list.className='touch-list';
  for(const touch of touches){
    const who=playerById(touch.playerId),btn=document.createElement('button');btn.className='touch-link';btn.type='button';
    const label=document.createElement('span');label.textContent=(who?.name||'Unidentified player')+(touch.touchKind?' · parser: '+String(touch.touchKind).replace(/_/g,' '):'');
    const ago=document.createElement('small');ago.textContent=Math.max(0,state.time-touch.t).toFixed(2)+'s ago';
    btn.append(label,ago);btn.onclick=()=>{stopPlay();chooseTime(touch.t);};
    list.append(btn);
  }
  holder.append(list);
}
function stopPlay(){
  if(state.timer)clearInterval(state.timer);
  state.timer=null;state.playing=false;$('playBtn').textContent='▶';
  const video=$('gameVideo');if(state.videoUrl&&!video.paused)video.pause();
}
function togglePlay(){
  if(!state.replay)return;
  if(state.playing){stopPlay();return;}
  state.playing=true;$('playBtn').textContent='❚❚';
  const startAt=performance.now(),from=state.time;
  const video=$('gameVideo');
  if(state.videoUrl && state.videoAligned && video.readyState>=1){
    video.playbackRate=state.speed;
    syncVideoToReplay(true);
    const target=state.time+state.videoOffset;
    if(target>=0&&target<video.duration)video.play().catch(()=>{});
  }
  state.timer=setInterval(()=>{
    const next=from+(performance.now()-startAt)/1000*state.speed;
    if(next>=state.replay.duration){chooseTime(state.replay.duration);stopPlay();return;}
    chooseTime(next);
  },50);
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
  $('gameVideo').addEventListener('timeupdate',()=>{
    if(!state.replay||!state.videoUrl||!state.videoAligned||state.playing)return;
    const t=$('gameVideo').currentTime-state.videoOffset;
    if(t>=0&&t<=state.replay.duration&&Math.abs(state.time-t)>0.16)chooseTime(t);
  });
}

function exportReview(){const body=JSON.stringify({replay:{schema:state.replay.schema,title:state.replay.title,mode:state.replay.mode,source:state.replay.source,duration:state.replay.duration},focus:playerById(state.focusId),findings:state.findings.map(f=>({...f,target:state.overrides.get(f.id)||f.target}))},null,2);const url=URL.createObjectURL(new Blob([body],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='rocket-league-review.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function loadFile(file){if(!file)return;if(!file.name.toLowerCase().endsWith('.replay'))return show('Select a Rocket League .replay file.');if(file.size>20*1024*1024)return show('File exceeds 20 MB.');$('uploadStatus').textContent='Processing native replay locally…';try{const r=await fetch('/api/replays',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Replay-Name':file.name},body:file});const body=await r.json();if(!r.ok)throw new Error(body.detail||'Replay parser could not read file.');setReplay(body.replay);show('Replay loaded. Choose your player to start.');}catch(e){$('uploadStatus').textContent=e.message;show(e.message);}}
async function aiReview(){if(!state.replay)return;if(!window.confirm('Send time-sampled car and ball positions (including player IDs/names) to Gemini? This uses your API quota; the raw .replay file is not sent.'))return;
$('aiBtn').disabled=true;$('aiBtn').textContent='Analyzing positions…';try{const r=await fetch('/api/ai-review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({replay:{schema:state.replay.schema,title:state.replay.title,mode:state.replay.mode,duration:state.replay.duration,players:state.replay.players,frames:state.replay.frames.filter((_,i)=>i%Math.max(1,Math.ceil(state.replay.frames.length/240))===0).slice(0,240)},player_id:state.focusId})});const body=await r.json();if(!r.ok)throw new Error(body.detail||'AI analysis failed.');for(const f of body.findings||[])state.findings.push(f);state.selectedId=body.findings?.[0]?.id||state.selectedId;$('flagsValue').textContent=state.findings.length;renderFindings();renderDetail();if(body.findings?.length)chooseTime(body.findings[0].t);show('Gemini findings received. Verify each observation before trusting it.');}catch(e){show(e.message);}finally{$('aiBtn').textContent='✦ Ask Gemini for coaching';$('aiBtn').disabled=false;}}
function addManualMarker(){if(!state.replay)return;const f=currentFrame();const id='manual-'+Date.now();const finding={id,t:f.t,type:'manual',title:'Review this decision',confidence:'unverified',evidence:'Manual marker at the current replay timestamp.',advice:'Inspect the opponent, ball height, timing and recent touches. A marker records a question, not a mistaken decision.',target:null};state.findings.unshift(finding);state.selectedId=id;$('flagsValue').textContent=state.findings.length;renderFindings();renderDetail();renderPitch();}
function wire(){
  const zone=$('uploadZone'),input=$('fileInput');
  zone.onclick=()=>input.click();
  zone.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();input.click();}};
  input.onchange=()=>loadFile(input.files?.[0]);
  zone.ondragover=e=>{e.preventDefault();zone.classList.add('dragging');};
  zone.ondragleave=()=>zone.classList.remove('dragging');
  zone.ondrop=e=>{e.preventDefault();zone.classList.remove('dragging');loadFile(e.dataTransfer.files[0]);};
  $('demoBtn').onclick=()=>{setReplay(demoReplay(),{demo:true});show('Synthetic example loaded; real replays provide measured physics.');};
  $('playerSelect').onchange=e=>{state.focusId=e.target.value;state.overrides.clear();refreshFindings();renderPitch();renderSceneInspector();};
  $('timeRange').oninput=e=>{stopPlay();chooseTime(Number(e.target.value));};
  $('playBtn').onclick=togglePlay;
  $('backBtn').onclick=()=>{stopPlay();chooseTime(state.time-2);};
  $('forwardBtn').onclick=()=>{stopPlay();chooseTime(state.time+2);};
  $('playSpeed').onchange=e=>{
    const speed=Number(e.target.value);state.speed=Number.isFinite(speed)&&speed>0?speed:1;
    if(state.videoUrl&&state.videoAligned)$('gameVideo').playbackRate=state.speed;
    if(state.playing){stopPlay();togglePlay();}
  };
  for(const [id,key] of [['showFacing','facing'],['showTravel','travel'],['showHeights','heights'],['showTrail','trail'],['showBallTrail','ballTrail']]){
    $(id).onchange=e=>{state.view[key]=e.target.checked;renderPitch();};
  }
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
  wireVideo();
}

wire();

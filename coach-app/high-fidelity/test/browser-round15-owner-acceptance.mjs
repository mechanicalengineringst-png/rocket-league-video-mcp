/**
 * Owner-facing Round 15 fail-first real browser acceptance.
 * REQUIRES live local Replay Lab, Chrome, and genuine 2v2 .replay.
 * cd coach-app/high-fidelity
 * set "REPLAY_LAB_REPLAY_PATH=C:\replays\match.replay"
 * set "REPLAY_LAB_URL=http://127.0.0.1:8001"
 * node test/browser-round15-owner-acceptance.mjs
 *
 * This intentionally fails the owner-rejected Round 14.5 layout and halos.
 * Browser test is additional to, not a replacement for, Windows owner review.
 * Explicitly NOT included in generic unit CI and NEVER uses force-click.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';

const here=path.dirname(fileURLToPath(import.meta.url));
const replayPath=process.env.REPLAY_LAB_REPLAY_PATH;
const baseURL=process.env.REPLAY_LAB_URL||'http://127.0.0.1:8000';
const screenshot=path.resolve(here,'../../round15_owner_browser.png');
if(!replayPath||!fs.existsSync(replayPath)||!replayPath.toLowerCase().endsWith('.replay'))
  throw new Error('Set REPLAY_LAB_REPLAY_PATH to an existing original 2v2 .replay. No synthetic fallback.');
const parseTime=x=>{
  const m=String(x).match(/(\d+):(\d\d)(?:\.(\d+))?/);
  return m?Number(m[1])*60+Number(m[2])+Number('0.'+(m[3]||'0')):NaN;
};
const must=(cond,why)=>assert.ok(cond,why);
const compare=(a,b,limit,why)=>
  must(Number.isFinite(a)&&Number.isFinite(b)&&Math.abs(a-b)<=limit,
    why+'; map='+a+' HD='+b+' tolerated '+limit+'s');

const browser=await chromium.launch({
  channel:process.env.REPLAY_LAB_BROWSER_CHANNEL||'chrome',
  headless:true,
  args:['--enable-webgl','--use-angle=swiftshader','--enable-unsafe-swiftshader']
});
const page=await browser.newPage({viewport:{width:1500,height:960}});
const hd=page.frameLocator('#hdInlineFrame');
const jsErrors=[];
page.on('pageerror',e=>jsErrors.push(e.message));
const parentTime=()=>page.locator('#timeRange').evaluate(el=>Number(el.value));
const hdTime=async()=>parseTime(await hd.locator('#currentTime').textContent());
const pass=x=>console.log('PASS: '+x);
let stage='startup';
try{
  await page.goto(baseURL,{waitUntil:'domcontentloaded',timeout:30000});
  stage='first upload without changing modes';
  await page.setInputFiles('#fileInput',replayPath);
  await page.waitForFunction(()=>
    document.getElementById('playerSelect')?.options.length===4 &&
    /Decoded|identities could not be verified/.test(document.getElementById('uploadStatus')?.textContent||''),
    null,{timeout:90000});
  await hd.locator('#statusText').filter({hasText:'High-fidelity stadium loaded'})
    .waitFor({state:'attached',timeout:90000});
  await hd.locator('#viewport canvas').waitFor({state:'visible',timeout:30000});
  pass('first single replay upload initializes HD and 2D');

  stage='dominant HD and small upper-right simultaneous map';
  const rect=await page.evaluate(()=>{
    const box=id=>{
      const el=document.getElementById(id);
      if(!el||getComputedStyle(el).display==='none')return null;
      const r=el.getBoundingClientRect();
      return{x:r.x,y:r.y,w:r.width,h:r.height};
    };
    return{stage:box('pitchShell'),hd:box('hdInlineFrame'),map:box('field')};
  });
  must(rect.stage&&rect.hd&&rect.map,'HD and tactical map must both be visible');
  const shell=rect.stage,canvas=rect.hd,map=rect.map;
  must(canvas.w>=shell.w*.87&&canvas.h>=shell.h*.87,
    'HD player is NOT dominant; giant map or 50/50 split is unacceptable');
  must(map.w<=shell.w*.34&&map.h<=shell.h*.58,
    '2D inset occupies too much of the game; proposed bound needs owner approval');
  must(map.x>=shell.x+shell.w-map.w-40&&map.y<=shell.y+50,
    'Map is not positioned in the upper-right of HD');
  pass('geometric layout candidate: HD dominates, compact simultaneous upper-right 2D');
  
  stage='previously prohibited dotted halos and focus rings';
  const unwanted=await page.locator('#dynamicLayers').evaluate(root=>
    [...root.querySelectorAll('circle')].filter(el=>
      el.hasAttribute('stroke-dasharray')||
      (el.getAttribute('fill')==='none'&&Number(el.getAttribute('r'))>=18))
      .map(el=>({r:el.getAttribute('r'),dash:el.getAttribute('stroke-dasharray')}))
  );
  must(unwanted.length===0,
    'Previously rejected circles/rings still rendered: '+JSON.stringify(unwanted.slice(0,4)));
  pass('banned dynamic rings/dotted halos absent');

  stage='first-upload play and map/HD time coherence';
  const play=page.locator('#playBtn');
  must(await play.isEnabled(),'Play disabled after first replay');
  await play.click();
  const before=await parentTime();
  await page.waitForTimeout(1500);
  const during=await parentTime(),hdDuring=await hdTime();
  must(during>before+.45,'First-upload play did not advance map clock');
  compare(during,hdDuring,.30,'HD did not advance with 2D playback');
  await play.click();
  await page.waitForTimeout(450);
  const paused1=await parentTime(),hdPaused1=await hdTime();
  await page.waitForTimeout(950);
  const paused2=await parentTime(),hdPaused2=await hdTime();
  must(Math.abs(paused2-paused1)<.08,'2D continued moving after pause');
  must(Math.abs(hdPaused2-hdPaused1)<.08,'HD continued playing after parent pause');
  compare(paused2,hdPaused2,.30,'Map/HD differ after pause');
  pass('play starts both, pause stops both, clocks aligned');

  stage='seek and second pause';
  const duration=await page.locator('#timeRange').evaluate(el=>Number(el.max));
  const target=Math.min(duration-4,Math.max(6,duration*.30));
  must(Number.isFinite(target)&&target>=6,'Real replay duration invalid');
  await page.locator('#timeRange').evaluate((el,t)=>{
    el.value=String(t);
    el.dispatchEvent(new Event('input',{bubbles:true}));
  },target);
  await page.waitForTimeout(850);
  compare(await parentTime(),await hdTime(),.30,'HD failed to follow seek');
  await play.click();await page.waitForTimeout(900);
  await play.click();await page.waitForTimeout(500);
  compare(await parentTime(),await hdTime(),.30,'HD clock drifted after seek/replay/pause');
  pass('seek, resume, second pause remain synced');

  stage='in-HD lower-right boost gauge';
  // Named, nonvisual DOM contract; screen evidence and numerical correctness
  // are separate mandatory manual gates described in OWNER_RELEASE_GATES.md.
  const hud=hd.locator('[data-testid="hud-boost"]');
  must(await hud.count()===1&&await hud.isVisible(),
    'No honest in-HD boost gauge (external BOOST text not sufficient)');
  const hudBox=await hud.boundingBox();
  const stageBox=await hd.locator('#viewport canvas').boundingBox();
  must(hudBox&&stageBox&&hudBox.x>stageBox.x+stageBox.width*.55&&
    hudBox.y>stageBox.y+stageBox.height*.55,
    'In-HD boost gauge not positioned in lower-right of replay canvas');
  pass('boost gauge physically inside HD lower-right (source/accuracy still require owner review)');

  stage='mandatory screenshot';
  await page.screenshot({path:screenshot,fullPage:false,animations:'disabled',timeout:15000});
  must(jsErrors.length===0,'Uncaught page errors: '+jsErrors.join('; '));
  console.log('Owner MUST inspect screenshot and camera/readability: '+screenshot);
  console.log('AUTOMATED GATES PASSED. NOT full owner acceptance or validated coaching.');
}catch(error){
  console.error('ROUND15 OWNER GATE FAILED at '+stage+': '+(error.stack||error));
  process.exitCode=1;
}finally{
  await browser.close();
}

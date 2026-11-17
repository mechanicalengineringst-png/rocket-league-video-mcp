/** Native replay acceptance smoke in Chromium, not a JSON schema test.
 * Run: node test/browser-smoke.mjs /absolute/path/to/example.replay
 * CI fetches a public fixture from rlrml/subtr-actor.
 */
import { chromium } from 'playwright';
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';

const fixture=process.argv[2];
if(!fixture || !existsSync(fixture)){
  throw new Error('Pass the path to an existing native Rocket League .replay file');
}
const base=process.env.HD_TEST_URL || 'http://127.0.0.1:4173/static/hd-player/';
const output=path.resolve('test-artifacts');
mkdirSync(output,{recursive:true});
const browser=await chromium.launch({
  headless:true,
  args:[
    '--enable-webgl',
    '--use-angle=swiftshader',
    '--enable-unsafe-swiftshader',
  ],
});
const page=await browser.newPage({viewport:{width:1440,height:900}});
const browserErrors=[];
const assetErrors=[];
const shaderErrors=[];
page.on('pageerror',error=>browserErrors.push(error.message));
page.on('console',entry=>{
  if(entry.type()==='error' && /shader error|webglprogram|fragment shader|vertex shader/i.test(entry.text()))
    shaderErrors.push(entry.text().slice(0,400));
});
page.on('response',response=>{
  if(response.status()>=400 && /\/static\/hd-player\//.test(response.url())){
    assetErrors.push(response.status() + ' ' + response.url());
  }
});
try{
  const nav=await page.goto(base+'?qa=1',{waitUntil:'domcontentloaded',timeout:45000});
  assert.equal(nav?.status(),200,'HD player page must load');
  await page.locator('#fileInput').setInputFiles(path.resolve(fixture));
  await page.locator('#viewport canvas').waitFor({state:'attached',timeout:120000});
  await page.waitForFunction(()=>{
    const status=document.querySelector('#statusText')?.textContent||'';
    return /stadium loaded|assets may be missing|Failed to open replay/i.test(status);
  },{},{timeout:150000});
  const status=await page.locator('#statusText').textContent();
  console.log('HD_REPLAY_STATUS',status);
  const materialQA=await page.evaluate(()=>{
    const qa=window.__rlReplayLabQA;
    if(!qa)return {missing:true};
    // Coordinates are viewport-relative. This scene has a conspicuous dark
    // angular region around the large midfield boost pad.
    const rect=document.getElementById('viewport').getBoundingClientRect();
    return {
      black:qa.hitsAt(rect.left+690,rect.top+278),
      blackEdge:qa.hitsAt(rect.left+735,rect.top+262),
      normalField:qa.hitsAt(rect.left+460,rect.top+278),
      pad:qa.hitsAt(rect.left+591,rect.top+236),
      arenaNames:qa.arenaMeshes().slice(0,15),
    };
  });
  console.log('HD_QA_MATERIAL_RAYCAST',JSON.stringify(materialQA).slice(0,18000));
  await page.screenshot({path:path.join(output,'native-replay-in-browser.png'),fullPage:true});
  assert.match(status,/High-fidelity stadium loaded/,'The GLTF stadium should load, not a fallback floor');
  const players=await page.locator('#playerSelect option').count();
  console.log('HD_REPLAY_PLAYERS',players);
  assert.ok(players>=2,'Real replay should have at least two player tracks');
  const canvas=await page.locator('#viewport canvas').evaluate(c=>({width:c.width,height:c.height}));
  assert.ok(canvas.width>100 && canvas.height>100,'Renderer should mount nonzero canvas');
  await page.locator('[data-camera="orbit"]').click();
  assert.equal(await page.locator('#cameraLabel').textContent(),'ORBIT CAM');
  await page.locator('[data-camera="follow"]').click();
  const label=await page.locator('#cameraLabel').textContent();
  assert.match(label,/BALL CAM|CAR CAM|REAR LOOK|CAMERA UNKNOWN/);
  const evidence=await page.locator('#cameraEvidence').textContent();
  assert.ok(evidence.length>25,'Recorded camera evidence must be visible');
  console.log('HD_CAMERA_EVIDENCE',evidence);
  await page.locator('#ballCamSelect').selectOption('car');
  assert.equal(await page.locator('#cameraLabel').textContent(),'CAR CAM');
  await page.locator('#ballCamSelect').selectOption('ball');
  assert.equal(await page.locator('#cameraLabel').textContent(),'BALL CAM');
  await page.locator('#ballCamSelect').selectOption('recorded');
  assert.equal(await page.locator('#cameraSource').textContent(),
    /Native camera events/i.test(evidence)?'REPLAY TELEMETRY':'NO RECORDED SWITCH');
  // Camera label alone could be UI theater: assert the actual replay engine
  // switched its CameraManager state using decoded native toggle events.
  const firstOff=page.locator('#cameraEventList button.off').first();
  if(await firstOff.count()) {
    await firstOff.click(); await page.waitForTimeout(320);
    const off=await page.evaluate(()=>window.__rlReplayLabQA?.effectiveCameraState());
    console.log('HD_REAL_CAMERA_OFF_STATE',JSON.stringify(off));
    assert.equal(off.viewMode,'follow');
    assert.equal(off.pluginBallCam,false,'Native Ball Cam OFF should reach real camera plugin');
    const firstOn=page.locator('#cameraEventList button').filter({hasText:'Ball Cam on'}).first();
    await firstOn.click(); await page.waitForTimeout(320);
    const on=await page.evaluate(()=>window.__rlReplayLabQA?.effectiveCameraState());
    console.log('HD_REAL_CAMERA_ON_STATE',JSON.stringify(on));
    assert.equal(on.pluginBallCam,true,'Native Ball Cam ON should reach real camera plugin');
  }
  await page.locator('#replayLookToggle').uncheck();
  await page.locator('#replayLookToggle').check();
  await page.locator('#qualitySelect').selectOption('sharp');
  await page.locator('#qualitySelect').selectOption('balanced');
  const decorState=()=>page.evaluate(()=>
    window.__rlReplayLabQA?.arenaMeshes()?.find(x=>x.name==='Field_STD_Floor_Hex002')?.visible
  );
  assert.equal(await decorState(),false,'Clean field hides only confirmed black/blue decal');
  await page.locator('#fieldDecorSelect').selectOption('original');
  assert.equal(await decorState(),true,'Original stadium artwork remains recoverable');
  await page.locator('#fieldDecorSelect').selectOption('clean');
  assert.equal(await decorState(),false);
  await page.locator('#fxStyle').selectOption('original');
  await page.locator('#fxStyle').selectOption('soft');
  await page.locator('#speedSelect').selectOption('2');
  await page.locator('#seek').evaluate(element => { element.value='2'; element.dispatchEvent(new Event('input',{bubbles:true})); });
  await page.locator('#playBtn').click();
  await page.waitForTimeout(400);
  const after=await page.locator('#currentTime').textContent();
  console.log('HD_REPLAY_TIME',after);
  assert.ok(after && after!=='00:00.00','Timeline should seek and advance');
  assert.deepEqual(assetErrors,[],'Model/wasm asset requests must return HTTP 2xx');
  assert.deepEqual(browserErrors,[],'No unhandled JavaScript errors during replay');
  assert.deepEqual(shaderErrors,[],'Soft VFX patches must not produce shader compile errors');
  console.log('HD_REPLAY_BROWSER_SMOKE_PASS');
}catch(error){
  console.error('HD_REPLAY_BROWSER_SMOKE_FAIL',error);
  console.error('PAGE_ERRORS',browserErrors);
  console.error('ASSET_ERRORS',assetErrors);
  console.error('SHADER_ERRORS',shaderErrors);
  try{await page.screenshot({path:path.join(output,'native-replay-error.png'),fullPage:true})}catch{}
  throw error;
}finally{
  await browser.close();
}

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
page.on('pageerror',error=>browserErrors.push(error.message));
page.on('response',response=>{
  if(response.status()>=400 && /\/static\/hd-player\//.test(response.url())){
    assetErrors.push(response.status() + ' ' + response.url());
  }
});
try{
  const nav=await page.goto(base,{waitUntil:'domcontentloaded',timeout:45000});
  assert.equal(nav?.status(),200,'HD player page must load');
  await page.locator('#fileInput').setInputFiles(path.resolve(fixture));
  await page.locator('#viewport canvas').waitFor({state:'attached',timeout:120000});
  await page.waitForFunction(()=>{
    const status=document.querySelector('#statusText')?.textContent||'';
    return /stadium loaded|assets may be missing|Failed to open replay/i.test(status);
  },{},{timeout:150000});
  const status=await page.locator('#statusText').textContent();
  console.log('HD_REPLAY_STATUS',status);
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
  assert.equal(await page.locator('#cameraLabel').textContent(),'PLAYER CAM');
  await page.locator('#speedSelect').selectOption('2');
  await page.locator('#seek').evaluate(element => { element.value='2'; element.dispatchEvent(new Event('input',{bubbles:true})); });
  await page.locator('#playBtn').click();
  await page.waitForTimeout(400);
  const after=await page.locator('#currentTime').textContent();
  console.log('HD_REPLAY_TIME',after);
  assert.ok(after && after!=='00:00.00','Timeline should seek and advance');
  assert.deepEqual(assetErrors,[],'Model/wasm asset requests must return HTTP 2xx');
  assert.deepEqual(browserErrors,[],'No unhandled JavaScript errors during replay');
  console.log('HD_REPLAY_BROWSER_SMOKE_PASS');
}catch(error){
  console.error('HD_REPLAY_BROWSER_SMOKE_FAIL',error);
  console.error('PAGE_ERRORS',browserErrors);
  console.error('ASSET_ERRORS',assetErrors);
  try{await page.screenshot({path:path.join(output,'native-replay-error.png'),fullPage:true})}catch{}
  throw error;
}finally{
  await browser.close();
}

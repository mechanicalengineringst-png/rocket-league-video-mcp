import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const replayPath = path.resolve(__dirname, '../../fixtures/replays/real_match_2v2.replay');
const screenshotPath = path.resolve(__dirname, '../../../round12_live_coaching_browser_verified.png');

console.log('Testing Replay Lab Round 12 end-to-end against http://127.0.0.1:8085...');
const browser = await chromium.launch({
  channel: 'chrome',
  headless: true,
  args: ['--enable-webgl', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
});

const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

try {
  // 1. Load application
  await page.goto('http://127.0.0.1:8085/', { waitUntil: 'networkidle', timeout: 30000 });
  console.log('Page loaded successfully.');

  // 2. Verify split view architecture & absence of retired 3D
  const hasRetiredVp = await page.$('#viewport3d');
  const hasRetiredControls = await page.$('#controls3d');
  const hasRetiredTab = await page.$('#viewTab3d');
  if (hasRetiredVp || hasRetiredControls || hasRetiredTab) {
    throw new Error('Retired geometric 3D viewer elements were found on page!');
  }
  console.log('Verified: Retired 3D viewer is completely absent.');

  const hdFrame = await page.$('#hdInlineFrame');
  const fieldSvg = await page.$('#field');
  if (!hdFrame || !fieldSvg) {
    throw new Error('Split view components (#hdInlineFrame or #field) missing!');
  }
  console.log('Verified: Split view (HD + Map) is active.');

  // 3. Test Companion Probe
  await page.click('#companionPanel summary');
  await page.click('#companionProbeBtn');
  await page.waitForTimeout(500);
  const badgeText = await page.textContent('#companionBadge');
  console.log('Companion status badge:', badgeText);

  // 4. Upload genuine replay file
  console.log('Uploading real_match_2v2.replay...');
  await page.setInputFiles('#fileInput', replayPath);

  // 5. Wait for replay parsing & playerSelect population
  await page.waitForFunction(() => {
    const sel = document.getElementById('playerSelect');
    return sel && sel.options.length > 1;
  }, { timeout: 30000 });

  // 6. Select focus player
  await page.selectOption('#playerSelect', { index: 1 });
  console.log('Player selected. Waiting for review bundle / candidate lessons...');

  // 7. Wait for coaching episodes to mount
  await page.waitForFunction(() => {
    const sel = document.getElementById('episodeSelect');
    return sel && sel.options.length > 0;
  }, { timeout: 30000 });

  const episodeCount = await page.evaluate(() => {
    const sel = document.getElementById('episodeSelect');
    return sel ? sel.options.length : 0;
  });
  if (episodeCount < 1) throw new Error('No actual source-backed coaching moments mounted.');
  console.log(`Successfully mounted ${episodeCount} coaching review moments!`);

  // 7b. A present iframe does NOT prove HD rendering; /hd can return an
  // informative HTML setup placeholder when the local Vite bundle is absent.
  // Require actual HD canvas AND successful multi-mesh stadium asset load.
  // This test still cannot verify visual accuracy or native game camera.
  const hd = page.frameLocator('#hdInlineFrame');
  await hd.locator('#viewport canvas').waitFor({ state: 'visible', timeout: 60000 });
  await hd.locator('#statusText').filter({hasText:'High-fidelity stadium loaded'})
    .waitFor({state:'attached',timeout:90000});
  const quality = await hd.locator('#fpsHint').textContent();
  const meshes = Number(/3D meshes (\d+)/.exec(quality||'')?.[1]||0);
  if (!(meshes > 1)) {
    throw new Error('HD canvas exists but multi-mesh stadium assets are not confirmed loaded.');
  }
  console.log(`HD viewer rendered WebGL canvas with ${meshes} meshes; visual fidelity remains unverified.`);

  // 7c. The new Decision Lens is a genuine interaction, not a static badge.
  // The selected coaching node pins a recorded t0 snapshot. The actual
  // +2s recording must be hidden until the tester explicitly reveals it.
  const lensPanel=page.locator('#decisionLensPanel');
  await lensPanel.waitFor({state:'visible'});
  const pinned=await lensPanel.evaluate(el=>el.open);
  if (!pinned) throw new Error('Selecting a real coaching moment failed to open Decision Lens.');
  const before=await page.locator('#lensMetrics .lens-metric').count();
  if (before < 6) throw new Error('Decision-time source metrics were not rendered.');
  const futureInitially=await page.locator('#lensMetrics').textContent();
  if ((futureInitially||'').includes('Actual Δ focus')) {
    throw new Error('Post-decision distances leaked before explicit reveal.');
  }
  await page.click('#lensRevealBtn');
  const after=await page.locator('#lensMetrics').textContent();
  if (!(after||'').includes('Actual Δ focus')) {
    throw new Error('Actual recorded follow-through did not appear after reveal.');
  }
  const ghostLabels=await page.locator('#decisionLensOverlay text').allTextContents();
  if (!ghostLabels.includes('+2s actual')) {
    throw new Error('Recorded +2s ghost markers did not appear on the tactical map.');
  }
  await page.waitForTimeout(400);
  console.log('Text before loop click:', await page.textContent('#lensLoopBtn'));
  await page.click('#lensLoopBtn', { force: true });
  await page.waitForTimeout(200);
  const loopState = await page.textContent('#lensLoopBtn');
  console.log('Text after loop click:', loopState);
  if (!loopState?.includes('Stop scene loop')) {
    throw new Error('Bounded Decision Lens playback loop did not start. Current text: ' + loopState);
  }
  console.log('Verified lens loop button switched to Stop scene loop.');
  await page.waitForTimeout(200);
  await page.click('#lensLoopBtn', { force: true });
  console.log('Verified: t0 metrics, explicit future reveal and synchronized scene replay loop.');

  // 8. Test Tester Feedback functionality
  const usefulBtn = await page.waitForSelector('.feedback-btn.useful', { timeout: 10000 });
  await usefulBtn.click({ force: true });
  console.log('Clicked "Useful & Accurate" feedback button.');

  await page.fill('#feedbackNoteInput', 'Verified challenge timing and recovery spacing in 2v2 formation.');
  await page.click('#saveFeedbackNoteBtn', { force: true });
  console.log('Saved tester feedback note.');

  // 9. Jump to decision point
  await page.click('#jumpDecisionBtn', { force: true });
  // The iframe renderer is a separately decoded replay. Confirm it received
  // parent seek data; DOM changes alone do not prove rendered pose/timestamp.
  await page.waitForTimeout(800);
  const embeddedTime = await hd.locator('#currentTime').textContent();
  console.log('HD camera clock after coaching seek:', embeddedTime);
  if (!embeddedTime || /^00:00\.00$/.test(embeddedTime)) {
    throw new Error('HD iframe clock stayed at initial zero; split synchronization not established.');
  }
  console.log('Parent seek forwarded to independently decoded HD player (pixel-level parity still unverified).');

  // 10. Capture visual evidence
  const artifactDir = 'C:\\Users\\Sam Meyer\\.gemini\\antigravity\\brain\\399a61b4-2479-44d8-affe-6a4c541cdaf3';
  await page.screenshot({ path: screenshotPath });
  console.log('Captured screenshot evidence at:', screenshotPath);
  try {
    fs.copyFileSync(screenshotPath, path.join(artifactDir, 'round12_live_coaching_browser_verified.png'));
    // Also capture HD viewer canvas directly
    const hdCanvas = await hd.locator('#viewport canvas').elementHandle();
    if (hdCanvas) {
      const hdScreenPath = path.resolve(__dirname, '../../../round12_hd_vehicle_grounded_verified.png');
      await hdCanvas.screenshot({ path: hdScreenPath });
      fs.copyFileSync(hdScreenPath, path.join(artifactDir, 'round12_hd_vehicle_grounded_verified.png'));
      console.log('Captured HD canvas screenshot at:', hdScreenPath);
    }
  } catch (copyErr) {
    console.warn('Could not copy to artifact dir:', copyErr.message);
  }

  console.log('Round 12 browser workflow completed successfully!');
} finally {
  await browser.close();
}

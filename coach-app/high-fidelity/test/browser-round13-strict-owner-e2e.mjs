/**
 * Round 13 strict REAL browser acceptance. NOT run in CI without an owner-supplied
 * .replay, a live localhost app, and installed Chrome/Playwright.
 *
 *   set REPLAY_LAB_REPLAY_PATH=C:\path\match.replay
 *   cd coach-app\high-fidelity
 *   node test/browser-round13-strict-owner-e2e.mjs
 *
 * No native-game commands and NO external model inference. An optional provider
 * must be assessed separately with explicit configuration and per-request consent.
 * This test FAILS on disabled/non-completing user journeys instead of logging
 * their existence as success. Screenshots remain on the local owner's machine.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const replayPath = process.env.REPLAY_LAB_REPLAY_PATH ||
  path.resolve(here, '../../fixtures/replays/real_match_2v2.replay');
const baseURL = process.env.REPLAY_LAB_URL || 'http://127.0.0.1:8000';
const screenshotPath = process.env.REPLAY_LAB_SCREENSHOT ||
  path.resolve(here, '../../round13_strict_owner_local.png');

if (!fs.existsSync(replayPath)) {
  throw new Error('Real 2v2 replay unavailable. Set REPLAY_LAB_REPLAY_PATH to a local .replay. No synthetic fallback.');
}
if (!replayPath.toLowerCase().endsWith('.replay')) {
  throw new Error('REPLAY_LAB_REPLAY_PATH must be an original .replay file.');
}
function requireTrue(condition, reason) {
  if (!condition) throw new Error(reason);
}
function seconds(text) {
  const value = String(text ?? '').trim();
  const match = value.match(/(\d+):(\d\d)(?:\.(\d+))?/);
  if (!match) return Number.NaN;
  return Number(match[1]) * 60 + Number(match[2]) +
    Number('0.' + (match[3] || '0'));
}
const browser = await chromium.launch({
  channel: process.env.REPLAY_LAB_BROWSER_CHANNEL || 'chrome',
  headless: true,
  args: ['--enable-webgl', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
});
const page = await browser.newPage({viewport: {width: 1500, height: 960}, acceptDownloads: true});
const errors = [];
page.on('pageerror', err => errors.push(err.message));
const check = name => console.log('PASS: ' + name);

try {
  await page.goto(baseURL, {waitUntil: 'domcontentloaded', timeout: 30000});
  requireTrue(await page.locator('#hdInlineFrame').count() === 1, 'No HD embedded iframe.');
  requireTrue(await page.locator('#field').count() === 1, 'No tactical map.');
  requireTrue(await page.locator('#viewport3d').count() === 0, 'Retired geometry-based viewer returned.');
  check('HD + Map entrypoint');

  await page.setInputFiles('#fileInput', replayPath);
  await page.waitForFunction(() => document.getElementById('playerSelect')?.options.length === 4,
    null, {timeout: 60000});
  const upload = await page.locator('#uploadStatus').textContent();
  requireTrue(/Decoded|identities could not be verified/.test(upload || ''),
    'Native replay upload did not show decoded telemetry.');
  // A test harness selects a roster slot; the OWNER must still verify identity.
  await page.locator('#playerSelect').selectOption({index: 0});
  await page.waitForFunction(() =>
    document.getElementById('episodeSelect')?.options.length > 0,
    null, {timeout: 120000});
  const count = await page.locator('#episodeSelect option').count();
  requireTrue(count >= 1, 'The real replay produced no automatic shortlist.');
  check('real .replay upload, four-person roster, automatic coaching shortlist');

  await page.locator('#decisionLensPanel').waitFor({state: 'visible', timeout: 30000});
  await page.waitForFunction(() => document.getElementById('decisionLensPanel')?.open === true,
    null, {timeout: 15000});
  const before = await page.locator('#lensMetrics').textContent();
  requireTrue(!String(before).includes('Actual Δ focus'),
    'Actual follow-through leaked before user reveal.');
  await page.locator('#lensRevealBtn').click();
  await page.waitForFunction(() =>
    document.getElementById('lensMetrics')?.textContent?.includes('Actual Δ focus'),
    null, {timeout: 10000});
  check('Decision Lens Stage A/recorded +2s reveal');

  // Start blind evaluation on an actual primary episode, not a detached demo.
  await page.locator('#blindReviewPanel').evaluate(el => {el.open = true;});
  await page.waitForFunction(() =>
    document.getElementById('blindStartBtn')?.disabled === false,
    null, {timeout: 15000});
  await page.locator('#blindPriorExposure').selectOption('seen');
  await page.locator('#blindStartBtn').click();
  requireTrue(await page.locator('#blindPreStage').isVisible(),
    'Blind Stage A did not appear.');
  requireTrue(await page.locator('#modelCoachPanel').getAttribute('hidden') !== null,
    'AI coaching remained exposed in blind Stage A.');
  requireTrue(await page.locator('#experimentalReportPanel').getAttribute('hidden') !== null,
    'Experimental tactical report remained exposed in blind Stage A.');
  await page.locator('#blindPreAction').selectOption('not_enough_information');
  await page.locator('#blindPreCoverage').selectOption('unclear');
  await page.locator('#blindPreConfidence').selectOption('3');
  await page.locator('#blindLockBtn').click();
  requireTrue(await page.locator('#blindPostStage').isVisible(),
    'Blind Stage B is not available after locking Stage A.');
  await page.locator('#blindRevealBtn').click();
  await page.waitForFunction(() => 
    document.getElementById('blindReviewStatus')?.textContent?.includes('explicitly revealed'),
    null, {timeout: 10000});
  await page.locator('#blindPostDecision').selectOption('undetermined');
  await page.locator('#blindPostExecution').selectOption('undetermined');
  await page.locator('#blindPostModel').selectOption('not_tested');
  await page.locator('#blindFinishBtn').click();
  await page.waitForFunction(() =>
    document.getElementById('blindReportSummary')?.textContent?.includes('1 completed'),
    null, {timeout: 10000});
  const trial = await page.evaluate(() => window.blindReviewUI?.report());
  assert.equal(trial?.schema, 'ReplayLabBlindReviewReportV0');
  assert.equal(trial?.summary?.completed_reviews, 1);
  const [exported] = await Promise.all([
    page.waitForEvent('download', {timeout: 15000}),
    page.locator('#blindExportBtn').click()
  ]);
  requireTrue(exported.suggestedFilename().endsWith('.json'), 'Blind export was not a JSON download.');
  check('blind Stage A mask, lock, outcome, complete, anonymized JSON export');

  // This model readiness probe does not contact any AI provider.
  await page.locator('#modelCoachPanel').evaluate(el => {el.open = true;});
  const readinessResponse = await page.request.get(
    new URL('/api/coach/model-readiness', baseURL).toString()
  );
  requireTrue(readinessResponse.ok(), 'Actual model-readiness API failed.');
  const readiness = await readinessResponse.json();
  assert.equal(readiness.schema, 'CoachModelReadinessV0');
  assert.equal(readiness.outbound_request_made, false);
  requireTrue(await page.locator('#modelCoachRunBtn').isDisabled(),
    'AI model button was enabled without per-request consent.');
  check('model readiness truthful, no external provider request, explicit consent gate');

  // Run the broader match report and FAIL if it returns no usable cards.
  await page.locator('#experimentalReportPanel').evaluate(el => {el.open = true;});
  const reportBtn = page.locator('#experimentalReportBtn');
  requireTrue(await reportBtn.isEnabled(), 'Experimental report cannot be started.');
  await reportBtn.click();
  await page.waitForFunction(() => {
    const s = document.getElementById('experimentalReportStatus')?.textContent || '';
    return s.includes('experimental source-checked findings') || s.includes('unavailable');
  }, null, {timeout: 120000});
  const experimentalStatus = await page.locator('#experimentalReportStatus').textContent();
  requireTrue(!String(experimentalStatus).includes('unavailable'),
    'The experimental situation-aware report failed its validation.');
  const findings = await page.locator('#experimentalReportResults .experimental-report-card').count();
  requireTrue(findings > 0,
    'The report completed but yielded zero inspectable findings: record a coverage gap.');
  const outcomes = page.locator('#experimentalReportResults details.experimental-report-outcome');
  for (let i = 0; i < await outcomes.count(); i++) {
    requireTrue(!(await outcomes.nth(i).evaluate(el => el.open)),
      'A Stage B retrospective drawer opened automatically.');
  }
  check('real local experimental situation report, visible findings, outcome hidden');

  // Claude Round 13 V2 is a DISTINCT local report; require its REAL endpoint
  // to complete and its stage B drawers to remain collapsed by default.
  // This may take over a minute for one full-length real replay.
  await page.locator('#reportV2Panel').evaluate(el => {el.open = true;});
  requireTrue(await page.locator('#reportV2Btn').isEnabled(),
    'V2 report is not available with a confirmed real 2v2 selection.');
  await page.locator('#reportV2Btn').click();
  await page.waitForFunction(() => {
    const status=document.getElementById('reportV2Status')?.textContent||'';
    return status.startsWith('V2:') || status.includes('unavailable');
  }, null, {timeout: 240000});
  const v2Status=await page.locator('#reportV2Status').textContent();
  requireTrue(String(v2Status).startsWith('V2:'),
    'V2 did not return a verified actual local report.');
  requireTrue(await page.locator('#reportV2Results .experimental-report-section').count()===3,
    'V2 did not render habits, turning points, and source-checked decisions.');
  requireTrue(await page.locator('#reportV2Results .experimental-report-card').count()>0,
    'V2 did not produce any inspectable real replay moments.');
  const v2Later=page.locator('#reportV2Results details.experimental-report-outcome');
  for(let i=0;i<await v2Later.count();i++){
    requireTrue(!(await v2Later.nth(i).evaluate(el=>el.open)),
      'V2 exposed the recorded action and outcome without separate reveal.');
  }
  const v2Visible=await page.locator('#reportV2Results').textContent();
  requireTrue(!String(v2Visible).includes('definitely made a terrible mistake'),
    'V2 inherited old mistake verdict language into its visible report.');
  check('Round 13 V2 real local habits, turning points, decision reads, Stage B hidden');

  // A true overlooked moment requires a fresh MANUAL pin, not an auto-pin.
  const mid = await page.locator('#timeRange').evaluate(el => {
    const lo = Number(el.min), hi = Number(el.max);
    const target = Math.min(hi - 0.6, Math.max(lo + 9, lo + (hi - lo) / 2));
    el.value = String(target);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    return target;
  });
  requireTrue(Number.isFinite(mid), 'Could not choose a manual replay timestamp.');
  await page.locator('#lensPinBtn').click();
  requireTrue(await page.locator('#lensManualReviewBtn').isEnabled(),
    'Manual review is unavailable after explicitly pinning a valid replay time.');
  await page.locator('#lensManualReviewBtn').click();
  await page.waitForFunction(() => {
    const s = document.getElementById('lensManualReviewStatus')?.textContent || '';
    return s.includes('Manual source-backed episode created') ||
      s.includes('could not be safely reconstructed');
  }, null, {timeout: 120000});
  const manualStatus = await page.locator('#lensManualReviewStatus').textContent();
  requireTrue(String(manualStatus).includes('Manual source-backed episode created'),
    'Manual review failed to create a verified local episode.');
  check('manually pinned previously unselected moment produced local verified lesson');

  await page.locator('#modelCoachSpatialPanel').evaluate(el => {el.open = true;});
  const spatialBtn = page.locator('#modelCoachSpatialBtn');
  requireTrue(await spatialBtn.isEnabled(), 'Geometry inspector has no primary episode.');
  await spatialBtn.click();
  await page.waitForFunction(() => {
    const s = document.getElementById('modelCoachSpatialStatus')?.textContent || '';
    return s.includes('Recorded coordinate relations') ||
      s.includes('lacks fresh enough telemetry') ||
      s.includes('could not be verified');
  }, null, {timeout: 45000});
  const spatial = await page.locator('#modelCoachSpatialStatus').textContent();
  requireTrue(!String(spatial).includes('could not be verified'),
    'Local geometric source contract failed.');
  check('real local spatial endpoint completed without model');

  const hd = page.frameLocator('#hdInlineFrame');
  await hd.locator('#viewport canvas').waitFor({state: 'visible', timeout: 60000});
  await hd.locator('#statusText').filter({hasText: 'High-fidelity stadium loaded'})
    .waitFor({state: 'attached', timeout: 90000});
  const canvasSize = await hd.locator('#viewport canvas').evaluate(c => ({
    width: c.width, height: c.height
  }));
  requireTrue(canvasSize.width > 300 && canvasSize.height > 200,
    'HD canvas is zero-sized or unexpectedly small.');
  await page.locator('#lensDecisionBtn').click();
  await page.waitForTimeout(1000);
  const hdClock = seconds(await hd.locator('#currentTime').textContent());
  const parentClock = await page.locator('#timeRange').evaluate(el => Number(el.value));
  requireTrue(Number.isFinite(hdClock) && Number.isFinite(parentClock) &&
    Math.abs(hdClock - parentClock) < 0.15,
    'HD/2D timestamp mismatch on decision seek; parent=' +
    parentClock + ' HD=' + hdClock);
  check('actual embedded HD clock tracks map decision within 150ms');

  const overlays = hd.locator('#tactical3dToggle');
  requireTrue(!(await overlays.isChecked()), '3D overlays are not opt-in by default.');
  await overlays.check();
  requireTrue(await overlays.isChecked(), '3D overlays cannot be enabled.');
  await hd.locator('button[data-camera="director"]').click();
  const audio = hd.locator('#audioToggleBtn');
  const offLabel = await audio.textContent();
  await audio.click();
  const onLabel = await audio.textContent();
  requireTrue(offLabel !== onLabel, 'Audio toggle did not change state.');
  await page.locator('#playSpeed').selectOption('0.1');
  await page.waitForTimeout(250);
  check('Round 13 overlays, broadcast director, audio toggle, 0.1x control');

  await page.screenshot({path: screenshotPath, fullPage: true});
  requireTrue(errors.length === 0, 'Page emitted uncaught errors: ' + errors.join('; '));
  console.log('STRICT OWNER TEST COMPLETE (no real LLM/native game tests performed).');
  console.log('Local screenshot saved at: ' + screenshotPath);
} catch (err) {
  console.error('STRICT OWNER TEST FAILED: ' + (err?.stack || err));
  process.exitCode = 1;
} finally {
  await browser.close();
}

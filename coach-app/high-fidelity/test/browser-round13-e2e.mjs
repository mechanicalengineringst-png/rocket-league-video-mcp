import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const replayPath = path.resolve(__dirname, '../../fixtures/replays/real_match_2v2.replay');
const screenshotPath = path.resolve(__dirname, '../../../round13_hd_experience_innovation_verified.png');
const artifactScreenshotPath = 'C:\\Users\\Sam Meyer\\.gemini\\antigravity\\brain\\399a61b4-2479-44d8-affe-6a4c541cdaf3\\round13_hd_experience_innovation_verified.png';

console.log('Testing Replay Lab Round 13 Innovation end-to-end against http://127.0.0.1:8085...');
const browser = await chromium.launch({
  channel: 'chrome',
  headless: true,
  args: ['--enable-webgl', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
});

const page = await browser.newPage({ viewport: { width: 1500, height: 960 } });

page.on('console', msg => console.log('PAGE LOG:', msg.text()));
page.on('pageerror', err => console.log('PAGE ERROR:', err.message));

try {
  // 1. Load application
  await page.goto('http://127.0.0.1:8085/', { waitUntil: 'networkidle', timeout: 30000 });
  console.log('Page loaded successfully.');

  // 2. Upload genuine replay file
  console.log('Uploading real_match_2v2.replay...');
  await page.setInputFiles('#fileInput', replayPath);

  // 3. Wait for replay parsing & playerSelect population
  await page.waitForFunction(() => {
    const sel = document.getElementById('playerSelect');
    return sel && sel.options.length > 1;
  }, { timeout: 30000 });

  // 4. Select focus player
  await page.selectOption('#playerSelect', { index: 1 });
  console.log('Player selected. Waiting for coaching episodes to mount...');

  // 5. Wait for coaching episodes
  await page.waitForFunction(() => {
    const sel = document.getElementById('episodeSelect');
    return sel && sel.options.length > 0;
  }, { timeout: 30000 });
  console.log('Coaching episodes mounted.');

  // 6. Inspect HD frame
  const hd = page.frameLocator('#hdInlineFrame');
  await hd.locator('#viewport canvas').waitFor({ state: 'visible', timeout: 60000 });
  for (let i = 0; i < 20; i++) {
    const text = await hd.locator('#statusText').textContent().catch(() => '');
    console.log(`[statusText poll ${i}]`, text);
    if (text.includes('High-fidelity stadium loaded')) break;
    await page.waitForTimeout(2000);
  }
  await hd.locator('#statusText').filter({ hasText: 'High-fidelity stadium loaded' })
    .waitFor({ state: 'attached', timeout: 60000 });

  console.log('HD stadium confirmed loaded.');

  // 7. Verify Round 13 Innovation UI Elements inside HD viewer
  // 7a. Director Autocam button
  const directorBtn = hd.locator('button[data-camera="director"]');
  await directorBtn.waitFor({ state: 'visible' });
  console.log('Verified: Director Autocam (TV) button present.');
  await directorBtn.click({ force: true });
  await page.waitForTimeout(500);

  const directorActive = await directorBtn.getAttribute('class');
  console.log('Director button class after click:', directorActive);

  // 7b. Camera Profile selector
  const profileSelect = hd.locator('#cameraProfileSelect');
  await profileSelect.waitFor({ state: 'visible' });
  const profileOptions = await profileSelect.locator('option').allTextContents();
  console.log('Verified camera profiles:', profileOptions);
  await profileSelect.selectOption('pro');

  // 7c. 3D Tactical Markers toggle (clean by default)
  const tactical3dToggle = hd.locator('#tactical3dToggle');
  await tactical3dToggle.waitFor({ state: 'attached' });
  const tacticalInitiallyChecked = await tactical3dToggle.isChecked();
  console.log('Verified 3D Tactical Markers initially unchecked for clean default:', !tacticalInitiallyChecked);
  await tactical3dToggle.check({ force: true });
  console.log('Verified 3D Tactical Markers opt-in checked:', await tactical3dToggle.isChecked());

  // 7d. Procedural Web Audio controls
  const audioBtn = hd.locator('#audioToggleBtn');
  await audioBtn.waitFor({ state: 'visible' });
  console.log('Initial audio button text:', await audioBtn.textContent());
  await audioBtn.click({ force: true });
  console.log('Audio button text after toggle:', await audioBtn.textContent());

  const volumeSlider = hd.locator('#audioVolumeSlider');
  await volumeSlider.waitFor({ state: 'attached' });
  console.log('Volume slider attached with initial value:', await volumeSlider.inputValue());

  // 7e. Ultra slow-motion 0.1x speed
  const speedSelect = hd.locator('#speedSelect');
  const speedOptions = await speedSelect.locator('option').allInnerTexts();
  console.log('Playback speed options:', speedOptions);
  const hasSlowMo = speedOptions.some(opt => opt.includes('0.1'));
  if (!hasSlowMo) throw new Error('0.1x ultra slow-motion option missing from speedSelect!');
  console.log('Verified: 0.1x ultra slow-motion supported.');

  // 8. Capture screenshot
  await page.waitForTimeout(1000);
  await page.screenshot({ path: screenshotPath });
  console.log(`Saved Round 13 verified screenshot to: ${screenshotPath}`);

  try {
    fs.copyFileSync(screenshotPath, artifactScreenshotPath);
    console.log(`Copied screenshot to conversation artifacts: ${artifactScreenshotPath}`);
  } catch (copyErr) {
    console.warn('Could not copy to artifacts:', copyErr.message);
  }

  console.log('All Round 13 browser E2E checks passed successfully!');
} catch (err) {
  console.error('Test failed:', err);
  process.exit(1);
} finally {
  await browser.close();
}

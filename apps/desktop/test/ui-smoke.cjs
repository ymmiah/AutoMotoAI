// Browser regressions against the real local server and a stubbed native launcher.
// No provider keys or model requests. PYTHON selects the installed engine interpreter.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { mkdtempSync, readFileSync, mkdirSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { randomBytes } = require('node:crypto');
const root = path.resolve(__dirname, '../../..');
const data = mkdtempSync(path.join(tmpdir(), 'automoto-ui-'));
const output = path.resolve(process.env.UI_SHOTS || path.join(data, 'screenshots'));
mkdirSync(output, { recursive: true });
const token = randomBytes(32).toString('hex');
const base = 'http://127.0.0.1:8876';
const server = spawn(process.env.PYTHON || 'python', ['-m', 'automoto', 'serve', '--no-browser', '--port', '8876'], {
  cwd: root,
  env: { ...process.env, AUTOMOTO_DATA_DIR: data, AUTOMOTO_LAUNCH_TOKEN: token, AUTOMOTO_SANDBOX: 'local' },
  stdio: ['ignore', 'pipe', 'pipe'],
});
let log = '';
server.stdout.on('data', d => { log += d; });
server.stderr.on('data', d => { log += d; });
const delay = ms => new Promise(r => setTimeout(r, ms));
let browser;
(async () => {
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw new Error(`UI server exited: ${log}`);
    if (await fetch(`${base}/api/health`).then(r => r.ok).catch(() => false)) break;
    if (i === 99) throw new Error(`UI server never started: ${log}`);
    await delay(100);
  }
  browser = await chromium.launch({ ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}), args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: 'dark', reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(`${base}/?launch=${token}`);
  await page.locator('.hero h2').waitFor();
  assert.match(await page.locator('.hero h2').innerText(), /A little idea/);
  assert.match(await page.locator('.hero p').innerText(), /don't pick the tools/);
  assert.equal((await page.locator('#modeSeg [data-mode="agent"]').innerText()).trim(), 'Assistant');
  assert.equal(await page.locator('.chip').count(), 8);
  assert.equal(await page.locator('#msgs').evaluate(el => el.scrollTop), 0, 'home must start at its heading');
  await page.locator('#msgs').evaluate(el => { el.scrollTop = el.scrollHeight; });
  assert.equal(await page.locator('#jumpLatest').isVisible(), false, 'starting ideas must not offer a latest reply');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  assert.equal(await page.locator('.chip').count(), 3);
  await page.getByRole('button', { name: 'Make slides' }).click();
  assert.match(await page.locator('#composerInput').inputValue(), /PowerPoint/);
  await page.locator('#composerInput').fill('Keep this draft while I check settings');
  await page.locator('.nav [data-page="settings"]').click();
  await page.locator('.set-nav').waitFor();
  assert.match(await page.locator('[data-set-panel="assistant"]').innerText(), /You write the request/);
  assert.equal(await page.locator('[data-set-panel="assistant"] a[href="#/tools"]').count(), 0, 'the assistant section must not list tools');
  await page.locator('.set-nav [data-set="offline"]').click();
  await page.waitForFunction(() => /Running|Installed|Not installed|Could not check/.test(document.querySelector('#offlineBody')?.innerText || ''));
  assert.equal(await page.locator('.ai-status').isVisible(), true);
  assert.equal(await page.locator('#offlineSw').isVisible(), true);
  await page.screenshot({ path: path.join(output, 'settings-offline.png') });
  await page.locator('.set-nav [data-set="look"]').click();
  await page.locator('#themeSeg').waitFor();
  await page.screenshot({ path: path.join(output, 'settings-appearance.png') });
  await page.locator('.set-nav [data-set="more"]').click();
  assert.equal(await page.locator('[data-set-panel="more"] a[href="#/tools"]').isVisible(), true);
  await page.locator('.set-nav [data-set="assistant"]').click();
  await page.locator('#newChat').click();
  await page.waitForFunction(() => document.querySelector('#composerInput')?.value === 'Keep this draft while I check settings');
  assert.equal(await page.locator('#composerInput').inputValue(), 'Keep this draft while I check settings');
  await page.locator('#commandLaunch').click();
  await page.keyboard.press('Shift+Tab');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'paletteInput', 'palette must contain focus');
  await page.keyboard.press('Control+n');
  assert.equal(await page.locator('#palette').isVisible(), true, 'background shortcuts must not navigate');
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'commandLaunch', 'closing returns focus');
  // A real conversation exercises modal cancellation and per-conversation drafts.
  const conv = await page.evaluate(async () => (await fetch('/api/conversations', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: 'chat' }),
  })).json());
  await page.evaluate(id => { location.hash = `#/c/${id}`; }, conv.id);
  await page.locator('#titleBtn').waitFor();
  assert.equal(await page.locator('#composerInput').inputValue(), '');
  await page.locator('#composerInput').fill('A separate conversation draft');
  await page.locator('#titleBtn').click();
  const modal = page.locator('#modal');
  await modal.locator('input').waitFor();
  await page.keyboard.press('Shift+Tab');
  assert.equal(await page.evaluate(() => document.activeElement.closest('#modal') !== null), true);
  await page.keyboard.press('Escape');
  assert.equal(await modal.isVisible(), false);
  await page.locator('#newChat').click();
  await page.waitForFunction(() => document.querySelector('#composerInput')?.value === 'Keep this draft while I check settings');
  assert.equal(await page.locator('#composerInput').inputValue(), 'Keep this draft while I check settings');
  await page.locator('#composerInput').fill('');
  await page.screenshot({ path: path.join(output, 'workspace-dark.png') });
  // Visual Studio uses the genuine Python scene renderer, not a mock screenshot.
  await page.locator('.nav [data-page="visual"]').click();
  await page.locator('#vsPreview').waitFor();
  await page.waitForFunction(() => document.querySelector('#vsPreview')?.naturalWidth > 0);
  assert.equal(await page.locator('#vsStage').getAttribute('aria-busy'), 'false');
  assert.equal(await page.locator('#vsElement option').count() > 4, true);
  await page.screenshot({ path: path.join(output, 'visual-studio-workflow.png') });
  // New layer stack: selecting, locking and visibility must affect actual exports.
  assert.ok(await page.locator('#vsLayers [data-layer-key="group:stage0"]').count() >= 3,
    'workflow group layer controls must exist');
  await page.locator('#vsLayers [data-layer-key="group:stage0"][data-layer-act="select"]').click();
  await page.locator('#vsLayers [data-layer-key="group:stage0"][data-layer-act="lock"]').click();
  assert.equal(await page.locator('#vsDelete').isDisabled(), true, 'locked layer forbids deletion');
  await page.locator('#vsLayers [data-layer-key="group:stage0"][data-layer-act="lock"]').click();
  assert.equal(await page.locator('#vsDelete').isDisabled(), false, 'unlock restores editing');
  await page.locator('#vsLayers [data-layer-key="group:stage0"][data-layer-act="visibility"]').click();
  assert.equal(await page.locator('#vsLayers [data-layer-key="group:stage0"][data-layer-act="visibility"]').getAttribute('aria-pressed'), 'true');
  await page.locator('#vsLayers [data-layer-key="group:stage0"][data-layer-act="visibility"]').click();
  // Drag the native corner grip and verify the editable source geometry changes.
  const widthBefore = Number(await page.locator('#vsProperties [data-key="w"]').inputValue());
  const grip = await page.locator('.vs-resize-handle').boundingBox();
  assert.ok(grip, 'selected grouped card must expose a resize handle');
  await page.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2);
  await page.mouse.down();
  await page.mouse.move(grip.x + grip.width / 2 + 24, grip.y + grip.height / 2 + 13, { steps: 6 });
  await page.mouse.up();
  const widthAfter = Number(await page.locator('#vsProperties [data-key="w"]').inputValue());
  assert.ok(widthAfter > widthBefore, 'drag-resize must update native element width');
  await page.screenshot({ path: path.join(output, 'visual-studio-layers-resize.png') });
  // A sequence timeline exposes group keyframes and renders the selected frame.
  await page.locator('#vsFormat').selectOption('gif');
  await page.locator('#vsEffect').selectOption('sequence');
  assert.equal(await page.locator('#vsTimeline').isVisible(), true);
  assert.equal(await page.locator('#vsTracks input[type="range"]').count(), 3);
  await page.locator('#vsPlayhead').evaluate(input => {
    input.value = '75';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.waitForFunction(() => /Structural checks passed/.test(document.querySelector('#vsStatus')?.textContent || '') &&
    document.querySelector('#vsStage')?.getAttribute('aria-busy') === 'false');
  await page.locator('#vsTimeline').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(output, 'visual-studio-timeline.png') });
  await page.locator('#vsAddText').click();
  await page.locator('#vsProperties textarea[data-key="text"]').fill('Exact source copy');
  await page.locator('#vsProperties textarea[data-key="text"]').press('Tab');
  // Deliberately create unreadable white text, then inspect, propose and
  // explicitly accept a reversible, non-destructive contrast repair.
  await page.locator('#vsProperties [data-key="colour"]').fill('#ffffff');
  await page.locator('#vsProperties [data-key="colour"]').press('Tab');
  await page.locator('#vsInspect').click();
  assert.match(await page.locator('#vsFindings').innerText(), /contrast/);
  await page.locator('#vsSuggest').click();
  await page.locator('#vsApply:not([disabled])').waitFor();
  assert.match(await page.locator('#vsFindings').innerText(), /proposed field adjustment/);
  await page.locator('#vsApply').click();
  assert.match(await page.locator('#vsFindings').innerText(), /Suggestions applied/);
  await page.waitForFunction(() => document.querySelector('#vsStage')?.getAttribute('aria-busy') === 'false');
  await page.screenshot({ path: path.join(output, 'visual-studio-repair.png') });
  await page.locator('#vsSave').click();
  await page.waitForFunction(() => document.querySelectorAll('#vsDraft option').length > 1);
  await page.locator('#vsFormat').selectOption('gif');
  assert.equal(await page.locator('#vsFrames').isVisible(), true);
  assert.equal(await page.locator('#vsEffect').inputValue(), 'sequence', 'timeline setting must survive draft save');
  await page.locator('#vsFrames').fill('10');
  // File format and editability are independent: a GIF can keep native layers.
  await page.locator('#vsOutputMode').selectOption('layered');
  await page.locator('#vsExport').click();
  await page.locator('#vsOutput:not([hidden])').waitFor();
  assert.match(await page.locator('#vsOutput').innerText(), /Download GIF/);
  assert.match(await page.locator('#vsOutput').innerText(), /Download editable layers/);
  await page.waitForFunction(() => document.querySelector('#vsStage')?.getAttribute('aria-busy') === 'false');
  await page.screenshot({ path: path.join(output, 'visual-studio-gif.png') });
  // Every supported picture has an Edit layers action in Files.
  await page.locator('.nav [data-page="files"]').click();
  await page.locator('[data-dir="artifacts"]').first().click();
  await page.locator('[data-dir="artifacts/visual-studio"]').first().click();
  await page.locator('[data-studio-image$=".gif"]').first().click();
  await page.locator('#vsOutputMode').waitFor();
  await page.waitForFunction(() => document.querySelector('#vsPreview')?.naturalWidth > 0 &&
    document.querySelector('#vsStage')?.getAttribute('aria-busy') === 'false');
  assert.equal(await page.locator('#vsOutputMode').inputValue(), 'layered',
    'opening an exported image must restore an editable Visual Studio project');
  assert.ok(await page.locator('#vsElement option').count() > 3,
    'native generated GIF must reopen its independently editable source layers');
  await page.screenshot({ path: path.join(output, 'visual-studio-reopen-layers.png') });
  await page.locator('#newChat').click();
  await page.locator('.hero h2').waitFor();
  await page.locator('#quickTheme').click();
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  await page.screenshot({ path: path.join(output, 'workspace-light.png') });
  await page.evaluate(() => { document.documentElement.dataset.chrome = 'custom'; window.__automotoChromeBoot(); });
  await page.locator('#amChrome').waitFor();
  assert.equal(await page.getByRole('button', { name: 'Minimize' }).isVisible(), true);
  assert.equal(await page.getByRole('button', { name: 'Maximize' }).isVisible(), true);
  assert.equal(await page.getByRole('button', { name: 'Close' }).isVisible(), true);
  await page.getByRole('button', { name: 'Menu', exact: true }).click();
  await page.getByRole('menuitem', { name: /Quit/ }).waitFor();
  await page.keyboard.press('ArrowDown');
  assert.equal(await page.evaluate(() => document.activeElement?.dataset?.action), 'reload');
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('data-chrome')), 'menu');
  assert.equal(await page.locator('#amAppMenu').isVisible(), false);
  await page.screenshot({ path: path.join(output, 'chrome-home-light.png') });
  await page.locator('#quickTheme').click();
  await page.screenshot({ path: path.join(output, 'chrome-home-dark.png') });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'custom chrome must not overflow');
  await page.evaluate(() => { delete document.documentElement.dataset.chrome; });
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.reload();
    await page.locator('.hero h2').waitFor();
    assert.match(await page.locator('.hero p').innerText(), /don't pick the tools/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `no horizontal overflow at ${width}px`);
    assert.equal(await page.locator('#msgs').evaluate(el => el.scrollTop), 0);
    await page.screenshot({ path: path.join(output, `workspace-${width}.png`) });
  }
  // Serve the bundled launcher through a browser route; native commands are mocked.
  await page.setViewportSize({ width: 1200, height: 1050 });
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
  await page.route(`${base}/launcher/**`, route => {
    const file = path.basename(new URL(route.request().url()).pathname);
    route.fulfill({ body: readFileSync(path.join(root, 'apps/desktop/dist', file)), contentType: file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'text/html' });
  });
  await page.addInitScript(() => {
    window.nativeInfo = { version: '5.6.0-beta.5', channel: 'Beta', windows: true, engine: null, server: '', signed_in: false };
    window.__TAURI__ = { core: { invoke: async command => {
      if (command === 'app_info') return structuredClone(window.nativeInfo);
      if (command === 'install_engine') { window.nativeInfo.engine = { version: '5.6.0b5', how: 'installed', outdated: false }; return { started: true }; }
      if (command === 'start_local') return { missing: true };
      return {};
    } } };
  });
  await page.goto(`${base}/launcher/index.html?home=1`);
  await page.locator('#installBtn:not([hidden])').waitFor();
  await page.locator('#username').fill('unsent-user');
  await page.locator('#password').fill('unsent-password');
  await page.locator('#showPassword').click();
  assert.equal(await page.locator('#password').getAttribute('type'), 'text');
  await page.locator('#showPassword').click();
  await page.screenshot({ path: path.join(output, 'launcher-dark.png') });
  await page.locator('#installBtn').click();
  await page.locator('#refreshBtn').click();
  assert.equal(await page.locator('#installBtn').isVisible(), false, 'installer status must refresh');
  assert.equal(await page.locator('#username').inputValue(), 'unsent-user', 'refresh must preserve credentials draft');
  await page.locator('#localBtn').click();
  assert.equal(await page.locator('#installBtn').isVisible(), true, 'missing engine must restore installation help');
  await page.emulateMedia({ colorScheme: 'light' });
  await page.screenshot({ path: path.join(output, 'launcher-light.png') });
  await page.setViewportSize({ width: 1024, height: 670 });
  const localAction = await page.locator('#localBtn').boundingBox();
  await page.screenshot({ path: path.join(output, 'launcher-laptop.png') });
  assert.ok(localAction.y + localAction.height <= 670, `local mode must be visible on a short laptop window: ${JSON.stringify(localAction)}`);
  await page.evaluate(() => { document.documentElement.dataset.chrome = 'custom'; window.__automotoChromeBoot(); });
  await page.setViewportSize({ width: 1280, height: 820 });
  await page.locator('#amChrome').waitFor();
  const framed = await page.locator('#localBtn').boundingBox();
  assert.ok(framed && framed.y >= 40 && framed.y + framed.height <= 820, `launcher actions sit below the caption: ${JSON.stringify(framed)}`);
  await page.getByRole('button', { name: 'Menu', exact: true }).click();
  await page.getByRole('menuitem', { name: /Sign out/ }).waitFor();
  await page.keyboard.press('Escape');
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.screenshot({ path: path.join(output, 'chrome-launcher-dark.png') });
  await page.emulateMedia({ colorScheme: 'light' });
  await page.screenshot({ path: path.join(output, 'chrome-launcher-light.png') });
  await page.evaluate(() => { delete document.documentElement.dataset.chrome; });
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, 'launcher-mobile.png'), fullPage: true });
  assert.deepEqual(errors, [], 'no browser script errors');
  console.log('UI smoke passed: ideas, draft recovery, focus containment, themes, responsive layouts and engine refresh.');
})().catch(e => { console.error(e); process.exitCode = 1; }).finally(async () => {
  await browser?.close();
  server.kill();
  rmSync(data, { recursive: true, force: true });
});

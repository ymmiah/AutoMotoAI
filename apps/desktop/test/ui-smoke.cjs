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
  assert.equal(await page.locator('.chip').count(), 8);
  assert.equal(await page.locator('#msgs').evaluate(el => el.scrollTop), 0, 'home must start at its heading');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  assert.equal(await page.locator('.chip').count(), 3);
  await page.getByRole('button', { name: 'Make slides' }).click();
  assert.match(await page.locator('#composerInput').inputValue(), /PowerPoint/);
  await page.locator('#composerInput').fill('Keep this draft while I check settings');
  await page.locator('.nav [data-page="settings"]').click();
  await page.locator('.page').waitFor();
  await page.locator('#newChat').click();
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
  assert.equal(await page.locator('#composerInput').inputValue(), 'Keep this draft while I check settings');
  await page.locator('#composerInput').fill('');
  await page.screenshot({ path: path.join(output, 'workspace-dark.png') });
  await page.locator('#quickTheme').click();
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  await page.screenshot({ path: path.join(output, 'workspace-light.png') });
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.reload();
    await page.locator('.hero h2').waitFor();
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

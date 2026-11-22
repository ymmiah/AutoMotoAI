// Shared copy button (automoto/web/static/copy.js): one accessible control used app-wide.
// Real local server, no provider keys. PYTHON selects the installed engine interpreter.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { randomBytes } = require('node:crypto');
const root = path.resolve(__dirname, '../../..');
const data = mkdtempSync(path.join(tmpdir(), 'automoto-copy-'));
const token = randomBytes(32).toString('hex');
const port = 8877, base = `http://127.0.0.1:${port}`;
const py = process.env.PYTHON || 'python';
const env = { ...process.env, AUTOMOTO_DATA_DIR: data, AUTOMOTO_LAUNCH_TOKEN: token, AUTOMOTO_SANDBOX: 'local', AUTOMOTO_RATE_LIMIT: '10000' };
const seed = spawnSync(py, ['-c', `
from automoto.conversations import Conversations
c = Conversations(); conv = c.create("Copy test")
c.add_message(conv["id"], "user", "How do I run it?")
c.add_message(conv["id"], "assistant", "Run this:\\n\\n\`\`\`bash\\ncd project\\npython -m pytest -q\\n\`\`\`\\n\\nThen \`npm start\`.")
print(conv["id"])`], { cwd: root, env, encoding: 'utf8' });
assert.equal(seed.status, 0, seed.stderr);
const convId = seed.stdout.trim();
const server = spawn(py, ['-m', 'automoto', 'serve', '--no-browser', '--port', String(port)], { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'] });
let log = '';
server.stdout.on('data', d => { log += d; }); server.stderr.on('data', d => { log += d; });
const delay = ms => new Promise(r => setTimeout(r, ms));
const frames = page => page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
let browser;
(async () => {
  for (let i = 0; i < 150; i++) {
    if (server.exitCode !== null) throw new Error(`server exited: ${log}`);
    if (await fetch(`${base}/api/health`).then(r => r.ok).catch(() => false)) break;
    if (i === 149) throw new Error(`server never started: ${log}`);
    await delay(100);
  }
  browser = await chromium.launch({ ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}), args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: 'dark', reducedMotion: 'reduce', permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await ctx.newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await page.goto(`${base}/?launch=${token}`);
  await page.locator('.hero h2').waitFor();
  assert.equal(await page.locator('.hero .copy-btn').count(), 0, 'the home screen has no code, so no copy buttons');

  // Chat code block: one button in the code header, keyboard operable, announced, exact text.
  await page.evaluate(id => { location.hash = '#/c/' + id; }, convId);
  await page.locator('.md .code').first().waitFor();
  await frames(page);
  assert.equal(await page.locator('.md .code .copy-btn').count(), 1, 'one copy button per chat code block');
  assert.equal(await page.locator('.md .code pre .copy-anchor').count(), 0, 'no second button inside chat code');
  const chatBtn = page.locator('.md .code .copy-btn');
  assert.equal(await chatBtn.getAttribute('aria-label'), 'Copy code');
  assert.equal(await chatBtn.getAttribute('type'), 'button');
  await chatBtn.focus(); await page.keyboard.press('Enter'); await delay(200);
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), 'cd project\npython -m pytest -q');
  assert.equal(await page.locator('#copyLive').textContent(), 'Copied');
  assert.equal(await page.locator('#copyLive').getAttribute('aria-live'), 'polite');
  assert.equal(await chatBtn.getAttribute('data-copy-state'), 'copied');
  assert.equal(await page.evaluate(() => document.activeElement?.classList.contains('copy-btn')), true, 'focus stays on the button');
  await delay(1700);
  assert.equal(await chatBtn.getAttribute('data-copy-state'), null, 'the Copied state clears');
  await page.keyboard.press('Space'); await delay(200);
  assert.equal(await chatBtn.getAttribute('data-copy-state'), 'copied', 'Space also copies');

  // Any <pre> anywhere gets one sticky button; secrets, sensitive areas and empty boxes do not.
  const r = await page.evaluate(async () => {
    const host = document.createElement('div'); host.id = 'copyFixture'; host.style.cssText = 'position:fixed;left:0;top:0;width:600px;z-index:99';
    const tok = 'ghp_' + 'Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2';
    host.innerHTML = '<pre id="c-out" style="max-height:60px;overflow:auto">line 1\nline 2\nline 3\nline 4\nline 5\nline 6</pre>' +
      '<pre id="c-secret">TOKEN=' + tok + '</pre><pre id="c-pem">-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----</pre>' +
      '<div data-sensitive><pre id="c-sens">hidden value</pre></div><pre id="c-empty"></pre>' +
      '<p><code id="c-path" data-copy="" data-copy-label="file path">C:\\Users\\me\\Documents\\AutoMoto\\notes.md</code></p>' +
      '<p><code id="c-cmd" data-copy="npm test" data-copy-label="command">Run tests</code></p>' +
      '<textarea id="c-ta">x</textarea>';
    document.body.append(host);
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
    const btnIn = id => document.querySelector('#' + id + ' > .copy-anchor > .copy-btn');
    const shown = b => !!b && !b.hidden && b.getBoundingClientRect().width > 0;
    const out = document.querySelector('#c-out');
    const before = btnIn('c-out').getBoundingClientRect().top;
    out.scrollTop = 40; await new Promise(r => requestAnimationFrame(r));
    const after = btnIn('c-out').getBoundingClientRect().top;
    return {
      out: shown(btnIn('c-out')), outCount: out.querySelectorAll('.copy-btn').length, sticky: Math.abs(before - after) < 1,
      outText: out.textContent.startsWith('line 1'), label: btnIn('c-out').getAttribute('aria-label'),
      secret: shown(btnIn('c-secret')), pem: shown(btnIn('c-pem')), sens: !!document.querySelector('#c-sens .copy-btn'),
      empty: shown(btnIn('c-empty')), path: shown(document.querySelector('#c-path + .copy-inline')),
      pathLabel: document.querySelector('#c-path + .copy-inline')?.getAttribute('aria-label'),
      cmd: shown(document.querySelector('#c-cmd + .copy-inline')), ta: !!document.querySelector('#c-ta + .copy-btn, #c-ta .copy-btn'),
    };
  });
  assert.deepEqual(r, { out: true, outCount: 1, sticky: true, outText: true, label: 'Copy code', secret: false, pem: false, sens: false,
    empty: false, path: true, pathLabel: 'Copy file path', cmd: true, ta: false });
  await page.locator('#c-path + .copy-inline').click(); await delay(150);
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), 'C:\\Users\\me\\Documents\\AutoMoto\\notes.md');
  await page.locator('#c-cmd + .copy-inline').click(); await delay(150);
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), 'npm test', 'data-copy value wins over the visible label');
  await page.locator('#c-out > .copy-anchor > .copy-btn').click(); await delay(150);
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), 'line 1\nline 2\nline 3\nline 4\nline 5\nline 6');
  // Replacing the text (as live logs do) keeps exactly one working button; a secret appearing later hides it.
  await page.evaluate(() => { document.querySelector('#c-empty').textContent = 'echo hello'; });
  await frames(page);
  assert.equal(await page.locator('#c-empty .copy-btn:not([hidden])').count(), 1);
  await page.evaluate(() => { document.querySelector('#c-empty').innerHTML += '\nmore'; });
  await frames(page);
  await page.locator('#c-empty > .copy-anchor > .copy-btn').click(); await delay(150);
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), 'echo hello\nmore', 'a button re-parsed from HTML is rebuilt and works');
  await page.evaluate(() => { document.querySelector('#c-empty').textContent = 'key=sk-' + 'abcdefghijklmnopqrstuvwxyz0123'; });
  await frames(page);
  assert.equal(await page.locator('#c-empty .copy-btn:not([hidden])').count(), 0, 'secret text hides the button');
  await page.evaluate(() => document.querySelector('#copyFixture').remove());

  // Tools page: the workspace path has a copy button.
  await page.evaluate(() => { location.hash = '#/tools'; });
  await page.locator('#tlList code[data-copy]').waitFor();
  await frames(page);
  assert.equal(await page.locator('#tlList code[data-copy] + .copy-inline').count(), 1);

  // Phone: buttons inside code boxes are at least 44px for touch.
  const phone = await browser.newContext({ storageState: await ctx.storageState(), viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, colorScheme: 'dark', reducedMotion: 'reduce' });
  const pp = await phone.newPage();
  await pp.goto(base + '/'); await pp.locator('.hero h2').waitFor();
  await pp.evaluate(() => { const p = document.createElement('pre'); p.id = 'p1'; p.textContent = 'npm run dev'; document.body.append(p); });
  await frames(pp);
  const size = await pp.locator('#p1 .copy-btn').evaluate(b => [b.offsetWidth, b.offsetHeight]);
  assert.ok(size[0] >= 44 && size[1] >= 44, 'touch target ' + size);
  await phone.close();
  assert.deepEqual(errors, []);
  console.log('copy buttons: ok');
})().catch(e => { console.error(e); process.exitCode = 1; }).finally(async () => {
  await browser?.close(); server.kill(); rmSync(data, { recursive: true, force: true });
});

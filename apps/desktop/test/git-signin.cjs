// Connect GitHub or GitLab (V46-V48 plan, PR 2): the guided sign-in steps in Developer Studio > Tools.
// Real local server with no network access needed: a malformed token is refused by the engine before any
// request leaves the computer. Checks the field is masked and cleared, nothing reaches browser storage,
// old GitHub/GitLab entries in the BYOK tab keys are dropped, and the phone layout has no sideways scroll.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { randomBytes } = require('node:crypto');
const root = path.resolve(__dirname, '../../..');
const data = mkdtempSync(path.join(tmpdir(), 'automoto-signin-'));
const token = randomBytes(32).toString('hex');
const port = 8878, base = `http://127.0.0.1:${port}`;
const py = process.env.PYTHON || 'python';
const env = { ...process.env, AUTOMOTO_DATA_DIR: data, AUTOMOTO_LAUNCH_TOKEN: token, AUTOMOTO_SANDBOX: 'local', AUTOMOTO_RATE_LIMIT: '10000' };
for (const k of ['GITHUB_TOKEN', 'GH_TOKEN', 'GITLAB_TOKEN', 'GITLAB_URL', 'AUTOMOTO_GITHUB_CLIENT_ID', 'AUTOMOTO_GITLAB_CLIENT_ID']) delete env[k];
const server = spawn(py, ['-m', 'automoto', 'serve', '--no-browser', '--port', String(port)], { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'] });
let log = '';
server.stdout.on('data', d => { log += d; }); server.stderr.on('data', d => { log += d; });
const delay = ms => new Promise(r => setTimeout(r, ms));
const FAKE = 'github_pat_tooShort' + 'X'.repeat(8);
let browser;
async function openAccount(page, compact) {
  await page.evaluate(() => document.querySelector('.nav [data-page="developer"]').click());
  await page.locator('#dsxRoot').waitFor();
  if (compact) await page.locator('#dsxNavTools').click(); else await page.locator('#dsxTools').click();
  await page.locator('.dsx-card[data-tool="account"]').click();
  await page.locator('#dsxToolDetail .dsa .dsb-steps').waitFor();
}
(async () => {
  for (let i = 0; i < 150; i++) {
    if (server.exitCode !== null) throw new Error(`server exited: ${log}`);
    if (await fetch(`${base}/api/health`).then(r => r.ok).catch(() => false)) break;
    if (i === 149) throw new Error(`server never started: ${log}`);
    await delay(100);
  }
  browser = await chromium.launch({ ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}), args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: 'dark', reducedMotion: 'reduce' });
  // An old tab may still hold GitHub/GitLab tokens in the BYOK keys: they must be dropped on load.
  await ctx.addInitScript(() => { try { if (window.top === window && !sessionStorage.getItem('seeded')) { sessionStorage.setItem('seeded', '1'); sessionStorage.setItem('automoto_keys', JSON.stringify({ github: 'ghp_old', gitlab: 'glpat-old', openai: 'sk-keep' })); } } catch { /* sandboxed frames have no storage */ } });
  const page = await ctx.newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.accept());
  const bodies = []; page.on('response', async r => { if (r.url().includes('/account/')) bodies.push(await r.text().catch(() => '')); });
  await page.goto(`${base}/?launch=${token}`);
  await page.locator('.hero h2').waitFor();
  const keysNow = JSON.parse(await page.evaluate(() => sessionStorage.getItem('automoto_keys')));
  assert.deepEqual(keysNow, { openai: 'sk-keep' }, 'GitHub/GitLab tokens are removed from browser storage');

  await openAccount(page, false);
  const steps = page.locator('.dsa .dsb-step');
  assert.equal(await steps.count(), 3, 'three guided steps');
  assert.equal(await page.locator('.dsa-seg .btn[aria-pressed="true"]').textContent(), 'GitHub');
  const href = await page.locator('a.dsa-open').getAttribute('href');
  assert.match(href, /^https:\/\/github\.com\/settings\/personal-access-tokens\/new\?/);
  assert.match(href, /contents=write/); assert.doesNotMatch(href, /workflows|administration|secrets/i);
  assert.equal(await page.locator('a.dsa-open').getAttribute('rel'), 'noopener noreferrer');
  assert.equal(await page.locator('.dsa-url code').getAttribute('data-copy'), '', 'the token page address has a copy button');
  await page.waitForFunction(() => document.querySelector('.dsa-url .copy-inline'));
  const input = page.locator('.dsa-token');
  assert.equal(await input.getAttribute('type'), 'password');
  assert.equal(await input.getAttribute('autocomplete'), 'off');
  assert.equal(await input.getAttribute('data-sensitive'), '');
  assert.equal(await page.locator('.dsa-paste .copy-inline, .dsa-paste .copy-btn').count(), 0, 'never a copy button on the token field');

  // GitLab shows the server picker and the least-privilege scopes.
  await page.locator('.dsa-seg .btn', { hasText: 'GitLab' }).click();
  await page.locator('.dsa-host select').waitFor();
  assert.match(await page.locator('a.dsa-open').getAttribute('href'), /^https:\/\/gitlab\.com\/-\/user_settings\/personal_access_tokens\?.*scopes=read_user%2Cread_api%2Cwrite_repository/);
  await page.locator('.dsa-add > summary').click();
  await page.locator('.dsa-add input').fill('http://10.0.0.5');
  await page.locator('.dsa-add .btn').click();
  await page.locator('.dsa-alert.bad').waitFor();
  assert.match(await page.locator('.dsa-alert.bad').textContent(), /https/);
  await page.locator('.dsa-seg .btn', { hasText: 'GitHub' }).click();

  // A malformed token: refused by the engine before anything is sent; the field is cleared at once.
  const consent = page.locator('.dsa-consent input');
  if (await consent.count()) await consent.check();
  await page.locator('.dsa-token').fill(FAKE);
  const cleared = await page.evaluate(() => { const i = document.querySelector('.dsa-token'); document.querySelector('.dsa-paste .btn.primary').click(); return i.value === ''; });
  assert.ok(cleared, 'the token field is emptied the moment Connect is pressed');
  await page.locator('.dsa-alert.bad').waitFor();
  assert.match(await page.locator('.dsa-alert.bad').textContent(), /doesn't look like a GitHub token/);
  const storage = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
  assert.ok(!storage.includes('tooShort'), 'nothing about the token is kept in browser storage');
  assert.ok(!bodies.some(b => b.includes('tooShort')), 'no engine response echoes the token');
  assert.ok(!(await page.content()).includes('tooShort'), 'the token is not left in the page');

  // Phone: same steps, no sideways scrolling, 40px+ provider buttons.
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'dark', reducedMotion: 'reduce', hasTouch: true, isMobile: true });
  const p2 = await phone.newPage(); p2.on('pageerror', e => errors.push(e.message));
  const launch = await (await fetch(`${base}/api/session/launch`, { method: 'POST', headers: { 'X-AutoMoto-Token': token, 'Content-Type': 'application/json' }, body: '{}' })).json().catch(() => null);
  await p2.goto(launch?.url || `${base}/?launch=${token}`);
  await p2.locator('.nav [data-page="developer"]').waitFor({ state: 'attached' });
  await openAccount(p2, true);
  const wide = await p2.evaluate(() => document.querySelector('#dsxToolDetail').scrollWidth - document.querySelector('#dsxToolDetail').clientWidth);
  assert.ok(wide <= 1, `no sideways scroll on phone (${wide}px)`);
  const h = await p2.locator('.dsa-seg .btn').first().evaluate(b => b.getBoundingClientRect().height);
  assert.ok(h >= 40, `provider buttons are easy to tap (${h}px)`);
  assert.deepEqual(errors, []);
  console.log('git sign-in UI ok');
})().catch(e => { console.error(e); process.exitCode = 1; }).finally(async () => {
  await browser?.close().catch(() => {});
  server.kill();
  await delay(300);
  try { rmSync(data, { recursive: true, force: true }); } catch { /* Windows may still hold files */ }
});

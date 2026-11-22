// Share to GitHub or GitLab (V46-V48 plan, PR 3): the guided steps in Developer Studio > Tools and the
// "share it yourself" fallback. Real local server, no network: without a connected account the card asks
// you to connect, and "Share it myself" saves a secret-scanned .patch with per-OS steps, every command
// with the shared copy button. Also checks the phone layout has no sideways scroll.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn, execFileSync } = require('node:child_process');
const { mkdtempSync, rmSync, mkdirSync, writeFileSync, readdirSync, readFileSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { randomBytes } = require('node:crypto');
const root = path.resolve(__dirname, '../../..');
const data = mkdtempSync(path.join(tmpdir(), 'automoto-share-'));
const ws = path.join(data, 'ws'); const patches = path.join(data, 'patches');
const proj = path.join(ws, 'demo');
mkdirSync(proj, { recursive: true });
const git = (...a) => execFileSync('git', ['-c', 'user.name=T', '-c', 'user.email=t@example.com', '-c', 'init.defaultBranch=main', ...a], { cwd: proj });
git('init', '-q');
writeFileSync(path.join(proj, 'README.md'), '# Demo\n');
git('add', '-A'); git('commit', '-q', '-m', 'Start <img src=x onerror=alert(1)>');
const token = randomBytes(32).toString('hex');
const port = 8879, base = `http://127.0.0.1:${port}`;
const py = process.env.PYTHON || 'python';
const env = { ...process.env, AUTOMOTO_DATA_DIR: data, AUTOMOTO_LAUNCH_TOKEN: token, AUTOMOTO_SANDBOX: 'local', AUTOMOTO_RATE_LIMIT: '10000', AUTOMOTO_WORKSPACE: ws, AUTOMOTO_PATCH_DIR: patches };
for (const k of ['GITHUB_TOKEN', 'GH_TOKEN', 'GITLAB_TOKEN', 'GITLAB_URL']) delete env[k];
const server = spawn(py, ['-m', 'automoto', 'serve', '--no-browser', '--port', String(port)], { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'] });
let log = '';
server.stdout.on('data', d => { log += d; }); server.stderr.on('data', d => { log += d; });
const delay = ms => new Promise(r => setTimeout(r, ms));
let browser;
let H = null;
async function openShare(page, compact) {
  await page.evaluate(() => document.querySelector('.nav [data-page="developer"]').click());
  await page.locator('#dsxRoot').waitFor();
  await page.evaluate(p => { document.querySelector('#dsPath').value = p; document.querySelector('#dsOpen').click(); }, proj);
  await page.waitForFunction(() => /demo/.test(document.querySelector('#dsxProjectName')?.textContent || ''));
  await page.keyboard.press('Escape');
  if (compact) await page.locator('#dsxNavTools').click(); else await page.locator('#dsxTools').click();
  await page.locator('.dsx-card[data-tool="share"]').click();
  await page.locator('#dsxToolDetail .dss .dsb-steps').waitFor();
}
(async () => {
  for (let i = 0; i < 150; i++) {
    if (server.exitCode !== null) throw new Error(`server exited: ${log}`);
    if (await fetch(`${base}/api/health`).then(r => r.ok).catch(() => false)) break;
    if (i === 149) throw new Error(`server never started: ${log}`);
    await delay(100);
  }
  H = { 'X-AutoMoto-Token': JSON.parse(readFileSync(path.join(data, 'session.json'), 'utf8')).token, 'Content-Type': 'application/json' };
  const t = await fetch(`${base}/api/developer/studio/trust`, { method: 'POST', headers: H, body: JSON.stringify({ project: proj, trusted: true, confirmed: true }) });
  assert.equal(t.status, 200, await t.text());
  browser = await chromium.launch({ ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}), args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: 'dark', reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.accept());
  await page.goto(`${base}/?launch=${token}`);
  await page.locator('.hero h2').waitFor();
  await openShare(page, false);
  assert.equal(await page.locator('.dss .dsb-step').count(), 4, 'four guided steps');
  assert.match(await page.locator('.dss .dsb-step').first().textContent(), /Connect your account/);
  assert.equal(await page.locator('.dss .dsb-step .btn', { hasText: 'Connect GitHub or GitLab' }).count(), 1);
  // Share it yourself: a saved .patch and step-by-step instructions.
  await page.locator('.dss .btn', { hasText: 'Share it myself' }).click();
  await page.locator('.dss-fallback').waitFor();
  const files = readdirSync(patches).filter(f => f.endsWith('.patch'));
  assert.equal(files.length, 1, 'one .patch saved in the patches folder');
  assert.match(readFileSync(path.join(patches, files[0]), 'utf8'), /Subject: \[PATCH\]/);
  assert.match(await page.locator('.dss-file code').textContent(), /\.patch$/);
  await page.locator('.dss-os .btn', { hasText: 'Windows' }).click();
  const winText = await page.locator('.dss-steps').textContent();
  assert.match(winText, /PowerShell/); assert.match(winText, /git am "/);
  await page.locator('.dss-os .btn', { hasText: 'Mac' }).click();
  assert.match(await page.locator('.dss-steps').textContent(), /Terminal/);
  await page.waitForFunction(() => { const c = [...document.querySelectorAll('.dss-cmd')]; return c.length > 2 && c.every(p => p.querySelector('.copy-anchor button')); });
  assert.equal(await page.locator('.dss img').count(), 0, 'untrusted text never becomes HTML');
  assert.ok(!(await page.locator('.dss-fallback').textContent()).includes('github_pat_'));
  // Phone: no sideways scroll, copy buttons on commands.
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'dark', reducedMotion: 'reduce', hasTouch: true, isMobile: true });
  const p2 = await phone.newPage(); p2.on('pageerror', e => errors.push(e.message));
  const launch = await (await fetch(`${base}/api/session/launch`, { method: 'POST', headers: H, body: '{}' })).json().catch(() => null);
  await p2.goto(launch?.url || `${base}/?launch=${token}`);
  await p2.locator('.nav [data-page="developer"]').waitFor({ state: 'attached' });
  await openShare(p2, true);
  await p2.locator('.dss .btn', { hasText: 'Share it myself' }).click();
  await p2.locator('.dss-fallback').waitFor();
  const wide = await p2.evaluate(() => document.querySelector('#dsxToolDetail').scrollWidth - document.querySelector('#dsxToolDetail').clientWidth);
  assert.ok(wide <= 1, `no sideways scroll on phone (${wide}px)`);
  assert.deepEqual(errors, []);
  console.log('share UI ok');
})().catch(e => { console.error(e); process.exitCode = 1; }).finally(async () => {
  await browser?.close().catch(() => {});
  server.kill();
  await delay(300);
  try { rmSync(data, { recursive: true, force: true }); } catch { /* Windows may still hold files */ }
});

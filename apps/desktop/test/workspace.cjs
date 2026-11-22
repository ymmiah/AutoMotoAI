// One workspace (Tools > Edit, test & share): the editor, the approval-gated runner and
// Checkpoints / Share / Ask for a review live under three tabs with a status strip. Real local
// server, no network. Checks on desktop, tablet and phone: the three tabs and the strip, unsaved
// changes show up and clear on save, tests run only after the confirm dialog and the strip shows the
// result ring, the offline "not shared yet" count, the old cards open the right tab, every command has
// a copy button, nothing scrolls sideways, and every panel goes back where it came from.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn, execFileSync } = require('node:child_process');
const { mkdtempSync, rmSync, mkdirSync, writeFileSync, readFileSync, appendFileSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { randomBytes } = require('node:crypto');
const root = path.resolve(__dirname, '../../..');
const data = mkdtempSync(path.join(tmpdir(), 'automoto-workspace-'));
const ws = path.join(data, 'ws'); const proj = path.join(ws, 'demo');
const SHOTS = process.env.WS_SHOTS || '';
mkdirSync(path.join(proj, 'src'), { recursive: true });
const git = (...a) => execFileSync('git', ['-c', 'user.name=T', '-c', 'user.email=t@example.com', '-c', 'init.defaultBranch=main', ...a], { cwd: proj }).toString().trim();
writeFileSync(path.join(proj, 'package.json'), '{"name":"demo","private":true,"scripts":{"test":"node check.js"}}\n');
writeFileSync(path.join(proj, 'check.js'), "console.log('ok 1 adds');\nconsole.log('ok 2 counts');\nconsole.log('ok 3 resets');\nconsole.log('3 passed');\n");
writeFileSync(path.join(proj, 'src', 'app.js'), "export const add = (a, b) => a + b;\n");
git('init', '-q'); git('add', '-A'); git('commit', '-q', '-m', 'Start');
const shared = git('rev-parse', 'HEAD');
writeFileSync(path.join(proj, 'README.md'), '# Demo <img src=x onerror=alert(1)>\n');
git('add', '-A'); git('commit', '-q', '-m', 'Add readme');
writeFileSync(path.join(proj, 'src', 'more.js'), 'export const two = 2;\n');
git('add', '-A'); git('commit', '-q', '-m', 'Add more');
// A repository picked earlier and one earlier share (what Share writes): two checkpoints are newer.
mkdirSync(path.join(data, 'developer-studio'), { recursive: true });
writeFileSync(path.join(data, 'developer-studio', 'share-targets.json'), JSON.stringify({ [proj]: { provider: 'github', host: 'github.com', repo: 'example/demo', default_branch: 'main' } }));
appendFileSync(path.join(data, 'remote-audit.jsonl'), JSON.stringify({ time: '2026-11-20T10:00:00+00:00', action: 'share', result: 'ok', project: proj, provider: 'github', host: 'github.com', repo: 'example/demo', branch: 'main', commits: 1, head: shared.slice(0, 12) }) + '\n');
const token = randomBytes(32).toString('hex');
const port = 8887, base = `http://127.0.0.1:${port}`;
const py = process.env.PYTHON || 'python';
const env = { ...process.env, AUTOMOTO_DATA_DIR: data, AUTOMOTO_LAUNCH_TOKEN: token, AUTOMOTO_SANDBOX: 'local', AUTOMOTO_RATE_LIMIT: '10000', AUTOMOTO_WORKSPACE: ws };
for (const k of ['GITHUB_TOKEN', 'GH_TOKEN', 'GITLAB_TOKEN', 'GITLAB_URL']) delete env[k];
const server = spawn(py, ['-m', 'automoto', 'serve', '--no-browser', '--port', String(port)], { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'] });
let log = ''; server.stdout.on('data', d => { log += d; }); server.stderr.on('data', d => { log += d; });
const delay = ms => new Promise(r => setTimeout(r, ms));
const fact = (page, id) => page.locator(`#dswFact-${id} .dsw-fact-t b`).innerText();
async function stable(page) { await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))); await delay(250); }
async function top(page) { await page.evaluate(() => { const t = document.querySelector('#dsxToolsPage'); if (t) t.scrollTop = 0; }); }
async function shot(page, name) { if (!SHOTS) return; await stable(page); await page.screenshot({ path: path.join(SHOTS, name) }); }
async function openWorkspace(page, compact) {
  await page.evaluate(() => document.querySelector('.nav [data-page="developer"]').click());
  await page.locator('#dsxRoot').waitFor();
  await page.evaluate(p => { document.querySelector('#dsPath').value = p; document.querySelector('#dsOpen').click(); }, proj);
  await page.waitForFunction(() => /demo/.test(document.querySelector('#dsxProjectName')?.textContent || ''));
  await page.keyboard.press('Escape');
  if (compact) await page.locator('#dsxNavTools').click(); else await page.locator('#dsxTools').click();
  await page.locator('.dsx-card[data-tool="workspace"]').click();
  await page.locator('#dswRoot').waitFor();
}
let browser; const errors = [];
(async () => {
  for (let i = 0; i < 150; i++) {
    if (server.exitCode !== null) throw new Error(`server exited: ${log}`);
    if (await fetch(`${base}/api/health`).then(r => r.ok).catch(() => false)) break;
    if (i === 149) throw new Error(`server never started: ${log}`);
    await delay(100);
  }
  const H = { 'X-AutoMoto-Token': JSON.parse(readFileSync(path.join(data, 'session.json'), 'utf8')).token, 'Content-Type': 'application/json' };
  const t = await fetch(`${base}/api/developer/studio/trust`, { method: 'POST', headers: H, body: JSON.stringify({ project: proj, trusted: true, confirmed: true }) });
  assert.equal(t.status, 200, await t.text());
  // The engine's offline count, straight from the existing share status.
  const st = await (await fetch(`${base}/api/developer/studio/remote/status?project=${encodeURIComponent(proj)}`, { headers: H })).json();
  assert.deepEqual({ state: st.sync.state, unshared: st.sync.unshared }, { state: 'ahead', unshared: 2 });
  browser = await chromium.launch({ ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}), args: ['--no-sandbox'] });
  for (const [name, vp, compact] of [['desktop', { width: 1280, height: 800 }, false], ['tablet', { width: 820, height: 1180 }, true], ['phone', { width: 390, height: 844 }, true]]) {
    writeFileSync(path.join(proj, 'src', 'app.js'), "export const add = (a, b) => a + b;\n");
    const ctx = await browser.newContext({ viewport: vp, colorScheme: 'dark', reducedMotion: 'reduce', ...(name === 'phone' ? { hasTouch: true, isMobile: true } : {}) });
    const page = await ctx.newPage(); page.on('pageerror', e => errors.push(name + ': ' + e.message));
    const dialogs = []; page.on('dialog', d => { dialogs.push(d.message()); d.accept(); });
    const launch = await (await fetch(`${base}/api/session/launch`, { method: 'POST', headers: H, body: '{}' })).json().catch(() => null);
    await page.goto(launch?.url || `${base}/?launch=${token}`);
    await page.locator('.nav [data-page="developer"]').waitFor({ state: 'attached' });
    await openWorkspace(page, compact);
    // Three tabs, Edit first, and the strip.
    assert.deepEqual(await page.locator('.dsw-tab b').allTextContents(), ['Edit', 'Test', 'Share']);
    assert.equal(await page.locator('#dswTab-edit').getAttribute('aria-selected'), 'true');
    assert.equal(await page.locator('#dswPane-edit .ds-columns').count(), 1, 'the editor is in the Edit tab');
    await page.waitForFunction(() => /not shared yet/.test(document.querySelector('#dswFact-share')?.textContent || ''));
    assert.equal(await fact(page, 'share'), '2 checkpoints not shared yet');
    assert.match(await page.locator('#dswFact-share small').innerText(), /On GitHub/);
    assert.equal(await fact(page, 'test'), 'Not tested yet');
    assert.equal(await fact(page, 'edit'), 'All saved');
    // Edit: open a file, change it, see "Unsaved changes", save.
    await page.locator('#dswPane-edit .ds-entry', { hasText: 'src' }).first().click();
    await page.locator('#dswPane-edit .ds-entry', { hasText: 'app.js' }).first().click();
    if (compact && await page.locator('#dsShowEditor').isVisible()) await page.locator('#dsShowEditor').click();
    await page.waitForFunction(() => /add/.test(document.querySelector('#dswPane-edit .view-lines')?.innerText || document.querySelector('#dsSourceText')?.value || ''), null, { timeout: 15000 });
    if (await page.locator('#dswPane-edit .view-lines').isVisible()) { await page.locator('#dswPane-edit .view-lines').click(); await page.keyboard.press('Control+End'); await page.keyboard.type('export const sub = (a, b) => a - b;\n'); }
    else { await page.locator('#dsSourceText').focus(); await page.keyboard.press('Control+End'); await page.keyboard.type('export const sub = (a, b) => a - b;\n'); }
    await page.waitForFunction(() => /Unsaved changes/.test(document.querySelector('#dswFact-edit')?.textContent || ''), null, { timeout: 8000 })
      .catch(async e => { await page.screenshot({ path: '/tmp/ws-dbg.png' }); await page.locator('#dswTab-test').click(); throw new Error(e.message + ' | ' + await page.locator('#dsEditorState').innerText() + ' | ' + await page.locator('#dswFact-edit').innerText()); });
    assert.equal(await page.locator('#dswTab-edit').getAttribute('data-state'), 'warn');
    await top(page); await shot(page, `${name}-edit.png`);
    if (name === 'phone') await shot(page, 'flow-phone-1-edit.png');
    await page.locator('#dswTab-test').click();
    assert.equal(await page.locator('#dswPane-test .dsw-note').isVisible(), true, 'unsaved warning on Test');
    await page.locator('#dswTab-edit').click();
    await page.locator('#dsSaveFile').click();
    await page.waitForFunction(() => /All saved/.test(document.querySelector('#dswFact-edit')?.textContent || ''));
    assert.match(readFileSync(path.join(proj, 'src', 'app.js'), 'utf8'), /sub/);
    // Test: one obvious next step, the runner asks first, the strip shows the result.
    await page.locator('#dswPane-edit .dsw-next .btn', { hasText: 'Test it' }).click();
    assert.equal(await page.locator('#dswTab-test').getAttribute('aria-selected'), 'true');
    assert.equal(await page.locator('#dswPane-test #dsRunRoot').isVisible(), true);
    assert.equal(await page.locator('#dswPane-test .dsw-note').isVisible(), false);
    await page.locator('#dswPane-test .dsb .btn', { hasText: 'Check it works' }).click();
    await page.waitForFunction(() => /Tests passed/.test(document.querySelector('#dswFact-test')?.textContent || ''), null, { timeout: 30000 })
      .catch(async e => { throw new Error(e.message + ' | ' + await page.locator('#dswFact-test').innerText() + ' | ' + await page.locator('#dsrStatus').innerText() + ' | ' + dialogs.join(' / ') + ' | ' + await page.locator('#dsrTests').innerText().catch(() => '')); });
    assert.ok(dialogs.some(d => /Run these tests/.test(d)), 'tests ran only after the confirm dialog');
    assert.equal(await fact(page, 'test'), 'Tests passed · 3 of 3');
    assert.equal(await page.locator('#dswFact-test .dsb-ring b').innerText(), '3');
    assert.equal(await page.locator('#dswTab-test').getAttribute('data-state'), 'ok');
    const cmds = await page.locator('#dswPane-test code[data-copy]').count();
    assert.ok(cmds > 0);
    await page.waitForFunction(() => [...document.querySelectorAll('#dswPane-test code[data-copy]')].every(c => c.parentElement.querySelector('.copy-anchor button, button.copy-btn, button[aria-label^="Copy"]')));
    await top(page); await shot(page, `${name}-test.png`);
    if (name === 'phone') {
      await page.evaluate(() => { const sc = document.querySelector('#dsxToolsPage'), h = document.querySelector('.dsw-head').getBoundingClientRect(), c = document.querySelector('#dswPane-test .dsb-check').getBoundingClientRect(); sc.scrollTop += c.top - h.bottom - 60; });
      await shot(page, 'flow-phone-2-test-pass.png'); await top(page);
    }
    if (name === 'desktop' && SHOTS) { await stable(page); await page.locator('#dswRoot .dsw-strip').screenshot({ path: path.join(SHOTS, 'status-strip-desktop.png') }); }
    if (name === 'phone' && SHOTS) { await stable(page); await page.locator('#dswRoot .dsw-strip').screenshot({ path: path.join(SHOTS, 'status-strip-phone.png') }); }
    // Share: Checkpoints, Share and Ask for a review, in that order.
    await page.locator('#dswPane-test .dsw-next .btn', { hasText: 'Share it' }).click();
    assert.equal(await page.locator('#dswTab-share').getAttribute('aria-selected'), 'true');
    for (const id of ['dsGitRoot', 'dsShareRoot', 'dsReviewRoot']) assert.equal(await page.locator(`#dswPane-share #${id}`).isVisible(), true, id);
    assert.equal(await page.locator('.dss .dsb-step').count(), 4, 'the Share card is unchanged');
    await page.waitForFunction(() => /app\.js/.test(document.querySelector('#dswPart-git .dsb')?.textContent || ''), null, { timeout: 10000 });
    assert.equal(await page.locator('#dswPane-share img').count(), 0, 'project text never becomes HTML');
    await top(page); await shot(page, `${name}-share.png`);
    if (name === 'phone') await shot(page, 'flow-phone-3-share.png');
    await page.locator('.dsw-jump-b', { hasText: /^2/ }).click(); await delay(500);
    assert.ok(await page.evaluate(() => { const h = document.querySelector('.dsw-head').getBoundingClientRect(), s = document.querySelector('#dswPart-share').getBoundingClientRect(); return s.top >= h.bottom - 2; }), 'the sticky strip never covers the Share card');
    await shot(page, `${name}-share-2-send.png`);
    if (name === 'phone') await shot(page, 'flow-phone-4-share-send.png');
    assert.equal(await page.locator('.dsw-head').isVisible(), true, 'tabs and strip stay on screen');
    const wide = await page.evaluate(() => { const d = document.querySelector('#dsxToolDetail'); return d.scrollWidth - d.clientWidth; });
    assert.ok(wide <= 1, `no sideways scroll on ${name} (${wide}px)`);
    // The old cards are shortcuts to the right tab.
    for (const [card, tab] of [['run', 'test'], ['git', 'share'], ['share', 'share'], ['review', 'share'], ['account', 'share']]) {
      await page.locator('#dsxDetailBack').click();
      await page.locator(`.dsx-card[data-tool="${card}"]`).click();
      await page.locator('#dswRoot').waitFor();
      assert.equal(await page.locator(`#dswTab-${tab}`).getAttribute('aria-selected'), 'true', card);
      if (card === 'account') { assert.equal(await page.locator('#dswAccount').getAttribute('open'), ''); assert.equal(await page.locator('#dswAccount .dsa').isVisible(), true); }
    }
    // Share's "Connect GitHub or GitLab" opens the sign-in inside the same workspace.
    await page.locator('#dswAccount > summary').click();
    await page.locator('.dss .dsb-step .btn', { hasText: 'Connect GitHub or GitLab' }).click();
    assert.equal(await page.locator('#dswAccount').getAttribute('open'), '');
    assert.equal(await page.locator('#dswTab-share').getAttribute('aria-selected'), 'true');
    // Leaving puts every panel back.
    await page.locator('#dsxDetailBack').click();
    assert.equal(await page.locator('#dsxDetailBody').evaluate(e => e.children.length), 0, 'panels go back where they came from');
    assert.equal(await page.locator('.ds-shell .ds-columns').count(), 1);
    if (name === 'desktop') {
      // In the editor view the files and code return to the editor.
      await page.locator('#dsxToolsBack').click();
      await page.locator('#dsxView').click();
      await page.locator('#dsxTools').click();
      await page.locator('.dsx-card[data-tool="workspace"]').click();
      assert.equal(await page.locator('#dswPane-edit .ds-columns').count(), 1);
      await page.locator('#dsxDetailBack').click();
      assert.equal(await page.locator('#dsxEditor .ds-columns').count(), 1, 'editor view keeps its files and code');
      await page.locator('#dsxToolsBack').click();
      await page.locator('#dsxView').click();
    }
    await ctx.close();
  }
  assert.deepEqual(errors, []);
  console.log('workspace UI ok');
})().catch(e => { console.error(e, errors); process.exitCode = 1; }).finally(async () => {
  await browser?.close().catch(() => {});
  server.kill();
  await delay(300);
  try { rmSync(data, { recursive: true, force: true }); } catch { /* Windows may still hold files */ }
});

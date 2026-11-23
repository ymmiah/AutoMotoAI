// Edit, test & share (Tools > Edit, test & share): the Developer chat first, with a live panel beside
// it on desktop and tablet and a slide-up sheet on phones. Real local server, no network and no model:
// the assistant task is stubbed with page.route, like the other Developer tests. Checks on desktop,
// tablet and phone: the friendly empty state and quick chips; "Fix the error" shows the change as a
// diff card and nothing is written until Apply; "Test my app" asks on an inline card, then the real
// approval-gated runner runs and a ring shows the result; "Share to GitHub" saves a checkpoint, shows
// what will be sent and only sends after Share; a refused share gives the .patch fallback with copy
// buttons; the status pills; the old cards open the right live panel; nothing scrolls sideways; and
// every panel goes back where it came from.
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
const BUG = "export const add = (a, b) => a - b;\n", FIXED = "export const add = (a, b) => a + b;\n";
writeFileSync(path.join(proj, 'package.json'), '{"name":"demo","private":true,"scripts":{"test":"node check.js"}}\n');
writeFileSync(path.join(proj, 'check.js'), "console.log('ok 1 adds');\nconsole.log('ok 2 counts');\nconsole.log('ok 3 resets');\nconsole.log('3 passed');\n");
writeFileSync(path.join(proj, 'src', 'app.js'), BUG);
git('init', '-q'); git('add', '-A'); git('commit', '-q', '-m', 'Start');
const shared = git('rev-parse', 'HEAD');
writeFileSync(path.join(proj, 'README.md'), '# Demo <img src=x onerror=alert(1)>\n');
git('add', '-A'); git('commit', '-q', '-m', 'Add readme');
writeFileSync(path.join(proj, 'src', 'more.js'), 'export const two = 2;\n');
git('add', '-A'); git('commit', '-q', '-m', 'Add more');
const startHead = git('rev-parse', 'HEAD');
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
async function stable(page) { await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))); await delay(300); }
async function shot(page, name) { if (!SHOTS) return; await stable(page); await page.screenshot({ path: path.join(SHOTS, name) }); }
const lastBot = page => page.locator('#dsxThread .dsx-msg.bot').last();
async function bottom(page) { await page.evaluate(() => { const s = document.querySelector('#dswRoot .dsx-scroll'); if (s) s.scrollTop = s.scrollHeight; }); }
// "Manual controls" and "All tools" are in the page's ••• menu while the workspace is open.
async function menu(page, id) {
  await page.locator('#convMore').click();
  await page.locator(`#convMenu [data-ws="${id}"]`).click();
}
const pill = (page, id) => page.locator(`#dswPill-${id} .dsw-pill-t`).innerText();
const tip = (page, id) => page.locator(`#dswPill-${id}`).getAttribute('title');
async function openWorkspace(page, compact) {
  await page.evaluate(() => document.querySelector('.nav [data-page="developer"]').click());
  await page.locator('#dsxRoot').waitFor();
  // Requests still waiting when the project fails to open, to say what it was stuck on.
  const pending = new Set(), add = r => pending.add(r), done = r => pending.delete(r);
  page.on('request', add); page.on('requestfinished', done); page.on('requestfailed', done);
  await page.evaluate(p => { document.querySelector('#dsPath').value = p; document.querySelector('#dsOpen').click(); }, proj);
  // Opening runs every studio's project check; a busy CI runner can take longer than 30s, so wait
  // up to 60s and say what Developer Studio reported if the project still did not open.
  await page.waitForFunction(() => /demo/.test(document.querySelector('#dsxProjectName')?.textContent || ''), null, { timeout: 60000 })
    .catch(async e => { throw new Error(`project did not open at ${page.viewportSize()?.width}px: ${await page.locator('#dsStatus').textContent().catch(() => '?')} pending=${[...pending].map(r => r.method() + ' ' + r.url().replace(base, '')).join(', ') || 'none'} (${e.message})`); });
  page.off('request', add); page.off('requestfinished', done); page.off('requestfailed', done);
  await page.keyboard.press('Escape');
  if (compact) await page.locator('#dsxNavTools').click(); else await page.locator('#dsxTools').click();
  await page.locator('.dsx-card[data-tool="workspace"]').click();
  await page.locator('#dswRoot').waitFor();
}
// The stubbed assistant: it asks to change src/app.js (the bug), and the file only changes when the
// approve call comes in with approve=true, the same as the engine's approval-gated task.
async function stubAssistant(page, seen) {
  let approved = null;
  await page.route('**/api/conversations', r => r.request().method() === 'POST' ? r.fulfill({ json: { id: 'conv-w' } }) : r.continue());
  await page.route('**/api/agent', r => { seen.agent.push(r.request().postDataJSON()); approved = null; r.fulfill({ json: { task_id: 'task-w' } }); });
  await page.route('**/api/tasks/task-w/approve', r => {
    const b = r.request().postDataJSON(); seen.approve.push(b); approved = b.approve === true;
    if (approved) writeFileSync(path.join(proj, 'src', 'app.js'), FIXED);
    r.fulfill({ json: { ok: true } });
  });
  await page.route('**/api/tasks/task-w?**', r => {
    if (approved === null) return r.fulfill({ json: { status: 'running', next: 1, events: [{ type: 'tool_call', id: 'c1', name: 'edit_file', args: { path: 'src/app.js' } }],
      pending: { id: 'c1', name: 'edit_file', args: { path: path.join(proj, 'src', 'app.js'), old: 'a - b', new: 'a + b' }, reason: 'changes a file', level: 'risky' } } });
    return r.fulfill({ json: { status: 'done', next: 2, events: [{ type: 'tool_result', id: 'c1', name: 'edit_file', ok: approved, output: approved ? 'edited' : 'denied' }],
      result: { text: approved ? 'Fixed it: add() was taking away instead of adding. Now it adds.' : 'Okay, I left it as it was.' } } });
  });
}
// Share is stubbed at the website step only (no network): status gets a signed-in account, plan and
// share answer like the engine, with the engine's own count of checkpoints not shared yet, so every
// card and tooltip shows the same number. The .patch fallback is the real engine call.
async function stubShare(page, mode, H) {
  const unsharedNow = async () => (await (await fetch(`${base}/api/developer/studio/remote/status?project=${encodeURIComponent(proj)}`, { headers: H })).json()).sync.unshared;
  await page.route('**/remote/status?**', async r => {
    // The page can close while this request is still in flight (end of a viewport run); ignore that.
    try {
      const res = await r.fetch(); const j = await res.json();
      j.accounts = [{ status: 'ok', login: 'demo-user', provider: 'github', host: 'github.com' }];
      if (mode.sharedHead && mode.sharedHead === git('rev-parse', 'HEAD')) j.sync = { ...j.sync, state: 'shared', unshared: 0 };
      await r.fulfill({ response: res, json: j });
    } catch (e) { if (!/disposed|closed/i.test(String(e && e.message))) throw e; }
  });
  await page.route('**/remote/plan', async r => {
    if (mode.refuse) return r.fulfill({ json: { ok: false, summary: 'GitHub turned this share down.', commits: [], commit_count: 0, files: [], file_count: 0, blocks: [{ rule: 'non_ff', message: 'GitHub has newer work on main. Get the latest first, or share it yourself.' }], warnings: [], remote_branch: 'main' } });
    const n = await unsharedNow(); mode.count = n;
    const commits = git('log', '-n', String(n), '--format=%h%x09%s').split('\n').map(l => { const [short, subject] = l.split('\t'); return { short, subject, author: 'T' }; });
    r.fulfill({ json: { ok: true, summary: 'This sends your checkpoints to main on example/demo.', commits, commit_count: n, files: ['src/app.js'], file_count: 1, blocks: [], warnings: [], remote_branch: 'main', action_sha256: 'a'.repeat(64) } });
  });
  await page.route('**/remote/share', r => { mode.shares.push(r.request().postDataJSON()); mode.sharedHead = git('rev-parse', 'HEAD'); r.fulfill({ json: { ok: true, message: `Sent ${mode.count} checkpoints to main on example/demo.`, links: { branch: 'https://github.com/example/demo/tree/main' } } }); });
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
  const st = await (await fetch(`${base}/api/developer/studio/remote/status?project=${encodeURIComponent(proj)}`, { headers: H })).json();
  assert.deepEqual({ state: st.sync.state, unshared: st.sync.unshared }, { state: 'ahead', unshared: 2 });
  browser = await chromium.launch({ ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}), args: ['--no-sandbox'] });
  for (const [name, vp, compact] of [['desktop', { width: 1280, height: 800 }, false], ['tablet', { width: 820, height: 1180 }, true], ['phone', { width: 390, height: 844 }, true]]) {
    git('reset', '-q', '--hard', startHead);
    const ctx = await browser.newContext({ viewport: vp, colorScheme: 'dark', reducedMotion: 'reduce', ...(name === 'phone' ? { hasTouch: true, isMobile: true } : {}) });
    const page = await ctx.newPage(); page.on('pageerror', e => errors.push(name + ': ' + e.message));
    const dialogs = []; page.on('dialog', d => { dialogs.push(d.message()); d.accept(); });
    const seen = { agent: [], approve: [] }, mode = { refuse: false, shares: [] };
    await stubAssistant(page, seen); await stubShare(page, mode, H);
    const launch = await (await fetch(`${base}/api/session/launch`, { method: 'POST', headers: H, body: '{}' })).json().catch(() => null);
    await page.goto(launch?.url || `${base}/?launch=${token}`);
    await page.locator('.nav [data-page="developer"]').waitFor({ state: 'attached' });
    await openWorkspace(page, compact);
    // The empty state: one big friendly line and six quick chips, the chat is the main thing.
    assert.equal(await page.locator('.dsw-hello h2').innerText(), 'Hi! What do you want to build or fix today?');
    assert.deepEqual(await page.locator('.dsw-chip').allTextContents(), ['Explain my project', 'Fix the error', 'Test my app', 'Share to GitHub', 'Ask for a review', 'Map my project']);
    assert.equal(await page.locator('.dsw-chatslot #dsxChat').count(), 1, 'the Developer chat itself, not a new bot');
    assert.equal(await page.locator('#dsxPrompt').isVisible(), true);
    assert.equal(await page.locator('#dsxHero').isVisible(), false);
    assert.equal(await page.locator('.dsw-tab, .dsw-chatcol [role="tablist"]').count(), 0, 'no heavy tabs');
    assert.equal(await page.locator('.dsw-strip').isVisible(), false, 'no status strip before anything has happened');
    assert.equal(await page.locator('.dsw-top, #dswManual, #dswBack').count(), 0, 'no header buttons taking space from the chat');
    assert.equal(await page.locator('#dsxCompProject').isVisible(), false, 'no project chip in the composer');
    assert.equal(await page.locator('#dswLive').isVisible(), name === 'desktop', 'live panel beside the chat on desktop, slide-in on tablet, sheet on phone');
    if (name === 'desktop') assert.equal(await page.locator('#dswLive .dsw-edit .ds-columns').isVisible(), true, 'your files beside the chat');
    const chatW = await page.locator('.dsw-chatcol').evaluate(e => e.getBoundingClientRect().width), boxW = await page.locator('#dswRoot').evaluate(e => e.getBoundingClientRect().width);
    const chatH = await page.locator('.dsw-chatcol').evaluate(e => e.getBoundingClientRect().height), boxH = await page.locator('#dswRoot').evaluate(e => e.getBoundingClientRect().height);
    assert.ok(chatW / boxW > 0.5 && chatH / boxH > 0.5, `chat is the biggest part (${chatW}x${chatH} of ${boxW}x${boxH})`);
    await shot(page, `empty-${name}.png`);
    if (name === 'phone' && SHOTS) { await stable(page); const b = await page.locator('.dsx-dock').boundingBox(); await page.screenshot({ path: path.join(SHOTS, 'phone-chips.png'), clip: { x: 0, y: Math.max(0, b.y - 8), width: vp.width, height: b.height + 16 } }); }
    // The ••• menu holds Manual controls and All tools.
    await page.locator('#convMore').click();
    assert.deepEqual(await page.locator('#convMenu [data-ws]').allTextContents(), ['Manual controls', 'All tools']);
    if (name === 'phone') await shot(page, 'phone-menu.png');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#convMenu').isVisible(), false);
    // 1. Fix the error: the assistant's change shows as a diff, nothing is written until Apply.
    await page.locator('.dsw-chip', { hasText: 'Fix the error' }).click();
    await page.locator('#dsxThread .dsx-plan').last().waitFor({ timeout: 15000 });
    assert.equal(seen.agent.length, 0, 'the plan cannot silently run the coding agent');
    await page.locator('.dsx-plan-actions .primary').last().click();
    await page.locator('#dsxThread .dsw-ask').waitFor({ timeout: 15000 });
    assert.ok(dialogs.some(d => /task/i.test(d) || d.length > 0), 'the existing task confirmation still asks');
    assert.match(seen.agent[0].task || seen.agent[0].prompt || JSON.stringify(seen.agent[0]), /Find the error/);
    assert.equal(await page.locator('#dsxThread .dsx-msg.user').last().innerText(), 'Fix the error');
    assert.match(await page.locator('.dsw-ask > b').innerText(), /Here's the change for src\/app\.js/);
    assert.match(await page.locator('.dsw-ask .dsw-diff .d').first().innerText(), /a - b/);
    assert.match(await page.locator('.dsw-ask .dsw-diff .a').first().innerText(), /a \+ b/);
    assert.equal(readFileSync(path.join(proj, 'src', 'app.js'), 'utf8'), BUG, 'nothing changes before Apply');
    await bottom(page); await shot(page, `${name}-1-fix-diff.png`);
    await page.locator('.dsw-ask .btn', { hasText: 'Apply' }).click();
    await page.locator('.dsw-ask .dsw-done.ok').waitFor();
    assert.deepEqual(seen.approve, [{ call_id: 'c1', approve: true }]);
    await page.waitForFunction(() => /Now it adds/.test(document.querySelector('#dsxThread')?.textContent || ''), null, { timeout: 15000 });
    assert.equal(readFileSync(path.join(proj, 'src', 'app.js'), 'utf8'), FIXED);
    await page.locator('.dsx-actions [data-act="undo"]').waitFor({ timeout: 15000 });
    await page.locator('.dsw-strip').waitFor();
    assert.deepEqual([await pill(page, 'file'), await pill(page, 'test'), await pill(page, 'share')], ['All saved', 'Not tested yet', 'Not shared yet']);
    assert.match(await tip(page, 'file'), /1 file changed since your last checkpoint/);
    await bottom(page); await shot(page, `${name}-2-applied.png`);
    // 2. Test my app: an inline card with the exact command, then the real approval-gated runner.
    const before = dialogs.length;
    if (name === 'desktop') { await page.locator('#dsxPrompt').fill('test my app'); await page.locator('#dsxSend').click(); }
    else await page.locator('.dsw-chip', { hasText: 'Test my app' }).click();
    await lastBot(page).locator('.dsw-card', { hasText: 'Run your tests?' }).waitFor();
    assert.equal(seen.agent.length, 1, 'quick actions never go to the model');
    assert.equal(await lastBot(page).locator('.dsw-cmd code').innerText(), 'npm test');
    await lastBot(page).locator('.btn', { hasText: 'Run tests' }).click();
    await lastBot(page).locator('.dsw-result').waitFor({ timeout: 30000 })
      .catch(async e => { throw new Error(e.message + ' | ' + await lastBot(page).innerText() + ' | ' + await page.locator('#dsrStatus').innerText().catch(() => '')); });
    assert.equal(dialogs.length, before, 'the inline card is the confirm, no extra dialog');
    assert.equal(await lastBot(page).locator('.dsw-result .dsb-ring b').innerText(), '3');
    assert.match(await lastBot(page).locator('.dsw-result .dsb-check-text > b').innerText(), /All 3 checks passed/);
    await page.waitForFunction(() => /Tests passed/.test(document.querySelector('#dswPill-test')?.textContent || ''));
    assert.equal(await tip(page, 'test'), '3 of 3 checks passed.');
    await bottom(page); await shot(page, `${name}-3-test-pass.png`);
    // 3. Share to GitHub: save a checkpoint, see what goes, then Share.
    await lastBot(page).locator('.btn', { hasText: 'Share to GitHub' }).click();
    const save = lastBot(page).locator('.dsw-card', { hasText: 'Save your changes first?' });
    await save.waitFor({ timeout: 10000 });
    assert.match(await save.innerText(), /src\/app\.js/);
    if (await save.locator('input[aria-label="Your name"]').count()) { await save.locator('input[aria-label="Your name"]').fill('Demo'); await save.locator('input[aria-label="Your email"]').fill('demo@example.com'); }
    await save.locator('input[aria-label="Describe your change"]').fill('Fix add');
    await save.locator('.btn', { hasText: 'Save checkpoint' }).click();
    const confirm = lastBot(page).locator('.dsw-card', { hasText: /^Share \d+ checkpoints? to example\/demo\?/ });
    await confirm.waitFor({ timeout: 10000 });
    const n = mode.count;
    assert.equal(n, 3, 'two earlier checkpoints plus the one just saved');
    assert.equal(await confirm.locator('b').first().innerText(), `Share ${n} checkpoints to example/demo?`);
    assert.equal(await confirm.locator('.dsw-files li').count(), n, 'one line per checkpoint');
    await page.waitForFunction(k => (document.querySelector('#dswPill-share')?.title || '').startsWith(k + ' checkpoints not on GitHub'), n);
    assert.equal(git('log', '-1', '--format=%s'), 'Fix add');
    assert.equal(mode.shares.length, 0, 'nothing is sent before Share');
    assert.match(await confirm.innerText(), /No passwords, keys/);
    await bottom(page); await shot(page, `${name}-4-share-confirm.png`);
    await confirm.locator('.btn', { hasText: /^Share$/ }).click();
    const done = lastBot(page).locator('.dsw-card.ok', { hasText: 'Shared ✓' });
    await done.waitFor();
    assert.deepEqual({ ...mode.shares[0], project: undefined }, { project: undefined, remote_branch: 'main', action_sha256: 'a'.repeat(64), confirmed: true });
    assert.equal(await done.locator('a').getAttribute('href'), 'https://github.com/example/demo/tree/main');
    assert.equal(await done.locator('a').getAttribute('rel'), 'noopener noreferrer');
    assert.match(await done.innerText(), new RegExp(`Sent ${n} checkpoints`));
    await page.waitForFunction(() => /Everything shared/.test(document.querySelector('#dswPill-share')?.textContent || ''));
    await bottom(page); await shot(page, `${name}-5-shared.png`);
    // A refused share: the .patch fallback with a copy button on every command (real engine call).
    if (name !== 'tablet') {
      mode.refuse = true;
      await page.locator('.dsw-chip', { hasText: 'Share to GitHub' }).click();
      const no = lastBot(page).locator('.dsw-card', { hasText: "It can't be shared yet." });
      await no.waitFor();
      await no.locator('.btn', { hasText: 'Share it myself' }).click();
      await lastBot(page).locator('.dsw-fallback pre').first().waitFor({ timeout: 15000 });
      await page.waitForFunction(() => { const c = [...document.querySelectorAll('#dsxThread .dsw-fallback pre, #dsxThread .dsw-fallback code[data-copy]')]; return c.length && c.every(n => (n.closest('pre')||n.parentElement).querySelector('.copy-anchor button, button.copy-btn, button[aria-label^="Copy"]') || n.parentElement.querySelector('button[aria-label^="Copy"]')); }, null, { timeout: 8000 });
      assert.equal(mode.shares.length, 1);
      await bottom(page); await shot(page, `${name}-6-patch-fallback.png`);
      mode.refuse = false;
    }
    assert.equal(await page.locator('#dsxThread img').count(), 0, 'project and website text never becomes HTML');
    const wide = await page.evaluate(() => { const d = document.querySelector('#dswRoot'); const s = d.querySelector('.dsx-scroll'); return Math.max(getComputedStyle(d).overflowX === 'clip' ? 0 : d.scrollWidth - d.clientWidth, s.scrollWidth - s.clientWidth, document.documentElement.scrollWidth - document.documentElement.clientWidth); });
    assert.ok(wide <= 1, `no sideways scroll on ${name} (${wide}px)`);
    // Status pills open the live panel; on tablets it slides in from the right, on phones it slides up,
    // and Close puts it away.
    await page.locator('#dswPill-test').click();
    assert.equal(await page.locator('#dswLive #dsRunRoot').isVisible(), true);
    if (name !== 'desktop') {
      if (name === 'tablet') {
        const b = await page.locator('#dswLive').boundingBox(), c = await page.locator('#dswRoot').boundingBox();
        assert.ok(Math.abs(b.x + b.width - (c.x + c.width)) <= 1 && b.width < c.width * 0.9 && b.height >= c.height - 1, 'a panel from the right edge, full height');
        assert.equal(await page.locator('.dsw-scrim').isVisible(), true, 'the chat dims behind the panel');
        await shot(page, 'tablet-slide-in.png');
      } else await shot(page, 'phone-sheet-test.png');
      assert.equal(await page.locator('.dsw-live-close').innerText(), 'Close');
      await page.locator('.dsw-live-close').click(); await delay(300);
      assert.equal(await page.locator('#dswLive').isVisible(), false);
    }
    // Manual controls (••• menu): the old panels are a small step away.
    await menu(page, 'manual');
    assert.equal(await page.locator('.dsw-seg').isVisible(), true);
    await page.locator('.dsw-seg .btn', { hasText: 'Share' }).click();
    for (const id of ['dsGitRoot', 'dsShareRoot', 'dsReviewRoot']) assert.equal(await page.locator(`#dswLive #${id}`).isVisible(), true, id);
    if (name !== 'desktop') await page.locator('.dsw-live-close').click();
    // The old cards are shortcuts: they open the workspace with the right live panel showing.
    for (const [card, m] of [['run', 'test'], ['git', 'share'], ['share', 'share'], ['review', 'share'], ['account', 'share']]) {
      await menu(page, 'tools');
      await page.locator(`.dsx-card[data-tool="${card}"]`).click();
      await page.locator('#dswRoot').waitFor();
      assert.equal(await page.locator(`#dswLive .dsw-${m === 'file' ? 'edit' : m}`).isVisible(), true, card);
      if (card === 'run') assert.equal(await page.locator('#dswLive #dsRunRoot .dsb-steps').isVisible(), true);
      if (card === 'share') assert.equal(await page.locator('#dswLive .dss .dsb-step').count(), 4, 'the Share card is unchanged');
      if (card === 'account') { assert.equal(await page.locator('#dswAccount').getAttribute('open'), ''); assert.equal(await page.locator('#dswAccount .dsa').isVisible(), true); }
    }
    // Leaving puts every panel back.
    if (name !== 'desktop') await page.locator('.dsw-live-close').click();
    await menu(page, 'tools');
    assert.equal(await page.locator('#dsxDetailBody').evaluate(e => e.children.length), 0, 'panels go back where they came from');
    assert.equal(await page.locator('.ds-shell .ds-columns').count(), 1);
    assert.equal(await page.locator('.dsw-hello, .dsw-chips').count(), 0, 'hello and chips leave with the workspace');
    assert.equal(await page.locator('#dsxChat').evaluate(e => !!e.closest('.dsx-body')), true, 'the chat goes home');
    if (name === 'desktop') {
      await page.locator('#dsxToolsBack').click();
      await page.locator('#dsxView').click();
      await page.locator('#dsxTools').click();
      await page.locator('.dsx-card[data-tool="workspace"]').click();
      assert.equal(await page.locator('#dswLive .ds-columns').count(), 1);
      await menu(page, 'tools');
      assert.equal(await page.locator('#dsxEditor .ds-columns').count(), 1, 'editor view keeps its files and code');
      await page.locator('#dsxToolsBack').click();
      await page.locator('#dsxView').click();
    }
    await page.unrouteAll({ behavior: 'ignoreErrors' });
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

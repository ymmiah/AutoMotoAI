// End-to-end Developer Studio flow in the simple views: rail/sidebar entry, setup steps, read-only
// gating, starter cards that never run, Tools & languages page, stubbed agent runs with real
// Keep / Undo checkpoints, the editor view and back, classic layout, light theme and narrow widths.
// No provider keys: the agent endpoints are stubbed, so no model request is made.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { mkdtempSync, writeFileSync, mkdirSync, readFileSync, existsSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { randomBytes } = require('node:crypto');
const root = path.resolve(__dirname, '../../..');
const data = mkdtempSync(path.join(tmpdir(), 'automoto-e2e-'));
const out = process.env.UI_SHOTS || path.join(data, 'screenshots');
mkdirSync(out, { recursive: true });
const token = randomBytes(32).toString('hex');
const base = 'http://127.0.0.1:8877';
const server = spawn(process.env.PYTHON || 'python', ['-m', 'automoto', 'serve', '--no-browser', '--port', '8877'], {
  cwd: root, env: { ...process.env, AUTOMOTO_DATA_DIR: data, AUTOMOTO_LAUNCH_TOKEN: token, AUTOMOTO_SANDBOX: 'local', AUTOMOTO_RATE_LIMIT: '10000' },
  stdio: ['ignore', 'pipe', 'pipe'] });
let log = ''; server.stdout.on('data', d => log += d); server.stderr.on('data', d => log += d);
const delay = ms => new Promise(r => setTimeout(r, ms));
const findings = [];
const step = (name) => { findings.push(name); console.log('✓', name); };
(async () => {
  for (let i = 0; i < 150; i++) { if (await fetch(base + '/api/health').then(r => r.ok).catch(() => false)) break; await delay(100); }
  // Small React/Next style sample project.
  const proj = path.join(data, 'workspace', 'projects', 'next-sample');
  mkdirSync(path.join(proj, 'app'), { recursive: true }); mkdirSync(path.join(proj, 'components'), { recursive: true }); mkdirSync(path.join(proj, 'test'), { recursive: true });
  writeFileSync(path.join(proj, 'package.json'), JSON.stringify({ name: 'next-sample', private: true, scripts: { dev: 'next dev', test: 'node --test' }, dependencies: { next: '15.0.0', react: '19.0.0', 'react-dom': '19.0.0' } }, null, 2));
  writeFileSync(path.join(proj, 'app', 'page.tsx'), "import Counter from '../components/Counter';\nexport default function Page() {\n  return <main><h1>Hello</h1><Counter start={1} /></main>;\n}\n");
  writeFileSync(path.join(proj, 'components', 'Counter.tsx'), "'use client';\nimport { useState } from 'react';\nexport default function Counter({ start }: { start: number }) {\n  const [n, setN] = useState(start);\n  return <button onClick={() => setN(n + 1)}>Count {n}</button>;\n}\n");
  writeFileSync(path.join(proj, 'test', 'sum.test.js'), "const test=require('node:test');const assert=require('node:assert');\ntest('sum',()=>assert.equal(1+1,2));\n");
  writeFileSync(path.join(proj, 'README.md'), '# next-sample\n');
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, colorScheme: 'dark', reducedMotion: 'reduce' });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  const agentCalls = [];
  page.on('request', r => { if (/\/api\/(agent|conversations)$/.test(new URL(r.url()).pathname) && r.method() === 'POST') agentCalls.push(r.url()); });
  const shot = async name => { await page.evaluate(() => document.activeElement?.blur()); await page.screenshot({ path: path.join(out, name) }); };
  const accept = () => page.once('dialog', d => d.accept());
  await page.goto(base + '/?launch=' + token);
  await page.locator('.hero h2').waitFor();
  await page.locator('.rail [data-rail-menu="studios"]').click();
  await page.locator('[data-rail-panel="studios"] a[href="#/developer"]').click();
  await page.locator('#dsxRoot').waitFor();
  assert.equal(await page.locator('.rail [data-rail="studios"]').evaluate(e => e.classList.contains('active')), true);
  step('rail Studios menu opens Developer Studio');
  await page.goto(base + '/#/new'); await page.locator('.hero h2').waitFor();
  await page.locator('.nav [data-page="developer"]').click();
  await page.locator('#dsxRoot').waitFor();
  assert.equal(await page.locator('#dsxRoot').getAttribute('data-view'), 'chat');
  assert.equal(await page.locator('.ds-shell').isVisible(), false, 'the classic wall of panels is hidden by default');
  assert.equal(await page.locator('.studio-drop').isVisible(), false, 'no big drop zone');
  assert.equal(await page.locator('.dsx-page > .studio-agent-bridge').isVisible(), false, 'agent box is folded away');
  assert.match(await page.locator('#dsxHero').innerText(), /What do you want to build or fix\?/);
  assert.equal(await page.locator('.dsx-starter').count(), 4);
  assert.match(await page.locator('#dsxStep1').getAttribute('class'), /now/);
  assert.equal(await page.locator('#dsxSend').isDisabled(), true);
  assert.equal(await page.locator('#dsxTrust').isVisible(), false);
  const geo = await page.evaluate(() => { const v = document.querySelector('#view .page'); return [v.scrollWidth, v.clientWidth]; });
  assert.ok(geo[0] <= geo[1] + 2, 'no horizontal overflow');
  step('chat-first start: hero, 4 starters, setup step 1, Send disabled, no clutter');
  await page.locator('.dsx-starter', { hasText: 'Add tests' }).click();
  assert.match(await page.locator('#dsxPrompt').inputValue(), /regression tests/);
  assert.equal(await page.locator('#dsxSend').isDisabled(), true);
  step('starter card before a project fills the prompt only');
  await page.locator('#dsxPrompt').fill('');
  await shot('01-start-screen.png');
  await page.setViewportSize({ width: 420, height: 800 }); await delay(300);
  const overlap = await page.evaluate(() => {
    const head = document.querySelector('.dsx-head'), step = document.querySelector('#dsxStep1');
    if (!head || !step) return { ok: false, reason: 'missing' };
    const h = head.getBoundingClientRect(), s = step.getBoundingClientRect();
    return { ok: s.top >= h.bottom - 1 && s.height > 0, headBottom: Math.round(h.bottom), stepTop: Math.round(s.top), stepHeight: Math.round(s.height) };
  });
  assert.ok(overlap.ok, 'setup step 1 is not covered by the toolbar: ' + JSON.stringify(overlap));
  await page.setViewportSize({ width: 1600, height: 1000 }); await delay(200);
  await page.locator('#dsxStepProject').click();
  await page.locator('#dsxProjectPop').waitFor();
  assert.equal(await page.evaluate(() => document.activeElement?.id), 'dsPath');
  await page.locator('#dsPath').fill(proj);
  await page.locator('#dsOpen').click();
  await page.waitForFunction(() => /next-sample/.test(document.querySelector('#dsxProjectName')?.textContent || ''));
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#dsxTrust').innerText(), 'Read-only');
  assert.match(await page.locator('#dsxStep2').getAttribute('class'), /now/);
  await page.locator('.dsx-starter', { hasText: 'Explain project' }).click();
  assert.equal(await page.locator('#dsxSend').isDisabled(), true, 'read-only projects cannot run tasks');
  assert.match(await page.locator('#dsxFoot').innerText(), /Read-only/);
  step('project opens read-only: step 2, Send disabled');
  await page.locator('#dsxPrompt').fill('');
  await shot('02-setup-steps.png');
  // Tools & languages page.
  await page.locator('#dsxTools').click();
  await page.locator('#dsxToolsPage').waitFor();
  await page.waitForFunction(() => /TypeScript/.test(document.querySelector('#dsxDetected')?.textContent || ''));
  assert.ok(await page.locator('.dsx-card').count() >= 25);
  await page.waitForFunction(() => !/Checking/.test(document.querySelector('#dsxToolGrid')?.textContent || ''));
  assert.ok(await page.locator('.dsx-card .dsx-badge', { hasText: /^(Installed|Not installed)$/ }).count() >= 20);
  assert.match(await page.locator('.dsx-card').first().innerText(), /TypeScript|Web pages/, 'detected stack is suggested first');
  await shot('06-tools-page.png');
  await page.locator('#dsxToolSearch').fill('rust');
  assert.equal(await page.locator('.dsx-card').count(), 1);
  await page.locator('#dsxToolSearch').fill('');
  for (const [tool, rootId] of [['typescript', 'dsJavaScriptRoot'], ['ios', 'dsIosRoot'], ['legacy', 'dsLegacyRoot'], ['wasm', 'dsWasmRoot'], ['lsp', 'dsLspRoot'], ['language', 'dsLanguageRoot'], ['agent', null]]) {
    await page.locator(`.dsx-card[data-tool="${tool}"]`).click();
    await page.locator('#dsxToolDetail').waitFor();
    if (rootId) assert.equal(await page.locator(`#dsxDetailBody #${rootId}`).isVisible(), true, tool);
    else assert.equal(await page.locator('#dsxDetailBody .studio-agent-bridge').isVisible(), true);
    await page.locator('#dsxDetailBack').click();
  }
  assert.equal(await page.locator('#dsxDetailBody').evaluate(e => e.children.length), 0, 'panels go back where they came from');
  await page.locator('#dsxToolsBack').click();
  await page.locator('#dsxToolsPage').waitFor({ state: 'hidden' });
  assert.equal(await page.locator('#dsxBody').isVisible(), true);
  step('Tools & languages: detected banner, badges, search, each card opens its panel, back');
  // Allow changes.
  accept();
  await page.locator('#dsxTrust').click();
  await page.waitForFunction(() => document.querySelector('#dsxTrust')?.textContent === 'Changes allowed');
  assert.equal(await page.locator('#dsxSetup').isVisible(), false, 'setup disappears once done');
  for (const [label, re] of [['Explain project', /architecture/], ['Find & fix a bug', /failing test/], ['Improve code', /maintainability/], ['Add tests', /regression tests/]]) {
    await page.locator('.dsx-starter', { hasText: label }).click();
    assert.match(await page.locator('#dsxPrompt').inputValue(), re);
    assert.equal(await page.locator('#dsxSend').isDisabled(), false);
  }
  await delay(400);
  assert.equal(agentCalls.length, 0, 'starter cards never start a task');
  await page.locator('#dsxSend').click();
  await page.locator('.dsx-plan').last().waitFor();
  assert.equal(agentCalls.length, 0, 'planning is read-only and never starts a model task');
  assert.match(await page.locator('.dsx-plan').last().innerText(), /Review your plan/);
  assert.ok(await page.locator('.dsx-plan-steps li').last().count() >= 4, 'plan contains concrete steps');
  await page.locator('.dsx-plan-step-title input').last().check();
  assert.match(await page.locator('.dsx-plan-reviewed').last().innerText(), /1 of \d+ steps reviewed/);
  page.once('dialog', d => d.dismiss());
  await page.locator('.dsx-plan-actions .primary').last().click(); await delay(250);
  assert.equal(agentCalls.length, 0, 'declining the final confirmation starts nothing');
  step('V50 plan: real steps, manual review ticks, no execution without confirmation');
  // Stubbed agent task, real checkpoint: the "agent" edits files while the task runs.
  const counter = path.join(proj, 'components', 'Counter.tsx');
  const original = readFileSync(counter, 'utf8');
  let release = null, polls = 0;
  const gate = () => new Promise(r => { release = r; });
  await page.route('**/api/conversations', r => r.request().method() === 'POST' ? r.fulfill({ json: { id: 'conv-e2e' } }) : r.continue());
  await page.route('**/api/agent', r => r.fulfill({ json: { task_id: 'task-e2e' } }));
  let script = [];
  await page.route('**/api/tasks/task-e2e?**', async r => {
    polls++;
    const next = script.shift();
    if (next?.wait) await next.wait;
    if (next?.before) next.before();
    r.fulfill({ json: next?.json || { status: 'running', events: [], next: 99 } });
  });
  const runOnce = async (finalText, edit) => {
    const hold = gate();
    script = [
      { json: { status: 'running', next: 3, events: [
        { type: 'tool_call', id: 'r1', name: 'read_file', args: { path: 'app/page.tsx' } },
        { type: 'tool_call', id: 'e1', name: 'edit_file', args: { path: 'components/Counter.tsx' } },
        { type: 'tool_call', id: 't1', name: 'run_command', args: { command: 'npm test' } }] } },
      { wait: hold, before: edit, json: { status: 'running', next: 4, events: [{ type: 'tool_result', id: 't1', name: 'run_command', ok: true, output: '4 passed' }] } },
      { json: { status: 'done', next: 4, events: [], result: { text: finalText } } }];
    return null;
  };
  await runOnce('Fixed the counter: it now uses the updater form.', () => {
    writeFileSync(counter, original.replace('setN(n + 1)', 'setN(c => c + 1)'));
    writeFileSync(path.join(proj, 'components', 'Counter.test.tsx'), "test('counts', () => {});\n");
  });
  await page.locator('.dsx-starter', { hasText: 'Find & fix a bug' }).click();
  await page.locator('#dsxSend').click();
  await page.locator('.dsx-plan').last().waitFor();
  accept();
  await page.locator('.dsx-plan-actions .primary').last().click();
  await page.waitForFunction(() => /Running tests 0 of 1/.test(document.querySelector('.dsx-progress')?.textContent || ''), null, { timeout: 15000 });
  assert.match(await page.locator('.dsx-progress').innerText(), /Planning[\s\S]*Editing 1 file[\s\S]*Ready for your review/);
  assert.equal(await page.locator('#dsxStop').isVisible(), true);
  assert.equal(await page.locator('#dsxSend').isDisabled(), true, 'one task at a time');
  await shot('03-run-in-progress.png');
  step('run in progress: plain-language phases, progress bar, Stop, Send locked');
  release();
  await page.locator('.dsx-actions [data-act="undo"]').waitFor({ timeout: 15000 });
  assert.equal(await page.locator('#dsxReview').isVisible(), true, 'changes open in the review panel');
  const diff = await page.locator('#dsxReviewBody').innerText();
  assert.match(diff, /components\/Counter\.tsx/); assert.match(diff, /\+.*setN\(c => c \+ 1\)/); assert.match(diff, /Counter\.test\.tsx/);
  assert.match(await page.locator('.dsx-check').innerText(), /Edited[\s\S]*Counter\.tsx[\s\S]*Ran tests/);
  assert.equal(await page.locator('#dsxPrompt').inputValue(), '');
  assert.equal(await page.locator('#dsxStop').isVisible(), false);
  assert.match(await page.locator('#dsxFoot').innerText(), /keep or undo/);
  await page.locator('[data-rtab="tests"]').click();
  assert.match(await page.locator('#dsxReviewBody').innerText(), /npm test[\s\S]*passed/);
  await page.locator('[data-rtab="files"]').click();
  assert.match(await page.locator('#dsxReviewBody').innerText(), /Counter\.test\.tsx/);
  const desktopRow = page.locator('#dsxReviewBody .dsx-frow', { hasText: 'Counter.test.tsx' });
  assert.equal(await desktopRow.locator('button', { hasText: 'Undo' }).count(), 0, 'per-file Keep/Undo stay off the desktop Files tab');
  assert.equal(await desktopRow.locator('button', { hasText: 'Keep' }).count(), 0);
  await page.locator('[data-rtab="changes"]').click();
  await shot('04-review-preview-panel.png');
  step('task finished: answer, checklist, review panel with Changes / Files / Tests, back to next prompt');
  await page.setViewportSize({ width: 820, height: 1000 }); await delay(300);
  await page.locator('[data-rtab="files"]').click();
  const testRow = page.locator('#dsxReviewBody .dsx-frow', { hasText: 'Counter.test.tsx' });
  assert.equal(await testRow.locator('button', { hasText: 'Undo' }).count(), 1);
  assert.equal(await testRow.locator('button', { hasText: 'Keep' }).count(), 1);
  accept();
  await testRow.locator('button', { hasText: 'Undo' }).click();
  await page.waitForFunction(() => /undone/.test(document.querySelector('#dsxReviewBody')?.innerText || ''), null, { timeout: 15000 });
  assert.equal(existsSync(path.join(proj, 'components', 'Counter.test.tsx')), false, 'per-file Undo removes the new file');
  assert.match(readFileSync(counter, 'utf8'), /setN\(c => c \+ 1\)/, 'other files stay until a full Undo');
  step('Files tab can undo one file and leave the others');
  await page.setViewportSize({ width: 1600, height: 1000 }); await delay(200);
  accept();
  await page.locator('.dsx-actions [data-act="undo"]').click();
  await page.waitForFunction(() => /Changes undone/.test(document.querySelector('.dsx-actions')?.textContent || ''));
  assert.equal(readFileSync(counter, 'utf8'), original, 'Undo restores the edited file');
  assert.equal(existsSync(path.join(proj, 'components', 'Counter.test.tsx')), false, 'Undo removes the new file');
  assert.equal(await page.locator('#dsxRUndo').isDisabled(), true);
  step('Undo restores edited files and removes new ones on disk');
  await runOnce('Added a label.', () => writeFileSync(counter, original.replace('<button', '<button aria-label="Increase count"')));
  await page.locator('#dsxPrompt').fill('Add an accessible label to the counter button');
  await page.locator('#dsxSend').click();
  await page.locator('.dsx-plan').last().waitFor();
  accept();
  await page.locator('.dsx-plan-actions .primary').last().click();
  await page.waitForFunction(() => document.querySelectorAll('.dsx-progress:not(.finished)').length === 1, null, { timeout: 15000 });
  release();
  await page.waitForFunction(() => document.querySelectorAll('.dsx-actions [data-act="keep"]').length === 1, null, { timeout: 15000 });
  await page.locator('.dsx-actions [data-act="keep"]').click();
  await page.waitForFunction(() => /Changes kept/.test([...document.querySelectorAll('.dsx-actions')].pop()?.textContent || ''));
  assert.match(readFileSync(counter, 'utf8'), /aria-label="Increase count"/, 'Keep leaves the change in place');
  step('Keep leaves the change and closes the checkpoint');
  // Tablet: the review panel opens as a side panel above the tab bar, chat stays visible.
  await page.setViewportSize({ width: 820, height: 1000 }); await delay(300);
  if (!(await page.locator('#dsxReview').isVisible())) await page.locator('.dsx-link').last().click();
  await page.locator('#dsxReview').waitFor();
  const sheet = await page.locator('#dsxReview').evaluate(e => {
    const r = e.getBoundingClientRect();
    const nav = document.querySelector('#dsxNav')?.getBoundingClientRect();
    const chat = document.querySelector('#dsxChat')?.getBoundingClientRect();
    return { left: Math.round(r.left), bottom: Math.round(r.bottom), w: Math.round(r.width), vw: innerWidth, navTop: nav ? Math.round(nav.top) : null, chatW: chat ? Math.round(chat.width) : 0, chatH: chat ? Math.round(chat.height) : 0 };
  });
  assert.ok(sheet.left > 300 && sheet.w < sheet.vw && sheet.bottom <= (sheet.navTop ?? 1000) + 2, 'review is a tablet side panel: ' + JSON.stringify(sheet));
  assert.ok(sheet.chatW > 300 && sheet.chatH > 200, 'chat stays visible beside the review panel: ' + JSON.stringify(sheet));
  assert.equal(await page.locator('#dsxNav').isVisible(), true, 'tab bar stays at the bottom on a tablet');
  await page.evaluate(() => document.activeElement?.blur());
  await shot('08-narrow-review-sheet.png');
  await page.setViewportSize({ width: 1600, height: 1000 }); await delay(300);
  step('tablet width: review panel opens as a side panel beside chat');
  // Editor view and back; the choice is remembered.
  await page.locator('#dsxReviewClose').click();
  await page.locator('#dsxView').click();
  assert.equal(await page.locator('#dsxRoot').getAttribute('data-view'), 'editor');
  assert.equal(await page.locator('#dsxEditor .ds-columns').isVisible(), true);
  assert.equal(await page.locator('#dsxAllow').getAttribute('aria-checked'), 'true');
  assert.equal(await page.locator('#dsxRunTests').isEnabled(), true);
  await page.locator('.ds-entry', { hasText: 'components' }).first().click();
  await page.locator('.ds-entry', { hasText: 'Counter.tsx' }).first().click();
  await page.waitForFunction(() => /aria-label/.test(document.querySelector('#dsEditorRoot .view-lines')?.innerText || ''), null, { timeout: 15000 });
  assert.match(await page.locator('#dsEditorState').innerText(), /Saved · SHA-256 /);
  if (!(await page.locator('#dsxReview').isVisible())) await page.locator('.dsx-link').last().click();
  assert.equal(await page.locator('#dsxROpen').innerText(), 'Open in editor');
  await shot('05-editor-view.png');
  await page.reload();
  await page.locator('#dsxRoot').waitFor();
  assert.equal(await page.locator('#dsxRoot').getAttribute('data-view'), 'editor', 'view choice is remembered');
  await page.locator('#dsxView').click();
  assert.equal(await page.locator('#dsxRoot').getAttribute('data-view'), 'chat');
  assert.equal(await page.locator('#dsxEditor .ds-columns').count(), 0);
  step('Open in editor shows files, Monaco and chat; Back to chat; choice remembered');
  // Classic layout keeps every panel reachable.
  await page.locator('#dsxTools').click();
  await page.locator('#dsxClassic').click();
  assert.equal(await page.locator('.ds-shell').isVisible(), true);
  assert.equal(await page.locator('#dsxRoot').isVisible(), false);
  await page.locator('#dsxBackSimple').click();
  assert.equal(await page.locator('#dsxRoot').isVisible(), true);
  step('classic all-panels layout and back');
  // Light theme and narrow widths.
  await page.locator('#dsPath').evaluate(() => 0);
  await page.locator('#dsxProject').click(); await page.locator('#dsPath').fill(proj); await page.locator('#dsOpen').click();
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => /next-sample/.test(document.querySelector('#dsxProjectName')?.textContent || ''));
  assert.match(await page.locator('#dsxThread').innerText(), /Changes kept|accessible label|Increase count/);
  assert.equal(await page.locator('#dsxClear').isVisible(), false, 'Clear chat is a phone/tablet control');
  await page.setViewportSize({ width: 820, height: 1000 }); await delay(300);
  assert.equal(await page.locator('#dsxClear').isVisible(), true);
  accept();
  await page.locator('#dsxClear').click();
  await page.waitForFunction(() => (document.querySelector('#dsxThread')?.children.length || 0) === 0);
  assert.equal(await page.locator('#dsxHero').isVisible(), true);
  step('studio chat is restored with the project and can be cleared');
  await page.setViewportSize({ width: 1600, height: 1000 }); await delay(200);
  await page.evaluate(() => { document.documentElement.dataset.theme = 'light'; });
  await delay(200);
  await shot('07-light-theme.png');
  await page.setViewportSize({ width: 820, height: 1000 }); await delay(300);
  const contrast = await page.evaluate(() => {
    const lum = (c) => { const m = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/); if (!m) return null; const s = [m[1], m[2], m[3]].map(Number).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * s[0] + 0.7152 * s[1] + 0.0722 * s[2]; };
    const el = document.querySelector('#dsxFoot'); const fg = getComputedStyle(el).color;
    let n = el, bg = 'rgb(255,255,255)';
    while (n) { const b = getComputedStyle(n).backgroundColor; if (b && !/^rgba?\(0,\s*0,\s*0,\s*0\)$/.test(b)) { bg = b; break; } n = n.parentElement; }
    const L1 = lum(fg), L2 = lum(bg); const [a, b] = L1 > L2 ? [L1, L2] : [L2, L1];
    return (a + 0.05) / (b + 0.05);
  });
  assert.ok(contrast >= 4.5, 'light-theme footer contrast on phone/tablet ' + contrast);
  await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });
  const ov = await page.evaluate(() => { const v = document.querySelector('#view .page'); return [v.scrollWidth, v.clientWidth]; });
  assert.ok(ov[0] <= ov[1] + 2, 'narrow: no horizontal overflow');
  await shot('09-narrow-820.png');
  await page.setViewportSize({ width: 420, height: 900 }); await delay(300);
  await page.locator('#dsxView').click();
  await page.locator('#dsxRoot[data-view="editor"]').waitFor();
  if (await page.locator('#dsShowExplorer').isVisible()) await page.locator('#dsShowExplorer').click();
  await page.locator('.ds-entry', { hasText: 'components' }).first().click();
  await page.locator('.ds-entry', { hasText: 'Counter.tsx' }).first().click();
  assert.equal(await page.locator('#dsShowEditor').isVisible(), true, 'Code toggle visible on a narrow editor');
  assert.equal(await page.locator('#dsShowExplorer').isVisible(), true, 'Files toggle visible on a narrow editor');
  if (await page.locator('#dsShowEditor').isVisible()) await page.locator('#dsShowEditor').click();
  await delay(500);
  const monacoVisible = async () => page.evaluate(() => {
    const node = document.querySelector('#dsMonacoShell:not([hidden]) .monaco-editor, #dsMonacoShell:not([hidden]), #dsSourceText:not([hidden])');
    if (!node) return { ok: false };
    const st = getComputedStyle(node), r = node.getBoundingClientRect();
    return { ok: st.display !== 'none' && st.visibility !== 'hidden' && r.height > 80 && r.width > 80, display: st.display, h: Math.round(r.height), w: Math.round(r.width), top: Math.round(r.top) };
  });
  let monaco = await monacoVisible();
  assert.ok(monaco.ok, 'narrow editor stays visible: ' + JSON.stringify(monaco));
  assert.equal(await page.locator('#dsEditorState').innerText(), 'Saved');
  assert.match(await page.locator('#dsEditorState').getAttribute('title') || '', /Checksum/);
  await page.locator('#dsShowExplorer').click();
  await delay(200);
  assert.equal(await page.locator('#dsFiles').isVisible(), true, 'Files toggle shows the file tree');
  await page.locator('#dsShowEditor').click();
  await delay(400);
  monaco = await monacoVisible();
  assert.ok(monaco.ok, 'Code toggle brings the editor back: ' + JSON.stringify(monaco));
  await shot('10-phone-420.png');
  await page.locator('#dsxView').click();
  await page.locator('#dsxRoot[data-view="chat"]').waitFor();
  step('light theme and narrow widths render without overflow; editor stays visible');

  // Hybrid phone (390) and tablet (820) nav: tab bar + sheets.
  const tabBar = async () => page.evaluate(() => {
    const nav = document.querySelector('#dsxNav');
    const st = nav ? getComputedStyle(nav) : null;
    const r = nav?.getBoundingClientRect();
    const buttons = [...(nav?.querySelectorAll('[data-nav]') || [])].map(b => {
      const br = b.getBoundingClientRect();
      return { id: b.id, label: (b.textContent || '').replace(/\d+$/, '').trim(), w: Math.round(br.width), h: Math.round(br.height) };
    });
    return { visible: !!(nav && st.display !== 'none' && r.height > 0), top: r ? Math.round(r.top) : 0, bottom: r ? Math.round(r.bottom) : 0, h: r ? Math.round(r.height) : 0, vh: innerHeight, buttons };
  });
  const sheetBox = (sel) => page.locator(sel).evaluate((e) => {
    const r = e.getBoundingClientRect();
    const nav = document.querySelector('#dsxNav')?.getBoundingClientRect();
    const chat = document.querySelector('#dsxChat')?.getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom), left: Math.round(r.left), w: Math.round(r.width), h: Math.round(r.height), vw: innerWidth, vh: innerHeight, navTop: nav ? Math.round(nav.top) : null, chatW: chat ? Math.round(chat.width) : 0, chatH: chat ? Math.round(chat.height) : 0 };
  });

  await page.setViewportSize({ width: 390, height: 844 }); await delay(300);
  let nav = await tabBar();
  assert.ok(nav.visible, 'tab bar shows on a phone: ' + JSON.stringify(nav));
  assert.ok(nav.bottom >= 840, 'tab bar sits at the bottom: ' + JSON.stringify(nav));
  assert.deepEqual(nav.buttons.map(b => b.label), ['Chat', 'Files', 'Review', 'Tools']);
  for (const b of nav.buttons) assert.ok(b.h >= 44 && b.w >= 44, 'thumb target 44px+: ' + JSON.stringify(b));

  await runOnce('Tweaked the count button label again.', () => writeFileSync(counter, original.replace('<button', '<button aria-label="Count"')));
  await page.locator('#dsxPrompt').fill('Tweak the count button label again');
  accept();
  await page.locator('#dsxSend').click();
  await page.waitForFunction(() => document.querySelectorAll('.dsx-progress:not(.finished)').length === 1, null, { timeout: 15000 });
  release();
  await page.locator('#dsxReview').waitFor({ timeout: 15000 });
  const phoneSheet = await sheetBox('#dsxReview');
  assert.ok(phoneSheet.bottom <= (phoneSheet.navTop ?? 844) + 2, 'review sheet sits above the tab bar: ' + JSON.stringify(phoneSheet));
  assert.ok(phoneSheet.left <= 2 && phoneSheet.w >= 300 && phoneSheet.w >= phoneSheet.vw - 4, 'review is a full-width bottom sheet: ' + JSON.stringify(phoneSheet));
  assert.equal(await page.locator('#dsxNavReviewBadge').isVisible(), true, 'Review tab shows a badge when changes are waiting');
  assert.match(await page.locator('#dsxRKeep').innerText(), /Keep changes/);
  assert.match(await page.locator('#dsxRUndo').innerText(), /Undo all/);
  await page.locator('#dsxReviewClose').click();
  assert.equal(await page.locator('#dsxReview').isVisible(), false);
  await page.locator('#dsxNavReview').click();
  await page.locator('#dsxReview').waitFor();
  step('phone tab bar; review sheet opens on its own and from the Review tab');
  await page.locator('#dsxRKeep').click();
  await page.waitForFunction(() => /Changes kept/.test([...document.querySelectorAll('.dsx-actions')].pop()?.textContent || ''));
  assert.equal(await page.locator('#dsxReview').isVisible(), false, 'Keep closes the review sheet');
  step('phone Keep / Undo closes the review sheet');

  await page.locator('#dsxNavFiles').click();
  await page.locator('#dsxFilesSheet').waitFor();
  const filesSheet = await sheetBox('#dsxFilesSheet');
  assert.ok(filesSheet.bottom <= (filesSheet.navTop ?? 844) + 2 && filesSheet.w >= 300, 'Files opens as a bottom sheet: ' + JSON.stringify(filesSheet));
  await page.locator('#dsxFilesSheet .ds-entry').first().waitFor({ timeout: 15000 });
  if (await page.locator('#dsxFilesSheet .ds-entry', { hasText: 'components' }).count()) {
    await page.locator('#dsxFilesSheet .ds-entry', { hasText: 'components' }).first().click();
  }
  await page.locator('#dsxFilesSheet .ds-entry', { hasText: 'Counter.tsx' }).first().click();
  await page.locator('#dsxRoot[data-view="editor"]').waitFor();
  assert.equal(await page.locator('#dsxFilesSheet').isVisible(), false, 'opening a file closes the files sheet');
  assert.equal(await page.locator('#dsShowEditor').isVisible(), true, 'Files / Code toggle stays in the editor');
  if (await page.locator('#dsShowEditor').isVisible()) await page.locator('#dsShowEditor').click();
  await delay(400);
  monaco = await monacoVisible();
  assert.ok(monaco.ok, 'Files tab opens the editor: ' + JSON.stringify(monaco));
  await page.locator('#dsxNavChat').click();
  await page.locator('#dsxRoot[data-view="chat"]').waitFor();
  step('phone Files tab opens a file in the full-width editor');

  await page.locator('#dsxNavTools').click();
  await page.locator('#dsxToolsPage').waitFor();
  const toolsSheet = await sheetBox('#dsxToolsPage');
  assert.ok(toolsSheet.bottom <= (toolsSheet.navTop ?? 844) + 2, 'Tools opens as a bottom sheet: ' + JSON.stringify(toolsSheet));
  await page.locator('#dsxToolSearch').fill('Python');
  await delay(200);
  const toolNames = await page.locator('#dsxToolGrid .dsx-card b').allTextContents();
  assert.ok(toolNames.some(n => /python/i.test(n)), 'Tools search finds Python: ' + toolNames.join(', '));
  assert.ok(toolNames.length < 15, 'Tools search narrows the list: ' + toolNames.join(', '));
  await page.locator('#dsxToolGrid .dsx-card', { hasText: 'Python' }).first().click();
  await page.locator('#dsxToolDetail:not([hidden])').waitFor();
  assert.equal(await page.locator('#dsxDetailBack').isVisible(), true, 'a tool opens full-screen with a back button');
  await page.locator('#dsxDetailBack').click();
  await page.locator('#dsxToolGrid').waitFor();
  await page.locator('#dsxNavChat').click();
  assert.equal(await page.locator('#dsxToolsPage').isVisible(), false, 'Chat tab closes the tools sheet');
  step('phone Tools tab is searchable and opens a tool full-screen');

  await page.setViewportSize({ width: 820, height: 1180 }); await delay(300);
  nav = await tabBar();
  assert.ok(nav.visible && nav.bottom >= 1170, 'tab bar sits at the bottom on a tablet: ' + JSON.stringify(nav));
  for (const b of nav.buttons) assert.ok(b.h >= 44 && b.w >= 44, 'tablet thumb target 44px+: ' + JSON.stringify(b));
  await runOnce('Reviewed the change on a tablet.', () => writeFileSync(counter, original.replace('<button', '<button aria-label="Tablet count"')));
  await page.locator('#dsxPrompt').fill('Review the change on a tablet');
  accept();
  await page.locator('#dsxSend').click();
  await page.waitForFunction(() => document.querySelectorAll('.dsx-progress:not(.finished)').length === 1, null, { timeout: 15000 });
  release();
  await page.locator('#dsxReview').waitFor({ timeout: 15000 });
  const tabSheet = await sheetBox('#dsxReview');
  assert.ok(tabSheet.left > 300 && tabSheet.w < tabSheet.vw && tabSheet.bottom <= (tabSheet.navTop ?? 1180) + 2, 'tablet review is a side panel: ' + JSON.stringify(tabSheet));
  assert.ok(tabSheet.chatW > 300 && tabSheet.chatH > 200, 'chat stays visible beside the tablet review panel: ' + JSON.stringify(tabSheet));
  assert.equal(await page.locator('#dsxNavReviewBadge').isVisible(), true, 'Review badge shows on a tablet');
  await page.locator('#dsxRKeep').click();
  await page.waitForFunction(() => /Changes kept/.test([...document.querySelectorAll('.dsx-actions')].pop()?.textContent || ''));
  await page.locator('#dsxNavFiles').click();
  await page.locator('#dsxFilesSheet').waitFor();
  const tabFiles = await sheetBox('#dsxFilesSheet');
  assert.ok(tabFiles.left > 300 && tabFiles.chatW > 300, 'tablet Files is a side panel beside chat: ' + JSON.stringify(tabFiles));
  await page.locator('#dsxNavTools').click();
  await page.locator('#dsxToolsPage').waitFor();
  await page.locator('#dsxToolSearch').fill('Rust');
  await delay(200);
  const rustNames = await page.locator('#dsxToolGrid .dsx-card b').allTextContents();
  assert.ok(rustNames.some(n => /rust/i.test(n)), 'tablet Tools search finds Rust: ' + rustNames.join(', '));
  await page.locator('#dsxNavChat').click();
  assert.equal(await page.locator('#dsxToolsPage').isVisible(), false);
  step('tablet tab bar; review and files open as a side panel; Tools search works');

  assert.deepEqual(errors, [], 'page errors: ' + errors.join('; '));
  console.log('E2E passed:', findings.length, 'steps');
  await browser.close(); server.kill();
})().catch(async e => { console.error(e); console.error(log.slice(-2000)); server.kill(); process.exit(1); });

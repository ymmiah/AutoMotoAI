// End-to-end Developer Studio flow inside the three-pane layout: rail/sidebar entry, read-only
// project, trust, V34 guide and starters, tools drawer, Monaco and a stubbed agent task.
// No provider keys: the agent endpoints are stubbed, so no model request is made.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { mkdtempSync, writeFileSync, mkdirSync } = require('node:fs');
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
  await page.goto(base + '/?launch=' + token);
  await page.locator('.hero h2').waitFor();
  // Reach Developer Studio from the rail studios menu.
  await page.locator('.rail [data-rail-menu="studios"]').click();
  await page.locator('[data-rail-panel="studios"] a[href="#/developer"]').click();
  await page.locator('.ds-v33-title').waitFor();
  assert.equal(await page.locator('.rail [data-rail="studios"]').evaluate(e => e.classList.contains('active')), true);
  step('rail Studios menu opens Developer Studio and marks Studios active');
  await page.goto(base + '/#/new'); await page.locator('.hero h2').waitFor();
  await page.locator('.nav [data-page="developer"]').click();
  await page.locator('.ds-v33-title').waitFor();
  assert.equal(await page.locator('.nav [data-page="developer"]').evaluate(e => e.classList.contains('active') || e.getAttribute('aria-current') === 'page'), true);
  step('sidebar Pinned studios link opens Developer Studio');
  // Layout sanity: workbench fits the centre pane without horizontal overflow.
  const geo = await page.evaluate(() => { const v = document.querySelector('#view .page'), s = document.querySelector('.ds-shell'); const vr = v.getBoundingClientRect(), sr = s.getBoundingClientRect(); return { vl: vr.left, vr: vr.right, sl: sr.left, sr: sr.right, vw: v.scrollWidth, cw: v.clientWidth }; });
  console.log('geometry', JSON.stringify(geo));
  assert.ok(geo.vw <= geo.cw + 2, 'centre pane must not scroll horizontally');
  step('workbench fits centre pane (no horizontal overflow)');
  assert.match(await page.locator('#dsV34Step').innerText(), /1 of 3/);
  assert.equal(await page.locator('#dsV33Send').isDisabled(), true);
  // Starter chip with no project: fills prompt but cannot run.
  await page.locator('.ds-v34-chip', { hasText: 'Add tests' }).click();
  assert.match(await page.locator('#dsV33Prompt').inputValue(), /regression tests/);
  assert.equal(await page.locator('#dsV33Send').isDisabled(), true);
  step('starter chip before project fills prompt, Run stays disabled');
  await page.evaluate(() => document.querySelector('#view .page').scrollTo(0, 0)); await delay(200);
  await page.screenshot({ path: path.join(out, '01-wide-dark-no-project.png') });
  // Open project (read-only).
  await page.locator('#dsV34Project').click();
  assert.equal(await page.evaluate(() => document.activeElement?.id), 'dsPath');
  step('guide step 1 focuses the project path field');
  await page.locator('#dsPath').fill(proj);
  await page.locator('#dsOpen').click();
  await page.waitForFunction(() => document.querySelector('#dsProject')?.textContent?.includes('next-sample'));
  assert.match(await page.locator('#dsTrustState').innerText(), /Restricted/);
  assert.match(await page.locator('#dsV34Step').innerText(), /2 of 3/);
  assert.match(await page.locator('#dsV33WorkspaceState').innerText(), /Read-only/);
  assert.equal(await page.locator('#dsV33Send').isDisabled(), true);
  assert.equal(await page.locator('#dsV34Prompt').isDisabled(), true);
  step('project opens read-only: guide 2 of 3, Run disabled');
  // Browse files and open in Monaco.
  await page.locator('.ds-entry', { hasText: 'components' }).first().click();
  await page.locator('.ds-entry', { hasText: 'Counter.tsx' }).first().click();
  await page.waitForFunction(() => document.querySelector('#dsFilename')?.textContent?.includes('Counter.tsx'));
  await page.waitForFunction(() => !!document.querySelector('#dsEditorRoot .monaco-editor'), null, { timeout: 15000 });
  const monacoText = await page.evaluate(() => document.querySelector('#dsEditorRoot .view-lines')?.innerText || '');
  assert.match(monacoText, /useState/);
  step('Monaco editor renders Counter.tsx');
  // Trust.
  await page.locator('#dsV34Trust').click();
  assert.equal(await page.evaluate(() => document.activeElement?.id), 'dsTrust');
  page.once('dialog', d => d.accept());
  await page.locator('#dsTrust').click();
  await page.waitForFunction(() => document.querySelector('#dsTrustState')?.textContent?.includes('Trusted'));
  await page.waitForFunction(() => /3 of 3/.test(document.querySelector('#dsV34Step')?.textContent || ''));
  assert.match(await page.locator('#dsV33WorkspaceState').innerText(), /Trusted/);
  step('trust: guide 3 of 3, workspace badge Trusted');
  // Starter chips fill prompt without running.
  for (const [label, re] of [['Explain project', /architecture/], ['Find and fix a bug', /failing test/], ['Improve code quality', /maintainability/], ['Add tests', /regression tests/]]) {
    await page.locator('.ds-v34-chip', { hasText: label }).click();
    assert.match(await page.locator('#dsV33Prompt').inputValue(), re);
    assert.equal(await page.locator('#dsV33Send').isDisabled(), false);
  }
  await delay(500);
  assert.equal(agentCalls.length, 0, 'chips must not start the agent');
  assert.equal(await page.locator('#dsV33AgentTimeline .ds-v33-user').count(), 0);
  step('all 4 starter chips fill prompt, enable Run, start nothing');
  await page.locator('.ds-v34-chip', { hasText: 'Explain project' }).click();
  await page.evaluate(() => document.querySelector('.ds-v33-title').scrollIntoView({ block: 'start' })); await delay(200);
  await page.screenshot({ path: path.join(out, '02-trusted-project-guide.png') });
  // Cancelling the confirm dialog must not run.
  page.once('dialog', d => d.dismiss());
  await page.locator('#dsV33Send').click(); await delay(400);
  assert.equal(agentCalls.length, 0);
  step('dismissing the run confirmation starts nothing');
  // Tools drawer.
  await page.locator('#dsV33Tools').click();
  await page.locator('#dsV33ToolsDrawer').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#dsV33Tools').getAttribute('aria-expanded'), 'true');
  assert.equal(await page.locator('#dsV33ToolsDrawer #dsLanguageRoot').count(), 1);
  assert.equal(await page.locator('#dsV33ToolsDrawer #dsIosRoot').count(), 1);
  const lang = await page.locator('#dsLanguageRoot').innerText();
  console.log('language panel:', lang.slice(0, 200).replace(/\n/g, ' | '));
  assert.equal(await page.evaluate(() => document.scrollingElement.scrollTop), 0, 'opening the drawer must not scroll the window');
  step('tools drawer opens with language panel and iPhone panel inside');
  await page.locator('#dsLanguageRoot').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, '03-tools-drawer-open.png') });
  await page.locator('#dsV33Tools').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, '03b-tools-drawer-top.png') });
  await page.locator('#dsV33CloseTools').click();
  await page.locator('#dsV33ToolsDrawer').waitFor({ state: 'hidden' });
  await page.locator('#dsV33Extensions').click();
  await page.locator('#dsV33ToolsDrawer').waitFor({ state: 'visible' });
  await page.locator('#dsV33Tools').click();
  await page.locator('#dsV33ToolsDrawer').waitFor({ state: 'hidden' });
  step('drawer closes via Close tools and toggle; Extensions rail opens it');
  // Simulated agent task (no API keys): stub agent endpoints and check return to next prompt.
  let polls = 0;
  await page.route('**/api/conversations', r => r.request().method() === 'POST' ? r.fulfill({ json: { id: 'conv-e2e' } }) : r.continue());
  await page.route('**/api/agent', r => r.fulfill({ json: { task_id: 'task-e2e' } }));
  await page.route('**/api/tasks/task-e2e?**', r => { polls++; r.fulfill({ json: polls < 2 ? { status: 'running', events: [{ type: 'tool', message: 'project_inspect' }], next: 1 } : { status: 'done', events: [], next: 1, result: { text: 'It is a Next.js app with one client Counter component.' } } }); });
  await page.locator('.ds-v34-chip', { hasText: 'Explain project' }).click();
  page.once('dialog', d => d.accept());
  await page.locator('#dsV33Send').click();
  await page.waitForFunction(() => /Waiting for next prompt/.test(document.querySelector('#dsV33AgentState')?.textContent || ''), null, { timeout: 15000 });
  assert.equal(await page.locator('#dsV33Prompt').inputValue(), '');
  assert.match(await page.locator('#dsV34Step').innerText(), /3 of 3/);
  assert.equal(await page.locator('#dsV33Stop').isDisabled(), true);
  assert.match(await page.locator('#dsV33AgentTimeline').innerText(), /Next\.js app/);
  step('stubbed agent task runs once, shows result, returns to "Waiting for next prompt"');
  await page.evaluate(() => document.querySelector('#dsV33AgentPanel').scrollIntoView({ block: 'end' }));
  await page.screenshot({ path: path.join(out, '04-task-finished-next-prompt.png') });
  page.once('dialog', d => d.accept());
  await page.locator('#dsTrust').click();
  await page.waitForFunction(() => /2 of 3/.test(document.querySelector('#dsV34Step')?.textContent || ''));
  await page.locator('.ds-v34-chip', { hasText: 'Add tests' }).click();
  assert.equal(await page.locator('#dsV33Send').isDisabled(), true);
  step('revoking trust returns guide to 2 of 3 and disables Run');
  page.once('dialog', d => d.accept());
  await page.locator('#dsTrust').click();
  await page.waitForFunction(() => /3 of 3/.test(document.querySelector('#dsV34Step')?.textContent || ''));
  // Narrow width.
  await page.setViewportSize({ width: 820, height: 1000 }); await delay(400);
  const ov = await page.evaluate(() => { const v = document.querySelector('#view .page'); return [v.scrollWidth, v.clientWidth]; });
  console.log('narrow overflow', ov);
  await page.evaluate(() => document.querySelector('.ds-v33-title').scrollIntoView({ block: 'start' })); await delay(200);
  await page.screenshot({ path: path.join(out, '05-narrow-820.png') });
  await page.setViewportSize({ width: 420, height: 900 }); await delay(400);
  await page.evaluate(() => document.querySelector('.ds-v33-title').scrollIntoView({ block: 'start' })); await delay(200);
  await page.screenshot({ path: path.join(out, '06-phone-420.png') });
  const ov2 = await page.evaluate(() => { const v = document.querySelector('#view .page'); return [v.scrollWidth, v.clientWidth]; });
  console.log('phone overflow', ov2);
  assert.deepEqual(errors, [], 'page errors: ' + errors.join('; '));
  console.log('E2E passed:', findings.length, 'steps');
  await browser.close(); server.kill();
})().catch(async e => { console.error(e); console.error(log.slice(-2000)); server.kill(); process.exit(1); });

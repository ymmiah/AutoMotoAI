// Project map (V37-V40 "polyglot intelligence"): the guided steps in Developer Studio > Tools against the
// real local engine and a small polyglot project (TypeScript frontend, Python API, SQL, Cargo + npm
// workspaces). Checks: five steps, the map and trace ring cards are the same 46px unit on desktop, tablet
// and phone, project text never becomes HTML, the rename shows the exact change in a confirm dialog
// before it writes, undo puts the file back, and every command has a copy button.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { mkdtempSync, rmSync, mkdirSync, writeFileSync, readFileSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');
const { randomBytes } = require('node:crypto');
const root = path.resolve(__dirname, '../../..');
const data = mkdtempSync(path.join(tmpdir(), 'automoto-polyglot-'));
const ws = path.join(data, 'ws'); const proj = path.join(ws, 'polyapp');
const INJECT = '<img src=x onerror=alert(1)>';
const files = {
  'package.json': '{"name":"polyapp","private":true,"workspaces":["web"]}',
  'Cargo.toml': '[workspace]\nmembers = ["native"]\n',
  'web/package.json': '{"name":"web","scripts":{"build":"vite build"}}',
  'web/src/api.ts': "export async function loadUsers() { return fetch('/api/users'); }\n" +
    "export const getUser = (id: number) => fetch(`/api/users/${id}`);\n" +
    `export const odd = () => fetch('/api/${INJECT}');\n`,
  'web/src/App.tsx': "import { loadUsers } from './api';\n// loadUsers in a comment\nexport const App = () => loadUsers();\n",
  'api/__init__.py': '',
  'api/main.py': "from fastapi import FastAPI\nfrom .models import User\napp = FastAPI()\n\n@app.get('/api/users')\ndef list_users():\n    return User\n\n@app.get('/api/users/{user_id}')\ndef get_user(user_id: int):\n    return User\n",
  'api/models.py': "from django.db import models\n\nclass User(models.Model):\n    pass\n",
  'db/schema.sql': 'CREATE TABLE users (id INT PRIMARY KEY);\nCREATE TABLE orders (id INT, user_id INT REFERENCES users(id));\n',
  'native/Cargo.toml': '[package]\nname = "native"\n\n[dependencies]\npyo3 = "0.22"\n',
  'native/src/lib.rs': 'use pyo3::prelude::*;\n#[pyfunction]\nfn total(a: i64) -> i64 { a }\n',
};
for (const [rel, text] of Object.entries(files)) { mkdirSync(path.dirname(path.join(proj, rel)), { recursive: true }); writeFileSync(path.join(proj, rel), text); }
const appBefore = files['web/src/App.tsx'];
const token = randomBytes(32).toString('hex');
const port = 8883, base = `http://127.0.0.1:${port}`;
const py = process.env.PYTHON || 'python';
const env = { ...process.env, AUTOMOTO_DATA_DIR: data, AUTOMOTO_LAUNCH_TOKEN: token, AUTOMOTO_SANDBOX: 'local', AUTOMOTO_RATE_LIMIT: '10000', AUTOMOTO_WORKSPACE: ws };
const server = spawn(py, ['-m', 'automoto', 'serve', '--no-browser', '--port', String(port)], { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'] });
let log = ''; server.stdout.on('data', d => { log += d; }); server.stderr.on('data', d => { log += d; });
const delay = ms => new Promise(r => setTimeout(r, ms));
async function openMap(page, compact) {
  await page.evaluate(() => document.querySelector('.nav [data-page="developer"]').click());
  await page.locator('#dsxRoot').waitFor();
  await page.evaluate(p => { document.querySelector('#dsPath').value = p; document.querySelector('#dsOpen').click(); }, proj);
  await page.waitForFunction(() => /polyapp/.test(document.querySelector('#dsxProjectName')?.textContent || ''));
  await page.keyboard.press('Escape');
  if (compact) await page.locator('#dsxNavTools').click(); else await page.locator('#dsxTools').click();
  await page.locator('.dsx-card[data-tool="polyglot"]').click();
  await page.locator('#dsxToolDetail .dsp .dsb-steps').waitFor();
  await page.locator('.dsp .btn', { hasText: 'Map my project' }).click();
  await page.locator('.dsp .dsb-check').first().waitFor();
}
const ringBox = page => page.evaluate(() => {
  const c = document.querySelector('.dsp .dsb-check'), r = c.querySelector('.dsb-ring'), b = c.querySelector('.dsb-check-btn');
  const cr = c.getBoundingClientRect(), rr = r.getBoundingClientRect(), br = b.getBoundingClientRect();
  return { ring: [Math.round(rr.width), Math.round(rr.height)], gap: Math.round(br.left - rr.right), padL: Math.round(rr.left - cr.left), maxW: Math.round(cr.width) <= 440 };
});
let browser;
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
  browser = await chromium.launch({ ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}), args: ['--no-sandbox'] });
  const errors = []; const boxes = {};
  for (const [name, vp, compact] of [['desktop', { width: 1280, height: 800 }, false], ['tablet', { width: 820, height: 1180 }, true], ['phone', { width: 390, height: 844 }, true]]) {
    const ctx = await browser.newContext({ viewport: vp, colorScheme: 'dark', reducedMotion: 'reduce', ...(name === 'phone' ? { hasTouch: true, isMobile: true } : {}) });
    const page = await ctx.newPage(); page.on('pageerror', e => errors.push(e.message));
    const dialogs = []; page.on('dialog', d => { dialogs.push(d.message()); d.accept(); });
    const launch = await (await fetch(`${base}/api/session/launch`, { method: 'POST', headers: H, body: '{}' })).json().catch(() => null);
    await page.goto(launch?.url || `${base}/?launch=${token}`);
    await page.locator('.nav [data-page="developer"]').waitFor({ state: 'attached' });
    await openMap(page, compact);
    boxes[name] = await ringBox(page);
    if (name === 'desktop') {
      assert.equal(await page.locator('.dsp .dsb-step').count(), 5, 'five guided steps');
      assert.match(await page.locator('.dsp .dsb-check-text b').first().textContent(), /^Mapped \d+ files$/);
      assert.equal(await page.locator('.dsp .dsb-ring b').first().textContent(), await page.evaluate(() => document.querySelector('.dsp .dsb-ring-of').textContent.replace('of ', '')), 'all files read');
      assert.equal(await page.locator('.dsp details[open]').count(), 0, 'details start collapsed');
      assert.match(await page.locator('.dsp .dsb-check-text p').first().textContent(), /TypeScript|Python/);
      await page.locator('.dsp .btn', { hasText: 'Check the connections' }).click();
      await page.locator('.dsp .dsb-check-text b', { hasText: 'connections work' }).waitFor();
      assert.match(await page.locator('.dsp').textContent(), /2 of 3 connections work/);
      assert.ok(await page.locator('.dsp .dsb-step').nth(1).locator('.dsb-step-main > .dsp-few > .dsp-items > li').count() <= 3, 'at most 3 visible');
      assert.match(await page.locator('.dsp').textContent(), /list_users/);
      assert.match(await page.locator('.dsp').textContent(), /Django model/);
      assert.equal(await page.locator('.dsp img').count(), 0, 'project text never becomes HTML');
      // Rename: preview -> confirm dialog with the exact files -> written -> undo puts it back.
      const inputs = page.locator('.dsp .dsb-step').nth(3).locator('input');
      await inputs.nth(0).fill('loadUsers'); await inputs.nth(1).fill('fetchUsers');
      await page.locator('.dsp .btn', { hasText: /^Preview$/ }).click();
      await page.locator('.dsp .dsp-result b', { hasText: /changes? in 2 files/ }).waitFor();
      await page.locator('.dsp summary', { hasText: 'Show the changes' }).click();
      await page.waitForFunction(() => { const c = [...document.querySelectorAll('.dsp .dsp-code')]; return c.length && c.every(p => p.querySelector('.copy-anchor button')); });
      assert.equal(readFileSync(path.join(proj, 'web/src/App.tsx'), 'utf8'), appBefore, 'preview changes nothing');
      await page.locator('.dsp .btn', { hasText: /^Rename$/ }).click();
      await page.locator('.dsp .dsp-result b', { hasText: 'Renamed loadUsers to fetchUsers' }).waitFor();
      assert.match(dialogs.at(-1), /Rename loadUsers to fetchUsers\?/); assert.match(dialogs.at(-1), /web\/src\/App\.tsx \(2\)/);
      const after = readFileSync(path.join(proj, 'web/src/App.tsx'), 'utf8');
      assert.match(after, /import \{ fetchUsers \}/); assert.match(after, /\/\/ loadUsers in a comment/);
      await page.locator('.dsp .btn', { hasText: 'Undo rename' }).click();
      await page.locator('.dsp .dsa-alert.ok', { hasText: 'Put back' }).waitFor();
      assert.equal(readFileSync(path.join(proj, 'web/src/App.tsx'), 'utf8'), appBefore, 'undo restores the file');
      // Packages: commands are shown with copy buttons, never run.
      await page.locator('.dsp .btn', { hasText: 'Show the parts' }).click();
      await page.locator('.dsp .dsp-big', { hasText: 'parts' }).waitFor();
      assert.match(await page.locator('.dsp').textContent(), /Languages that work together: Rust ↔ Python/);
      await page.locator('.dsp summary', { hasText: 'How to build each part' }).click();
      assert.match(await page.locator('.dsp').textContent(), /npm workspaces/);
      assert.match(await page.locator('.dsp').textContent(), /Rust ↔ Python \(PyO3\)/);
      await page.waitForFunction(() => { const c = [...document.querySelectorAll('.dsp .dsp-code')]; return c.length >= 3 && c.every(p => p.querySelector('.copy-anchor button')); });
      assert.match(await page.locator('.dsp').textContent(), /cd web && npm run build/);
    } else {
      const wide = await page.evaluate(() => document.querySelector('#dsxToolDetail').scrollWidth - document.querySelector('#dsxToolDetail').clientWidth);
      assert.ok(wide <= 1, `no sideways scroll on ${name} (${wide}px)`);
    }
    await ctx.close();
  }
  for (const n of ['tablet', 'phone']) assert.deepEqual(boxes[n], boxes.desktop, `ring card measures the same on ${n}: ${JSON.stringify(boxes)}`);
  assert.deepEqual(boxes.desktop.ring, [46, 46]);
  assert.deepEqual(errors, []);
  console.log('polyglot UI ok', JSON.stringify(boxes.desktop));
})().catch(e => { console.error(e); process.exitCode = 1; }).finally(async () => {
  await browser?.close().catch(() => {});
  server.kill();
  await delay(300);
  try { rmSync(data, { recursive: true, force: true }); } catch { /* Windows may still hold files */ }
});

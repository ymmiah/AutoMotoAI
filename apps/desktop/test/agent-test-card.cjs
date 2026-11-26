// V55: the chat-first approval card for a bounded agent test run. Loads the real
// developer-workspace.js module in Chromium (no server, no model) and checks that the card
// shows the server-chosen command as text, that "Run tests once" decides exactly once, that
// Skip says the tests were not checked, and that forged or incomplete evidence cannot be approved.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');

const STATIC = path.resolve(__dirname, '../../../automoto/web/static');
const ORIGIN = 'http://automoto.test';
const GOOD = {
  recipe: 'python:pytest', label: 'pytest', prepared_by_server: true, test_run: true,
  command: 'python3 -m pytest -q -rA -p no:cacheprovider <script>alert(1)</script>',
  command_sha256: 'a'.repeat(64), time_limit_seconds: 120, source: 'pytest configuration or test_*.py files',
  isolation: 'Runs in its own process group. This is not a sandbox.', os_sandbox: false,
};

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.route(`${ORIGIN}/**`, route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/app.css"><link rel="stylesheet" href="/static/developer-studio.css"><body><main id="m" style="padding:16px"></main>' });
    const file = path.join(STATIC, path.normalize(url.pathname.replace(/^\/static\//, '')));
    if (!file.startsWith(STATIC)) return route.fulfill({ status: 404, body: '' });
    const type = file.endsWith('.css') ? 'text/css' : 'text/javascript';
    try { return route.fulfill({ contentType: type, body: readFileSync(file) }); }
    catch { return route.fulfill({ status: 404, body: '' }); }
  });
  await page.goto(`${ORIGIN}/`);
  await page.evaluate(async () => {
    const mod = await import('/static/developer-workspace.js');
    window.__decisions = [];
    window.__card = (args) => {
      const card = mod.approvalCard({ name: 'developer_agent_test', args }, {
        api: async () => { throw new Error('no network in this test'); },
        getProject: () => ({ project: '/w/demo' }),
        decide: (allow) => { window.__decisions.push(allow); return Promise.resolve(); },
        showFile: () => false,
      });
      document.getElementById('m').replaceChildren(card);
    };
  });

  // Valid server evidence: the command is shown as text, and one click approves once.
  await page.evaluate(args => window.__card(args), GOOD);
  const run = page.getByRole('button', { name: 'Run tests once' });
  assert.equal(await run.isEnabled(), true);
  assert.match(await page.locator('#m').innerText(), /Run the tests\?/);
  assert.match(await page.locator('#m').innerText(), /Stops after 120 seconds/);
  assert.match(await page.locator('#m').innerText(), /not a sandbox/);
  assert.equal(await page.locator('#m code').innerText(), GOOD.command);
  assert.equal(await page.locator('#m script').count(), 0, 'command text is never parsed as HTML');
  await run.click();
  await page.waitForFunction(() => window.__decisions.length === 1);
  assert.deepEqual(await page.evaluate(() => window.__decisions), [true]);
  await page.getByText('Approved once · running tests').waitFor();
  assert.equal(await page.getByRole('button', { name: 'Run tests once' }).count(), 0, 'no second approval');

  // Skip says plainly that the tests were not checked.
  await page.evaluate(args => { window.__decisions = []; window.__card(args); }, GOOD);
  await page.getByRole('button', { name: 'Skip' }).click();
  await page.getByText('Not run. The tests were not checked.').waitFor();
  assert.deepEqual(await page.evaluate(() => window.__decisions), [false]);

  // Forged or incomplete evidence cannot be approved.
  for (const bad of [
    { ...GOOD, prepared_by_server: false },
    { ...GOOD, test_run: undefined },
    { ...GOOD, command: '' },
    { ...GOOD, command_sha256: 'nothex' },
    { ...GOOD, time_limit_seconds: 0 },
  ]) {
    await page.evaluate(args => { window.__decisions = []; window.__card(args); }, bad);
    assert.equal(await page.getByRole('button', { name: 'Run tests once' }).isDisabled(), true, JSON.stringify(bad));
    assert.match(await page.locator('#m').innerText(), /approval blocked/);
  }

  // No sideways scroll at phone width.
  await page.evaluate(args => window.__card(args), GOOD);
  const wide = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  assert.equal(wide, false, 'the card fits a 390px phone');

  if (process.env.CARD_SHOT) await page.locator('#m').screenshot({ path: process.env.CARD_SHOT });
  await browser.close();
  console.log('agent-test-card: ok');
})().catch(err => { console.error(err); process.exit(1); });

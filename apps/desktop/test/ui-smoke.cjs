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
  // This smoke test exercises many renderer previews in one minute. Use a
  // higher limit only in its isolated ephemeral server, never in production.
  env: { ...process.env, AUTOMOTO_DATA_DIR: data, AUTOMOTO_LAUNCH_TOKEN: token,
    AUTOMOTO_SANDBOX: 'local', AUTOMOTO_RATE_LIMIT: '10000' },
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
  assert.match(await page.locator('.hero h2').innerText(), /A little idea/);
  assert.match(await page.locator('.hero p').innerText(), /don't pick the tools/);
  assert.equal((await page.locator('#modeSeg [data-mode="agent"]').innerText()).trim(), 'Assistant');
  assert.equal(await page.locator('.chip').count(), 8);
  assert.equal(await page.locator('#msgs').evaluate(el => el.scrollTop), 0, 'home must start at its heading');
  await page.locator('#msgs').evaluate(el => { el.scrollTop = el.scrollHeight; });
  assert.equal(await page.locator('#jumpLatest').isVisible(), false, 'starting ideas must not offer a latest reply');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  assert.equal(await page.locator('.chip').count(), 3);
  await page.getByRole('button', { name: 'Make slides' }).click();
  assert.match(await page.locator('#composerInput').inputValue(), /PowerPoint/);
  await page.locator('#composerInput').fill('Keep this draft while I check settings');
  await page.locator('.nav [data-page="settings"]').click();
  await page.locator('.set-nav').waitFor();
  assert.match(await page.locator('[data-set-panel="assistant"]').innerText(), /You write the request/);
  assert.equal(await page.locator('[data-set-panel="assistant"] a[href="#/tools"]').count(), 0, 'the assistant section must not list tools');
  await page.locator('.set-nav [data-set="offline"]').click();
  await page.waitForFunction(() => /Running|Installed|Not installed|Could not check/.test(document.querySelector('#offlineBody')?.innerText || ''));
  assert.equal(await page.locator('.ai-status').isVisible(), true);
  assert.equal(await page.locator('#offlineSw').isVisible(), true);
  await page.screenshot({ path: path.join(output, 'settings-offline.png') });
  await page.locator('.set-nav [data-set="look"]').click();
  await page.locator('#themeSeg').waitFor();
  await page.screenshot({ path: path.join(output, 'settings-appearance.png') });
  await page.locator('.set-nav [data-set="more"]').click();
  assert.equal(await page.locator('[data-set-panel="more"] a[href="#/tools"]').isVisible(), true);
  await page.locator('.set-nav [data-set="assistant"]').click();
  await page.locator('#newChat').click();
  await page.waitForFunction(() => document.querySelector('#composerInput')?.value === 'Keep this draft while I check settings');
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
  await page.waitForFunction(() => document.querySelector('#composerInput')?.value === 'Keep this draft while I check settings');
  assert.equal(await page.locator('#composerInput').inputValue(), 'Keep this draft while I check settings');
  await page.locator('#composerInput').fill('');
  await page.screenshot({ path: path.join(output, 'workspace-dark.png') });
  // Document Assistant v1: real Office publishing, editable draft roundtrip,
  // uploaded document inspection and a non-destructive DOCX revision.
  await page.locator('.nav [data-page="documents"]').click();
  await page.locator('#daSource').waitFor();
  assert.equal(await page.locator('#daMode').innerText(), 'Editable draft');
  await page.locator('#daName').fill('Document smoke report');
  await page.locator('#daSource').fill('# Document smoke report\n\n## Findings\n\nOriginal body wording for review.');
  assert.match(await page.locator('#daPaper h1').innerText(),/Document smoke report/);
  const savingDocument=page.waitForResponse(r=>r.url().includes('/api/documents/save')&&r.request().method()==='POST');
  await page.locator('#daSave').click();
  const savedDocument=await savingDocument;
  assert.equal(savedDocument.status(),200,await savedDocument.text());
  const savedDraft=(await savedDocument.json()).path;
  assert.ok(savedDraft.endsWith('.document.json'));
  await page.waitForFunction(path=>[...document.querySelectorAll('#daLibrary [data-da-open]')]
    .some(x=>x.dataset.daOpen===path),savedDraft);
  const exportingDocument=page.waitForResponse(r=>r.url().includes('/api/documents/export')&&r.request().method()==='POST');
  await page.locator('#daExportWord').click();
  const exportedDocument=await exportingDocument;
  assert.equal(exportedDocument.status(),200,await exportedDocument.text());
  const wordFile=(await exportedDocument.json()).path;
  assert.ok(wordFile.endsWith('.docx'));
  const wordDownload=await page.request.get(base+'/api/files/download?path='+encodeURIComponent(wordFile));
  assert.equal(wordDownload.status(),200);
  const wordBytes=await wordDownload.body();
  assert.equal(wordBytes.subarray(0,2).toString('ascii'),'PK');
  // Reopen the native Markdown draft to verify its source was not flattened.
  await page.locator('#daSource').fill('Temporary unsaved text');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#daLibrary [data-da-open="'+savedDraft+'"]').click();
  await page.waitForFunction(()=>document.querySelector('#daSource')?.value.includes('Original body wording for review.'));
  assert.equal(await page.locator('#daName').inputValue(),'Document smoke report');
  // v2: native heading outline, table operations, layout, undo/redo and
  // persisted layout settings in a brand-new backward-compatible draft.
  assert.equal(await page.locator('#daOutline [data-da-heading]').count(),2);
  await page.locator('#daHeadingLevel').selectOption('3');
  await page.locator('#daSource').evaluate(el=>{
    const start=el.value.indexOf('Findings');el.focus();
    el.setSelectionRange(start,start);
  });
  await page.locator('[data-da-insert="heading"]').click();
  assert.match(await page.locator('#daSource').inputValue(),/### Findings/);
  assert.equal(await page.locator('#daPaper h3').count(),1);
  await page.locator('#daSource').evaluate(el=>{
    el.focus();el.setSelectionRange(el.value.length,el.value.length);
  });
  await page.locator('[data-da-insert="table"]').click();
  assert.equal(await page.locator('#daPaper .da-table').count(),1);
  assert.equal(await page.locator('#daPaper .da-table th').count(),3);
  await page.locator('#daSource').evaluate(el=>{
    const cursor=el.value.indexOf('Value 1');el.focus();el.setSelectionRange(cursor,cursor);
  });
  await page.locator('[data-da-insert="table-row"]').click();
  assert.equal(await page.locator('#daPaper .da-table tr').count(),4);
  await page.locator('#daOrientation').selectOption('landscape');
  await page.locator('#daPageSize').selectOption('Letter');
  await page.locator('#daFont').selectOption('Georgia');
  await page.locator('#daMargins').fill('3.1');
  await page.locator('#daMargins').press('Tab');
  await page.locator('#daFontSize').fill('13');
  await page.locator('#daFontSize').press('Tab');
  await page.locator('#daPageNumbers').uncheck();
  assert.equal(await page.locator('#daPaper').getAttribute('data-orientation'),'landscape');
  await page.locator('#daUndo').click();
  assert.equal(await page.locator('#daPageNumbers').isChecked(),true);
  await page.locator('#daRedo').click();
  assert.equal(await page.locator('#daPageNumbers').isChecked(),false);
  const savingV2=page.waitForResponse(r=>r.url().includes('/api/documents/save')&&r.request().method()==='POST');
  await page.locator('#daSave').click();
  const v2Response=await savingV2;
  assert.equal(v2Response.status(),200,await v2Response.text());
  const savedV2=(await v2Response.json()).path;
  const reopenedV2=await page.request.get(base+'/api/documents/open?path='+encodeURIComponent(savedV2));
  assert.equal(reopenedV2.status(),200);
  const v2Data=await reopenedV2.json();
  assert.equal(v2Data.options.orientation,'landscape');
  assert.equal(v2Data.options.page_size,'Letter');
  assert.equal(v2Data.options.font,'Georgia');
  assert.equal(v2Data.options.font_size,13);
  assert.equal(v2Data.options.page_numbers,false);
  assert.match(v2Data.markdown,/\| Column A \| Column B \|/);
  await page.screenshot({path:path.join(output,'document-assistant-v2-editor.png')});
  // v4 professional publishing uses only human-entered source details and a
  // server-side real DOCX preflight, without altering imported originals.
  await page.locator('#daPublication summary').click();
  await page.locator('#daTemplate').selectOption('academic-report');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#daApplyTemplate').click();
  assert.match(await page.locator('#daSource').inputValue(),/## Methodology/);
  await page.locator('#daUndo').click();
  assert.match(await page.locator('#daSource').inputValue(),/\| Column A \| Column B \|/);
  await page.locator('#daRefStyle').selectOption('ieee');
  await page.locator('#daPubAuthor').fill('Example Author');
  await page.locator('#daPubAuthor').press('Tab');
  await page.locator('#daPubHeader').fill('Academic review');
  await page.locator('#daPubHeader').press('Tab');
  await page.locator('#daCover').check();
  await page.locator('#daRefId').fill('author2025');
  await page.locator('#daRefAuthors').fill('Author, A.');
  await page.locator('#daRefYear').fill('2025');
  await page.locator('#daRefTitle').fill('Verified source title');
  await page.locator('#daRefType').selectOption('book');
  await page.locator('#daRefPublisher').fill('User-supplied publisher');
  await page.locator('#daAddReference').click();
  assert.equal(await page.locator('#daReferenceList .da-ref-card').count(),1);
  await page.locator('#daSource').evaluate(el=>{
    el.focus();el.setSelectionRange(el.value.length,el.value.length);
  });
  await page.locator('[data-da-cite="author2025"]').click();
  assert.match(await page.locator('#daSource').inputValue(),/\[@author2025\]$/);
  const checkingWord=page.waitForResponse(r=>r.url().includes('/api/documents/preflight')&&r.request().method()==='POST');
  await page.locator('#daPreflight').click();
  const preflight=await checkingWord;
  assert.equal(preflight.status(),200,await preflight.text());
  assert.equal((await preflight.json()).reference_count,1);
  const savingV4=page.waitForResponse(r=>r.url().includes('/api/documents/save')&&r.request().method()==='POST');
  await page.locator('#daSave').click();
  const v4Saved=await savingV4;
  assert.equal(v4Saved.status(),200,await v4Saved.text());
  const v4File=(await v4Saved.json()).path;
  const v4Opened=await page.request.get(base+'/api/documents/open?path='+encodeURIComponent(v4File));
  assert.equal(v4Opened.status(),200);
  const v4Draft=await v4Opened.json();
  assert.equal(v4Draft.publication.reference_style,'ieee');
  assert.equal(v4Draft.publication.references[0].title,'Verified source title');
  assert.match(v4Draft.markdown,/\[@author2025\]/);
  await page.screenshot({path:path.join(output,'document-assistant-v4-publication.png')});
  await page.locator('#daImportFile').setInputFiles({
    name:'review-import.docx',
    mimeType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    buffer:wordBytes
  });
  await page.waitForFunction(()=>document.querySelector('#daMode')?.textContent?.includes('Read-only Office'));
  assert.match(await page.locator('#daExtracted').innerText(),/Original body wording for review/);
  assert.equal(await page.locator('#daEditBody').isVisible(),false);
  assert.equal(await page.locator('#daReplace').isVisible(),true);
  // v5: real DOCX structure inspection and explicit create-only copy editing.
  await page.locator('#daRichParagraph option').first().waitFor();
  assert.equal(await page.locator('#daRich').isVisible(),true);
  await page.locator('#daRich summary').click();
  await page.locator('#daRichAction').selectOption('set_style');
  await page.locator('#daRichParagraph').selectOption('2');
  await page.locator('#daRichStyle').selectOption('Heading 3');
  const editingCopy=page.waitForResponse(r=>r.url().includes('/api/documents/docx/revise')&&r.request().method()==='POST');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#daRichSave').click();
  const updatedWord=await editingCopy;
  assert.equal(updatedWord.status(),200,await updatedWord.text());
  const richCopyPath=(await updatedWord.json()).path;
  assert.ok(richCopyPath.endsWith('.docx'));
  const richCopyDownload=await page.request.get(base+'/api/files/download?path='+encodeURIComponent(richCopyPath));
  assert.equal(richCopyDownload.status(),200);
  assert.equal((await richCopyDownload.body()).subarray(0,2).toString('ascii'),'PK');
  assert.match(await page.locator('#daRichStatus').innerText(),/separate Word copy/i);
  const importPath=await page.locator('#daLibrary [data-da-open]')
    .filter({hasText:'review-import.docx'}).first().getAttribute('data-da-open');
  const untouchedOriginal=await page.request.get(base+'/api/files/download?path='+
    encodeURIComponent(importPath));
  assert.equal(untouchedOriginal.status(),200);
  assert.ok((await untouchedOriginal.body()).equals(wordBytes),
    'the original imported Word content must remain byte-for-byte unchanged');
  await page.screenshot({path:path.join(output,'document-assistant-v5-word-copy.png')});
  await page.locator('#daFind').fill('Original body wording');
  await page.locator('#daReplaceWith').fill('Reviewed and approved wording');
  page.once('dialog',dialog=>dialog.accept());
  const revision=page.waitForResponse(r=>r.url().includes('/api/documents/replace-copy')&&r.request().method()==='POST');
  await page.locator('#daReplaceCopy').click();
  const revisedDocument=await revision;
  assert.equal(revisedDocument.status(),200,await revisedDocument.text());
  const revisionPath=(await revisedDocument.json()).path;
  assert.notEqual(revisionPath,wordFile);
  assert.match(await page.locator('#daStatus').innerText(),/revised copy/i);
  await page.screenshot({path:path.join(output,'document-assistant-v1-workspace.png')});
  // v3: deterministic intercepted local-AI responses. Python tests exercise
  // the real model-provider contract; browser tests prove explicit approval,
  // read-only imported summaries and reversible edit suggestions.
  assert.equal(await page.locator('#daAIAction').inputValue(),'summary',
    'imported Office documents must never expose a rewrite action');
  assert.equal(await page.locator('#daAIAction option[value="rewrite"]').isDisabled(),true);
  const quote='Original body wording for review.';
  const originalExtract=await page.locator('#daExtracted').innerText();
  assert.ok(originalExtract.includes(quote));
  let modelRequests=0;
  await page.route('**/api/documents/ai/review',async route=>{
    modelRequests++;
    const request=route.request().postDataJSON();
    const summary=request.mode==='summary';
    const data=summary
      ?{mode:'summary',provider:'ollama-local',model:'ci-local-stub',requires_approval:true,
        applied:false,source:'verified-import',selection:{start:0,end:originalExtract.length},
        sha256:request.source_sha256,proposal:null,changed:false,
        evidence:[{claim:'The imported document contains a statement about review.',
          quote,offset:originalExtract.indexOf(quote)}],
        explanation:'Verbatim source excerpt verified.',limitations:'Verify AI interpretation.'}
      :{mode:'proofread',provider:'ollama-local',model:'ci-local-stub',requires_approval:true,
        applied:false,source:'editable',selection:{start:request.start,end:request.end},
        sha256:request.sha256,proposal:'This sentence has an error.',changed:true,
        evidence:[],explanation:'Corrected grammar.',limitations:'Review the suggested wording.'};
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.locator('#daAIRun').click();
  await page.locator('#daAIResult .da-ai-evidence blockquote').waitFor();
  assert.equal(await page.locator('#daAIApply').isVisible(),false);
  assert.match(await page.locator('#daAIEvidence').innerText(),/Original body wording/);
  await page.locator('#daNew').click();
  await page.locator('#daSource').fill('This sentences has a error.\n\nThe source remains unchanged.');
  await page.locator('#daAIAction').selectOption('proofread');
  await page.locator('#daSource').evaluate(el=>{
    el.focus();el.setSelectionRange(0,'This sentences has a error.'.length);
  });
  const originalAIText=await page.locator('#daSource').inputValue();
  await page.locator('#daAIRun').click();
  await page.locator('#daAIProposal').waitFor({state:'visible'});
  assert.equal(await page.locator('#daAIProposal').inputValue(),'This sentence has an error.');
  assert.equal(await page.locator('#daSource').inputValue(),originalAIText,
    'review must not automatically change document content');
  assert.equal(await page.locator('#daAIApply').isVisible(),true);
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#daAIApply').click();
  assert.match(await page.locator('#daSource').inputValue(),/^This sentence has an error\./);
  assert.match(await page.locator('#daSource').inputValue(),/The source remains unchanged/);
  await page.locator('#daUndo').click();
  assert.equal(await page.locator('#daSource').inputValue(),originalAIText);
  await page.locator('#daRedo').click();
  assert.match(await page.locator('#daSource').inputValue(),/^This sentence has an error\./);
  assert.equal(modelRequests,2);
  // A stale review must be refused even when a model returns a valid proposal.
  await page.locator('#daAIClear').click();
  await page.locator('#daSource').evaluate(el=>{
    el.focus();el.setSelectionRange(0,'This sentence has an error.'.length);
  });
  await page.locator('#daAIRun').click();
  await page.locator('#daAIProposal').waitFor({state:'visible'});
  await page.locator('#daSource').fill('New text written while review was open.');
  await page.locator('#daAIApply').click();
  assert.equal(await page.locator('#daSource').inputValue(),
    'New text written while review was open.','stale AI proposal must not overwrite fresh edits');
  await page.screenshot({path:path.join(output,'document-assistant-v3-offline-ai-review.png')});
  await page.locator('#newChat').click();
  await page.locator('.hero h2').waitFor();
  // Visual Studio uses the genuine Python scene renderer, not a mock screenshot.
  await page.locator('.nav [data-page="visual"]').click();
  await page.locator('#vsPreview').waitFor();
  await page.waitForFunction(() => document.querySelector('#vsPreview')?.naturalWidth > 0);
  assert.equal(await page.locator('#vsStage').getAttribute('aria-busy'), 'false');
  assert.equal(await page.locator('#vsElement option').count() > 4, true);
  await page.screenshot({ path: path.join(output, 'visual-studio-workflow.png') });
  // New layer stack: selecting, locking and visibility must affect actual exports.
  assert.ok(await page.locator('#vsLayers [data-layer-key="group:stage0"]').count() >= 3,
    'workflow group layer controls must exist');
  await page.locator('#vsLayers [data-layer-key="group:stage0"][data-layer-act="select"]').click();
  await page.locator('#vsLayers [data-layer-key="group:stage0"][data-layer-act="lock"]').click();
  assert.equal(await page.locator('#vsDelete').isDisabled(), true, 'locked layer forbids deletion');
  await page.locator('#vsLayers [data-layer-key="group:stage0"][data-layer-act="lock"]').click();
  assert.equal(await page.locator('#vsDelete').isDisabled(), false, 'unlock restores editing');
  await page.locator('#vsLayers [data-layer-key="group:stage0"][data-layer-act="visibility"]').click();
  assert.equal(await page.locator('#vsLayers [data-layer-key="group:stage0"][data-layer-act="visibility"]').getAttribute('aria-pressed'), 'true');
  await page.locator('#vsLayers [data-layer-key="group:stage0"][data-layer-act="visibility"]').click();
  // Drag the native corner grip and verify the editable source geometry changes.
  const widthBefore = Number(await page.locator('#vsProperties [data-key="w"]').inputValue());
  const grip = await page.locator('.vs-resize-handle').boundingBox();
  assert.ok(grip, 'selected grouped card must expose a resize handle');
  await page.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2);
  await page.mouse.down();
  await page.mouse.move(grip.x + grip.width / 2 + 24, grip.y + grip.height / 2 + 13, { steps: 6 });
  await page.mouse.up();
  const widthAfter = Number(await page.locator('#vsProperties [data-key="w"]').inputValue());
  assert.ok(widthAfter > widthBefore, 'drag-resize must update native element width');
  await page.screenshot({ path: path.join(output, 'visual-studio-layers-resize.png') });
  // v10: real keyframe motion on native groups, not CSS-only fake playback.
  await page.locator('#vsFormat').selectOption('gif');
  await page.locator('#vsEffect').selectOption('keyframes');
  assert.equal(await page.locator('#vsTimeline').isVisible(),true);
  assert.equal(await page.locator('.vs-motion-track').count(),3);
  await page.locator('#vsPlayhead').evaluate(input=>{
    input.value='50';input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  await page.locator('[data-motion-add="stage0"]').click();
  assert.equal(await page.locator('[data-motion-select="stage0"] option').count(),3);
  assert.equal(await page.locator('[data-motion-select="stage0"]').inputValue(),'1');
  await page.locator('.vs-motion-track[data-motion-group="stage0"] [data-motion-field="dx"]').fill('45');
  await page.locator('.vs-motion-track[data-motion-group="stage0"] [data-motion-field="dx"]').press('Tab');
  assert.equal(await page.locator('.vs-motion-track[data-motion-group="stage0"] [data-motion-field="dx"]').inputValue(),'45');
  await page.locator('.vs-motion-track[data-motion-group="stage0"] [data-motion-easing="stage0"]').selectOption('ease-in');
  const motionResponse=page.waitForResponse(r=>r.url().includes('/api/visual/studio/animation-preview')&&
    r.request().method()==='POST');
  await page.locator('#vsMotionPlay').click();
  const playback=await motionResponse;
  assert.equal(playback.status(),200,await playback.text());
  assert.match((await playback.json()).image,/^data:image\/gif;base64,/);
  await page.waitForFunction(()=>document.querySelector('#vsPreview')?.src?.startsWith('data:image/gif;base64,'));
  await page.locator('#vsMotionStop').click();
  await page.waitForFunction(()=>document.querySelector('#vsPreview')?.src?.startsWith('data:image/png;base64,')&&
    document.querySelector('#vsStage')?.getAttribute('aria-busy')==='false');
  await page.screenshot({path:path.join(output,'visual-studio-v10-keyframe-timeline.png')});
  // Switching back to the original v2 layer timeline must remain compatible.
  // A sequence timeline exposes group keyframes and renders the selected frame.
  await page.locator('#vsFormat').selectOption('gif');
  await page.locator('#vsEffect').selectOption('sequence');
  assert.equal(await page.locator('#vsTimeline').isVisible(), true);
  assert.equal(await page.locator('#vsTracks input[type="range"]').count(), 3);
  await page.locator('#vsPlayhead').evaluate(input => {
    input.value = '75';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.waitForFunction(() => /Structural checks passed/.test(document.querySelector('#vsStatus')?.textContent || '') &&
    document.querySelector('#vsStage')?.getAttribute('aria-busy') === 'false');
  await page.locator('#vsTimeline').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(output, 'visual-studio-timeline.png') });
  await page.locator('#vsAddText').click();
  await page.locator('#vsProperties textarea[data-key="text"]').fill('Exact source copy');
  await page.locator('#vsProperties textarea[data-key="text"]').press('Tab');
  await page.waitForFunction(() => document.querySelector('#vsStage')?.getAttribute('aria-busy') === 'false');
  await page.locator('#vsSave').click();
  await page.waitForFunction(() => document.querySelectorAll('#vsDraft option').length > 1);
  await page.locator('#vsFormat').selectOption('gif');
  assert.equal(await page.locator('#vsFrames').isVisible(), true);
  assert.equal(await page.locator('#vsEffect').inputValue(), 'sequence', 'timeline setting must survive draft save');
  await page.locator('#vsFrames').fill('10');
  // File format and editability are independent: a GIF can keep native layers.
  await page.locator('#vsOutputMode').selectOption('layered');
  await page.locator('#vsExport').click();
  await page.locator('#vsOutput:not([hidden])').waitFor();
  assert.match(await page.locator('#vsOutput').innerText(), /Download GIF/);
  assert.match(await page.locator('#vsOutput').innerText(), /Download editable layers/);
  await page.waitForFunction(() => document.querySelector('#vsStage')?.getAttribute('aria-busy') === 'false');
  await page.screenshot({ path: path.join(output, 'visual-studio-gif.png') });
  // Every supported picture has an Edit layers action in Files.
  await page.locator('.nav [data-page="files"]').click();
  await page.locator('[data-dir="artifacts"]').first().click();
  await page.locator('[data-dir="artifacts/visual-studio"]').first().click();
  await page.locator('[data-studio-image$=".gif"]').first().click();
  try {
    await page.locator('#vsOutputMode').waitFor({ timeout: 10000 });
  } catch (err) {
    const state = await page.evaluate(() => ({
      hash: location.hash,
      pageTitle: document.querySelector('h1')?.textContent || "",
      outputModeCount: document.querySelectorAll('#vsOutputMode').length,
      notice: document.querySelector('.toast')?.textContent || ""
    }));
    throw new Error('Image layer reopen failed: ' + JSON.stringify({ state, pageErrors: errors, reason: err.message }));
  }
  await page.waitForFunction(() => document.querySelector('#vsPreview')?.naturalWidth > 0 &&
    document.querySelector('#vsStage')?.getAttribute('aria-busy') === 'false');
  assert.equal(await page.locator('#vsOutputMode').inputValue(), 'layered',
    'opening an exported image must restore an editable Visual Studio project');
  assert.ok(await page.locator('#vsElement option').count() > 3,
    'native generated GIF must reopen its independently editable source layers');
  await page.screenshot({ path: path.join(output, 'visual-studio-reopen-layers.png') });
  // Inspection is always review-first: a valid scene is not silently mutated.
  await page.locator('#vsInspect').click();
  await page.locator('#vsRepairReview:not([hidden])').waitFor();
  assert.match(await page.locator('#vsRepairSummary').innerText(), /proposed field changes/);
  await page.locator('#vsDismissRepair').click();
  assert.equal(await page.locator('#vsRepairReview').isVisible(), false);
  await page.screenshot({ path: path.join(output, 'visual-studio-repair-review.png') });
  // v5: repair choices are independent; a partial selection with an
  // unresolved contrast problem must never become applicable.
  await page.locator('#vsTemplate').selectOption('blank');
  for (let i = 0; i < 2; i++) {
    await page.locator('#vsAddText').click();
    await page.locator('#vsProperties [data-key="colour"]').fill('#ffffff');
    await page.locator('#vsProperties [data-key="colour"]').dispatchEvent('change');
  }
  await page.locator('#vsInspect').click();
  await page.locator('#vsRepairReview:not([hidden])').waitFor();
  assert.ok(await page.locator('[data-repair-index]').count() >= 2,
    'two unreadable labels must produce individual selectable corrections');
  assert.equal(await page.locator('#vsRepairOriginal').isVisible(), true,
    'before image must render the actual unmodified flawed canvas');
  await page.locator('#vsRepairNone').click();
  assert.equal(await page.locator('#vsApplyRepair').isDisabled(), true);
  await page.locator('#vsRepairAll').click();
  await page.locator('#vsRepairImage:visible').waitFor();
  assert.equal(await page.locator('#vsApplyRepair').isEnabled(), true);
  await page.locator('[data-repair-index]').first().uncheck();
  await page.waitForFunction(() =>
    /Cannot apply this selection/.test(document.querySelector('#vsRepairRemaining')?.textContent || ''));
  assert.equal(await page.locator('#vsApplyRepair').isDisabled(), true,
    'selecting one contrast fix must not bypass the remaining quality issue');
  await page.locator('#vsRepairAll').click();
  await page.locator('#vsRepairImage:visible').waitFor();
  await page.screenshot({ path: path.join(output, 'visual-studio-v5-selective-before-after.png') });
  await page.locator('#vsApplyRepair').click();
  assert.equal(await page.locator('#vsRepairReview').isVisible(), false);
  assert.equal(await page.locator('#vsUndo').isEnabled(), true);
  await page.locator('#vsUndo').click();
  assert.equal(await page.locator('#vsElement option').count(), 3,
    'undo must restore original editable objects without losing layers');
  // v6: exercise the real review UI contract with a stubbed model response;
  // no downloaded Ollama model or cloud provider is required in CI.
  await page.route('**/api/visual/studio/ai-review', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({
        model: 'test-local-vision', provider: 'ollama-local',
        changed: true, requires_approval: true,
        summary: 'Local AI reviewed this design. No edits applied.',
        original_preview: null,
        changes: [
          { index: 0, field: 'colour', old: '#ffffff', new: '#172638', reason: 'Improve headline readability.' },
          { index: 1, field: 'colour', old: '#ffffff', new: '#172638', reason: 'Improve label readability.' },
        ],
        design_notes: [
          { category: 'typography', layer: 1, message: 'Check headline hierarchy at final size.' },
        ],
      }) });
  });
  await page.locator('#vsAIReview').click();
  await page.locator('#vsRepairReview:not([hidden])').waitFor();
  assert.match(await page.locator('#vsReviewHeading').innerText(), /Local AI design review/);
  assert.match(await page.locator('#vsRepairSummary').innerText(), /test-local-vision/);
  assert.match(await page.locator('#vsRepairNotes').innerText(), /headline hierarchy/);
  assert.equal(await page.locator('[data-repair-index]').count(), 2,
    'AI edits must use independently selectable review checkboxes');
  await page.locator('#vsRepairNone').click();
  assert.equal(await page.locator('#vsApplyRepair').isDisabled(), true);
  await page.locator('#vsRepairAll').click();
  await page.locator('#vsRepairImage:visible').waitFor();
  assert.equal(await page.locator('#vsApplyRepair').isEnabled(), true);
  await page.screenshot({ path: path.join(output, 'visual-studio-v6-local-ai-review.png') });
  await page.locator('#vsApplyRepair').click();
  assert.equal(await page.locator('#vsRepairReview').isVisible(), false);
  await page.locator('#vsUndo').click();
  await page.unroute('**/api/visual/studio/ai-review');
  // v7: choose independent objects, distribute, align and group via the
  // actual editor, not a duplicated test-only geometry implementation.
  const acceptV7CanvasReset=dialog=>dialog.accept();
  page.on('dialog',acceptV7CanvasReset);
  await page.locator('#vsTemplate').selectOption('workflow');
  await page.locator('#vsTemplate').selectOption('blank');
  page.off('dialog',acceptV7CanvasReset);
  for (const [x, y] of [[140,120],[340,250],[550,400]]) {
    await page.locator('#vsAddIcon').click();
    await page.locator('#vsProperties [data-key="x"]').fill(String(x));
    await page.locator('#vsProperties [data-key="x"]').press('Tab');
    await page.locator('#vsProperties [data-key="y"]').fill(String(y));
    await page.locator('#vsProperties [data-key="y"]').press('Tab');
  }
  await page.locator('#vsSelectAll').click();
  assert.match(await page.locator('#vsSelectedCount').innerText(), /3 layers selected/);
  assert.equal(await page.locator('#vsDistribute').isEnabled(), true);
  await page.locator('#vsDistributeMode').selectOption('horizontal');
  await page.locator('#vsDistribute').click();
  await page.waitForFunction(() => document.querySelector('#vsStage')?.getAttribute('aria-busy') === 'false');
  await page.locator('#vsClearSelection').click();
  const layerButtons=page.locator('#vsLayers [data-layer-act="select"]');
  await layerButtons.nth(0).click();
  await layerButtons.nth(1).click({modifiers:['Shift']});
  assert.match(await page.locator('#vsSelectedCount').innerText(), /2 layers selected/);
  assert.equal(await page.locator('#vsAlign').isEnabled(), true);
  await page.locator('#vsAlignMode').selectOption('left');
  await page.locator('#vsAlign').click();
  await page.waitForFunction(() => document.querySelector('#vsStage')?.getAttribute('aria-busy') === 'false');
  await page.locator('#vsGroup').click();
  assert.ok(await page.locator('#vsLayers [data-layer-key^="group:studio_group_"]').count() >= 3,
    'two native objects must become a group unit with visibility, lock and order controls');
  assert.equal(await page.locator('#vsUngroup').isEnabled(), true);
  await page.screenshot({path:path.join(output,'visual-studio-v7-group-align.png')});
  await page.locator('#vsUngroup').click();
  assert.match(await page.locator('#vsSelectedCount').innerText(), /2 layers selected/);
  await page.locator('#vsUndo').click();
  assert.equal(await page.locator('#vsLayers [data-layer-key^="group:studio_group_"]').count() >= 3, true,
    'Undo must restore the grouped layer without losing original object editability');
  await page.locator('#vsRedo').click();
  assert.equal(await page.locator('#vsSnap').isChecked(), true);
  // Undo/Redo intentionally clear ephemeral multi-selection so stale item
  // indices cannot point at changed group membership.
  assert.match(await page.locator('#vsSelectedCount').innerText(), /0 layers selected/);
  await page.locator('#vsSelectAll').click();
  assert.match(await page.locator('#vsSelectedCount').innerText(), /3 layers selected/);
  await page.locator('#vsClearSelection').click();
  assert.match(await page.locator('#vsSelectedCount').innerText(), /0 layers selected/);
  // v8: save and reopen a genuinely multi-page editable project. In all-page
  // PDF/PPTX mode, every canvas must be rendered, not just the current one.
  const acceptDocumentChanges=dialog=>dialog.accept();
  page.on('dialog',acceptDocumentChanges);
  await page.locator('#vsTemplate').selectOption('workflow');
  await page.locator('#vsTemplate').selectOption('blank');
  page.off('dialog',acceptDocumentChanges);
  await page.locator('#vsAddText').click();
  await page.locator('#vsProperties [data-key="text"]').fill('First page');
  await page.locator('#vsProperties [data-key="text"]').press('Tab');
  await page.locator('#vsPageAdd').click();
  assert.equal(await page.locator('#vsPageTabs [data-page-index]').count(),2);
  assert.match(await page.locator('#vsPageCount').innerText(),/2 \/ 2/);
  await page.locator('#vsPageName').fill('Second page');
  await page.locator('#vsPageName').press('Tab');
  await page.locator('#vsAddText').click();
  await page.locator('#vsProperties [data-key="text"]').fill('Second page text');
  await page.locator('#vsProperties [data-key="text"]').press('Tab');
  await page.locator('#vsPageTabs [data-page-index="0"]').click();
  assert.match(await page.locator('#vsPageCount').innerText(),/1 \/ 2/);
  assert.equal(await page.locator('#vsElement option').count(),2,
    'returning to page one restores its editable object');
  await page.locator('#vsPageDuplicate').click();
  assert.equal(await page.locator('#vsPageTabs [data-page-index]').count(),3);
  await page.locator('#vsPageUp').click();
  assert.match(await page.locator('#vsPageCount').innerText(),/1 \/ 3/);
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#vsPageDelete').click();
  // The duplicate was removed; original pages and their exact text remain.
  assert.equal(await page.locator('#vsPageTabs [data-page-index]').count(),2);
  await page.locator('#vsPageTabs [data-page-index="0"]').click();
  assert.equal(await page.locator('#vsPageName').inputValue(),'Page 1');
  const saving=page.waitForResponse(r=>r.url().includes('/api/visual/studio/document/save')&&
    r.request().method()==='POST');
  await page.locator('#vsSave').click();
  const savedResponse=await saving;
  assert.equal(savedResponse.status(),200,await savedResponse.text());
  const savedDoc=(await savedResponse.json()).path;
  await page.waitForFunction(path=>document.querySelector('#vsDraft')?.value===path,savedDoc);
  assert.ok(savedDoc.endsWith('.design.json'));
  await page.locator('#vsLoad').click();
  assert.equal(await page.locator('#vsPageTabs [data-page-index]').count(),2);
  assert.equal(await page.locator('#vsPageTabs [data-page-index="1"]').innerText().then(x=>x.includes('Second page')),true);
  await page.locator('#vsFormat').selectOption('pptx');
  await page.locator('#vsOutputMode').selectOption('layered');
  assert.match(await page.locator('#vsPageExportHint').innerText(),/All 2 pages/);
  const exportingSlides=page.waitForResponse(r=>r.url().includes('/api/visual/studio/document/export')&&
    r.request().method()==='POST');
  await page.locator('#vsExport').click();
  const slidesResponse=await exportingSlides;
  assert.equal(slidesResponse.status(),200,await slidesResponse.text());
  assert.equal((await slidesResponse.json()).page_count,2);
  await page.waitForFunction(()=>decodeURIComponent(document.querySelector('#vsOutput a[download]')?.href||'').includes('.pptx'));
  assert.equal(await page.locator('#vsOutput a[download]').count()>=2,true,
    'multi-page editable PowerPoint must provide an editable project download');
  await page.locator('#vsFormat').selectOption('pdf');
  const exportingPdf=page.waitForResponse(r=>r.url().includes('/api/visual/studio/document/export')&&
    r.request().method()==='POST');
  await page.locator('#vsExport').click();
  const pdfResponse=await exportingPdf;
  assert.equal(pdfResponse.status(),200,await pdfResponse.text());
  assert.equal((await pdfResponse.json()).page_count,2);
  await page.waitForFunction(()=>decodeURIComponent(document.querySelector('#vsOutput a[download]')?.href||'').includes('.pdf'));
  await page.screenshot({path:path.join(output,'visual-studio-v8-multipage-export.png')});
  await page.locator('#vsFormat').selectOption('png');
  assert.match(await page.locator('#vsPageExportHint').innerText(),/Only page/);
  // v9: Save a brand kit, reload it and prove that one explicit approval
  // can validate and restyle both native pages without flattening them.
  await page.locator('#vsBrandCapture').click();
  await page.locator('#vsBrandName').fill('QA visual identity');
  const kitSaving=page.waitForResponse(r=>r.url().includes('/api/visual/studio/brand-kits/save')&&
    r.request().method()==='POST');
  await page.locator('#vsBrandSave').click();
  const kitSaveResponse=await kitSaving;
  assert.equal(kitSaveResponse.status(),200,await kitSaveResponse.text());
  const kitPath=(await kitSaveResponse.json()).path;
  await page.waitForFunction(path=>document.querySelector('#vsBrandKits')?.value===path,kitPath);
  await page.locator('#vsBrandName').fill('Temporary edit');
  const kitLoading=page.waitForResponse(r=>r.url().includes('/api/visual/studio/brand-kits/load')&&
    r.request().method()==='GET');
  await page.locator('#vsBrandLoad').click();
  assert.equal((await kitLoading).status(),200);
  assert.equal(await page.locator('#vsBrandName').inputValue(),'QA visual identity');
  await page.locator('#vsBrandHeading').fill('30');
  page.once('dialog',dialog=>dialog.accept());
  const kitChecking=page.waitForResponse(r=>r.url().includes('/api/visual/studio/document/validate')&&
    r.request().method()==='POST');
  await page.locator('#vsBrandApplyAll').click();
  const kitCheckResponse=await kitChecking;
  assert.equal(kitCheckResponse.status(),200,await kitCheckResponse.text());
  await page.locator('#vsPageTabs [data-page-index="1"]').click();
  await page.locator('#vsElement').selectOption('0');
  assert.equal(await page.locator('#vsProperties [data-key="font_size"]').inputValue(),'30');
  await page.locator('#vsPageTabs [data-page-index="0"]').click();
  await page.locator('#vsElement').selectOption('0');
  assert.equal(await page.locator('#vsProperties [data-key="font_size"]').inputValue(),'30');
  await page.locator('#vsUndo').click();
  await page.locator('#vsElement').selectOption('0');
  assert.equal(await page.locator('#vsProperties [data-key="font_size"]').inputValue(),'34',
    'brand application must be undoable without changing the original copy');
  await page.screenshot({path:path.join(output,'visual-studio-v9-brand-kits.png')});
  // Confirm the saved kit is only a reusable style reference; deleting it
  // must never remove any existing draft or its underlying artwork.
  page.once('dialog',dialog=>dialog.accept());
  const deletingKit=page.waitForResponse(r=>r.url().includes('/api/visual/studio/brand-kits/delete')&&
    r.request().method()==='POST');
  await page.locator('#vsBrandDelete').click();
  assert.equal((await deletingKit).status(),200);
  await page.locator('#newChat').click();
  await page.locator('.hero h2').waitFor();
  await page.locator('#quickTheme').click();
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  await page.screenshot({ path: path.join(output, 'workspace-light.png') });
  await page.evaluate(() => { document.documentElement.dataset.chrome = 'custom'; window.__automotoChromeBoot(); });
  await page.locator('#amChrome').waitFor();
  assert.equal(await page.getByRole('button', { name: 'Minimize' }).isVisible(), true);
  assert.equal(await page.getByRole('button', { name: 'Maximize' }).isVisible(), true);
  assert.equal(await page.getByRole('button', { name: 'Close' }).isVisible(), true);
  await page.getByRole('button', { name: 'Menu', exact: true }).click();
  await page.getByRole('menuitem', { name: /Quit/ }).waitFor();
  await page.keyboard.press('ArrowDown');
  assert.equal(await page.evaluate(() => document.activeElement?.dataset?.action), 'reload');
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('data-chrome')), 'menu');
  assert.equal(await page.locator('#amAppMenu').isVisible(), false);
  await page.screenshot({ path: path.join(output, 'chrome-home-light.png') });
  await page.locator('#quickTheme').click();
  await page.screenshot({ path: path.join(output, 'chrome-home-dark.png') });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'custom chrome must not overflow');
  await page.evaluate(() => { delete document.documentElement.dataset.chrome; });
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.reload();
    await page.locator('.hero h2').waitFor();
    assert.match(await page.locator('.hero p').innerText(), /don't pick the tools/);
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
  await page.setViewportSize({ width: 1024, height: 670 });
  const localAction = await page.locator('#localBtn').boundingBox();
  await page.screenshot({ path: path.join(output, 'launcher-laptop.png') });
  assert.ok(localAction.y + localAction.height <= 670, `local mode must be visible on a short laptop window: ${JSON.stringify(localAction)}`);
  await page.evaluate(() => { document.documentElement.dataset.chrome = 'custom'; window.__automotoChromeBoot(); });
  await page.setViewportSize({ width: 1280, height: 820 });
  await page.locator('#amChrome').waitFor();
  const framed = await page.locator('#localBtn').boundingBox();
  assert.ok(framed && framed.y >= 40 && framed.y + framed.height <= 820, `launcher actions sit below the caption: ${JSON.stringify(framed)}`);
  await page.getByRole('button', { name: 'Menu', exact: true }).click();
  await page.getByRole('menuitem', { name: /Sign out/ }).waitFor();
  await page.keyboard.press('Escape');
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.screenshot({ path: path.join(output, 'chrome-launcher-dark.png') });
  await page.emulateMedia({ colorScheme: 'light' });
  await page.screenshot({ path: path.join(output, 'chrome-launcher-light.png') });
  await page.evaluate(() => { delete document.documentElement.dataset.chrome; });
  await page.emulateMedia({ colorScheme: 'dark' });
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

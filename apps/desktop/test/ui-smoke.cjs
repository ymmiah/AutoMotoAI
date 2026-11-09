// Browser regressions against the real local server and a stubbed native launcher.
// No provider keys or model requests. PYTHON selects the installed engine interpreter.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { mkdtempSync, readFileSync, writeFileSync, mkdirSync, rmSync, existsSync } = require('node:fs');
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
  await page.waitForFunction(() =>
    document.querySelector('#daMode')?.textContent === 'Editable Markdown source');
  assert.equal(await page.locator('#daMode').innerText(), 'Editable Markdown source');
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
  // v7 final reliability: private opt-in recovery and real OOXML acceptance
  // are user-controlled, reversible and cannot overwrite imported sources.
  await page.locator('#daAcceptance summary').click();
  assert.equal(await page.locator('#daRecoveryAuto').isChecked(),false);
  const v7Source=await page.locator('#daSource').inputValue();
  const savingRecovery=page.waitForResponse(r=>r.url().includes('/api/documents/recovery/save')&&
    r.request().method()==='POST');
  await page.locator('#daRecoverySave').click();
  const recoveryResp=await savingRecovery;
  assert.equal(recoveryResp.status(),200,await recoveryResp.text());
  const checkpointId=(await recoveryResp.json()).id;
  assert.equal(checkpointId.length,24);
  await page.locator('[data-recovery-load="'+checkpointId+'"]').waitFor();
  const auditing=page.waitForResponse(r=>r.url().includes('/api/documents/quality/audit')&&
    r.request().method()==='POST');
  await page.locator('#daQualityRun').click();
  const auditResponse=await auditing;
  assert.equal(auditResponse.status(),200,await auditResponse.text());
  const auditResult=await auditResponse.json();
  assert.equal(auditResult.files_saved,false);
  assert.equal(auditResult.human_review_required,true);
  assert.equal(auditResult.structurally_exportable,true);
  assert.match(await page.locator('#daQualityResult').innerText(),/human review is still required/i);
  await page.locator('#daSource').fill('Temporary unsaved modifications.');
  const loadingRecovery=page.waitForResponse(r=>r.url().includes('/api/documents/recovery/load')&&
    r.request().method()==='GET');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('[data-recovery-load="'+checkpointId+'"]').click();
  const restoredResponse=await loadingRecovery;
  assert.equal(restoredResponse.status(),200,await restoredResponse.text());
  await page.waitForFunction(expected=>
    document.querySelector('#daSource')?.value===expected,v7Source);
  assert.equal(await page.locator('#daSource').inputValue(),v7Source,
    'explicitly restored checkpoint must match saved Markdown');
  await page.locator('#daUndo').click();
  assert.equal(await page.locator('#daSource').inputValue(),'Temporary unsaved modifications.');
  await page.locator('#daRedo').click();
  assert.equal(await page.locator('#daSource').inputValue(),v7Source);
  await page.locator('#daRecoveryAuto').check();
  assert.match(await page.locator('#daRecoveryStatus').innerText(),/enabled for this editing session/);
  await page.locator('#daRecoveryAuto').uncheck();
  assert.match(await page.locator('#daRecoveryStatus').innerText(),/Automatic recovery is off/);
  const deletingRecovery=page.waitForResponse(r=>r.url().includes('/api/documents/recovery/')&&
    r.request().method()==='DELETE');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('[data-recovery-delete="'+checkpointId+'"]').click();
  const deletion=await deletingRecovery;
  assert.equal(deletion.status(),200,await deletion.text());
  await page.locator('#daRecoveryList').getByText('No private recovery checkpoints saved yet.').waitFor();
  await page.screenshot({path:path.join(output,'document-assistant-v7-recovery-acceptance.png')});
  // Restoring intentionally marks the new editor state unsaved. Accept the
  // standard "leave unsaved changes" confirmation before importing the file.
  page.once('dialog',dialog=>dialog.accept());
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
  await page.locator('#daRichParagraph option').first().waitFor({state:'attached'});
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
  // v6: real local evidence retrieval from a checksum-pinned imported Word
  // document without model access, invented references or source writes.
  await page.locator('#daResearch summary').click();
  await page.locator('#daResearchSources input[type="checkbox"]').first()
    .waitFor({state:'attached'});
  const selectedSources=await page.locator('#daResearchSources input[type="checkbox"]:checked').count();
  assert.ok(selectedSources>=1,'current imported Word file becomes a research source');
  await page.locator('#daResearchQuestion').fill('What is the original body wording for review?');
  const searchingEvidence=page.waitForResponse(r=>
    r.url().includes('/api/documents/research/query')&&r.request().method()==='POST');
  await page.locator('#daResearchRun').click();
  const evidenceResponse=await searchingEvidence;
  assert.equal(evidenceResponse.status(),200,await evidenceResponse.text());
  assert.equal((await evidenceResponse.json()).mode,'evidence');
  await page.locator('#daResearchEvidence blockquote').first().waitFor();
  assert.match(await page.locator('#daResearchEvidence').innerText(),/Original body wording for review/);
  assert.match(await page.locator('#daResearchNotes').inputValue(),/Research evidence notes/);
  assert.match(await page.locator('#daResearchNotes').inputValue(),/not verified facts or bibliographic citations/);
  await page.locator('#daResearchMode').selectOption('outline');
  const searchingOutline=page.waitForResponse(r=>
    r.url().includes('/api/documents/research/query')&&r.request().method()==='POST');
  await page.locator('#daResearchRun').click();
  const outlineResponse=await searchingOutline;
  assert.equal(outlineResponse.status(),200,await outlineResponse.text());
  assert.equal((await outlineResponse.json()).mode,'outline');
  assert.match(await page.locator('#daResearchNotes').inputValue(),/Suggested academic structure/);
  const researchOriginal=await page.request.get(base+'/api/files/download?path='+
    encodeURIComponent(importPath));
  assert.ok((await researchOriginal.body()).equals(wordBytes),
    'research review must not modify the imported Word file');
  await page.screenshot({path:path.join(output,'document-assistant-v6-offline-research.png')});
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
  // Spreadsheet v1: real browser -> authenticated Python API -> genuine XLSX.
  await page.locator('.nav [data-page="spreadsheets"]').click();
  await page.locator('#ssBookName').waitFor();
  await page.locator('#ssBookName').fill('QA offline workbook');
  await page.locator('#ssGrid input[data-row="1"][data-col="1"]').fill('42.50');
  // V3 browser acceptance: style B2, freeze panes, width and validated numeric column.
  await page.locator('#ssStyleBold').check();
  await page.locator('#ssStyleFill').fill('#dce8f2');
  await page.locator('#ssStyleFormat').selectOption('gbp');
  await page.locator('#ssApplyStyle').click();
  await page.locator('#ssToolsColumn').selectOption('1');
  await page.locator('#ssFreeze').selectOption('both');
  await page.locator('#ssWidth').fill('25');
  await page.locator('#ssApplyLayout').click();
  await page.locator('#ssValidationKind').selectOption('decimal');
  await page.locator('#ssValidationMin').fill('0');
  await page.locator('#ssValidationMax').fill('100');
  await page.locator('#ssApplyValidation').click();
  const bookSaving=page.waitForResponse(r=>r.url().includes('/api/spreadsheets/save')&&
    r.request().method()==='POST');
  await page.locator('#ssSave').click();
  const bookSaved=await bookSaving;
  assert.equal(bookSaved.status(),200,'private workbook save should succeed');
  const workbookPath=(await bookSaved.json()).path;
  assert.ok(workbookPath.endsWith('.sheet.json'));
  const storedV3=await page.request.get(base+'/api/spreadsheets/load?path='+encodeURIComponent(workbookPath));
  assert.equal(storedV3.status(),200);
  const styledSheet=(await storedV3.json()).workbook.sheets[0];
  assert.equal(styledSheet.cell_styles.B2.bold,true);
  assert.equal(styledSheet.cell_styles.B2.number_format,'gbp');
  assert.equal(styledSheet.freeze,'both');
  assert.equal(styledSheet.column_widths.B,25);
  assert.equal(styledSheet.validations[0].kind,'decimal');
  const bookExporting=page.waitForResponse(r=>r.url().includes('/api/spreadsheets/export')&&
    r.request().method()==='POST');
  await page.locator('#ssExport').click();
  const bookExported=await bookExporting;
  assert.equal(bookExported.status(),200);
  const workbookXlsx=(await bookExported.json()).path;
  assert.ok(workbookXlsx.endsWith('.xlsx'));
  assert.ok((await page.request.get(base+'/api/files/download?path='+encodeURIComponent(workbookXlsx))).ok());

  // V2: formula evaluation, dependency change and history are exercised via the real API.
  assert.equal(await page.locator('#ssCalcMode').inputValue(),'formulas');
  await page.locator('#ssGrid input[data-row="1"][data-col="2"]').fill('=B2*2');
  const calculating=page.waitForResponse(r=>r.url().includes('/api/spreadsheets/calculate')&&
    r.request().method()==='POST');
  await page.locator('#ssCalculate').click();
  assert.equal((await calculating).status(),200);
  await page.waitForFunction(() =>
    document.querySelector('#ssCalcResults')?.textContent?.includes('C2 = 85'));
  await page.locator('#ssUndo').click();
  assert.equal(await page.locator('#ssGrid input[data-row="1"][data-col="2"]').inputValue(),'');
  await page.locator('#ssRedo').click();
  assert.equal(await page.locator('#ssGrid input[data-row="1"][data-col="2"]').inputValue(),'=B2*2');
  await page.waitForFunction(() =>
    document.querySelector('#ssCalcResults')?.textContent?.includes('C2 = 85'));
  await page.locator('#ssGrid input[data-row="1"][data-col="1"]').fill('20');
  await page.locator('#ssCalculate').click();
  await page.waitForFunction(() =>
    document.querySelector('#ssCalcResults')?.textContent?.includes('C2 = 40'));
  await page.locator('#ssGrid input[data-row="2"][data-col="0"]').fill('=A3');
  await page.locator('#ssCalculate').click();
  await page.waitForFunction(() =>
    document.querySelector('#ssCalcResults')?.textContent?.includes('#CYCLE!'));
  await page.screenshot({path:path.join(output,'invoice-spreadsheet-v2-formulas.png')});
  await page.locator('#ssUndo').click();
  await page.waitForFunction(() =>
    !document.querySelector('#ssCalcResults')?.textContent?.includes('#CYCLE!'));
  await page.locator('#ssSortAsc').click();
  await page.waitForFunction(() =>
    document.querySelector('#ssStatus')?.textContent?.includes('Sorting worksheets with formulas'));
  await page.locator('#ssFilterText').fill('20');
  assert.equal(await page.locator('#ssGrid tbody tr:not([hidden])').count(),2,
    'filter shows header plus the matching B-column row');
  await page.locator('#ssClearFilter').click();
  assert.equal(await page.locator('#ssGrid tbody tr[hidden]').count(),0,
    'clearing filters restores every row');
  await page.screenshot({path:path.join(output,'invoice-spreadsheet-v3-professional-editing.png')});

  // V6 model-free quality audit must run without Ollama and never change cell state.
  const beforeAudit=await page.locator('#ssGrid input[data-row="1"][data-col="1"]').inputValue();
  const auditingV6=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/ai/audit')&&r.request().method()==='POST');
  await page.locator('#saiAudit').click();
  const auditedV6=await auditingV6;
  assert.equal(auditedV6.status(),200);
  const qualityV6=await auditedV6.json();
  assert.equal(qualityV6.applied,false);
  assert.equal(typeof qualityV6.snapshot_sha256,'string');
  assert.equal(qualityV6.snapshot_sha256.length,64);
  assert.equal(await page.locator('#ssGrid input[data-row="1"][data-col="1"]').inputValue(),beforeAudit);
  await page.locator('#saiMode').selectOption('formula');
  await page.locator('#saiTarget').fill('D2');
  await page.locator('#saiQuestion').fill('Calculate twice the value in B2');
  await page.locator('#saiReview').click();
  await page.waitForFunction(()=>document.querySelector('#saiStatus')?.textContent?.includes('Explicit consent'));
  assert.equal(await page.locator('#saiProposal').isHidden(),true);

  // V6 approval validation never writes. A malicious or stale digest cannot apply changes.
  const validatingV6=await page.evaluate(async()=>{
    const response=await fetch('/api/spreadsheets/ai/validate',{
      method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        workbook:{name:'QA offline workbook',calculation_mode:'formulas',sheets:[{
          name:'Sheet1',rows:[['Item','Value'],['',20,null]]
        }]},
        sheet:0,target_cell:'C2',original:null,proposal:'=B2*2',mode:'formula',
        snapshot_sha256:'0'.repeat(64),approve:true
      })
    });
    return response.status;
  });
  assert.equal(validatingV6,409);
  await page.screenshot({path:path.join(output,'invoice-spreadsheet-v6-offline-ai.png')});

  await page.locator('#ssTabInvoice').click();
  await page.locator('#ssInvoiceNumber').fill('QA-2026-1');
  await page.locator('#ssSeller').fill('Example business, Birmingham');
  await page.locator('#ssCustomer').fill('Example customer, London');
  await page.locator('#ssIssued').fill('2026-11-07');
  await page.locator('#ssDue').fill('2026-12-07');
  await page.locator('#ssTax').fill('20');
  await page.locator('#ssInvoiceLines input[data-field="description"]').fill('V1 test service');
  await page.locator('#ssInvoiceLines input[data-field="quantity"]').fill('2');
  await page.locator('#ssInvoiceLines input[data-field="unit_price"]').fill('7.50');
  const invoiceChecking=page.waitForResponse(r=>r.url().includes('/api/spreadsheets/invoice/preview')&&
    r.request().method()==='POST');
  await page.locator('#ssPreview').click();
  assert.equal((await invoiceChecking).status(),200);
  await page.waitForFunction(()=>document.querySelector('#ssTotals')?.textContent?.includes('GBP 18.00'));
  const invoiceSaving=page.waitForResponse(r=>r.url().includes('/api/spreadsheets/invoice/save')&&
    r.request().method()==='POST');
  await page.locator('#ssInvoiceSave').click();
  assert.equal((await invoiceSaving).status(),200);
  const invoiceExporting=page.waitForResponse(r=>r.url().includes('/api/spreadsheets/invoice/export')&&
    r.request().method()==='POST');
  await page.locator('#ssInvoiceExport').click();
  const invoiceExported=await invoiceExporting;
  assert.equal(invoiceExported.status(),200);
  const invoiceData=await invoiceExported.json();
  assert.equal(invoiceData.draft_only,true);
  assert.equal(invoiceData.sent,false);
  assert.equal(invoiceData.totals.total,'18.00');
  await page.screenshot({path:path.join(output,'invoice-spreadsheet-v1-workspace.png')});

  // V4: actual browser -> local commercial API -> branded PDF document.
  await page.locator('#ssTabCommercial').click();
  await page.locator('#csBrandName').fill('QA Commerce Studio');
  await page.locator('#csKind').selectOption('quotation');
  await page.locator('#csReview').selectOption('reviewed');
  await page.locator('#csNumber').fill('QUOTE-QA-2026');
  await page.locator('#csDate').fill('2026-11-07');
  await page.locator('#csDue').fill('2026-12-07');
  await page.locator('#csSellerName').fill('QA Local Business Ltd');
  await page.locator('#csSellerAddress').fill('10 Example Square, Birmingham');
  await page.locator('#csCustomerName').fill('QA Customer Ltd');
  await page.locator('#csCustomerAddress').fill('22 Test Road, London');
  await page.locator('#csLines input[data-index="0"][data-field="description"]').fill('Development service');
  await page.locator('#csLines input[data-index="0"][data-field="quantity"]').fill('2');
  await page.locator('#csLines input[data-index="0"][data-field="unit_price"]').fill('19.99');
  await page.locator('#csLines input[data-index="0"][data-field="discount_percent"]').fill('10');
  await page.locator('#csOrderDiscount').fill('5');
  await page.locator('#csTaxRate').fill('20');
  await page.locator('#csTaxLabel').selectOption('VAT');
  const v4Previewing=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/commercial/preview')&&r.request().method()==='POST');
  await page.locator('#csPreview').click();
  const v4Preview=await v4Previewing;
  assert.equal(v4Preview.status(),200);
  assert.equal((await v4Preview.json()).total,'41.02');
  await page.waitForFunction(() =>
    document.querySelector('#csTotals')?.textContent?.includes('GBP 41.02'));

  const customerSaving=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/commercial/customer/save')&&r.request().method()==='POST');
  await page.locator('#csContactSave').click();
  assert.equal((await customerSaving).status(),200);
  await page.waitForFunction(()=>document.querySelector('#csContacts')?.options?.length>=2);

  const v4Saving=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/commercial/save')&&r.request().method()==='POST');
  await page.locator('#csSave').click();
  const commercialSaved=await v4Saving;
  assert.equal(commercialSaved.status(),200);
  const v4Path=(await commercialSaved.json()).path;
  assert.ok(v4Path.endsWith('.commercial.json'));
  const v4Loaded=await page.request.get(base+'/api/spreadsheets/commercial/load?path='+
    encodeURIComponent(v4Path));
  assert.equal(v4Loaded.status(),200);
  assert.equal((await v4Loaded.json()).document.kind,'quotation');

  const v4Exporting=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/commercial/export')&&r.request().method()==='POST');
  await page.locator('#csExport').click();
  const v4Exported=await v4Exporting;
  assert.equal(v4Exported.status(),200);
  const v4PDF=await v4Exported.json();
  assert.equal(v4PDF.draft_only,true);
  assert.equal(v4PDF.issued,false);
  assert.equal(v4PDF.sent,false);
  assert.equal(v4PDF.paid,false);
  assert.ok(v4PDF.path.endsWith('.pdf'));
  const pdfDownload=await page.request.get(base+'/api/files/download?path='+
    encodeURIComponent(v4PDF.path));
  assert.equal(pdfDownload.status(),200);
  assert.ok((await pdfDownload.body()).subarray(0,5).toString()==='%PDF-');
  await page.screenshot({path:path.join(output,'invoice-spreadsheet-v4-quotation-pdf.png')});

  // V5: user-confirmed cash, planned exclusion, private snapshots and real reporting.
  await page.locator('#ssTabFinance').click();
  await page.locator('#fiName').fill('QA cash-flow test');
  await page.locator('#fiOpening').fill('10.00');
  await page.locator('#fiFrom').fill('2026-01-01');
  await page.locator('#fiTo').fill('2026-12-31');
  await page.locator('#fiAdd').click();
  await page.locator('#fiEntries [data-index="0"][data-key="transaction_date"]').fill('2026-11-07');
  await page.locator('#fiEntries [data-index="0"][data-key="amount"]').fill('120.00');
  await page.locator('#fiEntries [data-index="0"][data-key="description"]').fill('Confirmed service receipt');
  await page.locator('#fiEntries [data-index="0"][data-key="status"]').selectOption('actual');
  await page.locator('#fiAdd').click();
  await page.locator('#fiEntries [data-index="1"][data-key="kind"]').selectOption('expense');
  await page.locator('#fiEntries [data-index="1"][data-key="amount"]').fill('20.00');
  await page.locator('#fiEntries [data-index="1"][data-key="description"]').fill('Confirmed software spend');
  await page.locator('#fiEntries [data-index="1"][data-key="status"]').selectOption('actual');
  await page.locator('#fiAdd').click();
  await page.locator('#fiEntries [data-index="2"][data-key="amount"]').fill('1000.00');
  await page.locator('#fiEntries [data-index="2"][data-key="description"]').fill('Forecast only');
  assert.equal(await page.locator('#fiEntries [data-index="2"][data-key="status"]').inputValue(),'planned');
  const analysingV5=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/finance/analyse')&&r.request().method()==='POST');
  await page.locator('#fiAnalyse').click();
  const analysisResponse=await analysingV5;
  assert.equal(analysisResponse.status(),200);
  const financeReport=await analysisResponse.json();
  assert.equal(financeReport.revenue,'120.00');
  assert.equal(financeReport.expenses,'20.00');
  assert.equal(financeReport.operating_surplus,'100.00');
  assert.equal(financeReport.closing_cash,'110.00');
  assert.equal(financeReport.planned_revenue,'1000.00');
  assert.equal(financeReport.invoices_included,false);
  await page.waitForFunction(()=>document.querySelector('#fiMetrics')?.textContent?.includes('GBP 110.00'));
  assert.ok(await page.locator('#fiChart .fi-bar-track').count()>=2);

  const savingV5=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/finance/save')&&r.request().method()==='POST');
  await page.locator('#fiSave').click();
  const savedV5=await savingV5;
  assert.equal(savedV5.status(),200);
  const financePath=(await savedV5.json()).path;
  assert.ok(financePath.endsWith('.finance.json'));
  const loadedV5=await page.request.get(base+'/api/spreadsheets/finance/load?path='+
    encodeURIComponent(financePath));
  assert.equal(loadedV5.status(),200);
  assert.equal((await loadedV5.json()).book.entries.length,3);

  const exportingV5=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/finance/export')&&r.request().method()==='POST');
  await page.locator('#fiExportPDF').click();
  const exportedV5=await exportingV5;
  assert.equal(exportedV5.status(),200);
  const reportPDF=await exportedV5.json();
  assert.equal(reportPDF.verified,false);
  assert.ok(reportPDF.path.endsWith('.pdf'));
  const financePDFDownload=await page.request.get(base+'/api/files/download?path='+
    encodeURIComponent(reportPDF.path));
  assert.equal(financePDFDownload.status(),200);
  assert.equal((await financePDFDownload.body()).subarray(0,5).toString(),'%PDF-');
  await page.screenshot({path:path.join(output,'invoice-spreadsheet-v5-financial-dashboard.png')});

  // V7 real browser: private saved quotation + manually entered finance snapshot,
  // review-only approval, audit chaining, and zero source/accounting mutation.
  await page.locator('#ssTabWorkflows').click();
  await page.locator('#wfRefresh').click();
  await page.waitForFunction(()=>document.querySelector('#wfSource')?.options?.length>=4);
  await page.locator('#wfSource').selectOption(v4Path);
  await page.locator('#wfRelated').selectOption(financePath);
  await page.locator('#wfPurpose').selectOption('cash_reconciliation_review');
  await page.locator('#wfNote').fill('Check quotation totals against the separate manual cash ledger, without posting entries.');
  await page.locator('#wfCreateConfirm').check();
  page.once('dialog',d=>d.accept());
  const creatingWorkflow=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/workflows/create')&&r.request().method()==='POST');
  await page.locator('#wfCreate').click();
  const createdWorkflow=await creatingWorkflow;
  assert.equal(createdWorkflow.status(),200,await createdWorkflow.text());
  const workflowRecord=await createdWorkflow.json();
  assert.equal(workflowRecord.status,'pending');
  assert.equal(workflowRecord.approved,false);
  assert.equal(workflowRecord.source_path,v4Path);
  assert.equal(workflowRecord.related_path,financePath);
  assert.equal(workflowRecord.events.length,1);
  await page.waitForFunction(()=>document.querySelector('#wfDetail')?.textContent?.includes('pending'));
  assert.equal(await page.locator('#wfApprove').isDisabled(),false);
  await page.locator('#wfReason').fill('I verified the saved evidence and acknowledge the review only.');
  await page.locator('#wfDecisionConfirm').check();
  page.once('dialog',d=>d.accept());
  const approvingWorkflow=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/workflows/decide')&&r.request().method()==='POST');
  await page.locator('#wfApprove').click();
  const approvedWorkflow=await approvingWorkflow;
  assert.equal(approvedWorkflow.status(),200,await approvedWorkflow.text());
  const approval=await approvedWorkflow.json();
  assert.equal(approval.status,'approved');
  assert.equal(approval.sources_modified,false);
  assert.equal(approval.financial_postings,0);
  assert.equal(approval.issued,false);
  const wfAudit=await page.request.get(base+'/api/spreadsheets/workflows/verify');
  assert.equal(wfAudit.status(),200);
  assert.equal((await wfAudit.json()).event_count,2);
  const v7Original=await page.request.get(base+'/api/spreadsheets/commercial/load?path='+
    encodeURIComponent(v4Path));
  assert.equal(v7Original.status(),200);
  assert.equal((await v7Original.json()).document.review_state,'reviewed');
  const v7Finance=await page.request.get(base+'/api/spreadsheets/finance/load?path='+
    encodeURIComponent(financePath));
  assert.equal(v7Finance.status(),200);
  assert.equal((await v7Finance.json()).book.entries.length,3);
  assert.equal(await page.locator('#wfApprove').isDisabled(),true);
  await page.screenshot({path:path.join(output,'invoice-spreadsheet-v7-workflow-audit.png')});

  // V8 real browser: keyboard-accessible release tab, private archive, SHA-256
  // verification, consented copy-only restore, unchanged original documents.
  await page.locator('#ssTabWorkflows').focus();
  await page.keyboard.press('ArrowRight');
  assert.equal(await page.locator('#ssTabRelease').getAttribute('aria-selected'),'true');
  assert.equal(await page.locator('#ssRelease').isVisible(),true);
  await page.waitForFunction(()=>document.querySelector('#srReleaseStatus')?.textContent==='Release blocked');
  const releaseReadiness=await page.request.get(base+'/api/spreadsheets/release/readiness');
  assert.equal(releaseReadiness.status(),200);
  assert.equal((await releaseReadiness.json()).release_ready,false);

  page.once('dialog',d=>d.accept());
  const creatingV8=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/release/create')&&r.request().method()==='POST');
  await page.locator('#srCreate').click();
  const v8Created=await creatingV8;
  assert.equal(v8Created.status(),200,await v8Created.text());
  const v8Backup=await v8Created.json();
  assert.ok(v8Backup.path.endsWith('.zip'));
  assert.ok(v8Backup.records>=3);
  assert.equal(v8Backup.workflow_history_included,true);
  assert.equal(v8Backup.source_files_changed,false);
  assert.equal(v8Backup.encrypted,false);
  const zipDownload=await page.request.get(base+'/api/files/download?path='+
    encodeURIComponent(v8Backup.path));
  assert.equal(zipDownload.status(),200);
  assert.equal((await zipDownload.body()).subarray(0,2).toString(),'PK');
  await page.waitForFunction(()=>document.querySelector('#srBackups')?.value?.endsWith('.zip'));

  const verifyingV8=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/release/verify')&&r.request().method()==='POST');
  await page.locator('#srVerify').click();
  const v8Verified=await verifyingV8;
  assert.equal(v8Verified.status(),200,await v8Verified.text());
  assert.equal((await v8Verified.json()).valid,true);
  await page.locator('#srRestore').click();
  await page.waitForFunction(()=>document.querySelector('#srStatus')?.textContent?.includes('RESTORE COPIES'));
  await page.locator('#srAcknowledgement').fill('RESTORE COPIES');
  await page.locator('#srNoOverwrite').check();
  page.once('dialog',d=>d.accept());
  const restoringV8=page.waitForResponse(r=>
    r.url().includes('/api/spreadsheets/release/restore')&&r.request().method()==='POST');
  await page.locator('#srRestore').click();
  const v8Restored=await restoringV8;
  assert.equal(v8Restored.status(),200,await v8Restored.text());
  const v8Result=await v8Restored.json();
  assert.equal(v8Result.original_records_overwritten,false);
  assert.equal(v8Result.live_workflow_history_replaced,false);
  assert.equal(v8Result.financial_postings,0);
  assert.equal(v8Result.records,v8Backup.records);
  assert.ok(v8Result.archived_workflow_evidence.endsWith('.sqlite3'));
  const v8Original=await page.request.get(base+'/api/spreadsheets/commercial/load?path='+
    encodeURIComponent(v4Path));
  assert.equal(v8Original.status(),200);
  assert.equal((await v8Original.json()).document.review_state,'reviewed');
  const v8Audit=await page.request.get(base+'/api/spreadsheets/workflows/verify');
  assert.equal(v8Audit.status(),200);
  assert.equal((await v8Audit.json()).event_count,2);
  await page.screenshot({path:path.join(output,'invoice-spreadsheet-v8-recovery-readiness.png')});

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

  // Dedicated Research Studio V1: sources are existing private saved docs;
  // evidence must be hash-pinned and saved as a new immutable project.
  await page.locator('.nav [data-page="research"]').click();
  await page.locator('#rsTitle').waitFor();
  await page.locator('#rsTitle').fill('Browser verified research');
  await page.locator('#rsQuestion').fill('What original body wording is in the document smoke report?');
  await page.waitForFunction(source=>[...document.querySelectorAll('#rsSourceList input')]
    .some(x=>x.value===source),savedDraft);
  await page.locator('#rsSourceList input[value="'+savedDraft+'"]').check();
  await page.waitForFunction(()=>document.querySelector('#rsSelected')?.textContent==='1 of 5 selected');
  const findingResearch=page.waitForResponse(r=>
    r.url().includes('/api/research/studio/query')&&r.request().method()==='POST');
  await page.locator('#rsFind').click();
  const researchResponse=await findingResearch;
  assert.equal(researchResponse.status(),200,await researchResponse.text());
  const researchReport=(await researchResponse.json()).result;
  assert.equal(researchReport.read_only,true);
  assert.equal(researchReport.source_count,1);
  assert.ok(researchReport.evidence.length>=1,'V1 must show genuine local quote evidence');
  assert.equal(researchReport.evidence[0].source,savedDraft);
  assert.equal(researchReport.evidence[0].page,null);
  assert.equal(researchReport.applied,false);
  await page.waitForFunction(()=>document.querySelectorAll('#rsEvidence .rs-excerpt').length>0);
  assert.equal(await page.locator('#rsCopy').isDisabled(),false);
  const saveResearch=page.waitForResponse(r=>
    r.url().includes('/api/research/studio/save')&&r.request().method()==='POST');
  await page.locator('#rsSave').click();
  const savedResearch=await saveResearch;
  assert.equal(savedResearch.status(),200,await savedResearch.text());
  const researchPath=(await savedResearch.json()).path;
  assert.ok(researchPath.endsWith('.research.json'));
  await page.waitForFunction(p=>document.querySelector('#rsProjects')?.value===p,researchPath);
  page.once('dialog',d=>d.accept());
  await page.locator('#rsOpen').click();
  await page.waitForFunction(()=>document.querySelector('#rsStatus')?.textContent?.includes('Historical project loaded'));
  assert.equal(await page.locator('#rsSourceStates .rs-current').count(),1);
  const historical=await page.request.get(base+'/api/research/studio/open?path='+encodeURIComponent(researchPath));
  assert.equal(historical.status(),200);
  assert.equal((await historical.json()).source_status[0].status,'current');
  await page.screenshot({path:path.join(output,'research-studio-v1-evidence-workspace.png')});

  // V2 public discovery: browser UI uses deterministic mock registry responses.
  // Actual safe network, robots, checksum, DOI and offline behaviours run in Python tests.
  let v2SavedMeta=false;
  const v2Paper={
    doi:'10.5555/research-security.2026',
    title:'<img src=x onerror=alert(1)> Evidence and resilience in secure release automation',
    authors:['Amina Test','Sam Researcher'],
    venue:'Journal of Test Engineering', publication_date:'2026-11',
    type:'journal-article',registry:'Crossref',
    registry_url:'https://api.crossref.org/works/10.5555/research-security.2026',
    doi_url:'https://doi.org/10.5555/research-security.2026',
    retrieved_at:'2026-11-08T12:00:00+00:00',metadata_only:true
  };
  const v2Mock=body=>({status:200,contentType:'application/json',body:JSON.stringify(body)});
  await page.route('**/api/research/studio/discovery/search',route=>
    route.fulfill(v2Mock({provider:'crossref',query:'secure release',results:[v2Paper],
      retrieved_at:'2026-11-08T12:00:00+00:00',not_verified_claims:true})));
  await page.route('**/api/research/studio/discovery/verify-doi',route=>
    route.fulfill(v2Mock({metadata:v2Paper,verified_in:'Crossref',
      registry_record_found:true,research_claims_verified:false,full_text_downloaded:false})));
  await page.route('**/api/research/studio/discovery/save-doi',route=>{
    v2SavedMeta=true;
    return route.fulfill(v2Mock({path:'artifacts/research/sources/source-aaaaaaaaaaaaaaaaaaaaaaaa.source.json',
      already_saved:false,metadata:v2Paper,citation_ready:false,source_files_modified:false}));
  });
  await page.route('**/api/research/studio/discovery/saved',route=>
    route.fulfill(v2Mock({sources:v2SavedMeta?[v2Paper]:[],metadata_only:true})));
  await page.route('**/api/research/studio/discovery/capture-page',route=>
    route.fulfill(v2Mock({document:'artifacts/documents/web-source-bbbbbbbbbbbbbbbbbbbbbbbb.txt',
      source_url:'https://example.org/public-study',sha256:'a'.repeat(64),
      provenance:'artifacts/research/pages/web-bbbbbbbbbbbbbbbbbbbbbbbb.web.json',
      user_confirmed:true,claim_verification:false})));
  assert.equal(await page.locator('#rdTitle').isVisible(),true);
  await page.locator('#rdQuery').fill('secure release');
  await page.locator('#rdSearchForm button').click();
  await page.waitForFunction(()=>document.querySelector('#rdResults .rd-record')?.textContent?.includes('Evidence and resilience'));
  assert.equal(await page.locator('#rdResults img').count(),0,'untrusted publisher HTML must remain plain text');
  assert.match(await page.locator('#rdResults').innerText(),/10\.5555\/research-security\.2026/);
  assert.equal(await page.locator('#rdResults .rd-record').count(),1);
  await page.locator('#rdResults').getByRole('button',{name:'Save verified metadata'}).click();
  assert.match(await page.locator('#rdStatus').innerText(),/acknowledgement/);
  await page.locator('#rdConfirmSave').check();
  page.once('dialog',d=>d.accept());
  await page.locator('#rdResults').getByRole('button',{name:'Save verified metadata'}).click();
  await page.waitForFunction(()=>document.querySelector('#rdSaved .rd-record')?.textContent?.includes('Journal of Test Engineering'));
  assert.equal(v2SavedMeta,true);
  await page.locator('#rdDoi').fill('10.5555/research-security.2026');
  await page.locator('#rdDoiForm button').click();
  await page.waitForFunction(()=>document.querySelector('#rdCount')?.textContent?.includes('Verified Crossref DOI'));
  assert.match(await page.locator('#rdStatus').innerText(),/does not establish peer review/);
  await page.locator('#rdPageUrl').fill('https://example.org/public-study');
  await page.locator('#rdCaptureForm button').click();
  assert.match(await page.locator('#rdStatus').innerText(),/Explicitly authorise/);
  await page.locator('#rdConfirmCapture').check();
  page.once('dialog',d=>d.accept());
  await page.locator('#rdCaptureForm button').click();
  await page.waitForFunction(()=>document.querySelector('#rdStatus')?.textContent?.includes('Webpage text captured'));
  await page.screenshot({path:path.join(output,'research-studio-v2-scholar-source-discovery.png')});
  await page.unrouteAll();

  // V3 end-to-end real source-pinned comparison (not mocked): a newly saved V1
  // project referencing two existing documents, genuine extracted source quotes,
  // human support/contradict labels, save and historical reopen.
  // The browser's actual authenticated fetch context carries its launch session.
  // Playwright's independent page.request client does not carry that session.
  const v3Request=({route,body})=>page.evaluate(async args=>{
    const init=args.body===undefined?{}:{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(args.body),
    };
    const response=await fetch(args.route,init);
    return {status:response.status,body:await response.text()};
  },{route,body});
  const [v3InfoOne,v3InfoTwo]=await Promise.all([
    v3Request({route:'/api/documents/research/source-info?path='+encodeURIComponent(savedDraft)}),
    v3Request({route:'/api/documents/research/source-info?path='+encodeURIComponent(savedV2)}),
  ]);
  assert.equal(v3InfoOne.status,200,v3InfoOne.body);
  assert.equal(v3InfoTwo.status,200,v3InfoTwo.body);
  const v3ProjectPayload={
    title:'V3 browser-evidence comparison',
    question:'What original body wording is present in the document smoke report?',
    notes:'Two original documents, human-assessed context only.',
    mode:'evidence',
    sources:[JSON.parse(v3InfoOne.body),JSON.parse(v3InfoTwo.body)].map(x=>({
      path:x.path,sha256:x.sha256,
    })),
  };
  const v3ProjectResult=await v3Request({route:'/api/research/studio/save',
    body:v3ProjectPayload});
  assert.equal(v3ProjectResult.status,200,v3ProjectResult.body);
  const v3ProjectPath=JSON.parse(v3ProjectResult.body).path;
  await page.locator('#rcTitle').waitFor();
  await page.locator('#rcRefreshProjects').click();
  await page.waitForFunction(p=>[...document.querySelectorAll('#rcProject option')]
    .some(x=>x.value===p),v3ProjectPath);
  await page.locator('#rcProject').selectOption(v3ProjectPath);
  const v3Preparing=page.waitForResponse(r=>
    r.url().includes('/api/research/studio/compare/prepare')&&r.request().method()==='POST');
  await page.locator('#rcPrepare').click();
  const v3Prepared=await v3Preparing;
  assert.equal(v3Prepared.status(),200,await v3Prepared.text());
  const v3PreparedData=await v3Prepared.json();
  assert.equal(v3PreparedData.no_model,true);
  assert.equal(v3PreparedData.source_count,2);
  assert.ok(v3PreparedData.evidence_count>=2);
  await page.waitForFunction(()=>document.querySelectorAll('#rcSourceCards .rc-source').length===2);
  const v3Sources=page.locator('#rcSourceCards .rc-source');
  const sourceA=v3Sources.first(),sourceB=v3Sources.last();
  assert.ok(await sourceA.locator('.rc-passage').count()>0);
  assert.ok(await sourceB.locator('.rc-passage').count()>0);
  await sourceA.locator('select[data-rc-stance]').first().selectOption('supports');
  await sourceA.locator('textarea[data-rc-rationale]').first().fill(
    'This original excerpt appears in the first source document.');
  await sourceB.locator('select[data-rc-stance]').first().selectOption('contradicts');
  await sourceB.locator('textarea[data-rc-rationale]').first().fill(
    'This reviewer considers the second source to challenge the claim.');
  await sourceA.locator('select[data-rc-method]').selectOption('observational');
  await sourceB.locator('select[data-rc-quality]').selectOption('moderate');
  await sourceB.locator('textarea[data-rc-limits]').fill(
    'Only a constrained development test case; not a scientific validity finding.');
  const v3PreviewPromise=page.waitForResponse(r=>
    r.url().includes('/api/research/studio/compare/preview')&&r.request().method()==='POST');
  await page.locator('#rcPreview').click();
  const v3PreviewResponse=await v3PreviewPromise;
  assert.equal(v3PreviewResponse.status(),200,await v3PreviewResponse.text());
  const v3Report=(await v3PreviewResponse.json()).report;
  assert.equal(v3Report.disagreement_flag,true);
  assert.equal(v3Report.science_verified,false);
  assert.equal(v3Report.counts.supports,1);
  assert.equal(v3Report.counts.contradicts,1);
  assert.equal(v3Report.source_count,2);
  await page.waitForFunction(()=>document.querySelector('#rcSummary')?.textContent?.
    includes('Reviewer-labelled disagreement'));
  await page.locator('#rcSave').click();
  assert.match(await page.locator('#rcStatus').innerText(),/Acknowledge/);
  await page.locator('#rcConfirm').check();
  page.once('dialog',d=>d.accept());
  const v3Saving=page.waitForResponse(r=>
    r.url().includes('/api/research/studio/compare/save')&&r.request().method()==='POST');
  await page.locator('#rcSave').click();
  const v3SavedResponse=await v3Saving;
  assert.equal(v3SavedResponse.status(),200,await v3SavedResponse.text());
  const v3SavedPath=(await v3SavedResponse.json()).path;
  assert.ok(v3SavedPath.endsWith('.comparison.json'));
  const v3Historical=await v3Request({route:
    '/api/research/studio/compare/open?path='+encodeURIComponent(v3SavedPath)});
  assert.equal(v3Historical.status,200,v3Historical.body);
  assert.equal(JSON.parse(v3Historical.body).project_status,'current');
  await page.waitForFunction(p=>document.querySelector('#rcReviews')?.value===p,v3SavedPath);
  await page.locator('#rcOpen').click();
  await page.waitForFunction(()=>document.querySelector('#rcStatus')?.textContent?.includes('Historical review loaded'));
  assert.equal(await page.locator('#rcEditor').isVisible(),false);
  assert.equal(await page.locator('#rcMatrix .rc-matrix-source').count(),2);
  await page.screenshot({path:path.join(output,'research-studio-v3-comparison-review.png')});

  // V4 browser contract: V3 review selection is REAL; DOI data and publication
  // responses are deterministic, mocked external-provider-independent fixtures.
  // Python tests separately exercise actual Word build and source verification.
  const v4Metadata=[
    {path:'artifacts/research/sources/source-aaaaaaaaaaaaaaaaaaaaaaaa.source.json',
      sha256:'1'.repeat(64),doi:'10.5555/browser-source-a.2026',
      title:'<img src=x onerror=alert(1)> Source A test record',
      authors:['A. Example'],publication_date:'2026',
      retrieved_at:'2026-11-08T12:00:00+00:00',venue:'Fixture Journal'},
    {path:'artifacts/research/sources/source-bbbbbbbbbbbbbbbbbbbbbbbb.source.json',
      sha256:'2'.repeat(64),doi:'10.5555/browser-source-b.2025',
      title:'Second source test record',authors:['B. Example'],
      publication_date:'2025',retrieved_at:'2026-11-08T12:00:00+00:00',
      venue:'Fixture Journal'}
  ];
  const v4Sources=v3PreparedData.project.sources;
  const v4PrepareData={
    comparison_path:v3SavedPath,comparison_sha256:'c'.repeat(64),
    sources:v4Sources,source_status:v3PreparedData.source_status,
    claim:'Local reviewer comparison of original document text.',
    review_complete:true,metadata_records:v4Metadata,
    no_network_requests:true,source_files_modified:false,
  };
  const v4Mock=body=>({status:200,contentType:'application/json',body:JSON.stringify(body)});
  let v4PreflightRequests=0,v4DraftRequests=0;
  await page.route('**/api/research/studio/publish/prepare',route=>
    route.fulfill(v4Mock(v4PrepareData)));
  await page.route('**/api/research/studio/publish/preflight',async route=>{
    const input=route.request().postDataJSON();
    v4PreflightRequests++;
    assert.equal(input.bindings.length,2);
    assert.ok(input.bindings.every(x=>x.confirm_same_publication===true));
    assert.equal(input.style,'ieee');
    return route.fulfill(v4Mock({
      ready:true,word_build_valid:true,word_bytes:3607,
      reference_count:2,citation_style:'ieee',
      formatted_references:[
        '[1] A. Example, "Source A test record," 2026. doi: 10.5555/browser-source-a.2026.',
        '[2] B. Example, "Second source test record," 2025. doi: 10.5555/browser-source-b.2025.'
      ],
      report_markdown:'# Human-reviewed evidence report\n\nVerified reviewer evidence with [@r1] and [@r2].',
      warnings:['The author must check original publication metadata.'],
      source_bindings:input.bindings,no_files_saved:true,
      no_network_requests:true,science_verified:false,
      manual_reference_check_required:true,
    }));
  });
  await page.route('**/api/research/studio/publish/save-draft',route=>{
    v4DraftRequests++;
    const data=route.request().postDataJSON();
    assert.equal(data.acknowledgement,'SAVE DRAFT');
    assert.equal(data.confirm_checked_references,true);
    return route.fulfill(v4Mock({
      path:'artifacts/documents/fixture-report.document.json',
      editable_in:'Document Assistant',create_only:true,
      reference_count:2,citation_style:'ieee',source_files_modified:false,
    }));
  });
  await page.waitForFunction(()=>document.querySelector('#rpComparison')!==null);
  await page.locator('#rpRefresh').click();
  await page.waitForFunction(p=>[...document.querySelectorAll('#rpComparison option')]
    .some(x=>x.value===p),v3SavedPath);
  await page.locator('#rpComparison').selectOption(v3SavedPath);
  await page.locator('#rpPrepare').click();
  await page.waitForFunction(()=>document.querySelectorAll('#rpBindings .rp-link-card').length===2);
  assert.equal(await page.locator('#rpBindings img').count(),0,
    'DOI registry titles must render as safe text');
  const v4BindingCards=page.locator('#rpBindings .rp-link-card');
  await v4BindingCards.nth(0).locator('select[data-rp-record]').selectOption(v4Metadata[0].path);
  await v4BindingCards.nth(1).locator('select[data-rp-record]').selectOption(v4Metadata[1].path);
  await page.locator('#rpReportTitle').fill('Browser-tested academic evidence report');
  await page.locator('#rpAuthor').fill('Author Example');
  await page.locator('#rpIntroduction').fill('This bounded test checks evidence citations and report structure.');
  await page.locator('#rpLimitations').fill('These citations are mock records for UI testing, not real scholarly publications.');
  await page.locator('#rpConclusion').fill('The final interpretation requires the reviewer to check the original context.');
  await page.locator('#rpStyle').selectOption('ieee');
  await page.locator('#rpPreflight').click();
  assert.match(await page.locator('#rpStatus').innerText(),/genuine matching DOI/);
  await v4BindingCards.nth(0).locator('input[data-rp-match]').check();
  await v4BindingCards.nth(1).locator('input[data-rp-match]').check();
  const v4Preflighting=page.waitForResponse(r=>
    r.url().includes('/api/research/studio/publish/preflight')&&r.request().method()==='POST');
  await page.locator('#rpPreflight').click();
  const v4Preflight=await v4Preflighting;
  assert.equal(v4Preflight.status(),200,await v4Preflight.text());
  assert.equal(v4PreflightRequests,1);
  await page.waitForFunction(()=>document.querySelector('#rpReviewStatus')?.textContent?.
    includes('Word build passed'));
  assert.equal(await page.locator('#rpReferences li').count(),2);
  assert.equal(await page.locator('#rpSaveDraft').isDisabled(),false);
  await page.locator('#rpSaveDraft').click();
  assert.match(await page.locator('#rpStatus').innerText(),/Confirm source-to-DOI/);
  await page.locator('#rpConfirm').check();
  page.once('dialog',d=>d.accept());
  await page.locator('#rpSaveDraft').click();
  await page.waitForFunction(()=>document.querySelector('#rpOutput')?.textContent?.
    includes('fixture-report.document.json'));
  assert.equal(v4DraftRequests,1);
  assert.equal(await page.locator('#rpOutput a').count(),1);
  await page.screenshot({path:path.join(output,'research-studio-v4-academic-report.png')});

  // V5 browser: real V3 comparison selection; deterministic local-model response
  // fixture. Python contract tests separately exercise the server's strict
  // source revalidation and actual loopback-only HTTP transport.
  const v5Evidence=[{
    id:'S1-01',source:v4Sources[0].path,sha256:v4Sources[0].sha256,
    page:null,section:'Original saved text',offset:0,
    quote:'<img src=x onerror=alert(1)> Signed release checks were associated with lower deployment risk.',
    reviewer_stance:'supports'
  }];
  const v5Points=[{
    id:'P1',claim:'Signed release checks were associated with lower deployment risk in the reported case study.',
    evidence_ids:['S1-01'],uncertainty:'Limited, reviewer-described evidence is not a verified causal finding.',
    review_required:true,scientifically_verified:false
  }];
  const v5Draft='artifacts/research/ai/proposals/proposal-'+'a'.repeat(24)+'.ai.json';
  const v5Digest='f'.repeat(64);
  let v5Generated=false,v5Reviewed=0;
  await page.route('**/api/research/studio/ai/prepare',route=>{
    const input=route.request().postDataJSON();
    assert.equal(input.comparison_path,v3SavedPath);
    assert.equal(input.comparison_sha256,v4PrepareData.comparison_sha256);
    return route.fulfill(v4Mock({
      comparison_path:v3SavedPath,comparison_sha256:v4PrepareData.comparison_sha256,
      claim:v4PrepareData.claim,evidence:v5Evidence,source_count:2,
      human_review_complete:true,model_invoked:false,no_network_requests:true
    }));
  });
  await page.route('**/api/research/studio/ai/generate',route=>{
    const input=route.request().postDataJSON();
    assert.equal(input.acknowledgement,'ANALYSE LOCALLY');
    assert.equal(input.confirm_local_model,true);
    v5Generated=true;
    return route.fulfill(v4Mock({
      path:v5Draft,sha256:v5Digest,points:v5Points,evidence:v5Evidence,
      model:'fixture-local-ollama',provider:'ollama-loopback',
      human_review_required:true,scientifically_verified:false,no_cloud_fallback:true,
      published:false
    }));
  });
  await page.route('**/api/research/studio/ai/list',route=>
    route.fulfill(v4Mock({drafts:v5Generated?[{
      path:v5Draft,sha256:v5Digest,claim:v4PrepareData.claim,
      point_count:1,review_state:'unreviewed'
    }]:[],review_required:true})));
  await page.route('**/api/research/studio/ai/open?*',route=>
    route.fulfill(v4Mock({
      path:v5Draft,sha256:v5Digest,points:v5Points,evidence:v5Evidence,
      comparison_status:'current',historical_snapshot:true,
      human_review_required:true,science_verified:false
    })));
  await page.route('**/api/research/studio/ai/save-review',route=>{
    const input=route.request().postDataJSON();
    assert.equal(input.acknowledgement,'SAVE HUMAN REVIEW');
    assert.equal(input.confirm_unverified,true);
    assert.equal(input.draft_path,v5Draft);
    assert.equal(input.decisions.length,1);
    assert.equal(input.decisions[0].decision,'retain_for_review');
    v5Reviewed++;
    return route.fulfill(v4Mock({
      path:'artifacts/research/ai/reviews/review-'+'b'.repeat(24)+'.ai-review.json',
      reviewed:1,retained_for_review:1,published:false,source_files_modified:false
    }));
  });
  await page.locator('#raiTitle').waitFor();
  await page.locator('#raiRefresh').click();
  await page.waitForFunction(p=>[...document.querySelectorAll('#raiComparison option')]
    .some(x=>x.value===p),v3SavedPath);
  await page.locator('#raiComparison').selectOption(v3SavedPath);
  await page.locator('#raiPrepare').click();
  await page.waitForFunction(()=>document.querySelector('#raiGenerate')?.disabled===false);
  await page.locator('#raiGenerate').click();
  assert.match(await page.locator('#raiStatus').innerText(),/Explicitly consent/);
  await page.locator('#raiConsent').check();
  page.once('dialog',d=>d.accept());
  await page.locator('#raiGenerate').click();
  await page.waitForFunction(()=>document.querySelectorAll('#raiPoints .rai-point').length===1);
  assert.equal(v5Generated,true);
  assert.equal(await page.locator('#raiPoints img').count(),0,
    'AI and cited source HTML are untrusted plain text');
  assert.match(await page.locator('#raiPoints').innerText(),/Limited, reviewer-described evidence/);
  await page.locator('#raiSaveReview').click();
  assert.match(await page.locator('#raiStatus').innerText(),/Confirm your individual review/);
  await page.locator('#raiHumanConfirm').check();
  await page.locator('[data-rai-decision="P1"]').selectOption('retain_for_review');
  await page.locator('[data-rai-note="P1"]').fill(
    'This claim is retained only for further manual examination of the original study.');
  page.once('dialog',d=>d.accept());
  await page.locator('#raiSaveReview').click();
  await page.waitForFunction(()=>document.querySelector('#raiStatus')?.textContent?.
    includes('Saved 1 human review'));
  assert.equal(v5Reviewed,1);
  await page.locator('#raiReloadDrafts').click();
  await page.locator('#raiDrafts').selectOption(v5Draft);
  await page.locator('#raiOpen').click();
  await page.waitForFunction(()=>document.querySelector('#raiReviewState')?.textContent?.
    includes('Historical proposal'));
  await page.screenshot({path:path.join(output,'research-studio-v5-local-ai-review.png')});

  // V6 — original evidence and human review must cross studios only on approval.
  const v6ReviewPath='artifacts/research/ai/reviews/review-'+'b'.repeat(24)+'.ai-review.json';
  const v6ReviewSha='c'.repeat(64);
  const v6Audit='artifacts/research/handoffs/handoff-'+'d'.repeat(24)+'.handoff.json';
  const v6DevFile='artifacts/research/handoffs/developer-'+'e'.repeat(24)+'.md';
  let v6Saved=0;
  await page.route('**/api/research/studio/handoff/sources',route=>
    route.fulfill(v4Mock({
      comparisons:[{path:v3SavedPath,sha256:v4PrepareData.comparison_sha256,
        claim:v4PrepareData.claim}],
      human_reviews:[{path:v6ReviewPath,sha256:v6ReviewSha,
        comparison_path:v3SavedPath,count:1}]
    })));
  await page.route('**/api/research/studio/handoff/preview',route=>{
    const input=route.request().postDataJSON();
    assert.equal(input.target,'developer');
    assert.equal(input.comparison_path,v3SavedPath);
    assert.equal(input.review_path,v6ReviewPath);
    return route.fulfill(v4Mock({
      target:'developer',preview:'Untrusted source data: <img src=x onerror=alert(1)>\nSHA-256 checked.',
      evidence_count:2,retained_unverified_count:1,
      sources:[],publication_ready:false
    }));
  });
  await page.route('**/api/research/studio/handoff/save',route=>{
    const input=route.request().postDataJSON();
    assert.equal(input.acknowledgement,'CREATE REVIEW-ONLY HANDOFF');
    assert.equal(input.confirm_sources_checked,true);
    assert.equal(input.confirm_no_publication,true);
    assert.equal(input.review_sha256,v6ReviewSha);
    v6Saved++;
    return route.fulfill(v4Mock({
      path:v6Audit,sha256:'a'.repeat(64),target:'developer',
      target_path:v6DevFile,target_sha256:'f'.repeat(64),
      evidence_count:2,human_review_required:true,publication_ready:false,
      source_files_modified:false,model_invoked:false,external_action_performed:false
    }));
  });
  await page.route('**/api/research/studio/handoff/list',route=>
    route.fulfill(v4Mock({handoffs:v6Saved?[{
      path:v6Audit,sha256:'a'.repeat(64),target:'developer',
      target_path:v6DevFile,research_question:v4PrepareData.claim,
      created_at:'2026-11-09T06:00:00Z'
    }]:[]})));
  await page.route('**/api/research/studio/handoff/open?*',route=>
    route.fulfill(v4Mock({
      path:v6Audit,target:'developer',target_path:v6DevFile,
      source_status:'current',target_status:'current',
      evidence:[{id:'S1-01'}],retained_unverified_observations:[{id:'P1'}],
      publication_ready:false,audit_is_cryptographically_signed:false
    })));
  await page.locator('#rshTitle').waitFor();
  await page.locator('#rshRefresh').click();
  await page.waitForFunction(p=>[...document.querySelectorAll('#rshComparison option')]
    .some(x=>x.value===p),v3SavedPath);
  await page.locator('#rshComparison').selectOption(v3SavedPath);
  await page.locator('#rshReview').selectOption(v6ReviewPath);
  await page.locator('#rshTarget').selectOption('developer');
  assert.equal(await page.locator('#rshSave').isDisabled(),true);
  await page.locator('#rshPreview').click();
  await page.waitForFunction(()=>document.querySelector('#rshPreviewSummary')?.
    textContent?.includes('2 source excerpts'));
  assert.match(await page.locator('#rshEvidence').innerText(),/Untrusted source data/);
  assert.equal(await page.locator('#rshEvidence img').count(),0,
    'Untrusted source HTML must never render as DOM markup');
  await page.locator('#rshConsent').check();
  page.once('dialog',d=>d.accept());
  await page.locator('#rshSave').click();
  await page.waitForFunction(()=>document.querySelector('#rshStatus')?.
    textContent?.includes('Audited hand-off created'));
  assert.equal(v6Saved,1);
  await page.locator('#rshHistory').selectOption(v6Audit);
  await page.locator('#rshOpen').click();
  await page.waitForFunction(()=>document.querySelector('#rshDetails')?.
    textContent?.includes('Original source evidence: current'));
  await page.screenshot({path:path.join(output,'research-studio-v6-cross-studio-handoff.png')});

  // V7 — inspect read-only integrity, explicit backup consent and isolated staging.
  const v7Recovery='artifacts/research/recovery/snapshots/backup-'+'f'.repeat(24)+'.recovery.json';
  const v7Archive='artifacts/research/recovery/snapshots/backup-'+'f'.repeat(24)+'.research.zip';
  const v7Digest='e'.repeat(64);
  let v7Saved=0,v7Staged=0;
  await page.route('**/api/research/studio/acceptance/audit',route=>{
    const chosen=route.request().postDataJSON();
    assert.equal(chosen.comparison_path,v3SavedPath);
    assert.equal(chosen.comparison_sha256,v4PrepareData.comparison_sha256);
    assert.equal(chosen.review_path,v6ReviewPath);
    assert.equal(chosen.handoff_path,v6Audit);
    return route.fulfill(v4Mock({
      comparison_path:v3SavedPath,comparison_sha256:chosen.comparison_sha256,
      checked_artifacts:[{role:'original_source',path:'uploads/<img src=x onerror=alert(1)>.txt',
        sha256:'f'.repeat(64),bytes:500}],
      checked_source_count:2,checked_bytes:500,elapsed_ms:5.1,
      integrity:'verified_against_selected_sha256',
      manual_acceptance:[{item:'Verify all citations manually',
        status:'not_certified_by_software'}],
      science_verified:false,publication_ready:false,store_release_approved:false,
      no_model_invocation:true,no_network_request:true,originals_modified:false
    }));
  });
  await page.route('**/api/research/studio/acceptance/snapshot',route=>{
    const input=route.request().postDataJSON();
    assert.equal(input.acknowledgement,'SAVE PRIVATE RESEARCH RECOVERY');
    assert.equal(input.confirm_no_publication,true);
    assert.equal(input.handoff_path,v6Audit);
    v7Saved++;
    return route.fulfill(v4Mock({
      path:v7Recovery,sha256:v7Digest,
      archive_path:v7Archive,archive_sha256:'b'.repeat(64),
      file_count:4,checked_bytes:500,
      create_only:true,source_files_modified:false,published:false
    }));
  });
  await page.route('**/api/research/studio/acceptance/list',route=>
    route.fulfill(v4Mock({snapshots:v7Saved?[{
      path:v7Recovery,sha256:v7Digest,
      created_at:'2026-11-09T07:10:00Z',file_count:4
    }]:[],limit:16})));
  await page.route('**/api/research/studio/acceptance/verify',route=>{
    const input=route.request().postDataJSON();
    assert.equal(input.path,v7Recovery);
    assert.equal(input.sha256,v7Digest);
    return route.fulfill(v4Mock({
      valid_against_recorded_hashes:true,file_count:4,
      archive_sha256:'b'.repeat(64),restored:false,original_files_modified:false
    }));
  });
  await page.route('**/api/research/studio/acceptance/stage',route=>{
    const input=route.request().postDataJSON();
    assert.equal(input.acknowledgement,'STAGE FILES WITHOUT OVERWRITING');
    assert.equal(input.confirm_no_original_changes,true);
    v7Staged++;
    return route.fulfill(v4Mock({
      staging_path:'artifacts/research/recovery/staging/stage-'+'c'.repeat(24),
      file_count:4,original_files_modified:false,published:false,
      requires_manual_review:true
    }));
  });
  await page.locator('#rsaTitle').waitFor();
  await page.locator('#rsaRefresh').click();
  await page.waitForFunction(p=>[...document.querySelectorAll('#rsaComparison option')]
    .some(x=>x.value===p),v3SavedPath);
  await page.locator('#rsaComparison').selectOption(v3SavedPath);
  await page.locator('#rsaReview').selectOption(v6ReviewPath);
  await page.locator('#rsaHandoff').selectOption(v6Audit);
  assert.equal(await page.locator('#rsaSnapshot').isDisabled(),true);
  await page.locator('#rsaAudit').click();
  await page.waitForFunction(()=>document.querySelector('#rsaIntegrity')?.textContent?.
    includes('Source hash and excerpt checks passed'));
  assert.equal(await page.locator('#rsaFiles img').count(),0,
    'Untrusted filenames cannot become HTML elements');
  assert.match(await page.locator('#rsaGates').innerText(),/Not independently verified/);
  assert.match(await page.locator('#rsaNotice').count()+'',/0/,
    'No untrusted source should produce a separate notice element');
  await page.locator('#rsaConsent').check();
  page.once('dialog',d=>d.accept());
  await page.locator('#rsaSnapshot').click();
  await page.waitForFunction(()=>document.querySelector('#rsaStatus')?.textContent?.
    includes('Recovery copy created'));
  assert.equal(v7Saved,1);
  await page.locator('#rsaSaved').selectOption(v7Recovery);
  assert.equal(await page.locator('#rsaStage').isDisabled(),true);
  await page.locator('#rsaVerify').click();
  await page.waitForFunction(()=>document.querySelector('#rsaStage')?.disabled===false);
  page.once('dialog',d=>d.accept());
  await page.locator('#rsaStage').click();
  await page.waitForFunction(()=>document.querySelector('#rsaStatus')?.textContent?.
    includes('staged in isolation'));
  assert.equal(v7Staged,1);
  assert.match(await page.locator('#rsaRecoveryStatus').innerText(),/staging\/stage-/);
  await page.screenshot({path:path.join(output,'research-studio-v7-quality-recovery.png')});

  // V8 — passphrase-confirmed encrypted export and isolated clean-machine import.
  const v8Portable='artifacts/research/recovery/portable/capsule-'+'b'.repeat(24)+'.amrc8';
  const v8Digest='d'.repeat(64);
  let v8PortableCreated=0,v8PortableInspected=0,v8PortableStaged=0;
  await page.route('**/api/research/studio/portable/list',route=>
    route.fulfill(v4Mock({capsules:v8PortableCreated?[{
      path:v8Portable,sha256:v8Digest,created_at:'2026-11-09T07:33:00Z',file_count:4
    }]:[],ciphertext_only:true})));
  await page.route('**/api/research/studio/portable/create',route=>{
    const form=route.request().postDataJSON();
    assert.equal(form.path,v7Recovery);
    assert.equal(form.sha256,v7Digest);
    assert.equal(form.passphrase,'v8-test-recovery-long-passphrase');
    assert.equal(form.acknowledgement,'ENCRYPT PORTABLE BACKUP');
    assert.equal(form.confirm_user_will_store_separately,true);
    v8PortableCreated++;
    return route.fulfill(v4Mock({path:v8Portable,sha256:v8Digest,file_count:4,
      encrypted:true,format:'amrc8-aes-256-gcm-scrypt',originals_modified:false}));
  });
  await page.route('**/api/research/studio/portable/inspect',route=>{
    assert.match(route.request().headers()['content-type'],/multipart\/form-data/);
    v8PortableInspected++;
    return route.fulfill(v4Mock({
      capsule_sha256:v8Digest,file_count:4,verified_against_encrypted_manifest:true,
      trust_status:'quarantined_not_reinstated',manual_review_required:true,
      file_roles:[{role:'original_source',path:'uploads/<img src=x onerror=alert(1)>.txt',
        sha256:'a'.repeat(64),bytes:300}]
    }));
  });
  await page.route('**/api/research/studio/portable/stage',route=>{
    assert.match(route.request().postData(),/expected_sha256/);
    assert.match(route.request().postData(),/STAGE ENCRYPTED BACKUP/);
    v8PortableStaged++;
    return route.fulfill(v4Mock({staging_path:'artifacts/research/recovery/staging/stage-'+
      'c'.repeat(24),file_count:4,original_files_modified:false,published:false,
      restored_into_trusted_locations:false,manual_review_required:true}));
  });
  await page.locator('#rspTitle').waitFor();
  await page.locator('#rspReload').click();
  await page.locator('#rspSource').selectOption(v7Recovery);
  await page.locator('#rspPassword').fill('v8-test-recovery-long-passphrase');
  await page.locator('#rspConfirm').fill('v8-test-recovery-long-passphrase');
  await page.locator('#rspConsent').check();
  page.once('dialog',d=>d.accept());
  await page.locator('#rspEncrypt').click();
  await page.waitForFunction(()=>document.querySelector('#rspStatus')?.textContent?.
    includes('Encrypted recovery created'));
  assert.equal(v8PortableCreated,1);
  assert.equal(await page.locator('#rspPassword').inputValue(),'',
    'Recovery password must clear after successful export');
  await page.locator('#rspFile').setInputFiles({
    name:'independent-backup.amrc8',mimeType:'application/octet-stream',
    buffer:Buffer.from('encrypted-capsule-fixture')
  });
  await page.locator('#rspImportPass').fill('v8-test-recovery-long-passphrase');
  assert.equal(await page.locator('#rspStage').isDisabled(),true);
  await page.locator('#rspInspect').click();
  await page.waitForFunction(()=>document.querySelector('#rspStatus')?.textContent?.
    includes('Encrypted archive and original source digests verified'));
  assert.equal(v8PortableInspected,1);
  assert.equal(await page.locator('#rspFileList img').count(),0,
    'Untrusted imported source paths must never become HTML markup');
  await page.locator('#rspStageConsent').check();
  page.once('dialog',d=>d.accept());
  await page.locator('#rspStage').click();
  await page.waitForFunction(()=>document.querySelector('#rspStatus')?.textContent?.
    includes('safely staged in isolation'));
  assert.equal(v8PortableStaged,1);
  assert.equal(await page.locator('#rspImportPass').inputValue(),'',
    'Import password must clear after successful isolated staging');
  await page.screenshot({path:path.join(output,'research-studio-v8-encrypted-portable-recovery.png')});
  await page.unrouteAll();

  // Developer Studio V2.1: the *actual* locally bundled Monaco must be active.
  const replaceDeveloperSource = async (text) => {
    // Interact with Monaco's public, visible editing surface, not its
    // version-specific hidden textarea/contenteditable implementation.
    const surface=page.locator('#dsMonaco .monaco-editor');
    await surface.click({position:{x:70,y:55}});
    await page.keyboard.press('ControlOrMeta+a');
    await page.keyboard.insertText(text);
    await page.waitForFunction(value=>
      document.querySelector('#dsSourceText')?.value===value,text);
  };

  // Developer Studio V2: verified source editing, UTF-8 and trust-based saves.
  const devProject=path.join(data,'workspace','projects','developer-studio-v2');
  mkdirSync(devProject,{recursive:true});
  writeFileSync(path.join(devProject,'main.ts'),'export const title = "read-only";\n');
  writeFileSync(path.join(devProject,'other.py'),'print("second tab")\n');
  writeFileSync(path.join(devProject,'package.json'),JSON.stringify({
    dependencies:{"next":"^16.0.0","react":"^19.0.0"},
    scripts:{postinstall:"not-executed-during-v5-detection"}
  }));
  writeFileSync(path.join(devProject,'.env'),'PRIVATE_KEY=never-disclose');
  const devBefore=readFileSync(path.join(devProject,'main.ts'));
  await page.locator('.nav [data-page="developer"]').click();
  await page.locator('#dsPath').waitFor();
  await page.locator('#dsMonaco .monaco-editor').waitFor({state:'visible'});
  assert.equal(await page.locator('#dsMonaco').isVisible(),true,'Must load Monaco locally');
  await page.locator('#dsPath').fill(devProject);
  await page.locator('#dsOpen').click();
  await page.waitForFunction(() => document.querySelector('#dsProject')?.textContent?.includes('developer-studio-v2'));
  assert.match(await page.locator('#dsTrustState').innerText(), /Restricted/);
  assert.equal(await page.locator('.ds-files').getByText('.env').count(),0);
  await page.locator('.ds-entry', {hasText:'main.ts'}).click();
  await page.waitForFunction(() => document.querySelector('#dsSourceText')?.value?.includes('read-only'));
  assert.equal(await page.locator('#dsSourceText').getAttribute('readonly'),'');
  assert.equal(await page.locator('#dsSaveFile').isDisabled(),true);
  assert.deepEqual(readFileSync(path.join(devProject,'main.ts')),devBefore);
  // V5: actual server detection, evidence, language-mode override and inert tool checks.
  await page.waitForFunction(() => document.querySelector('#dsDetectedFile')?.textContent==='typescript');
  assert.match(await page.locator('#dsDetectedFrameworks').innerText(),/Next\.js/);
  assert.match(await page.locator('#dsDetectedEvidence').innerText(),/extension: \.ts/);
  assert.equal(await page.locator('#dsLanguageOverride').isEnabled(),true);
  await page.locator('#dsLanguageOverride').selectOption('python');
  assert.equal(await page.locator('#dsEditorLang').innerText(),'python');
  await page.locator('#dsLanguageOverride').selectOption('');
  assert.equal(await page.locator('#dsEditorLang').innerText(),'typescript');
  await page.locator('#dsLanguageTools').click();
  await page.waitForFunction(() => document.querySelector('#dsDetectedTools')?.textContent?.includes('version not verified') ||
    document.querySelector('#dsDetectedTools')?.textContent?.includes('Unavailable on the host PATH'));
  assert.deepEqual(readFileSync(path.join(devProject,'main.ts')),devBefore,'V5 inspection never writes files');
  await page.screenshot({path:path.join(output,'developer-studio-v5-language-intelligence.png')});
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsTrust').click();
  await page.waitForFunction(() => document.querySelector('#dsTrustState')?.textContent?.includes('Trusted'));
  assert.equal(await page.locator('#dsSourceText').getAttribute('readonly'),null);
  // V6 browser: explicit local LSP consent, source-grounded safe presentation.
  assert.equal(await page.locator('#dsLspStart').isDisabled(),true,
    'No language server may start before the operator chooses an installed tool');
  let v6Started=0,v6Queried=0,v6Stopped=0;
  await page.route('**/api/developer/studio/lsp/*',async route=>{
    const url=new URL(route.request().url());
    const endpoint=url.pathname.split('/').at(-1);
    const payload=route.request().postDataJSON?.()||{};
    let body={};
    if(endpoint==='servers'){
      body={servers:[{language:'typescript',binary:'typescript-language-server',
        status:'available',requires_trust:true,requires_explicit_start:true}],
        automatic_start:false,platform_sandbox:false};
    }else if(endpoint==='start'){
      assert.equal(payload.confirmed,true);
      assert.equal(payload.language,'typescript');
      v6Started++;
      body={session_id:'v'.repeat(48),language:'typescript',capabilities:{
        hoverProvider:true,completionProvider:true,definitionProvider:true,
        referencesProvider:true,renameProvider:true},source_modified:false};
    }else if(endpoint==='query'){
      v6Queried++;
      assert.equal(payload.path,'main.ts');
      assert.equal(payload.method,'textDocument/hover');
      body={method:payload.method,result:{text:'fixture hover · trusted local source'},
        source_modified:false};
    }else if(endpoint==='stop'){
      v6Stopped++;
      body={stopped:true,source_modified:false};
    }else if(endpoint==='document')body={source_modified:false};
    else if(endpoint==='diagnostics')body={files:[],source_modified:false};
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.locator('#dsLspRefresh').click();
  await page.locator('#dsLspSelect').selectOption('typescript');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsLspStart').click();
  await page.waitForFunction(() => document.querySelector('#dsLspStatus')?.textContent?.includes('server ready'));
  await page.locator('[data-lsp="textDocument/hover"]').click();
  await page.waitForFunction(() => document.querySelector('#dsLspResult')?.textContent?.includes('fixture hover'));
  assert.equal(v6Started,1);
  assert.equal(v6Queried,1);
  assert.deepEqual(readFileSync(path.join(devProject,'main.ts')),devBefore,
    'LSP hover cannot modify source');
  await page.locator('#dsLspStop').click();
  await page.waitForFunction(() => document.querySelector('#dsLspStatus')?.textContent?.includes('server stopped'));
  assert.equal(v6Stopped,1);
  await page.unrouteAll();
  await page.screenshot({path:path.join(output,'developer-studio-v6-lsp-consent.png')});
  // V7: exercise real private index API and live on-disk incremental invalidation.
  await page.locator('#dsIndexRefresh').click();
  await page.waitForFunction(() => document.querySelector('#dsIndexState')?.textContent?.includes('files indexed'));
  await page.locator('#dsIndexQuery').fill('title');
  await page.locator('#dsIndexSearch').click();
  await page.waitForFunction(() => document.querySelector('#dsIndexResults')?.textContent?.includes('title'));
  assert.match(await page.locator('#dsIndexState').innerText(),/symbols found/);
  await page.locator('#dsIndexResults').getByRole('button',{name:/Find lexical occurrences of title/}).first().click();
  await page.waitForFunction(() => document.querySelector('#dsIndexState')?.textContent?.includes('lexical occurrences'));
  await page.locator('#dsIndexOutline').click();
  await page.waitForFunction(() => document.querySelector('#dsIndexState')?.textContent?.includes('definitions'));
  assert.match(await page.locator('#dsIndexResults').innerText(),/title/);
  const v7NewSource=path.join(devProject,'new-indexed.py');
  writeFileSync(v7NewSource,'def new_function():\n    return 1\n');
  await page.locator('#dsIndexRefresh').click();
  await page.waitForFunction(() => document.querySelector('#dsIndexState')?.textContent?.includes('changed'));
  await page.locator('#dsIndexQuery').fill('new_function');
  await page.locator('#dsIndexSearch').click();
  await page.waitForFunction(() => document.querySelector('#dsIndexResults')?.textContent?.includes('new_function'));
  writeFileSync(v7NewSource,'def updated_function():\n    return 2\n');
  await page.locator('#dsIndexQuery').fill('updated_function');
  await page.locator('#dsIndexSearch').click();
  await page.waitForFunction(() => document.querySelector('#dsIndexResults')?.textContent?.includes('updated_function'));
  await page.locator('#dsIndexQuery').fill('new_function');
  await page.locator('#dsIndexSearch').click();
  await page.waitForFunction(() => document.querySelector('#dsIndexState')?.textContent?.startsWith('0 symbols'));
  assert.doesNotMatch(await page.locator('#dsIndexResults').innerText(),/new-indexed\.py/);
  rmSync(v7NewSource);
  await page.locator('#dsIndexQuery').fill('updated_function');
  await page.locator('#dsIndexSearch').click();
  await page.waitForFunction(() => document.querySelector('#dsIndexState')?.textContent?.startsWith('0 symbols'));
  assert.deepEqual(readFileSync(path.join(devProject,'main.ts')),devBefore,
    'V7 never changed source or saved an index file into the project');
  await page.screenshot({path:path.join(output,'developer-studio-v7-source-index.png')});
  // V8: register an independently installed adapter without executing it;
  // run only after separate confirmation. The real process/DAP layer is covered
  // by tests/test_developer_adapters.py on Windows, macOS and Linux.
  let v8Adapters=[],v8Runs=0,v8DAP=0,v8Registrations=0;
  await page.route('**/api/developer/studio/adapters/**',async route=>{
    const endpoint=new URL(route.request().url()).pathname.split('/').at(-1);
    const payload=route.request().postDataJSON?.()||{};
    let body={};
    if(endpoint==='catalog')body={registered:v8Adapters,roles:[
      'compiler','test','formatter','linter','package','debugger'],
      auto_install:false,auto_execute:false,platform_sandbox:false};
    else if(endpoint==='inspect')body={
      executable:payload.executable,sha256:'a'.repeat(64),
      size_bytes:123456,verification:'file bytes only; not a security audit'};
    else if(endpoint==='register'){
      assert.equal(payload.confirmed,true);
      assert.equal(payload.expected_sha256,'a'.repeat(64));
      assert.deepEqual(payload.args,['--version']);
      assert.equal(v8Runs,0,'Registering must never launch any executable');
      const item={id:payload.id,label:payload.label,language:payload.language,
        category:payload.category,protocol:payload.protocol,executable:payload.executable,
        sha256:payload.expected_sha256,args:payload.args};
      v8Adapters.push(item);v8Registrations++;
      body={registered:true,adapter:item,executable_started:false,
        installed_binary:false,project_files_modified:false};
    }else if(endpoint==='run'){
      assert.equal(payload.confirmed,true);
      assert.equal(payload.accept_execution_and_write_risk,true);
      v8Runs++;
      body={adapter_id:payload.id,status:'completed',exit_code:0,
        output:'<img src=x onerror=alert(1)> trusted fixture output',
        elapsed_ms:5,platform_sandbox:false,source_files_unchanged:'not_verified'};
    }else if(endpoint==='initialize'){
      assert.equal(payload.confirmed,true);
      assert.equal(payload.accept_execution_and_write_risk,true);
      v8DAP++;
      body={adapter_id:payload.id,status:'initialized_only',
        launch_sent:false,attach_sent:false,configuration_sent:false,
        capabilities:{supportsConfigurationDoneRequest:true},process_terminated:true};
    }else if(endpoint==='unregister'){
      v8Adapters=v8Adapters.filter(item=>item.id!==payload.id);
      body={unregistered:true,binary_uninstalled:false,project_files_modified:false};
    }
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.locator('#dsAdapterId').fill('external-python-test');
  await page.locator('#dsAdapterLabel').fill('External test runner');
  await page.locator('#dsAdapterExecutable').fill('/usr/local/bin/installed-tool');
  await page.locator('#dsAdapterArgs').fill('["--version"]');
  await page.locator('#dsAdapterInspect').click();
  await page.waitForFunction(()=>document.querySelector('#dsAdapterSha')?.value?.length===64);
  assert.equal(await page.locator('#dsAdapterRegister').isEnabled(),true);
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsAdapterRegister').click();
  await page.waitForFunction(()=>document.querySelector('#dsAdapterSelected')?.options?.length===2);
  assert.equal(v8Registrations,1);
  assert.equal(v8Runs,0,'Installed adapter registration does not launch a process');
  await page.locator('#dsAdapterSelected').selectOption('external-python-test');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsAdapterRun').click();
  await page.waitForFunction(()=>document.querySelector('#dsAdapterOutput')?.textContent?.includes('trusted fixture output'));
  assert.equal(v8Runs,1);
  assert.equal(await page.locator('#dsAdapterOutput img').count(),0,
    'Untrusted tool output must be inert text, not HTML');
  await page.locator('#dsAdapterId').fill('external-dap-probe');
  await page.locator('#dsAdapterLabel').fill('External debug adapter');
  await page.locator('#dsAdapterCategory').selectOption('debugger');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsAdapterRegister').click();
  await page.waitForFunction(()=>document.querySelector('#dsAdapterSelected')?.options?.length===3);
  await page.locator('#dsAdapterSelected').selectOption('external-dap-probe');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsAdapterRun').click();
  await page.waitForFunction(()=>document.querySelector('#dsAdapterOutput')?.textContent?.includes('initialized_only'));
  assert.equal(v8DAP,1);
  assert.equal(await page.locator('#dsAdapterOutput').innerText().then(s=>s.includes('"launch_sent": false')),true);
  assert.deepEqual(readFileSync(path.join(devProject,'main.ts')),devBefore,
    'Mocked V8 SDK controls must not change project files');
  await page.screenshot({path:path.join(output,'developer-studio-v8-toolchain-adapters.png')});
  await page.unrouteAll();
  await replaceDeveloperSource('export const title = "edited";\n');
  assert.equal(await page.locator('#dsSaveFile').isEnabled(),true);
  page.once('dialog',dialog=>dialog.dismiss());
  await page.locator('#newChat').click();
  assert.equal(await page.evaluate(() => location.hash), '#/developer', 'dirty edits must not be discarded on navigation');
  assert.match(await page.locator('#dsSourceText').inputValue(),/edited/);
  await page.locator('#dsModePreview').click();
  const previewState=await page.locator('#dsHighlighted').evaluate(node=>({
    hidden:node.hidden,display:getComputedStyle(node).display,
    rect:node.getBoundingClientRect().toJSON(),
    editorHidden:document.querySelector('#dsSourceText')?.hidden,
    pressed:document.querySelector('#dsModePreview')?.getAttribute('aria-pressed'),
    status:document.querySelector('#dsStatus')?.textContent,
  }));
  assert.equal(await page.locator('#dsHighlighted').isVisible(),true,JSON.stringify(previewState));
  await page.locator('#dsModeEdit').click();
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsSaveFile').click();
  await page.waitForFunction(() => document.querySelector('#dsStatus')?.textContent?.includes('Saved:'));
  assert.equal(readFileSync(path.join(devProject,'main.ts'),'utf8'),'export const title = "edited";\n');
  await page.locator('.ds-entry', {hasText:'other.py'}).click();
  await page.waitForFunction(() => document.querySelectorAll('.ds-tab').length===2);
  await page.locator('.ds-tab-select', {hasText:'main.ts'}).click();
  await replaceDeveloperSource('export const title = "unsaved";\n');
  writeFileSync(path.join(devProject,'main.ts'),'export const title = "externally edited";\n');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsSaveFile').click();
  await page.waitForFunction(() => document.querySelector('#dsStatus')?.textContent?.includes('Save blocked:'));
  assert.match(readFileSync(path.join(devProject,'main.ts'),'utf8'),/externally edited/);
  assert.match(await page.locator('#dsSourceText').inputValue(),/unsaved/);
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsReloadFile').click();
  await page.waitForFunction(() => document.querySelector('#dsSourceText')?.value?.includes('externally edited'));
  await page.screenshot({path:path.join(output,'developer-studio-v2-safe-editor.png')});

  // V3: real Monaco split, disk diff, private recovery and reversible file ops.
  await page.locator('#dsSplit').click();
  await page.locator('#dsMonacoSplit .monaco-editor').waitFor({state:'visible'});
  assert.equal(await page.locator('#dsSplit').getAttribute('aria-pressed'),'true');
  await replaceDeveloperSource('export const title = "v3 recovery";\n');
  const savedSource=readFileSync(path.join(devProject,'main.ts'));
  await page.locator('#dsSnapshot').click();
  await page.waitForFunction(() => document.querySelector('#dsStatus')?.textContent?.includes('recovery snapshot recorded'));
  assert.deepEqual(readFileSync(path.join(devProject,'main.ts')),savedSource,'snapshot must never change disk source');
  await page.locator('#dsDiff').click();
  await page.waitForFunction(() =>
    document.querySelector('#dsDiffPreview')?.hidden===false ||
    document.querySelector('#dsStatus')?.textContent?.includes('Cannot generate diff:'));
  const diffDebug=await page.locator('#dsDiffPreview').evaluate(node=>({
    hidden:node.hidden,style:node.style.display,display:getComputedStyle(node).display,
    status:document.querySelector('#dsStatus')?.textContent,
    text:node.textContent?.slice(0,250),mode:document.querySelector('#dsModeEdit')?.getAttribute('aria-pressed')
  }));
  assert.equal(await page.locator('#dsDiffPreview').isVisible(),true,JSON.stringify(diffDebug));
  assert.match(await page.locator('#dsDiffPreview').innerText(),/Saved source/);
  assert.match(await page.locator('#dsDiffPreview').innerText(),/v3 recovery/);
  await page.locator('#dsModeEdit').click();
  const acceptRecovery=dialog=>dialog.accept();
  page.on('dialog',acceptRecovery);
  await page.locator('#dsRecover').click();
  await page.waitForFunction(() => document.querySelector('#dsStatus')?.textContent?.includes('Recovered an unsaved working copy'));
  page.off('dialog',acceptRecovery);
  assert.deepEqual(readFileSync(path.join(devProject,'main.ts')),savedSource);
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsReloadFile').click();
  await page.waitForFunction(() => document.querySelector('#dsSaveFile')?.disabled===true);
  const withFilename=dialog=>dialog.type()==='prompt'?dialog.accept('generated.txt'):dialog.accept();
  page.on('dialog',withFilename);
  await page.locator('#dsCreate').click();
  await page.waitForFunction(() => Array.from(document.querySelectorAll('.ds-file-name')).some(n=>n.textContent==='generated.txt'));
  assert.equal(readFileSync(path.join(devProject,'generated.txt')).length,0);
  page.off('dialog',withFilename);
  await page.locator('.ds-entry',{hasText:'generated.txt'}).click();
  await page.waitForFunction(() => document.querySelector('#dsFilename')?.textContent==='generated.txt');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsTrash').click();
  await page.waitForFunction(() => !Array.from(document.querySelectorAll('.ds-file-name')).some(n=>n.textContent==='generated.txt'));
  assert.equal(existsSync(path.join(devProject,'generated.txt')),false);
  page.on('dialog',withFilename);
  await page.locator('#dsRestore').click();
  await page.waitForFunction(() => Array.from(document.querySelectorAll('.ds-file-name')).some(n=>n.textContent==='generated.txt'));
  page.off('dialog',withFilename);
  assert.equal(readFileSync(path.join(devProject,'generated.txt')).length,0);
  await page.screenshot({path:path.join(output,'developer-studio-v3-safe-lifecycle.png')});

  // V4: literal search, guarded replacement proposal, keyboard navigation.
  assert.equal(await page.locator('#dsRootStrip .ds-root-chip').count()>=1,true,
    'Multi-root navigator must show approved locations');
  await page.locator('#dsSearchQuery').fill('externally');
  await page.locator('#dsSearchGo').click();
  await page.locator('#dsSearchResults .ds-search-hit').first().waitFor();
  assert.match(await page.locator('#dsResultSummary').innerText(),/matches/);
  assert.equal(await page.locator('#dsSearchResults .ds-search-hit').count()>=1,true);
  await page.locator('#dsSearchResults .ds-search-hit').first().click();
  await page.waitForFunction(() => document.querySelector('#dsFilename')?.textContent==='main.ts');
  const v4Before=readFileSync(path.join(devProject,'main.ts'));
  await page.locator('#dsReplaceValue').fill('reviewed');
  await page.locator('#dsReplaceReview').click();
  await page.locator('#dsReplacePreview').waitFor({state:'visible'});
  assert.match(await page.locator('#dsReplacePreview').innerText(),/reviewed/);
  assert.deepEqual(readFileSync(path.join(devProject,'main.ts')),v4Before,
    'Search-and-replace preview must never write source');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsReplaceApply').click();
  await page.waitForFunction(() => document.querySelector('#dsSourceText')?.value?.includes('reviewed'));
  assert.deepEqual(readFileSync(path.join(devProject,'main.ts')),v4Before,
    'Loading a proposed replacement must create unsaved text only');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsSaveFile').click();
  await page.waitForFunction(() => document.querySelector('#dsStatus')?.textContent?.includes('Saved:'));
  assert.match(readFileSync(path.join(devProject,'main.ts'),'utf8'),/reviewed/);

  await page.keyboard.press('ControlOrMeta+Shift+P');
  assert.equal(await page.locator('#dsCommandPalette').evaluate(node=>node.open),true);
  await page.locator('#dsPaletteFilter').fill('Focus source search');
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#dsCommandPalette').evaluate(node=>node.open),false);
  assert.equal(await page.evaluate(() => document.activeElement?.id),'dsSearchQuery');
  await page.locator('#dsPanelHandle').focus();
  await page.keyboard.press('ArrowRight');
  assert.equal(await page.locator('#dsPanelHandle').getAttribute('aria-valuenow'),'37');

  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsRemember').check();
  const navSaved=await page.evaluate(()=>
    JSON.parse(localStorage.getItem('automoto.developer.navigation.v4')||'null'));
  assert.equal(navSaved?.project,devProject);
  assert.equal(navSaved?.files?.includes('main.ts'),true);
  assert.equal(JSON.stringify(navSaved).includes('reviewed'),false,
    'Navigation persistence must not contain source text');

  const initialViewport=page.viewportSize();
  await page.setViewportSize({width:390,height:844});
  await page.locator('#dsShowEditor').click();
  assert.equal(await page.locator('section[aria-label="Project files"]').isVisible(),false);
  assert.equal(await page.locator('section[aria-label="Source editor"]').isVisible(),true);
  await page.locator('#dsShowExplorer').click();
  assert.equal(await page.locator('section[aria-label="Project files"]').isVisible(),true);
  assert.equal(await page.locator('section[aria-label="Source editor"]').isVisible(),false);
  if(initialViewport)await page.setViewportSize(initialViewport);
  await page.screenshot({path:path.join(output,'developer-studio-v4-project-navigation.png')});

  // Reload the app to prove opt-in session recovery revalidates the project and
  // reloads sources from disk instead of caching source bytes in localStorage.
  await page.reload();
  await page.locator('#dsRestoreSession').waitFor();
  assert.equal(await page.locator('#dsRemember').isChecked(),true);
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#dsRestoreSession').click();
  await page.waitForFunction(() =>
    document.querySelector('#dsStatus')?.textContent?.includes('Session navigation restored'));
  assert.match(await page.locator('#dsSourceText').inputValue(),/reviewed/);
  assert.equal(await page.locator('#dsSaveFile').isDisabled(),true,
    'Resuming navigation must not create or save unsaved source');
  assert.equal(await page.locator('#dsRootStrip .ds-root-chip').count()>=2,true,
    'Multi-root navigator must retain the workspace and selected project');
  await page.locator('#dsSearchQuery').fill('reviewed');
  await page.locator('#dsSearchAcross').selectOption('all');
  await page.locator('#dsSearchGo').click();
  await page.waitForFunction(()=>
    document.querySelectorAll('#dsSearchResults .ds-search-hit').length>=2);
  assert.equal(await page.locator('#dsSearchResults .ds-search-hit').count()>=2,true,
    'Explicit all-roots search must include matching files from approved roots');
  await page.locator('#dsClearSession').click();
  assert.equal(await page.evaluate(()=>
    localStorage.getItem('automoto.developer.navigation.v4')),null);
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

/* Research Studio V7: private acceptance audit and non-destructive recovery. */
export function mountResearchAcceptance({host,api,toast}){
  host.innerHTML=[
    '<section class="rsa-shell" aria-labelledby="rsaTitle">',
    '<header class="rsa-hero"><div><span class="rsa-kicker">RESEARCH STUDIO · V7 · QUALITY & RECOVERY</span>',
    '<h3 id="rsaTitle">Verify evidence. Protect original work.</h3>',
    '<p>Run source-integrity checks, create a private recovery copy and verify or stage that copy without overwriting any original files.</p></div>',
    '<span class="rsa-tag">7 of 7 · Development acceptance</span></header>',
    '<p class="rsa-notice"><strong>Release is not approved.</strong> A checksum can detect changed bytes, ',
    'but cannot certify research findings, peer review, citation quality, accessibility, a valid backup on another device or Store publication. ',
    'All manual acceptance gates remain open until separately verified.</p>',
    '<section class="rsa-panel" aria-labelledby="rsaSelectTitle"><h4 id="rsaSelectTitle">1. Select a reviewed research chain</h4>',
    '<div class="rsa-fields">',
    '<label>Completed V3 research comparison<select id="rsaComparison" class="input"><option value="">Choose saved comparison</option></select></label>',
    '<label>Optional V5 human AI review<select id="rsaReview" class="input"><option value="">No AI observations included</option></select></label>',
    '<label class="rsa-wide">Optional V6 hand-off audit<select id="rsaHandoff" class="input"><option value="">No hand-off included</option></select></label>',
    '</div>',
    '<div class="rsa-actions"><button type="button" class="btn" id="rsaRefresh">Refresh saved research</button>',
    '<button type="button" class="btn primary" id="rsaAudit">Run integrity and readiness checks</button></div>',
    '<p class="rsa-hint">The audit reopens the original documents, checks exact quotations and associated human review decisions. Source records must be unchanged to create a new recovery copy.</p>',
    '<div class="rsa-results"><h5>Integrity result</h5><div id="rsaIntegrity" class="rsa-state" aria-live="polite">No audit has been run.</div>',
    '<div id="rsaFiles" class="rsa-files"></div>',
    '<h5>Independent manual acceptance gates</h5><ul id="rsaGates" class="rsa-gates"></ul></div>',
    '<label class="rsa-consent"><input type="checkbox" id="rsaConsent">',
    ' I authorise a new private local recovery copy of the verified selected records. I understand this is not an off-device backup, publication or automatic restoration.</label>',
    '<button type="button" class="btn primary" id="rsaSnapshot" disabled>Create verified private recovery copy</button></section>',
    '<section class="rsa-panel" aria-labelledby="rsaRecoveryTitle"><div class="rsa-heading">',
    '<h4 id="rsaRecoveryTitle">2. Recover safely without overwriting</h4>',
    '<button class="btn" type="button" id="rsaReload">Refresh copies</button></div>',
    '<label>Saved recovery snapshots<select class="input" id="rsaSaved"><option value="">Choose a saved copy</option></select></label>',
    '<div class="rsa-actions"><button type="button" class="btn" id="rsaVerify">Verify archive and every file</button>',
    '<button type="button" class="btn" id="rsaStage" disabled>Stage recovery into a separate folder</button></div>',
    '<div id="rsaRecoveryStatus" class="rsa-state" aria-live="polite">',
    'A recovery copy must first pass its recorded hash and archive member checks before being staged.</div>',
    '<p class="rsa-hint">Staging creates new private files with their own manifest. It never replaces an uploaded source, original research, approved report or cross-studio draft. Examine staged files manually before any subsequent use.</p>',
    '</section>',
    '<p class="rsa-status" id="rsaStatus" role="status" aria-live="polite">Research acceptance requires a complete saved V3 comparison.</p>',
    '</section>'
  ].join('');
  const el=id=>host.querySelector('#'+id);
  const create=(tag,content,cls)=>{
    const n=document.createElement(tag);n.textContent=String(content??'');
    if(cls)n.className=cls;return n;
  };
  const opt=(text,value)=>{
    const e=document.createElement('option');e.value=value;e.textContent=text;return e;
  };
  let catalog={comparisons:[],human_reviews:[]},handoffs=[],backups=[];
  let audited=null,verified=null,requestId=0,busy=false;
  function status(msg,error=false){
    el('rsaStatus').textContent=msg;el('rsaStatus').classList.toggle('rsa-error',error);
    if(error&&toast)toast(msg,'bad');
  }
  function invalidate(){
    audited=null;requestId++;el('rsaSnapshot').disabled=true;
    el('rsaConsent').checked=false;
    el('rsaIntegrity').textContent='Selection changed. Run integrity checks again.';
    el('rsaFiles').replaceChildren();el('rsaGates').replaceChildren();
  }
  function clearVerification(){
    verified=null;el('rsaStage').disabled=true;
    el('rsaRecoveryStatus').textContent='Select a recovery copy and verify its archive before staging.';
  }
  function selection(){
    const comparison=catalog.comparisons.find(x=>x.path===el('rsaComparison').value);
    if(!comparison)return null;
    const review=catalog.human_reviews.find(x=>x.path===el('rsaReview').value);
    if(el('rsaReview').value&&(!review||review.comparison_path!==comparison.path))return null;
    const handoff=handoffs.find(x=>x.path===el('rsaHandoff').value);
    if(el('rsaHandoff').value&&!handoff)return null;
    return {
      comparison_path:comparison.path,comparison_sha256:comparison.sha256,
      ...(review?{review_path:review.path,review_sha256:review.sha256}:{}),
      ...(handoff?{handoff_path:handoff.path,handoff_sha256:handoff.sha256}:{})
    };
  }
  function reviewsForComparison(){
    const selected=el('rsaReview'),current=selected.value,path=el('rsaComparison').value;
    selected.replaceChildren(opt('No AI observations included',''));
    for(const r of catalog.human_reviews.filter(x=>x.comparison_path===path))
      selected.append(opt(r.count+' reviewed points · '+r.path.split('/').pop(),r.path));
    if([...selected.options].some(x=>x.value===current))selected.value=current;
  }
  function restoreList(select,items,placeholder,display){
    const previous=select.value;select.replaceChildren(opt(placeholder,''));
    for(const item of items)select.append(opt(display(item),item.path));
    if([...select.options].some(x=>x.value===previous))select.value=previous;
  }
  async function refresh(){
    const [source,handoff]=await Promise.all([
      api('/api/research/studio/handoff/sources'),
      api('/api/research/studio/handoff/list')
    ]);
    if(!host.isConnected)return;
    catalog={comparisons:source.comparisons||[],human_reviews:source.human_reviews||[]};
    handoffs=handoff.handoffs||[];
    restoreList(el('rsaComparison'),catalog.comparisons,'Choose saved comparison',x=>x.claim+' · '+x.path.split('/').pop());
    reviewsForComparison();
    restoreList(el('rsaHandoff'),handoffs,'No hand-off included',x=>x.target+' · '+x.research_question);
    invalidate();
    status('Loaded '+catalog.comparisons.length+' completed research comparisons.');
  }
  async function refreshBackups(preferred){
    const response=await api('/api/research/studio/acceptance/list');
    if(!host.isConnected)return;
    backups=response.snapshots||[];
    const list=el('rsaSaved'),before=preferred||list.value;
    list.replaceChildren(opt('Choose a saved copy',''));
    for(const item of backups){
      list.append(opt((item.created_at||'Needs inspection')+' · '+item.file_count+' checked files',item.path));
    }
    if([...list.options].some(x=>x.value===before))list.value=before;
    clearVerification();
  }
  function displayAudit(data){
    el('rsaIntegrity').textContent='Source hash and excerpt checks passed for '+data.checked_source_count+
      ' source(s) and '+data.checked_artifacts.length+' records ('+data.checked_bytes+
      ' bytes examined, '+data.elapsed_ms+' ms server processing). Academic validation and release remain unapproved.';
    el('rsaFiles').replaceChildren();
    for(const file of data.checked_artifacts){
      const line=create('div',file.role+' · '+file.path+' · SHA-256 '+file.sha256+' · '+file.bytes+' bytes');
      el('rsaFiles').append(line);
    }
    el('rsaGates').replaceChildren();
    for(const gate of data.manual_acceptance||[]){
      const item=document.createElement('li');
      item.append(create('strong','Not independently verified: '),document.createTextNode(gate.item));
      el('rsaGates').append(item);
    }
  }
  for(const id of ['rsaComparison','rsaReview','rsaHandoff']){
    el(id).onchange=()=>{if(id==='rsaComparison')reviewsForComparison();invalidate();};
  }
  el('rsaSaved').onchange=clearVerification;
  el('rsaConsent').onchange=()=>{el('rsaSnapshot').disabled=!audited||!el('rsaConsent').checked||busy;};
  el('rsaRefresh').onclick=async()=>{try{await refresh();}catch(e){status('Could not refresh research: '+e.message,true);}};
  el('rsaAudit').onclick=async()=>{
    const chosen=selection();if(!chosen){status('Select a completed, verified V3 comparison first.',true);return;}
    const seq=++requestId;audited=null;el('rsaSnapshot').disabled=true;el('rsaConsent').checked=false;
    busy=true;el('rsaAudit').disabled=true;
    try{
      status('Revalidating the exact source files, evidence offsets, reviews and prior hand-off records…');
      const response=await api('/api/research/studio/acceptance/audit',chosen);
      if(!host.isConnected||seq!==requestId)return;
      audited={chosen,serial:JSON.stringify(chosen)};
      displayAudit(response);
      status('Integrity checks passed. Manual release gates remain open; a separate private backup requires your consent.');
    }catch(e){el('rsaIntegrity').textContent='Integrity audit blocked: '+e.message;
      status('Cannot confirm source integrity: '+e.message,true);}
    finally{busy=false;el('rsaAudit').disabled=false;}
  };
  el('rsaSnapshot').onclick=async()=>{
    const current=selection();
    if(!audited||!current||JSON.stringify(current)!==audited.serial||!el('rsaConsent').checked){
      status('Re-audit this exact selection and authorise its backup first.',true);return;
    }
    if(!window.confirm('Make a new private, create-only research recovery archive? No original document is changed. This is not a remote backup or publication.'))return;
    busy=true;el('rsaSnapshot').disabled=true;
    try{
      const result=await api('/api/research/studio/acceptance/snapshot',{
        ...current,acknowledgement:'SAVE PRIVATE RESEARCH RECOVERY',
        confirm_no_publication:true
      });
      await refreshBackups(result.path);invalidate();
      el('rsaRecoveryStatus').textContent='Private copy created: '+result.archive_path+
        ' · '+result.file_count+' files · archive SHA-256 '+result.archive_sha256+
        '. Verify its contents before staging or relying on this copy.';
      status('Recovery copy created without modifying original research.');
    }catch(e){status('Recovery creation blocked: '+e.message,true);}
    finally{busy=false;}
  };
  el('rsaReload').onclick=async()=>{try{await refreshBackups();status('Recovery catalogue refreshed.');}
    catch(e){status('Could not list private backups: '+e.message,true);}};
  el('rsaVerify').onclick=async()=>{
    const chosen=backups.find(x=>x.path===el('rsaSaved').value);
    if(!chosen){status('Choose a saved recovery copy.',true);return;}
    const seq=++requestId;clearVerification();
    try{
      const result=await api('/api/research/studio/acceptance/verify',{
        path:chosen.path,sha256:chosen.sha256
      });
      if(!host.isConnected||seq!==requestId)return;
      verified=chosen;el('rsaStage').disabled=false;
      el('rsaRecoveryStatus').textContent='Exact archive and '+result.file_count+
        ' original file checksums match the saved manifest. SHA-256: '+
        result.archive_sha256+'. No files restored. This does not prove academic truth or an off-device backup.';
      status('Local recovery archive validated. Staging remains an explicit separate action.');
    }catch(e){status('Recovery verification failed: '+e.message,true);
      el('rsaRecoveryStatus').textContent='Verification failed. Do not rely on this archive until investigated.';}
  };
  el('rsaStage').onclick=async()=>{
    if(!verified||el('rsaSaved').value!==verified.path){
      status('Verify this exact saved archive before staging.',true);return;
    }
    if(!window.confirm('Stage verified source copies in a separate private recovery folder? Original uploads, projects and documents will NOT be replaced.'))return;
    el('rsaStage').disabled=true;
    try{
      const result=await api('/api/research/studio/acceptance/stage',{
        path:verified.path,sha256:verified.sha256,
        acknowledgement:'STAGE FILES WITHOUT OVERWRITING',
        confirm_no_original_changes:true
      });
      el('rsaRecoveryStatus').textContent='Staged '+result.file_count+
        ' files at '+result.staging_path+'. Inspect the staging manifest before manually deciding what to use. Originals unchanged.';
      status('Verified research material staged in isolation. No publication or automatic restoration.');
    }catch(e){status('Staging blocked: '+e.message,true);}
    finally{verified=null;el('rsaStage').disabled=true;}
  };
  Promise.all([refresh(),refreshBackups()]).catch(e=>status('V7 acceptance workspace unavailable: '+e.message,true));
}

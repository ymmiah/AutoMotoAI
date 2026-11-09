/* Research Studio V8 — portable encrypted recovery with separate inspection and staging. */
export function mountResearchPortable({host,api,uploadCapsule,downloadCapsule,toast}){
  host.innerHTML=[
    '<section class="rsp-shell" aria-labelledby="rspTitle">',
    '<header class="rsp-heading"><div><span class="rsp-eyebrow">RESEARCH STUDIO · V8 · PORTABLE RESILIENCE</span>',
    '<h3 id="rspTitle">Password-encrypted recovery across devices</h3>',
    '<p>Create an encrypted copy of a verified V7 backup, download it for separate storage, ',
    'then import and inspect that file on another AutoMoto installation without overwriting your work.</p></div>',
    '<span class="rsp-chip">AES-256-GCM · scrypt</span></header>',
    '<p class="rsp-warning"><strong>Your passphrase is essential.</strong> It is not saved, transmitted to a cloud service, ',
    'or recoverable by AutoMoto. Use a long, unique passphrase and store it separately from the encrypted file. ',
    'Downloading a file is not proof that it was copied off-device. Release and academic verification are still separate.</p>',
    '<div class="rsp-grid">',
    '<section class="rsp-panel" aria-labelledby="rspExportTitle"><h4 id="rspExportTitle">1. Encrypt an existing verified backup</h4>',
    '<label class="rsp-field">Existing V7 recovery snapshot<select class="input" id="rspSource"><option value="">Select verified local recovery</option></select></label>',
    '<label class="rsp-field">New recovery passphrase (16+ characters)<input class="input" id="rspPassword" type="password" autocomplete="new-password" maxlength="128" spellcheck="false"></label>',
    '<label class="rsp-field">Confirm recovery passphrase<input class="input" id="rspConfirm" type="password" autocomplete="new-password" maxlength="128" spellcheck="false"></label>',
    '<label class="rsp-check"><input id="rspConsent" type="checkbox"> I understand the passphrase cannot be recovered and will independently save the encrypted file off this device.</label>',
    '<button type="button" class="btn primary" id="rspEncrypt">Create encrypted copy</button>',
    '<div class="rsp-divider"></div><div class="rsp-actions"><h5>Encrypted copies</h5><button type="button" class="btn" id="rspReload">Refresh</button></div>',
    '<label class="rsp-field">Select a portable recovery file<select class="input" id="rspExports"><option value="">Select encrypted capsule</option></select></label>',
    '<button type="button" class="btn" id="rspDownload">Download encrypted .amrc8 file</button>',
    '<p class="rsp-hint">Only encrypted data is downloaded. File contents, original source paths and citations are inside authenticated ciphertext.</p></section>',
    '<section class="rsp-panel" aria-labelledby="rspImportTitle"><h4 id="rspImportTitle">2. Import on this device without overwriting</h4>',
    '<label class="rsp-field">Encrypted .amrc8 file<input id="rspFile" class="input" type="file" accept=".amrc8,application/octet-stream"></label>',
    '<label class="rsp-field">Recovery passphrase<input id="rspImportPass" class="input" type="password" autocomplete="off" maxlength="128" spellcheck="false"></label>',
    '<button type="button" class="btn primary" id="rspInspect">Inspect and authenticate file</button>',
    '<div id="rspInspectSummary" class="rsp-result" aria-live="polite">No imported encrypted file has been verified.</div>',
    '<div id="rspFileList" class="rsp-list" aria-label="Files included in recovery"></div>',
    '<label class="rsp-check"><input type="checkbox" id="rspStageConsent"> Stage only into a new private quarantine folder; never replace originals or approve academic findings.</label>',
    '<button type="button" class="btn" id="rspStage" disabled>Stage verified file copies</button>',
    '<p class="rsp-hint">Inspection verifies authenticated encryption and each archive member. ',
    'Restoration to trusted documents is intentionally not automatic; review staged originals and their manifest first.</p>',
    '</section></div><p id="rspStatus" class="rsp-result" role="status" aria-live="polite">',
    'Choose an existing verified recovery snapshot to create a portable copy, or select an .amrc8 file to import.</p></section>'
  ].join('');
  const el=id=>host.querySelector('#'+id);
  const option=(label,value)=>{const o=document.createElement('option');o.value=value;o.textContent=label;return o;};
  let snapshots=[],exports=[],verified=null,busy=false,inspectSeq=0;
  const message=(text,error=false)=>{
    el('rspStatus').textContent=text;el('rspStatus').classList.toggle('rsp-error',error);
    if(error&&toast)toast(text,'bad');
  };
  const updateStage=()=>{
    el('rspStage').disabled=busy||!verified||!el('rspStageConsent').checked;
  };
  const invalidate=()=>{
    verified=null;inspectSeq++;el('rspStageConsent').checked=false;
    el('rspInspectSummary').textContent='Selection changed. Authenticate the selected encrypted file again.';
    el('rspFileList').replaceChildren();updateStage();
  };
  for(const id of ['rspFile','rspImportPass'])el(id).addEventListener('change',invalidate);
  el('rspStageConsent').onchange=updateStage;
  async function refresh(){
    const [local,encrypted]=await Promise.all([
      api('/api/research/studio/acceptance/list'),
      api('/api/research/studio/portable/list')
    ]);
    if(!host.isConnected)return;
    snapshots=(local.snapshots||[]).filter(x=>x.file_count>=3&&!x.warning);
    exports=encrypted.capsules||[];
    const sources=el('rspSource'),exportsSelect=el('rspExports');
    const oldSource=sources.value,oldExport=exportsSelect.value;
    sources.replaceChildren(option('Select verified local recovery',''));
    for(const x of snapshots)sources.append(option((x.created_at||'Saved')+' · '+x.file_count+' files',x.path));
    exportsSelect.replaceChildren(option('Select encrypted capsule',''));
    for(const x of exports)exportsSelect.append(option((x.created_at||'Saved')+' · '+x.file_count+' files',x.path));
    if([...sources.options].some(x=>x.value===oldSource))sources.value=oldSource;
    if([...exportsSelect.options].some(x=>x.value===oldExport))exportsSelect.value=oldExport;
  }
  function selectedBackup(){return snapshots.find(x=>x.path===el('rspSource').value);}
  function selectedExport(){return exports.find(x=>x.path===el('rspExports').value);}
  el('rspReload').onclick=async()=>{
    try{await refresh();message('Recovery files refreshed.');}
    catch(e){message('Cannot refresh recovery files: '+e.message,true);}
  };
  el('rspEncrypt').onclick=async()=>{
    const backup=selectedBackup(),pass=el('rspPassword').value,confirm=el('rspConfirm').value;
    if(!backup){message('Select a verified V7 recovery snapshot first.',true);return;}
    if(pass.length<16||pass!==confirm){message('Enter matching unique recovery passphrases of at least 16 characters.',true);return;}
    if(!el('rspConsent').checked){message('Confirm independent passphrase and off-device file storage first.',true);return;}
    if(!window.confirm('Create a new encrypted recovery file? Losing the passphrase will permanently prevent its recovery.'))return;
    busy=true;el('rspEncrypt').disabled=true;
    try{
      const created=await api('/api/research/studio/portable/create',{
        path:backup.path,sha256:backup.sha256,passphrase:pass,
        acknowledgement:'ENCRYPT PORTABLE BACKUP',confirm_user_will_store_separately:true
      });
      el('rspPassword').value='';el('rspConfirm').value='';el('rspConsent').checked=false;
      await refresh();
      el('rspExports').value=created.path;
      message('Encrypted recovery created. Download it and independently store it off this machine. Keep the passphrase safe.');
    }catch(e){message('Encryption blocked: '+e.message,true);}
    finally{busy=false;el('rspEncrypt').disabled=false;}
  };
  el('rspDownload').onclick=async()=>{
    const item=selectedExport();
    if(!item){message('Select an encrypted recovery file.',true);return;}
    try{
      await downloadCapsule(item.path,item.sha256);
      message('Encrypted download started. Confirm the file has actually been saved somewhere independent of this machine.');
    }catch(e){message('Encrypted download failed: '+e.message,true);}
  };
  el('rspInspect').onclick=async()=>{
    const file=el('rspFile').files?.[0],pass=el('rspImportPass').value,seq=++inspectSeq;
    verified=null;updateStage();el('rspFileList').replaceChildren();
    if(!file||!file.name.toLowerCase().endsWith('.amrc8')||file.size>41*1024*1024){
      message('Choose a supported encrypted .amrc8 file within the recovery size limit.',true);return;
    }
    if(pass.length<16){message('Enter the original recovery passphrase.',true);return;}
    busy=true;el('rspInspect').disabled=true;
    try{
      const data=new FormData();data.append('capsule',file,file.name);data.append('passphrase',pass);
      const result=await uploadCapsule('/api/research/studio/portable/inspect',data);
      if(!host.isConnected||seq!==inspectSeq)return;
      verified={file,sha256:result.capsule_sha256,passphrase:pass};
      el('rspInspectSummary').textContent='Authenticated '+result.file_count+
        ' recovery files. Capsule SHA-256 '+result.capsule_sha256+
        '. Source accuracy and publication are NOT automatically verified.';
      for(const item of result.file_roles||[]){
        const n=document.createElement('p');n.textContent=item.role+' · '+item.path+' · '+item.bytes+' bytes';el('rspFileList').append(n);
      }
      message('Encrypted archive and original source digests verified. A separate approval is required to stage them.');
    }catch(e){el('rspInspectSummary').textContent='Authentication failed. Nothing restored.';
      message('Import inspection refused: '+e.message,true);}
    finally{busy=false;el('rspInspect').disabled=false;updateStage();}
  };
  el('rspStage').onclick=async()=>{
    if(!verified||el('rspFile').files?.[0]!==verified.file||!el('rspStageConsent').checked){
      message('Inspect and approve this exact encrypted file first.',true);return;
    }
    if(!window.confirm('Stage verified files in a separate private folder only? No trusted documents will be replaced.'))return;
    busy=true;updateStage();
    try{
      const data=new FormData();
      data.append('capsule',verified.file,verified.file.name);
      data.append('passphrase',verified.passphrase);
      data.append('expected_sha256',verified.sha256);
      data.append('acknowledgement','STAGE ENCRYPTED BACKUP');
      data.append('confirm_no_overwrite','true');
      const result=await uploadCapsule('/api/research/studio/portable/stage',data);
      el('rspInspectSummary').textContent='Staged '+result.file_count+
        ' files in '+result.staging_path+'. No trusted files overwritten. Inspect the staging manifest manually.';
      message('Encrypted recovery safely staged in isolation. No academic verification or publication was performed.');
      el('rspImportPass').value='';el('rspFile').value='';verified=null;el('rspStageConsent').checked=false;
    }catch(e){message('Encrypted recovery staging blocked: '+e.message,true);}
    finally{busy=false;updateStage();}
  };
  refresh().catch(e=>message('Portable recovery unavailable: '+e.message,true));
}

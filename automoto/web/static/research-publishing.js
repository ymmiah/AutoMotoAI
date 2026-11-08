/* Research Studio V4 — citation-checked Word/PDF report authoring.
   Registry data, source paths, quotes and user text never become HTML. */
export function mountResearchPublishing({host,api,toast}){
  host.innerHTML=[
    '<section class="rp-shell" aria-labelledby="rpTitle">',
    '<header class="rp-hero"><div><span class="rp-eyebrow">RESEARCH STUDIO · V4 · ACADEMIC PUBLISHING</span>',
    '<h3 id="rpTitle">Academic references & research reports</h3>',
    '<p>Bind a reviewed research source to a saved DOI record, check each reference, and create an evidence-linked Word or PDF report.</p>',
    '</div><span class="rp-tag">Local build · source fingerprints</span></header>',
    '<p class="rp-disclosure" role="note"><strong>Registered is not verified research.</strong> You must confirm that each local file really belongs to the saved DOI publication.',
    ' Crossref metadata can be incomplete, outdated or formatted differently from your university requirements. Reports use the original reviewer classifications, not AI-generated scientific conclusions.</p>',
    '<section class="rp-panel" aria-labelledby="rpChooseTitle">',
    '<div class="rp-heading"><h4 id="rpChooseTitle">1. Select a reviewed comparison</h4><button type="button" class="btn" id="rpRefresh">Refresh reviews</button></div>',
    '<div class="rp-selectrow"><label class="rp-field">Saved comparison',
    '<select id="rpComparison" class="input"><option value="">Choose a historical review</option></select></label>',
    '<button type="button" class="btn primary" id="rpPrepare">Verify evidence and references</button></div>',
    '<div id="rpSourceStates" class="rp-source-states" aria-live="polite"></div>',
    '</section>',
    '<section class="rp-panel" id="rpEditor" hidden>',
    '<div class="rp-heading"><h4>2. Link each source to its actual DOI record</h4>',
    '<span id="rpCitationCount">No sources linked</span></div>',
    '<p class="rp-note">Every original research source must have its own matching saved V2 Crossref DOI record.',
    ' If the bibliography is missing, use V2 to verify and save the real DOI first.',
    ' Do not assign an unrelated paper just to enable export.</p>',
    '<div id="rpBindings" class="rp-bindings"></div>',
    '<div class="rp-divider"></div>',
    '<div class="rp-heading"><h4>3. Author the report</h4><span>British English · A4 · 1.5 spacing</span></div>',
    '<div class="rp-two">',
    '<label class="rp-field">Report title<input id="rpReportTitle" class="input" maxlength="140" placeholder="Enter the verified report title"></label>',
    '<label class="rp-field">Your name<input id="rpAuthor" class="input" maxlength="130" placeholder="Author name"></label>',
    '<label class="rp-field">Institution (optional)<input id="rpInstitution" class="input" maxlength="140" placeholder="University or organisation"></label>',
    '<label class="rp-field">Referencing format<select id="rpStyle" class="input">',
    '<option value="harvard">Harvard (institutional variants may differ)</option>',
    '<option value="ieee">IEEE (numbered in first-citation order)</option></select></label></div>',
    '<label class="rp-field">Research scope and introduction<textarea id="rpIntroduction" class="input" rows="3" maxlength="1600" placeholder="Describe scope and how you selected the evidence."></textarea></label>',
    '<label class="rp-field">Interpretation (author-supplied, optional)<textarea id="rpInterpretation" class="input" rows="3" maxlength="1400" placeholder="Discuss what the reviewed evidence may indicate without overstating it."></textarea></label>',
    '<label class="rp-field">Limitations and uncertainty<textarea id="rpLimitations" class="input" rows="3" maxlength="1300" placeholder="Explain missing data, source-quality limits and opposing evidence."></textarea></label>',
    '<label class="rp-field">Conclusion (author-supplied)<textarea id="rpConclusion" class="input" rows="3" maxlength="1500" placeholder="Only draw conclusions your evidence reasonably supports."></textarea></label>',
    '<div class="rp-actions"><button type="button" id="rpPreflight" class="btn primary">Run Word & citation preflight</button>',
    '<button type="button" id="rpSaveDraft" class="btn" disabled>Save editable report draft</button>',
    '<button type="button" id="rpExportWord" class="btn" disabled>Export Word</button>',
    '<button type="button" id="rpExportPdf" class="btn" disabled>Export PDF</button></div>',
    '<label class="rp-confirm"><input id="rpConfirm" type="checkbox">I have checked each source-to-DOI association,',
    ' the bibliographic details and my own interpretations. I understand that publication metadata does not verify scientific findings.</label>',
    '</section>',
    '<section class="rp-panel" aria-labelledby="rpPreviewTitle"><div class="rp-heading">',
    '<h4 id="rpPreviewTitle">Reference preflight and report preview</h4>',
    '<span id="rpReviewStatus">Not checked</span></div>',
    '<div id="rpSummary" class="rp-summary" aria-live="polite">Choose a reviewed comparison to begin.</div>',
    '<div id="rpReferences" class="rp-references"></div>',
    '<div id="rpWarnings" class="rp-warnings"></div>',
    '<details id="rpPreviewDetails" hidden><summary>Show full structured report text</summary>',
    '<pre id="rpMarkdown" class="rp-markdown"></pre></details>',
    '<div id="rpOutput" class="rp-output"></div>',
    '</section>',
    '<p id="rpStatus" role="status" aria-live="polite" class="rp-status">No report has been generated or sent anywhere.</p>',
    '</section>'
  ].join('');
  const el=id=>host.querySelector('#'+id);
  let prepared=null,validated=null,validatedBody=null,run=0;
  const text=(tag,value,cls='')=>{const n=document.createElement(tag);n.textContent=String(value??'');
    if(cls)n.className=cls;return n;};
  const say=(message,error=false)=>{el('rpStatus').textContent=message;
    el('rpStatus').classList.toggle('rp-error',error);
    if(error&&toast)toast(message,'bad');};
  const invalidate=()=>{
    validated=null;validatedBody=null;
    for(const id of ['rpSaveDraft','rpExportWord','rpExportPdf'])el(id).disabled=true;
    el('rpReviewStatus').textContent='Recheck required';
  };
  async function refreshReviews(){
    const data=await api('/api/research/studio/compare/list');
    if(!host.isConnected)return;
    const drop=el('rpComparison'),previous=drop.value;drop.replaceChildren();
    const empty=document.createElement('option');empty.value='';empty.textContent='Choose a historical review';
    drop.append(empty);
    for(const item of data.comparisons||[]){
      const option=document.createElement('option');option.value=item.path;
      option.textContent=item.claim+' · '+item.source_count+' source(s)';
      drop.append(option);
    }
    if([...drop.options].some(item=>item.value===previous))drop.value=previous;
  }
  function displayPrepared(data){
    prepared=data;invalidate();el('rpEditor').hidden=false;el('rpBindings').replaceChildren();
    el('rpSourceStates').replaceChildren();el('rpOutput').replaceChildren();
    el('rpReportTitle').value='Research evidence report';
    el('rpIntroduction').value='';el('rpInterpretation').value='';
    el('rpLimitations').value='';el('rpConclusion').value='';
    el('rpConfirm').checked=false;
    el('rpPreviewDetails').hidden=true;
    el('rpSummary').textContent='Reviewed claim: '+data.claim+
      '. Sources: '+data.sources.length+'. Review classifications complete: '+
      (data.review_complete?'yes':'no; export blocked')+'.';
    for(const status of data.source_status){
      el('rpSourceStates').append(text('p',status.path+' · '+status.status+
        ' · SHA-256 '+status.sha256.slice(0,14)+'…',
        status.status==='current'?'rp-current':'rp-stale'));
    }
    for(const source of data.sources){
      const card=document.createElement('div');card.className='rp-link-card';
      card.setAttribute('data-rp-source',source.path);
      card.append(text('strong',source.path),text('small','Pinned SHA-256 '+source.sha256));
      const label=document.createElement('label');label.className='rp-field';
      label.append(text('span','Matching publication (saved V2 Crossref record)'));
      const combo=document.createElement('select');combo.className='input';combo.setAttribute('data-rp-record',source.path);
      const empty=document.createElement('option');empty.value='';empty.textContent='Select the actual paper DOI';
      combo.append(empty);
      for(const paper of data.metadata_records||[]){
        const option=document.createElement('option');option.value=paper.path;
        option.textContent=(paper.title||'Untitled')+' · DOI '+(paper.doi||'unavailable')+
          ' · published '+(paper.publication_date||'date unavailable');
        combo.append(option);
      }
      combo.onchange=()=>{
        invalidate();const item=data.metadata_records.find(p=>p.path===combo.value);
        description.textContent=item?'Registry: '+item.path+' · authors: '+
          (item.authors||[]).join(', ')+' · saved SHA-256 '+item.sha256:
          'Choose the correct saved publication; unknown links must remain unassigned.';
      };
      label.append(combo);
      const description=text('p','Choose the actual saved publication; do not guess.','rp-note');
      const confirm=document.createElement('label');confirm.className='rp-confirm';
      const cb=document.createElement('input');cb.type='checkbox';cb.setAttribute('data-rp-match',source.path);
      cb.onchange=invalidate;
      confirm.append(cb,text('span','I checked the original file and confirm this is the matching publication.'));
      card.append(label,description,confirm);el('rpBindings').append(card);
    }
    el('rpCitationCount').textContent=data.metadata_records.length+' saved Crossref record(s) available';
    if(!data.metadata_records.length)say('No saved Crossref DOI records. Add verified paper metadata in V2 first.',true);
    else say('Comparison and source fingerprints verified. Associate each local document with its actual DOI record.');
  }
  function reportBody(){
    if(!prepared)throw Error('Verify a comparison first.');
    const bindings=prepared.sources.map(source=>{
      const card=[...el('rpBindings').querySelectorAll('[data-rp-source]')]
        .find(x=>x.getAttribute('data-rp-source')===source.path);
      const chosen=card?.querySelector('select[data-rp-record]');
      const confirmed=card?.querySelector('input[data-rp-match]');
      const record=prepared.metadata_records.find(x=>x.path===chosen?.value);
      if(!record||!confirmed?.checked)throw Error('Choose and confirm a genuine matching DOI for every source.');
      return {source_path:source.path,source_sha256:source.sha256,
        metadata_path:record.path,metadata_sha256:record.sha256,confirm_same_publication:true};
    });
    const get=id=>el(id).value.trim();
    return {
      comparison_path:prepared.comparison_path,
      comparison_sha256:prepared.comparison_sha256,
      title:get('rpReportTitle'),author:get('rpAuthor'),institution:get('rpInstitution'),
      introduction:get('rpIntroduction'),interpretation:get('rpInterpretation'),
      limitations:get('rpLimitations'),conclusion:get('rpConclusion'),
      style:get('rpStyle'),bindings,
    };
  }
  function displayPreflight(data){
    validated=data;
    el('rpReviewStatus').textContent=data.ready?'Word build passed · human review required':'Not export-ready';
    el('rpSummary').textContent='Word build: '+(data.word_build_valid?'valid':'failed')+
      ' · '+data.word_bytes+' bytes · '+data.reference_count+' DOI citations · '+
      data.citation_style.toUpperCase()+'. '+(data.ready?
      'Manual publication checks still required.':'Unreviewed excerpts prevent export.');
    const refs=el('rpReferences');refs.replaceChildren();
    refs.append(text('h5','Formatted references (verify against original papers)'));
    const list=document.createElement('ol');
    for(const reference of data.formatted_references||[]){
      const item=document.createElement('li');item.textContent=reference;list.append(item);
    }refs.append(list);
    const warnings=el('rpWarnings');warnings.replaceChildren();
    for(const warning of data.warnings||[])warnings.append(text('p',warning,'rp-warning'));
    el('rpMarkdown').textContent=data.report_markdown||'';
    el('rpPreviewDetails').hidden=false;
    if(data.ready){
      for(const id of ['rpSaveDraft','rpExportWord','rpExportPdf'])el(id).disabled=false;
    }
  }
  for(const id of ['rpReportTitle','rpAuthor','rpInstitution','rpIntroduction',
                    'rpInterpretation','rpLimitations','rpConclusion','rpStyle']){
    el(id).addEventListener('input',invalidate);
  }
  el('rpComparison').onchange=()=>{prepared=null;el('rpEditor').hidden=true;invalidate();};
  el('rpRefresh').onclick=async()=>{
    try{await refreshReviews();say('Historical research comparisons refreshed.');}
    catch(e){say('Cannot load comparison history: '+e.message,true);}
  };
  el('rpPrepare').onclick=async()=>{
    const path=el('rpComparison').value;if(!path){say('Select a saved V3 comparison first.',true);return;}
    const version=++run;
    try{
      say('Rechecking the original research project, all saved quotes and source fingerprints…');
      const data=await api('/api/research/studio/publish/prepare',{comparison_path:path});
      if(!host.isConnected||version!==run||el('rpComparison').value!==path)return;
      if(data.comparison_path!==path||data.no_network_requests!==true)
        throw Error('Unexpected report source identity.');
      displayPrepared(data);
    }catch(e){say('Comparison cannot be prepared: '+e.message,true);}
  };
  el('rpPreflight').onclick=async()=>{
    try{
      const body=reportBody(),serialized=JSON.stringify(body);
      say('Validating DOI associations, source quotations and a real local Word build…');
      const result=await api('/api/research/studio/publish/preflight',body);
      if(JSON.stringify(reportBody())!==serialized){
        say('Report changed during preflight; run the checks again.',true);return;
      }
      validatedBody=serialized;displayPreflight(result);
      say(result.ready?'Word and citation preflight passed. Review all references before export.':
        'Preflight completed, but formal export remains blocked until every excerpt is classified.',!result.ready);
    }catch(e){invalidate();say('Publication preflight failed: '+e.message,true);}
  };
  async function commit(mode,format){
    try{
      if(!validated?.ready||!validatedBody||validatedBody!==JSON.stringify(reportBody()))
        throw Error('Run a successful preflight on the current inputs first.');
      if(!el('rpConfirm').checked)
        throw Error('Confirm source-to-DOI matches, references and your interpretations.');
      const label=mode==='save-draft'?'editable Document Assistant draft':format.toUpperCase()+' report';
      if(!window.confirm('Create a NEW '+label+'? Original evidence, research and reviewer decisions will remain unchanged.'))return;
      const request={...reportBody(),acknowledgement:mode==='save-draft'?'SAVE DRAFT':'EXPORT REVIEW',
        confirm_checked_references:true};
      if(format)request.format=format;
      const result=await api('/api/research/studio/publish/'+mode,request);
      const out=el('rpOutput');out.replaceChildren();
      const status=text('strong','Created '+(result.format||'editable draft')+
        ': '+result.path,'rp-result');out.append(status);
      const download=document.createElement('a');download.className='btn';
      download.href='/api/files/download?path='+encodeURIComponent(result.path);
      download.setAttribute('download','');
      download.textContent='Download '+(result.format||'report source');
      out.append(download);
      el('rpConfirm').checked=false;
      say('New research report created. Re-check publication references and the finished page layout.');
    }catch(e){say('Report creation blocked: '+e.message,true);}
  }
  el('rpSaveDraft').onclick=()=>commit('save-draft',null);
  el('rpExportWord').onclick=()=>commit('export','docx');
  el('rpExportPdf').onclick=()=>commit('export','pdf');
  refreshReviews().catch(e=>say('Saved review catalogue unavailable: '+e.message,true));
}

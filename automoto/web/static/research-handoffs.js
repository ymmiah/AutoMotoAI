/* Research Studio V6: source-pinned, reviewed cross-studio hand-offs.
   Untrusted research text is displayed only through textContent. */
export function mountResearchHandoffs({host,api,toast}){
  host.innerHTML=[
    '<section class="rsh-shell" aria-labelledby="rshTitle">',
    '<header class="rsh-hero"><div><span class="rsh-kicker">RESEARCH STUDIO · V6 · CONTROLLED HAND-OFFS</span>',
    '<h3 id="rshTitle">Carry evidence into your next workspace</h3>',
    '<p>Create a separate, traceable research brief for Document Assistant, an editable evidence design for Visual Studio, or a developer-review brief. Nothing runs or publishes automatically.</p></div>',
    '<span class="rsh-tag">Source checks · Human approval</span></header>',
    '<p class="rsh-disclosure"><strong>Approval is for transfer, not scientific truth.</strong>',
    ' Every quotation and retained AI observation is unverified source material. ',
    'Rejected AI proposals are excluded; all original files remain unchanged. ',
    'This V6 workflow is local-only, with no AI invocation, browsing or connector action.</p>',
    '<section class="rsh-panel" aria-labelledby="rshSetupTitle"><h4 id="rshSetupTitle">1. Select research and destination</h4>',
    '<div class="rsh-fields">',
    '<label>Completed V3 evidence comparison<select id="rshComparison" class="input"><option value="">Choose verified comparison</option></select></label>',
    '<label>Optional V5 human review<select id="rshReview" class="input"><option value="">Use human-labelled V3 evidence only</option></select></label>',
    '<label>Target workspace<select id="rshTarget" class="input">',
    '<option value="document">Document Assistant — editable evidence draft</option>',
    '<option value="visual">Visual Studio — editable source-linked cards</option>',
    '<option value="developer">Developer review — non-executable source brief</option>',
    '</select></label></div>',
    '<div class="rsh-controls"><button type="button" class="btn" id="rshRefresh">Refresh evidence</button>',
    '<button type="button" class="btn primary" id="rshPreview">Verify and preview hand-off</button></div>',
    '<p class="rsh-note">Developer review creates a private Markdown brief for Files and later manual code review; it does not claim a dedicated Developer Studio interface is already implemented.</p>',
    '</section>',
    '<section class="rsh-panel" aria-labelledby="rshPreviewTitle"><div class="rsh-heading">',
    '<h4 id="rshPreviewTitle">2. Inspect the evidence packet</h4>',
    '<span id="rshPreviewSummary">No validated packet yet</span></div>',
    '<pre id="rshEvidence" class="rsh-preview" tabindex="0">Choose an existing reviewed comparison and preview its source-linked hand-off.</pre>',
    '<label class="rsh-consent"><input type="checkbox" id="rshConsent">',
    ' I checked the quoted source context, understand any AI observations remain tentative, and authorise a new private review-only hand-off. This is not approval to publish, execute code or modify existing projects.</label>',
    '<button type="button" class="btn primary" id="rshSave" disabled>Create audited hand-off</button></section>',
    '<section class="rsh-panel" aria-labelledby="rshHistoryTitle"><div class="rsh-heading">',
    '<h4 id="rshHistoryTitle">Historical hand-offs</h4><button type="button" class="btn" id="rshReload">Refresh audit</button></div>',
    '<label class="rsh-full">Saved transfers<select id="rshHistory" class="input"><option value="">Choose saved audit</option></select></label>',
    '<button type="button" class="btn" id="rshOpen">Check destination and evidence status</button>',
    '<div id="rshDetails" class="rsh-note">Each transfer has an independent SHA-256 audit manifest. The hash detects later changes against the recorded value, but is not an external digital signature.</div>',
    '</section>',
    '<p role="status" aria-live="polite" id="rshStatus" class="rsh-status">No transfer is authorised until you inspect a preview and confirm.</p>',
    '</section>'
  ].join('');
  const el=id=>host.querySelector('#'+id);
  let catalog={comparisons:[],human_reviews:[]},preview=null,sequence=0,busy=false;
  function status(message,error=false){
    el('rshStatus').textContent=message;el('rshStatus').classList.toggle('rsh-error',error);
    if(error&&toast)toast(message,'bad');
  }
  function invalidate(){
    preview=null;sequence++;el('rshSave').disabled=true;el('rshConsent').checked=false;
    el('rshPreviewSummary').textContent='No validated packet yet';
    el('rshEvidence').textContent='Selection changed. Verify the evidence again.';
  }
  function option(text,value){
    const entry=document.createElement('option');entry.value=value;entry.textContent=text;return entry;
  }
  function choice(){
    const comparison=catalog.comparisons.find(x=>x.path===el('rshComparison').value);
    if(!comparison)return null;
    const chosen=el('rshReview').value;
    const review=catalog.human_reviews.find(x=>x.path===chosen);
    if(chosen&&(!review||review.comparison_path!==comparison.path))return null;
    return {
      comparison_path:comparison.path,comparison_sha256:comparison.sha256,
      target:el('rshTarget').value,
      ...(review?{review_path:review.path,review_sha256:review.sha256}:{})
    };
  }
  function filterReviews(){
    const select=el('rshReview'),before=select.value,comparison=el('rshComparison').value;
    select.replaceChildren(option('Use human-labelled V3 evidence only',''));
    for(const review of catalog.human_reviews.filter(x=>x.comparison_path===comparison)){
      select.append(option('Human-reviewed AI draft · '+review.count+' decisions · '+review.path.split('/').pop(),review.path));
    }
    if([...select.options].some(x=>x.value===before))select.value=before;
  }
  async function refresh(){
    const data=await api('/api/research/studio/handoff/sources');
    if(!host.isConnected)return;
    catalog={comparisons:data.comparisons||[],human_reviews:data.human_reviews||[]};
    const select=el('rshComparison'),prior=select.value;
    select.replaceChildren(option('Choose verified comparison',''));
    for(const comparison of catalog.comparisons){
      select.append(option(comparison.claim+' · '+comparison.path.split('/').pop(),comparison.path));
    }
    if([...select.options].some(x=>x.value===prior))select.value=prior;
    filterReviews();invalidate();
    status('Loaded '+catalog.comparisons.length+' fully human-labelled comparisons and '+catalog.human_reviews.length+' human AI reviews.');
  }
  async function history(preferred){
    const data=await api('/api/research/studio/handoff/list');
    if(!host.isConnected)return;
    const select=el('rshHistory'),prior=preferred||select.value;
    select.replaceChildren(option('Choose saved audit',''));
    for(const item of data.handoffs||[]){
      select.append(option(item.target.toUpperCase()+' · '+item.research_question+' · '+item.created_at,item.path));
    }
    if([...select.options].some(x=>x.value===prior))select.value=prior;
  }
  function readable(result,target){
    if(target==='developer')return result.preview;
    try{
      const file=JSON.parse(result.preview);
      if(target==='document')return file.markdown;
      return [
        'Editable Visual Studio evidence design',
        'Title: '+file.spec.title,
        'Subtitle: '+file.spec.subtitle,
        '',
        ...(file.spec.cards||[]).map(x=>x.title+'\n'+x.text+'\n'),
        'The complete quotations, offsets, fingerprints and review records are in the saved hand-off audit.',
      ].join('\n');
    }catch(_error){
      return result.preview;
    }
  }
  for(const id of ['rshComparison','rshReview','rshTarget']){
    el(id).onchange=()=>{if(id==='rshComparison')filterReviews();invalidate();};
  }
  el('rshConsent').onchange=()=>{el('rshSave').disabled=!el('rshConsent').checked||!preview||busy;};
  el('rshRefresh').onclick=async()=>{try{await refresh();}catch(e){status('Could not refresh saved research: '+e.message,true);}};
  el('rshPreview').onclick=async()=>{
    const selected=choice();if(!selected){status('Select a completed human-reviewed V3 comparison.',true);return;}
    const serial=++sequence;preview=null;el('rshSave').disabled=true;el('rshConsent').checked=false;
    busy=true;el('rshPreview').disabled=true;
    try{
      status('Revalidating original quotations, current source fingerprints and decisions…');
      const result=await api('/api/research/studio/handoff/preview',selected);
      if(!host.isConnected||serial!==sequence)return;
      preview={selected,signature:JSON.stringify(selected)};
      el('rshEvidence').textContent=readable(result,selected.target);
      el('rshPreviewSummary').textContent=result.evidence_count+' source excerpts · '+result.retained_unverified_count+' retained unverified AI observations';
      status('Preview is ready. Check each original source before authorising a new draft.');
    }catch(e){status('The hand-off was blocked: '+e.message,true);}
    finally{busy=false;el('rshPreview').disabled=false;}
  };
  el('rshSave').onclick=async()=>{
    if(!preview||!el('rshConsent').checked||JSON.stringify(choice())!==preview.signature){
      status('Preview this exact selection and confirm source checks before saving.',true);return;
    }
    if(!window.confirm('Create a separate private draft and SHA-256 audit? The output is review-only; no code will run or report be published.'))return;
    busy=true;el('rshSave').disabled=true;
    try{
      const saved=await api('/api/research/studio/handoff/save',{
        ...preview.selected,acknowledgement:'CREATE REVIEW-ONLY HANDOFF',
        confirm_sources_checked:true,confirm_no_publication:true
      });
      el('rshDetails').textContent='Created '+saved.target+' draft: '+saved.target_path+
        ' · SHA-256 '+saved.target_sha256+' · independent audit '+saved.path+
        '. Open it from Files / the destination workspace. Independent review remains required.';
      await history(saved.path);invalidate();
      status('Audited hand-off created. Originals unchanged, no model call or automatic publication.');
    }catch(e){status('Could not create the reviewed hand-off: '+e.message,true);}
    finally{busy=false;}
  };
  el('rshReload').onclick=async()=>{try{await history();status('Audit archive refreshed.');}
    catch(e){status('Audit archive unavailable: '+e.message,true);}};
  el('rshOpen').onclick=async()=>{
    const path=el('rshHistory').value;
    if(!path){status('Choose a saved hand-off first.',true);return;}
    try{
      const item=await api('/api/research/studio/handoff/open?path='+encodeURIComponent(path));
      el('rshDetails').textContent='Destination: '+item.target_path+' ('+item.target_status+
        '). Original source evidence: '+item.source_status+
        '. '+item.evidence.length+' archived quotations, '+item.retained_unverified_observations.length+
        ' human-retained AI observations. Not publication-ready or externally signed.';
      status('Historical transfer inspected. Reverify the original material before relying on it.');
    }catch(e){status('Cannot inspect this audit: '+e.message,true);}
  };
  Promise.all([refresh(),history()]).catch(e=>status('V6 workspace unavailable: '+e.message,true));
}

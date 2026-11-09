/* Research Studio V5 — explicitly opt-in local AI; model content is untrusted.
   Source excerpts and suggestions are DOM text only. No automatic publishing. */
export function mountResearchAI({host,api,toast}){
  host.innerHTML=[
    '<section class="rai-shell" aria-labelledby="raiTitle">',
    '<header class="rai-hero"><div><span class="rai-kicker">RESEARCH STUDIO · V5 · LOCAL OLLAMA</span>',
    '<h3 id="raiTitle">Offline AI research analysis</h3>',
    '<p>Use a reviewed source comparison to request bounded, source-linked suggestions from an installed model on this computer.</p></div>',
    '<span class="rai-tag">Local model · Explicit consent</span></header>',
    '<p class="rai-disclosure"><strong>Generated suggestions are not verified research.</strong>',
    ' Source material is untrusted and can contain malicious instructions.',
    ' Evidence links, numerical checks and human review reduce risk but cannot prove semantic correctness.',
    ' No model output is automatically copied into Word/PDF reports, accepted as a V3 decision or published.</p>',
    '<section class="rai-panel"><div class="rai-heading"><h4>1. Select verified human evidence</h4>',
    '<button id="raiRefresh" type="button" class="btn">Refresh reviews</button></div>',
    '<div class="rai-row"><label class="rai-field">Reviewed V3 comparison',
    '<select id="raiComparison" class="input"><option value="">Select a saved review</option></select></label>',
    '<button id="raiPrepare" type="button" class="btn primary">Verify source context</button></div>',
    '<div id="raiContext" class="rai-info" aria-live="polite">Choose a comparison with all evidence manually classified.</div>',
    '<label class="rai-consent"><input type="checkbox" id="raiConsent">',
    ' I authorise one inference using my selected installed Ollama model on loopback. The quotes may be included in the local prompt and results remain unverified.</label>',
    '<button id="raiGenerate" type="button" class="btn" disabled>Generate grounded suggestions locally</button>',
    '</section>',
    '<section class="rai-panel" aria-labelledby="raiReviewTitle"><div class="rai-heading">',
    '<h4 id="raiReviewTitle">2. Examine and review local suggestions</h4>',
    '<span id="raiReviewState">No suggestions generated</span></div>',
    '<div id="raiDraftInfo" class="rai-info">AI output is a separate, unapproved private draft.</div>',
    '<div id="raiPoints" class="rai-points"></div>',
    '<label class="rai-consent"><input type="checkbox" id="raiHumanConfirm">',
    ' I personally inspected each suggestion and its cited original evidence. My decisions do not certify academic truth.</label>',
    '<button id="raiSaveReview" class="btn" type="button" disabled>Save my independent review decisions</button>',
    '</section>',
    '<section class="rai-panel"><div class="rai-heading"><h4>Historical local proposals</h4>',
    '<button id="raiReloadDrafts" class="btn" type="button">Refresh proposals</button></div>',
    '<div class="rai-row"><label class="rai-field">Previous unverified suggestions',
    '<select id="raiDrafts" class="input"><option value="">Choose saved proposal</option></select></label>',
    '<button id="raiOpen" class="btn" type="button">Open historical proposal</button></div>',
    '<p class="rai-hint">Opening an older proposal does not mean its source files remain unchanged.</p></section>',
    '<p id="raiStatus" class="rai-status" role="status" aria-live="polite">',
    'Offline research synthesis requires an explicitly enabled installed Ollama model.</p>',
    '</section>'
  ].join('');
  const el=id=>host.querySelector('#'+id);
  const element=(tag,value,cls)=>{
    const item=document.createElement(tag);item.textContent=String(value??'');
    if(cls)item.className=cls;return item;
  };
  let context=null,draft=null,requestId=0;
  function status(value,error=false){
    el('raiStatus').textContent=value;el('raiStatus').classList.toggle('rai-error',error);
    if(error&&toast)toast(value,'bad');
  }
  function clear(){
    context=null;draft=null;el('raiGenerate').disabled=true;el('raiSaveReview').disabled=true;
    el('raiPoints').replaceChildren();el('raiConsent').checked=false;
    el('raiHumanConfirm').checked=false;el('raiReviewState').textContent='No suggestions generated';
    el('raiDraftInfo').textContent='AI output is a separate, unapproved private draft.';
  }
  async function refreshReviews(){
    const result=await api('/api/research/studio/compare/list');
    if(!host.isConnected)return;
    const list=el('raiComparison'),current=list.value;
    list.replaceChildren();
    const empty=document.createElement('option');empty.value='';empty.textContent='Select a saved review';
    list.append(empty);
    for(const review of result.comparisons||[]){
      const option=document.createElement('option');option.value=review.path;
      option.textContent=review.claim+' · '+review.source_count+' sources';
      list.append(option);
    }
    if([...list.options].some(x=>x.value===current))list.value=current;
  }
  async function refreshDrafts(preferred){
    const result=await api('/api/research/studio/ai/list');
    if(!host.isConnected)return;
    const list=el('raiDrafts'),current=preferred||list.value;
    list.replaceChildren();
    const empty=document.createElement('option');empty.value='';empty.textContent='Choose saved proposal';
    list.append(empty);
    for(const item of result.drafts||[]){
      const option=document.createElement('option');option.value=item.path;
      option.textContent=item.claim+' · '+item.point_count+' points';
      list.append(option);
    }
    if([...list.options].some(x=>x.value===current))list.value=current;
  }
  function display(result,{historical=false}={}){
    draft={path:result.path,sha256:result.sha256,points:result.points,evidence:result.evidence,
           comparison_status:result.comparison_status||'current'};
    el('raiPoints').replaceChildren();el('raiHumanConfirm').checked=false;
    el('raiSaveReview').disabled=historical&&result.comparison_status!=='current';
    el('raiReviewState').textContent=historical?'Historical proposal':'Human review required';
    el('raiDraftInfo').textContent='Private proposal '+result.path+
      ' · '+result.points.length+' claim(s) · '+(historical?'Historical, sources: '+result.comparison_status:'Fresh local response')+
      '. Claims have NOT been certified or published.';
    const sources=Object.fromEntries((result.evidence||[]).map(x=>[x.id,x]));
    for(const point of result.points){
      const card=document.createElement('article');card.className='rai-point';
      const head=document.createElement('div');head.className='rai-heading';
      head.append(element('strong',point.id),element('span','Unverified model suggestion'));
      card.append(head,element('p',point.claim,'rai-claim'));
      card.append(element('p','Uncertainty: '+point.uncertainty,'rai-hint'));
      for(const id of point.evidence_ids){
        const src=sources[id];if(!src)continue;
        const quote=document.createElement('blockquote');quote.textContent=src.quote;
        card.append(element('small',id+' · '+src.source+
          ' · SHA-256 '+src.sha256+' · offset '+src.offset+
          (src.page?' · PDF page '+src.page:' (page not verified)')),quote);
      }
      const decision=document.createElement('select');decision.className='input';
      decision.setAttribute('data-rai-decision',point.id);
      for(const [value,label] of [['','Choose reviewer decision'],['retain_for_review','Retain for further research'],['reject','Reject suggestion']]){
        const opt=document.createElement('option');opt.value=value;opt.textContent=label;
        decision.append(opt);
      }
      const note=document.createElement('textarea');note.className='input';note.rows=2;
      note.maxLength=500;note.placeholder='Explain your independent judgement (12–500 characters)';
      note.setAttribute('data-rai-note',point.id);
      const label=document.createElement('label');label.className='rai-field';
      label.append(element('span','Your decision'),decision);card.append(label);
      const notes=document.createElement('label');notes.className='rai-field';
      notes.append(element('span','Your review rationale'),note);card.append(notes);
      el('raiPoints').append(card);
    }
  }
  el('raiComparison').onchange=clear;
  el('raiRefresh').onclick=async()=>{try{await refreshReviews();status('Research reviews refreshed.');}
    catch(e){status('Review catalogue unavailable: '+e.message,true);}};
  el('raiPrepare').onclick=async()=>{
    const path=el('raiComparison').value;
    if(!path){status('Select a saved V3 comparison first.',true);return;}
    const seq=++requestId;clear();
    try{
      status('Rechecking the human-reviewed comparison and all source hashes…');
      const publication=await api('/api/research/studio/publish/prepare',{comparison_path:path});
      const data=await api('/api/research/studio/ai/prepare',{
        comparison_path:path,comparison_sha256:publication.comparison_sha256});
      if(!host.isConnected||seq!==requestId||el('raiComparison').value!==path)return;
      context={path,sha256:publication.comparison_sha256};
      el('raiContext').textContent=data.evidence.length+' exact source quotations · '+
        data.source_count+' current sources · human classifications complete. Claim: '+data.claim;
      el('raiGenerate').disabled=false;
      status('Evidence is verified. Local inference requires explicit consent.');
    }catch(e){status('Cannot prepare local analysis: '+e.message,true);}
  };
  el('raiGenerate').onclick=async()=>{
    if(!context){status('Prepare a source-verified comparison first.',true);return;}
    if(!el('raiConsent').checked){status('Explicitly consent to local model inference before generating.',true);return;}
    if(!window.confirm('Send the selected evidence excerpts to your installed local Ollama model? This does not use a cloud provider or update research files.'))return;
    el('raiGenerate').disabled=true;
    const identity=context;
    try{
      status('Running one bounded local Ollama analysis; no remote provider or fallback…');
      const result=await api('/api/research/studio/ai/generate',{
        comparison_path:identity.path,comparison_sha256:identity.sha256,
        acknowledgement:'ANALYSE LOCALLY',confirm_local_model:true});
      if(!host.isConnected||context!==identity)return;
      display(result);await refreshDrafts(result.path);
      status('Local suggestions created. Review every cited passage before retaining any observation.');
    }catch(e){status('Local inference rejected: '+e.message,true);}
    finally{el('raiGenerate').disabled=false;}
  };
  el('raiSaveReview').onclick=async()=>{
    if(!draft){status('Generate or open a saved proposal first.',true);return;}
    if(!el('raiHumanConfirm').checked){status('Confirm your individual review of each claim and source.',true);return;}
    const decisions=[];
    for(const point of draft.points){
      const decision=el('raiPoints').querySelector('[data-rai-decision="'+point.id+'"]')?.value;
      const note=el('raiPoints').querySelector('[data-rai-note="'+point.id+'"]')?.value.trim();
      if(!decision||!note||note.length<12){
        status('Assign a decision and at least twelve characters of explanation to every claim.',true);
        return;
      }
      decisions.push({point_id:point.id,decision,note});
    }
    if(!window.confirm('Save your human review as a separate private snapshot? This will not publish or update any existing research report.'))return;
    try{
      const result=await api('/api/research/studio/ai/save-review',{
        draft_path:draft.path,draft_sha256:draft.sha256,decisions,
        acknowledgement:'SAVE HUMAN REVIEW',confirm_unverified:true});
      status('Saved '+result.reviewed+' human review decision(s). Research files and academic reports remain unchanged.');
      el('raiHumanConfirm').checked=false;
    }catch(e){status('Could not save independent review: '+e.message,true);}
  };
  el('raiReloadDrafts').onclick=async()=>{try{await refreshDrafts();status('Private proposals refreshed.');}
    catch(e){status('Could not load proposal archive: '+e.message,true);}};
  el('raiOpen').onclick=async()=>{
    const path=el('raiDrafts').value;
    if(!path){status('Select a previous unverified proposal.',true);return;}
    try{
      const data=await api('/api/research/studio/ai/open?path='+encodeURIComponent(path));
      display(data,{historical:true});
      status('Historical proposal opened read-only. Recheck source material and review all claims.');
    }catch(e){status('Cannot open proposal: '+e.message,true);}
  };
  Promise.all([refreshReviews(),refreshDrafts()]).catch(e=>status('Local research AI workspace unavailable: '+e.message,true));
}

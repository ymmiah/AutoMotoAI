/* AutoMoto Research Studio V3: human-labelled comparisons. Untrusted text is
   inserted only via textContent; no AI stance inference or source mutation. */
export function mountResearchComparison({host,api,toast}){
  host.innerHTML=[
    '<section class="rc-shell" aria-labelledby="rcTitle">',
    '<header class="rc-hero"><div><span class="rc-kicker">RESEARCH STUDIO · V3 · OFFLINE</span>',
    '<h3 id="rcTitle">Compare evidence across sources</h3>',
    '<p>Select a saved V1 research project with at least two documents. Verify exact quotations, then assign your own supporting, contradicting, uncertain or unreviewed labels.</p></div>',
    '<span class="rc-tag">Human assessment, not automated fact checking</span></header>',
    '<p class="rc-disclosure" role="note"><strong>Evidence identity is not scientific validity.</strong>',
    ' Quotations are checked against extracted text and SHA-256 fingerprints. Positions, methodology ratings and conclusions are reviewer-assigned, not AI-generated. Source IDs are not formal academic citations.</p>',
    '<section class="rc-panel"><div class="rc-heading"><h4>Choose evidence project</h4>',
    '<button type="button" class="btn" id="rcRefreshProjects">Refresh projects</button></div>',
    '<div class="rc-inline"><label class="rc-field">Saved research project<select id="rcProject" class="input"><option value="">Choose a project with two sources</option></select></label>',
    '<button type="button" class="btn primary" id="rcPrepare">Verify quotations</button></div>',
    '<p class="rc-hint">Changed sources require a new V1 research snapshot. Old projects are never overwritten.</p>',
    '<div id="rcSourceStates" class="rc-states" aria-live="polite"></div></section>',
    '<section class="rc-panel" id="rcEditor" hidden>',
    '<div class="rc-heading"><h4>Claim, evidence and methodology</h4><span id="rcProgress">Not assessed</span></div>',
    '<label class="rc-field">Claim for human evaluation<textarea id="rcClaim" class="input" rows="2" maxlength="320"></textarea></label>',
    '<p class="rc-hint">These passages were retrieved for the saved project question. If you change the claim materially, start a fresh V1 search.</p>',
    '<div id="rcSourceCards" class="rc-sources"></div>',
    '<div class="rc-actions"><button type="button" class="btn primary" id="rcPreview">Preview assessment</button>',
    '<button type="button" class="btn" id="rcSave">Save new review snapshot</button></div>',
    '<label class="rc-confirm"><input type="checkbox" id="rcConfirm">',
    'I confirm the stances, quality ratings and methodology assessments are my own unverified judgements.</label>',
    '</section>',
    '<section class="rc-panel" aria-labelledby="rcMatrixTitle"><div class="rc-heading">',
    '<h4 id="rcMatrixTitle">Cross-source comparison matrix</h4><span id="rcResultState">Not assessed</span></div>',
    '<div id="rcSummary" class="rc-summary" aria-live="polite">Select a source-pinned project to begin.</div>',
    '<div id="rcMatrix" class="rc-matrix"></div><div id="rcWarnings" class="rc-warnings"></div></section>',
    '<section class="rc-panel"><div class="rc-heading"><h4>Saved review history</h4>',
    '<button type="button" class="btn" id="rcRefreshReviews">Refresh reviews</button></div>',
    '<div class="rc-inline"><label class="rc-field">Historical comparisons<select id="rcReviews" class="input"><option value="">Choose a saved review</option></select></label>',
    '<button type="button" class="btn" id="rcOpen">Open historical review</button></div>',
    '<p class="rc-hint">Reviews are immutable, private and human-authored. Reopen checks for changed or missing source files without changing the historical judgement.</p></section>',
    '<p id="rcStatus" role="status" aria-live="polite" class="rc-status">No external requests or source modifications.</p>',
    '</section>'
  ].join('');
  const el=id=>host.querySelector('#'+id);
  const node=(tag,value,cls)=>{const n=document.createElement(tag);n.textContent=String(value??'');
    if(cls)n.className=cls;return n;};
  const select=(items,chosen)=>{const n=document.createElement('select');n.className='input';
    for(const [value,label] of items){const o=document.createElement('option');o.value=value;o.textContent=label;n.append(o);}
    n.value=chosen;return n;};
  const STANCES=[['unreviewed','Not reviewed'],['supports','Supports (your judgement)'],
    ['contradicts','Contradicts (your judgement)'],['uncertain','Mixed or uncertain']];
  const METHODS=[['not_assessed','Not assessed'],['experimental','Experimental (reviewer)'],
    ['observational','Observational (reviewer)'],['review','Review (reviewer)'],['other','Other']];
  const QUALITY=[['not_assessed','Not assessed'],['low','Low (subjective)'],
    ['moderate','Moderate (subjective)'],['high','High (subjective)']];
  let prepared=null,sequence=0;
  const say=(s,error=false)=>{el('rcStatus').textContent=s;
    el('rcStatus').classList.toggle('rc-error',error);
    if(error&&toast)toast(s,'bad');};
  const invalidate=()=>{el('rcResultState').textContent='Changes not yet verified';};
  function field(title,input){
    const label=document.createElement('label');label.className='rc-field';
    label.append(node('span',title),input);input.oninput=invalidate;return label;
  }
  async function projects(){
    const result=await api('/api/research/studio/list');
    if(!host.isConnected)return;
    const combo=el('rcProject'),prior=combo.value;
    combo.replaceChildren();combo.append(select([['','Choose a project with two sources']],'').firstChild);
    for(const entry of result.projects||[]){
      if(entry.source_count<2)continue;
      const option=document.createElement('option');option.value=entry.path;
      option.textContent=entry.title+' · '+entry.source_count+' sources · '+entry.evidence_count+' excerpts';
      combo.append(option);
    }
    if([...combo.options].some(o=>o.value===prior))combo.value=prior;
  }
  async function comparisons(preferred){
    const result=await api('/api/research/studio/compare/list');
    if(!host.isConnected)return;
    const combo=el('rcReviews'),prior=preferred||combo.value;
    combo.replaceChildren();const blank=document.createElement('option');
    blank.value='';blank.textContent='Choose a saved review';combo.append(blank);
    for(const item of result.comparisons||[]){
      const option=document.createElement('option');option.value=item.path;
      option.textContent=item.claim+' · '+item.source_count+' sources';combo.append(option);
    }
    if([...combo.options].some(o=>o.value===prior))combo.value=prior;
  }
  function countReviewed(){
    const all=[...el('rcSourceCards').querySelectorAll('[data-rc-stance]')];
    const assessed=all.filter(e=>e.value!=='unreviewed').length;
    el('rcProgress').textContent=assessed+'/'+all.length+' excerpts classified';
    invalidate();
  }
  function prepareUI(data){
    prepared=data;el('rcEditor').hidden=false;el('rcClaim').value=data.project.question;
    el('rcConfirm').checked=false;el('rcSourceStates').replaceChildren();
    el('rcResultState').textContent='Human review required';
    el('rcSummary').textContent=data.evidence_count+' exact source-linked excerpts from '+
      data.source_count+' SHA-256-pinned documents; no reviewer positions assigned.';
    el('rcMatrix').replaceChildren();el('rcWarnings').replaceChildren();
    for(const state of data.source_status){
      el('rcSourceStates').append(node('p',state.path+' — '+state.status+
        ' — SHA-256 '+state.sha256.slice(0,16)+'…',
        state.status==='current'?'rc-current':'rc-stale'));
    }
    const holder=el('rcSourceCards');holder.replaceChildren();
    for(const src of data.project.sources){
      const source=document.createElement('section');source.className='rc-source';
      source.append(node('h5',src.path));
      const quality=document.createElement('div');quality.className='rc-quality';
      const method=select(METHODS,'not_assessed');method.setAttribute('data-rc-method',src.path);
      const rating=select(QUALITY,'not_assessed');rating.setAttribute('data-rc-quality',src.path);
      const limits=document.createElement('textarea');limits.className='input';limits.rows=2;
      limits.maxLength=650;limits.placeholder='Sample size, selection bias, missing data, limitations';
      limits.setAttribute('data-rc-limits',src.path);
      quality.append(field('Methodology',method),field('Source quality (subjective)',rating),
        field('Methodology / coverage limitations',limits));
      source.append(quality);
      const excerpts=data.evidence.filter(x=>x.source===src.path);
      if(!excerpts.length)
        source.append(node('p','No matching excerpt. This is a coverage gap, not evidence against the claim.','rc-gap'));
      for(const e of excerpts){
        const article=document.createElement('article');article.className='rc-passage';
        article.setAttribute('data-rc-evidence',e.id);
        const heading=document.createElement('div');heading.className='rc-passage-heading';
        heading.append(node('strong',e.id),
          node('span',e.page?'PDF page '+e.page+' · offset '+e.offset:
            e.section+' · offset '+e.offset+' (no verified page)'));
        const stance=select(STANCES,'unreviewed');stance.setAttribute('data-rc-stance',e.id);
        const reason=document.createElement('textarea');reason.className='input';
        reason.rows=2;reason.maxLength=500;reason.placeholder='Your rationale (minimum 8 characters when classified)';
        reason.setAttribute('data-rc-rationale',e.id);
        stance.onchange=countReviewed;reason.oninput=invalidate;
        article.append(heading,node('blockquote',e.quote),field('Classification',stance),
          field('Your rationale',reason),node('small','Source SHA-256 '+e.sha256));
        source.append(article);
      }
      holder.append(source);
    }
    countReviewed();
    say('Every saved quotation was rechecked at its original extracted source offset. Human classification is ready.');
  }
  function payload(){
    if(!prepared)throw Error('Verify a saved two-source research project first.');
    const cards=el('rcSourceCards');
    const claim=el('rcClaim').value.trim();
    if(claim.length<8)throw Error('Enter a claim of at least eight characters.');
    const sources=prepared.project.sources;
    const source_reviews=sources.map(item=>{
      const find=(attribute)=>[...cards.querySelectorAll('['+attribute+']')]
        .find(x=>x.getAttribute(attribute)===item.path);
      return {source_path:item.path,methodology:find('data-rc-method').value,
        quality:find('data-rc-quality').value,limitations:find('data-rc-limits').value.trim()};
    });
    const annotations=prepared.evidence.map(item=>({
      evidence_id:item.id,
      stance:cards.querySelector('[data-rc-stance="'+item.id+'"]').value,
      rationale:cards.querySelector('[data-rc-rationale="'+item.id+'"]').value.trim(),
    }));
    return {project_path:prepared.project_path,project_sha256:prepared.project_sha256,
      claim,annotations,source_reviews};
  }
  function reportUI(report,history){
    const counts=report.counts||{};
    el('rcResultState').textContent=history?'Read-only historical review':'Server-validated review';
    el('rcSummary').textContent='Supports '+(counts.supports||0)+
      ' · Contradicts '+(counts.contradicts||0)+' · Uncertain '+(counts.uncertain||0)+
      ' · Unreviewed '+(counts.unreviewed||0)+' · '+
      (report.disagreement_flag?'Reviewer-labelled disagreement across distinct sources':'No cross-source disagreement established');
    const matrix=el('rcMatrix');matrix.replaceChildren();
    for(const source of report.source_coverage||[]){
      const group=document.createElement('section');group.className='rc-matrix-source';
      group.append(node('h5',source.path),
        node('p',source.excerpt_count+' excerpts · Methodology (reviewer): '+
          source.methodology.replaceAll('_',' ')+' · Quality (reviewer): '+
          source.quality.replaceAll('_',' '),'rc-hint'));
      if(source.limitations)group.append(node('p','Limitations: '+source.limitations,'rc-hint'));
      if(source.gap)group.append(node('p','Coverage gap: '+source.gap.replaceAll('_',' '),'rc-gap'));
      for(const excerpt of (report.matrix||[]).filter(x=>x.source===source.path)){
        const card=document.createElement('article');card.className='rc-matrix-item';
        const flag=node('strong',excerpt.id+' · '+excerpt.stance.toUpperCase(),'rc-label');
        flag.setAttribute('data-rc-status',excerpt.stance);
        card.append(flag,node('blockquote',excerpt.quote),
          node('p',excerpt.rationale||'No reviewer rationale entered.','rc-hint'),
          node('small',(excerpt.page?'PDF page '+excerpt.page:'Section '+excerpt.section)+
            ' · offset '+excerpt.offset+' · SHA-256 '+excerpt.sha256));
        group.append(card);
      }
      matrix.append(group);
    }
    const warnings=el('rcWarnings');warnings.replaceChildren();
    for(const warning of report.warnings||[])warnings.append(node('p',warning,'rc-warning'));
    if(history){
      warnings.append(node('p',
        'Historical review. Source state: '+history.source_status.map(s=>s.path+' = '+s.status).join('; ')+
        '. V1 project state: '+history.project_status+'. Verify again before citing.','rc-warning'));
    }
  }
  el('rcProject').onchange=()=>{prepared=null;el('rcEditor').hidden=true;invalidate();};
  el('rcClaim').oninput=invalidate;
  el('rcRefreshProjects').onclick=async()=>{
    try{await projects();say('Available two-source projects refreshed.');}
    catch(e){say('Cannot load research projects: '+e.message,true);}
  };
  el('rcRefreshReviews').onclick=async()=>{
    try{await comparisons();say('Historical review library refreshed.');}
    catch(e){say('Cannot list comparisons: '+e.message,true);}
  };
  el('rcPrepare').onclick=async()=>{
    const path=el('rcProject').value;
    if(!path){say('Select a saved V1 project containing two or more source documents.',true);return;}
    const token=++sequence;
    try{
      say('Checking the saved research project and exact quotation locations…');
      const data=await api('/api/research/studio/compare/prepare',{project_path:path});
      if(!host.isConnected||sequence!==token||el('rcProject').value!==path)return;
      if(data.project_path!==path||data.source_count<2||!data.no_model)
        throw Error('Response identity could not be verified.');
      prepareUI(data);
    }catch(e){say('Quote verification rejected: '+e.message,true);}
  };
  el('rcPreview').onclick=async()=>{
    try{
      const body=payload(),original=JSON.stringify(body);
      say('Revalidating current sources and your assigned positions…');
      const data=await api('/api/research/studio/compare/preview',body);
      if(original!==JSON.stringify(payload())){say('Inputs changed; preview the comparison again.',true);return;}
      reportUI(data.report,null);say('Comparison preview complete. Human ratings are not verified factual conclusions.');
    }catch(e){say('Comparison preview rejected: '+e.message,true);}
  };
  el('rcSave').onclick=async()=>{
    if(!el('rcConfirm').checked){say('Acknowledge that these are your own unverified assessments.',true);return;}
    if(!window.confirm('Save a new immutable, human-labelled comparison? Source files, V1 projects and old reviews will not be changed.'))return;
    try{
      const result=await api('/api/research/studio/compare/save',{
        ...payload(),acknowledgement:'SAVE REVIEW',confirm_human_classification:true});
      await comparisons(result.path);
      const prior=await api('/api/research/studio/compare/open?path='+encodeURIComponent(result.path));
      reportUI(prior.report,{source_status:prior.source_status,project_status:prior.project_status});
      el('rcConfirm').checked=false;
      say('Private comparison saved as a separate create-only review snapshot.');
    }catch(e){say('Cannot save human review: '+e.message,true);}
  };
  el('rcOpen').onclick=async()=>{
    const path=el('rcReviews').value;
    if(!path){say('Choose an existing comparison.',true);return;}
    try{
      const record=await api('/api/research/studio/compare/open?path='+encodeURIComponent(path));
      prepared=null;el('rcEditor').hidden=true;
      reportUI(record.report,{source_status:record.source_status,project_status:record.project_status});
      say('Historical review loaded read-only. Any changed or missing source is flagged.');
    }catch(e){say('Could not open comparison: '+e.message,true);}
  };
  Promise.all([projects(),comparisons()]).catch(e=>say('Comparison catalogue unavailable: '+e.message,true));
}

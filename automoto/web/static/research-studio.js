/* Research Studio V1: private, source-pinned evidence workspace.
   All source, title, quote and notes values are rendered with textContent. */
import {researchRequest,verifiedResearchView,researchNotes} from "./document-research-model.js";
import {mountResearchDiscovery} from "./research-discovery.js";
import {mountResearchComparison} from "./research-comparison.js";
import {mountResearchPublishing} from "./research-publishing.js";

export async function mountResearchStudio({api,page,toast}){
  const host=page("Research Studio",
    "Evidence-first research using private saved documents. No invented citations, cloud model or background crawling.",
    '<div class="rs-shell">'+
    '<section class="rs-hero"><div><span class="rs-eyebrow">RESEARCH STUDIO · V1</span>'+
    '<h3>Ground every finding in your sources</h3>'+
    '<p>Choose documents, pin their SHA-256 fingerprints, find quoted evidence and save a private research project.</p></div>'+
    '<button type="button" class="btn" id="rsRefresh">Refresh sources</button></section>'+
    '<p class="rs-notice" role="note"><strong>Evidence is not fact verification.</strong> Quotations come from extracted document text. PDF page numbers are provided only when known; Word and text extracts have no verified page numbers. Source authors, publication dates and references are never guessed.</p>'+
    '<div class="rs-layout">'+
    '<section class="rs-panel" aria-labelledby="rsSourceTitle"><div class="rs-head"><h4 id="rsSourceTitle">Private source library</h4><span id="rsSelected">0 of 5 selected</span></div>'+
    '<label class="rs-field">Filter files<input id="rsFilter" class="input" type="search" placeholder="Search your uploaded documents" autocomplete="off" /></label>'+
    '<div id="rsSourceList" class="rs-source-list" role="group" aria-label="Select documents for research"></div>'+
    '<p class="rs-hint">Use Files or Document Assistant to upload PDF, DOCX, Markdown or TXT. Existing editable document drafts can also be selected. This screen never edits source files.</p></section>'+
    '<section class="rs-panel" aria-labelledby="rsQuestionTitle"><h4 id="rsQuestionTitle">Research project</h4>'+
    '<label class="rs-field">Project title<input class="input" id="rsTitle" maxlength="120" value="New research project"></label>'+
    '<label class="rs-field">Research question<textarea class="input" id="rsQuestion" rows="3" maxlength="320" placeholder="What do the selected sources say about…?"></textarea></label>'+
    '<label class="rs-field">Retrieval mode<select class="input" id="rsMode"><option value="evidence">Find source excerpts</option><option value="outline">Find excerpts and propose an outline</option></select></label>'+
    '<label class="rs-field">Research notes (your own)<textarea class="input" id="rsNotes" rows="3" maxlength="1400" placeholder="Scope, assumptions and questions to investigate"></textarea></label>'+
    '<div class="rs-actions"><button type="button" class="btn primary" id="rsFind">Find verified excerpts</button>'+
    '<button type="button" class="btn" id="rsSave">Save private project</button></div>'+
    '<div class="rs-divider"></div><div class="rs-head"><h4>Saved research projects</h4><button type="button" class="btn" id="rsReloadProjects">Refresh</button></div>'+
    '<label class="rs-field">Saved projects<select class="input" id="rsProjects"><option value="">Select a saved project</option></select></label>'+
    '<button type="button" class="btn" id="rsOpen">Open saved evidence</button>'+
    '<p class="rs-hint">Saving creates a new immutable snapshot. Opening saved excerpts does not mean their sources are still current.</p></section></div>'+
    '<section class="rs-panel" aria-label="Research findings"><div class="rs-head"><h4>Source-linked findings</h4>'+
    '<button class="btn" type="button" id="rsCopy" disabled>Copy evidence notes</button></div>'+
    '<div id="rsEvidenceSummary" class="rs-summary" aria-live="polite">No research has been run.</div>'+
    '<div id="rsSourceStates" class="rs-states"></div><div id="rsEvidence" class="rs-evidence"></div>'+
    '<div id="rsOutline" class="rs-outline"></div>'+
    '<p id="rsLimitations" class="rs-hint"></p></section>'+
    '<section id="rsDiscoveryRoot" aria-label="Scholarly source discovery"></section>'+
    '<section id="rsComparisonRoot" aria-label="Evidence comparison and contradiction mapping"></section>'+
    '<section id="rsPublishingRoot" aria-label="Academic report publishing"></section>'+
    '<p class="rs-status" id="rsStatus" role="status" aria-live="polite">Choose a file and research question to begin.</p></div>');
  const el=id=>host.querySelector("#"+id);
  let catalog=[],selected=new Set(),pinned={},loaded=null,latest=null,latestRequest=null,sequence=0;
  function notice(message,error=false){
    el("rsStatus").textContent=message;
    el("rsStatus").classList.toggle("rs-error",error);
    if(error&&toast)toast(message,"bad");
  }
  function invalidate(){
    latest=null;latestRequest=null;loaded=null;
    el("rsCopy").disabled=true;
  }
  function updateCount(){el("rsSelected").textContent=selected.size+" of 5 selected";}
  function renderCatalog(){
    const target=el("rsSourceList");target.replaceChildren();
    const needle=el("rsFilter").value.trim().toLowerCase();
    const view=catalog.filter(item=>item.name.toLowerCase().includes(needle));
    if(!view.length){
      const p=document.createElement("p");p.className="rs-hint";
      p.textContent=catalog.length?"No matching files.":"No supported files yet. Add one in Files or Document Assistant.";
      target.append(p);return;
    }
    for(const item of view){
      const label=document.createElement("label");label.className="rs-source";
      const input=document.createElement("input");input.type="checkbox";
      input.checked=selected.has(item.path);input.value=item.path;
      input.setAttribute("aria-label","Select "+item.name);
      const details=document.createElement("span");details.className="rs-file-detail";
      const name=document.createElement("strong");name.textContent=item.name;
      const meta=document.createElement("small");
      const pin=pinned[item.path];
      meta.textContent=item.kind.toUpperCase()+" · "+item.bytes+" bytes"+
        (pin?" · SHA-256 "+pin.sha256.slice(0,12)+"…":"");
      details.append(name,meta);label.append(input,details);
      input.onchange=async()=>{
        if(!input.checked){
          selected.delete(item.path);delete pinned[item.path];
          invalidate();updateCount();renderCatalog();return;
        }
        if(selected.size>=5){
          input.checked=false;notice("Select no more than five source documents.",true);return;
        }
        const token=++sequence;input.disabled=true;
        try{
          const info=await api("/api/documents/research/source-info?path="+encodeURIComponent(item.path));
          if(!host.isConnected||token!==sequence)return;
          if(info.path!==item.path||!/^[0-9a-f]{64}$/.test(info.sha256))
            throw Error("Invalid source verification.");
          pinned[item.path]={path:info.path,sha256:info.sha256};
          selected.add(item.path);invalidate();notice("Source pinned by SHA-256: "+item.name);
        }catch(error){input.checked=false;notice("Cannot verify source: "+error.message,true);}
        finally{input.disabled=false;updateCount();renderCatalog();}
      };
      target.append(label);
    }
  }
  function rows(result,request,historical=false,states=[]){
    const view=verifiedResearchView(result,request);
    latest=view;latestRequest=request;
    el("rsCopy").disabled=false;
    const summary=el("rsEvidenceSummary");summary.textContent=view.evidence.length+
      " source-linked excerpt(s) · "+request.sources.length+" pinned source(s) · "+
      (historical?"saved historical snapshot":"fresh local retrieval");
    const stat=el("rsSourceStates");stat.replaceChildren();
    for(const source of states){
      const p=document.createElement("p");
      p.textContent=source.path+" — "+source.status.replaceAll("_"," ")+
        (source.status==="current"?"":" (previous evidence may be stale)");
      p.className=source.status==="current"?"rs-current":"rs-stale";
      stat.append(p);
    }
    const evidence=el("rsEvidence");evidence.replaceChildren();
    for(const item of view.evidence){
      const article=document.createElement("article");article.className="rs-excerpt";
      const header=document.createElement("div");header.className="rs-excerpt-head";
      const badge=document.createElement("strong");badge.textContent=item.id;
      const ref=document.createElement("span");
      ref.textContent=item.source+" · "+(item.page?"PDF page "+item.page:item.section+" (no verified page)")+
        " · offset "+item.offset;
      const block=document.createElement("blockquote");block.textContent=item.quote;
      const digest=document.createElement("small");digest.textContent="Source SHA-256 "+item.sha256;
      header.append(badge,ref);article.append(header,block,digest);evidence.append(article);
    }
    if(!view.evidence.length){
      const empty=document.createElement("p");
      empty.textContent="No supported matching excerpts were found. This does not prove the claim false.";
      evidence.append(empty);
    }
    const outline=el("rsOutline");outline.replaceChildren();
    if(view.outline.length){
      const heading=document.createElement("h5");heading.textContent="Suggested research outline";
      outline.append(heading);
      for(const section of view.outline){
        const p=document.createElement("p");const strong=document.createElement("strong");
        strong.textContent=section.heading+": ";p.append(strong,document.createTextNode(section.guidance));
        outline.append(p);
      }
    }
    el("rsLimitations").textContent=view.limitations+
      (view.partialSources.length?" Partial extraction: "+view.partialSources.join(", "):"");
    return view;
  }
  function payload(){
    return {
      title:el("rsTitle").value.trim(),question:el("rsQuestion").value.trim(),
      mode:el("rsMode").value,notes:el("rsNotes").value.trim(),
      sources:researchRequest(el("rsQuestion").value,[...selected],pinned,el("rsMode").value).sources,
    };
  }
  async function refreshSources(){
    const response=await api("/api/research/studio/sources");
    if(!host.isConnected)return;
    catalog=response.sources||[];
    renderCatalog();updateCount();
  }
  async function refreshProjects(preferred){
    const response=await api("/api/research/studio/list");
    if(!host.isConnected)return;
    const chooser=el("rsProjects"),existing=preferred||chooser.value;
    chooser.replaceChildren();const empty=document.createElement("option");
    empty.value="";empty.textContent="Select a saved project";chooser.append(empty);
    for(const item of response.projects||[]){
      const option=document.createElement("option");option.value=item.path;
      option.textContent=item.title+" · "+item.evidence_count+" excerpt(s)";
      chooser.append(option);
    }
    if([...chooser.options].some(option=>option.value===existing))chooser.value=existing;
  }
  el("rsFilter").oninput=renderCatalog;
  for(const id of ["rsTitle","rsQuestion","rsMode","rsNotes"])
    el(id).addEventListener("input",invalidate);
  el("rsRefresh").onclick=async()=>{
    try{await refreshSources();notice("Private document list refreshed.");}
    catch(error){notice("Could not refresh private documents: "+error.message,true);}
  };
  el("rsReloadProjects").onclick=async()=>{
    try{await refreshProjects();notice("Saved research projects refreshed.");}
    catch(error){notice("Could not load saved projects: "+error.message,true);}
  };
  el("rsFind").onclick=async()=>{
    try{
      const project=payload(),original=JSON.stringify(project);
      notice("Searching locally extracted source text. No cloud model is being used…");
      const response=await api("/api/research/studio/query",project);
      if(!host.isConnected||JSON.stringify(payload())!==original){
        notice("Inputs changed during retrieval. Re-run your research.",true);return;
      }
      rows(response.result,researchRequest(project.question,project.sources.map(s=>s.path),pinned,project.mode),
        false,response.source_status);
      notice("Source-linked excerpts retrieved. Review the original documents before citing.");
    }catch(error){notice("Research retrieval failed: "+error.message,true);}
  };
  el("rsSave").onclick=async()=>{
    try{
      const project=payload();
      notice("Revalidating source fingerprints and saving a new private snapshot…");
      const result=await api("/api/research/studio/save",project);
      await refreshProjects(result.path);
      notice("Private project saved. "+result.evidence_count+" excerpt(s); source documents unchanged.");
    }catch(error){notice("Save failed: "+error.message,true);}
  };
  el("rsOpen").onclick=async()=>{
    const path=el("rsProjects").value;
    if(!path){notice("Select a saved research project.",true);return;}
    if(!window.confirm("Open this historical research snapshot? Unsaved changes in this editor will be replaced."))return;
    try{
      const data=await api("/api/research/studio/open?path="+encodeURIComponent(path));
      for(const [id,value] of [
        ["rsTitle",data.project.title],["rsQuestion",data.project.question],
        ["rsMode",data.project.mode],["rsNotes",data.project.notes]])el(id).value=value;
      selected=new Set(data.project.sources.map(x=>x.path));
      pinned=Object.fromEntries(data.project.sources.map(x=>[x.path,x]));
      renderCatalog();updateCount();
      const req=researchRequest(data.project.question,data.project.sources.map(s=>s.path),
        pinned,data.project.mode);
      rows(data.result,req,true,data.source_status);
      loaded=path;
      const stale=data.source_status.filter(s=>s.status!=="current").length;
      notice("Historical project loaded. "+(stale?stale+" source(s) changed or unavailable; re-run before relying on findings.":"Source fingerprints still match."));
    }catch(error){notice("Open failed: "+error.message,true);}
  };
  el("rsCopy").onclick=async()=>{
    if(!latest||!latestRequest)return;
    try{
      await navigator.clipboard.writeText(researchNotes(latestRequest.query,latest));
      notice("Research evidence notes copied. Check original source context before publication.");
    }catch(error){notice("Clipboard copy unavailable: "+error.message,true);}
  };
  mountResearchDiscovery({host:el("rsDiscoveryRoot"),api,refreshSources,toast});
  mountResearchComparison({host:el("rsComparisonRoot"),api,toast});
  mountResearchPublishing({host:el("rsPublishingRoot"),api,toast});
  await Promise.all([refreshSources(),refreshProjects()]).catch(error=>{
    notice("Research workspace could not load: "+error.message,true);
  });
}

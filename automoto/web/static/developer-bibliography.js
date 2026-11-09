/* Developer Studio V10 — provenance-first bibliography and citation preflight. */
export function mountDeveloperBibliography({api,host,getProject,editor,status}) {
  const BASE="/api/developer/studio/bibliography";
  const root=host.querySelector("#dsBibliographyRoot");
  root.innerHTML=
    '<section class="ds-bib-panel" aria-label="Bibliography and citation preflight">'+
      '<div class="ds-bib-head"><h3>Bibliography & citations · V10</h3><span class="ds-readonly">EVIDENCE FIRST · NO AUTO-LOOKUP</span></div>'+
      '<div class="ds-bib-body">'+
        '<p class="ds-footnote">Inspect locally referenced BibTeX/BibLaTeX records before submission. DOI checks contact Crossref only after your separate consent. Matching a DOI does not establish publication authenticity or peer review.</p>'+
        '<div class="ds-bib-controls">'+
          '<label for="dsBibMain">LaTeX root</label>'+
          '<input id="dsBibMain" class="input" maxlength="1024" placeholder="main.tex" spellcheck="false">'+
          '<button class="btn sm primary" id="dsBibPreflight" type="button" disabled>Run citation preflight</button>'+
          '<button class="btn sm" id="dsBibUseTexRoot" type="button" disabled>Use LaTeX root</button>'+
        '</div>'+
        '<p class="ds-footnote" id="dsBibStatus" role="status" aria-live="polite">Open a project to inspect its citations.</p>'+
        '<div class="ds-bib-actions">'+
          '<label for="dsBibEntry">Citation key</label>'+
          '<select id="dsBibEntry" class="input" disabled><option value="">Run preflight first</option></select>'+
          '<button type="button" id="dsBibVerify" class="btn sm" disabled>Check DOI with Crossref</button>'+
          '<label for="dsBibStyle">Reference preview</label>'+
          '<select id="dsBibStyle" class="input"><option value="harvard">Harvard</option><option value="ieee">IEEE</option></select>'+
          '<button type="button" id="dsBibFormat" class="btn sm" disabled>Preview reference</button>'+
        '</div>'+
        '<div id="dsBibResults" class="ds-bib-results" role="region" aria-label="Citation preflight findings" tabindex="0"></div>'+
        '<p class="ds-footnote">Preflight is a bounded static parser. BibTeX macro expansion, compiler-generated citation order, full CSL formatting and the validity of an academic paper are not certified. Review reference metadata against the publication before use.</p>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id), area=el("dsBibResults");
  let entries=[], report=null, busy=false, seq=0, activePath=null;
  const setMessage=(value,bad=false)=>{const node=el("dsBibStatus");node.textContent=value;node.classList.toggle("ds-error",bad);};
  const project=()=>getProject()?.project||"";
  function ready(){
    const enabled=!!project()&&!busy;
    el("dsBibPreflight").disabled=!enabled||!el("dsBibMain").value.trim();
    el("dsBibUseTexRoot").disabled=!enabled;
    el("dsBibEntry").disabled=!enabled||!entries.length;
    const current=entries.find(item=>item.key===el("dsBibEntry").value);
    el("dsBibVerify").disabled=!enabled||!current?.doi_normalised;
    el("dsBibFormat").disabled=!enabled||!current;
  }
  function clear(){
    area.replaceChildren();
  }
  function title(value){
    const h=document.createElement("h4");h.textContent=value;area.appendChild(h);
  }
  function line(value,kind="neutral"){
    const p=document.createElement("p");p.className="ds-bib-line";
    p.textContent=value;
    if(kind!=="neutral")p.dataset.severity=kind;
    area.appendChild(p);
  }
  function safeText(obj){return String(obj??"").slice(0,1000);}
  function selectEntries(){
    const prev=el("dsBibEntry").value;
    const select=el("dsBibEntry");
    select.replaceChildren();
    select.add(new Option("Select citation key",""));
    for(const item of entries.slice(0,200)){
      const state=item.issues?.length?" · needs attention":item.metadata_verified?" · Crossref checked":" · not checked";
      select.add(new Option(item.key+state,item.key));
    }
    if(entries.some(x=>x.key===prev))select.value=prev;
    else if(entries.length===1)select.value=entries[0].key;
    ready();
  }
  function showReport(data){
    clear();
    title("Citation preflight");
    line(data.entry_count+" bibliographic record(s) across "+data.bib_files.length+
      " BibTeX/BibLaTeX file(s). "+
      (data.truncated?"Scan truncated; findings may be incomplete.":"Read-only static scan complete."));
    if(data.missing_citations.length){
      title("Unresolved citations ("+data.missing_citations.length+")");
      for(const key of data.missing_citations)line(key,"error");
    }
    if(data.duplicate_keys.length){
      title("Duplicate citation keys ("+data.duplicate_keys.length+")");
      for(const key of data.duplicate_keys)line(key,"error");
    }
    if(data.parser_warnings.length){
      title("Parse warnings ("+data.parser_warnings.length+")");
      for(const warning of data.parser_warnings.slice(0,80))
        line(warning.code+" · "+warning.path+" · "+warning.message,"warning");
    }
    title("Bibliography records ("+data.entries.length+")");
    if(!data.entries.length)line("No local records were found in the selected root document.");
    for(const entry of data.entries.slice(0,120)){
      const section=document.createElement("div");section.className="ds-bib-record";
      const heading=document.createElement("strong");
      heading.textContent=entry.key+" · "+entry.type+" · "+entry.path+
        (entry.cited?" · cited":" · not cited");
      section.append(heading);
      const title=document.createElement("p");title.className="ds-bib-title";
      title.textContent=safeText(entry.fields.title||"Title missing");
      section.append(title);
      const state=document.createElement("p");state.className="ds-bib-meta";
      state.textContent=entry.doi_normalised?
        "DOI "+entry.doi_normalised+" · "+entry.doi_evidence:
        "No valid DOI · registry evidence unavailable";
      section.append(state);
      for(const problem of entry.issues||[]){
        const p=document.createElement("p");p.className="ds-bib-issue";p.textContent=problem;section.append(p);
      }
      area.append(section);
    }
    if(!data.blocking_issues){
      line("No blocking structural errors were detected in this bounded scan. This does not make the references publication-ready.");
    } else {
      line("Preflight has issues needing review. No source was rewritten.", "warning");
    }
  }
  function payload(){
    const rootPath=project(),main=el("dsBibMain").value.trim();
    if(!rootPath||!main)return null;
    const body={project:rootPath,main};
    const context=editor.lspContext();
    if(context?.path?.endsWith(".tex")){
      body.active_path=context.path;
      body.active_text=context.text;
    }
    return body;
  }
  async function preflight(){
    const body=payload();if(!body||busy)return;
    const turn=++seq;busy=true;ready();
    setMessage("Checking the local bibliography and cited keys. No network request is made.");
    try{
      const data=await api(BASE+"/preflight",body);
      if(turn!==seq||project()!==body.project||!root.isConnected)return;
      report=data;entries=data.entries||[];
      selectEntries();showReport(data);
      setMessage(data.entry_count+" records · "+data.missing_citations.length+
        " unresolved citation keys · "+
        entries.filter(x=>x.issues?.length).length+" records need attention"+
        (data.truncated?" · partial results":"")+". No network request.");
    }catch(error){setMessage("Citation preflight failed: "+error.message,true);}
    finally{busy=false;ready();}
  }
  async function verify(){
    const body=payload(),key=el("dsBibEntry").value;
    const entry=entries.find(item=>item.key===key);
    if(!body||!entry?.doi_normalised||busy)return;
    if(!window.confirm("Check DOI "+entry.doi_normalised+" against the Crossref registry? Only the DOI is sent to Crossref. Its record does not prove peer review, legitimacy or publication quality."))return;
    const turn=++seq;busy=true;ready();
    setMessage("Checking the selected DOI against Crossref…");
    try{
      const verified=await api(BASE+"/verify-doi",{...body,key});
      if(turn!==seq||project()!==body.project)return;
      clear();title("Crossref DOI evidence for "+key);
      line("Registry DOI: "+verified.doi);
      line("Registered title: "+(verified.registry.title||"Not supplied"));
      line("Registered year: "+(verified.registry.year??"Not supplied"));
      line("Registered publisher: "+(verified.registry.publisher||"Not supplied"));
      line("Field comparison: "+JSON.stringify(verified.field_comparison));
      for(const issue of verified.possible_mismatches||[])line(issue,"warning");
      line("This record is registry metadata, NOT proof that the research is genuine or peer-reviewed.","warning");
      setMessage("DOI lookup completed. Registry evidence remains advisory; review the actual publication.");
      const selected=key;
      const updated=await api(BASE+"/preflight",body);
      if(turn!==seq||project()!==body.project)return;
      report=updated;entries=updated.entries||[];selectEntries();
      el("dsBibEntry").value=selected;
    }catch(error){setMessage("DOI lookup unavailable or rejected: "+error.message,true);}
    finally{busy=false;ready();}
  }
  async function format(){
    const body=payload(),key=el("dsBibEntry").value;
    if(!body||!key||busy)return;
    const style=el("dsBibStyle").value,turn=++seq;
    busy=true;ready();setMessage("Generating a local reference-format preview…");
    try{
      const data=await api(BASE+"/format",{...body,key,style});
      if(turn!==seq||project()!==body.project)return;
      clear();title(data.style.toUpperCase()+" citation preview · "+key);
      const field=document.createElement("textarea");
      field.className="input ds-bib-preview";field.rows=5;field.readOnly=true;
      field.setAttribute("aria-label","Copy-ready citation preview");
      field.value=data.reference;
      const select=document.createElement("button");
      select.type="button";select.className="btn sm";select.textContent="Select reference text";
      select.onclick=()=>{field.focus();field.select();};
      area.append(field,select);
      line("Preview uses local bibliography fields. Harvard variants and actual IEEE order must be reviewed against your required style guide.","warning");
      setMessage("Reference preview generated. No project file was changed.");
    }catch(error){setMessage("Cannot format this citation safely: "+error.message,true);}
    finally{busy=false;ready();}
  }
  function useTexRoot(){
    const main=host.querySelector("#dsTexMain")?.value.trim();
    if(main)el("dsBibMain").value=main;
    else if(activePath?.toLowerCase().endsWith(".tex"))el("dsBibMain").value=activePath;
    ready();
  }
  function fileChanged(path){
    activePath=path||null;
    if(!el("dsBibMain").value.trim()&&path?.toLowerCase().endsWith(".tex"))
      el("dsBibMain").value=path;
    ready();
  }
  function projectChanged(){
    seq++;busy=false;report=null;entries=[];activePath=null;
    el("dsBibMain").value="";clear();selectEntries();
    setMessage("Open a project to inspect its bibliography.");ready();
  }
  el("dsBibMain").addEventListener("input",ready);
  el("dsBibEntry").addEventListener("change",ready);
  el("dsBibPreflight").onclick=()=>void preflight();
  el("dsBibUseTexRoot").onclick=useTexRoot;
  el("dsBibVerify").onclick=()=>void verify();
  el("dsBibFormat").onclick=()=>void format();
  ready();
  return {projectChanged,fileChanged,preflight};
}

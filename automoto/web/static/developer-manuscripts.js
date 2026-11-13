/* Developer Studio V12 — Typst, Quarto and provenance-preserving research review. */
export function mountDeveloperManuscripts({api,host,getProject,editor,status}) {
  const root=host.querySelector("#dsManuscriptsRoot");
  const M="/api/developer/studio/manuscripts";
  const T="/api/developer/studio/research-transfer";
  root.innerHTML=
    '<section class="ds-manuscript-panel" aria-label="Typst Quarto manuscript and research handoffs">'+
    '<div class="ds-manuscript-head"><h3>Typst, Quarto & research · V12</h3>'+
    '<span class="ds-readonly">SOURCE-VERIFIED · NO EXECUTION</span></div>'+
    '<div class="ds-manuscript-body">'+
      '<p class="ds-footnote">Inspect Typst/Quarto manuscripts, citation keys, chapter includes and bibliography files. Quarto code cells are never executed. Research Studio evidence stays in a separate review-only provenance file, not in executable source.</p>'+
      '<div class="ds-manuscript-controls">'+
        '<label for="dsManFormat">Format</label>'+
        '<select class="input" id="dsManFormat"><option value="typst">Typst (.typ)</option><option value="quarto">Quarto (.qmd)</option></select>'+
        '<label for="dsManMain">Manuscript</label><input class="input" id="dsManMain" maxlength="1024" spellcheck="false" placeholder="main.typ">'+
        '<button type="button" class="btn sm" id="dsManScan" disabled>Inspect manuscript</button>'+
        '<button type="button" class="btn sm" id="dsManTools" disabled>Inspect toolchains</button>'+
        '<button type="button" class="btn sm" id="dsManStarter">Preview starter</button>'+
      '</div>'+
      '<p class="ds-footnote" role="status" aria-live="polite" id="dsManStatus">Open a project to inspect manuscripts.</p>'+
      '<div class="ds-manuscript-result" id="dsManResult" role="region" aria-label="Manuscript findings" tabindex="0"></div>'+
      '<div class="ds-manuscript-transfer">'+
        '<h4>Research Studio evidence hand-off</h4>'+
        '<p class="ds-footnote">Select an already saved, source-reviewed Research Studio developer hand-off. Every source checksum is checked again before preview or export. Publication DOI bindings are optional, but must use exact V4-saved Crossref record fingerprints and explicit same-publication confirmations.</p>'+
        '<div class="ds-manuscript-controls">'+
          '<button class="btn sm" id="dsManHandoffs" disabled type="button">Find reviewed hand-offs</button>'+
          '<label for="dsManHandoffSelect">Research hand-off</label>'+
          '<select class="input" id="dsManHandoffSelect" disabled><option value="">No hand-off loaded</option></select>'+
        '</div>'+
        '<label for="dsManBindings">Optional publication bindings (JSON array of confirmed Research Studio V4 records)</label>'+
        '<textarea class="input ds-manuscript-bindings" id="dsManBindings" rows="3" spellcheck="false" placeholder="[]"></textarea>'+
        '<div class="ds-manuscript-controls">'+
          '<button class="btn sm" id="dsManReview" disabled type="button">Preview research package</button>'+
          '<button class="btn sm primary" id="dsManDownload" disabled type="button">Review & export ZIP</button>'+
        '</div>'+
        '<p class="ds-footnote">No research source, workspace manuscript or existing bibliography is overwritten. Downloads require explicit human approval. Exporting an evidence record does not certify any scientific conclusion or authorise publication.</p>'+
      '</div>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id);
  let busy=false, sequence=0, handoffs=[], last=null, current=null;
  const project=()=>getProject()?.project||"";
  function message(v,err=false) {
    const n=el("dsManStatus");n.textContent=v;n.classList.toggle("ds-error",err);
  }
  function controls(){
    const ok=!!project()&&!busy;
    el("dsManScan").disabled=!ok||!el("dsManMain").value.trim();
    el("dsManTools").disabled=!ok;
    el("dsManHandoffs").disabled=!ok;
    el("dsManHandoffSelect").disabled=!ok||!handoffs.length;
    const selected=handoffs.some(x=>x.path===el("dsManHandoffSelect").value);
    el("dsManReview").disabled=!ok||!selected;
    el("dsManDownload").disabled=!ok||!selected;
  }
  function title(v){const h=document.createElement("h4");h.textContent=v;el("dsManResult").append(h);}
  function line(v,kind="info"){
    const p=document.createElement("p");p.className="ds-manuscript-line";
    p.textContent=String(v);p.dataset.kind=kind;el("dsManResult").append(p);
  }
  function clear(){el("dsManResult").replaceChildren();}
  function data(){
    const context=editor.lspContext();
    const obj={project:project(),format:el("dsManFormat").value,main:el("dsManMain").value.trim()};
    if(context?.path && /\.(?:typ|qmd|md)$/i.test(context.path)){
      obj.active_path=context.path;obj.active_text=context.text;
    }
    return obj;
  }
  async function scan(){
    if(!project()||busy)return;
    const req=data(),id=++sequence;busy=true;controls();
    message("Checking local manuscript files; no compiler, model or code cell is run.");
    try{
      const out=await api(M+"/scan",req);
      if(id!==sequence||project()!==req.project)return;
      clear();title("Manuscript structure");
      line(out.files.length+" source file(s) · "+out.headings.length+" headings · "+
        out.citations.length+" citation markers · "+out.bibliography_files.length+" bibliographies.");
      for(const item of out.headings.slice(0,50))line(item.title+" · "+item.path+":"+((item.line||0)+1));
      title("Citation integrity");
      for(const key of out.missing_citations)line("Unresolved citation: "+key,"error");
      for(const key of out.duplicate_keys)line("Duplicate bibliography key: "+key,"error");
      for(const item of out.citation_issues)
        for(const issue of item.issues)line(item.key+": "+issue,"warning");
      if(!out.missing_citations.length&&!out.duplicate_keys.length)
        line("No unresolved or duplicate keys in the scanned subset; publication validity remains unverified.");
      title("Warnings");
      for(const item of out.warnings)line(item.code+" · "+item.path+" · "+item.message,"warning");
      if(out.executable_code_chunks)line(out.executable_code_chunks+
        " Quarto code chunk(s) detected. Rendering could execute code; V12 did not run it.","warning");
      message("Static analysis complete"+(out.truncated?" · incomplete bounded scan":"")+
        ". No source was executed or modified.");
    }catch(e){message("Manuscript scan failed: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function tools(){
    if(!project()||busy)return;
    busy=true;controls();
    try{
      const d=await api(M+"/toolchains?"+new URLSearchParams({project:project()}));
      clear();title("Local toolchain detection — nothing executed");
      for(const item of d.tools)line(item.name+": "+(item.installed_path_detected?
        "found on PATH (compatibility unverified)":"not detected"));
      message("Compiler locations inspected only; no versions checked or commands run.");
    }catch(e){message("Toolchain inspection failed: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function previewFiles(items){
    clear();
    for(const file of items){
      title(file.path+" — review only");
      const text=document.createElement("textarea");text.className="input ds-manuscript-preview";
      text.rows=Math.min(12,Math.max(4,file.text.split("\n").length));
      text.readOnly=true;text.value=file.text;
      text.setAttribute("aria-label","Review-only "+file.path);
      const select=document.createElement("button");select.type="button";select.className="btn sm";
      select.textContent="Select text";select.onclick=()=>{text.focus();text.select();};
      el("dsManResult").append(text,select);
    }
  }
  async function starter(){
    if(busy)return;
    busy=true;controls();
    try{
      const d=await api(M+"/starter",{format:el("dsManFormat").value});
      previewFiles([{path:d.path,text:d.text}]);
      message("Original source template previewed. No project files created.");
    }catch(e){message("Starter preview failed: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function loadHandoffs(){
    if(!project()||busy)return;
    busy=true;controls();
    try{
      const d=await api(T+"/handoffs");
      handoffs=d.handoffs||[];
      const select=el("dsManHandoffSelect"),old=select.value;
      select.replaceChildren();select.add(new Option("Select a source-reviewed developer hand-off",""));
      for(const item of handoffs)
        select.add(new Option(item.research_question+" · "+item.path,item.path));
      if(handoffs.some(x=>x.path===old))select.value=old;
      message(handoffs.length+" developer hand-off audit(s) found. Nothing transferred or modified.");
    }catch(e){message("Cannot load Research Studio hand-offs: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function transferPayload(){
    const found=handoffs.find(x=>x.path===el("dsManHandoffSelect").value);
    if(!found)throw Error("Select an existing reviewed developer hand-off.");
    let bindings;
    try{bindings=JSON.parse(el("dsManBindings").value.trim()||"[]");}
    catch{throw Error("Publication bindings must be valid JSON.");}
    if(!Array.isArray(bindings)||bindings.length>5)throw Error("Up to five confirmed binding records are supported.");
    return {project:project(),format:el("dsManFormat").value,
      handoff_path:found.path,handoff_sha256:found.sha256,bindings};
  }
  async function previewTransfer(){
    if(busy||!project())return;
    let req;try{req=transferPayload();}catch(e){message(e.message,true);return;}
    const id=++sequence;busy=true;controls();
    message("Rechecking Research Studio evidence, source fingerprints and DOI associations.");
    try{
      const d=await api(T+"/preview",req);
      if(id!==sequence||project()!==req.project)return;
      last=d;previewFiles(d.files);
      line("Review-only provenance manifest: "+JSON.stringify(d.manifest));
      message("Source-reverified draft package previewed. No project source was overwritten or published.");
    }catch(e){message("Research hand-off rejected: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function download(){
    if(busy||!project())return;
    let req;try{req=transferPayload();}catch(e){message(e.message,true);return;}
    if(!window.confirm("Export this source-verified research package for HUMAN REVIEW ONLY? "+
       "Research claims, quotations, publication identity and references are not certified. "+
       "No manuscript source will be automatically overwritten."))return;
    const id=++sequence;busy=true;controls();
    message("Rechecking saved research checksums and preparing a review-only ZIP.");
    try{
      const out=await api(T+"/download",{...req,confirmed:true,
        acknowledge_not_publication_ready:true});
      if(id!==sequence||project()!==req.project)return;
      const binary=atob(out.zip_base64),bytes=new Uint8Array(binary.length);
      if(bytes.length>327680)throw Error("Review archive exceeds size limit.");
      for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
      const url=URL.createObjectURL(new Blob([bytes],{type:"application/zip"}));
      try{
        const link=document.createElement("a");link.href=url;link.download=out.filename;
        link.click();
      }finally{
        // Keep URL valid through the synchronous download click; dispose during microtask.
        queueMicrotask(()=>URL.revokeObjectURL(url));
      }
      message("Review-only ZIP exported locally. No source changes, cloud upload or publication.");
    }catch(e){message("Research ZIP export failed: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function fileChanged(path){
    current=path||null;
    if(current?.toLowerCase().endsWith(".typ"))el("dsManFormat").value="typst";
    else if(current?.toLowerCase().endsWith(".qmd"))el("dsManFormat").value="quarto";
    if(current&&/\.(?:typ|qmd)$/.test(current)&&!el("dsManMain").value.trim())
      el("dsManMain").value=current;
    controls();
  }
  function projectChanged(){
    sequence++;busy=false;handoffs=[];last=null;current=null;clear();
    el("dsManMain").value="";
    el("dsManHandoffSelect").replaceChildren(new Option("No hand-off loaded",""));
    message("Open a project to inspect Typst/Quarto manuscripts.");controls();
  }
  el("dsManFormat").onchange=()=>{last=null;controls();};
  el("dsManMain").addEventListener("input",controls);
  el("dsManHandoffSelect").onchange=controls;
  el("dsManScan").onclick=()=>void scan();
  el("dsManTools").onclick=()=>void tools();
  el("dsManStarter").onclick=()=>void starter();
  el("dsManHandoffs").onclick=()=>void loadHandoffs();
  el("dsManReview").onclick=()=>void previewTransfer();
  el("dsManDownload").onclick=()=>void download();
  controls();
  return {fileChanged,projectChanged};
}

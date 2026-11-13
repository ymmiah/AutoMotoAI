/* Developer Studio V31 — read-only functional/logic evidence and approved fixtures. */
export function mountDeveloperLogic({api,host,getProject,status}){
  const root=host.querySelector("#dsLogicRoot");
  const base="/api/developer/studio/logic";
  root.innerHTML='<section class="ds-php-panel" aria-label="Functional and logic languages">'+
    '<div class="ds-php-head"><h3>Haskell, OCaml, Lisp, Scheme &amp; Prolog · V31</h3>'+
    '<span class="ds-readonly">STATIC EVIDENCE / APPROVED FIXED FIXTURES</span></div>'+
    '<div class="ds-php-body"><p class="ds-footnote">Inspect source SHA-256, heuristic declarations, package metadata and installed binary fingerprints. No source or manifest execution occurs during discovery.</p>'+
    '<div class="ds-php-controls">'+
    '<button id="dsLogicInspect" type="button" class="btn sm" disabled>Inspect five languages</button>'+
    '<label for="dsLogicTask">Fixed action</label><select id="dsLogicTask" class="input">'+
    '<option value="haskell_test">Haskell script</option><option value="ocaml_test">OCaml script</option>'+
    '<option value="lisp_test">Common Lisp script</option><option value="scheme_test">Scheme script</option>'+
    '<option value="prolog_test">Prolog script</option></select>'+
    '<label for="dsLogicTool">SHA-pinned interpreter</label>'+
    '<select id="dsLogicTool" class="input"><option value="">Inspect first</option></select>'+
    '<button id="dsLogicRun" type="button" class="btn sm primary" disabled>Review risk &amp; run</button>'+
    '<button id="dsLogicAgent" type="button" class="btn sm">Central Agent review</button></div>'+
    '<p id="dsLogicStatus" class="ds-footnote" role="status" aria-live="polite">Open a local project to begin.</p>'+
    '<div id="dsLogicResults" class="ds-php-results" role="region" tabindex="0" aria-label="Language source fingerprints and tools"></div>'+
    '<p class="ds-footnote">Interpreters run with local user privileges and are NOT sandboxed. They can read, write or access network resources. No general build, automatic installer, publication or deployment is approved.</p>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const out=el("dsLogicResults"), project=()=>getProject()?.project||"";
  const tools={haskell_test:"runghc",ocaml_test:"ocaml",lisp_test:"sbcl",
               scheme_test:"guile",prolog_test:"swipl"};
  const paths={haskell_test:"test/v31_fixture.hs",ocaml_test:"test/v31_fixture.ml",
               lisp_test:"test/v31_fixture.lisp",scheme_test:"test/v31_fixture.scm",
               prolog_test:"test/v31_fixture.pl"};
  let data=null,seq=0,busy=false;
  function notice(value,bad=false){
    el("dsLogicStatus").textContent=value;
    el("dsLogicStatus").classList.toggle("ds-error",bad);
  }
  function heading(value){const h=document.createElement("h4");h.textContent=value;out.append(h);}
  function line(value,bad=false){
    const node=document.createElement("p");
    node.className="ds-php-line";node.textContent=String(value);
    if(bad)node.dataset.severity="warning";out.append(node);
  }
  function currentTool(){return data?.toolchains?.find(t=>t.name===el("dsLogicTool").value&&t.status==="installed_not_executed");}
  function permitted(){
    if(!data||busy||!getProject()?.trusted||data.scan_incomplete||!currentTool())return false;
    const task=el("dsLogicTask").value;
    return tools[task]===currentTool().name&&
      data.files.some(file=>file.path===paths[task]&&file.canonical_fixture);
  }
  function controls(){
    el("dsLogicInspect").disabled=!project()||busy;
    el("dsLogicRun").disabled=!permitted();
  }
  function reset(){
    seq++;data=null;busy=false;out.replaceChildren();
    el("dsLogicTool").replaceChildren(new Option("Inspect first",""));
    notice("Inspection never evaluates code, build scripts or dependency manifests.");controls();
  }
  function render(d){
    out.replaceChildren();
    heading("Provenance and language navigation");
    line("Source inventory SHA-256: "+d.inventory_sha256);
    line("Installed toolchain SHA-256: "+d.toolchain_sha256);
    line("Language files: "+JSON.stringify(d.language_counts));
    for(const warning of d.warnings)line(warning,true);
    heading("Declared project manifests (inert)");
    for(const manifest of Object.values(d.manifests)){
      line(manifest.path+" · SHA-256 "+manifest.sha256+" · evaluated: "+manifest.evaluated);
    }
    heading("Source declarations");
    for(const file of d.files.slice(0,140)){
      line(file.language+" · "+file.path+" · "+file.sha256+
           (file.canonical_fixture?" · canonical fixture":""));
      if(file.symbols.length)line("Symbols: "+file.symbols.join(", "));
      for(const risk of file.risk_signals)
        line("Possible risk: "+file.path+":"+risk.line+" · "+risk.kind,true);
    }
    heading("Installed tools (not launched)");
    const select=el("dsLogicTool");
    select.replaceChildren(new Option("Choose installed interpreter",""));
    for(const tool of d.toolchains){
      line(tool.name+" · "+tool.status+(tool.sha256?" · "+tool.sha256:""));
      const option=new Option(tool.name+" · "+tool.status,tool.name);
      option.disabled=tool.status!=="installed_not_executed";
      select.add(option);
    }
    heading("Known limitations");line(d.limitations);
    line("Runtime used: "+d.source_executed+" · dependencies resolved: "+d.dependencies_resolved+
         " · network started: "+d.network_started+" · deployment: "+d.deployment_started);
  }
  async function inspect(){
    const p=project();if(!p||busy)return;
    const id=++seq;busy=true;controls();
    notice("Inspecting bounded source and manifest data.");
    try{
      const result=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==seq||project()!==p||!root.isConnected)return;
      data=result;render(result);
      notice("Inspection complete. Fixed actions require a trusted root and fresh consent.");
    }catch(error){
      data=null;out.replaceChildren();
      notice("Inspection refused: "+error.message,true);
    }finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),snapshot=data,task=el("dsLogicTask").value,tool=currentTool();
    if(!p||!snapshot||!tool||busy||!permitted())return;
    if(!window.confirm("Approve UNSANDBOXED "+task+" using "+tool.name+
      "? Even a fixed program can access files and the network with your user permissions. "+
      "This approval is for one fixed fixture, not package installation, publishing or deployment."))return;
    const id=++seq;busy=true;controls();notice("Executing separately approved fixed fixture.");
    try{
      const result=await api(base+"/run",{
        project:p,task,tool:tool.name,
        expected_inventory_sha256:snapshot.inventory_sha256,
        expected_toolchain_sha256:snapshot.toolchain_sha256,
        expected_executable:tool.executable,expected_sha256:tool.sha256,
        confirmed:true,accept_unsandboxed_execution_and_network_risk:true
      });
      if(id!==seq||project()!==p||!root.isConnected)return;
      out.replaceChildren();heading(task+" · "+result.status);
      line("Exit: "+result.exit_code+" · marker matched: "+result.fixture_marker_matched+
           " · tool SHA-256: "+result.tool_sha256);
      const pre=document.createElement("pre");
      pre.className="ds-php-output";pre.textContent=result.output||"(no output)";
      out.append(pre);
      notice("Approved fixture "+result.status+".",result.status!=="completed");
    }catch(error){notice("V31 operation refused: "+error.message,true);}
    finally{busy=false;controls();}
  }
  function agent(){
    const bridge=document.querySelector(".studio-agent-bridge");
    const action=bridge?.querySelector("#studioAgentAction");
    const message=bridge?.querySelector("#studioAgentMessage");
    if(!action||!message){notice("Shared Central Agent unavailable.",true);return;}
    action.value="deployment_readiness";
    message.value=("Review Developer Studio V31 Haskell, OCaml, Common Lisp, Scheme and Prolog: "+
      "inert manifests, SHA-256 provenance, ambiguous .pl classification, fixed interpreter fixtures, "+
      "unsandboxed host/network and supply-chain risk, Windows/macOS/Linux security CI, "+
      "real Ubuntu language acceptance, accessibility, backup and human sign-off. "+
      "REVIEW ONLY; no code execution, installation or deployment.").slice(0,2200);
    message.dispatchEvent(new Event("input",{bubbles:true}));
    bridge.scrollIntoView({block:"start",behavior:"smooth"});
    message.focus();notice("Central Agent review drafted; not submitted.");
  }
  el("dsLogicInspect").addEventListener("click",()=>void inspect());
  el("dsLogicRun").addEventListener("click",()=>void run());
  el("dsLogicAgent").addEventListener("click",agent);
  for(const id of ["dsLogicTask","dsLogicTool"])el(id).addEventListener("change",controls);
  reset();return {projectChanged:reset,fileChanged:controls};
}

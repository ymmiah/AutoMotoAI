/* AutoMoto AI Developer Studio V29: Scala, F# and Clojure tools. */
export function mountDeveloperFunctional({api,host,getProject,status}){
  const root=host.querySelector("#dsFunctionalRoot");
  const base="/api/developer/studio/functional";
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="Scala F sharp and Clojure enterprise language tools">'+
    '<div class="ds-php-head"><h3>Scala, F# &amp; Clojure · V29</h3>'+
    '<span class="ds-readonly">SOURCE PROVENANCE / EXPLICIT TOOL APPROVAL</span></div>'+
    '<div class="ds-php-body">'+
    '<p class="ds-footnote">Inspect Scala/sbt, F#/.NET and Clojure tools, file fingerprints and literal-looking dependency declarations without evaluating project scripts. Approved installed runtimes can run only fixed local fixture tests; no arbitrary flags or package install.</p>'+
    '<div class="ds-php-controls">'+
    '<button id="dsFunctionalInspect" type="button" class="btn sm" disabled>Inspect enterprise languages</button>'+
    '<label for="dsFunctionalTool">Installed interpreter</label>'+
    '<select id="dsFunctionalTool" class="input"><option value="scala">Scala</option><option value="dotnet">.NET / F#</option><option value="clojure">Clojure</option></select>'+
    '<label for="dsFunctionalTask">Fixed operation</label>'+
    '<select id="dsFunctionalTask" class="input"><option value="version">Installed tool version</option>'+
    '<option value="scala_test">Scala canonical fixture</option><option value="fsharp_test">F# canonical fixture</option>'+
    '<option value="clojure_test">Clojure canonical fixture</option></select>'+
    '<button id="dsFunctionalRun" type="button" class="btn sm primary" disabled>Review risk &amp; run</button>'+
    '<button id="dsFunctionalAgent" type="button" class="btn sm">Central Agent release review</button>'+
    '</div>'+
    '<p id="dsFunctionalStatus" role="status" aria-live="polite" class="ds-footnote">Open a local project to inspect.</p>'+
    '<div id="dsFunctionalResults" role="region" tabindex="0" class="ds-php-results" aria-label="Enterprise language source and runtime evidence"></div>'+
    '<p class="ds-footnote">IMPORTANT: Scala/F# macros, type providers, Clojure readers, build tasks and language runtimes may execute arbitrary host code. Temporary copies and SHA fingerprints are NOT an OS/network sandbox. Do not run untrusted code. ScalaCLI, sbt, Leiningen and package tools are discovery-only; arbitrary project builds, dependency downloads and publishing are not included.</p>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id),output=el("dsFunctionalResults");
  const project=()=>getProject()?.project||"";
  const names={scala_test:"scala",fsharp_test:"dotnet",clojure_test:"clojure"};
  const fixtures={scala_test:"test/Fixture.scala",fsharp_test:"test/Fixture.fsx",clojure_test:"test/fixture_test.clj"};
  let data=null,sequence=0,busy=false;
  function info(text,error=false){
    el("dsFunctionalStatus").textContent=text;
    el("dsFunctionalStatus").classList.toggle("ds-error",error);
  }
  function title(text){const h=document.createElement("h4");h.textContent=text;output.append(h);}
  function line(text,warning=false){
    const p=document.createElement("p");p.className="ds-php-line";
    p.textContent=String(text);if(warning)p.dataset.severity="warning";output.append(p);
  }
  function installed(){
    return data?.toolchains?.find(x=>x.name===el("dsFunctionalTool").value&&x.status==="installed_not_executed");
  }
  function allowed(){
    if(!data||!project()||!getProject()?.trusted||data.scan_incomplete||!installed()||busy)return false;
    const task=el("dsFunctionalTask").value,tool=el("dsFunctionalTool").value;
    if(task==="version")return true;
    return names[task]===tool&&data.files.some(f=>f.path===fixtures[task]&&f.canonical_fixture);
  }
  function controls(){
    el("dsFunctionalInspect").disabled=!project()||busy;
    el("dsFunctionalRun").disabled=!allowed();
  }
  function reset(){
    sequence++;data=null;busy=false;output.replaceChildren();
    info("Source inspection does not execute code or install dependencies.");
    controls();
  }
  function render(d){
    output.replaceChildren();
    title("Three-language project evidence");
    line("Inventory SHA-256: "+d.inventory_sha256);
    line("Toolchain SHA-256: "+d.toolchain_sha256);
    line("Source files: "+JSON.stringify(d.language_counts));
    for(const warning of d.warnings)line(warning,true);
    title("Manifest metadata — never evaluated");
    const manifests=Object.values(d.manifests||{});
    if(!manifests.length)line("No supported manifest present.");
    for(const entry of manifests)
      line(entry.path+" · "+entry.sha256+" · evaluated: "+entry.evaluated);
    for(const [name,values] of Object.entries(d.packages.coordinates||{}))
      line(name+" literal dependencies: "+(values.join(", ")||"none found"));
    title("Source symbols and risk indicators");
    for(const entry of d.files.slice(0,120)){
      line(entry.language+" · "+entry.path+" · "+entry.sha256+
           (entry.canonical_fixture?" · fixed fixture":""));
      if(entry.symbols.length)line("Declarations: "+entry.symbols.join(", "));
      for(const warning of entry.risk_signals)
        line("Heuristic risk · "+entry.path+":"+warning.line+" · "+warning.kind,true);
    }
    title("Installed local tools — no version probe during inspection");
    for(const tool of d.toolchains)
      line(tool.name+" · "+tool.status+(tool.sha256?" · "+tool.sha256:""));
    title("Execution and Agent boundaries");
    line(d.limitations);
    line("Source executed: "+d.source_executed+" · build scripts evaluated: "+
         d.build_scripts_evaluated+" · dependencies resolved: "+d.packages.dependencies_resolved+
         " · deployed: "+d.deployment_started);
  }
  async function inspect(){
    const p=project();if(!p||busy)return;
    const id=++sequence;busy=true;controls();info("Reading bounded enterprise language evidence.");
    try{
      const response=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==sequence||project()!==p||!root.isConnected)return;
      data=response;render(response);
      info("Inert project inventory ready. Tools require explicit consent.");
    }catch(error){data=null;output.replaceChildren();info("Inspection refused: "+error.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),snapshot=data,task=el("dsFunctionalTask").value,tool=installed();
    if(!p||!snapshot||!tool||!allowed())return;
    if(!window.confirm("Approve UNSANDBOXED "+task+" with "+tool.name+"? "+
      "This runs external local code with host filesystem and network access. "+
      "Only independently reviewed sources should execute. No OS sandbox, dependency installation or deployment is provided."))return;
    const id=++sequence;busy=true;controls();info("Executing explicitly approved fixed task.");
    try{
      const result=await api(base+"/run",{project:p,task,tool:tool.name,
        expected_inventory_sha256:snapshot.inventory_sha256,
        expected_toolchain_sha256:snapshot.toolchain_sha256,
        expected_executable:tool.executable,expected_sha256:tool.sha256,
        confirmed:true,accept_unsandboxed_code_and_network_risk:true});
      if(id!==sequence||project()!==p||!root.isConnected)return;
      output.replaceChildren();title(task+" · "+result.status);
      line("Exit: "+result.exit_code+" · SHA pinned: "+result.tool_sha256+
           " · temporary copy deleted: "+result.temporary_copy_deleted);
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=result.output||"(no output)";output.append(pre);
      info("Approved fixed task "+result.status+".",result.status!=="completed");
    }catch(error){info("Task refused: "+error.message,true);}
    finally{busy=false;controls();}
  }
  function agent(){
    const shared=document.querySelector(".studio-agent-bridge");
    const action=shared?.querySelector("#studioAgentAction");
    const message=shared?.querySelector("#studioAgentMessage");
    if(!action||!message){info("Central Agent review bridge unavailable.",true);return;}
    action.value="deployment_readiness";
    message.value=("Review Developer Studio V29 Scala, F# and Clojure readiness: "+
      "SHA-pinned source manifests and executable provenance; literal-only sbt, F# .fsproj and "+
      "deps.edn metadata; real Scala/F#/Clojure fixed fixture acceptance; Scala CLI and "+
      "Clojure package loading limitations; local trust and per-task approval; "+
      "unsandboxed execution risks; Windows/macOS/Linux tests, accessibility, "+
      "rollback and human sign-off. REVIEW ONLY — do not install, execute arbitrary tasks "+
      "or deploy anything.").slice(0,2200);
    message.dispatchEvent(new Event("input",{bubbles:true}));
    shared.scrollIntoView({block:"start",behavior:"smooth"});message.focus();
    info("Central Agent draft prepared only; no action submitted.");
  }
  el("dsFunctionalInspect").onclick=()=>void inspect();
  el("dsFunctionalRun").onclick=()=>void run();
  el("dsFunctionalAgent").onclick=agent;
  for(const name of ["dsFunctionalTask","dsFunctionalTool"])
    el(name).addEventListener("change",controls);
  reset();
  return {projectChanged:reset,fileChanged:controls};
}

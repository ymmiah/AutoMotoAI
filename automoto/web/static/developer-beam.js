/* AutoMoto AI Developer Studio V30: BEAM language provenance and approved tools. */
export function mountDeveloperBeam({api,host,getProject,status}){
  const root=host.querySelector("#dsBeamRoot");
  const base="/api/developer/studio/beam";
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="Elixir Erlang and Gleam development tools">'+
    '<div class="ds-php-head"><h3>Elixir, Erlang &amp; Gleam · V30</h3>'+
    '<span class="ds-readonly">SOURCE AND BEAM PROVENANCE / APPROVED FIXTURES</span></div>'+
    '<div class="ds-php-body">'+
    '<p class="ds-footnote">Inspect BEAM source, Mix, Rebar and Gleam manifests, installed tool fingerprints and risk indicators without compiling, running macros or fetching dependencies. Approved fixture actions use fixed commands in a temporary project copy.</p>'+
    '<div class="ds-php-controls">'+
    '<button id="dsBeamInspect" class="btn sm" type="button" disabled>Inspect BEAM project</button>'+
    '<label for="dsBeamTask">Fixed action</label>'+
    '<select class="input" id="dsBeamTask">'+
    '<option value="version">Installed tool version</option>'+
    '<option value="elixir_test">Elixir fixed fixture</option>'+
    '<option value="erlang_test">Erlang escript fixed fixture</option>'+
    '<option value="gleam_test">Gleam dependency-free fixed project</option>'+
    '</select>'+
    '<label for="dsBeamTool">SHA-pinned installed tool</label>'+
    '<select id="dsBeamTool" class="input"><option value="">Inspect first</option></select>'+
    '<button class="btn sm primary" id="dsBeamRun" type="button" disabled>Review risk &amp; run</button>'+
    '<button class="btn sm" id="dsBeamAgent" type="button">Central Agent review</button>'+
    '</div>'+
    '<p id="dsBeamStatus" class="ds-footnote" role="status" aria-live="polite">Open a local project to begin.</p>'+
    '<div id="dsBeamResults" class="ds-php-results" role="region" tabindex="0" aria-label="BEAM source fingerprints package metadata and tool results"></div>'+
    '<p class="ds-footnote">External interpreters are NOT sandboxed. Mix/Rebar metadata can run macros, build hooks and arbitrary code if evaluated; Gleam compilation may access the network or start processes. Only approved fixed fixtures are admitted here, and they still run with the local user permissions. No automatic publishing, package installation, cloud execution or production deployment.</p>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id),output=el("dsBeamResults");
  const project=()=>getProject()?.project||"";
  const fixed={elixir_test:"elixir",erlang_test:"escript",gleam_test:"gleam"};
  const fixture={elixir_test:"test/v30_fixture.exs",erlang_test:"test/v30_fixture.escript",
                 gleam_test:"src/v30_fixture.gleam"};
  let data=null,seq=0,busy=false;
  function info(text,bad=false){
    el("dsBeamStatus").textContent=text;el("dsBeamStatus").classList.toggle("ds-error",bad);
  }
  function heading(label){const h=document.createElement("h4");h.textContent=label;output.append(h);}
  function line(label,bad=false){
    const p=document.createElement("p");p.className="ds-php-line";
    p.textContent=String(label);if(bad)p.dataset.severity="warning";output.append(p);
  }
  function tool(){
    return data?.toolchains?.find(x=>x.name===el("dsBeamTool").value&&
                                      x.status==="installed_not_executed");
  }
  function permitted(){
    if(!data||!project()||!getProject()?.trusted||data.scan_incomplete||busy||!tool())return false;
    const task=el("dsBeamTask").value;
    if(task==="version")return ["elixir","erl","gleam"].includes(tool().name);
    if(fixed[task]!==tool().name)return false;
    if(!data.files.some(x=>x.path===fixture[task]&&x.canonical_fixture))return false;
    if(task==="gleam_test"&&!data.manifests["gleam.toml"])return false;
    return true;
  }
  function controls(){
    el("dsBeamInspect").disabled=!project()||busy;
    el("dsBeamRun").disabled=!permitted();
  }
  function reset(){
    seq++;data=null;busy=false;output.replaceChildren();
    el("dsBeamTool").replaceChildren(new Option("Inspect first",""));
    info("Inspection never executes Mix, Rebar, Gleam, source code or package installers.");
    controls();
  }
  function render(d){
    output.replaceChildren();
    heading("BEAM inventory fingerprints");
    line("Inventory SHA-256: "+d.inventory_sha256);
    line("Installed tool inventory SHA-256: "+d.toolchain_sha256);
    line("Language files: "+JSON.stringify(d.language_counts));
    for(const warning of d.warnings)line(warning,true);
    heading("Manifest metadata (parsed, not executed)");
    const manifests=Object.values(d.manifests);
    if(!manifests.length)line("No BEAM manifest found.");
    for(const m of manifests)line(m.path+" · SHA-256 "+m.sha256+" · evaluated: "+m.evaluated);
    for(const [language,coordinates] of Object.entries(d.packages.coordinates||{}))
      line(language+" literal dependencies: "+(coordinates.length?JSON.stringify(coordinates):"none"));
    line("Dependencies resolved: "+d.packages.dependencies_resolved+
         " · manifest execution: "+d.manifest_evaluated+
         " · installation: "+d.dependency_installed);
    heading("Source fingerprints and heuristic warnings");
    for(const file of d.files.slice(0,130)){
      line(file.language+" · "+file.path+" · "+file.sha256+
           (file.canonical_fixture?" · canonical fixture":""));
      if(file.symbols.length)line("Declarations: "+file.symbols.join(", "));
      for(const risk of file.risk_signals)
        line("Potential risk · "+file.path+":"+risk.line+" · "+risk.kind,true);
    }
    heading("Available tools (not executed during inspection)");
    const select=el("dsBeamTool");
    select.replaceChildren(new Option("Choose approved installed tool",""));
    for(const t of d.toolchains){
      line(t.name+" · "+t.status+(t.sha256?" · "+t.sha256:""));
      const option=new Option(t.name+" · "+t.status,t.name);
      option.disabled=t.status!=="installed_not_executed";
      select.add(option);
    }
    heading("Safety and Agent readiness");
    line(d.limitations);
    line("Code executed: "+d.source_executed+" · network started: "+d.network_started+
         " · deployed: "+d.deployment_started);
  }
  async function inspect(){
    const p=project();if(!p||busy)return;
    const id=++seq;busy=true;controls();info("Inspecting BEAM sources and manifests without executing.");
    try{
      const result=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==seq||project()!==p||!root.isConnected)return;
      data=result;render(result);info("BEAM inventory complete. Fixed operations require trust and consent.");
    }catch(error){data=null;output.replaceChildren();info("Inspection refused: "+error.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),snap=data,task=el("dsBeamTask").value,selected=tool();
    if(!p||!snap||!selected||busy||!permitted())return;
    const risk="Approve UNSANDBOXED "+task+" using "+selected.name+
      "? External BEAM programs, even fixed fixtures, can access host files and the network. "+
      "There is no OS isolation and implicit dependency fetching cannot be excluded. "+
      "Use independently reviewed local source only; this does not authorise publishing or deployment.";
    if(!window.confirm(risk))return;
    const id=++seq;busy=true;controls();info("Executing approved local BEAM fixture.");
    try{
      const result=await api(base+"/run",{
        project:p,task,tool:selected.name,
        expected_inventory_sha256:snap.inventory_sha256,
        expected_toolchain_sha256:snap.toolchain_sha256,
        expected_executable:selected.executable,expected_sha256:selected.sha256,
        confirmed:true,accept_unsandboxed_beam_and_network_risk:true
      });
      if(id!==seq||project()!==p||!root.isConnected)return;
      output.replaceChildren();heading(task+" · "+result.status);
      line("Exit: "+result.exit_code+" · temporary copy deleted: "+result.temporary_copy_deleted+
           " · tool SHA-256: "+result.tool_sha256);
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=result.output||"(no output)";output.append(pre);
      info("Approved task "+result.status+".",result.status!=="completed");
    }catch(error){info("BEAM operation refused: "+error.message,true);}
    finally{busy=false;controls();}
  }
  function agent(){
    const shared=document.querySelector(".studio-agent-bridge");
    const action=shared?.querySelector("#studioAgentAction");
    const message=shared?.querySelector("#studioAgentMessage");
    if(!action||!message){info("Central AutoMoto Agent bridge unavailable.",true);return;}
    action.value="deployment_readiness";
    message.value=("Review Developer Studio V30 Elixir, Erlang and Gleam: "+
      "non-evaluating Mix/Rebar/Gleam manifest inventory and SHA-pinned source/toolchain evidence; "+
      "real elixir, escript and gleam fixture acceptance; dependency and macro execution risks; "+
      "project trust and per-run approval; three-OS security, browser and Windows packaging CI; "+
      "accessibility, rollback and human release sign-off. REVIEW-ONLY; do not execute "+
      "code, install packages, publish or deploy autonomously.").slice(0,2200);
    message.dispatchEvent(new Event("input",{bubbles:true}));
    shared.scrollIntoView({block:"start",behavior:"smooth"});message.focus();
    info("Central Agent release review drafted only; no action submitted.");
  }
  el("dsBeamInspect").onclick=()=>void inspect();
  el("dsBeamRun").onclick=()=>void run();
  el("dsBeamAgent").onclick=agent;
  for(const id of ["dsBeamTask","dsBeamTool"])el(id).addEventListener("change",controls);
  reset();
  return {projectChanged:reset,fileChanged:controls};
}

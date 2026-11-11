/* Developer Studio V18 — Go services, gopls and consented local tools. */
export function mountDeveloperGo({api,host,getProject,status}) {
  const base="/api/developer/studio/go", root=host.querySelector("#dsGoRoot");
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="Go modules, service projects and explicit tools">'+
    '<div class="ds-php-head"><h3>Go Engineering · V18</h3><span class="ds-readonly">SAFE INSPECTION / APPROVED RUNS</span></div>'+
    '<div class="ds-php-body">'+
    '<p class="ds-footnote">Inspect local go.mod, go.work, go.sum, package/function outlines and HTTP/gRPC hints without running code. gopls is available separately through the approved Language Server panel. Analysis is heuristic, not a compiled program or a vulnerability audit.</p>'+
    '<div class="ds-php-controls">'+
      '<button class="btn sm" id="dsGoInspect" type="button" disabled>Inspect Go workspace</button>'+
      '<button class="btn sm" id="dsGoLsp" type="button">Go language server controls</button>'+
      '<label for="dsGoTask">Task</label>'+
      '<select class="input" id="dsGoTask">'+
        '<option value="version">Installed Go version</option>'+
        '<option value="gopls_version">Installed gopls version</option>'+
        '<option value="build">Build all approved packages</option>'+
        '<option value="test">Test all approved packages</option>'+
        '<option value="vet">Go vet diagnostics</option>'+
        '<option value="profile">Profile selected tested package</option>'+
      '</select>'+
      '<label for="dsGoTool">Approved tool</label>'+
      '<select class="input" id="dsGoTool" disabled><option value="">Inspect first</option></select>'+
      '<label for="dsGoPackage">Profile package</label>'+
      '<select class="input" id="dsGoPackage" disabled><option value="">Select a tested package</option></select>'+
      '<button class="btn sm primary" id="dsGoRun" type="button" disabled>Review risks & run</button>'+
      '<button class="btn sm" id="dsGoAgent" type="button">Central Agent release review</button>'+
    '</div>'+
    '<p class="ds-footnote" id="dsGoStatus" role="status" aria-live="polite">Open a project to inspect Go sources.</p>'+
    '<div class="ds-php-results" id="dsGoResults" role="region" aria-label="Go project findings and task output" tabindex="0"></div>'+
    '<p class="ds-footnote">Go test/profile executes project code as your current OS user. Go builds and language tooling can process untrusted source and dependencies. These processes are not OS- or network-sandboxed. Go modules are offline/read-only for tool execution (GOPROXY=off, GOTOOLCHAIN=local, -mod=readonly). File immutability is not guaranteed. The shared Agent only prepares a separately approved release review, not deployment.</p>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const project=()=>getProject()?.project||"";
  const output=el("dsGoResults");
  let snapshot=null,busy=false,seq=0;
  function message(t,bad=false){
    el("dsGoStatus").textContent=t;
    el("dsGoStatus").classList.toggle("ds-error",bad);
  }
  function clear(){output.replaceChildren();}
  function line(t,warn=false){
    const p=document.createElement("p");
    p.className="ds-php-line";
    if(warn)p.dataset.severity="warning";
    p.textContent=String(t);
    output.append(p);
  }
  function heading(t){const h=document.createElement("h4");h.textContent=t;output.append(h);}
  function tool(){return snapshot?.toolchains?.find(x=>x.name===el("dsGoTool").value && x.status==="installed_not_executed");}
  function taskOK(){
    const t=el("dsGoTask").value, selected=tool()?.name;
    if(t==="version")return selected==="go";
    if(t==="gopls_version")return selected==="gopls";
    if(t==="profile")return selected==="go" && !!el("dsGoPackage").value && !!snapshot?.safe_to_offer_runs;
    return selected==="go" && !!snapshot?.safe_to_offer_runs;
  }
  function controls(){
    const ready=!!project()&&!busy;
    el("dsGoInspect").disabled=!ready;
    el("dsGoTool").disabled=!ready||!snapshot;
    el("dsGoPackage").disabled=!ready||!snapshot||el("dsGoTask").value!=="profile";
    el("dsGoRun").disabled=!ready||!snapshot||!getProject()?.trusted||!taskOK();
  }
  function reset(){
    ++seq;busy=false;snapshot=null;clear();
    el("dsGoTool").replaceChildren(new Option("Inspect first",""));
    el("dsGoPackage").replaceChildren(new Option("Select a tested package",""));
    message("Select an approved local workspace. No Go tools run automatically.");
    controls();
  }
  function present(data){
    clear();heading("Go modules and workspace");
    line("Manifest SHA-256: "+data.manifest_sha256);
    line("Go source SHA-256: "+data.source_sha256);
    line(data.workspace?"go.work detected · modules: "+data.workspace_modules.join(", "):
      "Single-module discovery (go.work not present).");
    for(const m of data.modules)line(m.path+" · "+(m.module||"invalid module declaration")+
      " · Go "+(m.go||"unspecified"));
    for(const [name,meta] of Object.entries(data.manifests))
      line(name+" · SHA-256 "+meta.sha256);
    for(const warn of data.warnings||[])line("Review required: "+warn,true);
    if(!data.safe_to_offer_runs)line("Build/test/vet/profile disabled until Go workspace checks pass.",true);
    heading("Discovered source packages and services");
    line(data.sources.length+" Go source/test files inspected"+(data.scan_incomplete?" (bounded scan)":""));
    for(const pkg of data.packages){
      line(pkg.path+" · package "+(pkg.package||"undetermined")+
        " · "+pkg.files+" source(s), "+pkg.tests+" test file(s)");
      if(pkg.functions.length)line("Symbols: "+pkg.functions.slice(0,15).join(", "));
      if(pkg.service_hints.length)line("Service imports: "+pkg.service_hints.join(", ")+
        " (lexical evidence only)");
    }
    heading("System Go tools — no process launched");
    const select=el("dsGoTool");select.replaceChildren(new Option("Choose installed tool",""));
    for(const item of data.toolchains){
      line(item.name+" · "+item.status+(item.sha256?" · SHA-256 "+item.sha256:""));
      const opt=new Option(item.name+" · "+item.status,item.name);
      opt.disabled=item.status!=="installed_not_executed";select.add(opt);
    }
    const choice=el("dsGoPackage");
    choice.replaceChildren(new Option("Select a tested package",""));
    for(const pkg of data.packages.filter(x=>x.tests>0))
      choice.add(new Option(pkg.path+" · "+pkg.tests+" test file(s)",pkg.path));
  }
  async function inspect(){
    const p=project();if(!p||busy)return;
    const id=++seq;busy=true;controls();
    message("Inspecting local Go manifest/source fingerprints without running tools.");
    try{
      const data=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==seq||p!==project()||!root.isConnected)return;
      snapshot=data;present(data);
      message("Go project inspected. Choose one approved task for any execution.");
    }catch(e){snapshot=null;clear();message("Go inspection refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),picked=tool(),snap=snapshot,t=el("dsGoTask").value;
    if(!p||!picked||!snap||busy||!getProject()?.trusted||!taskOK())return;
    if(!window.confirm("Approve real UNSANDBOXED "+picked.name+" task '"+t+"' in this trusted workspace? "+
      "Go test/profiling executes arbitrary project/dependency code and may access private files, the network "+
      "and modify your project. Go tools have bounded time/output and use offline module resolution, "+
      "but there is no OS sandbox, no verified rollback and no automatic release approval."))return;
    const id=++seq;busy=true;controls();message("Running one SHA-pinned Go task with bounded execution.");
    try{
      const data=await api(base+"/run",{
        project:p,task:t,tool:picked.name,
        package:t==="profile"?el("dsGoPackage").value:null,
        expected_manifest_sha256:snap.manifest_sha256,
        expected_source_sha256:snap.source_sha256,
        expected_executable:picked.executable,expected_sha256:picked.sha256,
        confirmed:true,accept_unsandboxed_execution_and_write_risk:true
      });
      if(id!==seq||p!==project()||!root.isConnected)return;
      clear();heading("Go "+t+" · "+data.status);
      line("Exit "+data.exit_code+" · "+data.elapsed_ms+" ms · "+picked.name);
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=data.output||"(no output)";output.append(pre);
      if(data.profile?.requested){
        if(data.profile.sha256)line("Ephemeral CPU profile SHA-256: "+data.profile.sha256+
          " · "+data.profile.size_bytes+" bytes; raw file deleted.");
        if(data.profile.top){
          heading("pprof top functions · local temporary analysis");
          const report=document.createElement("pre");report.className="ds-php-output";
          report.textContent=data.profile.top;output.append(report);
        }else line("Profiling summary unavailable; no profile is retained.",true);
      }
      if(data.timed_out||data.output_truncated)line("Task exceeded time/output limit.",true);
      line("Project file immutability not verified; review source and test results before release.",true);
      message("Go task "+data.status+".",data.status!=="completed");
    }catch(e){message("Go task refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function agent(){
    const panel=document.querySelector(".studio-agent-bridge"),
      action=panel?.querySelector("#studioAgentAction"),
      field=panel?.querySelector("#studioAgentMessage");
    if(!action||!field){
      message("Shared central Agent panel is unavailable; release review cannot be prepared.",true);
      return;
    }
    action.value="deployment_readiness";
    field.value=("Review Developer Studio V18 Go service release readiness: verify go.work/module integrity, "+
      "no unreviewed module replace directives, offline reproducibility, gopls and build/test/vet results, "+
      "profiling evidence, source checksums, OS security, human QA, rollback and explicit manual approval. "+
      "No automated publishing, deployment or credential sharing.").slice(0,2200);
    field.dispatchEvent(new Event("input",{bubbles:true}));
    panel.scrollIntoView({block:"start",behavior:"smooth"});field.focus();
    message("Shared central Agent release-review form prepared; submit separately.");
  }
  el("dsGoInspect").onclick=()=>void inspect();
  el("dsGoRun").onclick=()=>void run();
  el("dsGoAgent").onclick=agent;
  el("dsGoLsp").onclick=()=>{
    const target=host.querySelector("#dsLspRoot");
    if(target){target.scrollIntoView({block:"start",behavior:"smooth"});
      message("Go gopls is controlled by the existing approved LSP panel; separate consent is required.");}
  };
  for(const name of ["dsGoTask","dsGoTool","dsGoPackage"])
    el(name).addEventListener("change",controls);
  reset();
  return {projectChanged:reset,fileChanged:()=>controls()};
}

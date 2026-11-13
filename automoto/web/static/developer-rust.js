/* V19 Rust: multi-crate Cargo checks and one shared Agent review boundary. */
export function mountDeveloperRust({api,host,getProject,status}) {
  const base="/api/developer/studio/rust",root=host.querySelector("#dsRustRoot");
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="Rust workspaces, Cargo, Clippy and approved debugging">'+
      '<div class="ds-php-head"><h3>Rust Engineering · V19</h3>'+
      '<span class="ds-readonly">INERT INSPECTION / OPT-IN TOOL EXECUTION</span></div>'+
      '<div class="ds-php-body">'+
        '<p class="ds-footnote">Inspect explicit Cargo workspace members, source symbols, lockfile integrity, rustc, rust-analyzer and local debug-adapter availability without executing project code. Use the existing LSP and adapter controls for Go/Rust editing and debugging; no second debugger or Agent is created here.</p>'+
        '<div class="ds-php-controls">'+
          '<button class="btn sm" id="dsRsInspect" type="button" disabled>Inspect Rust workspace</button>'+
          '<button class="btn sm" id="dsRsLsp" type="button">Rust language server</button>'+
          '<button class="btn sm" id="dsRsDap" type="button">Native debug adapters</button>'+
          '<label for="dsRsTask">Approved task</label>'+
          '<select class="input" id="dsRsTask">'+
            '<option value="cargo_version">Cargo version</option>'+
            '<option value="rustc_version">rustc version</option>'+
            '<option value="analyzer_version">rust-analyzer version</option>'+
            '<option value="check">Cargo check & compiler diagnostics</option>'+
            '<option value="build">Cargo build (temporary outputs)</option>'+
            '<option value="test">Cargo workspace tests</option>'+
            '<option value="clippy">Clippy warnings as errors</option>'+
            '<option value="fmt_check">rustfmt check, no rewrites</option>'+
          '</select>'+
          '<label for="dsRsTool">SHA-256 verified tool</label>'+
          '<select class="input" id="dsRsTool" disabled><option value="">Inspect first</option></select>'+
          '<button class="btn sm primary" id="dsRsRun" type="button" disabled>Review risks & run</button>'+
          '<button class="btn sm" id="dsRsAgent" type="button">Central Agent release review</button>'+
        '</div>'+
        '<p class="ds-footnote" role="status" aria-live="polite" id="dsRsStatus">Open a local workspace to inspect Rust source.</p>'+
        '<div class="ds-php-results" id="dsRsResults" role="region" tabindex="0" aria-label="Rust packages and diagnostic output"></div>'+
        '<p class="ds-footnote">Cargo tools and tests may execute untrusted build scripts and project code as your local OS user. Temporary build output, offline Cargo settings, SHA verification and explicit trust are NOT an OS or network sandbox. Project changes and network access from executable code are not prevented or certified. No package installation or automatic deployment is provided.</p>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const project=()=>getProject()?.project||"";
  const output=el("dsRsResults");
  let snapshot=null,busy=false,sequence=0;
  function message(text,error=false){
    el("dsRsStatus").textContent=text;
    el("dsRsStatus").classList.toggle("ds-error",error);
  }
  function clear(){output.replaceChildren();}
  function add(text,warn=false){
    const line=document.createElement("p");
    line.className="ds-php-line";line.textContent=String(text);
    if(warn)line.dataset.severity="warning";
    output.append(line);
  }
  function heading(text){const n=document.createElement("h4");n.textContent=text;output.append(n);}
  const selected=()=>snapshot?.toolchains?.find(x=>x.name===el("dsRsTool").value&&x.status==="installed_not_executed");
  function ready(){
    const task=el("dsRsTask").value,name=selected()?.name;
    if(task==="cargo_version")return name==="cargo";
    if(task==="rustc_version")return name==="rustc";
    if(task==="analyzer_version")return name==="rust-analyzer";
    return name==="cargo"&&!!snapshot?.safe_to_offer_runs;
  }
  function controls(){
    const active=!!project()&&!busy;
    el("dsRsInspect").disabled=!active;
    el("dsRsTool").disabled=!active||!snapshot;
    el("dsRsRun").disabled=!active||!snapshot||!getProject()?.trusted||!ready();
  }
  function reset(){
    sequence++;busy=false;snapshot=null;clear();
    el("dsRsTool").replaceChildren(new Option("Inspect project first",""));
    message("Inspect a local Rust project. No toolchain is executed automatically.");
    controls();
  }
  function show(data){
    clear();heading("Cargo workspace integrity");
    add("Workspace: "+(data.workspace?"explicit multi-crate":"single crate")+
      " · "+data.crates.length+" crate(s)");
    add("Manifest SHA-256: "+data.manifest_sha256);
    add("Source SHA-256: "+data.source_sha256);
    for(const member of data.crates)add(member.name+" "+member.version+
      " · edition "+member.edition+" · "+member.path);
    for(const [name,value] of Object.entries(data.manifests))add(
      name+" · SHA-256 "+value.sha256);
    for(const warning of data.warnings||[])add("Review required: "+warning,true);
    if(!data.safe_to_offer_runs)add("Compilation and tests refused until review blockers are resolved.",true);
    heading("Source symbols (lexical, not semantic)");
    add(data.files.length+" Rust source files inspected"+(data.scan_incomplete?" · bounded scan":""));
    for(const symbol of data.symbols.slice(0,35))
      add(symbol.kind+" "+symbol.name+" · "+symbol.path);
    heading("Installed Rust tools — not executed");
    const select=el("dsRsTool");select.replaceChildren(new Option("Choose an approved tool",""));
    for(const tool of data.toolchains){
      add(tool.name+" · "+tool.status+(tool.sha256?" · "+tool.sha256:""));
      const option=new Option(tool.name+" · "+tool.status,tool.name);
      option.disabled=tool.status!=="installed_not_executed";select.add(option);
    }
    heading("Native debugger adapters — V8 separate approval");
    for(const tool of data.debug_adapters)add(tool.name+" · "+tool.status);
    add("rust-analyzer LSP is in the shared LSP controls. No LSP/debugger was started.");
  }
  async function inspect(){
    const p=project();if(!p||busy)return;
    const id=++sequence;busy=true;controls();
    message("Reading bounded local Cargo manifests and source checksums.");
    try{
      const data=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==sequence||p!==project()||!root.isConnected)return;
      snapshot=data;show(data);
      message("Rust workspace inspection completed without execution.");
    }catch(error){snapshot=null;clear();message("Rust inspection rejected: "+error.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),data=snapshot,tool=selected(),task=el("dsRsTask").value;
    if(!p||!data||!tool||busy||!getProject()?.trusted||!ready())return;
    if(!window.confirm("Approve UNSANDBOXED "+tool.name+" task "+task+"? "+
      "Cargo builds and tests may execute project/dependency code, read files, write sources or "+
      "access the network. We use an isolated temporary Cargo output and offline settings, "+
      "but this is NOT OS/network isolation. No automatic release, install, deployment or rollback."))return;
    const id=++sequence;busy=true;controls();message("Running exactly one approved Rust command.");
    try{
      const result=await api(base+"/run",{
        project:p,task,tool:tool.name,
        expected_manifest_sha256:data.manifest_sha256,
        expected_source_sha256:data.source_sha256,
        expected_executable:tool.executable,expected_sha256:tool.sha256,
        confirmed:true,accept_unsandboxed_execution_and_write_risk:true
      });
      if(id!==sequence||p!==project()||!root.isConnected)return;
      clear();heading("Rust "+task+" · "+result.status);
      add("Exit "+result.exit_code+" · "+result.elapsed_ms+" ms");
      for(const issue of result.diagnostics||[])
        add((issue.path||"Untrusted output path")+":"+issue.line+":"+issue.column+
          " · "+issue.severity+(issue.code?" "+issue.code:"")+" · "+issue.message,true);
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=result.output||"(no output)";output.append(pre);
      if(result.timed_out||result.output_truncated)add("Run hit its time/output limit.",true);
      add("Build output deleted from temporary directory; source files were not certified unchanged.",true);
      message("Rust tool "+result.status+".",result.status!=="completed");
    }catch(error){message("Rust execution refused: "+error.message,true);}
    finally{busy=false;controls();}
  }
  function linkPanel(selector,label){
    const target=host.querySelector(selector);
    if(!target){message(label+" panel is unavailable.",true);return;}
    target.scrollIntoView({block:"start",behavior:"smooth"});
    message("Open "+label+" and approve its separate trusted project workflow.");
  }
  function agent(){
    const panel=document.querySelector(".studio-agent-bridge"),
      action=panel?.querySelector("#studioAgentAction"),
      field=panel?.querySelector("#studioAgentMessage");
    if(!action||!field){message("Central Agent bridge unavailable; review not prepared.",true);return;}
    action.value="deployment_readiness";
    field.value=("Review Developer Studio V19 Rust workspace release readiness: Cargo.lock provenance, "+
      "explicit crate membership, rustc/Cargo checks, test coverage, Clippy, formatting, "+
      "rust-analyzer and debugger admission, build scripts, offline dependencies, security, "+
      "CI and rollback. Review only; no automatic build, publishing or deployment.").slice(0,2200);
    field.dispatchEvent(new Event("input",{bubbles:true}));
    panel.scrollIntoView({block:"start",behavior:"smooth"});field.focus();
    message("Shared Agent release-review form prepared; separate confirmation is required.");
  }
  el("dsRsInspect").onclick=()=>void inspect();
  el("dsRsRun").onclick=()=>void run();
  el("dsRsAgent").onclick=agent;
  el("dsRsLsp").onclick=()=>linkPanel("#dsLspRoot","rust-analyzer");
  el("dsRsDap").onclick=()=>linkPanel("#dsAdaptersRoot","DAP debugger");
  for(const name of ["dsRsTool","dsRsTask"])el(name).addEventListener("change",controls);
  reset();
  return {projectChanged:reset,fileChanged:()=>controls()};
}

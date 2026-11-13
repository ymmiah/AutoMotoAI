/* Developer Studio V17: Python projects, uv, ty, Ruff and consented venv tests. */
export function mountDeveloperPython({api,host,getProject,status}) {
  const base="/api/developer/studio/python",root=host.querySelector("#dsPythonRoot");
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="Python project engineering">'+
      '<div class="ds-php-head"><h3>Python Engineering · V17</h3><span class="ds-readonly">READ-ONLY INSPECTION / CONSENTED RUNS</span></div>'+
      '<div class="ds-php-body">'+
        '<p class="ds-footnote">Inspect Python packaging, uv/Poetry/PDM lockfiles, dependency declarations, Django/Flask/FastAPI markers, venv metadata and local tools. Inspection and AST checks do not execute code or install dependencies. Installed versions and compatibility require separate verification.</p>'+
        '<div class="ds-php-controls">'+
          '<button class="btn sm" id="dsPyInspect" type="button" disabled>Inspect Python project</button>'+
          '<label for="dsPySource">Python source</label>'+
          '<input class="input" id="dsPySource" placeholder="src/app.py" maxlength="1024" spellcheck="false">'+
          '<button class="btn sm" id="dsPySyntax" type="button" disabled>AST syntax check</button>'+
        '</div>'+
        '<div class="ds-php-controls">'+
          '<label for="dsPyTask">Approved task</label>'+
          '<select class="input" id="dsPyTask">'+
            '<option value="version">Installed tool version</option>'+
            '<option value="pytest">Run local venv Pytest</option>'+
            '<option value="ty_check">ty type checking</option>'+
            '<option value="ruff_check">Ruff lint</option>'+
          '</select>'+
          '<label for="dsPyTool">SHA-256-pinned tool</label>'+
          '<select class="input" id="dsPyTool"><option value="">Inspect project first</option></select>'+
          '<button class="btn sm primary" id="dsPyRun" type="button" disabled>Review risks & run</button>'+
          '<button class="btn sm" id="dsPyAgent" type="button">Central Agent release review</button>'+
        '</div>'+
        '<p class="ds-footnote" role="status" aria-live="polite" id="dsPyStatus">Choose a project to inspect.</p>'+
        '<div class="ds-php-results" role="region" aria-label="Python project results" tabindex="0" id="dsPyResults"></div>'+
        '<p class="ds-footnote">Only explicitly trusted local roots can run tools. Tests require an existing copied, non-symlinked .venv Python interpreter; no environment is created or changed automatically. Tests, linters, and type checkers run unsandboxed as your local user and may access the network or modify files. Existing Pyright LSP is available in the separate LSP panel. The same central Agent receives optional review requests; it does not deploy without separate authorisation.</p>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const project=()=>getProject()?.project||"";
  let snapshot=null,busy=false,sequence=0;
  const result=el("dsPyResults");
  function message(text,bad=false){el("dsPyStatus").textContent=text;el("dsPyStatus").classList.toggle("ds-error",bad);}
  function add(text,kind="info"){
    const line=document.createElement("p");line.className="ds-php-line";line.textContent=String(text);
    if(kind==="warning")line.dataset.severity="warning";result.append(line);
  }
  function heading(text){const h=document.createElement("h4");h.textContent=text;result.append(h);}
  function clear(){result.replaceChildren();}
  function chosen(){return snapshot?.toolchains?.find(x=>x.name===el("dsPyTool").value&&x.status==="installed_not_executed");}
  function taskReady(){
    const t=el("dsPyTask").value,tool=chosen()?.name;
    return t==="version"?!!tool:t==="pytest"?tool==="venv_python":
      t==="ty_check"?tool==="ty":tool==="ruff";
  }
  function controls(){
    const ready=!!project()&&!busy;
    el("dsPyInspect").disabled=!ready;
    el("dsPySource").disabled=!ready;
    el("dsPySyntax").disabled=!ready||!snapshot||!el("dsPySource").value.trim();
    el("dsPyTool").disabled=!ready||!snapshot;
    el("dsPyRun").disabled=!ready||!snapshot||!getProject()?.trusted||!taskReady();
  }
  function reset(){
    ++sequence;busy=false;snapshot=null;clear();
    el("dsPySource").value="";
    el("dsPyTool").replaceChildren(new Option("Inspect project first",""));
    message("Inspect a project to see Python and emerging tooling; no commands run automatically.");
    controls();
  }
  function render(data){
    clear();heading("Packaging, dependencies and environments");
    add("Manifest SHA-256: "+data.manifest_sha256);
    add("Project: "+(data.name||"(unnamed)")+" · Python requirement: "+(data.requires_python||"not declared"));
    add("Build backend: "+(data.build_backend||"not declared"));
    add(data.dependency_count+" dependency declarations inspected; installed versions are not verified.");
    add("Detected package metadata: "+(data.managers_detected.join(", ")||"none"));
    add("Virtual environment: "+data.virtual_environment.status+
      (data.virtual_environment.version_declared?" · Python "+data.virtual_environment.version_declared:""));
    for(const [file,info] of Object.entries(data.manifests))add("Manifest "+file+" · "+info.sha256);
    for(const framework of data.frameworks)add(framework.name+" · "+framework.evidence);
    heading("Source and test candidates");
    add(data.python_files.length+" Python files discovered"+(data.scan_truncated?" · bounded scan incomplete":""));
    for(const file of data.test_files.slice(0,25))add("Test candidate: "+file);
    heading("Installed tools (fingerprinted, NOT executed)");
    for(const tool of data.toolchains)add(tool.name+" · "+tool.status+(tool.sha256?" · SHA-256 "+tool.sha256:""));
    el("dsPyTool").replaceChildren(new Option("Choose approved tool",""));
    for(const item of data.toolchains){
      const option=new Option(item.name+" · "+item.status,item.name);
      option.disabled=item.status!=="installed_not_executed";el("dsPyTool").add(option);
    }
  }
  async function inspect(){
    const p=project(),id=++sequence;if(!p||busy)return;
    busy=true;controls();message("Reading bounded Python manifests and installed binary hashes.");
    try{
      const data=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==sequence||p!==project()||!root.isConnected)return;
      snapshot=data;render(data);message("Python project inspection complete. No code has run.");
    }catch(error){snapshot=null;clear();message("Inspection refused: "+error.message,true);}
    finally{busy=false;controls();}
  }
  async function syntax(){
    const p=project(),path=el("dsPySource").value.trim(),id=++sequence;
    if(!snapshot||!p||busy||!path)return;
    busy=true;controls();message("Checking source hash and parsing Python AST without execution.");
    try{
      const file=await api("/api/developer/studio/preview?"+new URLSearchParams({project:p,path}));
      const data=await api(base+"/syntax",{project:p,path,expected_sha256:file.sha256});
      if(id!==sequence||p!==project()||!root.isConnected)return;
      clear();heading("Python AST syntax · "+(data.valid?"valid":"error"));
      add("Source SHA-256: "+data.source_sha256);
      if(data.valid)add(data.functions+" functions and "+data.classes+" classes parsed.");
      for(const diag of data.diagnostics)add("Line "+diag.line+" · "+diag.message,"warning");
      add("AST parsing does not execute the source or guarantee runtime correctness.");
      message(data.valid?"AST parse successful; no code executed.":"Python syntax issue detected.",!data.valid);
    }catch(e){message("AST check rejected: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),tool=chosen(),task=el("dsPyTask").value,meta=snapshot;
    if(!p||!tool||!meta||busy||!getProject()?.trusted||!taskReady())return;
    if(!window.confirm("Approve real UNSANDBOXED "+tool.name+" execution for "+task+"? "+
      "Project tooling and tests may run untrusted code, access files/network and modify the project. "+
      "No OS/network sandbox, installation, recovery, Agent deployment or release approval is provided."))return;
    const id=++sequence;busy=true;controls();message("Running approved tool with bounded time and output.");
    try{
      const data=await api(base+"/run",{
        project:p,task,tool:tool.name,expected_manifest_sha256:meta.manifest_sha256,
        expected_executable:tool.executable,expected_sha256:tool.sha256,
        confirmed:true,accept_unsandboxed_execution_and_write_risk:true
      });
      if(id!==sequence||p!==project()||!root.isConnected)return;
      clear();heading(task+" · "+data.status);
      add("Tool: "+tool.name+" · Exit code: "+data.exit_code+" · "+data.elapsed_ms+" ms");
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=data.output||"(no output)";result.append(pre);
      if(data.timed_out||data.output_truncated)add("Output was limited or the process timed out.","warning");
      add("No Agent release or deployment approved; file changes by external tools are not verified.","warning");
      message("Python tool "+data.status+".",data.status!=="completed");
    }catch(e){message("Python run rejected: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function agent(){
    const panel=document.querySelector(".studio-agent-bridge");
    const action=panel?.querySelector("#studioAgentAction");
    const field=panel?.querySelector("#studioAgentMessage");
    if(!field||!action){message("The shared central Agent bridge is not available.",true);return;}
    action.value="deployment_readiness";
    field.value=("Review Developer Studio V17 Python deployment readiness: pyproject and lockfile integrity, "+
      "venv isolation, dependency provenance, Pytest/type/lint results, security and cross-platform CI, "+
      "reproducible packaging, rollback and human release approval. "+
      "Review only; no automatic execution, publishing or deployment.").slice(0,2200);
    field.dispatchEvent(new Event("input",{bubbles:true}));
    panel.scrollIntoView({block:"start",behavior:"smooth"});field.focus();
    message("Shared central Agent form prepared; separate confirmation is required.");
  }
  function fileChanged(path){
    if(path?.toLowerCase().endsWith(".py"))el("dsPySource").value=path;
    controls();
  }
  el("dsPyInspect").onclick=()=>void inspect();
  el("dsPySyntax").onclick=()=>void syntax();
  el("dsPyRun").onclick=()=>void run();
  el("dsPyAgent").onclick=agent;
  for(const name of ["dsPyTool","dsPyTask"])el(name).addEventListener("change",controls);
  el("dsPySource").addEventListener("input",controls);
  reset();
  return {projectChanged:reset,fileChanged};
}

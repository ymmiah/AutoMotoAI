/* Developer Studio V13 — JavaScript/TypeScript project intelligence and consented tasks. */
export function mountDeveloperJavaScript({api,host,getProject,editor,status}) {
  const BASE="/api/developer/studio/javascript";
  const root=host.querySelector("#dsJavaScriptRoot");
  root.innerHTML=
    '<section class="ds-js-panel" aria-label="JavaScript TypeScript build and test workflows">'+
      '<div class="ds-js-head"><h3>JavaScript & TypeScript · V13</h3>'+
        '<span class="ds-readonly">EXPLICIT TOOL EXECUTION ONLY</span></div>'+
      '<div class="ds-js-body">'+
        '<p class="ds-footnote">Inspect Node.js project metadata, detected frameworks, package scripts, lockfile conflicts and local tests without running anything. Real runs require a trusted workspace and a fresh approval. npm, pnpm, yarn and project tests execute untrusted code as your current user; they are not OS-sandboxed.</p>'+
        '<div class="ds-js-controls">'+
          '<button class="btn sm" id="dsJsInspect" type="button" disabled>Inspect project & tools</button>'+
          '<label for="dsJsTask">Task</label>'+
          '<select class="input" id="dsJsTask">'+
            '<option value="tool_version">Installed tool version</option>'+
            '<option value="node_check">Node syntax check</option>'+
            '<option value="node_test">Node built-in test</option>'+
            '<option value="tsc_check">TypeScript typecheck (no emit)</option>'+
            '<option value="script">Package script (test/build/lint/typecheck)</option>'+
          '</select>'+
          '<label for="dsJsTool">Pinned tool</label>'+
          '<select class="input" id="dsJsTool" disabled><option value="">Inspect installed tools</option></select>'+
          '<label for="dsJsFile">Source/test file</label>'+
          '<input class="input" id="dsJsFile" maxlength="1024" spellcheck="false" placeholder="src/main.test.mjs">'+
          '<label for="dsJsScript">Declared script</label>'+
          '<select class="input" id="dsJsScript" disabled><option value="">No scripts inspected</option></select>'+
          '<button class="btn sm primary" type="button" id="dsJsRun" disabled>Approve & run</button>'+
        '</div>'+
        '<p class="ds-footnote" role="status" aria-live="polite" id="dsJsStatus">Open a project to inspect Node.js.</p>'+
        '<div id="dsJsSummary" class="ds-js-summary" role="region" aria-label="Project summary and execution diagnostics" tabindex="0"></div>'+
        '<p class="ds-footnote">Node --check parses only; node --test, TypeScript tooling and package scripts can execute project or dependency code. No package install is started automatically. npm run explicitly executes the chosen script, even with ignore-scripts; offline options do not provide a network sandbox. Windows .cmd/.bat/.ps1 package-manager wrappers are deliberately blocked pending a safe native adapter.</p>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id);
  let snapshot=null, runSeq=0, busy=false, currentProject="";
  function message(str,error=false){
    const n=el("dsJsStatus");n.textContent=str;n.classList.toggle("ds-error",error);
  }
  function addLine(str,kind="info"){
    const p=document.createElement("p");p.className="ds-js-line";
    p.dataset.kind=kind;p.textContent=String(str);el("dsJsSummary").append(p);
  }
  function heading(str){
    const n=document.createElement("h4");n.textContent=str;el("dsJsSummary").append(n);
  }
  function clear(){el("dsJsSummary").replaceChildren();}
  function project(){return getProject()?.project||"";}
  const tools=()=>snapshot?.toolchains||[];
  const selected=()=>tools().find(x=>x.name===el("dsJsTool").value&&x.status==="installed_not_executed");
  function controls(){
    const ready=!!project()&&!busy;
    const isScript=el("dsJsTask").value==="script";
    const isFile=["node_check","node_test"].includes(el("dsJsTask").value);
    const typecheck=el("dsJsTask").value==="tsc_check";
    el("dsJsInspect").disabled=!ready;
    el("dsJsTool").disabled=!ready||!tools().some(x=>x.status==="installed_not_executed");
    el("dsJsFile").disabled=!ready||!isFile;
    el("dsJsScript").disabled=!ready||!isScript||!Object.keys(snapshot?.scripts||{}).length;
    el("dsJsRun").disabled=!ready||!getProject()?.trusted||!snapshot||!selected()||
      (isScript&&!el("dsJsScript").value)||
      (isFile&&!el("dsJsFile").value.trim())||
      (typecheck&&(!snapshot.tsconfig_present||!snapshot.typescript_declared))||
      ((isFile||typecheck)&&selected()?.name!=="node")||
      (isScript&&selected()?.name==="node");
  }
  function reset(){
    runSeq++;busy=false;snapshot=null;currentProject=project();clear();
    el("dsJsTool").replaceChildren(new Option("Inspect installed tools",""));
    el("dsJsScript").replaceChildren(new Option("No scripts inspected",""));
    message("Inspect a project to see JavaScript and TypeScript tools. Nothing runs automatically.");
    controls();
  }
  function populate(summary){
    snapshot=summary;
    const tool=el("dsJsTool"),oldTool=tool.value;
    tool.replaceChildren();tool.add(new Option("Choose a pinned installed tool",""));
    for(const entry of summary.toolchains||[]){
      const opt=new Option(entry.name+" · "+(entry.status==="installed_not_executed"?
        "fingerprinted (not run)":entry.status),entry.name);
      opt.disabled=entry.status!=="installed_not_executed";
      tool.add(opt);
    }
    if(tools().some(x=>x.name===oldTool&&x.status==="installed_not_executed"))tool.value=oldTool;
    const scripts=el("dsJsScript"),oldScript=scripts.value;
    scripts.replaceChildren();scripts.add(new Option("Choose an existing package script",""));
    for(const [name,value] of Object.entries(summary.scripts||{})){
      scripts.add(new Option(name+" · "+value.slice(0,90),name));
    }
    if(Object.hasOwn(summary.scripts||{},oldScript))scripts.value=oldScript;
    clear();heading("Project metadata");
    addLine((summary.name||"(unnamed)")+
      " · Node engines: "+(summary.engines_node_declared||"not specified")+
      " · packageManager: "+(summary.package_manager_declared||"not specified"));
    addLine("Manifest SHA-256: "+summary.package_json_sha256);
    addLine(summary.dependencies_count+" declared dependencies · "+
      (summary.node_modules_directory_present?"node_modules directory exists (integrity unverified)":"no node_modules directory"));
    addLine("TypeScript: "+(summary.typescript_declared?"declared":"not declared")+
      " · tsconfig: "+(summary.tsconfig_present?"found":"missing"));
    for(const item of summary.frameworks||[])
      addLine(item.name+" declared ("+item.declared_version+"); installed/compatible version not verified.");
    for(const item of summary.lockfiles||[])
      addLine("Lockfile: "+item.file+" · "+item.manager+
        " · SHA-256: "+(item.fingerprint||"unreadable"));
    if(summary.lockfile_conflict)addLine("Multiple lockfile managers detected: review before executing builds.","warning");
    heading("Discovered tests and scripts");
    for(const name of (summary.test_files||[]).slice(0,30))addLine("Test candidate: "+name);
    if(summary.test_search_truncated)addLine("Test search incomplete due to bounded traversal.","warning");
    for(const [name,value] of Object.entries(summary.scripts||{}))
      addLine("Script "+name+": "+value,"warning");
    heading("Toolchain availability");
    for(const item of summary.toolchains||[])
      addLine(item.name+": "+item.status+
        (item.sha256?" · "+item.sha256:""),item.status==="installed_not_executed"?"info":"warning");
    addLine("Inspect does not execute Node, npm, pnpm, yarn or any scripts.");
  }
  async function inspect(){
    const p=project();if(!p||busy)return;
    const seq=++runSeq;busy=true;controls();
    message("Reading bounded local package metadata and fingerprinting installed tools; no code executed.");
    try{
      const data=await api(BASE+"/inspect?"+new URLSearchParams({project:p}));
      if(seq!==runSeq||project()!==p||!root.isConnected)return;
      populate(data);
      message("Project inspected. Approve an individual task before running any executable.");
    }catch(error){snapshot=null;clear();message("Project inspection failed: "+error.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),tool=selected(),snapshotAtStart=snapshot;
    if(!p||busy||!getProject()?.trusted||!tool||!snapshotAtStart)return;
    const task=el("dsJsTask").value,file=el("dsJsFile").value.trim();
    const script=el("dsJsScript").value;
    const source=task==="script"?
      "Run the package.json script '"+script+"': "+(snapshotAtStart.scripts?.[script]||""):
      task==="tsc_check"?"Execute the installed TypeScript compiler JavaScript from node_modules.":
      task==="node_test"?"Execute project test code in Node.js.":"Invoke the installed tool.";
    const warning="Approve REAL, UNSANDBOXED "+tool.name+" execution in this trusted project?\n"+
      source+"\nProject or dependency code may read, write or transmit files. "+
      "No OS sandbox, package integrity certification or general network block exists. "+
      "The executable and package.json fingerprints will be checked again.";
    if(!window.confirm(warning))return;
    const req={project:p,task,tool:tool.name,
      expected_manifest_sha256:snapshotAtStart.package_json_sha256,
      expected_executable:tool.executable,expected_sha256:tool.sha256,
      confirmed:true,accept_unsandboxed_execution_and_write_risk:true};
    if(["node_check","node_test"].includes(task))req.relative_file=file;
    if(task==="script")req.script=script;
    const seq=++runSeq;busy=true;controls();message("Running approved local task with time/output limits…");
    try{
      const result=await api(BASE+"/run",req);
      if(seq!==runSeq||project()!==p||!root.isConnected)return;
      clear();heading("Real execution · "+result.task+" · "+result.status);
      addLine("Tool: "+result.tool+" · exit code "+result.exit_code+" · "+
        result.elapsed_ms+" ms");
      if(result.reported_tool_version)addLine("Reported version: "+result.reported_tool_version);
      if(result.output_truncated)addLine("Output exceeded the safe limit and the process was stopped.","warning");
      if(result.timed_out)addLine("Process exceeded its runtime budget and was stopped.","warning");
      if(result.build_script_exited_zero)
        addLine("The selected build script exited successfully on this machine; output artefacts and framework correctness require separate review.");
      for(const d of result.diagnostics||[])
        addLine((d.path||"compiler")+(d.line?":"+d.line+":"+d.column:"")+
          " · "+(d.code||"diagnostic")+" · "+d.message,"warning");
      const pre=document.createElement("pre");pre.className="ds-js-output";
      pre.textContent=result.output||"(no output)";
      el("dsJsSummary").append(pre);
      addLine("External execution is NOT sandboxed; source-file integrity was not independently verified.","warning");
      message("Task "+result.status+" (exit "+result.exit_code+").",
        result.status!=="completed");
    }catch(error){message("Task rejected or failed: "+error.message,true);}
    finally{busy=false;controls();}
  }
  function fileChanged(path){
    if(/\.(?:[cm]?[jt]s|jsx|tsx)$/i.test(path||"") &&
       !el("dsJsFile").value.trim())el("dsJsFile").value=path;
    controls();
  }
  el("dsJsInspect").onclick=()=>void inspect();
  el("dsJsRun").onclick=()=>void run();
  for(const id of ["dsJsTask","dsJsTool","dsJsScript"])
    el(id).addEventListener("change",controls);
  el("dsJsFile").addEventListener("input",controls);
  reset();
  return {projectChanged:reset,fileChanged};
}

/* Developer Studio V8 — user-installed toolchain descriptors, never auto-execute. */
export function mountDeveloperAdapters({api,host,getProject,status}) {
  const BASE="/api/developer/studio/adapters";
  const root=host.querySelector("#dsAdaptersRoot");
  root.innerHTML=
    '<section class="ds-adapters-panel" aria-label="External toolchain adapter SDK">'+
      '<div class="ds-adapters-head"><h3>Toolchains & debugger adapters · V8</h3>'+
        '<span class="ds-readonly">EXPLICIT EXECUTION ONLY</span></div>'+
      '<div class="ds-adapters-body">'+
        '<p class="ds-footnote">An adapter is a registered description of an <strong>already installed</strong> local tool. This does not download or install software. Executing an external tool is not sandboxed and may read, change or upload files; run only trusted tools and projects.</p>'+
        '<div class="ds-adapters-config">'+
          '<label for="dsAdapterId">Adapter ID</label><input id="dsAdapterId" class="input" maxlength="48" placeholder="e.g. local-python-tests">'+
          '<label for="dsAdapterLabel">Description</label><input id="dsAdapterLabel" class="input" maxlength="80" placeholder="e.g. Python test runner">'+
          '<label for="dsAdapterLanguage">Language</label><select id="dsAdapterLanguage" class="input"></select>'+
          '<label for="dsAdapterCategory">Role</label><select id="dsAdapterCategory" class="input">'+
            '<option value="compiler">Compiler</option><option value="test">Test runner</option>'+
            '<option value="formatter">Formatter</option><option value="linter">Linter</option>'+
            '<option value="package">Package manager</option><option value="debugger">DAP debugger</option>'+
          '</select>'+
          '<label for="dsAdapterExecutable">Absolute executable path</label>'+
            '<input id="dsAdapterExecutable" class="input" maxlength="2048" spellcheck="false" placeholder="Installed system tool outside all source roots">'+
          '<label for="dsAdapterArgs">Fixed arguments (JSON array)</label>'+
            '<input id="dsAdapterArgs" class="input" maxlength="2048" spellcheck="false" value="[]" aria-describedby="dsAdapterArgsHelp">'+
          '<label for="dsAdapterSha">SHA-256 fingerprint</label>'+
            '<input id="dsAdapterSha" class="input" readonly aria-label="Verified binary SHA-256" placeholder="Inspect executable to calculate">'+
        '</div>'+
        '<p class="ds-footnote" id="dsAdapterArgsHelp">Arguments are fixed literal strings; never enter secrets. For debuggers, the adapter must speak DAP over standard input/output.</p>'+
        '<div class="ds-adapters-controls" role="group" aria-label="Adapter registration">'+
          '<button type="button" class="btn sm" id="dsAdapterInspect" disabled>Inspect executable</button>'+
          '<button type="button" class="btn sm primary" id="dsAdapterRegister" disabled>Register adapter</button>'+
          '<button type="button" class="btn sm" id="dsAdapterRefresh">Refresh registered tools</button>'+
        '</div>'+
        '<div class="ds-adapters-run">'+
          '<label for="dsAdapterSelected">Registered adapter</label>'+
          '<select class="input" id="dsAdapterSelected" disabled><option value="">None registered</option></select>'+
          '<button type="button" class="btn sm primary" id="dsAdapterRun" disabled>Run with approval</button>'+
          '<button type="button" class="btn sm" id="dsAdapterRemove" disabled>Unregister</button>'+
        '</div>'+
        '<p class="ds-footnote" id="dsAdapterStatus" role="status" aria-live="polite">Open and trust a local project to register an external tool.</p>'+
        '<pre id="dsAdapterOutput" class="ds-adapters-output" role="region" aria-label="Bounded external tool output" tabindex="0"></pre>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const selected=el("dsAdapterSelected"), language=el("dsAdapterLanguage");
  const sha=el("dsAdapterSha"), executable=el("dsAdapterExecutable");
  const message=(value,bad=false)=>{
    el("dsAdapterStatus").textContent=value;
    el("dsAdapterStatus").classList.toggle("ds-error",bad);
  };
  let registered=[], seq=0, busy=false, verified=null;
  const text=value=>{el("dsAdapterOutput").textContent=typeof value==="string"?value:JSON.stringify(value,null,2);};
  function controls(){
    const trusted=!!getProject()?.trusted;
    const choice=registered.find(x=>x.id===selected.value);
    el("dsAdapterInspect").disabled=busy||!trusted||!executable.value.trim();
    el("dsAdapterRegister").disabled=busy||!trusted||!verified||sha.value!==verified.sha256;
    el("dsAdapterRun").disabled=busy||!trusted||!choice;
    el("dsAdapterRemove").disabled=busy||!trusted||!choice;
    selected.disabled=busy||!trusted||!registered.length;
    el("dsAdapterRefresh").disabled=busy||!getProject();
  }
  function resetFingerprint(){
    verified=null;sha.value="";controls();
  }
  function render(){
    const previous=selected.value;
    selected.replaceChildren();
    selected.add(new Option("Choose a registered adapter",""));
    for(const item of registered){
      selected.add(new Option(item.label+" · "+item.language+" · "+item.category,item.id));
    }
    if(registered.some(x=>x.id===previous))selected.value=previous;
    controls();
  }
  async function refresh(){
    const project=getProject();
    if(!project){registered=[];render();return;}
    const id=++seq;
    try{
      const result=await api(BASE+"/catalog?"+new URLSearchParams({project:project.project}));
      if(id!==seq||getProject()?.project!==project.project||!root.isConnected)return;
      registered=result.registered||[];
      render();
      message(registered.length+" registered adapter(s). No executable started.");
    }catch(error){message("Unable to inspect registered adapters: "+error.message,true);}
  }
  async function languages(){
    try{
      const result=await api("/api/developer/studio/language/registry");
      if(!root.isConnected)return;
      language.replaceChildren();
      for(const item of result.languages||[])language.add(new Option(item.name||item.id,item.id));
    }catch{
      language.replaceChildren();
      language.add(new Option("Python","python"));
      language.add(new Option("TypeScript","typescript"));
    }
  }
  async function inspect(){
    const project=getProject();
    if(!project?.trusted||busy)return;
    busy=true;controls();message("Hashing the selected installed executable…");
    const candidate=executable.value.trim();
    try{
      const result=await api(BASE+"/inspect",{project:project.project,executable:candidate});
      if(getProject()?.project!==project.project)return;
      verified=result;sha.value=result.sha256;
      executable.value=result.executable;
      message("Executable verified by SHA-256 (not a malware or version certification).");
      text({sha256:result.sha256,size_bytes:result.size_bytes,
        verification:result.verification});
    }catch(error){resetFingerprint();message("Executable inspection refused: "+error.message,true);}
    finally{busy=false;controls();}
  }
  async function register(){
    const project=getProject();
    if(!project?.trusted||!verified||busy)return;
    let args;
    try{
      args=JSON.parse(el("dsAdapterArgs").value);
      if(!Array.isArray(args)||args.length>12||args.some(v=>typeof v!=="string"))
        throw Error("Arguments must be a JSON array of up to 12 fixed strings.");
    }catch(error){message("Invalid fixed arguments: "+error.message,true);return;}
    const category=el("dsAdapterCategory").value;
    const input={project:project.project,id:el("dsAdapterId").value.trim(),
      label:el("dsAdapterLabel").value.trim(),language:language.value,category,
      protocol:category==="debugger"?"dap":"process",
      executable:verified.executable,args,expected_sha256:verified.sha256,confirmed:true};
    if(!window.confirm("Register this exact executable and fixed arguments for the current trusted project? Registration stores a private descriptor, but does NOT run or install the program."))return;
    busy=true;controls();
    try{
      const result=await api(BASE+"/register",input);
      if(getProject()?.project!==project.project)return;
      message("Adapter "+result.adapter.id+" registered. No program executed.");
      await refresh();
      selected.value=result.adapter.id;controls();
    }catch(error){message("Adapter registration rejected: "+error.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const project=getProject(),adapter=registered.find(x=>x.id===selected.value);
    if(!project?.trusted||!adapter||busy)return;
    const isDap=adapter.protocol==="dap";
    const warning=isDap?
      "Start this installed DAP adapter for a capability handshake only? No debuggee launch or attach will be requested. The adapter process itself is not sandboxed and may still read, write or send files.":
      "Execute this installed "+adapter.category+" tool with fixed arguments in the trusted project? This is real process execution. It is NOT sandboxed and may modify files, access the network or run project scripts.";
    if(!window.confirm(warning))return;
    const id=++seq;
    busy=true;controls();message(isDap?"Initialising DAP adapter without launching a program…":
      "Running the confirmed external process…");
    text("External tool execution in progress. Source-file changes are not automatically reversible.");
    try{
      const result=await api(BASE+(isDap?"/dap/initialize":"/run"),{
        project:project.project,id:adapter.id,confirmed:true,
        accept_execution_and_write_risk:true});
      if(seq!==id||getProject()?.project!==project.project)return;
      text(isDap?result:("Exit status: "+result.status+" · code "+result.exit_code+
        "\nElapsed: "+result.elapsed_ms+"ms\n\n"+result.output));
      message(isDap?
        "DAP capability exchange complete; no launch or attach requested.":
        "External process "+result.status+". Project files may have changed; review the workspace.");
    }catch(error){message("Adapter execution failed: "+error.message,true);text("");}
    finally{busy=false;controls();}
  }
  async function unregister(){
    const project=getProject(),adapter=registered.find(x=>x.id===selected.value);
    if(!project?.trusted||!adapter||busy)return;
    if(!window.confirm("Unregister "+adapter.label+" for this project? The installed executable will not be deleted."))return;
    busy=true;controls();
    try{
      await api(BASE+"/unregister",{project:project.project,id:adapter.id,confirmed:true});
      if(getProject()?.project!==project.project)return;
      message("Adapter registration removed; system executable untouched.");
      registered=registered.filter(x=>x.id!==adapter.id);
      render();
    }catch(error){message("Cannot unregister adapter: "+error.message,true);}
    finally{busy=false;controls();}
  }
  async function projectChanged(){
    seq++;busy=false;registered=[];verified=null;sha.value="";
    el("dsAdapterOutput").textContent="";render();
    if(getProject())await refresh();
    else message("Open and trust a local project to register an external tool.");
  }
  async function trustChanged(){
    if(!getProject()?.trusted)resetFingerprint();
    controls();
  }
  el("dsAdapterInspect").onclick=()=>void inspect();
  el("dsAdapterRegister").onclick=()=>void register();
  el("dsAdapterRefresh").onclick=()=>void refresh();
  el("dsAdapterRun").onclick=()=>void run();
  el("dsAdapterRemove").onclick=()=>void unregister();
  executable.addEventListener("input",resetFingerprint);
  selected.addEventListener("change",controls);
  el("dsAdapterCategory").addEventListener("change",controls);
  void languages();
  controls();
  return {projectChanged,trustChanged,refresh};
}

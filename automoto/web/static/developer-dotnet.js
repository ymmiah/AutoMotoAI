/* Developer Studio V22 — C#/.NET evidence, SDK, NuGet, MSBuild and tests. */
export function mountDeveloperDotnet({api,host,getProject,status}){
  const base="/api/developer/studio/dotnet",root=host.querySelector("#dsDotnetRoot");
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="C sharp and dotnet SDK project and test workflows">'+
      '<div class="ds-php-head"><h3>C# & .NET Engineering · V22</h3>'+
        '<span class="ds-readonly">STATIC INSPECTION / CONSENTED SDK TASKS</span></div>'+
      '<div class="ds-php-body">'+
        '<p class="ds-footnote">Inspect .NET projects, target frameworks, declared NuGet packages, ASP.NET Core, Blazor and xUnit/NUnit evidence. Installed SDK version is reported only after an approved executable version check. C# language server and debugger actions use their separately approved existing controls.</p>'+
        '<div class="ds-php-controls">'+
          '<button class="btn sm" type="button" id="dsDotnetInspect" disabled>Inspect .NET project</button>'+
          '<button class="btn sm" type="button" id="dsDotnetLsp">C# language server</button>'+
          '<button class="btn sm" type="button" id="dsDotnetDap">.NET debugger controls</button>'+
          '<label for="dsDotnetTask">Approved task</label>'+
          '<select id="dsDotnetTask" class="input">'+
            '<option value="sdk_version">Installed .NET SDK version</option>'+
            '<option value="list_sdks">List installed SDKs</option>'+
            '<option value="msbuild_version">MSBuild version</option>'+
            '<option value="restore_offline">Restore only from installed NuGet cache</option>'+
            '<option value="build">Offline restore and build</option>'+
            '<option value="test">Offline restore, build and run tests</option>'+
            '<option value="run_smoke">Build and run approved console app</option>'+
          '</select>'+
          '<label for="dsDotnetTool">SHA-256 verified SDK</label>'+
          '<select id="dsDotnetTool" class="input" disabled><option value="">Inspect first</option></select>'+
          '<button type="button" class="btn sm primary" id="dsDotnetRun" disabled>Review risks & run</button>'+
          '<button type="button" class="btn sm" id="dsDotnetAgent">Central Agent release review</button>'+
        '</div>'+
        '<p class="ds-footnote" id="dsDotnetStatus" role="status" aria-live="polite">Open a local .NET project to inspect.</p>'+
        '<div id="dsDotnetResults" class="ds-php-results" role="region" tabindex="0" aria-label=".NET package and test evidence"></div>'+
        '<p class="ds-footnote">MSBuild, NuGet build targets and test assemblies can run arbitrary code with local user privileges. A temporary copy and offline package-source configuration are NOT an OS or network sandbox. Installed NuGet caches may be read or changed. The application does not automatically download packages, launch a debugger, deploy or release.</p>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const project=()=>getProject()?.project||"";
  const results=el("dsDotnetResults");
  let data=null,busy=false,seq=0;
  function info(s,error=false){
    el("dsDotnetStatus").textContent=s;
    el("dsDotnetStatus").classList.toggle("ds-error",error);
  }
  function clear(){results.replaceChildren();}
  function line(value,warn=false){
    const p=document.createElement("p");p.className="ds-php-line";
    p.textContent=String(value);
    if(warn)p.dataset.severity="warning";
    results.append(p);
  }
  function heading(value){const h=document.createElement("h4");h.textContent=value;results.append(h);}
  const tool=()=>data?.toolchains?.find(t=>t.name===el("dsDotnetTool").value&&t.status==="installed_not_executed");
  function control(){
    const enabled=!!project()&&!busy;
    el("dsDotnetInspect").disabled=!enabled;
    el("dsDotnetTool").disabled=!enabled||!data;
    const task=el("dsDotnetTask").value;
    el("dsDotnetRun").disabled=!enabled||!data||!getProject()?.trusted||
      tool()?.name!=="dotnet"||
      (!["sdk_version","list_sdks","msbuild_version"].includes(task)&&!data.safe_to_offer_builds);
  }
  function reset(){
    ++seq;busy=false;data=null;clear();
    el("dsDotnetTool").replaceChildren(new Option("Inspect .NET project first",""));
    info("Inspect a local .NET project. No SDK executable runs during inspection.");
    control();
  }
  function show(value){
    clear();heading("Target frameworks, MSBuild and NuGet");
    line("Manifest SHA-256: "+value.manifest_sha256);
    line("Source SHA-256: "+value.source_sha256);
    line("SDK request: "+(value.sdk_request.requested_version||"not pinned by global.json")+
      " · roll-forward "+(value.sdk_request.roll_forward||"default"));
    line("Actual installed SDK: not yet executed or verified");
    for(const p of value.projects){
      line(p.path+" · "+p.sdk+" · target "+
        (p.target_frameworks.join(", ")||"not specified")+
        " · output "+p.output_type+
        (p.is_test_project?" · test project":""));
      for(const ref of p.package_references.slice(0,25))
        line("NuGet declaration: "+ref.name+(ref.declared_version?" "+ref.declared_version:""));
      for(const issue of p.unsafe_constructs)line("Requires manual review: "+issue,true);
    }
    for(const warning of value.warnings)line(warning,true);
    if(!value.safe_to_offer_builds)line("Build, restore and test controls blocked by project review requirements.",true);
    heading("C# / Razor source evidence");
    line(value.files.length+" bounded source files · "+
      (value.framework_hints.join(", ")||"No framework established"));
    for(const source of value.files.slice(0,55))
      line(source.language+" · "+source.path+
        (source.types.length?" · "+source.types.join(", "):"")+
        (source.framework_hints.length?" · "+source.framework_hints.join(", "):""));
    heading("Installed SDK/IDE tools (hashes only, not executed)");
    const select=el("dsDotnetTool");select.replaceChildren(new Option("Choose approved SDK",""));
    for(const t of value.toolchains){
      line(t.name+" · "+t.status+(t.sha256?" · "+t.sha256:""));
      const option=new Option(t.name+" · "+t.status,t.name);
      option.disabled=t.status!=="installed_not_executed"||t.name!=="dotnet";
      select.add(option);
    }
    heading("Debug adapters — separately approved");
    for(const t of value.debug_adapters)line(t.name+" · "+t.status);
    line("No SDK, MSBuild, language server, debugger, package source or project code executed.");
  }
  async function inspect(){
    const p=project();
    if(!p||busy)return;
    const id=++seq;busy=true;control();info("Inspecting bounded C# project manifests and source.");
    try{
      const response=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==seq||p!==project()||!root.isConnected)return;
      data=response;show(response);info("C#/.NET inspection completed without execution.");
    }catch(e){data=null;clear();info("Inspection refused: "+e.message,true);}
    finally{busy=false;control();}
  }
  async function run(){
    const p=project(),snapshot=data,selected=tool(),task=el("dsDotnetTask").value;
    if(!p||!snapshot||!selected||busy||!getProject()?.trusted||el("dsDotnetRun").disabled)return;
    if(!window.confirm("Approve UNSANDBOXED .NET task "+task+"? "+
      "MSBuild, NuGet project targets and .NET tests can read secrets, write files and use "+
      "your network permissions. Only bounded project files are copied to a temporary folder; "+
      "NuGet package sources are cleared, but this does not isolate arbitrary code. "+
      "No installation, publication or deployment is authorised."))return;
    const id=++seq;busy=true;control();info("Executing one explicitly authorised .NET task.");
    try{
      const output=await api(base+"/run",{
        project:p,task,tool:"dotnet",
        expected_manifest_sha256:snapshot.manifest_sha256,
        expected_source_sha256:snapshot.source_sha256,
        expected_toolchain_sha256:snapshot.toolchain_sha256,
        expected_executable:selected.executable,expected_sha256:selected.sha256,
        confirmed:true,accept_unsandboxed_msbuild_and_test_execution:true
      });
      if(id!==seq||p!==project()||!root.isConnected)return;
      clear();heading(task+" · "+output.status);
      if(output.actual_sdk_version)line("Actual SDK version reported by executable: "+output.actual_sdk_version);
      for(const s of output.stages)line(s.stage+" · "+s.status+" · exit "+s.exit_code);
      for(const d of output.diagnostics||[])
        line((d.path||"Untrusted output path")+":"+d.line+":"+d.column+
          " · "+d.severity+" "+d.code+" · "+d.message,true);
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=output.output||"(no output)";results.append(pre);
      line("Temporary project copy deleted. Original project and OS-level isolation not certified.",true);
      info(".NET task "+output.status+".",output.status!=="completed");
    }catch(e){info(".NET task refused: "+e.message,true);}
    finally{busy=false;control();}
  }
  function panel(selector,label){
    const target=host.querySelector(selector);
    if(!target){info(label+" panel unavailable.",true);return;}
    target.scrollIntoView({block:"start",behavior:"smooth"});
    info("Use existing "+label+" with separate project trust and explicit consent.");
  }
  function agent(){
    const panel=document.querySelector(".studio-agent-bridge"),
      action=panel?.querySelector("#studioAgentAction"),
      field=panel?.querySelector("#studioAgentMessage");
    if(!action||!field){info("Central Agent review unavailable.",true);return;}
    action.value="deployment_readiness";
    field.value=("Review Developer Studio V22 C#/.NET release readiness: actual .NET SDK and MSBuild "+
      "versions, NuGet package provenance/locks, ASP.NET Core and Blazor safety, xUnit/NUnit "+
      "test results, C# LSP and debugger admission, CI, accessibility, security and rollback. "+
      "Review only, no automatic build, package installation or deployment; separate human "+
      "release authorisation required.").slice(0,2200);
    field.dispatchEvent(new Event("input",{bubbles:true}));
    panel.scrollIntoView({block:"start",behavior:"smooth"});field.focus();
    info("Shared central Agent release review prepared; submit separately.");
  }
  el("dsDotnetInspect").onclick=()=>void inspect();
  el("dsDotnetRun").onclick=()=>void run();
  el("dsDotnetLsp").onclick=()=>panel("#dsLspRoot","C# language server");
  el("dsDotnetDap").onclick=()=>panel("#dsAdaptersRoot",".NET debugger");
  el("dsDotnetAgent").onclick=agent;
  for(const name of ["dsDotnetTask","dsDotnetTool"])el(name).addEventListener("change",control);
  reset();return {projectChanged:reset,fileChanged:()=>control()};
}

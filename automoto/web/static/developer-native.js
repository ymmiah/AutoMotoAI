/* Developer Studio V20: C/C++ CMake and native diagnostics. */
export function mountDeveloperNative({api,host,getProject,status}) {
  const base="/api/developer/studio/native", root=host.querySelector("#dsNativeRoot");
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="C and C++ CMake, compiler, CTest and sanitiser checks">'+
      '<div class="ds-php-head"><h3>C & C++ Engineering · V20</h3>'+
        '<span class="ds-readonly">READ-ONLY INSPECTION / EXPLICIT EXECUTION</span></div>'+
      '<div class="ds-php-body">'+
        '<p class="ds-footnote">Inspect CMake and C/C++ source inventory, external compiler availability, redacted compilation database, includes and function hints. Native clangd language-server and debugging controls remain independently approved through the existing panels.</p>'+
        '<div class="ds-php-controls">'+
          '<button class="btn sm" type="button" id="dsNativeInspect" disabled>Inspect native project</button>'+
          '<button class="btn sm" type="button" id="dsNativeLsp">C/C++ clangd</button>'+
          '<button class="btn sm" type="button" id="dsNativeDebug">Native debugger adapters</button>'+
          '<label for="dsNativeTask">Approved task</label>'+
          '<select class="input" id="dsNativeTask">'+
            '<option value="cmake_version">CMake version</option>'+
            '<option value="ctest_version">CTest version</option>'+
            '<option value="compiler_version">Compiler version</option>'+
            '<option value="clangd_version">clangd version</option>'+
            '<option value="build">Configure and build temporary binary</option>'+
            '<option value="test">Configure, build and run CTest</option>'+
            '<option value="sanitize">Build/test with address and undefined-behaviour sanitisers</option>'+
          '</select>'+
          '<label for="dsNativeTool">Verified tool</label>'+
          '<select class="input" id="dsNativeTool" disabled><option value="">Inspect first</option></select>'+
          '<button class="btn sm primary" type="button" id="dsNativeRun" disabled>Review risks & run</button>'+
          '<button class="btn sm" type="button" id="dsNativeAgent">Central Agent release review</button>'+
        '</div>'+
        '<p id="dsNativeStatus" class="ds-footnote" role="status" aria-live="polite">Open a project to inspect native sources.</p>'+
        '<div id="dsNativeResults" class="ds-php-results" role="region" tabindex="0" aria-label="Native project diagnostics and sanitiser evidence"></div>'+
        '<p class="ds-footnote">CMake configuration can execute arbitrary project scripts. Building, testing and sanitiser instrumentation may read files, write to the project or access the network as the local user. Temporary outputs and checksum checks are not an OS/network sandbox. No automatic installation, debug attachment or deployment occurs.</p>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id), project=()=>getProject()?.project||"";
  const result=el("dsNativeResults");
  let snapshot=null,busy=false,seq=0;
  function msg(v,bad=false) {
    el("dsNativeStatus").textContent=v;
    el("dsNativeStatus").classList.toggle("ds-error",bad);
  }
  function clear(){result.replaceChildren();}
  function text(v,warn=false){
    const p=document.createElement("p");p.className="ds-php-line";p.textContent=String(v);
    if(warn)p.dataset.severity="warning";result.append(p);
  }
  function title(v){const h=document.createElement("h4");h.textContent=v;result.append(h);}
  const chosen=()=>snapshot?.toolchains?.find(x=>x.name===el("dsNativeTool").value&&x.status==="installed_not_executed");
  function allowed(){
    const task=el("dsNativeTask").value,name=chosen()?.name;
    if(task==="cmake_version"||task==="build"||task==="test"||task==="sanitize")
      return name==="cmake" && (task==="cmake_version"||!!snapshot?.safe_to_offer_runs);
    if(task==="ctest_version")return name==="ctest";
    if(task==="clangd_version")return name==="clangd";
    if(task==="compiler_version")return ["gcc","g++","clang","clang++","cl"].includes(name);
    return false;
  }
  function controls(){
    const ready=!!project()&&!busy;
    el("dsNativeInspect").disabled=!ready;
    el("dsNativeTool").disabled=!ready||!snapshot;
    el("dsNativeRun").disabled=!ready||!snapshot||!getProject()?.trusted||!allowed();
  }
  function reset(){
    ++seq;busy=false;snapshot=null;clear();
    el("dsNativeTool").replaceChildren(new Option("Inspect project first",""));
    msg("Inspect a local CMake project. No tools run automatically.");controls();
  }
  function render(data){
    clear();title("C/C++ sources and CMake fingerprints");
    text("Manifest SHA-256: "+data.manifest_sha256);
    text("Source SHA-256: "+data.source_sha256);
    text(data.files.length+" source/header files, "+data.symbols.length+" lexical function candidates");
    for(const [path,entry] of Object.entries(data.manifests))
      text(path+" · SHA-256 "+entry.sha256);
    for(const f of data.files.slice(0,50))
      text(f.language+" · "+f.path+
        (f.functions?.length?" · "+f.functions.slice(0,8).join(", "):"")+
        (f.includes?.length?" · includes "+f.includes.slice(0,5).join(", "):""));
    for(const w of data.warnings||[])text("Manual review needed: "+w,true);
    if(!data.safe_to_offer_runs)text("Native builds/tests blocked until workspace review.",true);
    title("Compilation database (commands and flags redacted)");
    text(data.compile_commands.present?
      data.compile_commands.entries.length+" compile command entries safely inspected":
      "No root compile_commands.json; CMake may produce one within a temporary build.");
    for(const entry of data.compile_commands.entries.slice(0,35))
      text(entry.language+" · "+entry.file);
    title("Installed toolchain hashes, no execution");
    const select=el("dsNativeTool");select.replaceChildren(new Option("Choose installed tool",""));
    for(const tool of data.toolchains){
      text(tool.name+" · "+tool.status+(tool.sha256?" · "+tool.sha256:""));
      const option=new Option(tool.name+" · "+tool.status,tool.name);
      option.disabled=tool.status!=="installed_not_executed";select.add(option);
    }
    title("Native LSP and debugger availability");
    text("clangd and compiler navigation use separately approved LSP/DAP panels.");
    for(const a of data.debug_adapters)text(a.name+" · "+a.status);
    text("Source review is inert; project code was not executed.");
  }
  async function inspect(){
    const p=project(),id=++seq;
    if(!p||busy)return;
    busy=true;controls();msg("Inspecting CMake and bounded source fingerprints.");
    try{
      const data=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==seq||p!==project()||!root.isConnected)return;
      snapshot=data;render(data);msg("Native inspection complete; nothing was executed.");
    }catch(e){snapshot=null;clear();msg("Native inspection refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),tool=chosen(),data=snapshot,task=el("dsNativeTask").value;
    if(!p||!tool||!data||busy||!getProject()?.trusted||!allowed())return;
    if(!window.confirm("Approve UNSANDBOXED "+tool.name+" task "+task+"? "+
      "CMake can execute scripts while configuring, and native compilers/CTest can run arbitrary "+
      "project code with your filesystem and network permissions. Outputs are temporary but "+
      "source changes are not blocked. This is NOT a release/deployment or a security sandbox."))return;
    const id=++seq;busy=true;controls();msg("Executing the approved native toolchain.");
    try{
      const resultData=await api(base+"/run",{
        project:p,task,tool:tool.name,expected_manifest_sha256:data.manifest_sha256,
        expected_source_sha256:data.source_sha256,
        expected_toolchain_sha256:data.toolchain_sha256,
        expected_executable:tool.executable,expected_sha256:tool.sha256,
        confirmed:true,accept_unsandboxed_build_test_and_network_risk:true
      });
      if(id!==seq||p!==project()||!root.isConnected)return;
      clear();title("Native "+task+" · "+resultData.status);
      for(const stage of resultData.stages||[])text(stage.stage+" · "+stage.status+" · exit "+stage.exit_code);
      for(const issue of resultData.diagnostics||[])
        text((issue.path||"Untrusted path")+":"+issue.line+":"+issue.column+
          " · "+issue.severity+" · "+issue.message,true);
      if(resultData.sanitizer_detected){
        title("Sanitiser evidence");
        for(const item of resultData.sanitizer_evidence)text(item,true);
      }
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=resultData.output||"(no output)";result.append(pre);
      text("Temporary build removed. Source changes by external tools not verified.",true);
      msg("Native task "+resultData.status+".",resultData.status!=="completed");
    }catch(e){msg("Native run rejected: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function panel(target,label){
    const node=host.querySelector(target);
    if(!node){msg(label+" is unavailable.",true);return;}
    node.scrollIntoView({block:"start",behavior:"smooth"});
    msg("Use existing "+label+" and provide separate approval.");
  }
  function agent(){
    const rootAgent=document.querySelector(".studio-agent-bridge");
    const action=rootAgent?.querySelector("#studioAgentAction");
    const field=rootAgent?.querySelector("#studioAgentMessage");
    if(!field||!action){msg("Shared Agent review is unavailable.",true);return;}
    action.value="deployment_readiness";
    field.value=("Review Developer Studio V20 C/C++ release readiness: CMake and compilation database "+
      "provenance, GCC/Clang/MSVC compiler compatibility, CTest results, clangd and native DAP, "+
      "sanitiser evidence, dependency/build script safety, CI, accessibility, rollback and "+
      "independent human approval. This is review-only; no automatic build or deployment.").slice(0,2200);
    field.dispatchEvent(new Event("input",{bubbles:true}));
    rootAgent.scrollIntoView({block:"start",behavior:"smooth"});field.focus();
    msg("Shared central Agent release review prepared; submit separately.");
  }
  el("dsNativeInspect").onclick=()=>void inspect();
  el("dsNativeRun").onclick=()=>void run();
  el("dsNativeLsp").onclick=()=>panel("#dsLspRoot","clangd language server");
  el("dsNativeDebug").onclick=()=>panel("#dsAdaptersRoot","native debugger adapters");
  el("dsNativeAgent").onclick=agent;
  for(const name of ["dsNativeTask","dsNativeTool"])el(name).addEventListener("change",controls);
  reset();
  return {projectChanged:reset,fileChanged:()=>controls()};
}

/* Developer Studio V24 — Swift, SwiftUI, Objective-C and iOS inspection. */
export function mountDeveloperSwift({api,host,getProject,status}){
  const base="/api/developer/studio/swift";
  const root=host.querySelector("#dsSwiftRoot");
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="Swift SwiftUI Objective C SwiftPM and Xcode iOS evidence">'+
    '<div class="ds-php-head"><h3>Swift & iOS Engineering · V24</h3>'+
    '<span class="ds-readonly">INERT INSPECTION / CONSENTED SWIFT & XCODE</span></div>'+
    '<div class="ds-php-body">'+
    '<p class="ds-footnote">Inspect Swift, SwiftUI and Objective-C source, SwiftPM manifests, Xcode shared schemes, simulator prerequisites and SourceKit-LSP evidence. Xcode builds require supported macOS. Simulator/device install and launch are never automatic.</p>'+
    '<div class="ds-php-controls">'+
    '<button id="dsSwiftInspect" class="btn sm" type="button" disabled>Inspect Swift / iOS</button>'+
    '<button id="dsSwiftLsp" class="btn sm" type="button">SourceKit-LSP controls</button>'+
    '<button id="dsSwiftDap" class="btn sm" type="button">LLDB debugger controls</button>'+
    '<label for="dsSwiftTask">Approved task</label>'+
    '<select id="dsSwiftTask" class="input">'+
    '<option value="swift_version">Installed Swift version</option>'+
    '<option value="swiftc_version">Installed Swift compiler version</option>'+
    '<option value="swift_build">Build SwiftPM package</option>'+
    '<option value="swift_test">Test SwiftPM package</option>'+
    '<option value="swift_smoke">Build and run SwiftPM executable</option>'+
    '<option value="xcode_version">Installed Xcode version (macOS)</option>'+
    '<option value="simulator_list">Read simulator availability (macOS)</option>'+
    '<option value="ios_simulator_build">Build unsigned iOS Simulator app (macOS)</option>'+
    '</select>'+
    '<label for="dsSwiftTool">Pinned installed executable</label>'+
    '<select id="dsSwiftTool" class="input" disabled><option value="">Inspect first</option></select>'+
    '<button type="button" id="dsSwiftRun" class="btn sm primary" disabled>Review risk & run</button>'+
    '<button id="dsSwiftAgent" type="button" class="btn sm">Central Agent release review</button>'+
    '</div>'+
    '<p id="dsSwiftStatus" class="ds-footnote" role="status" aria-live="polite">Open an approved local Swift or Xcode project to inspect.</p>'+
    '<div id="dsSwiftResults" class="ds-php-results" role="region" tabindex="0" aria-label="Swift package and iOS project inspection"></div>'+
    '<p class="ds-footnote">SwiftPM manifests, compiler plugins and Xcode projects execute with your local OS/network privileges. A temporary copy and pinned hashes do NOT provide an OS sandbox, prevent all network access or guarantee original files cannot change. Existing SourceKit-LSP and LLDB controls require separate approval. Device installation, signing, TestFlight and App Store deployment are not authorised here.</p>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const out=el("dsSwiftResults");
  const project=()=>getProject()?.project||"";
  let state=null,busy=false,sequence=0;
  function line(v,warn=false){const p=document.createElement("p");p.className="ds-php-line";p.textContent=String(v);if(warn)p.dataset.severity="warning";out.append(p);}
  function heading(v){const h=document.createElement("h4");h.textContent=v;out.append(h);}
  function info(v,error=false){const e=el("dsSwiftStatus");e.textContent=v;e.classList.toggle("ds-error",error);}
  function pinned(){return state?.toolchains?.find(t=>t.name===el("dsSwiftTool").value&&t.status==="installed_not_executed");}
  const taskTool={swift_version:"swift",swiftc_version:"swiftc",swift_build:"swift",swift_test:"swift",
    swift_smoke:"swift",xcode_version:"xcodebuild",simulator_list:"xcrun",ios_simulator_build:"xcodebuild"};
  function allowed(){
    if(!state||!getProject()?.trusted)return false;
    const task=el("dsSwiftTask").value,required=taskTool[task];
    if(pinned()?.name!==required)return false;
    if(["xcode_version","simulator_list","ios_simulator_build"].includes(task) && state.platform!=="darwin")return false;
    if(["swift_build","swift_test","swift_smoke"].includes(task))
      return state.safe_to_offer_builds&&state.project_type==="swiftpm"&&
        (task!=="swift_smoke"||!!state.swiftpm.declared_executable);
    if(task==="ios_simulator_build")
      return state.safe_to_offer_builds&&state.project_type==="xcode_ios";
    return true;
  }
  function controls(){
    el("dsSwiftInspect").disabled=!project()||busy;
    el("dsSwiftTool").disabled=!project()||busy||!state;
    el("dsSwiftRun").disabled=!project()||busy||!allowed();
  }
  function reset(){
    ++sequence;state=null;busy=false;out.replaceChildren();
    el("dsSwiftTool").replaceChildren(new Option("Inspect first",""));
    info("No executables run during inspection. Xcode and iOS Simulator require macOS.");
    controls();
  }
  function render(data){
    out.replaceChildren();
    heading("SwiftPM, Xcode project and source fingerprints");
    line("Project type: "+data.project_type+" · host platform: "+data.platform);
    line("Manifest SHA-256: "+data.manifest_sha256);
    line("Source SHA-256: "+data.source_sha256);
    line("SwiftPM executable: "+(data.swiftpm.declared_executable||"not declared")+
      " · external dependencies or plugins: "+data.swiftpm.external_dependencies);
    line("Xcode project: "+(data.ios.project||"not detected")+
      " · shared scheme: "+(data.ios.scheme||"not detected"));
    line("iOS deployment targets: "+(data.ios.deployment_targets.join(", ")||"unknown")+
      " · bundle identifiers: "+(data.ios.bundle_ids.join(", ")||"unknown"));
    line("SwiftUI and Objective-C: "+(data.framework_hints.join(", ")||"no source hint detected"));
    for(const warning of data.warnings)line("Requires review: "+warning,true);
    if(!data.safe_to_offer_builds)line("Build/test tasks blocked until project requirements pass.",true);
    heading("Bounded source evidence — no compilation or external command");
    for(const file of data.files.slice(0,65))
      line(file.language+" · "+file.path+
        (file.symbols.length?" · "+file.symbols.join(", "):"")+
        (file.swiftui_hint?" · SwiftUI hint":""));
    heading("Installed tools — file fingerprints, not verified runtime versions");
    const select=el("dsSwiftTool");
    select.replaceChildren(new Option("Choose approved executable",""));
    for(const t of data.toolchains){
      line(t.name+" · "+t.status+(t.sha256?" · "+t.sha256:""));
      const option=new Option(t.name+" · "+t.status,t.name);
      option.disabled=t.status!=="installed_not_executed"||
        !["swift","swiftc","xcodebuild","xcrun"].includes(t.name);
      select.add(option);
    }
    heading("Simulator, SourceKit-LSP and LLDB prerequisites");
    line("Simulator state: "+data.simulator_status+" · started: "+data.simulator_started+
      " · device connected: "+data.device_connected);
    line(data.sourcekit_lsp);
    line(data.debugger);
    line("Inspection did not execute Swift package manifests, Xcode, compiler, LSP or simulator.");
  }
  async function inspect(){
    const p=project();if(!p||busy)return;
    const id=++sequence;busy=true;controls();
    info("Reading bounded Swift and Xcode project evidence without execution.");
    try{
      const data=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==sequence||p!==project()||!root.isConnected)return;
      state=data;render(data);info("Swift/iOS inspection complete without execution.");
    }catch(e){state=null;out.replaceChildren();info("Swift inspection refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),data=state,tool=pinned(),task=el("dsSwiftTask").value;
    if(!p||!data||!tool||busy||!allowed())return;
    if(!window.confirm("Approve UNSANDBOXED "+task+" using "+tool.name+"? "+
      "SwiftPM manifests, Xcode targets, compilers and tests may access your secrets, "+
      "modify files outside the temporary project copy and use network permissions. "+
      "No Simulator launch, app installation, signing, publication or deployment is authorised."))return;
    const id=++sequence;busy=true;controls();
    info("Running one explicitly approved Swift/iOS task.");
    try{
      const result=await api(base+"/run",{
        project:p,task,tool:tool.name,
        expected_manifest_sha256:data.manifest_sha256,
        expected_source_sha256:data.source_sha256,
        expected_toolchain_sha256:data.toolchain_sha256,
        expected_executable:tool.executable,expected_sha256:tool.sha256,
        confirmed:true,accept_unsandboxed_compiler_manifest_and_network_risk:true
      });
      if(id!==sequence||p!==project()||!root.isConnected)return;
      out.replaceChildren();heading(task+" · "+result.status);
      for(const stage of result.stages)line("Stage "+stage.status+" · exit "+stage.exit_code);
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=result.output||"(no output)";out.append(pre);
      line("Temporary copy deleted; no device boot/install/deploy occurred.",true);
      info("Swift/iOS task "+result.status+".",result.status!=="completed");
    }catch(e){info("Swift/iOS task refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function panel(selector,name){
    const node=host.querySelector(selector);
    if(!node){info(name+" panel unavailable.",true);return;}
    node.scrollIntoView({block:"start",behavior:"smooth"});
    info("Use existing "+name+" controls with independent project trust and consent.");
  }
  function agent(){
    const block=document.querySelector(".studio-agent-bridge");
    const action=block?.querySelector("#studioAgentAction");
    const field=block?.querySelector("#studioAgentMessage");
    if(!action||!field){info("Shared AutoMoto Agent is unavailable.",true);return;}
    action.value="deployment_readiness";
    field.value=("Review Developer Studio V24 Swift/iOS release readiness: exact Swift/Xcode "+
      "versions, SwiftPM dependencies and source integrity, SourceKit-LSP and LLDB admission, "+
      "real iOS Simulator build/launch screenshots, SwiftUI and Objective-C diagnostics, "+
      "signing, App Store requirements, accessibility, security and rollback. Review-only; "+
      "no automatic simulator, device access, app signing or deployment. Require separate human approval.").slice(0,2200);
    field.dispatchEvent(new Event("input",{bubbles:true}));
    block.scrollIntoView({block:"start",behavior:"smooth"});field.focus();
    info("Same central AutoMoto Agent release-review draft prepared, not submitted.");
  }
  el("dsSwiftInspect").onclick=()=>void inspect();
  el("dsSwiftRun").onclick=()=>void run();
  el("dsSwiftLsp").onclick=()=>panel("#dsLspRoot","SourceKit-LSP");
  el("dsSwiftDap").onclick=()=>panel("#dsAdaptersRoot","LLDB debugger");
  el("dsSwiftAgent").onclick=agent;
  for(const id of ["dsSwiftTask","dsSwiftTool"])el(id).addEventListener("change",controls);
  reset();return {projectChanged:reset,fileChanged:controls};
}

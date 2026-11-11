/* Developer Studio V25: Flutter/Dart and React Native evidence, explicit tools only. */
export function mountDeveloperMobile({api,host,getProject,status}) {
  const root=host.querySelector("#dsMobileRoot");
  const base="/api/developer/studio/mobile";
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="Flutter Dart React Native device targets and approved builds">'+
    '<div class="ds-php-head"><h3>Flutter & React Native · V25</h3>'+
    '<span class="ds-readonly">INERT INSPECTION / APPROVED OFFLINE TASKS</span></div>'+
    '<div class="ds-php-body">'+
    '<p class="ds-footnote">Inspect pubspec/lockfiles, Dart widgets, React Native, Metro, native bridges and installed tools. Device lists are queried only after consent. Flutter package/build operations and Node/npm tasks use a bounded project copy, not an OS sandbox.</p>'+
    '<div class="ds-php-controls">'+
    '<button id="dsMobileInspect" class="btn sm" type="button" disabled>Inspect mobile project</button>'+
    '<button id="dsMobileLsp" class="btn sm" type="button">Dart / TypeScript LSP</button>'+
    '<button id="dsMobileDap" class="btn sm" type="button">Mobile debug adapters</button>'+
    '<label for="dsMobileTask">Approved local operation</label>'+
    '<select id="dsMobileTask" class="input">'+
    '<option value="flutter_version">Flutter SDK version</option>'+
    '<option value="dart_version">Dart SDK version</option>'+
    '<option value="node_version">Node.js version</option>'+
    '<option value="npm_version">npm version</option>'+
    '<option value="flutter_doctor">Flutter doctor (may inspect SDKs)</option>'+
    '<option value="flutter_devices">Flutter device target list (no launch)</option>'+
    '<option value="flutter_pub_offline">Flutter pub get --offline</option>'+
    '<option value="flutter_analyze">Flutter analyse (--no-pub)</option>'+
    '<option value="flutter_test">Flutter widget/unit tests (--no-pub)</option>'+
    '<option value="flutter_build_web">Flutter web build (--no-pub)</option>'+
    '<option value="rn_node_check">React Native JS entry syntax</option>'+
    '<option value="rn_node_test">React Native bridge Node tests</option>'+
    '<option value="rn_npm_ci_offline">React Native npm ci --offline --ignore-scripts</option>'+
    '</select>'+
    '<label for="dsMobileTool">Pinned local executable</label>'+
    '<select id="dsMobileTool" class="input" disabled><option value="">Inspect first</option></select>'+
    '<button id="dsMobileRun" class="btn sm primary" type="button" disabled>Review risks & run</button>'+
    '<button id="dsMobileAgent" class="btn sm" type="button">Central Agent release review</button>'+
    '</div>'+
    '<p id="dsMobileStatus" class="ds-footnote" role="status" aria-live="polite">Open a local Flutter or React Native project.</p>'+
    '<div id="dsMobileResults" class="ds-php-results" role="region" tabindex="0" aria-label="Flutter and React Native manifest source SDK toolchain evidence"></div>'+
    '<p class="ds-footnote">All external tools can execute code with your OS and network permissions. Offline flags, temporary copies and ignore-scripts do not guarantee isolation; Flutter may update installed SDK caches. The Studio never launches a device, installs an app, starts Metro, opens a debugger or publishes a release automatically. The existing central Agent performs review only.</p>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const view=el("dsMobileResults");
  const project=()=>getProject()?.project||"";
  let data=null,busy=false,sequence=0;
  const toolFor={
    flutter_version:"flutter",dart_version:"dart",node_version:"node",npm_version:"npm",
    flutter_doctor:"flutter",flutter_devices:"flutter",flutter_pub_offline:"flutter",
    flutter_analyze:"flutter",flutter_test:"flutter",flutter_build_web:"flutter",
    rn_node_check:"node",rn_node_test:"node",rn_npm_ci_offline:"npm"
  };
  function line(value,warn=false){const p=document.createElement("p");p.className="ds-php-line";p.textContent=String(value);if(warn)p.dataset.severity="warning";view.append(p);}
  function header(value){const h=document.createElement("h4");h.textContent=value;view.append(h);}
  function info(text,error=false){el("dsMobileStatus").textContent=text;el("dsMobileStatus").classList.toggle("ds-error",error);}
  function tool(){return data?.toolchains?.find(x=>x.name===el("dsMobileTool").value&&x.status==="installed_not_executed");}
  function canRun(){
    if(!data||!getProject()?.trusted)return false;
    const task=el("dsMobileTask").value;
    if(tool()?.name!==toolFor[task])return false;
    if(["flutter_version","dart_version","node_version","npm_version","flutter_doctor","flutter_devices"].includes(task))return true;
    if(!data.safe_to_offer_runs)return false;
    if(task.startsWith("flutter_"))return data.project_type==="flutter"&&
      (task!=="flutter_build_web"||data.flutter.web_entry_present);
    if(task==="rn_npm_ci_offline")return data.project_type==="react_native"&&data.react_native.lock_present;
    if(task==="rn_node_check")return data.project_type==="react_native"&&
      data.files.some(x=>x.path==="index.js");
    if(task==="rn_node_test")return data.project_type==="react_native"&&
      data.files.some(x=>x.path==="test/bridge.test.cjs");
    return false;
  }
  function controls(){
    const ready=!!project()&&!busy;
    el("dsMobileInspect").disabled=!ready;
    el("dsMobileTool").disabled=!ready||!data;
    el("dsMobileRun").disabled=!ready||!canRun();
  }
  function reset(){
    ++sequence;busy=false;data=null;view.replaceChildren();
    el("dsMobileTool").replaceChildren(new Option("Inspect first",""));
    info("No project code or external tools run during inspection.");
    controls();
  }
  function render(d){
    view.replaceChildren();
    header("Project type and source checksums");
    line("Project: "+d.project_type+" · host: "+d.platform);
    line("Manifests SHA-256: "+d.manifest_sha256);
    line("Sources SHA-256: "+d.source_sha256);
    line("Flutter package: "+(d.flutter.name||"not detected")+
      " · lock: "+d.flutter.lock_present+
      " · web entry: "+d.flutter.web_entry_present);
    line("Flutter dependencies: "+(d.flutter.dependencies.join(", ")||"none"));
    line("Flutter developer dependencies: "+(d.flutter.dev_dependencies.join(", ")||"none"));
    line("React Native package: "+(d.react_native.name||"not detected")+
      " · version declaration: "+(d.react_native.version||"none"));
    line("React Native dependencies: "+(d.react_native.dependencies.join(", ")||"none"));
    line("Native targets: Android "+d.react_native.native_android_present+
      " · iOS "+d.react_native.native_ios_present+
      " · Metro config "+d.react_native.metro_config_present);
    line("Framework hints: "+(d.framework_hints.join(", ")||"none"));
    for(const warning of d.warnings)line("Review needed: "+warning,true);
    if(!d.safe_to_offer_runs)line("Package/build tasks blocked pending project review.",true);
    header("Bounded Dart/JS/TS sources and heuristics");
    for(const item of d.files.slice(0,70))
      line(item.language+" · "+item.path+
        (item.symbols.length?" · "+item.symbols.join(", "):"")+
        (item.widget_hint?" · Flutter widgets":"")+
        (item.react_native_hint?" · RN components":""));
    header("Installed SDKs and bridge/debugger prerequisites");
    const select=el("dsMobileTool");
    select.replaceChildren(new Option("Choose installed tool",""));
    for(const item of d.toolchains){
      line(item.name+" · "+item.status+(item.sha256?" · "+item.sha256:""));
      const option=new Option(item.name+" · "+item.status,item.name);
      option.disabled=item.status!=="installed_not_executed"||
        !["flutter","dart","node","npm"].includes(item.name);
      select.add(option);
    }
    line("Device targets: "+d.device_targets+" · query performed: "+d.device_query_performed);
    line(d.language_servers);
    line(d.package_manager);
    line("No app launch, emulator start, Metro server, packages, devices or deployment touched.");
  }
  async function inspect(){
    const p=project();if(!p||busy)return;const id=++sequence;
    busy=true;controls();info("Inspecting mobile source and installed tool fingerprints.");
    try{
      const result=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==sequence||p!==project()||!root.isConnected)return;
      data=result;render(result);info("Mobile inspection complete without running tools.");
    }catch(e){data=null;view.replaceChildren();info("Mobile inspection refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),task=el("dsMobileTask").value,chosen=tool(),evidence=data;
    if(!p||!chosen||busy||!canRun())return;
    if(!window.confirm("Approve UNSANDBOXED "+task+" using "+chosen.name+"? "+
      "Package managers, compilers, hooks and tests can access host files, secrets and network, "+
      "including outside a temporary copy. Offline/ignore-scripts are NOT an OS sandbox. "+
      "Device query does not authorise device connection, installation, Metro startup or release."))return;
    const id=++sequence;busy=true;controls();info("Running one consented Flutter/React Native task.");
    try{
      const result=await api(base+"/run",{
        project:p,task,tool:chosen.name,
        expected_manifest_sha256:evidence.manifest_sha256,
        expected_source_sha256:evidence.source_sha256,
        expected_toolchain_sha256:evidence.toolchain_sha256,
        expected_executable:chosen.executable,expected_sha256:chosen.sha256,
        confirmed:true,accept_unsandboxed_build_packages_and_network_risk:true
      });
      if(id!==sequence||p!==project()||!root.isConnected)return;
      view.replaceChildren();header(task+" · "+result.status);
      for(const stage of result.stages)line("Step "+stage.status+" · exit "+stage.exit_code);
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=result.output||"(no stdout)";view.append(pre);
      line("Temporary project copy deleted; no device installation or app deployment.",true);
      info("Mobile operation "+result.status+".",result.status!=="completed");
    }catch(e){info("Mobile task refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function panel(selector,name){
    const element=host.querySelector(selector);
    if(!element){info(name+" panel unavailable.",true);return;}
    element.scrollIntoView({block:"start",behavior:"smooth"});
    info("Use independently authorised "+name+" tools; no debugger started.");
  }
  function agent(){
    const shared=document.querySelector(".studio-agent-bridge");
    const action=shared?.querySelector("#studioAgentAction");
    const field=shared?.querySelector("#studioAgentMessage");
    if(!action||!field){info("Central AutoMoto Agent bridge unavailable.",true);return;}
    action.value="deployment_readiness";
    field.value=("Review Developer Studio V25 Flutter and React Native readiness: Dart and "+
      "Node versions, pub/npm package-lock provenance, Flutter widget and web/Android/iOS "+
      "runtime acceptance, RN Metro/Hermes and native bridge, mobile device targets, "+
      "debug adapters, accessibility, supply-chain review, signing, release approvals "+
      "and rollback. Review only; no package installation, device launch, Store publication "+
      "or deployment without separate approval.").slice(0,2200);
    field.dispatchEvent(new Event("input",{bubbles:true}));
    shared.scrollIntoView({block:"start",behavior:"smooth"});field.focus();
    info("Central AutoMoto Agent review draft prepared, not submitted.");
  }
  el("dsMobileInspect").onclick=()=>void inspect();
  el("dsMobileRun").onclick=()=>void run();
  el("dsMobileLsp").onclick=()=>panel("#dsLspRoot","Dart/TypeScript LSP");
  el("dsMobileDap").onclick=()=>panel("#dsAdaptersRoot","mobile debug adapter");
  el("dsMobileAgent").onclick=agent;
  for(const name of ["dsMobileTool","dsMobileTask"])el(name).addEventListener("change",controls);
  reset();return {projectChanged:reset,fileChanged:controls};
}

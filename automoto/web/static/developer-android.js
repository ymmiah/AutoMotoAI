/* Developer Studio V23 — Kotlin/JVM, Android Gradle, SDK and emulator evidence. */
export function mountDeveloperAndroid({api,host,getProject,status}) {
  const root=host.querySelector("#dsAndroidRoot");
  const base="/api/developer/studio/android";
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="Kotlin Android SDK Gradle Jetpack Compose and emulator assessment">'+
    '<div class="ds-php-head"><h3>Kotlin & Android Engineering · V23</h3>'+
    '<span class="ds-readonly">INERT INSPECTION / CONSENTED GRADLE</span></div>'+
    '<div class="ds-php-body">'+
    '<p class="ds-footnote">Inspect Kotlin/JVM, Android Gradle, Compose source hints, SDK platforms, emulator presence and Gradle/AGP version declarations. Emulator and device execution is separate, never automatic.</p>'+
    '<div class="ds-php-controls">'+
    '<button id="dsAndroidInspect" class="btn sm" type="button" disabled>Inspect Kotlin / Android</button>'+
    '<button id="dsAndroidLsp" class="btn sm" type="button">Kotlin language server</button>'+
    '<button id="dsAndroidDap" class="btn sm" type="button">Debug adapters</button>'+
    '<label for="dsAndroidTask">Approved task</label>'+
    '<select id="dsAndroidTask" class="input">'+
    '<option value="gradle_version">Installed Gradle version</option>'+
    '<option value="java_version">Installed Java version</option>'+
    '<option value="adb_version">Installed ADB version</option>'+
    '<option value="kotlin_build">Build Kotlin/JVM offline</option>'+
    '<option value="kotlin_test">Test Kotlin/JVM offline</option>'+
    '<option value="android_assemble">Assemble Android debug APK offline</option>'+
    '<option value="android_unit_test">Run Android JVM unit tests offline</option>'+
    '</select>'+
    '<label for="dsAndroidTool">Approved executable</label>'+
    '<select class="input" id="dsAndroidTool" disabled><option value="">Inspect first</option></select>'+
    '<button id="dsAndroidRun" type="button" class="btn sm primary" disabled>Review risks & run</button>'+
    '<button id="dsAndroidAgent" type="button" class="btn sm">Central Agent release review</button>'+
    '</div>'+
    '<p class="ds-footnote" role="status" aria-live="polite" id="dsAndroidStatus">Select a local Kotlin/Android project.</p>'+
    '<div id="dsAndroidResults" class="ds-php-results" role="region" tabindex="0" aria-label="Kotlin Android SDK and Gradle inspection"></div>'+
    '<p class="ds-footnote">Gradle build scripts, Kotlin plugins and tests may execute arbitrary code using local OS/network privileges. A temporary copy and --offline are not a security sandbox. Uncached dependencies may fail. Android Studio, SDK licensing, emulator, real devices, app installation and production deployment are not started by this panel.</p>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const project=()=>getProject()?.project||"";
  const results=el("dsAndroidResults");
  let state=null,busy=false,sequence=0;
  const line=(value,warning=false)=>{
    const node=document.createElement("p");node.className="ds-php-line";
    node.textContent=String(value);if(warning)node.dataset.severity="warning";results.append(node);
  };
  const heading=value=>{const h=document.createElement("h4");h.textContent=value;results.append(h);};
  const msg=(value,error=false)=>{
    el("dsAndroidStatus").textContent=value;
    el("dsAndroidStatus").classList.toggle("ds-error",error);
  };
  const selected=()=>state?.toolchains?.find(x=>x.name===el("dsAndroidTool").value&&x.status==="installed_not_executed");
  function admissible(){
    const task=el("dsAndroidTask").value,tool=selected()?.name;
    if(task==="java_version")return tool==="java";
    if(task==="gradle_version")return tool==="gradle";
    if(task==="adb_version")return tool==="adb";
    if(!state?.safe_to_offer_runs||tool!=="gradle")return false;
    if(task.startsWith("kotlin_"))return state.project_type==="kotlin_jvm";
    if(task.startsWith("android_"))return state.project_type==="android"&&
      state.android_sdk.status==="installed_not_executed"&&
      state.android_sdk.platforms.length>0&&state.android_sdk.build_tools.length>0;
    return false;
  }
  function controls(){
    const active=!!project()&&!busy;
    el("dsAndroidInspect").disabled=!active;
    el("dsAndroidTool").disabled=!active||!state;
    el("dsAndroidRun").disabled=!active||!getProject()?.trusted||!admissible();
  }
  function reset(){
    sequence++;state=null;busy=false;results.replaceChildren();
    el("dsAndroidTool").replaceChildren(new Option("Inspect before selecting tool",""));
    msg("Inspect a local project; no Gradle, Kotlin, ADB or emulator processes run automatically.");
    controls();
  }
  function render(data){
    results.replaceChildren();heading("Project, sources and fingerprint evidence");
    line("Project type: "+data.project_type+" · manifest SHA-256: "+data.manifest_sha256);
    line("Source SHA-256: "+data.source_sha256);
    line("Gradle wrapper declared: "+(data.gradle.wrapper_version||"not pinned")+
      " · Android Gradle plugin: "+(data.gradle.agp_version||"not detected")+
      " · Kotlin plugin: "+(data.gradle.kotlin_plugin_version||"not detected"));
    line("AGP/Gradle advisory: "+data.gradle.agp_gradle_advisory);
    line("Compose: "+(data.gradle.compose_detected||data.framework_hints.includes("Jetpack Compose")?
      "heuristic evidence only":"not indicated"));
    for(const w of data.warnings)line("Manual review needed: "+w,true);
    for(const file of data.files.slice(0,65))line(file.language+" · "+file.path+
      (file.symbols?.length?" · "+file.symbols.join(", "):"")+
      (file.compose_hint?" · Compose hint":""));
    heading("Installed Android SDK and emulator prerequisites");
    line("SDK: "+data.android_sdk.status+
      " · platforms "+(data.android_sdk.platforms.join(", ")||"none")+
      " · build tools "+(data.android_sdk.build_tools.join(", ")||"none"));
    line("ADB installed: "+data.android_sdk.adb_present+
      " · emulator installed: "+data.android_sdk.emulator_present);
    line("No device connection, AVD launch, app installation or emulator test occurred.");
    heading("Installed tools (SHA-256 evidence, not executed)");
    const select=el("dsAndroidTool");
    select.replaceChildren(new Option("Choose approved installed tool",""));
    for(const tool of data.toolchains){
      line(tool.name+" · "+tool.status+(tool.sha256?" · "+tool.sha256:""));
      const option=new Option(tool.name+" · "+tool.status,tool.name);
      option.disabled=tool.status!=="installed_not_executed"||
        !["gradle","java","adb"].includes(tool.name);
      select.add(option);
    }
    heading("Kotlin LSP and device debugging");
    line(data.kotlin_lsp);
    line("Existing DAP/debugger UI requires separate registration and consent.");
    line("Project inspection executed no external tools.");
  }
  async function inspect(){
    const p=project();if(!p||busy)return;const id=++sequence;busy=true;controls();
    msg("Reading bounded Kotlin, manifest and SDK metadata.");
    try{
      const data=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==sequence||p!==project()||!root.isConnected)return;
      state=data;render(data);msg("Kotlin/Android inspection complete without execution.");
    }catch(e){state=null;results.replaceChildren();msg("Inspection refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),data=state,tool=selected(),task=el("dsAndroidTask").value;
    if(!p||!data||!tool||busy||!getProject()?.trusted||!admissible())return;
    if(!window.confirm("Approve UNSANDBOXED "+task+" using "+tool.name+"? "+
      "Gradle scripts, plugins and tests can read/write your local files and access the "+
      "network as you. An offline flag and private project copy are not an OS sandbox. "+
      "This does not authorise APK deployment, emulator launch, device access or publication."))return;
    const id=++sequence;busy=true;controls();msg("Running one explicitly approved Kotlin/Android task.");
    try{
      const output=await api(base+"/run",{
        project:p,task,tool:tool.name,
        expected_manifest_sha256:data.manifest_sha256,
        expected_source_sha256:data.source_sha256,
        expected_toolchain_sha256:data.toolchain_sha256,
        expected_executable:tool.executable,expected_sha256:tool.sha256,
        confirmed:true,accept_unsandboxed_gradle_and_test_risk:true
      });
      if(id!==sequence||p!==project()||!root.isConnected)return;
      results.replaceChildren();heading(task+" · "+output.status);
      line("Exit "+output.exit_code+" · "+output.elapsed_ms+" ms");
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=output.output||"(no output)";results.append(pre);
      line("Temporary copy deleted; build/test code is not OS/network sandboxed.",true);
      msg("Kotlin/Android task "+output.status+".",output.status!=="completed");
    }catch(e){msg("Kotlin/Android task refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function panel(target,name){
    const container=host.querySelector(target);
    if(container){container.scrollIntoView({block:"start",behavior:"smooth"});
      msg("Use existing "+name+" controls with separate approval.");}
    else msg(name+" controls unavailable.",true);
  }
  function agent(){
    const block=document.querySelector(".studio-agent-bridge");
    const action=block?.querySelector("#studioAgentAction");
    const field=block?.querySelector("#studioAgentMessage");
    if(!field||!action){msg("Shared Agent review unavailable.",true);return;}
    action.value="deployment_readiness";
    field.value=("Review Developer Studio V23 Kotlin/Android readiness: SDK, Android Gradle Plugin and "+
      "Kotlin version compatibility, Jetpack Compose, Android unit/instrumented emulator "+
      "acceptance, APK signing safety, dependency provenance, LSP gaps, DAP and device prerequisites, "+
      "security, accessibility and rollback. This is review-only; no automatic emulator, "+
      "device access, app publishing or deployment. Require separate human approval.").slice(0,2200);
    field.dispatchEvent(new Event("input",{bubbles:true}));
    block.scrollIntoView({block:"start",behavior:"smooth"});field.focus();
    msg("Shared central Agent release review prepared; submit separately.");
  }
  el("dsAndroidInspect").onclick=()=>void inspect();
  el("dsAndroidRun").onclick=()=>void run();
  el("dsAndroidLsp").onclick=()=>panel("#dsLspRoot","Kotlin language-server");
  el("dsAndroidDap").onclick=()=>panel("#dsAdaptersRoot","debugger");
  el("dsAndroidAgent").onclick=agent;
  for(const id of ["dsAndroidTask","dsAndroidTool"])el(id).addEventListener("change",controls);
  reset();return {projectChanged:reset,fileChanged:controls};
}

/* Developer Studio V21 — Java/JVM evidence, JDK, Maven, Gradle and JUnit. */
export function mountDeveloperJvm({api,host,getProject,status}) {
  const base="/api/developer/studio/jvm",root=host.querySelector("#dsJvmRoot");
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="Java and JVM project inspection and explicit builds">'+
      '<div class="ds-php-head"><h3>Java & JVM Engineering · V21</h3>'+
      '<span class="ds-readonly">INERT PROJECT INSPECTION / CONSENTED TESTS</span></div>'+
      '<div class="ds-php-body">'+
        '<p class="ds-footnote">Discover supported JDKs, Maven/Gradle project structure, Java/Kotlin classes, JUnit and Spring evidence, and Gradle wrapper/JDK compatibility. Language-server navigation uses the separately approved existing LSP panel; no Java process starts during inspection.</p>'+
        '<div class="ds-php-controls">'+
          '<button class="btn sm" type="button" id="dsJvmInspect" disabled>Inspect Java/JVM project</button>'+
          '<button class="btn sm" type="button" id="dsJvmLsp">Java language server</button>'+
          '<label for="dsJvmTask">Task</label>'+
          '<select class="input" id="dsJvmTask">'+
            '<option value="jdk_version">Java runtime version</option>'+
            '<option value="javac_version">Java compiler version</option>'+
            '<option value="maven_version">Maven version</option>'+
            '<option value="gradle_version">Gradle version</option>'+
            '<option value="jdk_compile">Compile Java sources in temporary copy</option>'+
            '<option value="jdk_smoke">Compile and run one local Java smoke test</option>'+
            '<option value="maven_test">Run Maven tests offline</option>'+
            '<option value="gradle_build">Build Gradle project offline</option>'+
            '<option value="gradle_test">Run Gradle tests offline</option>'+
          '</select>'+
          '<label for="dsJvmTool">Verified tool</label>'+
          '<select class="input" id="dsJvmTool" disabled><option value="">Inspect first</option></select>'+
          '<button class="btn sm primary" type="button" id="dsJvmRun" disabled>Review risks & run</button>'+
          '<button class="btn sm" type="button" id="dsJvmAgent">Central Agent release review</button>'+
        '</div>'+
        '<p class="ds-footnote" id="dsJvmStatus" role="status" aria-live="polite">Open a local Java project to inspect.</p>'+
        '<div class="ds-php-results" id="dsJvmResults" role="region" tabindex="0" aria-label="Java/JVM project findings and execution results"></div>'+
        '<p class="ds-footnote">Maven and Gradle can execute arbitrary plugins and Java test code. The backend stages bounded source files into a temporary copy, but processes still have the local user’s OS and network permissions. Offline dependency switches do not create a sandbox; cached libraries may be missing. No automatic installation, download, deployment or new Agent is provided.</p>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const project=()=>getProject()?.project||"",out=el("dsJvmResults");
  let snapshot=null,busy=false,seq=0;
  function message(s,error=false){
    el("dsJvmStatus").textContent=s;
    el("dsJvmStatus").classList.toggle("ds-error",error);
  }
  function clear(){out.replaceChildren();}
  function line(value,warn=false){
    const p=document.createElement("p");p.className="ds-php-line";p.textContent=String(value);
    if(warn)p.dataset.severity="warning";out.append(p);
  }
  function heading(value){const h=document.createElement("h4");h.textContent=value;out.append(h);}
  const selected=()=>snapshot?.toolchains?.find(x=>x.name===el("dsJvmTool").value&&x.status==="installed_not_executed");
  function allowed(){
    const task=el("dsJvmTask").value,name=selected()?.name;
    if(task==="jdk_version")return name==="java";
    if(task==="javac_version"||task==="jdk_compile"||task==="jdk_smoke")return name==="javac";
    if(task==="maven_version")return name==="mvn";
    if(task==="gradle_version")return name==="gradle";
    if(task==="maven_test")return name==="mvn"&&snapshot?.build_system==="maven"&&snapshot.safe_to_offer_builds;
    if(task==="gradle_build"||task==="gradle_test")
      return name==="gradle"&&snapshot?.build_system==="gradle"&&snapshot.safe_to_offer_builds;
    return false;
  }
  function controls(){
    const active=!!project()&&!busy;
    el("dsJvmInspect").disabled=!active;
    el("dsJvmTool").disabled=!active||!snapshot;
    el("dsJvmRun").disabled=!active||!snapshot||!getProject()?.trusted||!allowed();
  }
  function reset(){
    ++seq;busy=false;snapshot=null;clear();
    el("dsJvmTool").replaceChildren(new Option("Inspect project first",""));
    message("Inspect a local Java/JVM workspace; no code or tools run automatically.");controls();
  }
  function present(data){
    clear();heading("Java/JVM project and version evidence");
    line("Build system: "+data.build_system+" · "+data.files.length+" scanned source files");
    line("Manifest SHA-256: "+data.manifest_sha256);
    line("Source SHA-256: "+data.source_sha256);
    if(data.maven){
      line("Maven artifact: "+data.maven.artifact+
        " · requested Java release "+(data.maven.java_release||"unspecified"));
      for(const dep of data.maven.dependencies.slice(0,15))line("Declared dependency: "+dep);
    }
    if(data.gradle){
      line("Gradle wrapper declaration: "+(data.gradle.wrapper_version||"none")+
        " · requested Java "+(data.gradle.declared_java??"unspecified"));
      line("Gradle/JDK advisory: "+data.gradle.compatibility);
    }
    heading("Language and framework evidence");
    line("Framework hints: "+(data.framework_hints.length?data.framework_hints.join(", "):"not established"));
    for(const entry of data.files.slice(0,60))
      line(entry.language+" · "+entry.path+
        (entry.classes.length?" · "+entry.classes.join(", "):"")+
        (entry.framework_hints.length?" · "+entry.framework_hints.join(", "):""));
    for(const m of data.main_classes)
      line("Runnable class candidate: "+m.class+(m.test?" (test)":""));
    for(const warning of data.warnings)line("Review needed: "+warning,true);
    if(!data.safe_to_offer_builds)line("Maven/Gradle builds disabled until review criteria pass.",true);
    heading("Installed tools, fingerprints only");
    const select=el("dsJvmTool");
    select.replaceChildren(new Option("Choose installed tool",""));
    for(const item of data.toolchains){
      line(item.name+" · "+item.status+(item.sha256?" · "+item.sha256:""));
      const opt=new Option(item.name+" · "+item.status,item.name);
      opt.disabled=item.status!=="installed_not_executed";
      select.add(opt);
    }
    line("Existing Java LSP (jdtls) uses its own approval. No tool launched by this scan.");
  }
  async function inspect(){
    const p=project();if(!p||busy)return;
    const id=++seq;busy=true;controls();message("Inspecting bounded local JVM sources and build declarations.");
    try{
      const result=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==seq||p!==project()||!root.isConnected)return;
      snapshot=result;present(result);message("JVM inspection complete. No code was executed.");
    }catch(e){snapshot=null;clear();message("JVM inspection rejected: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),task=el("dsJvmTask").value,tool=selected(),info=snapshot;
    if(!p||!tool||!info||busy||!getProject()?.trusted||!allowed())return;
    if(!window.confirm("Approve UNSANDBOXED "+tool.name+" task "+task+"? "+
      "Java compilers, annotation processors, Maven/Gradle plugins and tests can execute "+
      "arbitrary code with your filesystem and network permissions. AutoMoto copies only "+
      "bounded project inputs into a private temporary folder, but this is NOT an OS sandbox. "+
      "No publishing, installation, deployment or automatic rollback is authorised."))return;
    const id=++seq;busy=true;controls();message("Running one SHA-approved Java/JVM task.");
    try{
      const result=await api(base+"/run",{
        project:p,task,tool:tool.name,
        expected_manifest_sha256:info.manifest_sha256,
        expected_source_sha256:info.source_sha256,
        expected_toolchain_sha256:info.toolchain_sha256,
        expected_executable:tool.executable,expected_sha256:tool.sha256,
        confirmed:true,accept_unsandboxed_build_test_and_network_risk:true
      });
      if(id!==seq||p!==project()||!root.isConnected)return;
      clear();heading("JVM "+task+" · "+result.status);
      for(const step of result.stages||[])
        line(step.stage+" · "+step.status+" · exit "+step.exit_code);
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=result.output||"(no output)";out.append(pre);
      line("Temporary project copy deleted; OS-level isolation and external source immutability not certified.",true);
      message("JVM task "+result.status+".",result.status!=="completed");
    }catch(e){message("JVM execution refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function agent(){
    const panel=document.querySelector(".studio-agent-bridge"),
      action=panel?.querySelector("#studioAgentAction"),
      field=panel?.querySelector("#studioAgentMessage");
    if(!action||!field){message("Shared Agent review is unavailable.",true);return;}
    action.value="deployment_readiness";
    field.value=("Review Developer Studio V21 Java/JVM release readiness: supported JDKs, Java LSP "+
      "and language navigation, Maven/Gradle version compatibility, JUnit tests, Spring "+
      "dependencies, offline build reproducibility, software supply chain, CI, security, "+
      "accessibility and rollback. This is review-only; require separate human release "+
      "approval. Do not deploy or publish.").slice(0,2200);
    field.dispatchEvent(new Event("input",{bubbles:true}));
    panel.scrollIntoView({block:"start",behavior:"smooth"});field.focus();
    message("Shared central Agent review prepared; submit separately.");
  }
  el("dsJvmInspect").onclick=()=>void inspect();
  el("dsJvmRun").onclick=()=>void run();
  el("dsJvmAgent").onclick=agent;
  el("dsJvmLsp").onclick=()=>{
    const node=host.querySelector("#dsLspRoot");
    if(node){node.scrollIntoView({block:"start",behavior:"smooth"});
      message("Use existing Java LSP controls; separate approval required.");}
  };
  for(const name of ["dsJvmTool","dsJvmTask"])el(name).addEventListener("change",controls);
  reset();
  return {projectChanged:reset,fileChanged:()=>controls()};
}

/* V32: Fortran COBOL Ada Pascal Assembly and Visual Basic evidence. */
export function mountDeveloperLegacy({api,host,getProject,status}){
  const root=host.querySelector("#dsLegacyRoot");
  const base="/api/developer/studio/legacy";
  root.innerHTML='<section class="ds-php-panel" aria-label="Legacy and specialist language tools">'+
    '<div class="ds-php-head"><h3>Fortran, COBOL, Ada, Pascal, Assembly &amp; Visual Basic · V32</h3>'+
    '<span class="ds-readonly">INERT ANALYSIS / APPROVED COMPILATION</span></div>'+
    '<div class="ds-php-body"><p class="ds-footnote">Review legacy source, dialect uncertainty, manifest hashes, risk indicators and installed compiler fingerprints. Discovery does not run any compiler, makefile, script or executable.</p>'+
    '<div class="ds-php-controls">'+
    '<button id="dsLegacyInspect" type="button" class="btn sm" disabled>Inspect legacy sources</button>'+
    '<label for="dsLegacyTask">Fixed sample</label><select id="dsLegacyTask" class="input">'+
    '<option value="fortran_compile">Fortran</option><option value="cobol_compile">COBOL</option>'+
    '<option value="ada_compile">Ada</option><option value="pascal_compile">Pascal</option>'+
    '<option value="assembly_compile">NASM x86-64 (Linux)</option></select>'+
    '<label for="dsLegacyTool">Compiler</label><select id="dsLegacyTool" class="input">'+
    '<option value="">Inspect first</option></select>'+
    '<button id="dsLegacyCompile" type="button" class="btn sm primary" disabled>Review risk &amp; compile</button>'+
    '<button id="dsLegacyAgent" type="button" class="btn sm">Central Agent review</button></div>'+
    '<p id="dsLegacyStatus" class="ds-footnote" role="status" aria-live="polite">Select a local project.</p>'+
    '<div id="dsLegacyResults" class="ds-php-results" role="region" tabindex="0" aria-label="Legacy source and compiler evidence"></div>'+
    '<p class="ds-footnote">Compilers are UNSANDBOXED and may access the host/network. No generated binary is executed, published or deployed. Visual Basic and VBScript remain inspection-only pending verified toolchain support.</p>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const out=el("dsLegacyResults"),project=()=>getProject()?.project||"";
  const tools={fortran_compile:"gfortran",cobol_compile:"cobc",ada_compile:"gnatmake",
               pascal_compile:"fpc",assembly_compile:"nasm"};
  const fixtures={fortran_compile:"test/v32_fixture.f90",
                  cobol_compile:"test/v32_fixture.cob",ada_compile:"test/v32_fixture.adb",
                  pascal_compile:"test/v32_fixture.pas",assembly_compile:"test/v32_fixture.asm"};
  let data=null,busy=false,seq=0;
  function notice(value,bad=false){
    el("dsLegacyStatus").textContent=value;
    el("dsLegacyStatus").classList.toggle("ds-error",bad);
  }
  function heading(value){const h=document.createElement("h4");h.textContent=value;out.append(h);}
  function line(value,bad=false){const p=document.createElement("p");
    p.className="ds-php-line";p.textContent=String(value);
    if(bad)p.dataset.severity="warning";out.append(p);}
  function tool(){return data?.toolchains?.find(x=>x.name===el("dsLegacyTool").value&&x.status==="installed_not_executed");}
  function allowed(){
    if(!data||busy||!getProject()?.trusted||data.scan_incomplete||!tool())return false;
    const task=el("dsLegacyTask").value;
    return tools[task]===tool().name&&data.files.some(f=>f.path===fixtures[task]&&f.canonical_fixture);
  }
  function controls(){
    el("dsLegacyInspect").disabled=!project()||busy;
    el("dsLegacyCompile").disabled=!allowed();
  }
  function reset(){seq++;data=null;busy=false;out.replaceChildren();
    el("dsLegacyTool").replaceChildren(new Option("Inspect first",""));
    notice("Read-only inspection never invokes compilers or scripts.");controls();}
  function render(d){
    out.replaceChildren();
    heading("Project evidence");
    line("Source SHA-256: "+d.inventory_sha256);
    line("Toolchain SHA-256: "+d.toolchain_sha256);
    line("Language counts: "+JSON.stringify(d.language_counts));
    for(const w of d.warnings)line(w,true);
    heading("Inert project manifests");
    for(const m of Object.values(d.manifests))
      line(m.path+" · "+m.sha256+" · evaluated: "+m.evaluated);
    heading("Source declarations and risk signals");
    for(const f of d.files.slice(0,150)){
      line(f.language+" · "+f.path+" · "+f.sha256+
           (f.canonical_fixture?" · fixed sample":""));
      if(f.symbols.length)line("Symbols: "+f.symbols.join(", "));
      for(const risk of f.risk_signals)
        line("Potential risk: "+risk.kind+" · "+f.path+":"+risk.line,true);
    }
    heading("Available compiler fingerprints");
    const select=el("dsLegacyTool");
    select.replaceChildren(new Option("Select available compiler",""));
    for(const t of d.toolchains){
      line(t.name+" · "+t.status+(t.sha256?" · "+t.sha256:""));
      const option=new Option(t.name+" · "+t.status,t.name);
      option.disabled=t.status!=="installed_not_executed";
      select.add(option);
    }
    heading("Unsupported or uncertain capabilities");
    line(d.limitations);
    line("Source executed: "+d.source_executed+
         " · dependencies resolved: "+d.dependencies_resolved+
         " · deployment: "+d.deployment_started);
  }
  async function inspect(){
    const p=project();if(!p||busy)return;
    const id=++seq;busy=true;controls();notice("Inspecting source and manifest evidence.");
    try{
      const d=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==seq||project()!==p||!root.isConnected)return;
      data=d;render(d);notice("Inspection complete. Compilation requires trust and explicit consent.");
    }catch(error){data=null;out.replaceChildren();notice("Inspection refused: "+error.message,true);}
    finally{busy=false;controls();}
  }
  async function compile(){
    const p=project(),snapshot=data,task=el("dsLegacyTask").value,selected=tool();
    if(!p||!snapshot||!selected||busy||!allowed())return;
    if(!window.confirm("Approve UNSANDBOXED fixed "+task+" with "+selected.name+
      "? Compilers can access files and network with your privileges. "+
      "This action only compiles a copied sample; it never executes the result, installs or deploys."))return;
    const id=++seq;busy=true;controls();notice("Compiling approved copied sample.");
    try{
      const d=await api(base+"/compile",{
        project:p,task,tool:selected.name,
        expected_inventory_sha256:snapshot.inventory_sha256,
        expected_toolchain_sha256:snapshot.toolchain_sha256,
        expected_executable:selected.executable,expected_sha256:selected.sha256,
        confirmed:true,accept_unsandboxed_compiler_and_network_risk:true
      });
      if(id!==seq||project()!==p||!root.isConnected)return;
      out.replaceChildren();heading(task+" · "+d.status);
      line("Exit: "+d.exit_code+" · compiler SHA-256: "+d.compiler_sha256);
      for(const a of d.generated_artifacts)
        line("Temporary object: "+a.name+" · "+a.bytes+" bytes · "+a.sha256);
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=d.output||"(no compiler output)";out.append(pre);
      notice("Fixed sample "+d.status+". Artifacts deleted; no binary executed.",
             d.status!=="completed");
    }catch(error){notice("Compilation refused: "+error.message,true);}
    finally{busy=false;controls();}
  }
  function agent(){
    const bridge=document.querySelector(".studio-agent-bridge");
    const action=bridge?.querySelector("#studioAgentAction");
    const message=bridge?.querySelector("#studioAgentMessage");
    if(!action||!message){notice("Central Agent unavailable.",true);return;}
    action.value="deployment_readiness";
    message.value=("Review Developer Studio V32 Fortran, COBOL, Ada, Pascal, Assembly, "+
      "Visual Basic and VBScript: inert manifests, SHA provenance, compiler execution risk, "+
      "dialect uncertainty, fixed compilation, Linux acceptance, cross-platform security, "+
      "manual accessibility, supply-chain, recovery and explicit unsupported toolchains. "+
      "REVIEW ONLY; do not execute or deploy.").slice(0,2200);
    message.dispatchEvent(new Event("input",{bubbles:true}));
    bridge.scrollIntoView({block:"start",behavior:"smooth"});message.focus();
    notice("Central Agent review drafted, not submitted.");
  }
  el("dsLegacyInspect").addEventListener("click",()=>void inspect());
  el("dsLegacyCompile").addEventListener("click",()=>void compile());
  el("dsLegacyAgent").addEventListener("click",agent);
  for(const id of ["dsLegacyTask","dsLegacyTool"])el(id).addEventListener("change",controls);
  reset();return {projectChanged:reset,fileChanged:controls};
}

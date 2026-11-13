/* Developer Studio V28 — scientific provenance, notebook preview and gated experiments. */
export function mountDeveloperScience({api,host,getProject,status}){
  const root=host.querySelector("#dsScienceRoot");
  const base="/api/developer/studio/science";
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="R Julia MATLAB Octave notebook and reproducible experiment workspace">'+
    '<div class="ds-php-head"><h3>Scientific Programming & Reproducibility · V28</h3>'+
    '<span class="ds-readonly">SOURCE + DATA PROVENANCE / CONSENTED COMPUTATION</span></div>'+
    '<div class="ds-php-body">'+
    '<p class="ds-footnote">Inspect R, Julia, MATLAB/Octave source, CSV data, declared package versions and Jupyter notebook cells without executing them. Run the approved experiment using installed R, Julia or Octave, compare its result against a separate numerical reference, and review the optional R PNG plot.</p>'+
    '<div class="ds-php-controls">'+
    '<button id="dsScienceInspect" type="button" class="btn sm" disabled>Inspect reproducibility</button>'+
    '<label for="dsScienceLanguage">Installed scientific runtime</label>'+
    '<select id="dsScienceLanguage" class="input">'+
    '<option value="r">R / Rscript</option>'+
    '<option value="julia">Julia</option>'+
    '<option value="octave">GNU Octave (MATLAB-compatible subset)</option>'+
    '</select>'+
    '<label for="dsScienceTask">Explicit action</label>'+
    '<select id="dsScienceTask" class="input">'+
    '<option value="version">Read installed runtime version</option>'+
    '<option value="reproduce">Reproduce SHA-pinned numerical experiment</option>'+
    '</select>'+
    '<button id="dsScienceRun" class="btn sm primary" type="button" disabled>Review risk & run</button>'+
    '<button id="dsScienceAgent" class="btn sm" type="button">Central Agent research review</button>'+
    '</div>'+
    '<p id="dsScienceStatus" class="ds-footnote" role="status" aria-live="polite">Open an approved local research project.</p>'+
    '<div id="dsScienceResults" class="ds-php-results" role="region" tabindex="0" aria-label="Scientific provenance runtime and experiment results"></div>'+
    '<p class="ds-footnote">A successful fixture does not certify a scientific conclusion or all packages. R, Julia and Octave code runs UNSANDBOXED with host file and network permissions, even from a temporary project copy. MATLAB is discovered only; notebooks and package manifests are never executed. No online package installation, remote deployment or report publication is permitted.</p>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id),out=el("dsScienceResults");
  const project=()=>getProject()?.project||"";
  let data=null,seq=0,busy=false;
  const executable={r:"Rscript",julia:"julia",octave:"octave"};
  function heading(s){const h=document.createElement("h4");h.textContent=s;out.append(h);}
  function line(s,warn=false){
    const p=document.createElement("p");p.className="ds-php-line";
    p.textContent=String(s);if(warn)p.dataset.severity="warning";out.append(p);
  }
  function info(s,error=false){el("dsScienceStatus").textContent=s;el("dsScienceStatus").classList.toggle("ds-error",error);}
  function tool(){return data?.toolchains?.find(x=>
    x.name===executable[el("dsScienceLanguage").value]&&x.status==="installed_not_executed");
  }
  function canRun(){
    if(!project()||!getProject()?.trusted||!data||busy||!tool())return false;
    if(el("dsScienceTask").value==="version")return true;
    const lang=el("dsScienceLanguage").value;
    return data.safe_to_offer_reproduction&&!!data.experiment?.source_sha256?.[lang];
  }
  function controls(){
    el("dsScienceInspect").disabled=!project()||busy;
    el("dsScienceRun").disabled=!canRun();
  }
  function reset(){
    ++seq;data=null;busy=false;out.replaceChildren();
    info("Inspection does not run code, install packages or read notebook outputs.");
    controls();
  }
  function render(d){
    out.replaceChildren();heading("Reproducible source, data and environment");
    line("Input inventory SHA-256: "+d.inventory_sha256);
    line("Toolchain inventory SHA-256: "+d.toolchain_sha256);
    if(d.experiment){
      const e=d.experiment;
      line("Experiment: "+e.name+" · "+e.dataset+" · column "+e.column);
      line("Manifest: "+e.manifest_sha256);
      line("Dataset: "+e.data_sha256);
      line("Independent reference: count="+e.calculated_count+
        " sum="+e.calculated_sum+" mean="+e.calculated_mean);
      line("Manifest expected data matches: "+e.expected_matches_data,!e.expected_matches_data);
      for(const [lang,sha] of Object.entries(e.source_sha256))
        line(lang+" source SHA-256: "+(sha||"missing"),!sha);
    }else line("No approved root experiment.json or data available.",true);
    for(const warning of d.warnings)line("Blocked: "+warning,true);
    heading("Scientific files and declared packages (not executed)");
    for(const file of d.files.slice(0,80))
      line(file.kind+" · "+file.path+" · "+file.sha256);
    for(const [name,info] of Object.entries(d.packages.locks))
      line("Package metadata: "+name+" · SHA256 "+info.sha256+
        " · runtime packages unverified"+
        (Object.keys(info.declared_versions||{}).length?
          " · "+JSON.stringify(info.declared_versions):""));
    heading("Jupyter notebooks — metadata only");
    if(!d.notebooks.length)line("No supported bounded .ipynb found.");
    for(const notebook of d.notebooks)
      line(notebook.path+" · cells "+notebook.cells+
        " · code cells "+notebook.code_cells+
        " · kernel "+(notebook.kernel_declared||"unknown")+
        " · never executed or trusted saved outputs");
    heading("Installed runtimes (SHA fingerprints, versions not queried)");
    for(const t of d.toolchains)
      line(t.name+" · "+t.status+(t.sha256?" · "+t.sha256:""));
    line(d.matlab);
    line(d.plot_engine);
    line("Inspection executed source="+d.source_executed+
      " · packages installed="+d.package_manager_invoked+
      " · notebook executed="+d.notebook_executed);
  }
  async function inspect(){
    const p=project();if(!p||busy)return;const id=++seq;
    busy=true;controls();info("Inspecting scientific inputs without execution.");
    try{
      const result=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==seq||p!==project()||!root.isConnected)return;
      data=result;render(result);info("Scientific source and data inspection complete.");
    }catch(e){data=null;out.replaceChildren();info("Scientific inspection refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    if(!canRun())return;
    const p=project(),snapshot=data,lang=el("dsScienceLanguage").value,task=el("dsScienceTask").value,exe=tool();
    if(!window.confirm("Approve UNSANDBOXED "+task+" using "+exe.name+"? "+
      "Scientific scripts can read secrets, modify files outside the temporary copy and access your network. "+
      "Only the fixed reviewed experiment path will run, but this does not provide OS isolation. "+
      "The tool will not install packages, run Jupyter cells or publish results."))return;
    const id=++seq;busy=true;controls();info("Running an explicitly approved scientific task.");
    try{
      const response=await api(base+"/run",{
        project:p,task,language:lang,tool:exe.name,
        expected_inventory_sha256:snapshot.inventory_sha256,
        expected_toolchain_sha256:snapshot.toolchain_sha256,
        expected_executable:exe.executable,expected_sha256:exe.sha256,
        confirmed:true,accept_unsandboxed_scientific_code_and_network_risk:true
      });
      if(id!==seq||p!==project()||!root.isConnected)return;
      out.replaceChildren();
      heading(lang.toUpperCase()+" · "+task+" · "+response.status);
      line("Interpreter SHA-256: "+response.tool_sha256);
      line("Input inventory SHA-256: "+response.inventory_sha256);
      line("Installed runtime version response: "+response.tool_version_output.trim());
      if(task==="reproduce"){
        line("Numerical result independently reproduced: "+response.reproduced,!response.reproduced);
        line("Source SHA-256: "+response.source_sha256);
        line("Dataset SHA-256: "+response.data_sha256);
        line("Experiment manifest SHA-256: "+response.manifest_sha256);
        for(const [name,entry] of Object.entries(response.package_locks||{}))
          line("Declared environment lock: "+name+" · "+entry.sha256+
          " (not evidence installed packages match)");
        if(response.plot_png_sha256&&response.plot_base64){
          heading("R numerical plot — temporary output preview");
          const image=document.createElement("img");
          image.src="data:image/png;base64,"+response.plot_base64;
          image.alt="Validated PNG plot generated by the approved R numerical fixture";
          image.loading="lazy";image.style.maxWidth="100%";image.style.height="auto";
          out.append(image);
          line("Generated PNG SHA-256: "+response.plot_png_sha256);
        }
      }
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=response.output||"(no captured output)";out.append(pre);
      line("Temporary project deleted="+response.temporary_project_deleted+
        " · notebook executed="+response.notebook_executed+
        " · deployment started="+response.deployment_started);
      info("Scientific operation "+response.status+".",response.status!=="completed");
    }catch(e){info("Scientific task refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function agent(){
    const shared=document.querySelector(".studio-agent-bridge");
    const action=shared?.querySelector("#studioAgentAction");
    const field=shared?.querySelector("#studioAgentMessage");
    if(!action||!field){info("Central AutoMoto Agent unavailable.",true);return;}
    action.value="deployment_readiness";
    field.value=("Review Developer Studio V28 scientific reproducibility: R, Julia, "+
      "MATLAB/Octave interpreter versions, source/CSV/package locks SHA-256, "+
      "independently verified numerical outputs, R PNG plotting, Jupyter "+
      "metadata-only inspection, statistical limitations, package supply chain, "+
      "OS/network sandbox absence, Windows/macOS/Linux acceptance and ethical "+
      "research integrity. Require human review before publication or deployment. "+
      "No autonomous package installs, notebook execution or experiment launches.").slice(0,2200);
    field.dispatchEvent(new Event("input",{bubbles:true}));
    shared.scrollIntoView({block:"start",behavior:"smooth"});field.focus();
    info("Review draft prepared in the existing central Agent; not submitted.");
  }
  el("dsScienceInspect").onclick=()=>void inspect();
  el("dsScienceRun").onclick=()=>void run();
  el("dsScienceAgent").onclick=agent;
  for(const id of ["dsScienceLanguage","dsScienceTask"])el(id).addEventListener("change",controls);
  reset();return {projectChanged:reset,fileChanged:controls};
}

/* Developer Studio V16: PHP/WordPress with central-agent release readiness. */
export function mountDeveloperPHP({api,host,getProject,editor,status}) {
  const root=host.querySelector("#dsPhpRoot"),BASE="/api/developer/studio/php";
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="PHP, Composer and WordPress security workflows">'+
      '<div class="ds-php-head"><h3>PHP & WordPress · V16</h3><span class="ds-readonly">SAFE REVIEW / CONSENTED RUNS</span></div>'+
      '<div class="ds-php-body">'+
        '<p class="ds-footnote">Review Composer, Laravel/Symfony, WordPress plugin headers and hook contracts. Security findings are lexical warnings, not a complete vulnerability scan. Existing source is never changed by inspection or patch preview.</p>'+
        '<div class="ds-php-controls">'+
          '<button class="btn sm" type="button" id="dsPhpInspect" disabled>Inspect PHP project</button>'+
          '<label for="dsPhpPath">Plugin/source</label>'+
          '<input class="input" id="dsPhpPath" placeholder="my-plugin.php" maxlength="1024" spellcheck="false">'+
          '<button class="btn sm" type="button" id="dsPhpPatch" disabled>Preview safe WordPress fix</button>'+
        '</div>'+
        '<div class="ds-php-controls">'+
          '<label for="dsPhpTask">Task</label>'+
          '<select class="input" id="dsPhpTask">'+
            '<option value="version">Installed PHP/Composer version</option>'+
            '<option value="lint">PHP -l syntax check</option>'+
            '<option value="composer_validate">Composer validate</option>'+
            '<option value="phpunit">Project PHPUnit tests</option>'+
            '<option value="phpstan">PHPStan analysis</option>'+
            '<option value="psalm">Psalm analysis</option>'+
          '</select>'+
          '<label for="dsPhpTool">Approved tool</label>'+
          '<select class="input" id="dsPhpTool" disabled><option value="">Inspect project first</option></select>'+
          '<button class="btn sm primary" id="dsPhpRun" type="button" disabled>Review risks & run</button>'+
          '<button class="btn sm" id="dsPhpAgent" type="button">Central agent release review</button>'+
        '</div>'+
        '<p class="ds-footnote" id="dsPhpStatus" role="status" aria-live="polite">Open a project to inspect PHP and WordPress.</p>'+
        '<div class="ds-php-results" id="dsPhpResults" role="region" aria-label="PHP and WordPress diagnostics" tabindex="0"></div>'+
        '<p class="ds-footnote">Every real tool runs as your current OS user and is not sandboxed. PHPUnit and project-local tools may modify files and use the network. WordPress fix previews need human code review, V2 checksum-guarded source saving and real PHP/WordPress tests. All release-readiness hand-offs go through the same central AutoMoto Agent; no release or deployment happens automatically.</p>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id);
  let snapshot=null,busy=false,seq=0;
  const project=()=>getProject()?.project||"";
  function message(s,bad=false){el("dsPhpStatus").textContent=s;el("dsPhpStatus").classList.toggle("ds-error",bad);}
  function line(str,warn=false){
    const p=document.createElement("p");p.className="ds-php-line";
    if(warn)p.dataset.severity="warning";
    p.textContent=String(str);el("dsPhpResults").append(p);
  }
  function heading(str){const h=document.createElement("h4");h.textContent=str;el("dsPhpResults").append(h);}
  function clear(){el("dsPhpResults").replaceChildren();}
  function chosen(){return snapshot?.toolchains?.find(x=>x.name===el("dsPhpTool").value&&x.status==="installed_not_executed");}
  function controls(){
    const ready=!!project()&&!busy,task=el("dsPhpTask").value;
    el("dsPhpInspect").disabled=!ready;
    el("dsPhpPatch").disabled=!ready||!snapshot||!el("dsPhpPath").value.trim();
    el("dsPhpTool").disabled=!ready||!snapshot;
    el("dsPhpPath").disabled=!ready;
    const correct=task==="composer_validate"?chosen()?.name==="composer":
      chosen()?.name==="php"||task==="version"&&chosen()?.name==="composer";
    el("dsPhpRun").disabled=!ready||!snapshot||!getProject()?.trusted||!correct||
      task==="lint"&&!el("dsPhpPath").value.trim();
  }
  function reset(){
    seq++;busy=false;snapshot=null;clear();
    el("dsPhpPath").value="";
    el("dsPhpTool").replaceChildren(new Option("Inspect project first",""));
    message("Open a local project and inspect its PHP/WordPress files.");
    controls();
  }
  function show(data){
    clear();heading("Composer and frameworks");
    const c=data.composer;
    line(c.present?"composer.json SHA-256: "+data.composer_sha256:
      "No composer.json; PHP syntax and WordPress review can still be used.");
    if(c.name)line("Package: "+c.name);
    if(c.php_requirement)line("Declared PHP requirement: "+c.php_requirement+" (not an installed-version check)");
    for(const fw of c.frameworks||[])line("Declared: "+fw+" (installation not verified)");
    line(data.php_files.length+" PHP source files discovered"+(data.scan_truncated?" · scan truncated":""));
    heading("WordPress plugin interfaces");
    for(const item of data.wordpress_plugins||[]){
      line((item.header.plugin_name||"Plugin")+" · "+item.path+" · SHA-256 "+item.sha256);
      for(const hook of item.hooks)line("Hook preserved for review: "+hook.type+" · "+hook.identifier);
    }
    heading("Security findings — human review required");
    if(!data.findings?.length)line("No lexical patterns flagged in scanned files. This does not certify plugin safety.");
    for(const f of data.findings||[])line(f.path+":"+f.line+" · "+f.code+" · "+f.message,true);
    heading("Installed tools · inspect only");
    for(const t of data.toolchains||[])line(t.name+": "+t.status+(t.sha256?" · SHA-256 "+t.sha256:""));
  }
  async function inspect(){
    const p=project(),id=++seq;if(!p||busy)return;
    busy=true;controls();message("Inspecting local PHP files and tool hashes without running code.");
    try{
      const data=await api(BASE+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==seq||p!==project()||!root.isConnected)return;
      snapshot=data;
      const select=el("dsPhpTool"),previous=select.value;select.replaceChildren(new Option("Choose an approved tool",""));
      for(const t of data.toolchains||[]){
        const option=new Option(t.name+" · "+t.status,t.name);
        option.disabled=t.status!=="installed_not_executed";
        select.add(option);
      }
      if(data.toolchains.some(t=>t.name===previous&&t.status==="installed_not_executed"))select.value=previous;
      show(data);
      message("Project inspected. Nothing was executed or modified. Tool runs require separate approval.");
    }catch(e){snapshot=null;clear();message("PHP project inspection failed: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function fileVersion(path){
    const p=project();
    if(!p||!path)throw Error("Choose an existing PHP file in this project.");
    return await api("/api/developer/studio/file?"+new URLSearchParams({project:p,path}));
  }
  async function patch(){
    const p=project(),path=el("dsPhpPath").value.trim(),id=++seq;
    if(!p||!path||busy)return;
    busy=true;controls();
    message("Checking source fingerprint and preparing a copy-only WordPress security patch.");
    try{
      const source=await fileVersion(path);
      const result=await api(BASE+"/patch-preview",{
        project:p,path,expected_sha256:source.sha256});
      if(p!==project()||id!==seq)return;
      clear();heading("Exact WordPress patch preview · NOT saved");
      line("Original SHA-256: "+result.source_sha256);
      line("Proposed SHA-256: "+result.patched_sha256);
      line(result.mitigation+". "+result.preserved_hooks+" hook declaration(s) preserved.");
      const text=document.createElement("textarea");text.className="input ds-php-source";
      text.readOnly=true;text.rows=11;text.value=result.patched_text;
      text.setAttribute("aria-label","Read-only proposed WordPress plugin source");
      el("dsPhpResults").append(text);
      const copy=document.createElement("button");copy.className="btn sm";copy.type="button";
      copy.textContent="Copy for guarded V2 editor review";
      copy.onclick=()=>{text.focus();text.select();
        if(navigator.clipboard?.writeText)void navigator.clipboard.writeText(text.value).catch(()=>{});
      };
      el("dsPhpResults").append(copy);
      line("No file changed. Open this same plugin in the V2 editor, review the exact diff and save using its original checksum, then run PHP -l and the plugin's tests.",true);
      message("Proposed limited WordPress fix previewed, not applied or deployed.");
    }catch(e){message("Safe fix unavailable: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),tool=chosen(),task=el("dsPhpTask").value,path=el("dsPhpPath").value.trim();
    if(!p||busy||!tool||!snapshot||!getProject()?.trusted)return;
    let version=null;
    if(task==="lint"){
      try{version=await fileVersion(path);}
      catch(e){message("Cannot fingerprint PHP source: "+e.message,true);return;}
    }
    if(!window.confirm("Approve REAL, UNSANDBOXED "+tool.name+" execution for "+task+
      " in the currently trusted project? Project tools may run PHP code, change files, access secrets or the network. "+
      "Only the approved tool is pinned by SHA-256. No OS sandbox or rollback is provided. "+
      "This does not grant Agent deployment approval."))return;
    const id=++seq;busy=true;controls();message("Running approved PHP task with bounded output and time.");
    try{
      const req={project:p,task,tool:tool.name,
        expected_manifest_sha256:snapshot.composer_sha256,
        expected_executable:tool.executable,expected_sha256:tool.sha256,
        confirmed:true,accept_unsandboxed_execution_and_write_risk:true};
      if(task==="lint"){req.path=path;req.expected_source_sha256=version.sha256;}
      const response=await api(BASE+"/run",req);
      if(id!==seq||p!==project()||!root.isConnected)return;
      clear();heading(task+" · "+response.status);
      line("Exit: "+response.exit_code+" · "+response.elapsed_ms+"ms · "+tool.name);
      if(response.php_version)line("Reported PHP version "+response.php_version);
      if(response.timed_out||response.output_truncated)
        line("Tool stopped due to timeout or output limit; output may be incomplete.",true);
      for(const diag of response.diagnostics||[])line(diag.message,true);
      const pre=document.createElement("pre");pre.className="ds-php-output";pre.textContent=response.output||"(no output)";
      el("dsPhpResults").append(pre);
      line("Tool execution is not an Agent deployment, security certification or a verified release.",true);
      message("PHP tool "+response.status+" (exit "+response.exit_code+").",
        response.status!=="completed");
    }catch(e){message("PHP tool rejected: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function agent(){
    const panel=document.querySelector(".studio-agent-bridge");
    const select=panel?.querySelector("#studioAgentAction");
    const messageField=panel?.querySelector("#studioAgentMessage");
    if(!panel||!select||!messageField){
      message("Central Agent panel is unavailable. Verify its shared Studio connection before requesting deployment review.",true);
      return;
    }
    select.value="deployment_readiness";
    const p=project(),path=el("dsPhpPath").value.trim();
    messageField.value=("Review deployment readiness for PHP/WordPress in Developer Studio. "+
      "Require real PHP lint, WordPress plugin security and hook/settings regression tests, "+
      "Composer dependency review, rollback and independent human release approval. "+
      "No automatic deployment or file writes. "+
      (p?"Local approved project is open; use its existing project trust controls. ":"")+
      (path?"Selected source path for review: "+path.slice(0,150):"")).slice(0,2200);
    messageField.dispatchEvent(new Event("input",{bubbles:true}));
    panel.scrollIntoView({block:"start",behavior:"smooth"});
    messageField.focus();
    message("Central agent deployment-readiness form prepared. Send separately with your confirmation.");
  }
  function fileChanged(path){
    if(path?.toLowerCase().endsWith(".php"))el("dsPhpPath").value=path;
    controls();
  }
  el("dsPhpInspect").onclick=()=>void inspect();
  el("dsPhpPatch").onclick=()=>void patch();
  el("dsPhpRun").onclick=()=>void run();
  el("dsPhpAgent").onclick=agent;
  for(const name of ["dsPhpTask","dsPhpTool"])el(name).addEventListener("change",controls);
  el("dsPhpPath").addEventListener("input",controls);
  reset();
  return {projectChanged:reset,fileChanged};
}

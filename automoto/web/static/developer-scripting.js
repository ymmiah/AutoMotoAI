/* Developer Studio V27 — Ruby/Lua/Perl/Groovy evidence and approved tools. */
export function mountDeveloperScripting({api,host,getProject,status}){
  const root=host.querySelector("#dsScriptingRoot");
  const base="/api/developer/studio/scripting";
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="Ruby Lua Perl and Groovy development adapters">'+
    '<div class="ds-php-head"><h3>Ruby, Lua, Perl & Groovy · V27</h3>'+
    '<span class="ds-readonly">STATIC PROJECT EVIDENCE / EXPLICIT TOOL APPROVAL</span></div>'+
    '<div class="ds-php-body">'+
    '<p class="ds-footnote">Inspect project sources, local package declarations and installed interpreters without execution. Approve fixed syntax, canonical fixture tests and supported Ruby/Lua lints individually. Package managers are not run or installed automatically.</p>'+
    '<div class="ds-php-controls">'+
    '<button id="dsScriptingInspect" type="button" class="btn sm" disabled>Inspect scripting project</button>'+
    '<label for="dsScriptingFile">Inspected source</label>'+
    '<select id="dsScriptingFile" class="input" disabled><option value="">Inspect first</option></select>'+
    '<label for="dsScriptingTask">Fixed operation</label>'+
    '<select id="dsScriptingTask" class="input">'+
    '<option value="version">Installed interpreter/tool version</option>'+
    '<option value="ruby_syntax">Ruby syntax check</option>'+
    '<option value="lua_syntax">Lua bytecode parser (no execute)</option>'+
    '<option value="perl_syntax">Perl syntax check (BEGIN risk)</option>'+
    '<option value="groovy_compile">Groovy compile to temp folder (AST risk)</option>'+
    '<option value="ruby_test">Ruby canonical fixture test</option>'+
    '<option value="lua_test">Lua canonical fixture test</option>'+
    '<option value="perl_test">Perl canonical fixture test</option>'+
    '<option value="groovy_test">Groovy canonical fixture test</option>'+
    '<option value="ruby_lint">RuboCop lint (installed tool)</option>'+
    '<option value="lua_lint">Luacheck lint (installed tool)</option>'+
    '<option value="ruby_bundle_check">Bundler lockfile check (evaluates Gemfile)</option>'+
    '</select>'+
    '<label for="dsScriptingTool">Pinned installed binary</label>'+
    '<select id="dsScriptingTool" class="input" disabled><option value="">Inspect first</option></select>'+
    '<button type="button" id="dsScriptingRun" class="btn sm primary" disabled>Review risk & run</button>'+
    '<button type="button" id="dsScriptingAgent" class="btn sm">Central Agent release review</button>'+
    '</div>'+
    '<p id="dsScriptingStatus" role="status" aria-live="polite" class="ds-footnote">Open a local project to inspect source and packages.</p>'+
    '<div id="dsScriptingResults" class="ds-php-results" role="region" tabindex="0" aria-label="Scripting project inventory and formatter hints"></div>'+
    '<p class="ds-footnote">External interpreters are UNSANDBOXED. Perl -c may run BEGIN blocks; Groovy AST transformations and Ruby Bundler manifests may execute code. Tests and lint plugins may read files, secrets or network and modify host state. Never approve untrusted projects. Ruby and Lua lint is optional; Perl/Groovy external formatting remains discovery-only.</p>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id),out=el("dsScriptingResults");
  const project=()=>getProject()?.project||"";
  const fixed={
    ruby_syntax:"ruby",lua_syntax:"luac",perl_syntax:"perl",groovy_compile:"groovyc",
    ruby_test:"ruby",lua_test:"lua",perl_test:"perl",groovy_test:"groovy",
    ruby_lint:"rubocop",lua_lint:"luacheck",ruby_bundle_check:"bundle"
  };
  const languages={
    ruby_syntax:"ruby",lua_syntax:"lua",perl_syntax:"perl",groovy_compile:"groovy",
    ruby_test:"ruby",lua_test:"lua",perl_test:"perl",groovy_test:"groovy",
    ruby_lint:"ruby",lua_lint:"lua"
  };
  let data=null,sequence=0,busy=false;
  function title(v){const h=document.createElement("h4");h.textContent=v;out.append(h);}
  function line(v,warn=false){const p=document.createElement("p");p.className="ds-php-line";p.textContent=String(v);if(warn)p.dataset.severity="warning";out.append(p);}
  function info(v,bad=false){el("dsScriptingStatus").textContent=v;el("dsScriptingStatus").classList.toggle("ds-error",bad);}
  function source(){return data?.files?.find(x=>x.path===el("dsScriptingFile").value);}
  function tool(){return data?.toolchains?.find(x=>x.name===el("dsScriptingTool").value&&x.status==="installed_not_executed");}
  function allowed(){
    if(!data||!getProject()?.trusted||data.scan_incomplete||!tool())return false;
    const task=el("dsScriptingTask").value,entry=source();
    if(task==="version")return true;
    if(fixed[task]!==tool().name)return false;
    if(task==="ruby_bundle_check")return !!data.manifests.Gemfile&&!!data.manifests["Gemfile.lock"];
    if(!entry||entry.language!==languages[task])return false;
    if(task.endsWith("_test"))return entry.fixture_test_path;
    return true;
  }
  function controls(){
    const ready=!!project()&&!busy;
    el("dsScriptingInspect").disabled=!ready;
    el("dsScriptingFile").disabled=!ready||!data;
    el("dsScriptingTool").disabled=!ready||!data;
    el("dsScriptingRun").disabled=!ready||!allowed();
  }
  function reset(){
    ++sequence;data=null;busy=false;out.replaceChildren();
    el("dsScriptingFile").replaceChildren(new Option("Inspect first",""));
    el("dsScriptingTool").replaceChildren(new Option("Inspect first",""));
    info("No project scripts, package manifests or interpreters execute during inspection.");
    controls();
  }
  function render(d){
    out.replaceChildren();
    title("Language and package inventory (no manifest evaluation)");
    line("Language counts: "+JSON.stringify(d.language_counts)+" · platform: "+d.platform);
    line("Inventory SHA-256: "+d.inventory_sha256);
    line("Toolchain SHA-256: "+d.toolchain_sha256);
    for(const language of ["ruby","lua","perl","groovy"])
      line(language+" declared packages: "+(d.packages[language].join(", ")||"none found"));
    line("Metadata parsed only: "+d.packages.parsed_only+" · no install: "+!d.packages.install_started);
    for(const warning of d.warnings)line("Review required: "+warning,true);
    title("Static formatter hints and source symbols");
    const select=el("dsScriptingFile");
    select.replaceChildren(new Option("Choose source",""));
    for(const f of d.files.slice(0,125)){
      select.add(new Option(f.language+" · "+f.path+(f.fixture_test_path?" · canonical test":""),f.path));
      line(f.language+" · "+f.path+" · "+f.sha256+(f.symbols.length?" · "+f.symbols.join(", "):""),f.risk_signals.length>0);
      for(const risk of f.risk_signals)line("Heuristic warning: "+risk.kind+" · line "+risk.line,true);
      for(const style of f.style_hints.slice(0,4))line("Style: "+f.path+":"+style.line+" · "+style.kind);
    }
    title("Installed executables — fingerprints, not versions");
    const tools=el("dsScriptingTool");
    tools.replaceChildren(new Option("Choose installed tool",""));
    for(const f of d.toolchains){
      line(f.name+" · "+f.status+(f.sha256?" · "+f.sha256:""));
      const option=new Option(f.name+" · "+f.status,f.name);
      option.disabled=f.status!=="installed_not_executed";
      tools.add(option);
    }
    title("Release/safety boundaries");
    line(d.formatting);
    line(d.test_policy);
    line("Inspection code executed: "+d.scripts_executed+" · network started: "+d.network_access_started+" · deployed: "+d.deployment_started);
  }
  async function inspect(){
    const p=project();if(!p||busy)return;
    const id=++sequence;busy=true;controls();info("Reading bounded Ruby/Lua/Perl/Groovy project evidence.");
    try{
      const result=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==sequence||p!==project()||!root.isConnected)return;
      data=result;render(result);info("Scripting language inventory complete without executing code.");
    }catch(e){data=null;out.replaceChildren();info("Scripting inspection refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),snapshot=data,task=el("dsScriptingTask").value,exe=tool(),selected=source();
    if(!p||!snapshot||!exe||busy||!allowed())return;
    if(!window.confirm("Approve UNSANDBOXED "+task+" with "+exe.name+"? "+
      "Tests, package checkers and even some syntax/formatter tools can run project code, "+
      "read local secrets, access the network or change files outside the temporary copy. "+
      "Only fixed commands are offered. No general scripts or production deployment is approved."))return;
    const id=++sequence;busy=true;controls();info("Executing individually approved scripting task.");
    try{
      const result=await api(base+"/run",{
        project:p,task,tool:exe.name,
        source:task==="version"||task==="ruby_bundle_check"?"":selected.path,
        expected_inventory_sha256:snapshot.inventory_sha256,
        expected_toolchain_sha256:snapshot.toolchain_sha256,
        expected_executable:exe.executable,expected_sha256:exe.sha256,
        confirmed:true,accept_unsandboxed_script_and_package_risk:true
      });
      if(id!==sequence||p!==project()||!root.isConnected)return;
      out.replaceChildren();title(task+" · "+result.status);
      line("Exit code: "+result.exit_code+" · temporary copy deleted: "+result.temporary_copy_deleted);
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=result.output||"(no output)";out.append(pre);
      info("Approved task "+result.status+".",result.status!=="completed");
    }catch(e){info("Scripting task refused: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function agent(){
    const shared=document.querySelector(".studio-agent-bridge");
    const action=shared?.querySelector("#studioAgentAction");
    const field=shared?.querySelector("#studioAgentMessage");
    if(!action||!field){info("Shared AutoMoto Agent bridge unavailable.",true);return;}
    action.value="deployment_readiness";
    field.value=("Review Developer Studio V27 Ruby, Lua, Perl and Groovy readiness: "+
      "Gemfile/Gemfile.lock and Bundler, LuaRocks, cpanfile, Gradle dependencies, "+
      "real installed interpreter versions, syntax/test fixtures, optional RuboCop and "+
      "Luacheck, formatter limitations, Perl BEGIN and Groovy AST transformation risks, "+
      "unsandboxed process access, Windows/macOS/Linux CI, security, accessibility, "+
      "rollback and human approval. Review only; no package installation, arbitrary "+
      "script execution or deployment authorised.").slice(0,2200);
    field.dispatchEvent(new Event("input",{bubbles:true}));
    shared.scrollIntoView({block:"start",behavior:"smooth"});field.focus();
    info("Existing central Agent review draft prepared, not submitted.");
  }
  el("dsScriptingInspect").onclick=()=>void inspect();
  el("dsScriptingRun").onclick=()=>void run();
  el("dsScriptingAgent").onclick=agent;
  for(const id of ["dsScriptingFile","dsScriptingTask","dsScriptingTool"])
    el(id).addEventListener("change",controls);
  reset();return {projectChanged:reset,fileChanged:controls};
}

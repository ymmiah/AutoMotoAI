/* Developer Studio V26 — shell/automation evidence and restricted fixture diagnostics. */
export function mountDeveloperShell({api,host,getProject,status}){
  const base="/api/developer/studio/shell";
  const root=host.querySelector("#dsShellRoot");
  root.innerHTML=
    '<section class="ds-php-panel" aria-label="Bash Zsh Fish PowerShell and Batch security inspection">'+
    '<div class="ds-php-head"><h3>Shell & Automation · V26</h3>'+
    '<span class="ds-readonly">INERT SCAN / FIXED LITERAL FIXTURES</span></div>'+
    '<div class="ds-php-body">'+
    '<p class="ds-footnote">Inspect Bash, Zsh, Fish, PowerShell and Windows Batch without running them. Flag dangerous patterns, review script fingerprints and request supported syntax checks or a pre-defined literal-output smoke fixture. General arbitrary script execution is prohibited.</p>'+
    '<div class="ds-php-controls">'+
    '<button id="dsShellInspect" class="btn sm" type="button" disabled>Inspect shell scripts</button>'+
    '<label for="dsShellFile">Script from approved inventory</label>'+
    '<select id="dsShellFile" class="input" disabled><option value="">Inspect first</option></select>'+
    '<label for="dsShellTask">Approved operation</label>'+
    '<select id="dsShellTask" class="input">'+
    '<option value="syntax">Parse / syntax check (no script execution)</option>'+
    '<option value="shellcheck">ShellCheck Bash/sh diagnostics</option>'+
    '<option value="fixture_smoke">Run fixed literal-output smoke fixture</option>'+
    '<option value="version">Installed interpreter version</option>'+
    '</select>'+
    '<label for="dsShellTool">SHA-pinned installed interpreter</label>'+
    '<select id="dsShellTool" class="input" disabled><option value="">Inspect first</option></select>'+
    '<button id="dsShellRun" class="btn sm primary" type="button" disabled>Review risks & run</button>'+
    '<button id="dsShellAgent" class="btn sm" type="button">Central Agent security review</button>'+
    '</div>'+
    '<p id="dsShellStatus" class="ds-footnote" role="status" aria-live="polite">Open an approved local workspace to inspect scripts.</p>'+
    '<div id="dsShellResults" class="ds-php-results" role="region" tabindex="0" aria-label="Shell script static risk and diagnostics evidence"></div>'+
    '<p class="ds-footnote">The fixed smoke grammar permits only safe-shaped literal output and exit 0, not arbitrary scripts, loops, variables, redirects, pipes or system commands. This is not a security proof, OS sandbox or network firewall. External toolchains can still affect host resources; review each task before approving it. Central Agent reviews are never automatically submitted or deployed.</p>'+
    '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const out=el("dsShellResults");
  const project=()=>getProject()?.project||"";
  let data=null,busy=false,sequence=0;
  function line(text,warn=false){
    const p=document.createElement("p");p.className="ds-php-line";
    p.textContent=String(text);if(warn)p.dataset.severity="warning";out.append(p);
  }
  function header(text){const h=document.createElement("h4");h.textContent=text;out.append(h);}
  function info(text,bad=false){
    el("dsShellStatus").textContent=text;el("dsShellStatus").classList.toggle("ds-error",bad);
  }
  function selection(){
    return data?.files?.find(item=>item.path===el("dsShellFile").value);
  }
  function executable(){
    return data?.tools?.find(t=>t.name===el("dsShellTool").value&&t.status==="installed_not_executed");
  }
  function available(){
    if(!getProject()?.trusted||!data||!executable()||data.scan_incomplete)return false;
    const task=el("dsShellTask").value,item=selection(),name=executable().name;
    if(task==="version")return true;
    if(!item)return false;
    if(task==="shellcheck")return item.language==="bash"&&name==="shellcheck";
    if(task==="syntax")return (
      ["bash","zsh","fish"].includes(item.language)&&item.language===name
    )||(item.language==="powershell"&&["pwsh","powershell"].includes(name));
    if(task==="fixture_smoke")return item.fixture_smoke_eligible&&(
      (["bash","zsh","fish"].includes(item.language)&&item.language===name)||
      (item.language==="powershell"&&["pwsh","powershell"].includes(name))||
      (item.language==="batch"&&name==="cmd.exe"&&data.platform==="win32")
    );
    return false;
  }
  function controls(){
    const enabled=!!project()&&!busy;
    el("dsShellInspect").disabled=!enabled;
    el("dsShellFile").disabled=!enabled||!data;
    el("dsShellTool").disabled=!enabled||!data;
    el("dsShellRun").disabled=!enabled||!available();
  }
  function reset(){
    ++sequence;data=null;busy=false;out.replaceChildren();
    el("dsShellFile").replaceChildren(new Option("Inspect first",""));
    el("dsShellTool").replaceChildren(new Option("Inspect first",""));
    info("No script executes during inspection.");controls();
  }
  function render(d){
    out.replaceChildren();
    header("Shell inventory — read-only");
    line("Platforms: "+d.platform+" · language counts: "+JSON.stringify(d.language_counts));
    line("Inventory SHA-256: "+d.inventory_sha256);
    line("Toolchain SHA-256: "+d.toolchain_sha256);
    line("Risk-signalled files: "+d.risk_files+" · literal-output fixtures: "+d.fixture_count);
    for(const warning of d.warnings)line("Review: "+warning,true);
    const sel=el("dsShellFile");
    sel.replaceChildren(new Option("Select inspected script",""));
    for(const file of d.files){
      const label=file.language+" · "+file.path+" · "+
        (file.risk_signals.length?file.risk_signals.length+" risk signal(s)":"no matched risk signals")+
        (file.fixture_smoke_eligible?" · fixture eligible":"");
      sel.add(new Option(label,file.path));
      line(label+" · SHA256 "+file.sha256,file.risk_signals.length>0);
      for(const flag of file.risk_signals)
        line("  Heuristic risk: "+flag.kind+" on line "+flag.line,true);
    }
    header("Installed tools (fingerprint only — no interpreter launched)");
    const t=el("dsShellTool");
    t.replaceChildren(new Option("Choose installed tool",""));
    for(const tool of d.tools){
      line(tool.name+" · "+tool.status+(tool.sha256?" · "+tool.sha256:""));
      const option=new Option(tool.name+" · "+tool.status,tool.name);
      option.disabled=tool.status!=="installed_not_executed";
      t.add(option);
    }
    header("Execution boundaries");
    line(d.safe_execution_policy);
    line(d.syntax_policy);
    line(d.powershell_policy);
    line(d.batch_policy);
    line("Inspection: scripts executed="+d.scripts_executed+" · deployment started="+d.deployment_started);
  }
  async function inspect(){
    const p=project();if(!p||busy)return;
    const id=++sequence;busy=true;controls();
    info("Inspecting bounded shell scripts and installed interpreter fingerprints.");
    try{
      const result=await api(base+"/inspect?"+new URLSearchParams({project:p}));
      if(id!==sequence||p!==project()||!root.isConnected)return;
      data=result;render(result);info("Shell script inspection complete; no script executed.");
    }catch(error){data=null;out.replaceChildren();info("Shell inspection refused: "+error.message,true);}
    finally{busy=false;controls();}
  }
  async function run(){
    const p=project(),task=el("dsShellTask").value,file=el("dsShellFile").value,
      tool=executable(),snapshot=data;
    if(!p||!tool||busy||!available())return;
    if(!window.confirm("Approve UNSANDBOXED "+task+" with "+tool.name+"? "+
      "The tool runs with your OS/network privileges. Only a fixed literal-output fixture "+
      "may execute script content; other scripts can only be parsed or checked. "+
      "A copied file and SHA-256 fingerprint are NOT an OS sandbox or security guarantee."))return;
    const id=++sequence;busy=true;controls();info("Running one explicitly approved shell task.");
    try{
      const result=await api(base+"/run",{
        project:p,task,script:task==="version"?"":file,tool:tool.name,
        expected_inventory_sha256:snapshot.inventory_sha256,
        expected_toolchain_sha256:snapshot.toolchain_sha256,
        expected_executable:tool.executable,expected_sha256:tool.sha256,
        confirmed:true,accept_unsandboxed_interpreter_risk:true
      });
      if(id!==sequence||p!==project()||!root.isConnected)return;
      out.replaceChildren();header(task+" · "+result.status);
      line("Script: "+(result.script||"(none)")+" · exit: "+result.exit_code);
      const pre=document.createElement("pre");pre.className="ds-php-output";
      pre.textContent=result.output||"(no output)";out.append(pre);
      line("Temporary copy removed. No arbitrary execution or deployment authorised.");
      info("Approved shell task "+result.status+".",result.status!=="completed");
    }catch(error){info("Shell diagnostic refused: "+error.message,true);}
    finally{busy=false;controls();}
  }
  function agent(){
    const shared=document.querySelector(".studio-agent-bridge");
    const action=shared?.querySelector("#studioAgentAction");
    const message=shared?.querySelector("#studioAgentMessage");
    if(!action||!message){info("Central AutoMoto Agent bridge unavailable.",true);return;}
    action.value="deployment_readiness";
    message.value=("Review Developer Studio V26 Shell and Automation release readiness: "+
      "Bash, Zsh, Fish, PowerShell and Batch shell tooling, ShellCheck and PowerShell AST "+
      "syntax diagnostics, false-negative risk patterns, literal-only fixture grammar, "+
      "script fingerprints, executable provenance, OS/network isolation limitations, "+
      "Windows/macOS/Linux test evidence, malicious input rejection, audits, user approval "+
      "and rollback. Review only. No arbitrary scripts, CI/agent deployments, cloud changes "+
      "or privilege grants authorised.").slice(0,2200);
    message.dispatchEvent(new Event("input",{bubbles:true}));
    shared.scrollIntoView({block:"start",behavior:"smooth"});message.focus();
    info("Existing central AutoMoto Agent review drafted, not submitted.");
  }
  el("dsShellInspect").onclick=()=>void inspect();
  el("dsShellRun").onclick=()=>void run();
  el("dsShellAgent").onclick=agent;
  for(const id of ["dsShellFile","dsShellTask","dsShellTool"])
    el(id).addEventListener("change",controls);
  reset();
  return {projectChanged:reset,fileChanged:controls};
}

/* Developer Studio V6: manually approved local LSP service and inert results. */
export function mountDeveloperLSP({api,host,getProject,editor,status}) {
  const BASE="/api/developer/studio/lsp";
  const root=host.querySelector("#dsLspRoot");
  root.innerHTML=
    '<section class="ds-lsp-panel" aria-label="Language server features">'+
      '<div class="ds-lsp-head"><h3>Language services · V6</h3>'+
        '<span class="ds-readonly">USER-APPROVED SERVER</span></div>'+
      '<div class="ds-lsp-body">'+
        '<p class="ds-footnote">Language servers are external executables and may inspect project files. Start only for a trusted project. No compiler, project script or code modification is started by this panel.</p>'+
        '<div class="ds-lsp-controls">'+
          '<label for="dsLspSelect">Installed server</label>'+
          '<select id="dsLspSelect" class="input" aria-label="Available language servers" disabled><option value="">Choose a trusted project</option></select>'+
          '<button class="btn sm primary" type="button" id="dsLspStart" disabled>Start server</button>'+
          '<button class="btn sm" type="button" id="dsLspStop" disabled>Stop server</button>'+
          '<button class="btn sm" type="button" id="dsLspRefresh">Refresh availability</button>'+
        '</div>'+
        '<p class="ds-footnote" id="dsLspStatus" role="status" aria-live="polite">Language server not running.</p>'+
        '<div class="ds-lsp-actions" role="group" aria-label="Language server actions">'+
          '<button type="button" class="btn sm" data-lsp="textDocument/hover" disabled>Hover</button>'+
          '<button type="button" class="btn sm" data-lsp="textDocument/completion" disabled>Completions</button>'+
          '<button type="button" class="btn sm" data-lsp="textDocument/definition" disabled>Definition</button>'+
          '<button type="button" class="btn sm" data-lsp="textDocument/references" disabled>References</button>'+
          '<button type="button" class="btn sm" data-lsp="textDocument/rename" disabled>Rename preview</button>'+
          '<button type="button" class="btn sm" id="dsLspDiagnostics" disabled>Diagnostics</button>'+
        '</div>'+
        '<div id="dsLspResult" class="ds-lsp-results" aria-label="Language service results" role="region" tabindex="0"></div>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id);
  let session=null,openedProject=null,activeFile=null,busy=false,seq=0;
  const select=el("dsLspSelect"), log=el("dsLspStatus"),output=el("dsLspResult");
  const buttons=[...root.querySelectorAll("[data-lsp]")];
  function message(text,failed=false){log.textContent=text;log.classList.toggle("ds-error",failed);}
  function controls() {
    const trusted=!!getProject()?.trusted;
    el("dsLspStart").disabled=busy||!!session||!trusted||!select.value;
    el("dsLspStop").disabled=busy||!session;
    select.disabled=busy||!!session||!trusted;
    el("dsLspRefresh").disabled=busy||!getProject();
    for(const button of [...buttons,el("dsLspDiagnostics")])
      button.disabled=busy||!session||!activeFile;
  }
  function text(value){
    output.replaceChildren();
    const pre=document.createElement("pre");
    pre.textContent=typeof value==="string"?value:JSON.stringify(value,null,2);
    output.appendChild(pre);
  }
  async function stop(priorProject=null){
    const previous=session;
    session=null;activeFile=null;
    if(!previous){controls();return;}
    const project=priorProject||openedProject;
    try{await api(BASE+"/stop",{session_id:previous.session_id,project});}
    catch{/* Sessions expire server-side; never assume they persist. */}
    message("Language server stopped. No files were changed.");
    controls();
  }
  async function refresh(){
    const project=getProject();
    const id=++seq;
    if(!project){select.replaceChildren();select.add(new Option("Open a project first",""));controls();return;}
    try{
      const available=await api(BASE+"/servers?"+new URLSearchParams({project:project.project}));
      if(id!==seq||getProject()?.project!==project.project||!root.isConnected)return;
      select.replaceChildren();
      select.add(new Option("Select available server",""));
      for(const tool of available.servers||[]){
        if(tool.status!=="available")continue;
        select.add(new Option(tool.language+" · "+tool.binary,tool.language));
      }
      message(available.servers?.some(x=>x.status==="available")?
        "A server is available. Starting requires an explicit confirmation.":
        "No approved language server is installed on this device.");
    }catch(error){message("Unable to inspect language servers: "+error.message,true);}
    controls();
  }
  async function projectChanged(previousProject){
    const prior=openedProject;
    seq++;
    session=null;activeFile=null;busy=false;
    if(prior) {
      // Stop the previous session with the previous project identifier, not the new one.
      try {
        if(previousProject?.project===prior && previousProject?.trusted)await stop(prior);
      } catch{}
    }
    openedProject=getProject()?.project||null;
    text("No language-server request has been made.");
    await refresh();
  }
  async function trustChanged(){
    if(!getProject()?.trusted&&session)await stop();
    controls();
  }
  async function start(){
    const project=getProject();
    const language=select.value;
    if(!project?.trusted||!language||busy||session)return;
    if(!window.confirm("Start the installed "+language+" language server for this trusted project? The server is an external program that can read project files. It is not an operating-system sandbox. Continue?"))return;
    busy=true;controls();
    message("Initialising installed language server…");
    try{
      const data=await api(BASE+"/start",{project:project.project,language,confirmed:true});
      // A user might change folders while an asynchronous launch is running.
      if(getProject()?.project!==project.project||!root.isConnected) {
        await api(BASE+"/stop",{session_id:data.session_id,project:project.project});
        return;
      }
      session=data;
      openedProject=project.project;
      const caps=Object.entries(data.capabilities||{}).filter(([,v])=>v).map(([k])=>k);
      message(language+" server ready. Advertised capabilities: "+(caps.join(", ")||"not reported")+".");
    }catch(error){message("Language server start failed: "+error.message,true);}
    finally{busy=false;controls();}
  }
  async function request(method){
    if(!session||busy||!getProject()?.trusted)return;
    const snapshot=editor.lspContext();
    if(!snapshot)return message("Open a source file before using language services.",true);
    const sessionAtStart=session;
    const projectAtStart=getProject().project;
    const payload={session_id:session.session_id,project:projectAtStart,
      path:snapshot.path,text:snapshot.text,method,
      line:snapshot.position.line,character:snapshot.position.character};
    if(method==="textDocument/rename"){
      const name=window.prompt("New symbol name for an unsaved, review-only rename proposal:");
      if(!name)return;
      payload.new_name=name;
    }
    busy=true;controls();
    message("Requesting "+method+"…");
    try{
      const response=await api(BASE+"/query",payload);
      if(session!==sessionAtStart||getProject()?.project!==projectAtStart)return;
      output.replaceChildren();
      const result=response.result||{};
      if(result.locations?.length){
        for(const loc of result.locations){
          const button=document.createElement("button");
          button.type="button";button.className="ds-lsp-location";
          button.textContent=loc.path+" · line "+(loc.line+1);
          button.onclick=async()=>{
            await editor.openFile(loc.path);
            editor.revealLocation(loc.path,loc.line+1,loc.character+1);
          };
          output.appendChild(button);
        }
      } else if(result.items){
        text(result.items.map(x=>x.label+(x.detail?" — "+x.detail:"")).join("\n")||"No completions returned.");
      } else if(result.preview_only){
        text("Rename proposal (never applied):\n"+
          (result.edits||[]).map(x=>x.path+" · "+JSON.stringify(x.range)+" → "+x.newText).join("\n"));
      } else text(result.text||"No result returned.");
      message("Read-only "+method+" result received; source unchanged.");
    }catch(error){
      message("Language service request failed: "+error.message,true);
      if([404,410,502,504].includes(error.status)){session=null;}
    }finally{busy=false;controls();}
  }
  async function diagnostics(){
    if(!session||!getProject()?.trusted)return;
    const snapshot=editor.lspContext();
    if(!snapshot)return;
    busy=true;controls();
    try{
      await api(BASE+"/document",{session_id:session.session_id,project:getProject().project,
        path:snapshot.path,text:snapshot.text});
      const response=await api(BASE+"/diagnostics",{session_id:session.session_id,
        project:getProject().project});
      const messages=(response.files||[]).flatMap(f=>(f.items||[]).map(d=>
        f.path+": "+d.message));
      text(messages.join("\n")||"No diagnostics reported. The server may need additional analysis time.");
      message("Diagnostics received without modifying project files.");
    }catch(error){message("Diagnostics unavailable: "+error.message,true);}
    finally{busy=false;controls();}
  }
  el("dsLspStart").onclick=()=>void start();
  el("dsLspStop").onclick=()=>void stop();
  el("dsLspRefresh").onclick=()=>void refresh();
  select.onchange=controls;
  for(const button of buttons)button.onclick=()=>void request(button.dataset.lsp);
  el("dsLspDiagnostics").onclick=()=>void diagnostics();
  function fileChanged(path){activeFile=path;controls();}
  controls();
  return {projectChanged,trustChanged,fileChanged,stop};
}

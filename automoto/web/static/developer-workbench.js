/* Developer Studio V33: VS Code-style workbench and task-scoped AutoMoto Agent.
   One prompt = one task. Never automatically issue a follow-up prompt. */
export function mountDeveloperWorkbench({api,host,getProject,status}){
  const shell=host.querySelector(".ds-shell");
  if(!shell)throw Error("Developer Studio shell unavailable");
  shell.classList.add("ds-v33");
  const toolbar=shell.querySelector(".ds-toolbar");
  const summary=shell.querySelector(".ds-summary");
  const columns=shell.querySelector(".ds-columns");
  const warning=shell.querySelector(".ds-warning");
  const nav=shell.querySelector("#dsNavigationRoot");
  const mobile=shell.querySelector(".ds-mobile-switch");
  const toolIds=["dsLanguageRoot","dsLspRoot","dsIndexRoot","dsAdaptersRoot",
    "dsLatexRoot","dsBibliographyRoot","dsTexBuildRoot","dsManuscriptsRoot",
    "dsJavaScriptRoot","dsFrontendRoot","dsDataRoot","dsPhpRoot",
    "dsPythonRoot","dsGoRoot","dsRustRoot","dsNativeRoot","dsJvmRoot",
    "dsDotnetRoot","dsAndroidRoot","dsSwiftRoot","dsMobileRoot","dsShellRoot",
    "dsScriptingRoot","dsScienceRoot","dsFunctionalRoot","dsBeamRoot",
    "dsLogicRoot","dsLegacyRoot","dsWasmRoot"];
  const title=document.createElement("header");
  title.className="ds-v33-title";
  title.innerHTML='<div class="ds-v33-brand"><span class="ds-v33-mark" aria-hidden="true">◇</span>'+
    '<div><strong>AutoMoto Developer</strong><small>WORKBENCH · V34</small></div></div>'+
    '<div class="ds-v33-title-actions">'+
    '<span class="ds-v33-badge" id="dsV33WorkspaceState">No workspace</span>'+
    '<button type="button" class="btn sm" id="dsV33Tools" aria-expanded="false" aria-controls="dsV33ToolsDrawer">Extensions &amp; tools</button>'+
    '<button type="button" class="btn sm" id="dsV33AgentToggle" aria-expanded="true" aria-controls="dsV33AgentPanel">AI Agent</button></div>';
  shell.prepend(title);
  const layout=document.createElement("div");
  layout.className="ds-v33-layout";
  const left=document.createElement("aside");
  left.className="ds-v33-rail";
  left.setAttribute("aria-label","Workbench navigation");
  left.innerHTML='<button class="ds-v33-rail-btn" id="dsV33Explorer" type="button" aria-label="Focus Explorer" title="Explorer">☷</button>'+
    '<button class="ds-v33-rail-btn" id="dsV33Extensions" type="button" aria-label="Open extensions" title="Extensions">▦</button>'+
    '<button class="ds-v33-rail-btn" id="dsV33AgentRail" type="button" aria-label="Show AI Agent" title="AI Agent">✧</button>';
  const centre=document.createElement("section");
  centre.className="ds-v33-centre";
  centre.setAttribute("aria-label","Code workbench");
  const editorTop=document.createElement("div");
  editorTop.className="ds-v33-editor-top";
  editorTop.innerHTML='<span>EXPLORER / EDITOR</span><span id="dsV33EditorStatus">Ready for a project</span>';
  centre.append(editorTop,nav,mobile,columns);
  const panel=document.createElement("aside");
  panel.className="ds-v33-agent";
  panel.id="dsV33AgentPanel";
  panel.setAttribute("aria-label","AutoMoto coding agent");
  panel.innerHTML='<header class="ds-v33-agent-head"><div><strong>AutoMoto Agent</strong>'+
    '<small>One task at a time · stops after each request</small></div>'+
    '<span id="dsV33AgentState" role="status" aria-live="polite">Ready</span></header>'+
    '<div id="dsV33AgentTimeline" class="ds-v33-timeline" role="log" aria-live="polite" aria-relevant="additions">'+
    '<p class="ds-v33-intro">Describe a coding task. The agent can inspect the workspace, plan, edit, run available tests and report results using its existing tools. Risky actions require approval. After finishing, it waits for your next prompt.</p></div>'+
    '<form id="dsV33AgentForm" class="ds-v33-composer">'+
    '<label for="dsV33Prompt">Your next task</label>'+
    '<textarea id="dsV33Prompt" rows="4" maxlength="8000" placeholder="Implement a feature, investigate a bug, run tests and explain what changed…" required></textarea>'+
    '<div class="ds-v33-composer-actions"><span id="dsV33Scope">Local trusted workspace required</span>'+
    '<button id="dsV33Send" type="submit" class="btn primary" disabled>Run task</button>'+
    '<button id="dsV33Stop" type="button" class="btn" disabled>Stop</button></div>'+
    '<p class="ds-v33-footnote">No unattended follow-up, auto-merge, publish or deployment. Approve risky actions individually.</p></form>';
  // V34: visible, keyboard-accessible onboarding and shortcuts.
  const guide=document.createElement("section");
  guide.className="ds-v34-guide";
  guide.setAttribute("aria-label","Quick start");
  guide.innerHTML='<div class="ds-v34-guide-head"><strong>Start here</strong>'+
    '<span id="dsV34Step" role="status" aria-live="polite">1 of 3 · Open a project</span></div>'+
    '<p id="dsV34Hint">Choose a local project in the toolbar. You can browse without trusting it.</p>'+
    '<div class="ds-v34-guide-actions">'+
    '<button id="dsV34Project" type="button" class="btn sm">1 · Choose project</button>'+
    '<button id="dsV34Trust" type="button" class="btn sm">2 · Trust project</button>'+
    '<button id="dsV34Prompt" type="button" class="btn sm">3 · Ask AI to code</button></div>';
  centre.insertBefore(guide,editorTop.nextSibling);
  const starters=document.createElement("div");
  starters.className="ds-v34-starters";
  starters.setAttribute("aria-label","Suggested coding tasks");
  const examples=[
    ["Explain project","Inspect this workspace and explain its architecture and how to run it. Do not edit files."],
    ["Find and fix a bug","Investigate the most relevant failing test, fix the root cause and rerun focused tests. Summarise changes."],
    ["Improve code quality","Review this project for maintainability and accessibility improvements. Make a focused change and run tests."],
    ["Add tests","Identify an important untested behaviour, add focused regression tests and run them."]
  ];
  for(const [label,value] of examples){
    const b=document.createElement("button");b.type="button";b.className="ds-v34-chip";
    b.textContent=label;b.dataset.prompt=value;starters.append(b);
  }
  panel.querySelector(".ds-v33-composer").prepend(starters);
  layout.append(left,centre,panel);
  const drawer=document.createElement("section");
  drawer.className="ds-v33-drawer";
  drawer.id="dsV33ToolsDrawer";
  drawer.hidden=true;
  drawer.setAttribute("aria-label","Language extensions and specialist tools");
  drawer.innerHTML='<div class="ds-v33-drawer-head"><h3>Languages, toolchains &amp; specialist tools</h3>'+
    '<button id="dsV33CloseTools" type="button" class="btn sm">Close tools</button></div>';
  for(const id of toolIds){
    const node=shell.querySelector("#"+id);
    if(node)drawer.append(node);
  }
  shell.insertBefore(layout,toolbar);
  shell.insertBefore(drawer,layout.nextSibling);
  shell.insertBefore(toolbar,layout);
  shell.insertBefore(summary,layout);
  if(warning)drawer.append(warning);
  const el=id=>host.querySelector("#"+id);
  const state=el("dsV33AgentState"),log=el("dsV33AgentTimeline");
  const prompt=el("dsV33Prompt"),send=el("dsV33Send"),stop=el("dsV33Stop");
  let taskId=null,conversationId=null,taskProject=null,pollHandle=null;
  let busy=false,closed=false,seen=0,lastStatus="",approvalIds=new Set();
  let activeConversationProject=null,pollErrors=0;
  const terminal=new Set(["completed","failed","cancelled","error","stopped"]);
  function append(label,text,kind="note"){
    const item=document.createElement("div");item.className="ds-v33-entry ds-v33-"+kind;
    const strong=document.createElement("strong");strong.textContent=label;
    const body=document.createElement("pre");body.textContent=String(text||"");
    item.append(strong,body);log.append(item);
    log.scrollTop=log.scrollHeight;
  }
  function trusted(){return !!getProject()?.trusted&&!!getProject()?.project;}
  function refresh(){
    const p=getProject();
    el("dsV33WorkspaceState").textContent=p?(p.trusted?"Trusted workspace":"Read-only workspace"):"No workspace";
    el("dsV33Scope").textContent=p?.trusted?"Workspace: "+p.project:"Trust a local workspace first";
    send.disabled=busy||!trusted()||prompt.value.trim().length<5;
    const step=el("dsV34Step"),hint=el("dsV34Hint");
    if(!p?.project){
      step.textContent="1 of 3 · Open a project";
      hint.textContent="Choose a local project from the existing project toolbar. Browse files safely before trusting it.";
    }else if(!p.trusted){
      step.textContent="2 of 3 · Trust your project";
      hint.textContent="Inspect the files first. Trust only a workspace you own or have reviewed; this allows the agent to edit it.";
    }else if(busy){
      step.textContent="Agent working · follow progress";
      hint.textContent="The agent is handling your task. Approve sensitive actions individually or stop the task.";
    }else{
      step.textContent="3 of 3 · Describe your task";
      hint.textContent="Type a request or choose an example. The agent stops when finished and waits for your next prompt.";
    }
    el("dsV34Trust").disabled=!p?.project||!!p?.trusted;
    el("dsV34Prompt").disabled=!p?.trusted;
    stop.disabled=!busy||!taskId;
  }
  function showTools(value){
    drawer.hidden=!value;el("dsV33Tools").setAttribute("aria-expanded",String(value));
    if(value)drawer.scrollIntoView({block:"nearest"});
  }
  function showAgent(value){
    layout.classList.toggle("ds-v33-agent-hidden",!value);
    el("dsV33AgentToggle").setAttribute("aria-expanded",String(value));
    if(value)prompt.focus();
  }
  function finish(message,kind="note"){
    if(!busy)return;
    busy=false;taskId=null;taskProject=null;pollErrors=0;
    if(pollHandle){clearTimeout(pollHandle);pollHandle=null;}
    state.textContent="Waiting for next prompt";
    append("Task finished",message,kind);
    refresh();
  }
  async function approve(callId,allow,buttons){
    if(!taskId||!busy)return;
    for(const b of buttons)b.disabled=true;
    try{
      await api("/api/tasks/"+encodeURIComponent(taskId)+"/approve",
                {call_id:callId,approve:allow});
      append("Approval",allow?"Approved a single requested action":"Denied requested action");
    }catch(e){append("Approval error",e.message,"error");}
  }
  function approvals(snapshot){
    const waiting=snapshot.waiting_approval||snapshot.pending_approval||
      snapshot.pending||snapshot.approval;
    const entries=Array.isArray(waiting)?waiting:(waiting?[waiting]:[]);
    for(const entry of entries){
      const callId=entry?.call_id||entry?.id;
      if(!callId||approvalIds.has(callId))continue;
      approvalIds.add(callId);
      const row=document.createElement("div");row.className="ds-v33-approval";
      const desc=document.createElement("p");
      desc.textContent="Approval required: "+String(entry.description||entry.tool||entry.name||"tool action");
      const yes=document.createElement("button"),no=document.createElement("button");
      yes.type=no.type="button";yes.textContent="Approve once";no.textContent="Deny";
      yes.className="btn sm";no.className="btn sm";
      yes.addEventListener("click",()=>void approve(callId,true,[yes,no]));
      no.addEventListener("click",()=>void approve(callId,false,[yes,no]));
      row.append(desc,yes,no);log.append(row);
    }
  }
  async function poll(){
    if(!taskId||!busy||closed)return;
    const id=taskId;
    try{
      const result=await api("/api/tasks/"+encodeURIComponent(id)+"?since="+seen);
      pollErrors=0;
      if(id!==taskId||!busy)return;
      for(const event of result.events||[]){
        const type=String(event.type||event.kind||"progress");
        const detail=event.message||event.text||event.detail||event.content||
          (event.tool?String(event.tool):JSON.stringify(event));
        append(type,typeof detail==="string"?detail:JSON.stringify(detail),"event");
      }
      seen=Number.isInteger(result.next)?result.next:seen+(result.events||[]).length;
      approvals(result);
      const current=String(result.status||"running").toLowerCase();
      if(current!==lastStatus){state.textContent=current;lastStatus=current;}
      if(terminal.has(current)){
        let answer=result.result?.text||result.result?.message||"";
        if(!answer&&conversationId){
          try{
            const conv=await api("/api/conversations/"+encodeURIComponent(conversationId));
            const msgs=conv.messages||[];
            answer=msgs.filter(x=>x.role==="assistant").at(-1)?.content||"";
          }catch(_){}
        }
        finish(answer||"Task "+current,current==="completed"?"note":"error");
        return;
      }
    }catch(e){
      pollErrors++;
      if(pollErrors===1||pollErrors===5)append("Connection",e.message+" · retrying","error");
      if(pollErrors>=10){
        finish("Lost task monitoring after repeated connection errors. Check task history before starting another task.","error");
        return;
      }
    }
    if(busy&&taskId===id)pollHandle=setTimeout(()=>void poll(),1400);
  }
  async function run(){
    const note=prompt.value.trim(),p=getProject();
    if(busy||!p?.trusted||!p.project||note.length<5)return;
    if(!window.confirm("Run one AutoMoto Agent coding task in this trusted workspace? "+
      "The agent may inspect, edit and test using its configured tools. "+
      "Risky actions still require separate approval. No automatic next prompt, "+
      "deployment or publication is authorised."))return;
    busy=true;seen=0;approvalIds.clear();lastStatus="";
    taskProject=p.project;refresh();state.textContent="Starting";
    append("You",note,"user");
    try{
      if(conversationId&&activeConversationProject!==taskProject)conversationId=null;
      if(!conversationId){
        const conv=await api("/api/conversations",
          {title:"Developer Studio · "+note.slice(0,70),mode:"agent"});
        if(!conv.id)throw Error("Conversation not created");
        conversationId=conv.id;
        activeConversationProject=taskProject;
      }
      const result=await api("/api/agent",{
        conversation_id:conversationId,message:note,workspace:taskProject,
        client:"web",max_steps:50
      });
      if(!result.task_id)throw Error("Agent did not start");
      taskId=result.task_id;
      prompt.value="";
      state.textContent="Working";refresh();void poll();
    }catch(e){
      // Preserve the original prompt when the API rejects or fails to start the task.
      prompt.value=note;
      finish("Unable to start: "+e.message,"error");
    }
  }
  el("dsV34Project").addEventListener("click",()=>{
    const control=el("dsProject")||el("dsProjectSelect")||el("dsOpenProject");
    if(control){control.focus();control.scrollIntoView({block:"center"});}
    else toolbar?.scrollIntoView({block:"center"});
  });
  el("dsV34Trust").addEventListener("click",()=>{
    const control=el("dsTrust")||el("dsTrustProject");
    if(control){control.focus();control.scrollIntoView({block:"center"});}
    else toolbar?.scrollIntoView({block:"center"});
  });
  el("dsV34Prompt").addEventListener("click",()=>{
    showAgent(true);prompt.focus();
  });
  starters.addEventListener("click",event=>{
    const b=event.target.closest("button[data-prompt]");
    if(!b||busy)return;
    prompt.value=b.dataset.prompt;showAgent(true);refresh();
  });
  el("dsV33Tools").addEventListener("click",()=>showTools(drawer.hidden));
  el("dsV33CloseTools").addEventListener("click",()=>showTools(false));
  el("dsV33Extensions").addEventListener("click",()=>showTools(true));
  el("dsV33AgentToggle").addEventListener("click",
    ()=>showAgent(layout.classList.contains("ds-v33-agent-hidden")));
  el("dsV33AgentRail").addEventListener("click",()=>showAgent(true));
  el("dsV33Explorer").addEventListener("click",()=>el("dsShowExplorer")?.click());
  el("dsV33AgentForm").addEventListener("submit",event=>{event.preventDefault();void run();});
  prompt.addEventListener("input",refresh);
  prompt.addEventListener("keydown",event=>{
    if(event.key==="Enter"&&(event.ctrlKey||event.metaKey)){
      event.preventDefault();void run();
    }
  });
  stop.addEventListener("click",async()=>{
    if(!taskId||!busy)return;
    if(!window.confirm("Stop the current AutoMoto Agent task?"))return;
    try{await api("/api/tasks/"+encodeURIComponent(taskId)+"/cancel",{});}
    catch(e){append("Stop failed",e.message,"error");}
  });
  const observer=new MutationObserver(()=>{if(!host.isConnected){
    closed=true;if(pollHandle)clearTimeout(pollHandle);observer.disconnect();
  }});
  observer.observe(document.body,{childList:true,subtree:true});
  refresh();
  return {projectChanged(){
    if(taskId&&getProject()?.project!==taskProject)
      append("Workspace changed","The running task remains bound to its original workspace.");
    refresh();
  },fileChanged:refresh};
}

/* Single central AutoMoto agent link for ALL existing Studio pages. */
export function mountStudioAgentBridge({api,host,studio,enqueue}) {
  const anchor=host.querySelector(".lead")||host.querySelector("h2");
  if(!anchor)return;
  const panel=document.createElement("section");
  panel.className="studio-agent-bridge";
  panel.setAttribute("aria-label","Central AutoMoto AI Agent hand-off");
  panel.innerHTML=
    '<div class="studio-agent-title"><strong>AutoMoto AI Agent</strong>'+
    '<span class="studio-agent-state" role="status" aria-live="polite">Checking link…</span></div>'+
    '<p class="muted">This Studio uses the same central agent, not an isolated model. Agent reviews and deployment-readiness plans are linked to a saved conversation and task ID. Nothing is deployed or published automatically.</p>'+
    '<div class="studio-agent-controls">'+
      '<label for="studioAgentAction">Agent workflow</label>'+
      '<select id="studioAgentAction" class="input">'+
      '<option value="review">Review project</option>'+
      '<option value="plan">Plan next work</option>'+
      '<option value="deployment_readiness">Review deployment readiness</option></select>'+
      '<label for="studioAgentMessage">Request</label>'+
      '<textarea id="studioAgentMessage" class="input" rows="2" maxlength="2200" placeholder="What should the central agent review?"></textarea>'+
      '<button class="btn primary" id="studioAgentSend" type="button" disabled>Send to central agent</button></div>'+
    '<p id="studioAgentResult" class="muted" role="status" aria-live="polite">'+
    'Your request and selected Studio are shared only when you confirm. No file bytes or secrets are included automatically.</p>';
  anchor.insertAdjacentElement("afterend",panel);
  const el=id=>panel.querySelector("#"+id);
  let ready=false;
  const status=(s,bad=false)=>{el("studioAgentResult").textContent=s;
    el("studioAgentResult").classList.toggle("bad",bad);};
  function controls(){el("studioAgentSend").disabled=!ready||
    el("studioAgentMessage").value.trim().length<5;}
  async function load(){
    try{
      const data=await api("/api/agent/studios/catalog");
      const match=data.studios?.find(x=>x.id===studio);
      if(!match?.connected||data.central_agent!=="AutoMoto AI Agent")
        throw Error("The central agent did not register this Studio.");
      ready=true;
      panel.querySelector(".studio-agent-state").textContent="Connected to central agent";
      controls();
    }catch(e){
      ready=false;controls();
      panel.querySelector(".studio-agent-state").textContent="Agent link unavailable";
      status("Central agent handshake failed: "+e.message,true);
    }
  }
  async function handoff(){
    const note=el("studioAgentMessage").value.trim();
    if(!ready||note.length<5)return;
    const action=el("studioAgentAction").value;
    const explanation="Send this "+studio+" Studio request to the central AutoMoto AI Agent "+
      "as a REVIEW-ONLY task? It will create a saved Agent conversation and audit task. "+
      "Risky tools are denied for this hand-off. No deployment, publication, installation "+
      "or file upload is authorised.";
    if(!window.confirm(explanation))return;
    const req={studio,action,request:note,confirmed:true,accept_agent_review_only:true};
    if(studio==="developer"&&host.querySelector("#dsTrustState")?.textContent?.startsWith("Trusted")){
      const folder=host.querySelector("#dsPath")?.value?.trim();
      if(folder)req.workspace=folder;
    }
    const send=enqueue||(async(item)=>item.run());
    status("Queued. This studio stays open. The task starts when the one ahead of it finishes.");
    el("studioAgentMessage").value="";
    controls();
    try{
      await send({studio,title:action+": "+note.slice(0,80),run:async(job)=>{
        await job.update("Asking the central agent…");
        const result=await api("/api/agent/studios/handoff",req);
        if(!result.linked||!result.conversation_id||result.deployment_started)
          throw Error("Agent did not confirm a safe, linked hand-off.");
        status("Linked as task "+result.task_id+". The studio stayed open. Open the conversation when you want it.");
        return result;
      }});
    }catch(e){status("Agent hand-off refused: "+e.message,true);}
  }
  el("studioAgentMessage").addEventListener("input",controls);
  el("studioAgentSend").addEventListener("click",()=>void handoff());
  void load();
}

/* AutoMoto V7 workflow studio: explicit approvals, private evidence and audit.
   No client-supplied role, issued invoice, financial posting or remote actions. */
export function mountBusinessWorkflows({host,api,status}){
  host.innerHTML=`
    <div class="wf-shell">
      <header class="wf-hero"><div>
        <span class="wf-overline">AUTOMOTO AI / BUSINESS WORKFLOWS / V7</span>
        <h3>Evidence & approval centre</h3>
        <p>Link existing private workbook, invoice and financial snapshots into review-only workflows. Inspect source fingerprints and every decision.</p>
      </div><div class="wf-actions"><button class="btn" id="wfRefresh" type="button">Refresh evidence</button>
        <button class="btn" id="wfVerify" type="button">Verify audit history</button></div></header>
      <p class="wf-warning" role="note"><strong>Review only.</strong> Approving a workflow does not issue or send invoices, accept quotations, post financial transactions, change balances, process payments or modify source files. Hash-chain verification detects some alterations but is not external notarisation or tamper-proof storage.</p>
      <div class="wf-columns">
        <section class="wf-panel" aria-label="Create evidence review">
          <h4>Prepare a controlled review</h4>
          <div class="wf-fields">
            <label>Primary saved record<select class="input" id="wfSource"></select></label>
            <label>Related saved record<select class="input" id="wfRelated"></select></label>
            <label>Review purpose<select class="input" id="wfPurpose">
              <option value="business_review">Business record review</option>
              <option value="evidence_handoff">Evidence handoff</option>
              <option value="cash_reconciliation_review">Cash reconciliation review (no posting)</option>
            </select></label>
            <label>Purpose and checks<textarea class="input" id="wfNote" maxlength="650" rows="4"
              placeholder="Explain why these two saved records should be reviewed and what evidence the reviewer should check."></textarea></label>
          </div>
          <div class="wf-source-detail" id="wfFingerprints" aria-live="polite">Select two records to view their current fingerprints.</div>
          <label class="wf-confirm"><input type="checkbox" id="wfCreateConfirm">
            I understand this creates a private review request only and does not change the linked files.</label>
          <button type="button" id="wfCreate" class="btn primary">Create review request</button>
          <p class="wf-hint">Only immutable saved records are selectable. A changed file is refused, not silently re-linked.</p>
        </section>
        <section class="wf-panel" aria-label="Review decision">
          <h4>Review and decide</h4>
          <label>Pending / historical review<select class="input" id="wfSelect"></select></label>
          <div id="wfDetail" class="wf-detail" aria-live="polite">Choose a review to see its source hashes, status and events.</div>
          <label>Decision reason<textarea id="wfReason" class="input" rows="3" maxlength="500"
            placeholder="Record why the evidence is accepted, rejected or cancelled."></textarea></label>
          <label class="wf-confirm"><input type="checkbox" id="wfDecisionConfirm">
            I have checked the record references and understand this decision has no accounting or issuing effect.</label>
          <div class="wf-actions">
            <button class="btn primary" id="wfApprove" type="button">Approve review</button>
            <button class="btn" id="wfReject" type="button">Reject review</button>
            <button class="btn" id="wfCancel" type="button">Cancel my request</button>
          </div>
          <p class="wf-hint" id="wfPolicy">The server enforces the authenticated role. Hosted users can request and cancel their own reviews; hosted admins can decide within their own tenant workspace. Local owner approvals are single-person, not two-person authorisation.</p>
        </section>
      </div>
      <section class="wf-panel" aria-label="Workflow audit history">
        <div class="wf-heading"><h4>Private audit timeline</h4><span id="wfCount">No reviews loaded</span></div>
        <div id="wfHistory" class="wf-history" aria-live="polite"></div>
      </section>
      <p id="wfStatus" class="wf-status" role="status" aria-live="polite">Review-only workflows are ready.</p>
    </div>`;
  const el=id=>host.querySelector("#"+id);
  let sources=[],workflows=[],selected=null,permissions={can_approve:false,actor:"",role:"user"},sequence=0;
  function notice(message,error=false){
    el("wfStatus").textContent=message;el("wfStatus").classList.toggle("wf-error",error);
    if(error)status(message,true);
  }
  function option(parent,value,label){
    const element=document.createElement("option");element.value=value;element.textContent=label;parent.append(element);
  }
  function shortHash(value){return value?.slice(0,12)+"…"+value?.slice(-8);}
  function currentSource(id){
    return sources.find(record=>record.path===el(id).value);
  }
  function showFingerprints(){
    const first=currentSource("wfSource"),other=currentSource("wfRelated");
    const box=el("wfFingerprints");box.replaceChildren();
    for(const [title,item] of [["Primary",first],["Related",other]]){
      const line=document.createElement("div");
      const a=document.createElement("strong");a.textContent=title+": ";
      const text=document.createElement("span");
      text.textContent=item?item.kind+" · "+item.name+" · SHA-256 "+shortHash(item.sha256):"Not selected";
      line.append(a,text);box.append(line);
    }
  }
  function showDetails(){
    const item=workflows.find(record=>record.id===el("wfSelect").value)||null;
    selected=item;
    const view=el("wfDetail");view.replaceChildren();
    if(item){
      const header=document.createElement("div");header.className="wf-state";
      const name=document.createElement("strong");name.textContent=item.purpose.replaceAll("_"," ");
      const state=document.createElement("span");state.textContent=item.status;
      header.append(name,state);view.append(header);
      for(const [label,value] of [
        ["Requested by",item.requester+" ("+item.requester_role+")"],
        ["Source",item.source_path],
        ["Source SHA-256",item.source_sha256],
        ["Related",item.related_path],
        ["Related SHA-256",item.related_sha256],
        ["Reason",item.note],
      ]){
        const row=document.createElement("div");row.className="wf-meta-row";
        const heading=document.createElement("b");heading.textContent=label;
        const body=document.createElement("span");body.textContent=value;row.append(heading,body);view.append(row);
      }
    }else{
      view.textContent="Choose a saved review to see its evidence, status and history.";
    }
    const pending=item?.status==="pending",owner=item?.requester===permissions.actor;
    el("wfApprove").disabled=!pending||!permissions.can_approve;
    el("wfReject").disabled=!pending||!permissions.can_approve;
    el("wfCancel").disabled=!pending||!owner;
    el("wfCount").textContent=workflows.length+" review(s)";
    const timeline=el("wfHistory");timeline.replaceChildren();
    if(!item){timeline.textContent="No review selected.";return;}
    for(const event of item.events||[]){
      const row=document.createElement("article");row.className="wf-event";
      const title=document.createElement("strong");
      title.textContent=event.action+" · "+event.created_at+" · "+event.actor_role;
      const note=document.createElement("p");note.textContent=event.note;
      const hash=document.createElement("code");hash.textContent="Audit "+shortHash(event.event_hash);
      row.append(title,note,hash);timeline.append(row);
    }
  }
  async function refresh(selectId){
    const version=++sequence;
    const [sourceData,reviewData]=await Promise.all([
      api("/api/spreadsheets/workflows/sources"),
      api("/api/spreadsheets/workflows/list")
    ]);
    if(!host.isConnected||version!==sequence)return;
    sources=sourceData.sources||[];
    workflows=reviewData.workflows||[];
    permissions=reviewData.permissions||permissions;
    for(const id of ["wfSource","wfRelated"]){
      const select=el(id),old=select.value;
      select.replaceChildren();option(select,"","Select a saved file");
      for(const item of sources)option(select,item.path,item.kind+" · "+item.name);
      if(sources.some(x=>x.path===old))select.value=old;
    }
    showFingerprints();
    const select=el("wfSelect"),prior=selectId||select.value;
    select.replaceChildren();option(select,"","Choose a saved review");
    for(const review of workflows){
      option(select,review.id,review.status+" · "+review.purpose.replaceAll("_"," ")+" · "+review.id.slice(0,8));
    }
    if(workflows.some(x=>x.id===prior))select.value=prior;
    showDetails();
    el("wfPolicy").textContent=permissions.role==="admin"?
      "Your authenticated role can decide reviews within this private workspace. Local single-owner approvals are not two-person authorisation; approvals never change records.":
      "Your role can request or cancel your own review but not approve or reject it. Hosted account workspaces are isolated; cross-account approval is not available in V7.";
  }
  for(const id of ["wfSource","wfRelated"])el(id).onchange=showFingerprints;
  el("wfSelect").onchange=showDetails;
  el("wfRefresh").onclick=async()=>{
    try{await refresh();notice("Saved source fingerprints and review list refreshed.");}
    catch(error){notice("Refresh failed: "+error.message,true);}
  };
  el("wfVerify").onclick=async()=>{
    try{
      const result=await api("/api/spreadsheets/workflows/verify");
      notice(result.valid?"Audit chain verified: "+result.event_count+" events. Latest "+shortHash(result.latest_event_hash)+". Not externally notarised.":"Audit validation did not succeed.",!result.valid);
    }catch(error){notice("Audit integrity check FAILED: "+error.message,true);}
  };
  el("wfCreate").onclick=async()=>{
    const source=currentSource("wfSource"),related=currentSource("wfRelated");
    if(!source||!related){notice("Select two different existing saved records.",true);return;}
    if(!el("wfCreateConfirm").checked){notice("Confirm the review-only boundary before creating a request.",true);return;}
    if(!window.confirm("Create this review-only link? No saved record will be edited or posted."))return;
    try{
      const result=await api("/api/spreadsheets/workflows/create",{
        source_path:source.path,source_sha256:source.sha256,
        related_path:related.path,related_sha256:related.sha256,
        purpose:el("wfPurpose").value,note:el("wfNote").value,
        confirm_review_only:true
      });
      await refresh(result.id);el("wfCreateConfirm").checked=false;
      notice("Review request created as pending. No linked files or financial records were changed.");
    }catch(error){notice("Could not create review: "+error.message,true);}
  };
  async function decide(action){
    const review=selected;
    if(!review){notice("Select an existing review first.",true);return;}
    if(review.status!=="pending"){notice("This review already has a decision.",true);return;}
    if(!el("wfDecisionConfirm").checked){notice("Explicitly confirm the review-only decision boundary.",true);return;}
    const reason=el("wfReason").value.trim();
    if(reason.length<5){notice("Enter a decision reason of at least five characters.",true);return;}
    if(!window.confirm("Record '"+action+"' for this review? This does not edit sources, send invoices or post payments."))return;
    try{
      const result=await api("/api/spreadsheets/workflows/decide",{
        workflow_id:review.id,expected_event_hash:review.last_event_hash,
        action,reason,confirm_review_only:true
      });
      await refresh(review.id);el("wfDecisionConfirm").checked=false;el("wfReason").value="";
      notice("Review "+result.status+". No source files were modified or financial entries posted.");
    }catch(error){notice("Review decision rejected: "+error.message,true);}
  }
  el("wfApprove").onclick=()=>decide("approve");
  el("wfReject").onclick=()=>decide("reject");
  el("wfCancel").onclick=()=>decide("cancel");
  refresh().catch(error=>notice("Unable to load private workflows: "+error.message,true));
  return {refresh};
}

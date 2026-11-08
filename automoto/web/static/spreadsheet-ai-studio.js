/* V6 local-only, review-first spreadsheet intelligence. All cell text is untrusted
   and is rendered with textContent. No direct edits, network calls or tool use. */
export function mountSpreadsheetAI({host,api,getBook,getSheet,getSelected,applyCell,status}){
  host.innerHTML=`
    <div class="sai-head">
      <div><span class="sai-kicker">V6 · PRIVATE SPREADSHEET INTELLIGENCE</span>
        <h3>Offline AI assistant</h3>
        <p>Inspect local data, investigate anomalies or propose a single, reviewable cell edit. Nothing is changed automatically.</p></div>
      <button class="btn" id="saiAudit" type="button">Run offline quality audit</button>
    </div>
    <div class="sai-note" role="note">The quality audit is deterministic and needs no model.
      Optional AI uses only an <strong>explicitly enabled local Ollama model on this computer</strong>.
      It sends at most 60 sampled cell values (up to 120 characters each) to that local model.
      This workspace makes no cloud AI calls, and model output is untrusted.</div>
    <div class="sai-controls">
      <label>AI task<select id="saiMode" class="input">
        <option value="insights">Evidence-backed observations (read only)</option>
        <option value="formula">Suggest one safe formula</option>
        <option value="clean">Clean one existing text cell</option>
      </select></label>
      <label>Target cell<input id="saiTarget" class="input" value="A1" maxlength="4" aria-label="Target cell A1 to P100"></label>
      <button class="btn" type="button" id="saiUseSelected">Use selected cell</button>
      <label class="sai-prompt">What should the model examine or calculate?
        <textarea id="saiQuestion" class="input" maxlength="180" rows="2"
          placeholder="For example, calculate the total from B2:B8 in D2"></textarea></label>
      <label class="sai-consent"><input type="checkbox" id="saiConsent">
        I agree to send the bounded worksheet sample to my local Ollama model only for this review.</label>
      <button class="btn primary" type="button" id="saiReview">Request local AI suggestion</button>
    </div>
    <p class="sai-status" id="saiStatus" role="status" aria-live="polite">No data has been sent to a model.</p>
    <div class="sai-findings" id="saiFindings" aria-label="Verified audit and model findings"></div>
    <section id="saiProposal" class="sai-proposal" hidden aria-label="Pending cell proposal">
      <h4>Review proposed edit</h4>
      <div class="sai-diff"><div><strong>Current</strong><pre id="saiBefore"></pre></div>
        <div><strong>Suggested</strong><pre id="saiAfter"></pre></div></div>
      <p id="saiReason"></p>
      <div id="saiEvidence" class="sai-evidence"></div>
      <p class="sai-note">A local model can be wrong. Applying this edit requires your approval,
        a live workbook fingerprint check and a successful formula/validation check.
        The change is Undo-tracked and is not saved to disk automatically.</p>
      <div class="sai-actions"><button class="btn" id="saiReject" type="button">Discard</button>
        <button class="btn primary" id="saiApprove" type="button">Review and apply this cell</button></div>
    </section>`;
  const el=id=>host.querySelector("#"+id);
  let pending=null,requestSequence=0;
  function clear(){
    pending=null;el("saiProposal").hidden=true;
  }
  function note(value,error=false){
    el("saiStatus").textContent=value;
    el("saiStatus").classList.toggle("sai-error",error);
    if(error)status(value,true);
  }
  function appendFinding(label,detail,quote){
    const article=document.createElement("article");
    article.className="sai-finding";
    const heading=document.createElement("strong");heading.textContent=label;
    const description=document.createElement("p");description.textContent=detail;
    article.append(heading,description);
    if(quote!==undefined){
      const evidence=document.createElement("blockquote");
      evidence.textContent=quote;article.append(evidence);
    }
    el("saiFindings").append(article);
  }
  el("saiUseSelected").onclick=()=>{
    el("saiTarget").value=getSelected();
    note("Target set to "+getSelected()+". No model call has been made.");
  };
  el("saiMode").onchange=clear;
  el("saiTarget").oninput=clear;
  el("saiQuestion").oninput=clear;
  el("saiReject").onclick=()=>{clear();note("Suggestion discarded. No workbook changes.");};
  el("saiAudit").onclick=async()=>{
    const sequence=++requestSequence;
    clear();el("saiFindings").replaceChildren();
    try{
      note("Auditing worksheet locally with deterministic rules…");
      const report=await api("/api/spreadsheets/ai/audit",{
        workbook:getBook(),sheet:getSheet()});
      if(sequence!==requestSequence||!host.isConnected)return;
      if(!report.findings.length)appendFinding("No issues found in checked rules",
        "This limited audit cannot guarantee a clean or accurate workbook.");
      for(const finding of report.findings){
        appendFinding(finding.type.replaceAll("_"," ")+" · "+finding.cell,
          finding.observation,finding.evidence);
      }
      note("Checked "+report.populated_cells+" populated cells. "+
        report.findings.length+" limited-rule findings; no model or edits.");
    }catch(error){note("Offline audit failed: "+error.message,true);}
  };
  el("saiReview").onclick=async()=>{
    if(!el("saiConsent").checked){
      note("Explicit consent is required before sending any cells to a local model.",true);
      return;
    }
    const mode=el("saiMode").value,target=el("saiTarget").value.toUpperCase().trim();
    if(!/^[A-P](?:100|[1-9][0-9]?)$/.test(target)){
      note("Enter a cell from A1 to P100.",true);return;
    }
    const snapshot=getBook(),sheet=getSheet();
    const serialized=JSON.stringify(snapshot);
    const seq=++requestSequence;
    clear();el("saiFindings").replaceChildren();
    try{
      note("Requesting a bounded, local-only model review…");
      const report=await api("/api/spreadsheets/ai/review",{
        workbook:snapshot,sheet,mode,target_cell:target,
        question:el("saiQuestion").value,consent:true
      });
      if(seq!==requestSequence||!host.isConnected)return;
      if(JSON.stringify(getBook())!==serialized||getSheet()!==sheet){
        note("Workbook changed during review. Re-run the suggestion.",true);
        return;
      }
      if(mode==="insights"){
        if(!report.findings?.length)appendFinding("No grounded AI observations",
          "The model returned no claims with exact matching worksheet evidence.");
        for(const finding of report.findings||[]){
          appendFinding(finding.evidence.cell, finding.claim,finding.evidence.quote);
        }
        note("Read-only local model observations. Verify every claim independently.");
        return;
      }
      pending={...report,workbook:snapshot,sheet};
      el("saiBefore").textContent=String(report.original??"(empty)");
      el("saiAfter").textContent=report.proposal;
      el("saiReason").textContent=report.reason||"No explanation provided by local model.";
      el("saiEvidence").replaceChildren();
      for(const evidence of report.evidence||[])
        appendEvidence(evidence);
      el("saiProposal").hidden=false;
      note("One-cell suggestion ready for explicit approval; no changes have been made.");
    }catch(error){clear();note("Local AI review failed: "+error.message,true);}
  };
  function appendEvidence(evidence){
    const p=document.createElement("p");
    p.textContent="Source "+evidence.cell+": "+evidence.quote;
    el("saiEvidence").append(p);
  }
  el("saiApprove").onclick=async()=>{
    const suggestion=pending;
    if(!suggestion)return;
    if(JSON.stringify(getBook())!==JSON.stringify(suggestion.workbook)||
       getSheet()!==suggestion.sheet){
      clear();note("Workbook changed. The stale suggestion was discarded.",true);return;
    }
    const prompt="Apply this untrusted AI suggestion to "+suggestion.target_cell+
      " only? Original and other cells will remain untouched, and Undo will be available.";
    if(!window.confirm(prompt))return;
    try{
      note("Checking live workbook fingerprint and permitted formula rules…");
      const result=await api("/api/spreadsheets/ai/validate",{
        workbook:getBook(),sheet:suggestion.sheet,mode:suggestion.mode,
        target_cell:suggestion.target_cell,original:suggestion.original,
        proposal:suggestion.proposal,snapshot_sha256:suggestion.snapshot_sha256,
        approve:true
      });
      if(!result.valid||JSON.stringify(getBook())!==JSON.stringify(suggestion.workbook)||
         getSheet()!==suggestion.sheet){
        clear();note("Workbook changed before approval. Start a fresh review.",true);return;
      }
      const done=applyCell(suggestion.sheet,suggestion.target_cell,suggestion.proposal);
      if(done===false){clear();note("Change failed local validation; no edit was applied.",true);return;}
      clear();el("saiFindings").replaceChildren();
      note("Approved edit applied to one cell in this session. Undo or save a private copy as needed.");
    }catch(error){clear();note("Approval rejected: "+error.message,true);}
  };
  return {invalidate:()=>{requestSequence++;clear();}};
}

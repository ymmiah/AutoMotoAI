/* AutoMoto AI V5 financial workspace: manual evidence-only cash analytics.
   No bank connection, invoice auto-posting, external services, payment or tax filing.
   All user text is rendered via value or textContent, never HTML. */
export function mountFinancialStudio({host,api,status,showDownload}){
  host.innerHTML=`
    <div class="fi-shell">
      <header class="fi-hero">
        <div><span class="fi-eyebrow">AUTOMOTO AI · FINANCIAL INTELLIGENCE · V5</span>
          <h3>Cash-flow & financial dashboard</h3>
          <p>Private, cash-basis reporting from your manually entered activity. Plan, compare and export without banking connections.</p></div>
        <div class="fi-actions"><button type="button" id="fiSave" class="btn">Save private snapshot</button>
          <button type="button" id="fiExportPDF" class="btn">Report PDF</button>
          <button type="button" id="fiExportCSV" class="btn">Report CSV</button>
          <button type="button" id="fiAnalyse" class="btn primary">Calculate dashboard</button></div>
      </header>
      <p class="fi-disclosure" role="note"><strong>Not verified accounting.</strong> Only user-confirmed actual receipts/expenses enter cash totals. Planned transactions are shown separately. Draft invoices and quotations are <strong>never</strong> counted as revenue. No bank verification, payments or tax filing.</p>
      <div class="fi-panel">
        <h4>Ledger and reporting period</h4>
        <div class="fi-fields">
          <label>Ledger name<input class="input" id="fiName" maxlength="100" value="My financial ledger"></label>
          <label>Currency<select class="input" id="fiCurrency"><option>GBP</option><option>EUR</option><option>USD</option></select></label>
          <label>Opening cash balance<input class="input" id="fiOpening" inputmode="decimal" value="0.00" maxlength="20"></label>
          <label>From<input class="input" id="fiFrom" type="date"></label>
          <label>To<input class="input" id="fiTo" type="date"></label>
        </div>
        <p class="fi-hint">Opening balance is your user-supplied cash at the beginning of the ledger, not revenue. The dashboard adjusts period opening cash for any earlier actual entries.</p>
      </div>
      <div class="fi-panel">
        <div class="fi-head"><h4>Manual transaction register</h4>
          <button type="button" class="btn" id="fiAdd">Add transaction</button></div>
        <div class="fi-table-scroll"><table class="fi-ledger"><thead><tr>
          <th>Date</th><th>Movement</th><th>Category</th><th>Status</th><th>Amount</th><th>Description</th><th>Reference</th><th></th>
        </tr></thead><tbody id="fiEntries"></tbody></table></div>
        <p class="fi-hint">Choose <strong>Actual (user-confirmed)</strong> only for cash genuinely received/paid. Owner contributions and drawings affect cash but not operating surplus. Planned entries cannot inflate results. Transaction IDs are unique within each snapshot.</p>
      </div>
      <section class="fi-panel fi-report" aria-label="Financial analysis">
        <div class="fi-head"><h4>Financial performance</h4><span class="fi-meta" id="fiSummaryPeriod">No analysis yet</span></div>
        <div class="fi-metrics" id="fiMetrics" aria-live="polite"></div>
        <div class="fi-grid-two">
          <div><h5>Monthly cash performance</h5><div id="fiChart" role="img" aria-label="Monthly revenue and expenses"></div></div>
          <div><h5>Category analysis</h5><div class="fi-table-scroll"><table class="fi-breakdown"><thead><tr><th>Category</th><th>Revenue</th><th>Expenses</th></tr></thead><tbody id="fiCategories"></tbody></table></div></div>
        </div>
        <div class="fi-table-scroll"><table class="fi-breakdown"><thead><tr><th>Month</th><th>Revenue</th><th>Expenses</th><th>Operating cash surplus</th><th>Cash balance</th></tr></thead><tbody id="fiMonthly"></tbody></table></div>
        <div id="fiWarnings" class="fi-warnings" aria-live="polite"></div>
      </section>
      <div class="fi-panel fi-saved">
        <div><h4>Private saved snapshots</h4><p class="fi-hint">Saving creates a new, independently loadable copy. Earlier records remain unchanged.</p></div>
        <div class="fi-actions"><select id="fiSnapshots" class="input" aria-label="Saved financial snapshots"></select>
          <button type="button" id="fiLoad" class="btn">Open snapshot</button></div>
      </div>
      <div class="fi-actions" id="fiDownloads" aria-live="polite"></div>
      <p class="fi-status" id="fiStatus" role="status" aria-live="polite">Start by entering manually confirmed activity.</p>
    </div>`;
  const el=id=>host.querySelector("#"+id);
  const fields={name:"fiName",currency:"fiCurrency",opening_balance:"fiOpening",
    period_from:"fiFrom",period_to:"fiTo"};
  const kinds=["revenue","expense","capital_in","capital_out"];
  const categories=["Sales","Services","Subscriptions","Other income","Materials","Payroll",
    "Rent","Marketing","Software","Tax paid","Travel","Utilities","Other expense","Capital","Other"];
  let counter=0;
  const freshId=()=>{
    counter++;
    if(typeof crypto!=="undefined"&&typeof crypto.randomUUID==="function")
      return "tx-"+crypto.randomUUID();
    return "tx-"+Date.now().toString(36)+"-"+counter.toString(36);
  };
  const today=new Date(),year=today.getFullYear();
  el("fiFrom").value=year+"-01-01";
  el("fiTo").value=year+"-12-31";
  let entries=[],version=0,report=null;
  function notice(message,error=false){
    el("fiStatus").textContent=message;
    el("fiStatus").classList.toggle("fi-error",error);
    if(error)status(message,true);
  }
  function invalidate(){
    version++;report=null;
    el("fiMetrics").replaceChildren();
    el("fiChart").replaceChildren();
    el("fiCategories").replaceChildren();
    el("fiMonthly").replaceChildren();
    el("fiWarnings").replaceChildren();
    el("fiSummaryPeriod").textContent="Changed — calculate again";
    el("fiDownloads").replaceChildren();
  }
  function snapshot(){
    return {...Object.fromEntries(Object.entries(fields).map(([key,id])=>[key,el(id).value])),
      entries:entries.map(row=>({...row}))};
  }
  function makeControl(row,index,key,type,options,max=150){
    const td=document.createElement("td");
    const element=document.createElement(type==="select"?"select":"input");
    element.className="input";element.dataset.index=String(index);element.dataset.key=key;
    if(type==="select"){
      for(const [value,label] of options){
        const option=document.createElement("option");
        option.value=value;option.textContent=label;element.append(option);
      }
    }else{
      element.type=type;
      element.maxLength=max;
      if(key==="amount")element.inputMode="decimal";
    }
    element.value=row[key];
    element.setAttribute("aria-label",key.replaceAll("_"," ")+" transaction "+(index+1));
    td.append(element);return td;
  }
  function renderEntries(){
    const body=el("fiEntries");body.replaceChildren();
    entries.forEach((entry,index)=>{
      const tr=document.createElement("tr");
      tr.append(
        makeControl(entry,index,"transaction_date","date"),
        makeControl(entry,index,"kind","select",kinds.map(x=>[x,x.replace("_"," ")])),
        makeControl(entry,index,"category","select",categories.map(x=>[x,x])),
        makeControl(entry,index,"status","select",[
          ["planned","Planned — excluded"],["actual","Actual (user-confirmed)"]]),
        makeControl(entry,index,"amount","text",null,20),
        makeControl(entry,index,"description","text",null,220),
        makeControl(entry,index,"reference","text",null,100),
      );
      const td=document.createElement("td"),remove=document.createElement("button");
      remove.className="btn";remove.type="button";remove.textContent="Remove";
      remove.setAttribute("aria-label","Remove transaction "+(index+1));
      remove.onclick=()=>{entries.splice(index,1);renderEntries();invalidate();};
      td.append(remove);tr.append(td);body.append(tr);
    });
    el("fiAdd").disabled=entries.length>=500;
  }
  el("fiEntries").addEventListener("input",e=>{
    const control=e.target.closest("[data-index][data-key]");
    if(!control)return;
    entries[Number(control.dataset.index)][control.dataset.key]=control.value;invalidate();
  });
  el("fiEntries").addEventListener("change",e=>{
    const control=e.target.closest("[data-index][data-key]");
    if(!control)return;
    entries[Number(control.dataset.index)][control.dataset.key]=control.value;invalidate();
  });
  el("fiAdd").onclick=()=>{
    if(entries.length>=500)return;
    entries.push({entry_id:freshId(),transaction_date:el("fiFrom").value,
      kind:"revenue",status:"planned",category:"Sales",description:"",
      reference:"",amount:"0.00"});
    renderEntries();invalidate();
    notice("Transaction added as planned. Fill the fields and explicitly confirm actual status when appropriate.");
  };
  host.addEventListener("input",e=>{
    if(e.target.closest("#fiEntries"))return;
    if(e.target.matches("input,select"))invalidate();
  });
  function optionList(data){
    const select=el("fiSnapshots");select.replaceChildren();
    const empty=document.createElement("option");empty.value="";empty.textContent="Select saved snapshot";
    select.append(empty);
    for(const item of data){
      const option=document.createElement("option");
      option.value=item.path;option.textContent=item.name;select.append(option);
    }
  }
  async function refresh(){
    const data=await api("/api/spreadsheets/finance/list");
    if(host.isConnected)optionList(data.snapshots||[]);
  }
  function metric(parent,label,value){
    const card=document.createElement("div");card.className="fi-metric";
    const name=document.createElement("span");name.textContent=label;
    const amount=document.createElement("strong");amount.textContent=value;
    card.append(name,amount);parent.append(card);
  }
  function tableRow(parent,values){
    const tr=document.createElement("tr");
    for(const value of values){
      const td=document.createElement("td");td.textContent=String(value);tr.append(td);
    }
    parent.append(tr);
  }
  function draw(data){
    report=data;
    el("fiSummaryPeriod").textContent=data.period_from+" to "+data.period_to+" · "+data.currency;
    const m=el("fiMetrics");m.replaceChildren();
    for(const [label,key] of [
      ["Confirmed receipts","revenue"],["Paid expenses","expenses"],
      ["Operating cash surplus","operating_surplus"],["Opening cash","opening_cash"],
      ["Net cash movement","net_cash_movement"],["Closing cash","closing_cash"],
      ["Planned income (excluded)","planned_revenue"],["Planned costs (excluded)","planned_expenses"]
    ])metric(m,label,data.currency+" "+data[key]);
    const cat=el("fiCategories");cat.replaceChildren();
    for(const row of data.categories)tableRow(cat,[row.category,row.revenue,row.expenses]);
    if(!data.categories.length)tableRow(cat,["No confirmed activity","—","—"]);
    const monthly=el("fiMonthly");monthly.replaceChildren();
    for(const item of data.months)tableRow(monthly,[
      item.month,item.revenue,item.expenses,item.operating_surplus,item.cash_balance]);
    const graph=el("fiChart");graph.replaceChildren();
    const max=Math.max(1,...data.months.flatMap(row=>[
      Number(row.revenue)||0,Number(row.expenses)||0]));
    for(const row of data.months){
      const outer=document.createElement("div");outer.className="fi-bar-group";
      const title=document.createElement("span");title.textContent=row.month;
      const bars=document.createElement("div");bars.className="fi-bars";
      for(const [kind,value,label] of [
        ["income",row.revenue,"Revenue"],["cost",row.expenses,"Expenses"]
      ]){
        const track=document.createElement("div");track.className="fi-bar-track";
        const bar=document.createElement("div");bar.className="fi-bar fi-"+kind;
        bar.style.width=Math.max(0,Math.min(100,Number(value)*100/max))+"%";
        const text=document.createElement("span");text.className="fi-bar-caption";
        text.textContent=label+": "+data.currency+" "+value;
        track.append(bar,text);bars.append(track);
      }
      outer.append(title,bars);graph.append(outer);
    }
    const warnings=el("fiWarnings");warnings.replaceChildren();
    for(const item of data.warnings){
      const p=document.createElement("p");p.textContent=item;warnings.append(p);
    }
    notice("Dashboard calculated locally from manually entered transactions. Draft invoices remain excluded.");
  }
  el("fiAnalyse").onclick=async()=>{
    const mark=version;
    try{
      notice("Calculating cash-basis report…");
      const result=await api("/api/spreadsheets/finance/analyse",snapshot());
      if(!host.isConnected||mark!==version)return;
      draw(result);
    }catch(error){notice("Financial validation failed: "+error.message,true);}
  };
  el("fiSave").onclick=async()=>{
    try{
      const data=await api("/api/spreadsheets/finance/save",snapshot());
      await refresh();
      notice("Private financial snapshot saved: "+data.path+". No invoices or transactions were posted.");
    }catch(error){notice("Could not save financial snapshot: "+error.message,true);}
  };
  el("fiLoad").onclick=async()=>{
    const path=el("fiSnapshots").value;
    if(!path){notice("Choose a saved snapshot first.",true);return;}
    if(!window.confirm("Open this snapshot? Unsaved ledger changes will be replaced."))return;
    try{
      const data=await api("/api/spreadsheets/finance/load?path="+encodeURIComponent(path));
      for(const [key,id] of Object.entries(fields))el(id).value=data.book[key]??"";
      entries=data.book.entries.map(row=>({...row}));
      renderEntries();invalidate();
      notice("Private snapshot loaded. Original record remains unchanged.");
    }catch(error){notice("Could not load snapshot: "+error.message,true);}
  };
  async function exportAs(format){
    try{
      notice("Creating private "+format.toUpperCase()+" report…");
      const data=await api("/api/spreadsheets/finance/export",{...snapshot(),format});
      const target=el("fiDownloads");target.replaceChildren();
      const a=document.createElement("a");a.className="btn primary";
      a.textContent="Download "+format.toUpperCase()+" cash-basis report";
      a.href="/api/files/download?path="+encodeURIComponent(data.path);
      a.setAttribute("download","");target.append(a);
      showDownload(data);
      notice("Private "+format.toUpperCase()+" created, without payment or accounting actions.");
    }catch(error){notice("Report export failed: "+error.message,true);}
  }
  el("fiExportPDF").onclick=()=>exportAs("pdf");
  el("fiExportCSV").onclick=()=>exportAs("csv");
  renderEntries();refresh().catch(error=>notice("Could not list saved snapshots: "+error.message,true));
  return {refresh};
}

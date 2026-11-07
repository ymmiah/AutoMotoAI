/* AutoMoto AI v4 — invoice/quotation PDF studio. No dispatch, payment or issue actions. */
export function mountCommercialStudio({host,api,status,showDownload}){
  // Template below is fixed markup; client data only goes to textContent/value.
  host.innerHTML=`
    <div class="cs-shell">
      <div class="cs-hero">
        <div><span class="cs-eyebrow">AUTOMOTO AI / BUSINESS DOCUMENTS / V4</span>
          <h3>Invoice & quotation studio</h3>
          <p>Branded, page-aware PDFs with exact decimal totals and private customer records.</p></div>
        <div class="cs-actions">
          <button class="btn" type="button" id="csSave">Save draft</button>
          <button class="btn primary" type="button" id="csExport">Export PDF</button>
        </div>
      </div>
      <p class="cs-alert" role="note">DRAFT ONLY — no invoices are issued or sent, no quotations are accepted, and no payments are recorded.</p>
      <div class="cs-card">
        <h4>Document details</h4>
        <div class="cs-fields">
          <label>Type<select id="csKind" class="input"><option value="invoice">Invoice</option><option value="quotation">Quotation</option></select></label>
          <label>Review stage<select id="csReview" class="input"><option value="draft">Draft</option><option value="reviewed">Reviewed draft</option></select></label>
          <label>Reference<input id="csNumber" class="input" maxlength="60" placeholder="Your reference"></label>
          <label>Document date<input id="csDate" class="input" type="date"></label>
          <label id="csDueLabel">Due date<input id="csDue" class="input" type="date"></label>
          <label>Currency<select id="csCurrency" class="input"><option>GBP</option><option>EUR</option><option>USD</option></select></label>
        </div>
      </div>
      <div class="cs-card"><h4>Business branding</h4>
        <div class="cs-fields">
          <label>Brand / business name<input id="csBrandName" class="input" maxlength="100"></label>
          <label>Design<select class="input" id="csTemplate"><option value="executive">Executive</option><option value="minimal">Minimal</option></select></label>
          <label>Accent colour<input id="csAccent" type="color" value="#183153" aria-label="Business accent colour"></label>
        </div><p class="cs-tip">Brand name and colour appear on every page. Uploaded company logos are not included in v4.</p>
      </div>
      <div class="cs-two">
        <div class="cs-card"><h4>Seller / business</h4>
          <div class="cs-fields cs-party">
            <label>Name<input class="input" id="csSellerName" maxlength="140"></label>
            <label>Address<textarea class="input" id="csSellerAddress" rows="3" maxlength="500"></textarea></label>
            <label>Email<input class="input" id="csSellerEmail" maxlength="160" type="email"></label>
            <label>Phone<input class="input" id="csSellerPhone" maxlength="70"></label>
            <label>Company / VAT reference<input class="input" id="csSellerReg" maxlength="100"></label>
          </div>
        </div>
        <div class="cs-card"><h4>Customer details</h4>
          <div class="cs-fields cs-party">
            <label>Name<input class="input" id="csCustomerName" maxlength="140"></label>
            <label>Address<textarea class="input" id="csCustomerAddress" rows="3" maxlength="500"></textarea></label>
            <label>Email<input class="input" id="csCustomerEmail" maxlength="160" type="email"></label>
            <label>Phone<input class="input" id="csCustomerPhone" maxlength="70"></label>
            <label>Company / tax reference<input class="input" id="csCustomerReg" maxlength="100"></label>
          </div>
          <div class="cs-actions cs-contact-actions">
            <button class="btn" id="csContactSave" type="button">Save customer</button>
            <select class="input" id="csContacts" aria-label="Saved customers"></select>
            <button class="btn" id="csContactLoad" type="button">Load customer</button>
          </div>
        </div>
      </div>
      <div class="cs-card">
        <div class="cs-head"><h4>Line items</h4><button class="btn" id="csAddLine" type="button">Add item</button></div>
        <div class="cs-scroll"><table class="cs-table"><thead><tr>
          <th>Description</th><th>Quantity</th><th>Unit price</th><th>Discount %</th><th></th>
        </tr></thead><tbody id="csLines"></tbody></table></div>
        <div class="cs-fields cs-taxes">
          <label>Order discount %<input class="input" id="csOrderDiscount" inputmode="decimal" value="0"></label>
          <label>Tax name<select class="input" id="csTaxLabel"><option>Tax</option><option>VAT</option><option>GST</option><option>Sales tax</option></select></label>
          <label>Tax rate %<input class="input" id="csTaxRate" inputmode="decimal" value="0"></label>
        </div><p class="cs-tip">Tax and discounts are manually selected. A 0% default does not mean tax-exempt; verify legal and VAT obligations.</p>
      </div>
      <div class="cs-two">
        <div class="cs-card"><h4>Notes and terms</h4>
          <label>Customer-facing notes<textarea class="input" id="csNotes" rows="3" maxlength="1000"></textarea></label>
          <label>Commercial/payment terms<textarea class="input" id="csTerms" rows="3" maxlength="1000"></textarea></label>
        </div>
        <div class="cs-card"><div class="cs-head"><h4>Precise totals</h4>
          <button class="btn primary" id="csPreview" type="button">Recalculate</button></div>
          <div id="csTotals" aria-live="polite">Enter your details and calculate a draft preview.</div>
        </div>
      </div>
      <div class="cs-card cs-saved">
        <div><h4>Previous private drafts</h4><p class="cs-tip">Opening a draft replaces unsaved fields. Saving creates a fresh copy, never overwrites.</p></div>
        <div class="cs-actions"><select class="input" id="csDocuments" aria-label="Saved invoices and quotations"></select>
          <button class="btn" id="csLoad" type="button">Open selected</button></div>
      </div>
      <div id="csDownload" class="cs-actions" aria-live="polite"></div>
      <p id="csStatus" class="cs-status" role="status" aria-live="polite">Private commercial studio ready.</p>
    </div>`;
  const el=id=>host.querySelector("#"+id);
  const props={
    kind:"csKind",review_state:"csReview",number:"csNumber",issue_date:"csDate",due_date:"csDue",
    currency:"csCurrency",discount_percent:"csOrderDiscount",tax_percent:"csTaxRate",
    tax_label:"csTaxLabel",notes:"csNotes",terms:"csTerms"
  };
  const partyIds={
    seller:{name:"csSellerName",address:"csSellerAddress",email:"csSellerEmail",
      phone:"csSellerPhone",registration:"csSellerReg"},
    customer:{name:"csCustomerName",address:"csCustomerAddress",email:"csCustomerEmail",
      phone:"csCustomerPhone",registration:"csCustomerReg"}
  };
  const branding={display_name:"csBrandName",accent:"csAccent",template:"csTemplate"};
  let lines=[{description:"",quantity:"1",unit_price:"0.00",discount_percent:"0"}];
  let revision=0;
  function note(msg,error=false){
    el("csStatus").textContent=msg;el("csStatus").classList.toggle("cs-error",error);
    if(error)status(msg,true);
  }
  function party(side){
    return Object.fromEntries(Object.entries(partyIds[side]).map(([field,id])=>[field,el(id).value.trim()]));
  }
  function applyParty(side,data){
    for(const [field,id] of Object.entries(partyIds[side]))el(id).value=data?.[field]??"";
  }
  function payload(){
    return {
      ...Object.fromEntries(Object.entries(props).map(([field,id])=>[field,el(id).value])),
      seller:party("seller"),customer:party("customer"),
      brand:Object.fromEntries(Object.entries(branding).map(([field,id])=>[field,el(id).value])),
      lines:lines.map(row=>({...row}))
    };
  }
  function invalidate(){
    revision++;el("csTotals").textContent="Details changed. Recalculate before use.";
    el("csDownload").replaceChildren();
  }
  function updateDueLabel(){
    el("csDueLabel").childNodes[0].textContent=el("csKind").value==="quotation"?"Valid until":"Due date";
  }
  function rows(){
    const target=el("csLines");target.replaceChildren();
    lines.forEach((line,index)=>{
      const tr=document.createElement("tr");
      for(const [field,label,max] of [
        ["description","Description",220],["quantity","Quantity",26],
        ["unit_price","Unit price",26],["discount_percent","Line discount percent",10]
      ]){
        const td=document.createElement("td"),input=document.createElement("input");
        input.type="text";input.className="input";input.maxLength=max;
        input.value=line[field]??"";
        input.inputMode=field==="description"?"text":"decimal";
        input.dataset.index=String(index);input.dataset.field=field;
        input.setAttribute("aria-label",label+" line "+(index+1));
        td.append(input);tr.append(td);
      }
      const td=document.createElement("td"),button=document.createElement("button");
      button.type="button";button.className="btn";button.textContent="Remove";
      button.disabled=lines.length===1;button.setAttribute("aria-label","Remove line "+(index+1));
      button.onclick=()=>{lines.splice(index,1);rows();invalidate();};
      td.append(button);tr.append(td);target.append(tr);
    });
    el("csAddLine").disabled=lines.length>=40;
  }
  function applyDoc(data){
    for(const [key,id] of Object.entries(props))el(id).value=data[key]??"";
    for(const [key,id] of Object.entries(branding))el(id).value=data.brand?.[key]??"";
    applyParty("seller",data.seller);applyParty("customer",data.customer);
    lines=(data.lines||[]).map(line=>({...line}));
    if(!lines.length)lines=[{description:"",quantity:"1",unit_price:"0.00",discount_percent:"0"}];
    rows();updateDueLabel();invalidate();
  }
  function options(id,arr,caption){
    const select=el(id);select.replaceChildren();
    const empty=document.createElement("option");empty.value="";empty.textContent=caption;
    select.append(empty);
    for(const item of arr){
      const option=document.createElement("option");option.value=item.path;
      option.textContent=item.name;select.append(option);
    }
  }
  async function refresh(){
    const data=await api("/api/spreadsheets/commercial/list");
    if(!host.isConnected)return;
    options("csDocuments",data.documents||[],"Select a private draft");
    options("csContacts",data.customers||[],"Select a saved customer");
  }
  el("csLines").addEventListener("input",event=>{
    const input=event.target.closest("input[data-index][data-field]");
    if(!input)return;
    lines[Number(input.dataset.index)][input.dataset.field]=input.value;invalidate();
  });
  el("csAddLine").onclick=()=>{
    if(lines.length>=40)return;
    lines.push({description:"",quantity:"1",unit_price:"0.00",discount_percent:"0"});
    rows();invalidate();
  };
  host.addEventListener("input",event=>{
    if(event.target.closest("#csLines"))return;
    if(event.target.matches("input,textarea,select"))invalidate();
  });
  el("csKind").addEventListener("change",updateDueLabel);
  function totals(data){
    const panel=el("csTotals");panel.replaceChildren();
    const heading=document.createElement("h5");heading.textContent=data.kind+" "+data.number;
    panel.append(heading);
    for(const [label,value] of [
      ["Subtotal",data.subtotal],["Line discounts","-"+data.line_discounts],
      ["Order discount","-"+data.document_discount],["Taxable",data.taxable],
      [data.tax_label+" "+data.tax_percent+"%",data.tax],["TOTAL",data.total]
    ]){
      const row=document.createElement("div");row.className="cs-total-row";
      if(label==="TOTAL")row.classList.add("cs-grand-total");
      const a=document.createElement("span");a.textContent=label;
      const b=document.createElement("strong");b.textContent=data.currency+" "+value;
      row.append(a,b);panel.append(row);
    }
    const foot=document.createElement("p");foot.className="cs-tip";
    foot.textContent="Draft only — not issued, sent, accepted or paid.";panel.append(foot);
  }
  el("csPreview").onclick=async()=>{
    const mark=revision;
    try{
      const data=await api("/api/spreadsheets/commercial/preview",payload());
      if(!host.isConnected||mark!==revision)return;
      totals(data);note("Decimal totals calculated. Check tax, company details and terms.");
    }catch(error){note("Calculation failed: "+error.message,true);}
  };
  el("csSave").onclick=async()=>{
    try{
      const result=await api("/api/spreadsheets/commercial/save",payload());
      await refresh();note("Saved "+result.kind+" draft privately, without issuing or sending it.");
    }catch(error){note("Draft save failed: "+error.message,true);}
  };
  el("csExport").onclick=async()=>{
    try{
      note("Creating local draft PDF…");
      const result=await api("/api/spreadsheets/commercial/export",payload());
      const download=el("csDownload");download.replaceChildren();
      const a=document.createElement("a");a.className="btn primary";
      a.textContent="Download "+result.kind+" DRAFT PDF";
      a.href="/api/files/download?path="+encodeURIComponent(result.path);
      a.setAttribute("download","");download.append(a);
      showDownload(result);
      note("Branded draft PDF ready. No document has been issued, sent or paid.");
    }catch(error){note("PDF export failed: "+error.message,true);}
  };
  el("csLoad").onclick=async()=>{
    const path=el("csDocuments").value;
    if(!path){note("Choose a saved draft.",true);return;}
    if(!window.confirm("Open the saved draft? Unsaved document fields will be replaced."))return;
    try{
      const data=await api("/api/spreadsheets/commercial/load?path="+encodeURIComponent(path));
      applyDoc(data.document);note("Loaded private draft. Saving creates a new immutable record.");
    }catch(error){note("Draft load failed: "+error.message,true);}
  };
  el("csContactSave").onclick=async()=>{
    try{
      const result=await api("/api/spreadsheets/commercial/customer/save",party("customer"));
      await refresh();note("Customer contact saved: "+result.customer);
    }catch(error){note("Contact save failed: "+error.message,true);}
  };
  el("csContactLoad").onclick=async()=>{
    const path=el("csContacts").value;
    if(!path){note("Choose a saved customer.",true);return;}
    try{
      const data=await api("/api/spreadsheets/commercial/customer/load?path="+encodeURIComponent(path));
      applyParty("customer",data.customer);invalidate();note("Customer contact loaded.");
    }catch(error){note("Contact load failed: "+error.message,true);}
  };
  rows();updateDueLabel();
  refresh().catch(error=>note("Could not list documents: "+error.message,true));
  return {refresh};
}

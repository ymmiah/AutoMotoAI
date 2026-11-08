/* AutoMoto Research Studio V2: user-controlled discovery, never automatic import.
   Dynamic registry/web text always uses textContent, never string interpolation into HTML. */
export function mountResearchDiscovery({host,api,refreshSources,toast}){
  host.innerHTML = `
    <section class="rd-panel" aria-labelledby="rdTitle">
      <div class="rd-hero">
        <div><span class="rd-kicker">RESEARCH STUDIO · V2</span>
          <h3 id="rdTitle">Discover scholarly sources</h3>
          <p>Search public DOI metadata, verify the record, then decide what to save. This is not peer-review, study-quality or factual verification.</p></div>
        <span class="rd-tag">External lookup · Opt-in</span>
      </div>
      <div class="rd-grid">
        <div class="rd-group">
          <form id="rdSearchForm" class="rd-search">
            <label for="rdQuery">Search topic or paper title</label>
            <div class="rd-fields"><input class="input" id="rdQuery" required minlength="3" maxlength="180"
               placeholder="e.g. software supply chain vulnerability prioritisation">
              <select class="input" id="rdProvider" aria-label="Scholarly source registry">
                <option value="crossref">Crossref</option><option value="openalex">OpenAlex (free limited access)</option>
              </select>
              <button class="btn primary" type="submit">Find publications</button></div>
          </form>
          <form id="rdDoiForm" class="rd-search">
            <label for="rdDoi">Verify an exact DOI</label>
            <div class="rd-fields"><input class="input" id="rdDoi" placeholder="10.xxxx/…" maxlength="260" required>
              <button type="submit" class="btn">Verify DOI in Crossref</button></div>
          </form>
          <div class="rd-head"><h4>Discovered records</h4><span id="rdCount">No search yet</span></div>
          <div class="rd-results" id="rdResults" aria-live="polite"></div>
        </div>
        <div class="rd-group">
          <div class="rd-head"><h4>Private source catalogue</h4><button type="button" class="btn" id="rdReload">Refresh saved</button></div>
          <p class="rd-hint">Saved entries contain provider-supplied metadata and a retrieval timestamp, not a verified citation or downloaded paper.</p>
          <label class="rd-confirm"><input type="checkbox" id="rdConfirmSave">
            I understand DOI registration and metadata do not verify study findings, peer review or full-text rights.</label>
          <div class="rd-saved" id="rdSaved" aria-live="polite"></div>
          <div class="rd-capture">
            <h4>Capture one public webpage</h4>
            <p class="rd-hint">Optional: provide a direct public HTTPS webpage. AutoMoto checks robots.txt, rejects redirects and scripts, and imports a limited text snapshot into the private Document Assistant library. The original page remains unchanged.</p>
            <form id="rdCaptureForm">
              <label for="rdPageUrl">Public webpage URL</label>
              <input id="rdPageUrl" class="input" type="url" required maxlength="900" placeholder="https://example.org/public-page">
              <label class="rd-confirm"><input id="rdConfirmCapture" type="checkbox">
                I authorise this single-page retrieval and understand the captured text is unverified, may be copyrighted, and could be incomplete.</label>
              <button class="btn" type="submit">Capture approved webpage</button>
            </form>
          </div>
        </div>
      </div>
      <p class="rd-status" id="rdStatus" role="status" aria-live="polite">Registry searches require Internet access and respect offline mode. Existing private evidence search remains offline.</p>
    </section>`.replaceAll("\\`","`");
  const el=id=>host.querySelector("#"+id);
  let works=[],requestVersion=0;
  function notify(message,error=false){
    el("rdStatus").textContent=message;el("rdStatus").classList.toggle("rd-error",error);
    if(error && toast)toast(message,"bad");
  }
  function action(label,handler,kind=""){
    const button=document.createElement("button");button.type="button";
    button.className="btn"+(kind?" "+kind:"");button.textContent=label;
    button.onclick=async()=>{button.disabled=true;try{await handler();}finally{button.disabled=false;}};
    return button;
  }
  function textNode(tag,value,cls=""){
    const node=document.createElement(tag);node.textContent=String(value??"");
    if(cls)node.className=cls;return node;
  }
  function safeDoiLink(record){
    if(!/^https:\/\/doi\.org\/10\.[0-9]{4,9}\//.test(record.doi_url||""))return null;
    const link=document.createElement("a");link.href=record.doi_url;
    link.target="_blank";link.rel="noopener noreferrer";link.textContent="Open DOI in browser";
    return link;
  }
  function card(record,{saved=false}={}){
    const node=document.createElement("article");node.className="rd-record";
    node.append(textNode("strong",record.title||"Untitled registry record","rd-title"));
    const meta=[record.authors?.slice(0,4).join(", "),record.venue,record.publication_date,record.type]
      .filter(Boolean).join(" · ");
    node.append(textNode("p",meta||"Publisher/author/date metadata unavailable.","rd-meta"));
    const code=document.createElement("code");
    code.textContent="DOI "+record.doi+" · "+record.registry+" · accessed "+record.retrieved_at;
    node.append(code);
    const flags=document.createElement("p");flags.className="rd-hint";
    flags.textContent=record.retraction_flag===true?
      "OpenAlex flags this work as retracted. Verify the publisher's record before use.":
      "Registry metadata only. Check authors, publication status, version and original full text.";
    node.append(flags);
    const actions=document.createElement("div");actions.className="rd-actions";
    const href=safeDoiLink(record);if(href)actions.append(href);
    if(!saved){
      actions.append(action("Verify Crossref DOI",async()=>{
        try{
          const answer=await api("/api/research/studio/discovery/verify-doi",{doi:record.doi});
          showRecords([answer.metadata],"Crossref-verified DOI record");
          notify("Crossref DOI record retrieved. Metadata is not a proof of academic claims.");
        }catch(error){notify("DOI verification failed: "+error.message,true);}
      }));
      actions.append(action("Save verified metadata",async()=>{
        if(!el("rdConfirmSave").checked){
          notify("Tick the metadata-only acknowledgement before saving.",true);return;
        }
        if(!window.confirm("Fetch this DOI from Crossref again and save a private metadata-only record? No full paper will be downloaded."))return;
        try{
          const saved=await api("/api/research/studio/discovery/save-doi",{
            doi:record.doi,confirm_metadata_only:true
          });
          await refreshSaved();
          notify(saved.already_saved?"This DOI already exists in the private catalogue.":"DOI metadata saved privately. Verify bibliographic details before citing.");
        }catch(error){notify("Could not save DOI: "+error.message,true);}
      },"primary"));
    }
    node.append(actions);return node;
  }
  function showRecords(items,title){
    works=items;const hostList=el("rdResults");hostList.replaceChildren();
    el("rdCount").textContent=title+" · "+works.length+" record(s)";
    if(!works.length){hostList.append(textNode("p","No DOI-bearing matching records were returned. This is not evidence that the publication does not exist.","rd-hint"));return;}
    for(const record of works)hostList.append(card(record));
  }
  async function refreshSaved(){
    const data=await api("/api/research/studio/discovery/saved");
    if(!host.isConnected)return;
    const node=el("rdSaved");node.replaceChildren();
    const items=data.sources||[];
    if(!items.length){node.append(textNode("p","No metadata records saved yet.","rd-hint"));return;}
    for(const item of items.slice(0,50))node.append(card(item,{saved:true}));
    if(items.length>50)node.append(textNode("p","Showing the first 50 of "+items.length+" saved entries.","rd-hint"));
  }
  el("rdSearchForm").onsubmit=async event=>{
    event.preventDefault();
    const version=++requestVersion;
    const q=el("rdQuery").value.trim(),provider=el("rdProvider").value;
    if(q.length<3){notify("Enter at least three characters.",true);return;}
    notify("Searching public scholarly metadata. No documents are being downloaded…");
    const button=el("rdSearchForm").querySelector("button");button.disabled=true;
    try{
      const result=await api("/api/research/studio/discovery/search",{query:q,provider,limit:8});
      if(!host.isConnected||requestVersion!==version)return;
      showRecords(result.results||[],provider==="crossref"?"Crossref":"OpenAlex");
      notify(result.results?.length?
        "Results retrieved from "+provider+". Verify a DOI before citing or saving.":
        "No DOI-bearing results found. Try a different query or provider.");
    }catch(error){notify("Scholarly search failed: "+error.message,true);}
    finally{button.disabled=false;}
  };
  el("rdDoiForm").onsubmit=async event=>{
    event.preventDefault();const doi=el("rdDoi").value.trim();
    notify("Checking the exact DOI in Crossref…");
    const button=el("rdDoiForm").querySelector("button");button.disabled=true;
    try{
      const data=await api("/api/research/studio/discovery/verify-doi",{doi});
      showRecords([data.metadata],"Verified Crossref DOI");
      notify("The DOI exists in Crossref. This does not establish peer review or factual correctness.");
    }catch(error){notify("DOI check failed: "+error.message,true);}
    finally{button.disabled=false;}
  };
  el("rdReload").onclick=async()=>{
    try{await refreshSaved();notify("Private metadata catalogue refreshed.");}
    catch(error){notify("Catalogue unavailable: "+error.message,true);}
  };
  el("rdCaptureForm").onsubmit=async event=>{
    event.preventDefault();
    if(!el("rdConfirmCapture").checked){notify("Explicitly authorise the single-page public capture.",true);return;}
    const url=el("rdPageUrl").value.trim();
    if(!window.confirm("Retrieve only this public webpage after checking robots.txt? Save a bounded, unverified text snapshot as a new private document?"))return;
    const button=el("rdCaptureForm").querySelector("button");button.disabled=true;
    try{
      const saved=await api("/api/research/studio/discovery/capture-page",{
        url,confirm_public_capture:true
      });
      await refreshSources();
      notify("Webpage text captured as "+saved.document+". Select it in Private source library before researching. Not a verified academic paper.");
      el("rdConfirmCapture").checked=false;
    }catch(error){notify("Website capture rejected: "+error.message,true);}
    finally{button.disabled=false;}
  };
  refreshSaved().catch(error=>notify("Saved scholarly metadata could not load: "+error.message,true));
}

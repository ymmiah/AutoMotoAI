/* Document Assistant v1 — private native-source editor and safe Office workspace.
   No CDN, browser-side file parsing, executable macros or destructive edits. */
export async function mountDocuments({api,page,toast,esc,icon,uploadFile}) {
  const html = `
    <div class="da-shell">
      <aside class="da-library" aria-label="Document library">
        <div class="da-library-top"><h3>My documents</h3>
          <button class="btn" id="daRefresh" type="button">Refresh</button></div>
        <label class="da-search-label">Find a document
          <input class="input" id="daSearch" type="search" placeholder="Search file names" autocomplete="off"></label>
        <div id="daLibrary" class="da-file-list" role="list" aria-label="Workspace documents">
          <p class="muted small">Loading workspace documents…</p>
        </div>
        <p id="daEnvironment" class="da-environment muted small">Imported Office files are read-only in this first editor version.</p>
      </aside>
      <section class="da-editor" aria-label="Document editor">
        <div class="da-toolbar">
          <button id="daNew" type="button" class="btn">New document</button>
          <button id="daImport" type="button" class="btn">Import file</button>
          <input id="daImportFile" type="file" hidden accept=".docx,.doc,.odt,.rtf,.pptx,.ppt,.odp,.xlsx,.xls,.ods,.pdf,.md,.txt">
          <span class="da-spacer"></span>
          <button id="daSave" type="button" class="btn primary">Save draft</button>
          <button id="daExportWord" type="button" class="btn">Export Word</button>
          <button id="daExportPdf" type="button" class="btn">Export PDF</button>
        </div>
        <div class="da-title-row">
          <label class="da-title-label">Document title
            <input id="daName" class="input" maxlength="100" value="Untitled document" placeholder="Document name">
          </label>
          <span id="daMode" class="da-mode">Editable draft</span>
        </div>
        <p class="da-status" id="daStatus" role="status" aria-live="polite">Create a document or open one from your workspace.</p>
        <div id="daEditBody" class="da-edit-layout">
          <section class="da-compose" aria-label="Editable document source">
            <div class="da-section-head"><strong>Source editor</strong><span class="muted small">Markdown · A4 Word output</span></div>
            <div class="da-format" aria-label="Formatting tools">
              <button class="btn" type="button" data-da-insert="heading">Heading</button>
              <button class="btn" type="button" data-da-insert="bold">Bold</button>
              <button class="btn" type="button" data-da-insert="list">List</button>
              <button class="btn" type="button" data-da-insert="quote">Quote</button>
            </div>
            <textarea id="daSource" spellcheck="true" aria-label="Document Markdown text" placeholder="# Document title&#10;&#10;Start writing here…" rows="18"></textarea>
            <div class="da-count" id="daCount">0 characters</div>
          </section>
          <section class="da-paper-wrap" aria-label="Live document preview">
            <div class="da-section-head"><strong>Writing preview</strong><span class="muted small">Layout approximation, not print proof</span></div>
            <article class="da-paper" id="daPaper"></article>
          </section>
        </div>
        <section id="daImported" class="da-import-view" hidden aria-label="Imported document">
          <div class="da-import-note" id="daImportNote"></div>
          <div class="da-preview-toolbar">
            <button class="btn" id="daPrevPage" type="button">Previous page</button>
            <span id="daPageLabel">Page 1</span>
            <button class="btn" id="daNextPage" type="button">Next page</button>
            <a id="daOriginal" href="#" class="btn" download>Download original</a>
          </div>
          <div class="da-import-split">
            <div class="da-import-paper"><img id="daPageImage" alt="Preview of imported document page 1" hidden>
              <p id="daPreviewUnavailable" class="muted">Preview depends on local PDF rendering tools.</p></div>
            <div class="da-extraction"><div class="da-section-head"><strong>Extracted text</strong><span class="muted small">Read-only · not layout-equivalent</span></div>
              <pre id="daExtracted"></pre></div>
          </div>
          <section class="da-replace" id="daReplace" hidden>
            <h3>Save a revised Word copy</h3>
            <p class="muted small">Find and replace exact text in a NEW DOCX copy. Your uploaded file is never overwritten; inspect the exported copy before using it.</p>
            <div class="da-replace-grid">
              <label>Find exact text<input class="input" id="daFind" maxlength="500" placeholder="Existing phrase"></label>
              <label>Replace with<input class="input" id="daReplaceWith" maxlength="2000" placeholder="Updated phrase"></label>
              <button class="btn primary" type="button" id="daReplaceCopy">Create revised copy</button>
            </div>
          </section>
        </section>
        <div id="daDownloads" class="da-downloads" aria-live="polite"></div>
      </section>
    </div>`;
  const root=page("Document Assistant",
    "Write, review and publish Word documents locally. Import existing Office and PDF files for safe inspection.", html);
  root.classList.add("da-page");
  const at=id=>root.querySelector("#"+id);
  let current=null,documentList=[],dirty=false,openSequence=0,previewPage=1,libreoffice=false;
  const source=at("daSource");
  const downloadUrl=path=>"/api/files/download?path="+encodeURIComponent(path);
  const previewUrl=(path,number)=>"/api/files/preview?path="+encodeURIComponent(path)+"&page="+number;
  const cleanName=()=>at("daName").value.trim()||"Untitled document";
  function status(message,error=false){
    at("daStatus").textContent=message;
    at("daStatus").classList.toggle("da-error",!!error);
  }
  function safePreview(value){
    // No HTML injection, remote images, linked resources, or script execution.
    // This is only a writing aid; the Python Word renderer is authoritative.
    const lines=value.split(/\r?\n/);
    const rendered=[];
    let inList=false;
    const inline=text=>esc(text).replace(/\*\*([^*\n]+)\*\*/g,"<strong>$1</strong>");
    for(const raw of lines.slice(0,1800)){
      const line=raw.trim();
      const bullet=/^[-*+]\s+(.+)/.exec(line);
      if(!bullet && inList){rendered.push("</ul>");inList=false;}
      if(!line){rendered.push('<div class="da-blank"></div>');continue;}
      const heading=/^(#{1,3})\s+(.+)/.exec(line);
      if(heading){const n=heading[1].length;rendered.push("<h"+n+">"+inline(heading[2])+"</h"+n+">");}
      else if(bullet){if(!inList){rendered.push("<ul>");inList=true;}rendered.push("<li>"+inline(bullet[1])+"</li>");}
      else if(line.startsWith(">"))rendered.push("<blockquote>"+inline(line.slice(1).trim())+"</blockquote>");
      else rendered.push("<p>"+inline(line)+"</p>");
    }
    if(inList)rendered.push("</ul>");
    return rendered.join("");
  }
  function renderWriting(){
    const value=source.value;
    at("daPaper").innerHTML=safePreview(value)||'<p class="da-placeholder">Your document appears here as you write.</p>';
    at("daCount").textContent=value.length.toLocaleString()+" characters";
    const editable=!current||current.editable;
    at("daSave").disabled=!editable;
    at("daExportWord").disabled=!editable;
    at("daExportPdf").disabled=!editable||!libreoffice;
  }
  function showEditor(isEditable){
    at("daEditBody").hidden=!isEditable;
    at("daImported").hidden=isEditable;
    at("daMode").textContent=isEditable?"Editable Markdown source":"Read-only Office/PDF extraction";
    at("daName").readOnly=!isEditable;
    renderWriting();
  }
  function markDirty(){
    dirty=true;
    status("Unsaved changes. Save a new draft to preserve them.");
  }
  function canLeave(){
    return !dirty||window.confirm("Discard your unsaved edits? Saved documents and imported files will not be changed.");
  }
  function newDocument(){
    if(!canLeave())return;
    current=null;previewPage=1;dirty=false;
    at("daName").value="Untitled document";
    source.value="# Untitled document\n\n";
    showEditor(true);
    status("New source document. Save a draft or export Word when ready.");
    source.focus();
  }
  function linkTo(path,label){
    const a=document.createElement("a");
    a.className="btn da-download";
    a.textContent=label;
    a.href=downloadUrl(path);a.download="";
    at("daDownloads").prepend(a);
  }
  function libraryRender(){
    const query=at("daSearch").value.trim().toLowerCase();
    const matched=documentList.filter(doc=>doc.name.toLowerCase().includes(query));
    const list=at("daLibrary");
    list.innerHTML=matched.length?matched.map(item=>
      '<button type="button" class="da-file" role="listitem" data-da-open="'+esc(item.path)+
      '" aria-current="'+(current?.path===item.path?'true':'false')+'">'+
      '<span class="da-file-type">'+esc(item.kind.toUpperCase())+'</span>'+
      '<span class="da-file-name">'+esc(item.name)+'</span>'+
      '<span class="da-file-size">'+(item.size/1024).toFixed(0)+' KB</span></button>'
    ).join(""):'<p class="muted small">No matching documents. Import a file or create a draft.</p>';
  }
  async function refreshLibrary(){
    try{
      const result=await api("/api/documents/list");
      documentList=result.documents||[];
      libreoffice=!!result.libreoffice;
      at("daEnvironment").textContent=libreoffice?
        "Local LibreOffice is ready for Word/PDF rendering. Imported originals remain unchanged.":
        "DOCX export is available. PDF publishing and some page previews need locally installed LibreOffice.";
      libraryRender();renderWriting();
    }catch(error){status("Could not load the document library: "+error.message,true);}
  }
  async function openDocument(path){
    if(!canLeave())return;
    const sequence=++openSequence;
    status("Opening your document…");
    try{
      const data=await api("/api/documents/open?path="+encodeURIComponent(path));
      if(sequence!==openSequence||!root.isConnected)return;
      current=data;previewPage=1;dirty=false;
      at("daName").value=data.name;
      at("daDownloads").replaceChildren();
      if(data.editable){
        source.value=data.markdown;
        showEditor(true);
        status(data.notice);
      }else{
        source.value="";
        showEditor(false);
        at("daExtracted").textContent=data.extracted_text||"No extractable text found. A scanned PDF may require OCR.";
        at("daOriginal").href=downloadUrl(data.path);
        at("daImportNote").textContent=data.notice+(data.truncated?" The text extract was truncated; use the original for complete content.":"");
        at("daReplace").hidden=data.kind!=="docx";
        updatePagePreview();
        status("Opened "+data.name+" for read-only inspection.");
      }
      libraryRender();
    }catch(error){status("Could not open document: "+error.message,true);}
  }
  function updatePagePreview(){
    if(!current||current.editable)return;
    at("daPageLabel").textContent="Page "+previewPage;
    at("daPrevPage").disabled=previewPage===1;
    const picture=at("daPageImage"),message=at("daPreviewUnavailable");
    picture.hidden=true;
    message.hidden=false;
    message.textContent="Rendering page "+previewPage+" if local preview tools are available…";
    picture.onload=()=>{if(!root.isConnected)return;picture.hidden=false;message.hidden=true;};
    picture.onerror=()=>{picture.hidden=true;message.hidden=false;
      message.textContent="Page preview unavailable. The original file and extracted text are still accessible.";};
    picture.alt="Preview of "+current.name+", page "+previewPage;
    picture.src=previewUrl(current.path,previewPage);
  }
  function editorData(){
    const markdown=source.value;
    if(markdown.length>120000)throw Error("Document limit is 120,000 characters.");
    return {name:cleanName(),markdown};
  }
  async function saveDraft(){
    const button=at("daSave");button.disabled=true;
    try{
      const result=await api("/api/documents/save",editorData());
      dirty=false;status("Saved new editable draft: "+result.path);
      linkTo(result.path,"Download draft");
      current={path:result.path,name:cleanName(),kind:"draft",editable:true};
      await refreshLibrary();
      toast("Document draft saved");
    }catch(error){status("Save failed: "+error.message,true);}
    finally{button.disabled=false;renderWriting();}
  }
  async function exportAs(fmt){
    const button=at(fmt==="pdf"?"daExportPdf":"daExportWord");
    button.disabled=true;status("Preparing "+fmt.toUpperCase()+" from editable source…");
    try{
      const data=await api("/api/documents/export",{...editorData(),format:fmt});
      status("Exported "+data.path+". This is a new file, not an overwrite.");
      linkTo(data.path,"Download "+fmt.toUpperCase());
      await refreshLibrary();
      toast("Document published as "+fmt.toUpperCase());
    }catch(error){status("Export failed: "+error.message,true);}
    finally{button.disabled=false;renderWriting();}
  }
  async function createCopy(){
    if(!current||current.kind!=="docx")return;
    const find=at("daFind").value,replace=at("daReplaceWith").value;
    if(!find){status("Enter the exact text to find.",true);return;}
    if(!window.confirm("Create a revised copy of this Word document? The original will not be modified."))return;
    const button=at("daReplaceCopy");button.disabled=true;
    try{
      const data=await api("/api/documents/replace-copy",
        {path:current.path,sha256:current.sha256,find,replace});
      linkTo(data.path,"Download revised DOCX");
      status("Created a revised copy with "+data.changes+" change(s). Original unchanged.");
      await refreshLibrary();
    }catch(error){status("Could not revise copy: "+error.message,true);}
    finally{button.disabled=false;}
  }
  at("daNew").onclick=newDocument;
  at("daImport").onclick=()=>at("daImportFile").click();
  at("daImportFile").onchange=async e=>{
    for(const file of [...e.target.files]){
      try{
        status("Importing "+file.name+"…");
        const item=await uploadFile(file,"uploads");
        await refreshLibrary();
        await openDocument(item.path);
        toast(file.name+" imported");
      }catch(error){status(file.name+": "+error.message,true);}
    }
    e.target.value="";
  };
  at("daSave").onclick=saveDraft;
  at("daExportWord").onclick=()=>exportAs("docx");
  at("daExportPdf").onclick=()=>exportAs("pdf");
  at("daReplaceCopy").onclick=createCopy;
  at("daRefresh").onclick=refreshLibrary;
  at("daSearch").oninput=libraryRender;
  at("daLibrary").onclick=e=>{
    const item=e.target.closest("[data-da-open]");
    if(item)openDocument(item.dataset.daOpen);
  };
  at("daName").oninput=markDirty;
  source.oninput=()=>{markDirty();renderWriting();};
  at("daPrevPage").onclick=()=>{if(previewPage>1){previewPage--;updatePagePreview();}};
  at("daNextPage").onclick=()=>{if(previewPage<200){previewPage++;updatePagePreview();}};
  root.querySelector(".da-format").onclick=e=>{
    const item=e.target.closest("[data-da-insert]");
    if(!item)return;
    const start=source.selectionStart,end=source.selectionEnd,text=source.value.slice(start,end);
    const insertion={
      heading:"# "+(text||"Section heading"),
      bold:"**"+(text||"important text")+"**",
      list:"- "+(text||"List item"),
      quote:"> "+(text||"Quotation"),
    }[item.dataset.daInsert];
    if(!insertion)return;
    source.setRangeText(insertion,start,end,"select");
    source.dispatchEvent(new Event("input",{bubbles:true}));source.focus();
  };
  root.addEventListener("keydown",event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="s"&&
       !at("daEditBody").hidden){
      event.preventDefault();saveDraft();
    }
  });
  await refreshLibrary();
  const openPath=sessionStorage.getItem("automoto_document_open_path");
  sessionStorage.removeItem("automoto_document_open_path");
  if(openPath)await openDocument(openPath);
  else newDocument();
}

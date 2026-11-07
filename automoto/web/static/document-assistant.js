/* Document Assistant v2 — structured native-source editor; no untrusted execution. */
import {DEFAULT_LAYOUT,layoutOptions,createDocumentHistory,documentOutline,
  formatHeading,createTable,appendTableRow,renderDocumentPreview} from "./document-editor-model.js";
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
          <button id="daUndo" type="button" class="btn" disabled>Undo</button>
          <button id="daRedo" type="button" class="btn" disabled>Redo</button>
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
        <fieldset class="da-settings" id="daSettings">
          <legend>Page and typography</legend>
          <label>Paper<select class="input" id="daPageSize"><option>A4</option><option>Letter</option></select></label>
          <label>Orientation<select class="input" id="daOrientation">
            <option value="portrait">Portrait</option><option value="landscape">Landscape</option></select></label>
          <label>Margins (cm)<input class="input" type="number" id="daMargins" min="1.2" max="4" step="0.1" value="2.5"></label>
          <label>Font<select class="input" id="daFont">
            <option>Calibri</option><option>Arial</option><option>Aptos</option>
            <option>Georgia</option><option>Times New Roman</option><option>Liberation Serif</option></select></label>
          <label>Body size<input class="input" type="number" id="daFontSize" min="9" max="16" step="1" value="11"></label>
          <label>Line spacing<input class="input" type="number" id="daLineSpacing" min="1" max="2" step="0.05" value="1.15"></label>
          <label>Heading colour<input class="input da-colour" type="color" id="daHeadingColour" value="#1F3864"></label>
          <label class="da-check"><input type="checkbox" id="daPageNumbers" checked> Page numbers</label>
        </fieldset>
        <div id="daEditBody" class="da-edit-layout">
          <section class="da-compose" aria-label="Editable document source">
            <div class="da-section-head"><strong>Source editor</strong><span class="muted small">Markdown · A4 Word output</span></div>
            <div class="da-format" aria-label="Formatting tools">
              <label class="da-heading-label">Heading level
                <select class="input" id="daHeadingLevel">
                  <option value="1">H1</option><option value="2">H2</option><option value="3">H3</option>
                  <option value="4">H4</option><option value="5">H5</option><option value="6">H6</option>
                </select></label>
              <button class="btn" type="button" data-da-insert="heading">Set heading</button>
              <button class="btn" type="button" data-da-insert="bold">Bold</button>
              <button class="btn" type="button" data-da-insert="list">List</button>
              <button class="btn" type="button" data-da-insert="quote">Quote</button>
              <button class="btn" type="button" data-da-insert="table">Insert table</button>
              <button class="btn" type="button" data-da-insert="table-row">Add table row</button>
            </div>
            <details class="da-outline-panel" open>
              <summary>Document outline <span id="daOutlineCount">0 headings</span></summary>
              <nav id="daOutline" aria-label="Document headings"></nav>
            </details>
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
  const settingIds={
    page_size:"daPageSize",orientation:"daOrientation",margins_cm:"daMargins",
    font:"daFont",font_size:"daFontSize",line_spacing:"daLineSpacing",
    heading_color:"daHeadingColour",page_numbers:"daPageNumbers"};
  const readOptions=()=>({
    page_size:at("daPageSize").value,orientation:at("daOrientation").value,
    margins_cm:Number(at("daMargins").value),font:at("daFont").value,
    font_size:Number(at("daFontSize").value),
    line_spacing:Number(at("daLineSpacing").value),
    heading_color:at("daHeadingColour").value,
    page_numbers:at("daPageNumbers").checked
  });
  function setOptions(options){
    const normalized=layoutOptions(options);
    for(const [key,id] of Object.entries(settingIds)){
      if(key==="page_numbers")at(id).checked=normalized[key];
      else at(id).value=normalized[key];
    }
  }
  const snapshot=()=>({name:cleanName(),markdown:source.value,options:readOptions()});
  const history=createDocumentHistory({name:"Untitled document",
    markdown:"# Untitled document\\n\\n",options:{...DEFAULT_LAYOUT}});
  const historyButtons=()=>{
    const state=history.state();
    at("daUndo").disabled=!state.canUndo||at("daEditBody").hidden;
    at("daRedo").disabled=!state.canRedo||at("daEditBody").hidden;
  };
  function commitEditor(kind="edit",coalesce=false){
    history.commit(snapshot(),{kind,coalesce});
    dirty=true;status("Unsaved changes. Save a new draft to preserve them.");
    renderWriting();historyButtons();
  }
  function restoreEditor(state){
    at("daName").value=state.name;
    source.value=state.markdown;
    setOptions(state.options);
    dirty=true;status("Change restored. Save as a new draft to preserve this version.");
    renderWriting();historyButtons();
  }
  const downloadUrl=path=>"/api/files/download?path="+encodeURIComponent(path);
  const previewUrl=(path,number)=>"/api/files/preview?path="+encodeURIComponent(path)+"&page="+number;
  const cleanName=()=>at("daName").value.trim()||"Untitled document";
  function status(message,error=false){
    at("daStatus").textContent=message;
    at("daStatus").classList.toggle("da-error",!!error);
  }
  function renderWriting(){
    const value=source.value;
    at("daPaper").innerHTML=renderDocumentPreview(value,esc)||
      '<p class="da-placeholder">Your document appears here as you write.</p>';
    const options=readOptions(),paper=at("daPaper");
    paper.dataset.orientation=options.orientation;
    paper.style.setProperty("--da-font",JSON.stringify(options.font));
    paper.style.setProperty("--da-font-size",String(Math.max(9,Math.min(16,options.font_size||11)))+"pt");
    paper.style.setProperty("--da-line-height",String(Math.max(1,Math.min(2,options.line_spacing||1.15))));
    paper.style.setProperty("--da-heading-colour",/^#[0-9a-f]{6}$/i.test(options.heading_color)?
      options.heading_color:"#1F3864");
    const headings=documentOutline(value);
    at("daOutlineCount").textContent=headings.length+" heading"+(headings.length===1?"":"s");
    at("daOutline").innerHTML=headings.length?headings.map((h,i)=>
      '<button type="button" class="da-outline-entry" data-da-heading="'+i+'"'+
      ' style="--da-depth:'+Math.min(5,h.level-1)+'">'+esc(h.text)+'</button>'
    ).join(""):'<p class="muted small">Add a heading to navigate your document.</p>';
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
    at("daSettings").hidden=!isEditable;
    renderWriting();historyButtons();
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
    setOptions(DEFAULT_LAYOUT);
    history.reset(snapshot());
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
        setOptions(data.options||DEFAULT_LAYOUT);
        history.reset(snapshot());
        showEditor(true);
        status(data.notice);
      }else{
        source.value="";
        setOptions(DEFAULT_LAYOUT);
        history.reset(snapshot());
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
    return {name:cleanName(),markdown,options:readOptions()};
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
  at("daName").oninput=()=>commitEditor("title",true);
  source.oninput=()=>commitEditor("source",true);
  for(const id of Object.values(settingIds)){
    at(id).onchange=()=>{
      if(at(id).type==="number"&&!at(id).checkValidity()){
        status("Page settings must be within the displayed limits.",true);return;
      }
      commitEditor("layout",false);
    };
  }
  at("daUndo").onclick=()=>{const previous=history.undo();if(previous)restoreEditor(previous);};
  at("daRedo").onclick=()=>{const next=history.redo();if(next)restoreEditor(next);};
  at("daOutline").onclick=e=>{
    const item=e.target.closest("[data-da-heading]");
    if(!item)return;
    const heading=documentOutline(source.value)[Number(item.dataset.daHeading)];
    if(!heading)return;
    source.focus();source.setSelectionRange(heading.offset,heading.end);
    const before=source.value.slice(0,heading.offset).split("\\n").length-1;
    source.scrollTop=Math.max(0,before*23-80);
  };
  at("daPrevPage").onclick=()=>{if(previewPage>1){previewPage--;updatePagePreview();}};
  at("daNextPage").onclick=()=>{if(previewPage<200){previewPage++;updatePagePreview();}};
  root.querySelector(".da-format").onclick=e=>{
    const item=e.target.closest("[data-da-insert]");
    if(!item)return;
    const start=source.selectionStart,end=source.selectionEnd,text=source.value.slice(start,end);
    const action=item.dataset.daInsert;
    let result=null;
    if(action==="heading")result=formatHeading(source.value,start,end,Number(at("daHeadingLevel").value));
    else if(action==="table")result=createTable(source.value,start,end);
    else if(action==="table-row")result=appendTableRow(source.value,start);
    else{
      const insertion={
        bold:"**"+(text||"important text")+"**",
        list:"- "+(text||"List item"),
        quote:"> "+(text||"Quotation")
      }[action];
      if(insertion)result={value:source.value.slice(0,start)+insertion+source.value.slice(end),
        start,end:start+insertion.length};
    }
    if(!result){status("Place the cursor inside a Markdown table before adding a row.",true);return;}
    source.value=result.value;
    source.setSelectionRange(result.start,result.end);
    commitEditor("format",false);
    source.focus();
  };
  root.addEventListener("keydown",event=>{
    const mod=event.ctrlKey||event.metaKey;
    const key=event.key.toLowerCase();
    if(mod && !at("daEditBody").hidden){
      if(key==="s"){event.preventDefault();saveDraft();}
      else if(key==="z"){
        event.preventDefault();
        const next=event.shiftKey?history.redo():history.undo();
        if(next)restoreEditor(next);
      }else if(key==="y"){event.preventDefault();
        const next=history.redo();if(next)restoreEditor(next);}
    }
  });
  await refreshLibrary();
  const openPath=sessionStorage.getItem("automoto_document_open_path");
  sessionStorage.removeItem("automoto_document_open_path");
  if(openPath)await openDocument(openPath);
  else newDocument();
}

/* Document Assistant v2 — structured native-source editor; no untrusted execution. */
import {DEFAULT_LAYOUT,layoutOptions,createDocumentHistory,documentOutline,
  formatHeading,createTable,appendTableRow,renderDocumentPreview} from "./document-editor-model.js";
import {editableReviewRequest,applyReviewedProposal,supportedEvidence,sourceDigest}
  from "./document-ai-review.js";
import {publicationOptions,DEFAULT_PUBLICATION,addReference,removeReference,insertCitation,templateById}
  from "./document-publishing.js";
import {researchCandidates,researchRequest,verifiedResearchView,researchNotes,MAX_RESEARCH_SOURCES}
  from "./document-research-model.js";
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

        <details class="da-publication" id="daPublication">
          <summary>Professional publishing · Templates, references, cover and contents</summary>
          <div class="da-pub-content">
            <div class="da-pub-row">
              <label>Document template<select class="input" id="daTemplate"><option value="">Choose a template…</option></select></label>
              <button type="button" class="btn" id="daApplyTemplate">Use template</button>
              <label>Reference style<select id="daRefStyle" class="input"><option value="harvard">Harvard</option><option value="ieee">IEEE</option></select></label>
              <label class="da-pub-check"><input type="checkbox" id="daCover"> Cover page</label>
              <label class="da-pub-check"><input type="checkbox" id="daContents"> Contents</label>
            </div>
            <div class="da-pub-row">
              <label>Document author<input class="input" id="daPubAuthor" maxlength="150" placeholder="Author (user-entered)"></label>
              <label>Organisation/institution<input class="input" id="daPubInstitution" maxlength="150"></label>
              <label>Document date<input class="input" id="daPubDate" maxlength="70" placeholder="Enter actual date"></label>
              <label>Page header<input class="input" id="daPubHeader" maxlength="150"></label>
              <label>Page footer<input class="input" id="daPubFooter" maxlength="150"></label>
            </div>
            <section class="da-ref-library" aria-label="Reference library">
              <div class="da-section-head"><strong>Author-provided references</strong>
                <span class="muted small">No invented sources or automatic research</span></div>
              <div id="daReferenceList" class="da-reference-list" aria-live="polite"></div>
              <div class="da-ref-add">
                <label>Source ID<input id="daRefId" class="input" maxlength="32" placeholder="e.g. smith2024"></label>
                <label>Author(s)<input id="daRefAuthors" class="input" maxlength="200" placeholder="Exact author(s)"></label>
                <label>Year<input id="daRefYear" class="input" maxlength="6" placeholder="2024 or n.d."></label>
                <label>Work title<input id="daRefTitle" class="input" maxlength="320" placeholder="Actual title"></label>
                <label>Type<select class="input" id="daRefType">
                  <option value="web">Website</option><option value="journal">Journal</option>
                  <option value="book">Book</option><option value="report">Report</option></select></label>
                <label>Publisher / journal<input id="daRefPublisher" class="input" maxlength="200"></label>
                <label>HTTPS URL (optional)<input id="daRefUrl" class="input" maxlength="600" placeholder="https://…"></label>
                <label>DOI (optional)<input id="daRefDoi" class="input" maxlength="120" placeholder="10.…"></label>
                <button type="button" class="btn" id="daAddReference">Add verified source details</button>
              </div>
              <p class="muted small">Use “Insert citation” beside a source to place an <code>[@source-id]</code> marker at the editor cursor. Harvard/IEEE formatting is applied on export. Confirm the original bibliographic details yourself.</p>
            </section>
            <div class="da-pub-check">
              <button type="button" class="btn primary" id="daPreflight">Check Word publication</button>
              <p id="daPreflightResult" class="muted small" role="status" aria-live="polite">Preflight creates a temporary Word document for inspection; it never saves your draft.</p>
            </div>
          </div>
        </details>
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
          <details class="da-rich" id="daRich" hidden>
            <summary>Advanced Word copy editing · preserve the original</summary>
            <div class="da-rich-content">
              <p class="muted small">Edit a specific existing Word text run, paragraph style or simple table cell, append a table row, or insert your own uploaded image. These actions create a NEW genuine Word file and never overwrite the original. Review the exported pages.</p>
              <p id="daRichStats" class="muted small">Loading Word structure…</p>
              <div class="da-rich-controls">
                <label>Action<select class="input" id="daRichAction">
                  <option value="replace_run">Replace exact text run</option>
                  <option value="set_style">Change paragraph style</option>
                  <option value="table_cell">Edit a simple table cell</option>
                  <option value="append_row">Append one table row</option>
                  <option value="insert_image">Insert an uploaded image</option>
                </select></label>
                <label id="daRichParagraphLabel">Paragraph<select class="input" id="daRichParagraph"></select></label>
                <label id="daRichRunLabel">Text run<select class="input" id="daRichRun"></select></label>
                <label id="daRichStyleLabel" hidden>New style<select class="input" id="daRichStyle">
                  <option value="Normal">Normal</option><option value="Title">Title</option>
                  <option value="Subtitle">Subtitle</option><option value="Quote">Quote</option>
                  <option value="Heading 1">Heading 1</option><option value="Heading 2">Heading 2</option>
                  <option value="Heading 3">Heading 3</option><option value="Heading 4">Heading 4</option>
                  <option value="Heading 5">Heading 5</option><option value="Heading 6">Heading 6</option>
                </select></label>
                <label id="daRichTableLabel" hidden>Table<select class="input" id="daRichTable"></select></label>
                <label id="daRichRowLabel" hidden>Row number (0-based)<input class="input" type="number" id="daRichRow" min="0" max="11" value="0"></label>
                <label id="daRichCellLabel" hidden>Column number (0-based)<input class="input" type="number" id="daRichCell" min="0" max="11" value="0"></label>
                <label id="daRichImageLabel" hidden>Image file (PNG or JPEG)<input class="input" type="file" id="daRichImage" accept=".png,.jpg,.jpeg,image/png,image/jpeg"></label>
                <label id="daRichWidthLabel" hidden>Image width (cm)<input class="input" type="number" id="daRichWidth" min="1" max="14" step="0.5" value="5"></label>
              </div>
              <label id="daRichCurrentLabel" class="da-rich-description">Existing text
                <textarea id="daRichCurrent" rows="2" readonly aria-label="Original Word text"></textarea></label>
              <label id="daRichNewLabel" class="da-rich-description">Replacement text
                <textarea id="daRichNew" rows="3" maxlength="12000" aria-label="Replacement Word text"></textarea></label>
              <p class="muted small" id="daRichInstruction">Replace only the selected run to keep surrounding Word formatting.</p>
              <button type="button" class="btn primary" id="daRichSave">Create revised DOCX copy</button>
              <p class="da-ai-status" id="daRichStatus" role="status" aria-live="polite">No changes have been made.</p>
            </div>
          </details>
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
        <section class="da-ai" aria-label="Offline AI document review">
          <div class="da-ai-head"><strong>Offline AI review</strong>
            <span class="da-ai-privacy">Local Ollama only · no automatic changes</span></div>
          <p class="muted small">Select source text for a focused review, or use the whole document (up to 12,000 characters). Imported Office documents support evidence-based summaries only. AI can make mistakes.</p>
          <div class="da-ai-controls">
            <label>Review action<select id="daAIAction" class="input">
              <option value="proofread">Proofread</option>
              <option value="rewrite">Rewrite for clarity</option>
              <option value="summary">Source-grounded summary</option>
            </select></label>
            <button type="button" class="btn primary" id="daAIRun">Review with local AI</button>
            <button type="button" class="btn" id="daAIClear">Clear suggestions</button>
          </div>
          <p id="daAIStatus" class="da-ai-status" role="status" aria-live="polite">Ready. A downloaded local model is required in Settings → Offline AI.</p>
          <div id="daAIResult" class="da-ai-result" hidden>
            <p class="da-ai-meta" id="daAIMeta"></p>
            <label class="da-ai-proposal-label" id="daAIProposalLabel" hidden>
              Suggested text (review before applying)
              <textarea id="daAIProposal" rows="9" readonly spellcheck="false"></textarea>
            </label>
            <div id="daAIEvidence" class="da-ai-evidence" aria-label="Verified source excerpts"></div>
            <p id="daAIExplanation" class="muted small"></p>
            <button type="button" id="daAIApply" class="btn primary" hidden>Apply to editable source (Undo available)</button>
          </div>
        </section>
        <details class="da-research" id="daResearch">
          <summary>Academic Research · Offline multi-document evidence</summary>
          <div class="da-research-content">
            <p class="muted small">Search up to five selected local Word, PDF, text or draft documents. Evidence search works without any AI model. Optional synthesis requires enabled local Ollama and never edits source files. Exact quotes are not proof that a claim is true.</p>
            <div class="da-research-settings">
              <label class="da-research-question">Research question
                <textarea id="daResearchQuestion" rows="2" maxlength="320"
                  placeholder="What does the selected source evidence say about…?"></textarea>
              </label>
              <label>Mode<select class="input" id="daResearchMode">
                <option value="evidence">Find exact evidence</option>
                <option value="outline">Evidence and literature-review outline</option>
                <option value="synthesis">Optional local-AI synthesis</option>
              </select></label>
            </div>
            <div class="da-research-sources-head">
              <strong>Private research sources</strong>
              <span id="daResearchCount" class="muted small">0 of 5 selected</span>
            </div>
            <div id="daResearchSources" class="da-research-sources" role="group" aria-label="Select up to five local research sources"></div>
            <button type="button" id="daResearchRun" class="btn primary">Search selected documents</button>
            <p id="daResearchStatus" class="da-ai-status" role="status" aria-live="polite">Choose a saved or uploaded source, then enter a question.</p>
            <section id="daResearchResult" class="da-research-result" hidden aria-label="Research evidence results">
              <p id="daResearchSummary" class="muted small"></p>
              <div id="daResearchEvidence" class="da-research-evidence"></div>
              <div id="daResearchSynthesis" class="da-research-synthesis"></div>
              <label class="da-research-notes">Read-only research notes and evidence outline
                <textarea readonly id="daResearchNotes" rows="12" spellcheck="false"
                  aria-label="Copyable research notes with exact quoted sources"></textarea>
              </label>
              <p class="muted small" id="daResearchLimitations"></p>
            </section>
          </div>
        </details>
        <div id="daDownloads" class="da-downloads" aria-live="polite"></div>
      </section>
    </div>`;
  const root=page("Document Assistant",
    "Write, review and publish Word documents locally. Import existing Office and PDF files for safe inspection.", html);
  root.classList.add("da-page");
  const at=id=>root.querySelector("#"+id);
  let current=null,documentList=[],dirty=false,openSequence=0,previewPage=1,libreoffice=false;
  let pendingAI=null,aiRequestId=0,aiRunning=false;
  let publication=publicationOptions(),templates=[];
  let researchSelection=new Set(),researchRunId=0,researchBusy=false;
  let richStructure=null;
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
  const snapshot=()=>({name:cleanName(),markdown:source.value,options:readOptions(),
    publication:publicationOptions(publication)});
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
    setPublication(state.publication);
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
    at("daPublication").hidden=!isEditable;
    at("daRich").hidden=isEditable||current?.kind!=="docx";
    renderWriting();historyButtons();
  }
  function aiStatus(message,error=false){
    at("daAIStatus").textContent=message;
    at("daAIStatus").classList.toggle("da-error",Boolean(error));
  }
  function resetAI(){
    ++aiRequestId;
    pendingAI=null;
    at("daAIResult").hidden=true;
    at("daAIEvidence").replaceChildren();
    at("daAIProposal").value="";
    at("daAIApply").hidden=true;
    at("daAIProposalLabel").hidden=true;
    aiStatus("Ready. Nothing has been applied.");
  }
  function refreshAIContext(){
    if(current && !current.editable){
      at("daAIAction").value="summary";
      for(const option of at("daAIAction").options)
        option.disabled=option.value!=="summary";
    }else{
      for(const option of at("daAIAction").options)option.disabled=false;
    }
    at("daAIRun").disabled=aiRunning;
  }
  async function runAIReview(){
    if(aiRunning)return;
    const mode=at("daAIAction").value;
    resetAI();
    const requestId=++aiRequestId;
    let snapshot=null,body=null,verifiedSource="";
    try{
      if(current&&!current.editable){
        if(mode!=="summary")throw Error("Imported Office files support source-grounded summaries only.");
        if(!current.path||!current.sha256)throw Error("Reopen the original imported document.");
        body={mode,source_path:current.path,source_sha256:current.sha256};
        snapshot={path:current.path,sha256:current.sha256};
        verifiedSource=current.extracted_text||"";
      }else{
        const edit=editableReviewRequest(mode,source.value,source.selectionStart,source.selectionEnd);
        const digest=await sourceDigest(edit.markdown);
        if(requestId!==aiRequestId||!root.isConnected)return;
        snapshot={markdown:edit.markdown,start:edit.start,end:edit.end};
        verifiedSource=edit.text;
        body={mode,markdown:edit.markdown,start:edit.start,end:edit.end,sha256:digest};
      }
      aiRunning=true;refreshAIContext();
      aiStatus("Using the local model to prepare suggestions. Your document will not be changed.");
      const result=await api("/api/documents/ai/review",body);
      if(requestId!==aiRequestId||!root.isConnected)return;
      if(snapshot.markdown!==undefined&&source.value!==snapshot.markdown){
        throw Error("The document changed while the model was reviewing it. Review the latest version again.");
      }
      if(snapshot.path&&(!current||current.path!==snapshot.path||current.sha256!==snapshot.sha256)){
        throw Error("A different imported document is open. Run the review again.");
      }
      if(result.mode!==mode||result.requires_approval!==true||result.applied!==false){
        throw Error("The AI service did not return a reviewable result.");
      }
      pendingAI={result,snapshot,verifiedSource};
      at("daAIResult").hidden=false;
      at("daAIMeta").textContent="Source: "+result.source+" · Model: "+result.model+
        " · No changes applied";
      at("daAIExplanation").textContent=(result.explanation||"")+" "+
        (result.limitations||"");
      const rewrite=mode==="proofread"||mode==="rewrite";
      at("daAIProposalLabel").hidden=!rewrite;
      at("daAIApply").hidden=!rewrite||!result.changed;
      if(rewrite)at("daAIProposal").value=result.proposal||"";
      if(mode==="summary"){
        const verified=supportedEvidence(result,verifiedSource);
        if(!verified.length)throw Error("No evidence could be independently checked against the opened source.");
        const list=document.createElement("ol");
        for(const point of verified){
          const li=document.createElement("li");
          const claim=document.createElement("p");
          claim.textContent=point.claim;
          const quote=document.createElement("blockquote");
          quote.textContent=point.quote;
          li.append(claim,quote);
          if(snapshot.markdown!==undefined){
            const jump=document.createElement("button");
            jump.type="button";jump.className="btn";jump.textContent="Find in source";
            jump.onclick=()=>{
              if(source.value!==snapshot.markdown){aiStatus("Source changed; reopen review.",true);return;}
              const a=snapshot.start+point.offset;
              source.focus();source.setSelectionRange(a,a+point.quote.length);
            };
            li.append(jump);
          }
          list.append(li);
        }
        at("daAIEvidence").replaceChildren(list);
      }
      aiStatus(rewrite?"Suggestion ready. Compare the proposed text before applying.":
        "Summary ready. Quotes match the source, but check each interpretation.");
    }catch(error){
      if(requestId===aiRequestId&&root.isConnected){
        pendingAI=null;at("daAIResult").hidden=true;
        aiStatus("Local AI review unavailable: "+error.message,true);
      }
    }finally{
      aiRunning=false;
      if(root.isConnected)refreshAIContext();
    }
  }
  function applyAIReview(){
    if(!pendingAI||pendingAI.snapshot.markdown===undefined){
      aiStatus("Only editable source suggestions may be applied.",true);return;
    }
    try{
      const {result,snapshot}=pendingAI;
      const replacement=applyReviewedProposal(source.value,snapshot,result);
      if(replacement.markdown===source.value){aiStatus("No change is needed.");return;}
      if(!window.confirm("Apply this local AI suggestion to your editable document? You can Undo it."))return;
      // The result is inserted only after explicit approval, with a native
      // history entry. Imported Office documents can never reach this path.
      source.value=replacement.markdown;
      source.focus();source.setSelectionRange(replacement.start,replacement.end);
      commitEditor("ai",false);
      resetAI();
      aiStatus("AI text applied to the editor. Review and Save draft to preserve it.");
    }catch(error){aiStatus(error.message,true);at("daAIApply").disabled=true;}
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
    resetAI();
    setOptions(DEFAULT_LAYOUT);
    setPublication(DEFAULT_PUBLICATION);
    history.reset(snapshot());
    showEditor(true);
    refreshAIContext();
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
      libraryRender();renderResearchSources();renderWriting();
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
      if(researchCandidates([{path:data.path}]).length&&researchSelection.size<MAX_RESEARCH_SOURCES){
        researchSelection.add(data.path);renderResearchSources();
      }
      richStructure=null;
      resetAI();
      at("daName").value=data.name;
      at("daDownloads").replaceChildren();
      if(data.editable){
        source.value=data.markdown;
        setOptions(data.options||DEFAULT_LAYOUT);
        setPublication(data.publication||DEFAULT_PUBLICATION);
        history.reset(snapshot());
        showEditor(true);
        status(data.notice);
      }else{
        source.value="";
        setOptions(DEFAULT_LAYOUT);
        setPublication(DEFAULT_PUBLICATION);
        history.reset(snapshot());
        showEditor(false);
        at("daExtracted").textContent=data.extracted_text||"No extractable text found. A scanned PDF may require OCR.";
        at("daOriginal").href=downloadUrl(data.path);
        at("daImportNote").textContent=data.notice+(data.truncated?" The text extract was truncated; use the original for complete content.":"");
        at("daReplace").hidden=data.kind!=="docx";
        updatePagePreview();
        if(data.kind==="docx")await loadRichStructure(data);
        status("Opened "+data.name+" for read-only inspection.");
      }
      libraryRender();refreshAIContext();
    }catch(error){status("Could not open document: "+error.message,true);}
  }
  function researchStatus(message,error=false){
    at("daResearchStatus").textContent=message;
    at("daResearchStatus").classList.toggle("da-error",Boolean(error));
  }
  function resetResearchResults(){
    ++researchRunId;
    at("daResearchResult").hidden=true;
    at("daResearchEvidence").replaceChildren();
    at("daResearchSynthesis").replaceChildren();
    at("daResearchNotes").value="";
  }
  function renderResearchSources(){
    const candidates=researchCandidates(documentList).slice(0,100);
    const valid=new Set(candidates.map(item=>item.path));
    for(const path of [...researchSelection])if(!valid.has(path))researchSelection.delete(path);
    at("daResearchCount").textContent=researchSelection.size+" of "+MAX_RESEARCH_SOURCES+" selected";
    const panel=at("daResearchSources");
    panel.innerHTML=candidates.length?candidates.map(item=>
      '<label class="da-research-source"><input type="checkbox" data-research-path="'+esc(item.path)+
      '" '+(researchSelection.has(item.path)?"checked":"")+' '+
      (!researchSelection.has(item.path)&&researchSelection.size>=MAX_RESEARCH_SOURCES?"disabled":"")+'>'+
      '<span>'+esc(item.name)+'</span><small>'+esc(item.kind.toUpperCase())+
      '</small></label>').join(""):
      '<p class="muted small">No supported documents yet. Save a draft or import a local Word/PDF/text document.</p>';
  }
  at("daResearchSources").onchange=event=>{
    const checkbox=event.target.closest("input[data-research-path]");
    if(!checkbox)return;
    if(checkbox.checked){
      if(researchSelection.size>=MAX_RESEARCH_SOURCES){
        checkbox.checked=false;researchStatus("You can select at most five sources.",true);return;
      }
      researchSelection.add(checkbox.dataset.researchPath);
    }else researchSelection.delete(checkbox.dataset.researchPath);
    resetResearchResults();renderResearchSources();
  };
  at("daResearchQuestion").oninput=resetResearchResults;
  at("daResearchMode").onchange=resetResearchResults;
  at("daResearchRun").onclick=async()=>{
    if(researchBusy)return;
    const question=at("daResearchQuestion").value.trim();
    const chosen=[...researchSelection];
    const mode=at("daResearchMode").value;
    resetResearchResults();
    const token=++researchRunId;
    researchBusy=true;at("daResearchRun").disabled=true;
    try{
      if(!chosen.length||chosen.length>MAX_RESEARCH_SOURCES)
        throw Error("Select between one and five private source documents.");
      if(question.length<3||question.length>320)
        throw Error("Enter a question between 3 and 320 characters.");
      researchStatus("Verifying selected files and searching source text locally…");
      const infos=await Promise.all(chosen.map(path=>
        api("/api/documents/research/source-info?path="+encodeURIComponent(path))));
      if(!root.isConnected||token!==researchRunId)return;
      const pinned=Object.fromEntries(infos.map(source=>[source.path,source]));
      const request=researchRequest(question,chosen,pinned,mode);
      researchStatus(mode==="synthesis"?
        "Searching source passages, then preparing optional local-model notes…":
        "Retrieving exact passage evidence without calling any AI model…");
      const result=await api("/api/documents/research/query",request);
      if(!root.isConnected||token!==researchRunId||
          question!==at("daResearchQuestion").value.trim()||
          mode!==at("daResearchMode").value)return;
      const view=verifiedResearchView(result,request);
      at("daResearchResult").hidden=false;
      at("daResearchSummary").textContent=view.evidence.length+
        " source-grounded passage(s) from "+request.sources.length+
        " selected file(s)."+(view.partialSources.length?
          " Warning: some source contents were truncated.":"");
      const container=at("daResearchEvidence");
      container.replaceChildren();
      for(const item of view.evidence){
        const card=document.createElement("article");
        card.className="da-research-evidence-card";
        const name=document.createElement("h4");
        name.textContent="["+item.id+"] "+item.source+
          (item.page?" · PDF page "+item.page:" · "+item.section);
        const quote=document.createElement("blockquote");
        quote.textContent=item.quote;
        const details=document.createElement("p");
        details.className="muted small";
        details.textContent="Source SHA-256: "+item.sha256.slice(0,16)+
          "… · Extracted section offset "+item.offset+
          " · Verify full source context before citing.";
        card.append(name,quote,details);
        const open=document.createElement("button");
        open.type="button";open.className="btn";
        open.textContent="Open original source";
        open.onclick=()=>openDocument(item.source);
        card.append(open);
        container.append(card);
      }
      const points=at("daResearchSynthesis");
      points.replaceChildren();
      if(view.synthesis.length){
        const heading=document.createElement("h4");
        heading.textContent="Local AI interpretations — not independently verified";
        points.append(heading);
        for(const claim of view.synthesis){
          const paragraph=document.createElement("p");
          paragraph.textContent=claim.claim+" ("+claim.evidence_ids.join(", ")+")";
          points.append(paragraph);
        }
      }
      if(!view.evidence.length){
        const noResult=document.createElement("p");
        noResult.textContent="No matching passages were found in the selected, extracted text. This does not prove that the topic is absent from the original files.";
        container.append(noResult);
      }
      at("daResearchNotes").value=researchNotes(question,view);
      at("daResearchLimitations").textContent=view.limitations;
      researchStatus("Research results are read-only. Copy notes if useful; verify every quotation and add real reference details yourself.");
    }catch(error){
      if(token===researchRunId&&root.isConnected){
        at("daResearchResult").hidden=true;
        researchStatus("Research search failed: "+error.message,true);
      }
    }finally{
      researchBusy=false;
      if(root.isConnected)at("daResearchRun").disabled=false;
    }
  };
  function richStatus(text,error=false){
    at("daRichStatus").textContent=text;
    at("daRichStatus").classList.toggle("da-error",error);
  }
  async function loadRichStructure(documentData){
    richStatus("Reading actual Word paragraphs, text runs and table cells…");
    try{
      const value=await api("/api/documents/docx/structure?path="+encodeURIComponent(documentData.path));
      if(!root.isConnected||!current||current.path!==documentData.path)return;
      if(value.sha256!==documentData.sha256)throw Error("Original changed; reopen document.");
      richStructure=value;
      at("daRichStats").textContent=value.paragraphs.length+" displayed paragraphs · "+
        value.tables.length+" tables · "+value.images+" images · "+value.sections+
        " sections"+(value.truncated?" (large structure truncated; edit visible items only)":"");
      at("daRichParagraph").innerHTML=value.paragraphs.map(p=>
        '<option value="'+p.index+'">'+p.index+' · '+esc(p.style)+' · '+
        esc((p.text||"(empty)").slice(0,62))+'</option>').join("");
      at("daRichTable").innerHTML=value.tables.map(t=>
        '<option value="'+t.index+'">Table '+t.index+' · '+t.rows+' rows × '+
        t.columns+' columns</option>').join("");
      at("daRichRow").value="0";at("daRichCell").value="0";
      renderRichControls();
      richStatus("Word structure loaded. Every operation produces a new copy.");
    }catch(error){richStructure=null;richStatus("Cannot edit this Word structure: "+error.message,true);}
  }
  const richAt=id=>at("daRich"+id);
  function renderRichControls(){
    if(!richStructure)return;
    const action=at("daRichAction").value;
    const paragraph=richStructure.paragraphs.find(
      x=>x.index===Number(at("daRichParagraph").value))||richStructure.paragraphs[0];
    const table=richStructure.tables.find(
      x=>x.index===Number(at("daRichTable").value))||richStructure.tables[0];
    const pNeeded=["replace_run","set_style","insert_image"].includes(action);
    const tableNeeded=["table_cell","append_row"].includes(action);
    at("daRichParagraphLabel").hidden=!pNeeded;
    at("daRichRunLabel").hidden=action!=="replace_run";
    at("daRichStyleLabel").hidden=action!=="set_style";
    at("daRichTableLabel").hidden=!tableNeeded;
    at("daRichRowLabel").hidden=action!=="table_cell";
    at("daRichCellLabel").hidden=action!=="table_cell";
    at("daRichImageLabel").hidden=action!=="insert_image";
    at("daRichWidthLabel").hidden=action!=="insert_image";
    at("daRichCurrentLabel").hidden=!["replace_run","table_cell"].includes(action);
    at("daRichNewLabel").hidden=!["replace_run","table_cell","append_row"].includes(action);
    at("daRichRun").innerHTML=paragraph?paragraph.runs.map(r=>
      '<option value="'+r.index+'">Run '+r.index+' · '+esc((r.text||"(empty)").slice(0,80))+
      '</option>').join(""):"";
    if(table){
      at("daRichRow").max=Math.max(0,Math.min(table.rows,12)-1);
      at("daRichCell").max=Math.max(0,Math.min(table.columns,12)-1);
    }
    const run=paragraph?.runs.find(r=>r.index===Number(at("daRichRun").value));
    const row=Number(at("daRichRow").value),cell=Number(at("daRichCell").value);
    const existing=action==="replace_run"?run?.text:
      action==="table_cell"?table?.preview[row]?.[cell]:"";
    if(existing!==undefined&&existing!==null)at("daRichCurrent").value=existing;
    else at("daRichCurrent").value="";
    if(action==="append_row"){
      at("daRichNewLabel").firstChild.textContent="New row values (one cell per line)";
      at("daRichInstruction").textContent="Enter "+(table?.columns||0)+
        " values, one per line; complex merged tables are refused.";
    }else if(action==="table_cell"){
      at("daRichNewLabel").firstChild.textContent="Replacement cell text";
      at("daRichInstruction").textContent="Only single-paragraph simple cells are edited; other Word formatting stays unchanged.";
    }else if(action==="replace_run"){
      at("daRichNewLabel").firstChild.textContent="Replacement run text";
      at("daRichInstruction").textContent="This operation preserves other runs, inline images and paragraph styles.";
    }else if(action==="set_style"){
      at("daRichInstruction").textContent="Change only the selected paragraph's style; words, tables and images stay intact.";
    }else{
      at("daRichInstruction").textContent="Choose your private PNG/JPEG. It will be inserted after the selected paragraph in a new Word copy.";
    }
    at("daRichSave").disabled=!richStructure||
      (pNeeded&&!paragraph)||(tableNeeded&&!table)||
      (action==="replace_run"&&!run);
  }
  async function saveRichCopy(){
    if(!current||current.kind!=="docx"||!richStructure)return;
    if(current.sha256!==richStructure.sha256){richStatus("Original changed. Reopen it before editing.",true);return;}
    const action=at("daRichAction").value;
    const op={kind:action};
    if(["replace_run","set_style","insert_image"].includes(action))
      op.paragraph=Number(at("daRichParagraph").value);
    if(action==="replace_run"){
      op.run=Number(at("daRichRun").value);
      op.expected=at("daRichCurrent").value;
      op.text=at("daRichNew").value;
    }else if(action==="set_style")op.style=at("daRichStyle").value;
    else if(["table_cell","append_row"].includes(action)){
      op.table=Number(at("daRichTable").value);
      if(action==="table_cell"){
        op.row=Number(at("daRichRow").value);
        op.cell=Number(at("daRichCell").value);
        op.expected=at("daRichCurrent").value;
        op.text=at("daRichNew").value;
      }else op.values=at("daRichNew").value.split(/\r?\n/);
    }else if(action==="insert_image"){
      const image=at("daRichImage").files?.[0];
      if(!image){richStatus("Choose a private PNG or JPEG file.",true);return;}
      op.width_cm=Number(at("daRichWidth").value);
      if(!Number.isFinite(op.width_cm)||op.width_cm<=0||op.width_cm>14){
        richStatus("Image width must be between 0 and 14 cm.",true);return;
      }
    }
    if(!window.confirm("Create a new Word copy with this change? The original will remain unchanged."))return;
    const button=at("daRichSave");button.disabled=true;
    try{
      richStatus("Applying the approved structured edit to a separate Word copy…");
      if(action==="insert_image"){
        const uploaded=await uploadFile(at("daRichImage").files[0],"uploads");
        op.image_path=uploaded.path;
      }
      const result=await api("/api/documents/docx/revise",{
        path:current.path,sha256:current.sha256,operations:[op]});
      linkTo(result.path,"Download edited DOCX");
      richStatus("Created a separate Word copy. Inspect it before sharing: "+result.path);
      await refreshLibrary();
      toast("Revised Word copy saved");
    }catch(error){richStatus("Word copy edit failed: "+error.message,true);}
    finally{button.disabled=false;renderRichControls();}
  }
  at("daRichAction").onchange=()=>{at("daRichNew").value="";renderRichControls();};
  at("daRichParagraph").onchange=()=>{at("daRichRun").value="0";renderRichControls();};
  at("daRichRun").onchange=()=>{const paragraph=richStructure?.paragraphs.find(
    p=>p.index===Number(at("daRichParagraph").value));
    const run=paragraph?.runs.find(r=>r.index===Number(at("daRichRun").value));
    at("daRichCurrent").value=run?.text||"";};
  for(const id of ["daRichTable","daRichRow","daRichCell"]){
    at(id).onchange=renderRichControls;
  }
  at("daRichSave").onclick=saveRichCopy;
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
    return {name:cleanName(),markdown,options:readOptions(),
      publication:publicationOptions(publication)};
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
      status("Exported "+data.path+". This is a new file, not an overwrite."+
        (data.warnings?.length?" Review warnings: "+data.warnings.join(" "):""));
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

  function renderReferenceList(){
    const list=at("daReferenceList");
    if(!publication.references.length){
      list.innerHTML='<p class="muted small">No sources entered. Bibliographies are never invented.</p>';return;
    }
    list.innerHTML=publication.references.map(ref=>
      '<article class="da-ref-card"><span class="da-ref-id">'+esc(ref.id)+'</span>'+
      '<span class="da-ref-name">'+esc(ref.authors)+' ('+esc(ref.year)+') · '+esc(ref.title)+'</span>'+
      '<button class="btn" type="button" data-da-cite="'+esc(ref.id)+'">Insert citation</button>'+
      '<button class="btn" type="button" data-da-delete-ref="'+esc(ref.id)+'">Remove</button></article>'
    ).join("");
  }
  function setPublication(value){
    publication=publicationOptions(value);
    at("daRefStyle").value=publication.reference_style;
    at("daCover").checked=publication.cover_page;
    at("daContents").checked=publication.contents_page;
    at("daTemplate").value=publication.template;
    at("daPubAuthor").value=publication.author||"";
    at("daPubInstitution").value=publication.institution||"";
    at("daPubDate").value=publication.document_date||"";
    at("daPubHeader").value=publication.header||"";
    at("daPubFooter").value=publication.footer||"";
    renderReferenceList();
  }
  const pubFields={
    daRefStyle:"reference_style",daCover:"cover_page",daContents:"contents_page",
    daPubAuthor:"author",daPubInstitution:"institution",daPubDate:"document_date",
    daPubHeader:"header",daPubFooter:"footer"
  };
  for(const [id,key] of Object.entries(pubFields)){
    at(id).onchange=()=>{
      publication[key]=at(id).type==="checkbox"?at(id).checked:at(id).value;
      commitEditor("publication",false);
    };
  }
  at("daAddReference").onclick=()=>{
    const record={
      id:at("daRefId").value.trim(),authors:at("daRefAuthors").value.trim(),
      title:at("daRefTitle").value.trim(),year:at("daRefYear").value.trim(),
      type:at("daRefType").value,
    };
    const publisher=at("daRefPublisher").value.trim(),url=at("daRefUrl").value.trim(),
          doi=at("daRefDoi").value.trim();
    if(publisher)record[record.type==="journal"?"journal":"publisher"]=publisher;
    if(url)record.url=url;
    if(doi)record.doi=doi;
    try{
      const next=addReference(publication,record);
      publication=next;renderReferenceList();
      for(const id of ("daRefId","daRefAuthors","daRefTitle","daRefYear","daRefPublisher","daRefUrl","daRefDoi"))
        at(id).value="";
      commitEditor("reference",false);
      status("Reference added from the details you entered. Insert it into the document when needed.");
    }catch(error){status("Reference not added: "+error.message,true);}
  };
  at("daReferenceList").onclick=e=>{
    const cite=e.target.closest("[data-da-cite]");
    const remove=e.target.closest("[data-da-delete-ref]");
    if(cite){
      const ref=publication.references.find(r=>r.id===cite.dataset.daCite);
      if(!ref)return;
      try{
        const insertion=insertCitation(source.value,source.selectionStart,source.selectionEnd,ref);
        source.value=insertion.markdown;
        source.focus();source.setSelectionRange(insertion.start,insertion.end);
        commitEditor("citation",false);
        status("Inserted source reference marker. Publication resolves it to the selected citation style.");
      }catch(error){status(error.message,true);}
    }else if(remove){
      const id=remove.dataset.daDeleteRef;
      if(source.value.includes("[@"+id+"]") &&
         !window.confirm("This reference is cited in your document. Removing it will leave unresolved citations until you fix them. Continue?"))return;
      publication=removeReference(publication,id);renderReferenceList();
      commitEditor("reference",false);
    }
  };
  at("daApplyTemplate").onclick=()=>{
    const id=at("daTemplate").value,item=templateById(templates,id);
    if(!item){status("Choose an available document template first.",true);return;}
    if(!window.confirm("Replace your current editable document with this template? Unsaved edits may be lost; you can Undo."))return;
    publication.template=id;
    at("daName").value=item.name;
    source.value=item.markdown;
    commitEditor("template",false);
    status("Template inserted. All square-bracket placeholders must be replaced with your own verified details.");
  };
  at("daPreflight").onclick=async()=>{
    const button=at("daPreflight");button.disabled=true;
    at("daPreflightResult").textContent="Verifying the complete Word document locally…";
    try{
      const result=await api("/api/documents/preflight",editorData());
      at("daPreflightResult").textContent="Word preflight passed: "+result.headings+
        " headings, "+result.tables+" tables, "+result.reference_count+" references. "+
        (result.warnings?.length?result.warnings.join(" "):
          "No structural warnings. Check wording, source authenticity and visual pagination yourself.");
    }catch(error){
      at("daPreflightResult").textContent="Word preflight failed: "+error.message;
    }finally{button.disabled=false;}
  };
  async function loadTemplates(){
    try{
      const result=await api("/api/documents/templates");
      templates=Array.isArray(result.templates)?result.templates:[];
      at("daTemplate").innerHTML='<option value="">Choose a template…</option>'+
        templates.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.name)+'</option>').join("");
      at("daTemplate").value=publication.template;
    }catch(error){at("daPreflightResult").textContent="Templates unavailable: "+error.message;}
  }
  at("daAIRun").onclick=runAIReview;
  at("daAIClear").onclick=resetAI;
  at("daAIApply").onclick=applyAIReview;
  at("daAIAction").onchange=resetAI;
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
  source.oninput=()=>{commitEditor("source",true);if(pendingAI)aiStatus("Source changed; review again before applying.",true);};
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
  await loadTemplates();
  refreshAIContext();
  const openPath=sessionStorage.getItem("automoto_document_open_path");
  sessionStorage.removeItem("automoto_document_open_path");
  if(openPath)await openDocument(openPath);
  else newDocument();
}

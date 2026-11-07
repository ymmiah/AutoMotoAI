/* AutoMoto AI — Invoice & Spreadsheet Intelligence v3.
   Safe XLSX styling, bounded editing, local sorting/filtering and cell validation. */
import {blankBook,setGridCell,workbookPayload,invoicePayload,createWorkbookHistory,MAX_SHEETS,MAX_ROWS,MAX_COLS}
  from "./spreadsheet-model.js";
import {styleAt,applyCellStyle,setColumnRule,validateEntry,filterIndices,sortSheetRows,NUMBER_FORMATS}
  from "./spreadsheet-editing.js";

export async function mountSpreadsheetStudio({api,page,uploadFile}){
  const html='<div class="ss-shell">'+
    '<div class="ss-tabs" role="tablist" aria-label="Workspace mode">'+
      '<button type="button" role="tab" id="ssTabBook" aria-selected="true" aria-controls="ssBook">Spreadsheets</button>'+
      '<button type="button" role="tab" id="ssTabInvoice" aria-selected="false" aria-controls="ssInvoice">Invoices</button>'+
    '</div>'+
    '<section id="ssBook" role="tabpanel" aria-labelledby="ssTabBook">'+
      '<div class="ss-panel ss-tools"><div><h3>Workbook editor</h3><p>Safe offline formulas, dependencies, validation and private workbook drafts.</p></div>'+
      '<div class="ss-actions"><button type="button" class="btn" id="ssNew">New workbook</button>'+
        '<button type="button" class="btn" id="ssUndo" disabled>Undo</button>'+
        '<button type="button" class="btn" id="ssRedo" disabled>Redo</button>'+
        '<button type="button" class="btn" id="ssSave">Save private copy</button>'+
        '<button type="button" class="btn primary" id="ssExport">Export XLSX</button></div></div>'+
      '<div class="ss-fields"><label>Workbook name<input class="input" id="ssBookName" maxlength="100"></label>'+
        '<label>Export format<select class="input" id="ssFormat"><option value="xlsx">Excel (.xlsx)</option><option value="csv">CSV (single sheet)</option></select></label>'+
        '<label>Calculation mode<select class="input" id="ssCalcMode" aria-describedby="ssCalcHint"><option value="formulas">Enable safe formulas</option><option value="literal">Literal text (legacy/imports)</option></select></label></div>'+
      '<div class="ss-panel ss-calc-controls"><div><strong>Formula calculation</strong><p id="ssCalcHint">Formulas operate only on the selected worksheet, without macros, remote links or arbitrary code. Old workbooks stay literal until enabled.</p></div>'+
        '<button type="button" class="btn" id="ssCalculate">Recalculate</button></div>'+
      '<div class="ss-import ss-panel"><div><strong>Import from this workspace</strong><p>CSV and XLSX only. V3 imports basic visible cell styling; advanced layouts are not round-tripped, and originals remain unchanged.</p></div>'+
        '<div class="ss-actions"><select class="input" id="ssImportPick" aria-label="Previously uploaded spreadsheets"></select>'+
          '<button type="button" class="btn" id="ssImport">Open upload</button>'+
          '<label class="ss-file-btn btn" for="ssUpload">Upload CSV/XLSX</label><input type="file" id="ssUpload" accept=".csv,.xlsx" hidden></div></div>'+
      '<div class="ss-panel ss-saved"><label>Saved private workbooks<select id="ssSavedBooks" class="input"></select></label>'+
        '<button type="button" class="btn" id="ssLoad">Load selected</button></div>'+
      '<div class="ss-sheets" id="ssSheets" role="tablist" aria-label="Worksheets"></div>'+
      '<div class="ss-grid-tools"><strong id="ssSheetLabel">Sheet1</strong>'+
        '<div class="ss-actions"><button class="btn" id="ssAddSheet" type="button">Add sheet</button>'+
          '<button class="btn" id="ssRenameSheet" type="button">Rename</button>'+
          '<button class="btn" id="ssRows" type="button">+10 rows</button>'+
          '<button class="btn" id="ssCols" type="button">+1 column</button></div></div>'+
      '<section class="ss-panel ss-edit-panel" aria-label="Professional spreadsheet editing">'+
        '<div class="ss-edit-title"><strong>Professional editing</strong><span>Formatting, sort/filter and column rules · offline</span></div>'+
        '<div class="ss-edit-group">'+
          '<label>Column<select class="input" id="ssToolsColumn"></select></label>'+
          '<label>Filter contains<input class="input" type="search" id="ssFilterText" placeholder="Show matching rows"></label>'+
          '<button type="button" class="btn" id="ssSortAsc">Sort A–Z</button>'+
          '<button type="button" class="btn" id="ssSortDesc">Sort Z–A</button>'+
          '<button type="button" class="btn" id="ssClearFilter">Clear filter</button>'+
        '</div>'+
        '<div class="ss-edit-group">'+
          '<label>Freeze<select class="input" id="ssFreeze"><option value="none">No panes</option><option value="row">Header row</option><option value="column">First column</option><option value="both">Row and column</option></select></label>'+
          '<label>Column width<input class="input" id="ssWidth" type="number" min="8" max="48" step="1" value="18"></label>'+
          '<label class="ss-check"><input type="checkbox" id="ssExcelFilter" checked> Excel filter buttons</label>'+
          '<button type="button" class="btn" id="ssApplyLayout">Apply layout</button>'+
        '</div>'+
        '<div class="ss-edit-group">'+
          '<label>Selected cell<input class="input" readonly id="ssSelectedCell" value="A1"></label>'+
          '<label class="ss-check"><input type="checkbox" id="ssStyleBold"> Bold</label>'+
          '<label class="ss-check"><input type="checkbox" id="ssStyleItalic"> Italic</label>'+
          '<label>Alignment<select class="input" id="ssStyleAlign"><option value="left">Left</option><option value="center">Centre</option><option value="right">Right</option></select></label>'+
          '<label>Number format<select class="input" id="ssStyleFormat"><option value="general">General</option><option value="number">Number</option><option value="integer">Integer</option><option value="gbp">GBP</option><option value="usd">USD</option><option value="eur">EUR</option><option value="percent">Percentage</option></select></label>'+
          '<label>Fill<input aria-label="Cell fill colour" id="ssStyleFill" type="color" value="#ffffff"></label>'+
          '<label>Text<input aria-label="Cell text colour" id="ssStyleText" type="color" value="#1e293b"></label>'+
          '<button type="button" class="btn primary" id="ssApplyStyle">Style selected cell</button>'+
        '</div>'+
        '<div class="ss-edit-group">'+
          '<label>Column rule<select class="input" id="ssValidationKind"><option value="none">No new rule</option><option value="list">Dropdown list</option><option value="whole">Whole number</option><option value="decimal">Decimal number</option></select></label>'+
          '<label>List choices (comma-separated)<input class="input" id="ssValidationOptions" maxlength="240" placeholder="Open,In progress,Closed"></label>'+
          '<label>Minimum<input class="input" type="number" id="ssValidationMin" step="any" value="0"></label>'+
          '<label>Maximum<input class="input" type="number" id="ssValidationMax" step="any" value="100"></label>'+
          '<button type="button" class="btn" id="ssApplyValidation">Apply column rule</button>'+
        '</div>'+
        '<p class="ss-hint">Sort keeps the header and matching cell formatting together. Sorting is disabled when a worksheet contains formulas to protect references. Filtering changes only the visible view; exports still contain every row.</p>'+
      '</section>'+
      '<div class="ss-grid-wrap" tabindex="0" aria-label="Editable workbook grid"><table class="ss-grid" id="ssGrid"></table></div>'+
      '<section class="ss-panel ss-formula-panel" aria-label="Formula results"><strong>Calculated values</strong>'+
        '<p id="ssCalcSummary" role="status" aria-live="polite">No formulas calculated.</p>'+
        '<div id="ssCalcResults" class="ss-formula-results"></div></section>'+
      '<p class="ss-hint">Formula mode supports +, −, ×, ÷, ^, comparisons, IF, SUM, AVERAGE, MIN, MAX, COUNT and COUNTA, with same-sheet A1:P100 references and ranges. Imported/legacy workbooks remain literal unless calculation mode is enabled. Excel must recalculate exported formula cells when opened.</p>'+
    '</section>'+
    '<section id="ssInvoice" role="tabpanel" aria-labelledby="ssTabInvoice" hidden>'+
      '<div class="ss-panel ss-tools"><div><h3>Invoice drafts</h3><p>Create private draft invoices with precise decimal totals. No invoices are sent or marked paid.</p></div>'+
        '<div class="ss-actions"><button type="button" class="btn" id="ssInvoiceSave">Save private draft</button>'+
        '<button type="button" class="btn primary" id="ssInvoiceExport">Export draft XLSX</button></div></div>'+
      '<div class="ss-fields ss-invoice-fields">'+
        '<label>Invoice number<input class="input" id="ssInvoiceNumber" maxlength="60" placeholder="Your invoice number"></label>'+
        '<label>Invoice date<input class="input" type="date" id="ssIssued"></label>'+
        '<label>Due date<input class="input" type="date" id="ssDue"></label>'+
        '<label>Currency<select class="input" id="ssCurrency"><option>GBP</option><option>EUR</option><option>USD</option></select></label>'+
        '<label>Seller details<textarea class="input" id="ssSeller" rows="3" maxlength="500" placeholder="Your business details"></textarea></label>'+
        '<label>Customer details<textarea class="input" id="ssCustomer" rows="3" maxlength="500" placeholder="Customer details"></textarea></label>'+
        '<label>Tax / VAT rate (%)<input class="input" id="ssTax" inputmode="decimal" value="0" aria-describedby="ssTaxHint"></label>'+
        '<p class="ss-hint" id="ssTaxHint">Default 0% is not a tax determination. Set the applicable rate and verify all legal invoice requirements.</p></div>'+
      '<div class="ss-panel"><div class="ss-line-head"><h3>Line items</h3><button type="button" class="btn" id="ssAddLine">Add item</button></div>'+
        '<div class="ss-invoice-table-wrap"><table class="ss-line-table"><thead><tr><th>Description</th><th>Quantity</th><th>Unit price</th><th></th></tr></thead>'+
        '<tbody id="ssInvoiceLines"></tbody></table></div></div>'+
      '<div class="ss-panel ss-summary"><div class="ss-actions"><button type="button" class="btn primary" id="ssPreview">Calculate precise totals</button></div>'+
        '<div id="ssTotals" aria-live="polite">Enter complete invoice details and calculate the totals.</div></div>'+
      '<div class="ss-panel ss-saved"><label>Saved invoice drafts<select class="input" id="ssSavedInvoices"></select></label>'+
        '<button type="button" class="btn" id="ssInvoiceLoad">Load selected draft</button></div>'+
      '<p class="ss-hint">Draft only. Verify seller identity, VAT registration, terms, currency and tax before you issue any invoice. PDF invoicing and richer templates follow in v4.</p>'+
    '</section>'+
    '<p id="ssStatus" class="ss-status" role="status" aria-live="polite">Ready. Changes are kept in this session until you save or export.</p>'+
    '<div id="ssDownload" class="ss-download" aria-live="polite"></div></div>';
  const root=page("Invoice & Spreadsheet Intelligence",
    "Offline workbook editing and invoice drafts, integrated into AutoMoto AI.",html);
  root.classList.add("ss-page");
  const el=id=>root.querySelector("#"+id);
  let book=blankBook(),activeSheet=0,gridRows=15,gridCols=8;
  const history=createWorkbookHistory(book);
  let calculationSeq=0,calculation=null;
  let invoiceLines=[{description:"",quantity:"1",unit_price:"0.00"}];
  let invoiceResult=null;
  const status=(message,error=false)=>{
    el("ssStatus").textContent=message;
    el("ssStatus").classList.toggle("ss-error",error);
  };
  const showDownload=(result)=>{
    const panel=el("ssDownload");
    panel.replaceChildren();
    const a=document.createElement("a");
    a.className="btn primary";
    a.textContent="Download "+(result.format||"file").toUpperCase();
    a.href="/api/files/download?path="+encodeURIComponent(result.path);
    a.setAttribute("download","");
    panel.append(a);
  };
  const setTab=(tab)=>{
    const bookTab=tab==="book";
    el("ssBook").hidden=!bookTab;
    el("ssInvoice").hidden=bookTab;
    el("ssTabBook").setAttribute("aria-selected",String(bookTab));
    el("ssTabInvoice").setAttribute("aria-selected",String(!bookTab));
  };
  el("ssTabBook").onclick=()=>setTab("book");
  el("ssTabInvoice").onclick=()=>setTab("invoice");
  root.querySelector(".ss-tabs").onkeydown=e=>{
    if(!["ArrowLeft","ArrowRight"].includes(e.key))return;
    e.preventDefault();
    const next=e.target===el("ssTabBook")?"invoice":"book";
    setTab(next);
    el(next==="book"?"ssTabBook":"ssTabInvoice").focus();
  };
  const heading=col=>String.fromCharCode(65+col);
  const syncName=()=>{book.name=el("ssBookName").value;};
  let selectedCell="A1",viewFilter="",viewColumn=0;
  for(let n=0;n<MAX_COLS;n++){
    const option=document.createElement("option");
    option.value=String(n);option.textContent=heading(n);
    el("ssToolsColumn").append(option);
  }
  function currentSheet(){return book.sheets[activeSheet];}
  function syncStyleControls(){
    const style=styleAt(currentSheet(),selectedCell);
    el("ssSelectedCell").value=selectedCell;
    el("ssStyleBold").checked=style.bold;
    el("ssStyleItalic").checked=style.italic;
    el("ssStyleAlign").value=style.align;
    el("ssStyleFormat").value=style.number_format;
    el("ssStyleFill").value=style.fill;
    el("ssStyleText").value=style.color;
  }
  function syncSheetControls(){
    const sheet=currentSheet();
    el("ssFreeze").value=sheet.freeze??"row";
    el("ssExcelFilter").checked=sheet.filter_enabled??true;
    const letter=heading(viewColumn);
    el("ssWidth").value=String(sheet.column_widths?.[letter]??18);
    const rule=(sheet.validations||[]).find(x=>x.column===letter);
    el("ssValidationKind").value=rule?.kind??"none";
    el("ssValidationOptions").value=(rule?.options||[]).join(",");
    el("ssValidationMin").value=String(rule?.min_value??0);
    el("ssValidationMax").value=String(rule?.max_value??100);
    syncStyleControls();
  }
  el("ssToolsColumn").onchange=()=>{
    viewColumn=Number(el("ssToolsColumn").value);syncSheetControls();renderGrid();
  };
  el("ssFilterText").oninput=()=>{
    viewFilter=el("ssFilterText").value;renderGrid();
    status(viewFilter?"Temporary view filter active. No rows are deleted.":"Showing all rows.");
  };
  el("ssClearFilter").onclick=()=>{
    viewFilter="";el("ssFilterText").value="";renderGrid();status("All rows restored.");
  };
  function sortRows(descending){
    try{
      sortSheetRows(currentSheet(),viewColumn,descending);
      recordWorkbookChange();renderGrid();recalculate();
      status("Sorted entire data rows with header and cell formatting preserved. Save to keep it.");
    }catch(error){status(error.message,true);}
  }
  el("ssSortAsc").onclick=()=>sortRows(false);
  el("ssSortDesc").onclick=()=>sortRows(true);
  el("ssApplyLayout").onclick=()=>{
    try{
      const width=Number(el("ssWidth").value);
      if(!Number.isInteger(width)||width<8||width>48)throw Error("Column width must be 8–48.");
      currentSheet().freeze=el("ssFreeze").value;
      currentSheet().filter_enabled=el("ssExcelFilter").checked;
      currentSheet().column_widths={...(currentSheet().column_widths||{}),[heading(viewColumn)]:width};
      recordWorkbookChange();renderGrid();
      status("Freeze, Excel filtering and column width updated in your workbook.");
    }catch(error){status(error.message,true);}
  };
  el("ssApplyStyle").onclick=()=>{
    try{
      applyCellStyle(currentSheet(),selectedCell,{
        bold:el("ssStyleBold").checked,italic:el("ssStyleItalic").checked,
        align:el("ssStyleAlign").value,number_format:el("ssStyleFormat").value,
        fill:el("ssStyleFill").value,color:el("ssStyleText").value
      });
      recordWorkbookChange();renderGrid();
      status("Applied formatting to "+selectedCell+". Save a private copy to retain it.");
    }catch(error){status(error.message,true);}
  };
  el("ssApplyValidation").onclick=()=>{
    const sheet=currentSheet(),column=heading(viewColumn);
    const previous=[...(sheet.validations||[])];
    try{
      const kind=el("ssValidationKind").value;
      if(kind==="none"){
        sheet.validations=previous.filter(x=>x.column!==column);
      }else{
        setColumnRule(sheet,{column,kind,options:el("ssValidationOptions").value,
          min_value:el("ssValidationMin").value,max_value:el("ssValidationMax").value});
        for(let rowIndex=1;rowIndex<sheet.rows.length;rowIndex++){
          const issue=validateEntry(sheet,rowIndex,viewColumn,sheet.rows[rowIndex]?.[viewColumn]);
          if(issue)throw Error("Existing row "+(rowIndex+1)+": "+issue);
        }
      }
      recordWorkbookChange();renderGrid();syncSheetControls();
      status("Column "+column+" validation updated. It will also be written to XLSX.");
    }catch(error){
      sheet.validations=previous;
      status("Validation not applied: "+error.message,true);
    }
  };
  el("ssGrid").addEventListener("focusin",event=>{
    const input=event.target.closest("input.ss-cell");
    if(!input)return;
    selectedCell=heading(Number(input.dataset.col))+(Number(input.dataset.row)+1);
    syncStyleControls();
  });
  function updateHistoryButtons(){
    const controls=history.state();
    el("ssUndo").disabled=!controls.canUndo;
    el("ssRedo").disabled=!controls.canRedo;
  }
  function recordWorkbookChange(){
    history.record(book);
    updateHistoryButtons();
  }
  function restoreHistory(next){
    if(!next)return;
    book=next;
    activeSheet=Math.min(activeSheet,book.sheets.length-1);
    gridRows=Math.min(MAX_ROWS,Math.max(gridRows,...book.sheets.map(s=>s.rows.length)));
    gridCols=Math.min(MAX_COLS,Math.max(gridCols,...book.sheets.flatMap(s=>s.rows.map(row=>row.length))));
    el("ssBookName").value=book.name;
    el("ssCalcMode").value=book.calculation_mode||"literal";
    ++calculationSeq;calculation=null;
    el("ssDownload").replaceChildren();
    updateHistoryButtons();renderSheets();syncSheetControls();renderGrid();recalculate();
    status("Workbook change restored in memory. Save a new private copy when ready.");
  }
  el("ssUndo").onclick=()=>restoreHistory(history.undo());
  el("ssRedo").onclick=()=>restoreHistory(history.redo());
  el("ssCalcMode").onchange=()=>{
    book.calculation_mode=el("ssCalcMode").value;
    recordWorkbookChange();++calculationSeq;calculation=null;
    refreshCalculatedCells();recalculate();
    status(book.calculation_mode==="formulas"
      ?"Safe formula calculation enabled. Existing =-prefixed text will be interpreted as formulas."
      :"Literal mode enabled. All =-prefixed text remains unchanged.");
  };
  el("ssCalculate").onclick=()=>recalculate();
  function refreshCalculatedCells(){
    const mode=book.calculation_mode||"literal";
    const sheetName=book.sheets[activeSheet].name;
    const byCell=new Map((calculation?.results||[])
      .filter(row=>row.sheet===sheetName).map(item=>[item.cell,item]));
    el("ssGrid").querySelectorAll("input.ss-cell").forEach(input=>{
      const row=Number(input.dataset.row),col=Number(input.dataset.col);
      const address=heading(col)+(row+1);
      const original=book.sheets[activeSheet].rows[row]?.[col];
      const label=input.parentElement.querySelector(".ss-evaluated");
      if(!label)return;
      const value=byCell.get(address);
      label.hidden=!(mode==="formulas"&&typeof original==="string"&&original.startsWith("="));
      label.textContent=value?"→ "+String(value.value??""):"Awaiting calculation";
      label.classList.toggle("ss-formula-error",Boolean(value?.error));
    });
    const panel=el("ssCalcResults");
    panel.replaceChildren();
    const results=(calculation?.results||[]).filter(row=>row.sheet===sheetName);
    for(const result of results){
      const button=document.createElement("button");
      button.type="button";button.className="ss-formula-item";
      button.textContent=result.cell+" = "+String(result.value??"");
      button.classList.toggle("ss-formula-error",Boolean(result.error));
      button.title=result.error?"Formula error "+result.error:"Show formula in "+result.cell;
      button.onclick=()=>{
        const cell=/^([A-P])([1-9][0-9]*)$/.exec(result.cell);
        if(!cell)return;
        const input=el("ssGrid").querySelector(
          'input[data-row="'+(Number(cell[2])-1)+'"][data-col="'+(cell[1].charCodeAt(0)-65)+'"]');
        input?.focus();input?.select();
      };
      panel.append(button);
    }
    const summary=el("ssCalcSummary");
    if(mode==="literal")summary.textContent="Literal mode: formulas are preserved as text. Enable safe formulas to calculate.";
    else if(!calculation)summary.textContent="Awaiting local formula calculation…";
    else summary.textContent=calculation.formula_count+" formula(s) in workbook, "+
      calculation.errors.length+" error(s). Errors must be corrected before exporting.";
  }
  async function recalculate(){
    const run=++calculationSeq;
    if((book.calculation_mode||"literal")==="literal"){
      calculation=null;refreshCalculatedCells();return;
    }
    el("ssCalcSummary").textContent="Calculating locally…";
    try{
      const response=await api("/api/spreadsheets/calculate",workbookPayload(book));
      if(!root.isConnected||run!==calculationSeq)return;
      calculation=response;
      refreshCalculatedCells();
      if(response.errors?.length)status(response.errors.length+
        " formula error(s). Check the calculated values panel and correct them before exporting.",true);
    }catch(error){
      if(!root.isConnected||run!==calculationSeq)return;
      calculation=null;refreshCalculatedCells();
      el("ssCalcSummary").textContent="Calculation failed: "+error.message;
      status("Formula calculation failed: "+error.message,true);
    }
  }
  function renderSheets(){
    const tabs=el("ssSheets");
    tabs.replaceChildren();
    book.sheets.forEach((sheet,index)=>{
      const button=document.createElement("button");
      button.type="button";
      button.role="tab";
      button.className="ss-sheet-tab";
      button.textContent=sheet.name;
      button.setAttribute("aria-selected",String(index===activeSheet));
      button.onclick=()=>{activeSheet=index;selectedCell="A1";viewFilter="";el("ssFilterText").value="";renderSheets();syncSheetControls();renderGrid();refreshCalculatedCells();};
      tabs.append(button);
    });
    el("ssSheetLabel").textContent=book.sheets[activeSheet].name;
    el("ssAddSheet").disabled=book.sheets.length>=MAX_SHEETS;
  }
  function renderGrid(){
    const table=el("ssGrid");
    table.replaceChildren();
    const head=document.createElement("thead"),header=document.createElement("tr");
    const corner=document.createElement("th");
    corner.textContent="#";corner.scope="col";header.append(corner);
    for(let c=0;c<gridCols;c++){
      const th=document.createElement("th");th.scope="col";th.textContent=heading(c);header.append(th);
    }
    head.append(header);table.append(head);
    const body=document.createElement("tbody");
    for(let r=0;r<gridRows;r++){
      const row=document.createElement("tr");
      const number=document.createElement("th");number.scope="row";number.textContent=String(r+1);row.append(number);
      for(let c=0;c<gridCols;c++){
        const td=document.createElement("td"),input=document.createElement("input");
        input.type="text";input.maxLength=2000;input.className="ss-cell";
        input.dataset.row=String(r);input.dataset.col=String(c);
        input.setAttribute("aria-label",heading(c)+(r+1));
        input.value=String(book.sheets[activeSheet].rows[r]?.[c]??"");
        const preview=document.createElement("small");
        preview.className="ss-evaluated";
        preview.setAttribute("aria-live","off");
        preview.hidden=true;
        td.append(input,preview);row.append(td);
      }
      body.append(row);
    }
    table.append(body);
    el("ssRows").disabled=gridRows>=MAX_ROWS;
    el("ssCols").disabled=gridCols>=MAX_COLS;
    refreshCalculatedCells();
  }
  function updateCell(input){
    const r=Number(input.dataset.row),c=Number(input.dataset.col);
    ++calculationSeq;calculation=null;
    setGridCell(book,activeSheet,r,c,input.value);
    refreshCalculatedCells();
    status("Unsaved worksheet edits. Save a private copy to keep them.");
    el("ssDownload").replaceChildren();
  }
  el("ssGrid").addEventListener("input",e=>{
    if(e.target.matches("input.ss-cell"))updateCell(e.target);
  });
  el("ssGrid").addEventListener("change",e=>{
    if(e.target.matches("input.ss-cell")){recordWorkbookChange();recalculate();}
  });
  el("ssGrid").addEventListener("keydown",e=>{
    if(e.key==="Enter"&&e.target.matches("input.ss-cell")&&!e.isComposing){
      e.preventDefault();
      const r=Number(e.target.dataset.row)+1,c=Number(e.target.dataset.col);
      el("ssGrid").querySelector('input[data-row="'+r+'"][data-col="'+c+'"]')?.focus();
    }
  });
  el("ssGrid").addEventListener("paste",e=>{
    const input=e.target.closest("input.ss-cell");
    if(!input)return;
    const clipboard=e.clipboardData?.getData("text/plain")||"";
    if(!clipboard.includes("\t")&&!clipboard.includes("\n"))return;
    e.preventDefault();
    const baseRow=Number(input.dataset.row),baseCol=Number(input.dataset.col);
    const lines=clipboard.replace(/\r\n?/g,"\n").replace(/\n$/,"").split("\n");
    let changed=0;
    for(let r=0;r<lines.length&&baseRow+r<MAX_ROWS;r++){
      const cols=lines[r].split("\t");
      for(let c=0;c<cols.length&&baseCol+c<MAX_COLS;c++){
        setGridCell(book,activeSheet,baseRow+r,baseCol+c,cols[c]);changed++;
      }
    }
    gridRows=Math.min(MAX_ROWS,Math.max(gridRows,baseRow+Math.min(lines.length,MAX_ROWS-baseRow)));
    gridCols=Math.min(MAX_COLS,Math.max(gridCols,baseCol+Math.max(...lines.map(v=>v.split("\t").length))));
    renderGrid();recordWorkbookChange();recalculate();
    status("Pasted "+changed+" cells. Save a private copy.");
    el("ssGrid").querySelector('input[data-row="'+baseRow+'"][data-col="'+baseCol+'"]')?.focus();
  });
  function openBook(data){
    book=data;activeSheet=0;
    gridRows=Math.min(MAX_ROWS,Math.max(15,...book.sheets.map(s=>s.rows.length)));
    gridCols=Math.min(MAX_COLS,Math.max(8,...book.sheets.flatMap(s=>s.rows.map(row=>row.length))));
    el("ssBookName").value=book.name;
    el("ssCalcMode").value=book.calculation_mode||"literal";
    history.reset(book);updateHistoryButtons();
    ++calculationSeq;calculation=null;
    el("ssDownload").replaceChildren();
    selectedCell="A1";viewFilter="";viewColumn=0;
    el("ssFilterText").value="";el("ssToolsColumn").value="0";
    renderSheets();syncSheetControls();renderGrid();setTab("book");recalculate();
  }
  el("ssBookName").oninput=()=>{syncName();status("Unsaved workbook name change.");};
  el("ssBookName").onchange=()=>recordWorkbookChange();
  el("ssNew").onclick=()=>{
    if(!window.confirm("Create a new empty workspace? Unsaved edits in this view will be lost."))return;
    openBook(blankBook());status("New unsaved workbook.");
  };
  el("ssAddSheet").onclick=()=>{
    if(book.sheets.length>=MAX_SHEETS)return;
    let n=book.sheets.length+1,label="Sheet"+n;
    while(book.sheets.some(s=>s.name.toLowerCase()===label.toLowerCase()))label="Sheet"+(++n);
    book.sheets.push({name:label,rows:[]});activeSheet=book.sheets.length-1;
    renderSheets();syncSheetControls();renderGrid();recordWorkbookChange();recalculate();
    status("New worksheet created; save to keep it.");
  };
  el("ssRenameSheet").onclick=()=>{
    const old=book.sheets[activeSheet].name;
    const name=window.prompt("New worksheet name",old);
    if(name===null)return;
    const value=name.trim();
    if(!value||value.length>31||/[\[\]:*?/\\]/.test(value)||
       book.sheets.some((s,i)=>i!==activeSheet&&s.name.toLowerCase()===value.toLowerCase())){
      status("Enter a unique Excel-compatible worksheet name.",true);return;
    }
    book.sheets[activeSheet].name=value;renderSheets();recordWorkbookChange();recalculate();
    status("Worksheet renamed; save to keep it.");
  };
  el("ssRows").onclick=()=>{gridRows=Math.min(MAX_ROWS,gridRows+10);renderGrid();};
  el("ssCols").onclick=()=>{gridCols=Math.min(MAX_COLS,gridCols+1);renderGrid();};

  function selectFill(id,records,placeholder){
    const select=el(id);select.replaceChildren();
    const opt=document.createElement("option");opt.value="";opt.textContent=placeholder;select.append(opt);
    records.forEach(item=>{
      const option=document.createElement("option");
      option.value=item.path;option.textContent=item.name;select.append(option);
    });
  }
  async function refreshLibrary(){
    const data=await api("/api/spreadsheets/list");
    if(!root.isConnected)return;
    selectFill("ssSavedBooks",data.workbooks||[],"Select a saved workbook");
    selectFill("ssSavedInvoices",data.invoices||[],"Select an invoice draft");
    selectFill("ssImportPick",data.imports||[],"Select uploaded XLSX/CSV");
  }
  el("ssImport").onclick=async()=>{
    const path=el("ssImportPick").value;
    if(!path){status("Select an uploaded CSV or Excel file.",true);return;}
    try{
      status("Reading the uploaded spreadsheet safely…");
      const result=await api("/api/spreadsheets/import",{path});
      if(!root.isConnected)return;
      openBook(result.workbook);
      status("Imported into an unsaved V1 preview. "+(result.warnings||[]).join(" "));
    }catch(error){status("Import failed: "+error.message,true);}
  };
  el("ssUpload").onchange=async e=>{
    const file=e.target.files?.[0];
    if(!file)return;
    try{
      if(!/\.(xlsx|csv)$/i.test(file.name))throw Error("Select .xlsx or .csv.");
      status("Uploading "+file.name+"…");
      const uploaded=await uploadFile(file);
      const result=await api("/api/spreadsheets/import",{path:uploaded.path});
      if(!root.isConnected)return;
      openBook(result.workbook);await refreshLibrary();
      status("Imported into an unsaved preview. "+(result.warnings||[]).join(" "));
    }catch(error){status("Upload/import failed: "+error.message,true);}
    finally{e.target.value="";}
  };
  el("ssSave").onclick=async()=>{
    try{
      syncName();const result=await api("/api/spreadsheets/save",workbookPayload(book));
      await refreshLibrary();status("Saved private, create-only workbook: "+result.path);
    }catch(error){status("Save failed: "+error.message,true);}
  };
  el("ssLoad").onclick=async()=>{
    const path=el("ssSavedBooks").value;
    if(!path){status("Select a saved workbook.",true);return;}
    if(!window.confirm("Open the saved workbook? Unsaved edits in this view will be lost."))return;
    try{
      const data=await api("/api/spreadsheets/load?path="+encodeURIComponent(path));
      openBook(data.workbook);status("Loaded private workbook. Editing will not overwrite the saved copy.");
    }catch(error){status("Open failed: "+error.message,true);}
  };
  el("ssExport").onclick=async()=>{
    try{
      syncName();const data={...workbookPayload(book),format:el("ssFormat").value};
      status("Creating a local "+data.format.toUpperCase()+" export…");
      const result=await api("/api/spreadsheets/export",data);
      showDownload(result);
      status(data.calculation_mode==="formulas"
        ?"Export ready. Supported formulas use safe Excel references; Excel recalculates when opened."
        :"Export ready. Literal formula-looking text was not executed.");
    }catch(error){status("Export failed: "+error.message,true);}
  };

  const invoiceFields={number:"ssInvoiceNumber",seller:"ssSeller",customer:"ssCustomer",
    issue_date:"ssIssued",due_date:"ssDue",currency:"ssCurrency",tax_rate:"ssTax"};
  const getInvoice=()=>{
    const form=Object.fromEntries(Object.entries(invoiceFields).map(([key,id])=>[key,el(id).value]));
    return invoicePayload(form,invoiceLines);
  };
  function updateInvoiceInputs(data){
    for(const [key,id] of Object.entries(invoiceFields))el(id).value=data[key]??"";
    invoiceLines=data.lines.map(line=>({...line}));
    invoiceResult=null;renderInvoiceLines();el("ssTotals").textContent="Review details and calculate totals.";
    setTab("invoice");
  }
  function renderInvoiceLines(){
    const list=el("ssInvoiceLines");list.replaceChildren();
    invoiceLines.forEach((line,index)=>{
      const tr=document.createElement("tr");
      for(const field of ["description","quantity","unit_price"]){
        const td=document.createElement("td"),input=document.createElement("input");
        input.type="text";input.className="input";
        input.maxLength=field==="description"?200:30;
        input.inputMode=field==="description"?"text":"decimal";
        input.dataset.line=String(index);input.dataset.field=field;
        input.value=line[field];
        input.setAttribute("aria-label",field.replace("_"," ")+" for item "+(index+1));
        td.append(input);tr.append(td);
      }
      const td=document.createElement("td"),button=document.createElement("button");
      button.type="button";button.className="btn";button.textContent="Remove";
      button.disabled=invoiceLines.length<=1;
      button.setAttribute("aria-label","Remove invoice item "+(index+1));
      button.onclick=()=>{
        invoiceLines.splice(index,1);renderInvoiceLines();
        invoiceResult=null;el("ssTotals").textContent="Invoice changed. Recalculate totals.";
      };
      td.append(button);tr.append(td);list.append(tr);
    });
    el("ssAddLine").disabled=invoiceLines.length>=40;
  }
  el("ssInvoiceLines").oninput=e=>{
    const input=e.target.closest("input[data-line][data-field]");
    if(!input)return;
    invoiceLines[Number(input.dataset.line)][input.dataset.field]=input.value;
    invoiceResult=null;el("ssTotals").textContent="Invoice changed. Recalculate totals.";
  };
  el("ssAddLine").onclick=()=>{
    if(invoiceLines.length>=40)return;
    invoiceLines.push({description:"",quantity:"1",unit_price:"0.00"});
    renderInvoiceLines();
  };
  for(const id of Object.values(invoiceFields)){
    el(id).addEventListener("input",()=>{
      invoiceResult=null;el("ssTotals").textContent="Invoice changed. Recalculate totals.";
    });
  }
  el("ssPreview").onclick=async()=>{
    try{
      const result=await api("/api/spreadsheets/invoice/preview",getInvoice());
      invoiceResult=result;
      const totals=el("ssTotals");totals.replaceChildren();
      const heading=document.createElement("h3");heading.textContent="Draft "+result.invoice_number;
      totals.append(heading);
      for(const [label,value] of [["Subtotal",result.subtotal],["Tax",result.tax],["Total",result.total]]){
        const row=document.createElement("div");row.className="ss-total-row";
        const key=document.createElement("span");key.textContent=label;
        const amount=document.createElement("strong");amount.textContent=result.currency+" "+value;
        row.append(key,amount);totals.append(row);
      }
      status("Totals calculated using decimal arithmetic. Review tax and details before issue.");
    }catch(error){status("Invoice validation failed: "+error.message,true);}
  };
  el("ssInvoiceSave").onclick=async()=>{
    try{
      const result=await api("/api/spreadsheets/invoice/save",getInvoice());
      await refreshLibrary();status("Private invoice draft saved: "+result.path+" (not sent).");
    }catch(error){status("Invoice save failed: "+error.message,true);}
  };
  el("ssInvoiceLoad").onclick=async()=>{
    const path=el("ssSavedInvoices").value;
    if(!path){status("Choose a saved invoice.",true);return;}
    if(!window.confirm("Open this invoice draft? Current unsaved invoice edits will be lost."))return;
    try{
      const result=await api("/api/spreadsheets/invoice/load?path="+encodeURIComponent(path));
      updateInvoiceInputs(result.invoice);
      status("Invoice draft loaded. Nothing has been sent or marked paid.");
    }catch(error){status("Invoice load failed: "+error.message,true);}
  };
  el("ssInvoiceExport").onclick=async()=>{
    try{
      const result=await api("/api/spreadsheets/invoice/export",getInvoice());
      showDownload(result);
      status("Draft invoice XLSX ready. It has not been issued, sent or paid.");
    }catch(error){status("Invoice export failed: "+error.message,true);}
  };
  openBook(book);renderInvoiceLines();
  try{await refreshLibrary();}catch(error){status("Could not load workspace files: "+error.message,true);}
  return root;
}

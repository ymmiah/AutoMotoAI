/* Pure, offline v1 spreadsheet view model — no code execution, no formula evaluator. */
export const MAX_SHEETS=5, MAX_ROWS=100, MAX_COLS=16;
export function blankBook(){
  return {name:"Untitled workbook",calculation_mode:"formulas",sheets:[{name:"Sheet1",rows:[["Item","Value"],["",""]]}]};
}
export function coerceCell(raw){
  const text=String(raw??"");
  // Keep identifiers such as 00123 as text; '=' is always literal in V1.
  if(/^[-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(text)&&
     !/^[-]?0[0-9]/.test(text)&&text.length<=16){
    const number=Number(text);
    if(Number.isFinite(number)&&Math.abs(number)<=1e12)return number;
  }
  return text;
}
export function setGridCell(book,sheetIndex,rowIndex,colIndex,value){
  if(!Number.isInteger(sheetIndex)||sheetIndex<0||sheetIndex>=book.sheets.length||
     !Number.isInteger(rowIndex)||rowIndex<0||rowIndex>=MAX_ROWS||
     !Number.isInteger(colIndex)||colIndex<0||colIndex>=MAX_COLS)throw Error("Cell is outside the V1 workbook limits.");
  const rows=book.sheets[sheetIndex].rows;
  while(rows.length<=rowIndex)rows.push([]);
  while(rows[rowIndex].length<=colIndex)rows[rowIndex].push(null);
  rows[rowIndex][colIndex]=coerceCell(value);
  return book;
}
export function workbookPayload(book){
  if(!book||!Array.isArray(book.sheets)||book.sheets.length<1||book.sheets.length>MAX_SHEETS)
    throw Error("V1 supports one to five worksheets.");
  const name=String(book.name||"").trim();
  if(!name||name.length>100)throw Error("Give the workbook a name (up to 100 characters).");
  const seen=new Set();
  const sheets=book.sheets.map(sheet=>{
    const label=String(sheet.name||"").trim();
    if(!label||label.length>31||/[\[\]:*?/\\]/.test(label)||seen.has(label.toLowerCase()))
      throw Error("Worksheet names must be unique and valid for Excel.");
    seen.add(label.toLowerCase());
    if(!Array.isArray(sheet.rows)||sheet.rows.length>MAX_ROWS)throw Error("Maximum 100 rows per sheet.");
    const rows=sheet.rows.map(row=>{
      if(!Array.isArray(row)||row.length>MAX_COLS)throw Error("Maximum 16 columns per sheet.");
      return row.map(value=>{
        if(value==null||typeof value==="boolean")return value;
        if(typeof value==="number"&&Number.isFinite(value)&&Math.abs(value)<=1e12)return value;
        if(typeof value==="string"&&value.length<=2000)return value;
        throw Error("Cell values must be short text or finite numbers.");
      });
    });
    const metadata={};
    if(sheet.cell_styles!==undefined)metadata.cell_styles=sheet.cell_styles;
    if(sheet.freeze!==undefined)metadata.freeze=sheet.freeze;
    if(sheet.filter_enabled!==undefined)metadata.filter_enabled=sheet.filter_enabled;
    if(sheet.column_widths!==undefined)metadata.column_widths=sheet.column_widths;
    if(sheet.validations!==undefined)metadata.validations=sheet.validations;
    return {name:label,rows,...metadata};
  });
  const mode=book.calculation_mode;
  if(mode!==undefined&&mode!=="literal"&&mode!=="formulas")throw Error("Unknown formula mode.");
  return {...(mode===undefined?{}:{calculation_mode:mode}),name,sheets};
}
export function invoicePayload(form,lines){
  if(!Array.isArray(lines)||lines.length<1||lines.length>40)throw Error("Add between one and forty invoice items.");
  return {
    number:String(form.number||"").trim(),seller:String(form.seller||"").trim(),
    customer:String(form.customer||"").trim(),
    issue_date:String(form.issue_date||""),due_date:String(form.due_date||""),
    currency:String(form.currency||"GBP"),tax_rate:String(form.tax_rate??"0"),
    lines:lines.map(line=>({description:String(line.description||"").trim(),
      quantity:String(line.quantity||""),unit_price:String(line.unit_price||"")}))
  };
}


// V2 bounded undo/redo: snapshots include formula mode, sheet data and names.
// No data is sent or persisted when navigating history.
export function createWorkbookHistory(initial,limit=40){
  const clone=value=>JSON.parse(JSON.stringify(value));
  let present=clone(initial),past=[],future=[];
  const state=()=>({canUndo:past.length>0,canRedo:future.length>0,
    undoDepth:past.length,redoDepth:future.length});
  return {
    state,
    reset(next){present=clone(next);past=[];future=[];return clone(present);},
    record(next){
      if(JSON.stringify(present)===JSON.stringify(next))return state();
      past.push(present);
      if(past.length>limit)past.shift();
      present=clone(next);future=[];
      return state();
    },
    undo(){
      if(!past.length)return null;
      future.push(present);present=past.pop();return clone(present);
    },
    redo(){
      if(!future.length)return null;
      past.push(present);present=future.pop();return clone(present);
    }
  };
}

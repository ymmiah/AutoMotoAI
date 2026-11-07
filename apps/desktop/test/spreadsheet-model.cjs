// V1 offline spreadsheet and invoice view model. No formula or script execution.
const assert=require("node:assert/strict");
const {readFileSync}=require("node:fs");
const path=require("node:path");
(async()=>{
  const source=readFileSync(path.resolve(__dirname,
    "../../../automoto/web/static/spreadsheet-model.js"),"utf8");
  const model=await import("data:text/javascript;base64,"+Buffer.from(source).toString("base64"));
  const book=model.blankBook();
  assert.equal(book.sheets.length,1);
  model.setGridCell(book,0,2,0,"00123");
  model.setGridCell(book,0,2,1,"19.95");
  model.setGridCell(book,0,2,2,"=2+2");
  assert.equal(book.sheets[0].rows[2][0],"00123");
  assert.equal(book.sheets[0].rows[2][1],19.95);
  assert.equal(book.sheets[0].rows[2][2],"=2+2");
  assert.equal(model.coerceCell("1e3"),"1e3");
  assert.equal(model.coerceCell("@SUM(A1)"),"@SUM(A1)");
  assert.equal(model.workbookPayload(book).sheets[0].rows[2][2],"=2+2");
  assert.throws(()=>model.setGridCell(book,0,100,0,"nope"),/limits/);
  assert.throws(()=>model.workbookPayload({name:"A",sheets:[
    {name:"Sales",rows:[]},{name:"sales",rows:[]}]}),/unique/);
  assert.throws(()=>model.workbookPayload({name:"A",sheets:[
    {name:"A/B",rows:[]}]}),/valid/);
  const invoice=model.invoicePayload({
    number:"INV-1",seller:"Example Ltd",customer:"Customer",
    issue_date:"2026-11-07",due_date:"2026-11-30",currency:"GBP",tax_rate:"20"
  },[{description:"Item",quantity:"2",unit_price:"9.99"}]);
  assert.equal(invoice.lines[0].unit_price,"9.99");
  assert.equal(invoice.currency,"GBP");
  assert.throws(()=>model.invoicePayload({},[]),/forty/);
  const app=readFileSync(path.resolve(__dirname,
    "../../../automoto/web/static/spreadsheet-studio.js"),"utf8");
  assert.match(app,/invoice\/preview/);
  assert.match(app,/spreadsheets\/export/);
  assert.doesNotMatch(app,/eval\s*\(/);
  assert.match(app,/originals remain unchanged/i);
  console.log("Spreadsheet v1 grid, literal formulas, invoice draft and app wiring passed.");
})().catch(err=>{console.error(err);process.exitCode=1;});

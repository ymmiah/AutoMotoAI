// V3 data-preserving sorting, filtering, formatting and column-rule tests.
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");

(async()=>{
  const file=path.resolve(__dirname,"../../../automoto/web/static/spreadsheet-editing.js");
  const editing=await import("data:text/javascript;base64,"+
    Buffer.from(fs.readFileSync(file,"utf8")).toString("base64"));

  const sheet={name:"Operations",rows:[
    ["Name","Amount"],["Alice",50],["Bob",10],["Charlie",30]
  ],cell_styles:{A2:{...editing.STYLE_DEFAULT,bold:true},B3:{...editing.STYLE_DEFAULT,italic:true}}};
  const original=JSON.stringify(sheet.rows);
  assert.deepEqual(editing.filterIndices(sheet,0,"ali"),[0,1]);
  assert.deepEqual(editing.filterIndices(sheet,1,"0"),[0,1,2,3]);
  assert.equal(JSON.stringify(sheet.rows),original,"view filtering must never mutate workbook data");
  const applied=editing.applyCellStyle(sheet,"B2",{bold:true,fill:"#DCE8F2",number_format:"gbp"});
  assert.equal(applied.bold,true);
  assert.equal(applied.number_format,"gbp");
  assert.equal(editing.styleAt(sheet,"B2").fill,"#DCE8F2");
  assert.throws(()=>editing.applyCellStyle(sheet,"Q1",{bold:true}),/Outside/);
  assert.throws(()=>editing.applyCellStyle(sheet,"A2",{fill:"javascript:bad"}),/Invalid/);
  assert.equal(editing.applyCellStyle(sheet,"A100",{italic:true}).italic,true);

  const rule=editing.setColumnRule(sheet,{
    column:"B",kind:"whole",min_value:"0",max_value:"100",options:""});
  assert.equal(rule.kind,"whole");
  assert.equal(editing.validateEntry(sheet,1,1,25),null);
  assert.match(editing.validateEntry(sheet,1,1,25.5),/numeric validation/);
  assert.match(editing.validateEntry(sheet,2,1,"=SUM(1,1)"),/Formulas cannot/);
  const list=editing.setColumnRule(sheet,{
    column:"A",kind:"list",options:"Alice,Bob,Charlie"});
  assert.deepEqual(list.options,["Alice","Bob","Charlie"]);
  assert.equal(editing.validateEntry(sheet,2,0,"Bob"),null);
  assert.match(editing.validateEntry(sheet,2,0,"Nobody"),/allowed value/);
  assert.throws(()=>editing.setColumnRule(sheet,{
    column:"A",kind:"list",options:"OK,=WEBSERVICE(1)"}),/list choices/);

  editing.sortSheetRows(sheet,1,false);
  assert.deepEqual(sheet.rows[0],["Name","Amount"],"header must remain in place");
  assert.deepEqual(sheet.rows.slice(1).map(row=>row[0]),["Bob","Charlie","Alice"]);
  assert.equal(sheet.cell_styles.A4.bold,true,"Alice's formatting must move with its row");
  assert.equal(sheet.cell_styles.B2.italic,true,"Bob's formatting must move with its row");
  assert.equal(sheet.cell_styles.B4.number_format,"gbp","styled amount moves with Alice");
  editing.sortSheetRows(sheet,1,true);
  assert.deepEqual(sheet.rows.slice(1).map(row=>row[0]),["Alice","Charlie","Bob"]);

  const unsafe={rows:[["Item","Price"],["a",4],["b","=B2*2"]]};
  const before=JSON.stringify(unsafe);
  assert.throws(()=>editing.sortSheetRows(unsafe,1),/formulas is disabled/);
  assert.equal(JSON.stringify(unsafe),before,"unsafe sort must not modify formula references");
  console.log("Spreadsheet v3 styles, row-safe sorting, non-destructive filters and validation passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});

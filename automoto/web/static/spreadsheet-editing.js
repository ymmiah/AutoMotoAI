/* V3 pure spreadsheet editing helpers. No eval, macros or network services. */
export const STYLE_DEFAULT={
  bold:false,italic:false,align:"left",fill:"#FFFFFF",color:"#1E293B",number_format:"general"
};
export const NUMBER_FORMATS=["general","number","integer","gbp","usd","eur","percent"];

export function styleAt(sheet,address){
  return {...STYLE_DEFAULT,...(sheet.cell_styles?.[address]||{})};
}
export function applyCellStyle(sheet,address,patch){
  if(!/^[A-P](?:100|[1-9][0-9]?)$/.test(address))throw Error("Outside the editable grid.");
  const merged={...styleAt(sheet,address),...patch};
  if(!NUMBER_FORMATS.includes(merged.number_format)||
     !["left","center","right"].includes(merged.align)||
     !/^#[\da-f]{6}$/i.test(merged.fill)||!/^#[\da-f]{6}$/i.test(merged.color)||
     typeof merged.bold!=="boolean"||typeof merged.italic!=="boolean")
    throw Error("Invalid cell style.");
  const styles={...(sheet.cell_styles||{})};
  styles[address]=merged;
  if(Object.keys(styles).length>500)throw Error("Maximum 500 styled cells.");
  sheet.cell_styles=styles;
  return merged;
}
export function setColumnRule(sheet,rule){
  const column=String(rule?.column||"");
  if(!/^[A-P]$/.test(column))throw Error("Choose a column A–P.");
  if(!["list","whole","decimal"].includes(rule.kind))throw Error("Unsupported validation rule.");
  const result={column,kind:rule.kind,options:[],min_value:null,max_value:null};
  if(rule.kind==="list"){
    const options=String(rule.options||"").split(",").map(x=>x.trim()).filter(Boolean);
    if(!options.length||options.length>10||new Set(options).size!==options.length||
       options.some(x=>x.length>40||/[=\r\n"]/.test(x))||options.join(",").length>240)
      throw Error("Enter 1–10 unique, short list choices without formulas.");
    result.options=options;
  }else{
    const min=Number(rule.min_value),max=Number(rule.max_value);
    if(!Number.isFinite(min)||!Number.isFinite(max)||min>max||
       Math.abs(min)>1e9||Math.abs(max)>1e9||
       (rule.kind==="whole"&&(!Number.isInteger(min)||!Number.isInteger(max))))
      throw Error("Enter valid ordered numeric bounds.");
    result.min_value=min;result.max_value=max;
  }
  sheet.validations=[...(sheet.validations||[]).filter(x=>x.column!==column),result];
  return result;
}
export function validateEntry(sheet,rowIndex,colIndex,value){
  if(rowIndex===0||value==null||value==="")return null;
  const letter=String.fromCharCode(65+colIndex);
  const rule=(sheet.validations||[]).find(x=>x.column===letter);
  if(!rule)return null;
  if(typeof value==="string"&&value.startsWith("="))
    return "Formulas cannot be entered in validated columns.";
  if(rule.kind==="list"){
    return rule.options.includes(String(value))?null:
      "Choose an allowed value for column "+letter+".";
  }
  const num=typeof value==="number"?value:Number(value);
  if(typeof value==="boolean"||!Number.isFinite(num)||(rule.kind==="whole"&&!Number.isInteger(num))||
     num<rule.min_value||num>rule.max_value)
    return "Value must satisfy the numeric validation rule for "+letter+".";
  return null;
}
export function filterIndices(sheet,column,search){
  const index=Number(column),query=String(search||"").toLocaleLowerCase();
  if(!Number.isInteger(index)||index<0||index>=16)throw Error("Choose column A–P.");
  const shown=[];
  for(let r=0;r<sheet.rows.length;r++){
    if(r===0||!query||String(sheet.rows[r]?.[index]??"").toLocaleLowerCase().includes(query))
      shown.push(r);
  }
  return shown; // non-destructive view only, no data mutation
}
export function sortSheetRows(sheet,column,descending=false){
  const index=Number(column);
  if(!Number.isInteger(index)||index<0||index>=16)throw Error("Choose column A–P.");
  if(sheet.rows.some(row=>row.some(v=>typeof v==="string"&&v.startsWith("="))))
    throw Error("Sorting worksheets with formulas is disabled in v3 to avoid changing cell references.");
  const data=sheet.rows.slice(1).map((row,i)=>({row,source:i+1}));
  function compare(a,b){
    const x=a.row[index],y=b.row[index];
    const blank=v=>v==null||v==="";
    if(blank(x)!==blank(y))return blank(x)?1:-1; // blanks last both directions
    let order=0;
    if(typeof x==="number"&&typeof y==="number")order=x-y;
    else order=String(x??"").localeCompare(String(y??""),undefined,{numeric:true,sensitivity:"base"});
    return (descending?-order:order)||a.source-b.source;
  }
  data.sort(compare);
  const sourceToTarget=new Map(data.map((item,i)=>[item.source,i+1]));
  const styles={};
  for(const [address,style] of Object.entries(sheet.cell_styles||{})){
    const found=/^([A-P])(100|[1-9][0-9]?)$/.exec(address);
    if(!found)continue;
    const original=Number(found[2])-1;
    const moved=original===0?0:(sourceToTarget.get(original)??original);
    styles[found[1]+String(moved+1)]=style;
  }
  sheet.rows=[sheet.rows[0]||[],...data.map(entry=>entry.row)];
  if(sheet.cell_styles)sheet.cell_styles=styles;
  return sheet;
}

/* Document Assistant v4: source-owned reference library and citation insertion.
   References never originate from models. No cross-origin resolver calls. */
export const DEFAULT_PUBLICATION=Object.freeze({
  reference_style:"harvard",author:"",institution:"",document_date:"",
  header:"",footer:"",cover_page:false,contents_page:false,template:"",references:[]
});
const IDS=new Set(["academic-report","business-proposal","meeting-minutes","formal-letter"]);
const ID=/^[a-z][a-z0-9_-]{0,31}$/;
export function publicationOptions(options){
  const src=options&&typeof options==="object"?options:{};
  const result={...DEFAULT_PUBLICATION};
  for(const key of Object.keys(result)){
    if(key==="references"){
      result.references=Array.isArray(src.references)?src.references.map(r=>({...r})):[];
    }else if(Object.hasOwn(src,key))result[key]=src[key];
  }
  if(!["harvard","ieee"].includes(result.reference_style))result.reference_style="harvard";
  if(!IDS.has(result.template))result.template="";
  return result;
}
export function citationMarker(ref){
  if(!ref||typeof ref.id!=="string"||!ID.test(ref.id))throw Error("Choose a valid source identifier.");
  return "[@"+ref.id+"]";
}
export function insertCitation(markdown,start,end,ref){
  if(typeof markdown!=="string"||!Number.isInteger(start)||!Number.isInteger(end)||
     start<0||start>end||end>markdown.length)throw Error("Invalid document selection.");
  const marker=citationMarker(ref);
  return {markdown:markdown.slice(0,start)+marker+markdown.slice(end),
    start:start+marker.length,end:start+marker.length};
}
export function addReference(publishing,record){
  const next=publicationOptions(publishing);
  if(next.references.length>=60)throw Error("Maximum 60 source references.");
  if(!record||!ID.test(record.id||""))throw Error("Use a lowercase source ID, starting with a letter.");
  if(!String(record.title||"").trim()||!String(record.authors||"").trim()||
     !/^(?:[12][0-9]{3}[a-z]?|n\.d\.)$/.test(record.year||""))
    throw Error("Enter a real author, publication year and title.");
  if(next.references.some(r=>r.id===record.id))
    throw Error("Reference ID already used.");
  if(record.url && (!/^https:\/\//.test(record.url)||/[\s@<>]/.test(record.url)))
    throw Error("Reference URL must be a valid HTTPS URL.");
  if(record.doi && !/^10\.\d{4,9}\/[-._;()/:A-Za-z0-9]+$/.test(record.doi))
    throw Error("DOI must have valid DOI syntax.");
  next.references.push({...record});
  return next;
}
export function removeReference(publishing,id){
  const next=publicationOptions(publishing);
  next.references=next.references.filter(ref=>ref.id!==id);
  return next;
}
export function templateById(templates,id){
  const item=templates.find(t=>t.id===id);
  if(!item||typeof item.source!=="string"||item.source.length>12000||
     !IDS.has(id))return null;
  return {name:item.name,markdown:item.source};
}

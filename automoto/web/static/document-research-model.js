/* v6 academic evidence: view-only source-pinned research result model.
   Never invent sources, authors, bibliography, page numbers or document facts. */
const SUPPORTED=/\.(docx|pdf|md|txt)$/i;
export const MAX_RESEARCH_SOURCES=5;
export function researchCandidates(documents){
  return (Array.isArray(documents)?documents:[]).filter(item=>
    item&&typeof item.path==="string"&&
    (item.path.endsWith(".document.json")||SUPPORTED.test(item.path)));
}
export function researchRequest(question,selected,pinned,mode="evidence"){
  const query=String(question||"").trim();
  if(query.length<3||query.length>320)throw Error("Enter a research question (3–320 characters).");
  if(!["evidence","outline","synthesis"].includes(mode))throw Error("Unsupported research mode.");
  if(!Array.isArray(selected)||selected.length<1||selected.length>MAX_RESEARCH_SOURCES||
     new Set(selected).size!==selected.length)throw Error("Select between one and five distinct documents.");
  const sources=selected.map(path=>{
    const entry=pinned[path];
    if(!entry||entry.path!==path||!/^[0-9a-f]{64}$/.test(entry.sha256||""))
      throw Error("The source identity was not verified. Reopen the document.");
    return {path,sha256:entry.sha256};
  });
  return {query,sources,mode};
}
const EVIDENCE_ID=/^S[1-5]-0[1-8]$/;
export function verifiedResearchView(response,request){
  if(!response||response.read_only!==true||response.applied!==false||
    response.question!==request.query||response.mode!==request.mode||
    response.source_count!==request.sources.length)
    throw Error("Research result does not match this request.");
  const paths=new Map(request.sources.map((src,i)=>[src.path,{...src,index:i+1}]));
  const evidence=[],byId=new Map();
  if(!Array.isArray(response.evidence)||response.evidence.length>8)
    throw Error("Invalid source evidence list.");
  for(const item of response.evidence){
    const src=paths.get(item.source);
    if(!src||item.sha256!==src.sha256||!EVIDENCE_ID.test(item.id||"")||
       !item.id.startsWith("S"+src.index+"-")||byId.has(item.id)||
       typeof item.quote!=="string"||item.quote.length<20||item.quote.length>450||
       !Number.isInteger(item.offset)||item.offset<0||
       (item.page!==null&&item.page!==undefined&&(!Number.isInteger(item.page)||item.page<1||item.page>200)))
      throw Error("Evidence source identity or quotation metadata is inconsistent.");
    const entry={id:item.id,source:item.source,sha256:src.sha256,
      quote:item.quote,section:String(item.section||""),
      page:item.page??null,offset:item.offset};
    evidence.push(entry);byId.set(entry.id,entry);
  }
  const synthesis=[];
  for(const claim of Array.isArray(response.synthesis)?response.synthesis:[]){
    if(typeof claim.claim!=="string"||claim.claim.length>430||
       !Array.isArray(claim.evidence_ids)||claim.evidence_ids.length<1||
       claim.evidence_ids.some(id=>!byId.has(id)))continue;
    synthesis.push({claim:claim.claim,evidence_ids:[...new Set(claim.evidence_ids)]});
  }
  return {evidence,synthesis,partialSources:Array.isArray(response.partial_sources)?
    response.partial_sources.filter(path=>paths.has(path)):[],
    outline:Array.isArray(response.outline)?response.outline.filter(item=>
      typeof item?.heading==="string"&&typeof item?.guidance==="string").slice(0,6):[],
    hasMatches:evidence.length>0,limitations:String(response.limitations||"")};
}
export function researchNotes(question,view){
  const lines=["# Research evidence notes","","> Evidence excerpts are not verified facts or bibliographic citations.",
    "", "## Research question","",question.trim(),"", "## Source excerpts",""];
  if(!view.evidence.length)lines.push("No matching quoted passages were found in the selected extracted text.","");
  for(const e of view.evidence){
    lines.push("### ["+e.id+"] "+e.source+(e.page?" — page "+e.page:""),"",
      "Section: "+e.section,"",
      "> "+e.quote.replace(/\n/g,"\n> "),"");
  }
  if(view.synthesis.length){
    lines.push("## Local AI interpretations — verify against source context","");
    for(const claim of view.synthesis)
      lines.push("- "+claim.claim+" ("+claim.evidence_ids.join(", ")+")");
    lines.push("");
  }
  if(view.outline.length){
    lines.push("## Suggested academic structure","");
    for(const part of view.outline)lines.push("### "+part.heading,"",part.guidance,"");
  }
  if(view.partialSources.length){
    lines.push("## Coverage warning","",
      "The following sources were not fully extracted: "+view.partialSources.join("; "),"");
  }
  lines.push("## Referencing reminder","",
    "Enter real author, publication year, title and other bibliographic details in Professional Publishing. Do not treat internal S1-01-style evidence IDs as Harvard or IEEE citations.");
  return lines.join("\n");
}

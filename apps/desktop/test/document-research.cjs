// v6: source-pinned research notes never invent bibliography or document metadata.
const assert=require("node:assert/strict");
const {readFileSync}=require("node:fs");
const path=require("node:path");
(async()=>{
 const src=readFileSync(path.resolve(__dirname,
   "../../../automoto/web/static/document-research-model.js"),"utf8");
 const mod=await import("data:text/javascript;base64,"+Buffer.from(src).toString("base64"));
 const paths=[
   {path:"uploads/report.pdf",name:"report.pdf",kind:"pdf"},
   {path:"artifacts/documents/my-report.document.json",name:"my report",kind:"draft"},
   {path:"uploads/photo.jpg",name:"photo.jpg",kind:"jpg"},
   {path:"uploads/notes.txt",name:"notes.txt",kind:"txt"}
 ];
 assert.deepEqual(mod.researchCandidates(paths).map(x=>x.path),
   [paths[0].path,paths[1].path,paths[3].path]);
 const digest="a".repeat(64);
 const selected=[paths[0].path,paths[1].path];
 const pinned=Object.fromEntries(selected.map(p=>[p,{path:p,sha256:digest}]));
 const request=mod.researchRequest("What is the research budget?",selected,pinned,"outline");
 assert.equal(request.sources.length,2);
 assert.equal(request.mode,"outline");
 assert.throws(()=>mod.researchRequest("??",selected,pinned),/question/);
 assert.throws(()=>mod.researchRequest("Research budget?",[...selected,...selected],pinned),/distinct/);
 assert.throws(()=>mod.researchRequest("Research budget?",[paths[2].path],pinned),/not verified/);
 const result={
   read_only:true,applied:false,question:request.query,mode:"outline",
   source_count:2,partial_sources:[paths[0].path],
   evidence:[
     {id:"S1-01",source:paths[0].path,sha256:digest,page:2,section:"Page 2",offset:120,
      quote:"The annual research budget was one hundred and twenty thousand pounds."},
     {id:"S2-01",source:paths[1].path,sha256:digest,page:null,section:"Editable draft",offset:18,
      quote:"The faculty also reported a different allocation from the same research fund."}
   ],
   synthesis:[{claim:"A summary grounded in both sources",evidence_ids:["S1-01","S2-01"]}],
   outline:[{heading:"Research question",guidance:"Use documented source limitations."}],
   limitations:"Do not invent bibliographic data."
 };
 const view=mod.verifiedResearchView(result,request);
 assert.equal(view.evidence.length,2);
 assert.equal(view.synthesis.length,1);
 assert.equal(view.evidence[0].page,2);
 const notes=mod.researchNotes(request.query,view);
 assert.match(notes,/\[S1-01\] uploads\/report.pdf — page 2/);
 assert.match(notes,/The annual research budget was/);
 assert.match(notes,/not verified facts or bibliographic citations/);
 assert.match(notes,/not fully extracted/);
 assert.ok(!notes.includes("Smith (2024)"));
 assert.throws(()=>mod.verifiedResearchView({...result,evidence:[
   {...result.evidence[0],sha256:"b".repeat(64)}]},request),/identity/);
 assert.throws(()=>mod.verifiedResearchView({...result,evidence:[
   {...result.evidence[0],id:"S2-01"}]},request),/identity/);
 assert.throws(()=>mod.verifiedResearchView({...result,read_only:false},request),/request/);
 const filtered=mod.verifiedResearchView({...result,synthesis:[
   {claim:"This is a made-up observation",evidence_ids:["FAKE"]}]},request);
 assert.equal(filtered.synthesis.length,0);
 console.log("Document Assistant v6 research model, evidence pinning and notes passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});

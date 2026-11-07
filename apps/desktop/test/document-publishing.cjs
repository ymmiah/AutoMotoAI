// v4 source-owned bibliography and template helpers (no network).
const assert=require("node:assert/strict");
const {readFileSync}=require("node:fs");
const path=require("node:path");
(async()=>{
  const text=readFileSync(path.resolve(__dirname,
    "../../../automoto/web/static/document-publishing.js"),"utf8");
  const m=await import("data:text/javascript;base64,"+Buffer.from(text).toString("base64"));
  const original=m.publicationOptions();
  assert.equal(original.reference_style,"harvard");
  assert.deepEqual(original.references,[]);
  const source={id:"smith2024",authors:"Smith, A.",year:"2024",
    title:"Verified user-entered report",type:"report",
    url:"https://example.invalid/research"};
  const added=m.addReference(original,source);
  assert.equal(added.references.length,1);
  assert.equal(original.references.length,0,"source library remains immutable");
  assert.equal(m.citationMarker(source),"[@smith2024]");
  const markdown="# Literature review\n\nThe evidence is relevant.";
  const insertion=m.insertCitation(markdown,markdown.length,markdown.length,source);
  assert.equal(insertion.markdown,markdown+"[@smith2024]");
  assert.equal(insertion.start,insertion.end);
  assert.throws(()=>m.addReference(added,source),/already used/);
  assert.throws(()=>m.addReference(original,{...source,url:"http://insecure"}),/HTTPS/);
  assert.throws(()=>m.addReference(original,{...source,year:"yesterday"}),/year/);
  const removed=m.removeReference(added,"smith2024");
  assert.equal(removed.references.length,0);
  assert.equal(added.references.length,1);
  const template=m.templateById([{id:"academic-report",name:"Academic report",
    source:"# Example\n\n[Replace placeholders]"}],"academic-report");
  assert.match(template.markdown,/placeholders/);
  assert.equal(m.templateById([], "unknown"),null);
  assert.equal(m.publicationOptions({reference_style:"ieee",unknown:"bad"}).unknown,undefined);
  console.log("Document Assistant v4 bibliography and author-owned citation assertions passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});

// Pure approval boundaries: tests run without any AI account or remote model.
const assert=require("node:assert/strict");
const {readFileSync}=require("node:fs");
const path=require("node:path");
(async()=>{
  const source=readFileSync(path.resolve(__dirname,
    "../../../automoto/web/static/document-ai-review.js"),"utf8");
  const {editableReviewRequest,applyReviewedProposal,supportedEvidence,REVIEW_LIMIT}=
    await import("data:text/javascript;base64,"+Buffer.from(source).toString("base64"));
  const markdown="# Report\n\nThis sentences has a error.\n\nFurther details are unchanged.";
  const i=markdown.indexOf("This sentences"),end=i+"This sentences has a error.".length;
  const req=editableReviewRequest("proofread",markdown,i,end);
  assert.equal(req.text,"This sentences has a error.");
  assert.deepEqual([req.start,req.end],[i,end]);
  const whole=editableReviewRequest("summary",markdown,0,0);
  assert.equal(whole.text,markdown);
  assert.equal(whole.selected,false);
  assert.throws(()=>editableReviewRequest("summarize",markdown,0,1),/Unknown/);
  assert.throws(()=>editableReviewRequest("summary","x".repeat(REVIEW_LIMIT+1),0,0),/12,000/);
  const response={mode:"proofread",proposal:"This sentence has an error.",
    changed:true,applied:false,requires_approval:true,selection:{start:i,end}};
  const before=markdown;
  const candidate=applyReviewedProposal(markdown,req,response);
  assert.match(candidate.markdown,/This sentence has an error\./);
  assert.match(candidate.markdown,/Further details are unchanged\./);
  assert.equal(markdown,before,"proposal must not mutate the source");
  assert.throws(()=>applyReviewedProposal(markdown+"extra",req,response),/changed/);
  assert.throws(()=>applyReviewedProposal(markdown,req,{...response,applied:true}),/approved/);
  assert.throws(()=>applyReviewedProposal(markdown,req,{...response,mode:"summary"}),/approved/);
  assert.throws(()=>applyReviewedProposal(markdown,req,{...response,selection:{start:0,end}}),/selection/);
  const quote="Further details are unchanged.";
  const summary={evidence:[
    {claim:"The document includes further details",quote,offset:markdown.indexOf(quote)},
    {claim:"Made-up evidence",quote:"Not in the document",offset:10},
  ]};
  assert.deepEqual(supportedEvidence(summary,markdown),[summary.evidence[0]]);
  console.log("Document Assistant v3 approval and evidence helper assertions passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});

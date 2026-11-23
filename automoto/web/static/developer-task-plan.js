/* Developer Studio V50: accessible, purely presentational task plan review.
   Planning never starts an agent. Execution requires a separate user click. */

const el=(tag,cls,text)=>{
  const node=document.createElement(tag);
  if(cls)node.className=cls;
  if(text!==undefined&&text!==null)node.textContent=String(text);
  return node;
};

export function isCodingRequest(value){
  const text=String(value||"").trim();
  if(!text||/^(?:please\s+)?(?:explain|describe|what|where|why|how|tell me|show me|summarise|summarize|read|list)\b/i.test(text))return false;
  return /\b(add|build|create|implement|fix|repair|debug|change|modify|update|improve|refactor|rewrite|remove|delete|replace|make|develop|integrate|secure)\b/i.test(text);
}

/**
 * The checkboxes mean "I reviewed this proposed step"; they never mark a real
 * agent action or test as completed. Verified source paths are displayed as
 * locally readable evidence, not executable instructions.
 */
export function taskPlanCard(plan,{onStart,onEdit,onCancel,onOpenSource}={}){
  const root=el("section","dsx-plan");
  root.setAttribute("aria-label","Review suggested coding task plan");
  const top=el("div","dsx-plan-head");
  const heading=el("div");
  heading.append(el("strong",null,"Review your plan"),el("p",null,"A suggested sequence. No files have changed and no commands have run."));
  top.append(heading,el("span","dsx-plan-count",String(plan.steps?.length||0)+" steps"));
  root.append(top);
  const request=el("p","dsx-plan-request",plan.request||"");
  root.append(request);

  const list=el("ol","dsx-plan-steps");
  const steps=Array.isArray(plan.steps)?plan.steps.slice(0,6):[];
  let reviewed=0;
  const counter=el("p","dsx-plan-reviewed");
  const refresh=()=>{counter.textContent=reviewed+" of "+steps.length+" steps reviewed (not completed)";};
  steps.forEach((step,i)=>{
    const item=el("li","dsx-plan-step");
    const label=el("label","dsx-plan-step-title");
    const checkbox=el("input");
    checkbox.type="checkbox";
    checkbox.setAttribute("aria-label","Mark step "+(i+1)+" as reviewed: "+String(step.title||""));
    checkbox.addEventListener("change",()=>{reviewed+=checkbox.checked?1:-1;refresh();});
    label.append(checkbox,el("strong",null,String(step.title||"Review step")));
    item.append(label,el("p",null,step.detail||""));
    const check=el("p","dsx-plan-check","Check: "+String(step.acceptance_check||"Evidence required."));
    item.append(check);
    list.append(item);
  });
  root.append(list,counter);
  refresh();

  const sources=Array.isArray(plan.evidence)?plan.evidence: [];
  const evidence=el("div","dsx-plan-evidence");
  evidence.append(el("strong",null,sources.length?"Matching project source":"No matching source found"));
  if(sources.length){
    const refs=el("div","dsx-plan-refs");
    for(const item of sources.slice(0,3)){
      const button=el("button","dsx-plan-ref",item.path+":"+item.line_start+"–"+item.line_end);
      button.type="button";
      button.title="Open the matching source file";
      button.addEventListener("click",()=>onOpenSource?.(item.path));
      refs.append(button);
    }
    evidence.append(refs,el("p",null,"These paths were found in the project. The proposed steps still need review."));
  }else{
    evidence.append(el("p",null,"The plan is a starting suggestion, not evidence that a feature already exists."));
  }
  if(plan.scan_truncated)evidence.append(el("p","dsx-plan-warning","Search was limited. Other relevant files may exist."));
  root.append(evidence);

  const controls=el("div","dsx-plan-actions");
  const start=el("button","btn sm primary","Review & start task");
  start.type="button";
  const edit=el("button","btn sm","Edit request");
  edit.type="button";
  const cancel=el("button","btn sm","Dismiss");
  cancel.type="button";
  const note=el("p","dsx-plan-note","Starting still requires confirmation. Each risky file change, command or share asks separately.");
  start.addEventListener("click",async()=>{
    if(start.disabled)return;
    start.disabled=true;
    try{
      const started=await onStart?.(plan);
      if(started){
        start.textContent="Task started";
        edit.disabled=true;cancel.disabled=true;
        note.textContent="The assistant is working. Changes and commands still require your approval.";
      }else start.disabled=false;
    }catch(err){
      start.disabled=false;
      note.textContent="Could not start: "+String(err?.message||"Unknown error");
    }
  });
  edit.addEventListener("click",()=>onEdit?.(plan.request));
  cancel.addEventListener("click",()=>{
    root.replaceChildren(el("p","dsx-plan-dismissed","Plan dismissed. Nothing was executed."));
    onCancel?.();
  });
  controls.append(start,edit,cancel);
  root.append(controls,note);
  return root;
}

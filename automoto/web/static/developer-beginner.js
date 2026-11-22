/* Beginner-friendly faces for Run my app and Checkpoints (Git): guided steps, with a small
   health ring beside the test result. They sit on top of the same approval-gated runner and
   project-confined Git; the original expert panels stay available under "Advanced details". */
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const btn=(text,cls,fn)=>{const b=el("button","btn "+(cls||""),text);b.type="button";if(fn)b.onclick=fn;return b;};
const CHANGE={modified:"edited",added:"new",untracked:"new",deleted:"removed",renamed:"renamed",copied:"copied","type changed":"edited",conflict:"needs a decision"};

export function friendlyName(raw){
  let s=String(raw||"").split("::").pop().split(/[/\\]/).pop();
  s=s.replace(/^(test_|Test)/,"").replace(/\.(py|js|ts|tsx)$/,"").replace(/[_-]+/g," ").replace(/([a-z])([A-Z])/g,"$1 $2");
  return s.trim().replace(/^./,c=>c.toUpperCase())||String(raw);
}
function testStory(run){
  if(!run)return null;
  const s=run.summary||{passed:0,failed:0,skipped:0,total:0,failures:[]};
  const checked=(s.passed||0)+(s.failed||0);
  if(run.live)return {tone:"busy",title:"Checking your code…",text:"This usually takes a few seconds."};
  if(run.status==="stopped")return {tone:"idle",title:"Check stopped",text:"Nothing was changed."};
  if(!s.recognised&&!checked)return {tone:run.status==="passed"?"ok":"bad",title:run.status==="passed"?"All checks passed":"The checks didn't finish",text:"Open Advanced details to read the full output."};
  if(!s.failed)return {tone:"ok",title:"All "+checked+" checks passed",text:s.skipped?s.skipped+" skipped for later.":"Everything you tested works."};
  return {tone:"bad",title:s.passed+" of "+checked+" checks passed",text:"Here's what broke:",broken:(s.failures||[]).map(friendlyName)};
}
function wrapAdvanced(root,section){
  const adv=el("details","dsb-adv");adv.append(el("summary",null,"Advanced details"));
  section.before(adv);adv.append(section);return adv;
}
function previewFrame(){
  const wrap=el("div","dsb-preview");wrap.hidden=true;
  const bar=el("div","dsb-preview-bar");const lock=el("span","dsr-lock","Only on this computer");const open=el("a","dsb-link","Open in browser ↗");open.target="_blank";open.rel="noopener noreferrer";
  bar.append(lock,el("span","dsx-gap"),open);
  const frame=el("iframe","dsb-frame");frame.title="Live preview of your app";
  frame.setAttribute("sandbox","allow-scripts allow-forms allow-same-origin allow-popups allow-modals");frame.setAttribute("referrerpolicy","no-referrer");
  wrap.append(bar,frame);let url=null;
  return {node:wrap,set(next){wrap.hidden=!next;if(next&&next!==url){url=next;frame.src=next;open.href=next;}if(!next&&url){url=null;frame.removeAttribute("src");}}};
}
function changedList(files,limit=4,onPick){
  const list=el("ul","dsb-files");
  const shown=files.slice(0,limit);
  for(const f of shown){
    const li=el("li");const name=el(onPick?"button":"span","dsb-file",f.path);
    if(onPick){name.type="button";name.onclick=()=>onPick(f);}
    li.append(name,el("span","dsb-tag",f.secret_like?"private, not saved":CHANGE[f.conflict?"conflict":(f.worktree||f.index)]||"edited"));
    list.append(li);
  }
  if(files.length>limit)list.append(el("li","dsb-more","and "+(files.length-limit)+" more"));
  return list;
}
function suggestMessage(files){
  const names=files.map(f=>f.path.split("/").pop());
  if(!names.length)return "";
  return "Update "+(names.length<=2?names.join(" and "):names.slice(0,2).join(", ")+" and "+(names.length-2)+" more");
}
function identityInputs(){
  const box=el("div","dsb-ident");
  const name=el("input","input");name.placeholder="Your name";name.setAttribute("aria-label","Your name, shown on checkpoints");name.maxLength=120;
  const email=el("input","input");email.placeholder="you@example.com";email.setAttribute("aria-label","Your email, shown on checkpoints");email.maxLength=200;
  box.append(el("p","dsb-hint","First time? Add your name so checkpoints show who made them."),name,email);
  return {node:box,get:()=>({name:name.value.trim(),email:email.value.trim()})};
}
async function confirmSave(git,files,message,ident){
  const n=files.length;
  if(!window.confirm("Save a checkpoint of "+n+" file"+(n===1?"":"s")+"?\n\n“"+message+"”\n\nIt stays on this computer. Nothing is uploaded."))return null;
  return git.saveCheckpoint(message,ident);
}
function gitFacts(g){
  const s=g.state||{},files=s.files||[];
  return {s,files,conflicts:files.filter(f=>f.conflict),saveable:files.filter(f=>!f.conflict&&!f.secret_like&&(f.unstaged||f.staged)),
    needIdent:s.identity&&!s.identity.configured,idea:s.branch==="main"||s.branch==="master"||!s.branch?"Main version":s.branch.replace(/^(feature|idea)\//,"")};
}


// ------------------------------------------------------------------ Guided steps
function step(n,title,state,body){
  const s=el("li","dsb-step s-"+state);const num=el("span","dsb-num",state==="done"?"✓":String(n));
  const main=el("div","dsb-step-main");main.append(el("b",null,title));if(body)main.append(body);
  s.append(num,main);return s;
}
function runGuided(box,runner){
  const list=el("ol","dsb-steps");const preview=previewFrame();
  const mk=(n,title)=>{const li=el("li","dsb-step");const num=el("span","dsb-num",String(n));const main=el("div","dsb-step-main");const body=el("div");main.append(el("b",null,title),body);li.append(num,main);list.append(li);return {li,num,body,n};};
  const s1=mk(1,"Start your app"),s2=mk(2,"See it live"),s3=mk(3,"Check it works");
  const hint2=el("p","dsb-hint");s2.body.append(hint2,preview.node);
  const set=(s,state)=>{s.li.className="dsb-step s-"+state;s.num.textContent=state==="done"?"✓":String(s.n);};
  box.append(el("h3","dsb-h","Try your app in 3 steps"),list);
  return ()=>{
    const st=runner.getState(),app=st.app,app_r=runner.pick("app"),test_r=runner.pick("test");
    const running=!!(app?.live&&app.preview_url);
    s1.body.replaceChildren();
    if(!app_r)s1.body.append(el("p","dsb-hint","No start command found. Ask the assistant to set one up."));
    else if(app?.live)s1.body.append(el("p","dsb-hint",running?"Running on this computer only.":"Starting…"),btn("Stop","",()=>runner.stop("app")));
    else{s1.body.append(el("p","dsb-hint","We'll ask before anything runs."));const b=btn("▶ Start my app","primary",()=>runner.start(app_r));b.disabled=!st.trusted;s1.body.append(b);}
    set(s1,running?"done":"now");
    hint2.textContent=running?"Click around. Reload to see new changes.":"Your app will appear here.";
    preview.set(running?app.preview_url:null);
    set(s2,running?"now":"todo");
    s3.body.replaceChildren();const ts=testStory(st.test);
    if(!test_r){s3.body.append(el("p","dsb-hint","No checks found yet. Ask the assistant to add some."));}
    else{
      s3.body.append(el("p","dsb-hint","Runs your project's checks. Nothing is changed."));
      const b=btn(st.test?.live?"Checking…":st.test?"Check again":"Check it works",running||st.test?"primary":"",()=>runner.start(test_r));
      b.classList.add("dsb-check-btn");b.disabled=!st.trusted||!!st.test?.live;
      s3.body.append(ts?checkCard(st.test,ts,b):b);
    }
    set(s3,ts&&ts.tone==="ok"?"done":st.test?"now":"todo");
  };
}
function gitGuided(box,git){
  const list=el("ol","dsb-steps");const msg=el("input","input dsb-msg");msg.placeholder="e.g. Fixed the counter";msg.maxLength=200;msg.setAttribute("aria-label","Describe your change");
  const ident=identityInputs();const viewer=el("div","dsb-mini-diff");const conflict=el("div","dsb-conflict");
  let touched=false;msg.addEventListener("input",()=>{touched=true;});
  box.append(el("h3","dsb-h","Save a checkpoint in 3 steps"),list);
  return ()=>{
    const g=git.getState();const f=gitFacts(g);list.replaceChildren();
    if(!f.s?.repository){
      const b=el("div");b.append(el("p","dsb-hint","Checkpoints let you save versions and go back if something breaks."));
      if(f.s&&f.s.repository===false){const x=btn("Turn on checkpoints","primary",()=>{if(window.confirm("Turn on checkpoints for this project? Nothing is uploaded."))git.init();});x.disabled=!g.trusted;b.append(x);}
      list.append(step(1,"Turn on checkpoints","now",b));return;
    }
    let n=1;
    if(f.conflicts.length){
      const b=el("div");b.append(el("p","dsb-hint","Two versions changed the same lines. Choose what to keep."),conflict);
      if(conflict.dataset.path!==f.conflicts[0].path){conflict.dataset.path=f.conflicts[0].path;git.showConflict(f.conflicts[0].path,conflict,true);}
      list.append(step(n++,"Fix the disagreement","now",b));
      list.append(step(n++,"Describe it","todo",null));list.append(step(n++,"Save checkpoint","todo",null));return;
    }
    conflict.replaceChildren();delete conflict.dataset.path;
    const has=f.saveable.length;
    const b1=el("div");
    if(has){b1.append(el("p","dsb-hint",has+" file"+(has===1?"":"s")+" changed on "+f.idea+". Tap one to see what's different."),changedList(f.saveable,5,async file=>{viewer.replaceChildren(el("p","dsb-hint","Loading…"));try{viewer.replaceChildren(miniDiff(await git.fetchDiff(file.path,file.staged&&!file.unstaged)));}catch(e){viewer.replaceChildren(el("p","dsb-hint",e.message));}}),viewer);}
    else b1.append(el("p","dsb-hint","Nothing has changed since your last checkpoint."));
    list.append(step(n++,"See what changed",has?"done":"now",b1));
    const b2=el("div");if(!touched)msg.value=suggestMessage(f.saveable);b2.append(msg);if(f.needIdent)b2.append(ident.node);
    list.append(step(n++,"Describe it",has&&msg.value.trim()?"done":has?"now":"todo",has?b2:null));
    const b3=el("div");const save=btn("Save checkpoint","primary",()=>confirmSave(git,f.saveable,msg.value.trim(),ident.get()).then(d=>{if(d){touched=false;msg.value="";viewer.replaceChildren();}}));
    save.disabled=!has||!g.trusted||g.busy||msg.value.trim().length<2;b3.append(el("p","dsb-hint","Saved on this computer only."),save);
    list.append(step(n++,"Save checkpoint",has?"now":"todo",has?b3:null));
    if((f.s.recent||[]).length){const last=f.s.recent[0];box.querySelector(".dsb-last")?.remove();const p=el("p","dsb-hint dsb-last","Last checkpoint: “"+last.subject+"” · "+last.when);list.after(p);}
  };
}
function miniDiff(text){
  const pre=el("pre","dsx-diff");
  for(const line of String(text||"").split("\n")){
    if(/^(diff --git|index |--- |\+\+\+ |@@)/.test(line))continue;
    if(!line.startsWith("+")&&!line.startsWith("-"))continue;
    pre.append(el("span",line.startsWith("+")?"a":"d",(line.startsWith("+")?"Added:   ":"Removed: ")+line.slice(1)+"\n"));
  }
  if(!pre.childNodes.length)pre.append(el("span",null,"No text changes."));
  return pre;
}
export function ring(passed,total,tone,fallback){
  const r=el("div","dsb-ring sm t-"+tone);r.setAttribute("role","img");
  r.setAttribute("aria-label",total?passed+" of "+total+" checks passed":tone==="busy"?"Checking":tone==="ok"?"Checks passed":tone==="idle"?"Check stopped":"Checks did not pass");
  r.style.setProperty("--p",(total?Math.round(100*passed/total):tone==="ok"?100:0)+"%");
  r.append(el("b",null,total?passed+"/"+total:fallback));return r;
}
// The test result, the small health ring and the Check again button sit together in one
// card, so they keep the same size, spacing and alignment on phone, tablet and desktop.
function checkCard(run,ts,button){
  const sum=run?.summary||{};const passed=sum.passed||0,total=passed+(sum.failed||0);
  const card=el("div","dsb-check t-"+ts.tone);
  card.append(ring(run?.live?null:passed,run?.live?0:total,ts.tone,ts.tone==="ok"?"✓":ts.tone==="bad"?"!":ts.tone==="busy"?"…":"–"));
  const text=el("div","dsb-check-text");text.append(el("b",null,ts.title),el("p",null,ts.text));
  if(ts.broken?.length){const ul=el("ul","dsb-broken");for(const x of ts.broken.slice(0,6))ul.append(el("li",null,x));text.append(ul);}
  card.append(text,button);return card;
}

export function mountBeginnerPanels({host,runner,git}){
  const runRoot=host.querySelector("#dsRunRoot"),gitRoot=host.querySelector("#dsGitRoot");
  const make=(rootNode,sel,builder,src)=>{
    const section=rootNode?.querySelector(sel);if(!section)return;
    const box=el("section","dsb");box.setAttribute("aria-label",sel===".dsr"?"Run your app":"Checkpoints");
    rootNode.prepend(box);wrapAdvanced(rootNode,section);
    const update=builder(box,src);update();src.onChange(update);
  };
  make(runRoot,".dsr",runGuided,runner);
  make(gitRoot,".dsg",gitGuided,git);
}

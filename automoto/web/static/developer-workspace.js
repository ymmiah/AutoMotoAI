/* Edit, test & share: the AutoMoto chat first, with a live panel beside it (a slide-up sheet on phones).
   It reuses what is already there: the Developer chat and its coding assistant (the same assistant
   task, review checkpoint and Keep / Undo), the editor, the approval-gated runner, Checkpoints, Share,
   Ask for a review and the Project map. Quick actions such as "Test my app" or "Share to GitHub" are
   handled here, never by the model: each one shows an inline confirm card and only the user's click
   runs, applies or sends anything. Model output and website text are untrusted and only ever go on the
   page as text. Nothing is stored in the browser. */
import {ring} from "./developer-beginner.js";
import {renderFallback} from "./developer-share.js";
import {hydrateIcons} from "./icons.js";

const BRAND=document.querySelector('meta[name="automoto-brand-short"]')?.content||"AutoMoto";
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const btn=(text,cls,fn)=>{const b=el("button","btn "+(cls||""),text);b.type="button";if(fn)b.onclick=fn;return b;};
const NAMES={github:"GitHub",gitlab:"GitLab"};
const safeUrl=u=>/^https:\/\/[^\s"<>]+$/.test(String(u||""))?u:null;
const plural=(n,w)=>n+" "+w+(n===1?"":"s");
function extLink(url,label){
  const ok=safeUrl(url);const a=el("a","btn sm",label+" ↗");
  if(ok){a.href=ok;a.target="_blank";a.rel="noopener noreferrer";}else a.setAttribute("aria-disabled","true");
  return a;
}
export const CHIPS=[["explain","Explain my project"],["fix","Fix the error"],["test","Test my app"],["share","Share to GitHub"],["review","Ask for a review"],["map","Map my project"]];
// What the two AI chips ask the assistant. Only the request goes to the model; the assistant reads
// files itself through its own tools, and every change still needs the user's Apply.
export const AI_PROMPTS={
  explain:"Use developer_sources to find relevant evidence in this project first. Explain what the project does and how to run it in plain words. Cite each verified project claim with an exact path and line range (path:Lx-Ly). Do not invent citations or instructions when project evidence is missing. Do not change any files.",
  fix:"Find the error in this project (from the tests or the error output), fix it with the smallest change, and explain the fix in one or two plain sentences."
};
const INTENTS=[
  ["test",/^(please\s+)?((test|check)\s+(my|the|this)\s+(app|project|code)|run\s+(my|the)\s+tests?)\b/i],
  ["app",/^(please\s+)?(run|start|open)\s+(my|the)\s+app\b/i],
  ["share",/^(please\s+)?(share|push|upload|send)\b.*\b(github|gitlab|online)\b|^(please\s+)?share(\s+it|\s+my\s+(work|changes))?[.!]?$/i],
  ["review",/^(please\s+)?(ask\s+for\s+a\s+review|(open|make|create)\s+(a\s+)?(pull|merge)\s+request)/i],
  ["checks",/^(please\s+)?(show|see|check)\s+(the\s+|my\s+)?checks\b/i],
  ["map",/^(please\s+)?map\s+(my|the|this)\s+project\b/i],
  ["checkpoint",/^(please\s+)?save\s+(a\s+)?checkpoint\b/i]
];
/** A quick action the workspace handles itself, or null when the request goes to the assistant. */
export function intentOf(text){const t=String(text||"").trim();for(const [k,re] of INTENTS)if(re.test(t))return k;return null;}

// ---------------------------------------------------------------- diff preview
function lineDiff(a,b){
  const A=a.split("\n"),B=b.split("\n"),n=A.length,m=B.length;
  if(n*m>250000)return [...A.map(x=>["d",x]),...B.map(x=>["a",x])];
  const dp=Array.from({length:n+1},()=>new Uint32Array(m+1));
  for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)dp[i][j]=A[i]===B[j]?dp[i+1][j+1]+1:Math.max(dp[i+1][j],dp[i][j+1]);
  const out=[];let i=0,j=0;
  while(i<n&&j<m){if(A[i]===B[j]){out.push([" ",A[i]]);i++;j++;}else if(dp[i+1][j]>=dp[i][j+1])out.push(["d",A[i++]]);else out.push(["a",B[j++]]);}
  while(i<n)out.push(["d",A[i++]]);while(j<m)out.push(["a",B[j++]]);
  return out;
}
function around(rows,ctx=3){
  const keep=rows.map(()=>false);
  rows.forEach((r,k)=>{if(r[0]!==" ")for(let d=-ctx;d<=ctx;d++)if(k+d>=0&&k+d<rows.length)keep[k+d]=true;});
  const out=[];let gap=false;
  rows.forEach((r,k)=>{if(keep[k]){out.push(r);gap=false;}else if(!gap){out.push(["h","…"]);gap=true;}});
  return out;
}
function diffPre(rows){
  const pre=el("pre","dsx-diff dsw-diff");
  for(const [t,l] of rows.slice(0,400))pre.append(el("span",t==="a"?"a":t==="d"?"d":t==="h"?"h":"",(t==="a"?"+ ":t==="d"?"- ":t==="h"?"":"  ")+l+"\n"));
  if(rows.length>400)pre.append(el("span","h","… "+(rows.length-400)+" more lines\n"));
  return pre;
}
function relPath(path,project){
  let p=String(path||"").replace(/\\/g,"/");const root=String(project||"").replace(/\\/g,"/").replace(/\/+$/,"");
  if(root&&p.toLowerCase().startsWith(root.toLowerCase()+"/"))p=p.slice(root.length+1);
  return p.replace(/^\.\//,"");
}
/** The inline confirm card for a step the assistant wants to take: a file change shows its diff with
    Apply / Skip, a command shows the exact command with Run once / Don't run. Nothing happens until
    the user presses a button; decide(allow) tells the waiting task. */
export function approvalCard(entry,{api,getProject,decide,showFile}){
  const name=String(entry?.name||entry?.tool||""),args=entry?.args&&typeof entry.args==="object"?entry.args:{};
  const card=el("div","dsw-card dsw-ask");const bar=el("div","dsw-btns");
  const pick=(allow,buttons,okText,noText)=>{
    for(const b of buttons)b.disabled=true;
    Promise.resolve(decide(allow)).then(()=>{bar.replaceChildren(el("span","dsw-done"+(allow?" ok":""),allow?okText:noText));if(allow&&path)showFile?.(path,{after:true});});
  };
  let path=null;
  if(name==="edit_file"||name==="write_file"){
    path=relPath(args.path,getProject()?.project);
    card.append(el("b",null,"Here's the change for "+path),el("p",null,"Nothing is saved until you press Apply."));
    const slot=el("div","dsw-diffslot");card.append(slot);
    if(name==="edit_file")slot.append(diffPre(around(lineDiff(String(args.old??""),String(args.new??"")))));
    else{
      slot.append(el("p","dsw-hint","Loading the change…"));
      void (async()=>{
        let old=null;
        try{const p=getProject();const d=await api("/api/developer/studio/file?"+new URLSearchParams({project:p.project,path,encoding:"auto"}));old=String(d.text||"").replace(/\r\n?/g,"\n");}catch{old=null;}
        const add=String(args.content??""),append=args.append===true||String(args.append).toLowerCase()==="true";
        const nu=append&&old!=null?old+add:add;slot.replaceChildren();
        if(old==null)slot.append(el("p","dsw-hint","This makes a new file."));
        slot.append(diffPre(old==null?nu.split("\n").map(l=>["a",l]):around(lineDiff(old,nu))));
      })();
    }
    const yes=btn("Apply","primary"),no=btn("Skip",""),show=btn("Show file","link");
    yes.onclick=()=>pick(true,[yes,no],"✓ Applied","Skipped. Nothing changed.");
    no.onclick=()=>pick(false,[yes,no],"✓ Applied","Skipped. Nothing changed.");
    show.onclick=()=>showFile?.(path,{open:true});
    bar.append(yes,no,show);
    queueMicrotask(()=>showFile?.(path,{peek:true}));
  }else if(/^(run_shell|run_command)$/.test(name)){
    card.append(el("b",null,"Run this command?"),el("p",null,"It runs on this computer. Say no if you're not sure."));
    const pre=el("pre","dsw-cmd");pre.append(el("code",null,String(args.command||args.cmd||"")));card.append(pre);
    const yes=btn("Run once","primary"),no=btn("Don't run","");
    yes.onclick=()=>pick(true,[yes,no],"✓ Allowed once","Not run.");no.onclick=()=>pick(false,[yes,no],"","Not run.");
    bar.append(yes,no);
  }else{
    card.append(el("b",null,"Needs your OK"),el("p",null,String(entry?.label||entry?.reason||entry?.description||name||"a tool step")));
    const yes=btn("Approve once","primary"),no=btn("Deny","");
    yes.onclick=()=>pick(true,[yes,no],"✓ Approved once","Denied.");no.onclick=()=>pick(false,[yes,no],"","Denied.");
    bar.append(yes,no);
  }
  card.append(bar);return card;
}

// ---------------------------------------------------------------- the workspace
export function mountWorkspace({api,q,getProject,runner,git,editor,share,openFile,chat,onBack,status}){
  const BASE="/api/developer/studio";
  const box=el("div","dsw");box.id="dswRoot";
  // Chat column: a small status strip (only once something has happened) and the Developer chat
  // itself, moved in on open. "Manual controls" and "All tools" live in the page's ••• menu.
  const col=el("section","dsw-chatcol");col.setAttribute("aria-label","Chat with "+BRAND);
  const strip=el("div","dsw-strip");strip.setAttribute("aria-label","Where you are");strip.hidden=true;
  const pills={};
  for(const id of ["file","test","share"]){
    const b=el("button","dsw-pill");b.type="button";b.id="dswPill-"+id;b.dataset.mode=id;
    const mk=el("span","dsw-dot");mk.setAttribute("aria-hidden","true");const t=el("span","dsw-pill-t");
    b.append(mk,t);strip.append(b);pills[id]={b,t};
  }
  const chatSlot=el("div","dsw-chatslot");
  col.append(strip,chatSlot);
  // Live panel: the file being edited, the test result, sharing or the project map. Beside the chat
  // when there's room; a slide-in panel (tablets) or slide-up sheet (phones) otherwise.
  const live=el("aside","dsw-live");live.id="dswLive";live.setAttribute("aria-label","Live view");
  const handle=el("div","dsx-sheet-handle");handle.setAttribute("aria-hidden","true");
  const lhead=el("div","dsw-live-head");const ltitle=el("h3","dsw-live-title","Your files");
  const lclose=btn("Close","sm dsw-live-close",()=>{openLive(false);chat.focus?.();});
  lhead.append(ltitle,el("span","dsx-gap"),lclose);
  const MODES=[["file","Files","Your files"],["test","Test","Test results"],["share","Share","Share to GitHub or GitLab"],["map","Map","Project map"]];
  const seg=el("div","dsw-seg");seg.setAttribute("role","group");seg.setAttribute("aria-label","Manual controls");seg.hidden=true;
  const segBtns={},slots={};
  for(const [id,label] of MODES){
    const b=btn(label,"sm");b.dataset.mode=id;b.setAttribute("aria-pressed","false");seg.append(b);segBtns[id]=b;
    const s=el("div","dsw-slot dsw-"+(id==="file"?"edit":id));s.hidden=true;slots[id]=s;
  }
  const acct=el("details","dsw-account");acct.id="dswAccount";
  acct.append(el("summary",null,"Your GitHub or GitLab sign-in"));const acctSlot=el("div");acct.append(acctSlot);
  const shareParts={git:el("div"),share:el("div"),review:el("div")};
  slots.share.append(shareParts.git,shareParts.share,shareParts.review,acct);
  live.append(handle,lhead,seg,...Object.values(slots));
  const scrim=el("div","dsw-scrim");scrim.setAttribute("aria-hidden","true");scrim.onclick=()=>openLive(false);
  box.append(col,scrim,live);
  // Friendly empty state and quick chips, put into the chat only while the workspace is open.
  const hello=el("div","dsw-hello");
  const hav=el("span","dsw-hello-av",BRAND.charAt(0));hav.setAttribute("aria-hidden","true");
  hello.append(hav,el("h2",null,"Hi! What do you want to build or fix today?"),
    el("p",null,"Ask in your own words, or tap an idea below."));
  const chips=el("div","dsw-chips");chips.setAttribute("role","group");chips.setAttribute("aria-label","Quick actions");
  for(const [id,label] of CHIPS){const b=el("button","dsw-chip",label);b.type="button";b.dataset.chip=id;chips.append(b);}

  let open=false,mode="file",move=null,sync=null,syncFor=null,syncSeq=0,timer=null,watch=null,os=null,active=false,activeFor=null;
  const project=()=>getProject()?.project||null;
  const unsaved=()=>{try{return !!editor?.hasUnsaved?.();}catch{return false;}};
  const overlay=()=>getComputedStyle(live).position==="absolute";
  function setMode(id){
    mode=id;
    for(const [m,,title] of MODES){slots[m].hidden=m!==id;segBtns[m].setAttribute("aria-pressed",String(m===id));if(m===id)ltitle.textContent=title;}
    if(id==="file")queueMicrotask(()=>window.dispatchEvent(new Event("resize")));
    if(id==="share"){void loadSync();if(project())void git?.load?.();}
  }
  function openLive(on,id){
    if(id)setMode(id);
    box.classList.toggle("live-open",!!on);
    if(on)queueMicrotask(()=>overlay()&&lclose.focus());
  }
  /** Manual controls: the full Run my app, Checkpoints, Share and Project map panels. */
  function manualControls(){
    seg.hidden=false;
    if(overlay())openLive(true);
    queueMicrotask(()=>(segBtns[mode]||seg.firstChild)?.focus?.());
  }
  // The page's ••• menu gets two extra items while the workspace is open. The shell rebuilds the menu
  // on every click, so they are added right after it (text only, no HTML).
  const more=document.querySelector("#convMore"),menu=document.querySelector("#convMenu");
  more?.addEventListener("click",()=>{
    if(!open||!menu||menu.hidden)return;
    const close=()=>menu.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true}));
    const item=(label,id,ic,fn)=>{const b=el("button","dsw-menu-item",label);b.type="button";b.dataset.icon=ic;b.setAttribute("role","menuitem");b.dataset.ws=id;b.onclick=()=>{close();fn();};return b;};
    const sep=el("div");sep.setAttribute("role","separator");
    menu.prepend(item("Manual controls","manual","wrench",manualControls),item("All tools","tools","grid",()=>onBack?.()),sep);
    hydrateIcons(menu);
    menu.querySelector("[role=menuitem]")?.focus();
  });
  seg.addEventListener("click",e=>{const b=e.target.closest("[data-mode]");if(b)setMode(b.dataset.mode);});
  strip.addEventListener("click",e=>{const b=e.target.closest("[data-mode]");if(b)openLive(true,b.dataset.mode);});
  chips.addEventListener("click",e=>{const b=e.target.closest("[data-chip]");if(b)quick(b.dataset.chip,b.textContent);});
  box.addEventListener("keydown",e=>{if(e.key==="Escape"&&box.classList.contains("live-open")&&overlay()){openLive(false);chat.focus?.();}});

  // ------------------------------------------------------------ strip
  // Hidden until something has happened here (an edit, a test or a checkpoint), in plain words.
  // Numbers only go in the tooltip.
  function draw(){
    const p=project();if(activeFor!==p){active=false;activeFor=p;}
    const dirty=unsaved(),t=runner?.getState?.().test,gs=git?.getState?.().state||{};
    const changed=(gs.files||[]).filter(f=>f.unstaged||f.staged).length;
    if(dirty||t||changed)active=true;
    strip.hidden=!active;
    const set=(id,tone,label,tip)=>{const x=pills[id];x.b.className="dsw-pill t-"+tone;x.t.textContent=label;x.b.title=tip;x.b.setAttribute("aria-label",label+". "+tip);};
    set("file",dirty?"warn":"ok",dirty?"Changes not saved":"All saved",
      dirty?"Press Save in the editor.":changed?plural(changed,"file")+" changed since your last checkpoint.":"Everything is saved.");
    const s=t?.summary||{},passed=s.passed||0,total=passed+(s.failed||0);
    if(t?.live)set("test","busy","Testing…","Your tests are running.");
    else if(t?.status==="passed")set("test","ok","Tests passed",total?passed+" of "+total+" checks passed.":"Your tests passed.");
    else if(t&&t.status!=="stopped")set("test","bad","Tests failing",s.failed?s.failed+" of "+total+" checks failed.":"Your tests didn't pass.");
    else set("test","idle","Not tested yet","Tap to test your app.");
    const st=sync?.sync||{},n=st.unshared||0,site=NAMES[sync?.target?.provider]||"GitHub or GitLab";
    if(sync&&!sync.error&&st.state==="shared")set("share","ok","Everything shared","Everything is on "+site+".");
    else set("share",n?"warn":"idle","Not shared yet",n?plural(n,"checkpoint")+" not on "+site+" yet.":"Nothing is on "+site+" yet.");
  }
  function noteActivity(){active=true;draw();}
  async function loadSync(){
    const p=project();if(!p){sync=null;syncFor=null;draw();return null;}
    const seq=++syncSeq;
    try{const s=await api(BASE+"/remote/status?project="+encodeURIComponent(p));if(seq===syncSeq){sync=s;syncFor=p;}}
    catch{if(seq===syncSeq){sync={error:true};syncFor=p;}}
    draw();return sync;
  }
  runner?.onChange?.(()=>{if(open)draw();});
  git?.onChange?.(()=>{if(open)void loadSync();});

  // ------------------------------------------------------------ quick actions (never sent to the model)
  function quick(id,label){
    if(chat.busy()){status?.("Wait for the current task to finish first.",true);return;}
    if(AI_PROMPTS[id]){void chat.submit(AI_PROMPTS[id],{display:label});return;}
    void run(id,label);
  }
  const card=(body,title,text,cls)=>{const c=el("div","dsw-card"+(cls?" "+cls:""));c.append(el("b",null,title));if(text)c.append(el("p",null,text));body.append(c);chat.scroll();return c;};
  const bar=(c,...items)=>{const b=el("div","dsw-btns");b.append(...items.filter(Boolean));c.append(b);chat.scroll();return b;};
  const done=(b,text,ok)=>b.replaceChildren(el("span","dsw-done"+(ok?" ok":""),text));
  const chipBtn=(label,id,primary)=>btn(label,primary?"primary":"",()=>quick(id,label));
  const showBtn=(label,id)=>btn(label,"link",()=>openLive(true,id));
  const fail=(body,e,what)=>card(body,"I couldn't "+what+".",(e?.message||"Something went wrong.")+" Try again, or use Manual controls.","bad");
  async function run(kind,userText){
    const body=chat.exchange(userText);
    const p=getProject();
    if(!p?.project){card(body,"Open a project first.","Pick a folder with the project button at the top.");return;}
    try{
      if(kind==="test"||kind==="app")await runFlow(body,kind);
      else if(kind==="share")await shareFlow(body);
      else if(kind==="checkpoint")await saveFlow(body,()=>card(body,"✓ Checkpoint saved.","It stays on this computer until you share it.","ok"));
      else if(kind==="review")await reviewFlow(body);
      else if(kind==="checks")await checksFlow(body);
      else if(kind==="map")await mapFlow(body);
    }catch(e){fail(body,e,"do that");}
  }
  // ---- run the app or its tests: inline confirm, then the approval-gated runner
  function waitRun(kind,before){
    return new Promise(res=>{
      let off=null;
      const check=()=>{const r=runner.getState()[kind];if(r&&r.run_id!==before&&(!r.live||(kind==="app"&&r.preview_url))){off?.();res(r);return true;}return false;};
      if(!check())off=runner.onChange(check);
    });
  }
  async function runFlow(body,kind){
    const p=getProject();
    if(!p.trusted){const c=card(body,"Allow changes for this project first.","Then I can run it. You still say yes before anything runs.");bar(c,btn("Allow changes","primary",()=>q("#dsTrust")?.click()));return;}
    await runner.hasRecipe(kind).catch(()=>false);
    const r=runner.pick(kind);
    if(!r){const c=card(body,kind==="test"?"I couldn't find any tests yet.":"I couldn't find how to start this app.","I can set that up for you.");
      bar(c,btn(kind==="test"?"Add tests for me":"Set it up for me","primary",()=>void chat.submit(kind==="test"?"Add a few simple tests for the most important part of this project, then run them.":"Find or add a start command for this app so it can run locally, then tell me how to start it.",{display:kind==="test"?"Add tests for me":"Set up a start command"})));return;}
    if(!r.available){card(body,r.missing+" isn't installed on this computer.","Install it, then try again.","bad");return;}
    const c=card(body,kind==="test"?"Run your tests?":"Start your app?",kind==="test"?"This runs your project's own test command on this computer. Nothing is changed.":"It runs on this computer only. Nobody else on your network can open it.");
    const pre=el("pre","dsw-cmd");pre.append(el("code",null,r.command));c.append(pre);
    const go=btn(kind==="test"?"Run tests":"Start app","primary"),no=btn("Not now","");
    const b=bar(c,go,no);
    no.onclick=()=>done(b,"Okay, nothing ran.");
    go.onclick=async()=>{
      go.disabled=no.disabled=true;
      const before=runner.getState()[kind]?.run_id;
      const ok=await runner.start(r,{confirmed:true});
      if(!ok){done(b,"It didn't start. See Manual controls → Test.");return;}
      done(b,kind==="test"?"Running your tests…":"Starting your app…");noteActivity();
      if(!isSheet())setMode("test");
      const res=await waitRun(kind,before);
      if(kind==="test")testCard(body,res);
      else if(res.preview_url){const rc=card(body,"✓ Your app is running.","It's at "+res.preview_url+". Only this computer can open it.","ok");bar(rc,showBtn("See it live","test"));}
      else card(body,"The app stopped.",res.reason||"Check the output in Manual controls → Test.","bad");
      draw();
    };
  }
  function testCard(body,r){
    const s=r.summary||{},passed=s.passed||0,total=passed+(s.failed||0),ok=r.status==="passed",tone=ok?"ok":r.status==="stopped"?"idle":"bad";
    const c=el("div","dsb-check t-"+tone+" dsw-result");
    c.append(ring(total?passed:null,total,tone,ok?"✓":tone==="idle"?"–":"!"));
    const tx=el("div","dsb-check-text");
    tx.append(el("b",null,ok?(total?"All "+total+" checks passed":"Your tests passed"):tone==="idle"?"Tests stopped":(s.failed?s.failed+" of "+total+" checks failed":"Your tests didn't pass")),
      el("p",null,ok?"Everything you tested works.":tone==="idle"?"Run them again when you're ready.":"Here's what didn't work."));
    if(!ok&&s.failures?.length){const ul=el("ul","dsb-broken");for(const f of s.failures.slice(0,5))ul.append(el("li",null,f));tx.append(ul);}
    const b=el("div","dsw-btns");
    if(ok)b.append(chipBtn("Share to GitHub","share",true));
    else if(tone==="bad")b.append(btn("Fix it for me","primary",()=>void chat.submit(AI_PROMPTS.fix+(s.failures?.length?" These checks failed: "+s.failures.slice(0,5).join("; ")+".":""),{display:"Fix the failing checks"})));
    b.append(showBtn("See details","test"));tx.append(b);c.append(tx);body.append(c);chat.scroll();
  }
  // ---- save a checkpoint (the inline card's button is the confirmation)
  function saveable(){
    const s=git?.getState?.().state||{};
    return {files:(s.files||[]).filter(f=>!f.conflict&&!f.secret_like&&(f.unstaged||f.staged)),needIdent:!!(s.identity&&!s.identity.configured),repo:s.repository!==false};
  }
  async function saveFlow(body,then){
    await git?.load?.();
    const f=saveable();
    if(!f.repo){card(body,"Checkpoints aren't turned on for this project.","Turn them on in Manual controls → Share. Nothing is uploaded.");return false;}
    if(!f.files.length){if(then)return then();card(body,"Nothing new to save.","Your last checkpoint already has everything.");return true;}
    if(unsaved()){card(body,"Save your open file first.","Press Save in the editor, then ask again.","bad");return false;}
    return new Promise(res=>{
      const c=card(body,"Save your changes first?",plural(f.files.length,"file")+" changed. A checkpoint is a saved version. It stays on this computer.");
      const ul=el("ul","dsw-files");for(const x of f.files.slice(0,6))ul.append(el("li",null,x.path));if(f.files.length>6)ul.append(el("li",null,"…and "+(f.files.length-6)+" more"));c.append(ul);
      const msg=el("input","input dsw-input");msg.maxLength=200;msg.value=lastAsk||"My changes";msg.setAttribute("aria-label","Describe your change");c.append(msg);
      let name=null,email=null;
      if(f.needIdent){
        c.append(el("p","dsw-hint","First time? Add your name so checkpoints show who made them."));
        name=el("input","input dsw-input");name.placeholder="Your name";name.setAttribute("aria-label","Your name");name.maxLength=120;
        email=el("input","input dsw-input");email.placeholder="you@example.com";email.setAttribute("aria-label","Your email");email.maxLength=200;c.append(name,email);
      }
      const go=btn("Save checkpoint","primary"),no=btn("Not now","");const b=bar(c,go,no);
      no.onclick=()=>{done(b,"Okay, nothing saved.");res(false);};
      go.onclick=async()=>{
        const m=msg.value.trim();if(m.length<2){msg.focus();return;}
        if(name&&(!name.value.trim()||!email.value.trim())){(name.value.trim()?email:name).focus();return;}
        go.disabled=no.disabled=true;
        const r=await git.saveCheckpoint(m,name?{name:name.value.trim(),email:email.value.trim()}:null);
        if(!r){done(b,"It didn't save. "+(git.getState().lastError||"See Manual controls → Share."));res(false);return;}
        done(b,"✓ Saved “"+m+"”.",true);noteActivity();await loadSync();
        res(then?await then():true);
      };
    });
  }
  // ---- share: account, where, check, then the user's Share click
  async function shareFlow(body){
    const ok=await saveFlow(body,null);if(ok===false)return;
    const st=await loadSync();
    if(!st||st.error){fail(body,{message:st?.error?.message||"I couldn't read this project's checkpoints."},"get ready to share");return;}
    const site=NAMES[st.target?.provider]||"GitHub";
    if(!(st.accounts||[]).some(a=>a.status==="ok")){
      const c=card(body,"Connect your GitHub or GitLab account first.","Your sign-in stays in this computer's password store, never in the chat.");
      bar(c,btn("Connect my account","primary",()=>{acct.open=true;openLive(true,"share");acct.scrollIntoView?.({block:"start"});}));return;}
    if(!st.target){const c=card(body,"Pick where to share.","Choose the repository on "+site+" once. I'll remember it for this project.");bar(c,btn("Pick a repository","primary",()=>openLive(true,"share")));return;}
    if(!isSheet())setMode("share");
    const plan=await api(BASE+"/remote/plan",{project:project(),remote_branch:null});
    const c=card(body,plan.ok?"Share "+plural(plan.commit_count,"checkpoint")+" to "+st.target.repo+"?":"It can't be shared yet.",plan.summary);
    if(plan.commits?.length){const ul=el("ul","dsw-files");for(const x of plan.commits.slice(0,5))ul.append(el("li",null,x.subject));if(plan.commit_count>5)ul.append(el("li",null,"…and "+(plan.commit_count-5)+" more"));c.append(ul);}
    if(plan.blocks?.length){
      const ul=el("ul","dsw-blocks");for(const x of plan.blocks)ul.append(el("li",null,x.message));c.append(ul);
      if(plan.blocks.every(x=>x.rule==="nothing"))return;
      bar(c,plan.blocks.some(x=>x.rule==="non_ff")?btn("Get latest","primary",()=>openLive(true,"share")):null,btn("Share it myself (save a .patch)","",()=>void fallback(body,plan.blocks.find(x=>x.rule!=="nothing")?.rule||"manual")));
      return;
    }
    c.append(el("p","dsw-ok","✓ No passwords, keys, .env files, huge files or CI changes found."));
    for(const w of plan.warnings||[])c.append(el("p","dsw-warn",w.message));
    const go=btn("Share","primary"),no=btn("Not now","");const b=bar(c,go,no);
    no.onclick=()=>done(b,"Okay, nothing was sent.");
    go.onclick=async()=>{
      go.disabled=no.disabled=true;done(b,"Sharing…");
      try{
        const r=await api(BASE+"/remote/share",{project:project(),remote_branch:plan.remote_branch,action_sha256:plan.action_sha256,confirmed:true});
        if(r.ok){done(b,"Sent.",true);const rc=card(body,"Shared ✓",r.message,"ok");bar(rc,r.links?.branch?extLink(r.links.branch,"Open on "+site):null,chipBtn("Ask for a review","review",true));}
        else{done(b,"It didn't go through.");fallbackCard(body,r.fallback,site);}
      }catch(e){done(b,"It didn't go through.");const ec=card(body,"It didn't go through.",e.message,"bad");bar(ec,btn("Share it myself (save a .patch)","",()=>void fallback(body,"manual")));}
      share?.refresh?.();void loadSync();
    };
  }
  async function fallback(body,reason){
    try{const r=await api(BASE+"/remote/fallback",{project:project(),remote_branch:null,reason});fallbackCard(body,r.fallback,NAMES[sync?.target?.provider]||"GitHub");}
    catch(e){fail(body,e,"save the .patch file");}
  }
  function fallbackCard(body,fb,site){
    if(!fb)return;
    os=os||sync?.os||"windows";
    const wrap=el("div","dsw-card dsw-fallback");
    const drawFb=()=>wrap.replaceChildren(renderFallback(fb,{os,setOs:k=>{os=k;drawFb();},site,actions:{signin:["Connect again",()=>{acct.open=true;openLive(true,"share");}],get_latest:["Get latest",()=>openLive(true,"share")],retry:["Try again",()=>quick("share","Share to GitHub")]}}));
    drawFb();body.append(wrap);chat.scroll();
  }
  // ---- ask for a review (a draft; nothing is ever merged)
  async function reviewFlow(body){
    const R=BASE+"/remote/review";
    const pv=await api(R+"/preview",{project:project(),branch:null,base:null});
    const site=NAMES[pv.provider]||"GitHub";
    if(pv.ok===false){card(body,"I couldn't ask for a review yet.",pv.fallback?.headline||"");fallbackCard(body,pv.fallback,site);return;}
    if(pv.existing){const c=card(body,"You already asked for a review.",pv.existing.title||"");bar(c,pv.existing.url?extLink(pv.existing.url,"Open it on "+site):null,chipBtn("See checks","checks",false));return;}
    const c=card(body,"Ask for a review?","I wrote the title and description from your checkpoints. Change anything you like. It opens as a draft on "+site+", and nothing is merged.");
    const t=el("input","input dsw-input");t.value=pv.title||"";t.maxLength=200;t.setAttribute("aria-label","Title");
    const d=el("textarea","input dsw-input");d.value=pv.body||"";d.rows=4;d.setAttribute("aria-label","Description");
    c.append(t,d);
    const go=btn("Ask for a review","primary"),no=btn("Not now","");const b=bar(c,go,no);
    no.onclick=()=>done(b,"Okay, nothing was sent.");
    go.onclick=async()=>{
      if(t.value.trim().length<3){t.focus();return;}
      go.disabled=no.disabled=true;done(b,"Sending…");
      try{
        const r=await api(R+"/open",{project:project(),branch:pv.branch,base:pv.base,title:t.value.trim(),body:d.value,draft:true,action_sha256:pv.action_sha256,confirmed:true});
        if(r.ok){done(b,"Sent.",true);const rc=card(body,"Review asked ✓",r.message||"","ok");bar(rc,r.review?.url?extLink(r.review.url,"Open it on "+site):null,chipBtn("See checks","checks",false));}
        else{done(b,"It didn't go through.");fallbackCard(body,r.fallback,site);}
      }catch(e){done(b,"It didn't go through.");fail(body,e,"ask for a review");}
    };
  }
  async function checksFlow(body){
    const st=sync||await loadSync();
    const ck=await api(BASE+"/remote/review/checks?project="+encodeURIComponent(project())+(st?.branch?"&branch="+encodeURIComponent(st.branch):""));
    const tone=ck.state==="passed"||ck.state==="success"?"ok":ck.running?"busy":ck.failed?"bad":"idle";
    const c=el("div","dsb-check t-"+tone+" dsw-result");c.append(ring(ck.total?ck.passed:null,ck.total||0,tone,tone==="ok"?"✓":tone==="bad"?"!":"–"));
    const tx=el("div","dsb-check-text");tx.append(el("b",null,ck.title||"Checks"),el("p",null,ck.text||""));
    const b=el("div","dsw-btns");if(ck.web_url)b.append(extLink(ck.web_url,"Open checks"));b.append(showBtn("See details","share"));tx.append(b);c.append(tx);body.append(c);chat.scroll();
  }
  // ---- project map: read-only static analysis, nothing runs
  async function mapFlow(body){
    const m=await api(BASE+"/polyglot/map",{project:project()});
    const b=m.budget||{},langs=(m.languages||[]).map(l=>l.name);
    const c=card(body,b.read?"Mapped "+plural(b.read,"file"):"I didn't find any code files yet.",
      b.read?(langs.length?langs.slice(0,4).join(", ")+". ":"")+(m.broken_count?plural(m.links||0,"link")+" between files, "+m.broken_count+" broken.":plural(m.links||0,"link")+" between files, and none are broken."):"Add some files, then ask again.",b.read?"ok":"");
    bar(c,showBtn("See the map","map"));
  }

  // ------------------------------------------------------------ open / close
  let lastAsk="";
  const isSheet=overlay;
  function find(sel){return sel.startsWith(".")?q(sel):q("#"+sel);}
  function show(m="file",{section,place,openPanel=false}={}){
    move=place;open=true;
    const put=(sel,slot)=>{const n=find(sel);if(n)move(n,slot);};
    put("dsxChat",chatSlot);
    put(".ds-mobile-switch",slots.file);put(".ds-columns",slots.file);put("dsStatus",slots.file);
    put("dsRunRoot",slots.test);
    put("dsGitRoot",shareParts.git);put("dsShareRoot",shareParts.share);put("dsReviewRoot",shareParts.review);put("dsAccountRoot",acctSlot);
    put("dsPolyglotRoot",slots.map);
    const thread=chatSlot.querySelector("#dsxThread");thread?.before(hello);
    chatSlot.querySelector("#dsxComposer")?.before(chips);
    acct.open=section==="account";seg.hidden=true;
    if(syncFor!==project())sync=null;
    setMode(m);openLive(openPanel);void loadSync();draw();
    clearInterval(watch);let was=unsaved();
    watch=setInterval(()=>{if(!open)return;const now=unsaved();if(now!==was){was=now;draw();}},600);
    clearInterval(timer);timer=setInterval(()=>{if(open&&!document.hidden)void loadSync();},10000);
    if(section==="account")queueMicrotask(()=>acct.scrollIntoView?.({block:"start"}));
    return box;
  }
  function hide(){
    open=false;clearInterval(timer);clearInterval(watch);timer=watch=null;
    hello.remove();chips.remove();box.classList.remove("live-open");
  }
  /** Show a file in the live panel (on phones only when asked, so the chat stays in view). */
  function showFile(path,{open:want=false,changed=false}={}){
    if(!open)return false;
    if(changed){void git?.load?.();noteActivity();}
    setMode("file");if(path)void openFile?.(path);
    if(want)openLive(true);
    return true;
  }
  return {el:box,show,hide,setMode,openLive,showFile,refresh(){if(open){sync=null;void loadSync();}},
    /** A typed request: handled here when it's a quick action, otherwise it goes to the assistant. */
    handle(text){const k=intentOf(text);if(!k){lastAsk=String(text).trim().slice(0,80);return false;}void run(k,String(text).trim());return true;},
    noteAsk(text){lastAsk=String(text||"").trim().slice(0,80);},
    get open(){return open;},get mode(){return mode;}};
}

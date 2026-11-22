/* One workspace: Edit, Test and Share side by side, with a status strip that always shows
   unsaved files, the last test result and how many checkpoints aren't shared yet.
   It owns no logic of its own: the editor, the approval-gated runner, Checkpoints, Share and
   Ask for a review are the same panels moved in here, and they go back where they came from
   when the workspace closes. The sync count comes from the local, offline share status. */
import {ring} from "./developer-beginner.js";

const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const TABS=[
  ["edit","Edit","Change your files"],
  ["test","Test","Check it works"],
  ["share","Share","Send it online"]
];

export function mountWorkspace({api,q,getProject,runner,git,editor}){
  const BASE="/api/developer/studio";
  const box=el("div","dsw");box.id="dswRoot";
  // Tabs: a simple three-step row. Each one is a real tab with a panel.
  const tabs=el("div","dsw-tabs");tabs.setAttribute("role","tablist");tabs.setAttribute("aria-label","Edit, test and share");
  const panes={},tabBtns={};
  TABS.forEach(([id,label,sub],i)=>{
    const b=el("button","dsw-tab");b.type="button";b.id="dswTab-"+id;b.dataset.tab=id;
    b.setAttribute("role","tab");b.setAttribute("aria-controls","dswPane-"+id);b.setAttribute("aria-selected","false");b.tabIndex=-1;
    const n=el("span","dsw-n",String(i+1));n.setAttribute("aria-hidden","true");
    const t=el("span","dsw-tab-t");t.append(el("b",null,label),el("small",null,sub));
    b.append(n,t);tabs.append(b);tabBtns[id]=b;
    if(i<TABS.length-1){const a=el("span","dsw-arrow","›");a.setAttribute("aria-hidden","true");tabs.append(a);}
  });
  // Status strip: three facts, each one opens the tab it belongs to.
  const strip=el("div","dsw-strip");strip.setAttribute("aria-label","Where you are");
  const facts={};
  for(const [id,label] of [["edit","Your files"],["test","Last test"],["share","On the website"]]){
    const f=el("button","dsw-fact");f.type="button";f.dataset.go=id;f.id="dswFact-"+id;
    const mark=el("span","dsw-mark");mark.setAttribute("aria-hidden","true");
    const t=el("span","dsw-fact-t");const main=el("b");const small=el("small",null,label);const brief=el("span","dsw-brief");brief.setAttribute("aria-hidden","true");
    t.append(main,small,brief);f.append(mark,t);strip.append(f);facts[id]={f,mark,main,small,brief};
  }
  const live=el("p","sr");live.setAttribute("role","status");live.setAttribute("aria-live","polite");
  // Tabs and strip stay at the top while the page scrolls.
  const head=el("div","dsw-head");head.append(tabs,strip);
  box.append(head,live);
  for(const [id] of TABS){
    const p=el("section","dsw-pane dsw-"+id);p.id="dswPane-"+id;p.setAttribute("role","tabpanel");p.setAttribute("aria-labelledby","dswTab-"+id);p.hidden=true;
    panes[id]=p;box.append(p);
  }
  const lead=(id,text)=>panes[id].append(el("p","dsw-lead",text));
  lead("edit","Pick a file on the left, change it and press Save. Saving only changes this computer.");
  const editSlot=el("div","dsw-slot");panes.edit.append(editSlot);
  lead("test","Run your app or its tests. "+"Nothing runs until you press a button and say yes.");
  const testNote=el("p","dsw-note");testNote.hidden=true;panes.test.append(testNote);
  const testSlot=el("div","dsw-slot");panes.test.append(testSlot);
  lead("share","First save a checkpoint (a saved version), then share it. Nothing is sent until you click Share.");
  const shareSlots={};const jump=el("div","dsw-jump");jump.setAttribute("aria-label","Steps to share");panes.share.append(jump);
  [["git","Save a checkpoint"],["share","Share"],["review","Ask for a review"]].forEach(([id,title],i)=>{
    const s=el("section","dsw-part");s.id="dswPart-"+id;const slot=el("div","dsw-slot");s.append(slot);
    panes.share.append(s);shareSlots[id]=slot;
    const b=el("button","dsw-jump-b");b.type="button";b.append(el("span","dsw-n",String(i+1)),el("span",null,title));
    b.addEventListener("click",()=>{
      // Scroll so the part starts just under the sticky tabs and strip.
      const sc=box.closest(".dsx-tools");if(!sc){s.scrollIntoView?.({block:"start"});return;}
      sc.scrollTop+=s.getBoundingClientRect().top-head.getBoundingClientRect().bottom-8;
    });
    if(i)jump.append(el("span","dsw-arrow","›"));jump.append(b);
  });
  const acct=el("details","dsw-account");acct.id="dswAccount";
  acct.append(el("summary",null,"Your GitHub or GitLab sign-in"));const acctSlot=el("div","dsw-slot");acct.append(acctSlot);
  panes.share.append(acct);
  // One obvious next step at the end of each tab.
  const nexts={};
  for(const id of ["edit","test","share"]){
    const n=el("div","dsw-next");const text=el("span","dsw-next-t");n.append(text);nexts[id]={n,text,btns:el("span","dsw-next-b")};
    n.append(nexts[id].btns);panes[id].append(n);
  }
  const go=(label,tab,primary)=>{const b=el("button","btn"+(primary?" primary":""),label);b.type="button";b.dataset.goTab=tab;return b;};

  let current=null,move=null,open=false,sync=null,syncFor=null,syncSeq=0,timer=null,watch=null;
  function select(id,{focus=false}={}){
    current=id;
    for(const [t] of TABS){
      const on=t===id;tabBtns[t].setAttribute("aria-selected",String(on));tabBtns[t].tabIndex=on?0:-1;
      tabBtns[t].classList.toggle("on",on);panes[t].hidden=!on;
    }
    if(focus)tabBtns[id].focus();
    if(id==="edit")queueMicrotask(()=>window.dispatchEvent(new Event("resize")));
    // Share shows what changed since the last checkpoint, so it looks again each time.
    if(id==="share"){void loadSync();if(getProject()?.project)void git?.load?.();}
    draw();
  }
  const toTop=()=>{const sc=box.closest(".dsx-tools");if(sc)sc.scrollTop=0;};
  // The page around the workspace has top padding; the sticky tabs sit flush at the very top.
  const pin=()=>{const sc=box.closest(".dsx-tools");if(sc)head.style.top="-"+(parseFloat(getComputedStyle(sc).paddingTop)||0)+"px";};
  window.addEventListener("resize",()=>{if(open)pin();});
  tabs.addEventListener("click",e=>{const b=e.target.closest("[data-tab]");if(b)select(b.dataset.tab);});
  tabs.addEventListener("keydown",e=>{
    const order=TABS.map(t=>t[0]);const i=order.indexOf(current);
    const j=e.key==="ArrowRight"?i+1:e.key==="ArrowLeft"?i-1:e.key==="Home"?0:e.key==="End"?order.length-1:null;
    if(j==null)return;e.preventDefault();select(order[(j+order.length)%order.length],{focus:true});
  });
  strip.addEventListener("click",e=>{const b=e.target.closest("[data-go]");if(b){select(b.dataset.go);toTop();}});
  box.addEventListener("click",e=>{const b=e.target.closest("[data-go-tab]");if(b){select(b.dataset.goTab);toTop();}});

  // ------------------------------------------------------------ facts
  const unsaved=()=>{try{return !!editor?.hasUnsaved?.();}catch{return false;}};
  function testFact(){
    const t=runner?.getState?.().test;
    if(!t)return {tone:"idle",title:"Not tested yet",passed:null,total:0,mark:"–"};
    const s=t.summary||{};const passed=s.passed||0,total=passed+(s.failed||0);
    if(t.live)return {tone:"busy",title:"Testing…",passed:null,total:0,mark:"…"};
    if(t.status==="passed")return {tone:"ok",title:"Tests passed",passed,total,mark:"✓"};
    if(t.status==="stopped")return {tone:"idle",title:"Tests stopped",passed:null,total:0,mark:"–"};
    return {tone:"bad",title:(s.failed?s.failed+" test"+(s.failed===1?"":"s")+" failing":"Tests didn't pass"),passed,total,mark:"!"};
  }
  function syncFact(){
    const g=git?.getState?.();
    if(!getProject()?.project)return {tone:"idle",title:"No project open"};
    if(g?.state&&g.state.repository===false)return {tone:"idle",title:"No checkpoints yet"};
    if(!sync)return {tone:"idle",title:"Checking…"};
    if(sync.error)return {tone:"idle",title:"No checkpoints yet"};
    const s=sync.sync||{};const n=s.unshared||0,word=n===1?"checkpoint":"checkpoints";
    const where=sync.target?(sync.target.provider==="gitlab"?"GitLab":"GitHub"):null;
    if(s.state==="no_checkpoints")return {tone:"idle",title:"No checkpoints yet"};
    if(!where)return {tone:"warn",title:"Not connected to a website yet",n};
    if(s.state==="shared")return {tone:"ok",title:"Everything is shared",where};
    if(s.state==="never_shared")return {tone:"warn",title:n+" "+word+" not shared yet",where,n};
    return {tone:"warn",title:n+" "+word+" not shared yet",where,n};
  }
  async function loadSync(){
    const p=getProject()?.project;if(!p){sync=null;syncFor=null;draw();return;}
    const seq=++syncSeq;
    try{const s=await api(BASE+"/remote/status?project="+encodeURIComponent(p));if(seq===syncSeq){sync=s;syncFor=p;}}
    catch{if(seq===syncSeq){sync={error:true};syncFor=p;}}
    draw();
  }
  function draw(){
    const dirty=unsaved();
    const e=facts.edit;e.f.className="dsw-fact t-"+(dirty?"warn":"ok");
    e.mark.replaceChildren(el("span","dsw-dot"));
    e.main.textContent=dirty?"Unsaved changes":"All saved";e.brief.textContent=dirty?"Unsaved":"Saved";
    const t=testFact(),f=facts.test;f.f.className="dsw-fact t-"+t.tone;
    f.mark.replaceChildren(ring(t.total?t.passed:null,t.total,t.tone,t.mark));
    f.main.textContent=t.total?t.title+" · "+t.passed+" of "+t.total:t.title;
    f.brief.textContent=t.tone==="ok"?"Passed":t.tone==="bad"?"Failing":t.tone==="busy"?"Testing…":"Not tested";
    const s=syncFact(),h=facts.share;h.f.className="dsw-fact t-"+s.tone;
    h.mark.replaceChildren(el("span","dsw-up",s.tone==="ok"?"✓":"⇧"));
    h.main.textContent=s.title;
    h.brief.textContent=s.tone==="ok"?"All shared":s.n?s.n+" not shared":s.title==="Checking…"?"Checking…":"Not shared";h.small.textContent=s.where?"On "+s.where:"On the website";
    // Notes and next steps.
    testNote.hidden=!dirty;testNote.textContent=dirty?"You have unsaved changes. Tests use the saved files, so save first.":"";
    const ne=nexts.edit;ne.text.textContent=dirty?"Save your changes, then test them.":"Done changing things?";ne.btns.replaceChildren(go("Test it →","test",true));
    const nt=nexts.test;nt.btns.replaceChildren();
    if(t.tone==="ok"){nt.text.textContent="Tests passed. Ready to share.";nt.btns.append(go("Share it →","share",true));}
    else if(t.tone==="bad"){nt.text.textContent="Some tests didn't pass. Fix them in Edit, or share anyway.";nt.btns.append(go("← Back to Edit","edit",false),go("Share it →","share",true));}
    else{nt.text.textContent="When you're happy, share your work.";nt.btns.append(go("Share it →","share",true));}
    const ns=nexts.share;ns.btns.replaceChildren(go("Start the next change","edit",false));
    ns.text.textContent=s.tone==="ok"?"All shared. Nice work.":"Shared? Ask someone to look at it, or start your next change.";
    for(const [id] of TABS)tabBtns[id].dataset.state=id==="edit"?(dirty?"warn":""):id==="test"?(t.tone==="ok"||t.tone==="bad"?t.tone:""):(s.tone==="ok"?"ok":"");
  }
  runner?.onChange?.(()=>{if(open)draw();});
  git?.onChange?.(()=>{if(open)void loadSync();});

  function find(sel){return sel.startsWith(".")?q(sel):q("#"+sel);}
  function show(tab="edit",{section,place}={}){
    move=place;open=true;
    const put=(sel,slot)=>{const n=find(sel);if(n)move(n,slot);};
    put(".ds-mobile-switch",editSlot);put(".ds-columns",editSlot);put("dsStatus",editSlot);
    put("dsRunRoot",testSlot);
    put("dsGitRoot",shareSlots.git);put("dsShareRoot",shareSlots.share);put("dsReviewRoot",shareSlots.review);
    put("dsAccountRoot",acctSlot);
    acct.open=section==="account";
    if(syncFor!==getProject()?.project)sync=null;
    select(tab);void loadSync();queueMicrotask(pin);
    // Unsaved files: a cheap local check, only while the workspace is open.
    clearInterval(watch);let was=unsaved();
    watch=setInterval(()=>{if(!open)return;const now=unsaved();if(now!==was){was=now;draw();}},600);
    clearInterval(timer);timer=setInterval(()=>{if(open&&!document.hidden&&current==="share")void loadSync();},8000);
    if(section==="account")queueMicrotask(()=>acct.scrollIntoView?.({block:"start"}));
    return box;
  }
  function hide(){open=false;clearInterval(timer);clearInterval(watch);timer=null;watch=null;}
  return {el:box,show,hide,select,refresh(){if(open){sync=null;void loadSync();}},get open(){return open;},get tab(){return current;}};
}

/* Ask for a review + Checks on GitHub/GitLab (V46-V48 plan, PR 4).
   Guided steps: your shared branch -> write the request -> ask for a review (a draft pull/merge
   request, only after your click and a preview of the exact text) -> read-only checks in the same
   small health-ring card as Run my app. AutoMoto never merges.
   Everything from the website (titles, check and job names, messages, logs, links) is untrusted:
   it only reaches the page through textContent, links must be https, and nothing is ever run.
   Nothing is stored in the browser; the engine keeps the token and never sends it here. */
import {ring} from "./developer-beginner.js";
const BASE="/api/developer/studio/remote/review";
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const btn=(text,cls,fn)=>{const b=el("button","btn "+(cls||""),text);b.type="button";if(fn)b.onclick=fn;return b;};
const NAMES={github:"GitHub",gitlab:"GitLab"};
const OSES=[["windows","Windows"],["macos","Mac"],["linux","Linux"]];
const TONE={passed:"ok",failed:"bad",running:"busy"};
const safeUrl=u=>/^https:\/\/[^\s"'<>`\\]+$/.test(String(u||""))?u:null;
function extLink(url,label,cls){
  const ok=safeUrl(url);const a=el("a","btn "+(cls||"sm"),label+" ↗");
  if(ok){a.href=ok;a.target="_blank";a.rel="noopener noreferrer";}else a.setAttribute("aria-disabled","true");
  return a;
}
function copyLine(text,label){const c=el("code","dsv-url",text);c.dataset.copy="";c.dataset.copyLabel=label||"link";return c;}
function step(n,title,state){
  const li=el("li","dsb-step s-"+state);li.append(el("span","dsb-num",state==="done"?"✓":String(n)));
  const main=el("div","dsb-step-main");main.append(el("b",null,title));li.append(main);return {li,main};
}

export function mountDeveloperPulls({api,host,getProject,status,openTool}){
  const root=host.querySelector("#dsReviewRoot");if(!root)return null;
  const box=el("section","dsb dsv");box.setAttribute("aria-label","Ask for a review");root.append(box);
  let st=null,pv=null,result=null,fallback=null,ck=null,detail=null,busy=false,checking=false,notice=null,osSel=null;
  let title="",body="",base="",draft=true;
  const say=(text,bad)=>{notice={text,bad};if(status)status(text,bad);};
  const project=()=>getProject?.()?.project||null;
  const site=()=>NAMES[st?.target?.provider]||"the website";
  const kind=()=>st?.target?.provider==="gitlab"?"merge request":"pull request";

  async function load(){
    const p=project();
    if(!p){st=null;draw();return;}
    try{st=await api(BASE+"/status?project="+encodeURIComponent(p));}catch(e){st={state:"error",error:{message:e.message}};}
    if(!osSel)osSel=st?.os||"windows";
    if(!base&&st?.base)base=st.base;
    draw();
    if(st?.shared&&!ck)void doChecks();
  }
  async function act(fn){
    if(busy)return;busy=true;notice=null;draw();
    try{await fn();}catch(e){say(e.message||"Something went wrong.",true);}
    finally{busy=false;draw();}
  }

  // ---- step 1: the shared branch
  function stepBranch(){
    const s=step(1,"Your shared branch",st.shared?"done":"now");
    if(st.state==="no_target"||!st.target){
      s.main.append(el("p","dsb-hint","Share your work first. Then you can ask someone to look at it."));
      s.main.append(btn("Open Share to GitHub or GitLab","primary",()=>openTool?.("share")));return s.li;
    }
    s.main.append(el("p","dsb-hint",(st.branch||"?")+" on "+st.target.repo+" ("+site()+")"));
    if(st.error){
      s.main.append(el("p","dsa-alert bad",st.error.message));
      const bar=el("div","dsa-bar");
      if(["auth","expired","classic_token","scope"].includes(st.error.code))bar.append(btn("Connect again","sm",()=>openTool?.("account")));
      bar.append(btn("Ask for a review yourself","sm",()=>doFallback(st.error.code)));s.main.append(bar);
    }else if(!st.shared){
      s.main.append(el("p","dsb-hint",(st.branch||"This branch")+" isn't on "+site()+" yet. Share it first."));
      s.main.append(btn("Open Share to GitHub or GitLab","primary sm",()=>openTool?.("share")));
    }else if(st.state==="same_as_base"){
      s.main.append(el("p","dsb-hint","This is the main branch. Share your work as a new branch to ask for a review."));
    }
    return s.li;
  }
  // ---- step 2: write it
  function stepWrite(){
    const review=result?.review||st.review;
    const ready=st.state==="ready"||st.state==="review_open";
    const s=step(2,"Write the request",review||pv?"done":ready?"now":"later");
    if(review){s.main.append(el("p","dsb-hint","Already open: #"+review.number+" “"+review.title+"”"+(review.draft?" (draft)":"")));return s.li;}
    if(!ready){s.main.append(el("p","dsb-hint","A short title and a description, written for you from your checkpoints."));return s.li;}
    if(!pv){
      s.main.append(el("p","dsb-hint","We'll write a title and description from your checkpoints. You can change every word. Nothing is sent yet."));
      const b=btn("Write it for me","primary",()=>doPreview());b.disabled=busy;s.main.append(b);return s.li;
    }
    s.main.append(el("p","dss-summary",pv.summary));
    s.main.append(el("p","dsv-note",pv.prefilled_note));
    const form=el("div","dss-pick dsv-form");
    const lt=el("label","dss-field");lt.append(el("span",null,"Title"));
    const ti=el("input");ti.value=title;ti.maxLength=250;ti.spellcheck=true;ti.oninput=()=>{title=ti.value;};lt.append(ti);
    const lb=el("label","dss-field");lb.append(el("span",null,"Description"));
    const ta=el("textarea","dsv-body");ta.value=body;ta.rows=7;ta.maxLength=20000;ta.oninput=()=>{body=ta.value;};lb.append(ta);
    const lbase=el("label","dss-field");lbase.append(el("span",null,"Into branch"));
    const bi=el("input");bi.value=base;bi.maxLength=100;bi.autocomplete="off";bi.spellcheck=false;bi.onchange=()=>{base=bi.value.trim();pv=null;draw();};lbase.append(bi);
    const ld=el("label","dsv-check");const cb=el("input");cb.type="checkbox";cb.checked=draft;cb.onchange=()=>{draft=cb.checked;};
    ld.append(cb,el("span",null,"Open as a draft (recommended: nobody can merge it by accident)"));
    form.append(lt,lb,lbase,ld);s.main.append(form);
    return s.li;
  }
  // ---- step 3: ask
  function stepAsk(){
    const review=result?.review||st.review;
    const s=step(3,"Ask for a review",review?"done":pv?"now":"later");
    if(review){
      s.main.append(el("p","dss-ok","✓ "+(result?.message||("Review #"+review.number+" is open on "+site()+"."))));
      const bar=el("div","dsa-bar");bar.append(extLink(review.url,"Open #"+review.number+" on "+site()));s.main.append(bar);
      if(safeUrl(review.url))s.main.append(copyLine(review.url,"review link"));
      s.main.append(el("p","dsb-hint",BRAND()+" never merges. The reviewer decides on "+site()+"."));
      return s.li;
    }
    const need=pv?.need_scope||st.need_scope;
    if(need&&st.target?.provider==="gitlab"){
      const c=el("div","dsv-scope");c.append(el("b",null,"GitLab needs one more permission"),el("p",null,need.why));
      const ol=el("ol","dss-steps");for(const t of need.steps)ol.append(el("li",null,t));c.append(ol);
      const pre=el("pre","dss-cmd");pre.append(el("code",null,need.url));c.append(pre);
      const bar=el("div","dsa-bar");bar.append(extLink(need.url,"Open GitLab token page"),btn("Connect again","sm",()=>openTool?.("account")),btn("Do it on GitLab instead","sm",()=>doFallback("scope_api")));
      c.append(bar);s.main.append(c);
    }
    s.main.append(el("p","dsb-hint",pv?"You'll see the exact text before anything is sent.":"Write the request first."));
    const go=btn("Ask for a review","primary",()=>doOpen());go.disabled=busy||!pv||title.trim().length<3||!!(need&&st.target?.provider==="gitlab");
    s.main.append(go);
    return s.li;
  }
  // ---- step 4: checks (read-only), in the same ring card as Run my app
  function stepChecks(){
    const s=step(4,"Checks on "+site(),!st.shared?"later":ck?.state==="passed"?"done":"now");
    if(!st.shared){s.main.append(el("p","dsb-hint","After you share, see whether "+site()+"'s automatic checks passed. Read-only: nothing is re-run."));return s.li;}
    s.main.append(el("p","dsb-hint","Read-only. "+BRAND()+" only looks; it never re-runs or changes anything on "+site()+"."));
    const b=btn(checking?"Checking…":ck?"Check again":"Check now",ck?"":"primary",()=>doChecks());b.classList.add("dsb-check-btn");b.disabled=checking;
    if(!ck){s.main.append(b);return s.li;}
    const tone=checking?"busy":TONE[ck.state]||"idle";
    const card=el("div","dsb-check t-"+tone);
    card.append(ring(ck.state==="running"||checking?null:ck.passed,ck.state==="running"||checking?0:ck.total,tone,tone==="ok"?"✓":tone==="bad"?"!":tone==="busy"?"…":"–"));
    const text=el("div","dsb-check-text");text.append(el("b",null,ck.title),el("p",null,ck.text));
    if(ck.failing_names?.length){const ul=el("ul","dsb-broken");for(const x of ck.failing_names.slice(0,6))ul.append(el("li",null,x));text.append(ul);}
    card.append(text,b);s.main.append(card);
    if(ck.error&&["auth","expired","classic_token"].includes(ck.error.code))s.main.append(btn("Connect again","sm",()=>openTool?.("account")));
    const items=(ck.items||[]).filter(i=>i.state!=="passed"&&i.state!=="skipped").slice(0,12);
    if(items.length){
      const ul=el("ul","dsv-items");ul.setAttribute("aria-label","Checks that need a look");
      for(const i of items){
        const li=el("li","st-"+i.state);
        li.append(el("span","dsv-state",i.state==="failed"?"✗":i.state==="warning"?"⚠":"…"),el("span","dsv-name",i.name));
        if(i.note)li.append(el("small",null,i.note));
        if(i.external_host&&!i.url)li.append(el("small",null,"reported by "+i.external_host));
        const bar=el("span","dsv-acts");
        if(i.id&&i.state==="failed")bar.append(btn("What it said","sm",()=>doDetails(i)));
        if(i.url)bar.append(extLink(i.url,"Open"));
        li.append(bar);ul.append(li);
      }
      s.main.append(ul);
    }
    if(detail){
      const d=el("div","dsv-detail");d.append(el("b",null,detail.name||"What the check said"));
      d.append(el("p","dsb-hint","This text comes from the website. It's shown as plain text and never run."));
      const pre=el("pre","dss-log dsv-log");pre.append(el("code",null,detail.text));d.append(pre);
      const bar=el("div","dsa-bar");if(detail.url)bar.append(extLink(detail.url,"Full log on "+site()));bar.append(btn("Close","sm",()=>{detail=null;draw();}));d.append(bar);
      s.main.append(d);
    }
    if(ck.web_url){const bar=el("div","dsa-bar");bar.append(extLink(ck.web_url,"Open checks on "+site()));s.main.append(bar);}
    if(ck.truncated)s.main.append(el("p","dsb-hint","Showing the first 100. Open the website to see the rest."));
    return s.li;
  }
  // ---- fallback: do it yourself, every command copyable
  function fallbackCard(){
    const fb=fallback;const c=el("div","dss-fallback");c.setAttribute("role","region");c.setAttribute("aria-label","Ask for a review yourself");
    c.append(el("h4",null,fb.headline),el("p",null,fb.explain));
    if(fb.detail){const d=el("details","dss-detail");d.append(el("summary",null,"What "+site()+" said"));d.append(el("pre","dss-log",fb.detail));c.append(d);}
    const tabs=el("div","dss-os");tabs.setAttribute("role","group");tabs.setAttribute("aria-label","Your computer");
    for(const [k,label] of OSES){const b=btn(label,"sm",()=>{osSel=k;draw();});b.setAttribute("aria-pressed",String(osSel===k));tabs.append(b);}
    c.append(tabs);
    const ol=el("ol","dss-steps");
    for(const s of fb.steps[osSel]||fb.steps[fb.os_default]||[]){
      const li=el("li");li.append(el("p",null,s.title));
      if(s.cmd){const pre=el("pre","dss-cmd");pre.append(el("code",null,s.cmd));li.append(pre);}
      if(s.link)li.append(extLink(s.link.url,s.link.label));
      if(s.action==="signin")li.append(btn("Connect again","sm",()=>openTool?.("account")));
      if(s.action==="share")li.append(btn("Open Share to GitHub or GitLab","sm",()=>openTool?.("share")));
      ol.append(li);
    }
    c.append(ol);
    c.append(el("p","dsb-hint","Never paste your token into a terminal or a file."));
    c.append(btn("Close","sm",()=>{fallback=null;draw();}));
    return c;
  }

  async function doPreview(){
    await act(async()=>{
      result=null;fallback=null;
      const r=await api(BASE+"/preview",{project:project(),branch:st.branch||null,base:base||null});
      if(r.ok===false){fallback=r.fallback;say(r.fallback.headline,true);return;}
      pv=r;title=r.title;body=r.body;base=r.base;draft=true;
      if(r.existing){st.review=r.existing;st.state="review_open";}
    });
  }
  async function doOpen(){
    if(!pv)return;
    const t=title.trim();
    const lines=["Ask for a review on "+site()+"?","",(draft?"Draft ":"")+kind()+": "+pv.branch+" → "+base+" ("+pv.repo+")","","Title: "+t,"","Description:",body.length>600?body.slice(0,600)+"…":body,"",
      "Only this is sent. Nothing is merged."];
    if(!window.confirm(lines.join("\n")))return;
    await act(async()=>{
      const r=await api(BASE+"/open",{project:project(),branch:pv.branch,base,title:t,body,draft,action_sha256:pv.action_sha256,confirmed:true});
      if(r.ok){result=r;fallback=null;say(r.message);pv=null;await load();}
      else{fallback=r.fallback;say(r.fallback.headline,true);pv=null;}
    });
  }
  async function doChecks(){
    if(checking)return;checking=true;draw();
    try{ck=await api(BASE+"/checks?project="+encodeURIComponent(project())+(st?.branch?"&branch="+encodeURIComponent(st.branch):""));detail=null;}
    catch(e){ck={state:"error",title:"Couldn't read the checks",text:e.message,passed:0,total:0,items:[]};}
    finally{checking=false;draw();}
  }
  async function doDetails(i){
    await act(async()=>{detail=await api(BASE+"/details?project="+encodeURIComponent(project())+"&kind="+encodeURIComponent(i.kind)+"&id="+encodeURIComponent(i.id));});
  }
  async function doFallback(reason){
    await act(async()=>{const r=await api(BASE+"/fallback",{project:project(),branch:st?.branch||null,base:base||null,title,body,reason:reason||"manual"});fallback=r.fallback;});
  }

  function draw(){
    box.replaceChildren();
    const head=el("div","dsb-head");
    head.append(el("h3",null,"Ask for a review"),el("p","dsb-hint","Ask someone to look at your shared work, then see if the website's checks passed. Only your click sends anything."));
    box.append(head);
    if(!project()){box.append(el("p","dsb-hint","Open a project first."));return;}
    if(!st){box.append(el("p","dsb-hint","Loading…"));return;}
    if(st.state==="error"&&!st.target){box.append(el("p","dsa-alert bad",st.error?.message||"Something went wrong."));return;}
    if(notice)box.append(el("p","dsa-alert"+(notice.bad?" bad":""),notice.text));
    const ol=el("ol","dsb-steps");ol.append(stepBranch(),stepWrite(),stepAsk(),stepChecks());box.append(ol);
    if(fallback)box.append(fallbackCard());
    if(!fallback&&st.target){const more=btn("Ask for a review yourself (step-by-step)","link sm",()=>doFallback("manual"));more.disabled=busy;box.append(more);}
  }
  function BRAND(){return document.querySelector('meta[name="automoto-brand-short"]')?.content||"AutoMoto";}
  // Refresh whenever the card is opened (it lives inside Tools and is hidden otherwise).
  if("IntersectionObserver" in window){let seen=false;new IntersectionObserver(es=>{const v=es.some(e=>e.isIntersecting);if(v&&!seen)void load();seen=v;}).observe(root);}
  void load();
  return {projectChanged(){st=null;pv=null;result=null;fallback=null;ck=null;detail=null;title="";body="";base="";void load();},refresh:load};
}

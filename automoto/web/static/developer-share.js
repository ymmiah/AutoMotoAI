/* Share to GitHub or GitLab (V46-V48 plan, PR 3): guided steps Connect -> Pick where -> Check -> Share,
   plus Get latest, and a "share it yourself" fallback with a saved .patch and per-OS copyable steps.
   Everything from the website or from other people's checkpoints (repo names, commit messages, Git's
   answers) is untrusted: it is only ever put on the page with textContent, never as HTML.
   Nothing is stored in the browser; the engine keeps the token and never sends it here. */
const BASE="/api/developer/studio/remote";
const BRAND=document.querySelector('meta[name="automoto-brand-short"]')?.content||"AutoMoto";
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const btn=(text,cls,fn)=>{const b=el("button","btn "+(cls||""),text);b.type="button";if(fn)b.onclick=fn;return b;};
const NAMES={github:"GitHub",gitlab:"GitLab"};
const OSES=[["windows","Windows"],["macos","Mac"],["linux","Linux"]];
const safeUrl=u=>/^https:\/\/[^\s"<>]+$/.test(String(u||""))?u:null;
function extLink(url,label,cls){
  const ok=safeUrl(url);const a=el("a","btn "+(cls||"sm"),label+" ↗");
  if(ok){a.href=ok;a.target="_blank";a.rel="noopener noreferrer";}else a.setAttribute("aria-disabled","true");
  return a;
}
function step(n,title,state){
  const li=el("li","dsb-step s-"+state);li.append(el("span","dsb-num",state==="done"?"✓":String(n)));
  const main=el("div","dsb-step-main");main.append(el("b",null,title));li.append(main);return {li,main};
}

export function mountDeveloperShare({api,host,getProject,status,openTool}){
  const root=host.querySelector("#dsShareRoot");if(!root)return null;
  const box=el("section","dsb dss");box.setAttribute("aria-label","Share to GitHub or GitLab");root.append(box);
  let st=null,plan=null,result=null,fallback=null,latest=null,busy=false,notice=null,osSel=null,branch="",pickOpen=false,choice=null,repoText="";
  const say=(text,bad)=>{notice={text,bad};if(status)status(text,bad);};
  const project=()=>getProject?.()?.project||null;

  async function load(){
    const p=project();
    if(!p){st=null;draw();return;}
    try{st=await api(BASE+"/status?project="+encodeURIComponent(p));}catch(e){st={error:{message:e.message}};}
    if(!branch&&st?.branch)branch=st.branch;
    if(!osSel)osSel=st?.os||"windows";
    draw();
  }
  async function act(fn){
    if(busy)return;busy=true;notice=null;draw();
    try{await fn();}catch(e){say(e.message||"Something went wrong.",true);}
    finally{busy=false;draw();}
  }
  const accounts=()=>(st?.accounts||[]).filter(a=>a.status==="ok");
  const target=()=>st?.target||null;
  const siteName=()=>NAMES[target()?.provider]||"the website";

  // ---- step 1: connect
  function stepConnect(){
    const ok=accounts();
    const s=step(1,"Connect your account",ok.length?"done":"now");
    if(ok.length){
      s.main.append(el("p","dsb-hint",ok.map(a=>"@"+a.login+" on "+(NAMES[a.provider]||a.provider)+(a.host&&a.host!=="github.com"&&a.host!=="gitlab.com"?" ("+a.host+")":"")).join(" · ")));
    }else{
      s.main.append(el("p","dsb-hint","Sign in to GitHub or GitLab first. Your token stays in your computer's password store."));
      s.main.append(btn("Connect GitHub or GitLab","primary",()=>openTool?.("account")));
    }
    return s.li;
  }
  // ---- step 2: pick where
  function stepPick(){
    const t=target(),ok=accounts();
    const s=step(2,"Pick where to share",!ok.length?"later":t&&!pickOpen?"done":"now");
    if(!ok.length){s.main.append(el("p","dsb-hint","After you connect, pick the repository on the website."));return s.li;}
    if(t&&!pickOpen){
      s.main.append(el("p","dsb-hint",t.repo+" on "+(NAMES[t.provider]||t.provider)+" ("+t.host+")"));
      const row=el("div","dss-row");
      const lab=el("label","dss-field");lab.append(el("span",null,"Branch on "+(NAMES[t.provider]||"the website")));
      const inp=el("input");inp.value=branch;inp.maxLength=100;inp.autocomplete="off";inp.spellcheck=false;
      inp.oninput=()=>{branch=inp.value.trim();plan=null;};lab.append(inp);
      row.append(lab,btn("Change","sm",()=>{pickOpen=true;draw();}));
      s.main.append(row);
      return s.li;
    }
    const sugg=st?.suggestion;
    if(!choice){const a=ok.find(x=>sugg&&x.provider===sugg.provider&&x.host===sugg.host)||ok[0];choice=a.provider+"|"+a.host;}
    if(!repoText)repoText=t?.repo||(sugg?.allowed?sugg.repo:"")||"";
    const form=el("div","dss-pick");
    if(ok.length>1){
      const lab=el("label","dss-field");lab.append(el("span",null,"Account"));
      const sel=el("select");
      for(const a of ok){const o=el("option",null,"@"+a.login+" · "+(NAMES[a.provider]||a.provider)+" ("+a.host+")");o.value=a.provider+"|"+a.host;sel.append(o);}
      sel.value=choice;sel.onchange=()=>{choice=sel.value;};lab.append(sel);form.append(lab);
    }
    const lab=el("label","dss-field");lab.append(el("span",null,"Repository (owner/name, or paste its web address)"));
    const inp=el("input");inp.placeholder="for example ymmiah/AutoMotoAI";inp.value=repoText;inp.maxLength=400;inp.autocomplete="off";inp.spellcheck=false;
    inp.oninput=()=>{repoText=inp.value;};lab.append(inp);form.append(lab);
    if(sugg&&sugg.allowed&&sugg.repo)form.append(el("p","dsb-hint","Found in this project: "+sugg.repo+"."));
    const bar=el("div","dsa-bar");
    const use=btn("Use this repository","primary",()=>act(async()=>{
      const [provider,h]=choice.split("|");
      const r=await api(BASE+"/target",{project:project(),provider,host:h,repo:repoText});
      pickOpen=false;plan=null;fallback=null;result=null;await load();say("Sharing to "+r.repo+".");
    }));
    use.disabled=busy||!repoText.trim();bar.append(use);
    if(t)bar.append(btn("Cancel","",()=>{pickOpen=false;draw();}));
    form.append(bar);s.main.append(form);
    return s.li;
  }
  // ---- step 3: check
  function stepCheck(){
    const ready=accounts().length&&target()&&!pickOpen;
    const s=step(3,"Check what will be shared",!ready?"later":plan?(plan.ok?"done":"now"):"now");
    if(!ready){s.main.append(el("p","dsb-hint",BRAND+" looks for passwords, keys, .env files, huge files and automatic-job (CI) changes before anything is sent."));return s.li;}
    if(st?.refused){s.main.append(el("p","dsa-alert bad",st.refused.message));s.main.append(btn("Share it myself instead","",()=>doFallback("refused_config")));return s.li;}
    const go=btn(plan?"Check again":"Check now",plan?"":"primary",()=>doPlan());go.disabled=busy;
    if(!plan){s.main.append(el("p","dsb-hint",BRAND+" looks for passwords, keys, .env files, huge files and automatic-job (CI) changes. Nothing is sent yet."),go);return s.li;}
    s.main.append(el("p","dss-summary",plan.summary));
    if(plan.commits?.length){
      const ul=el("ul","dss-commits");
      for(const c of plan.commits.slice(0,20)){const li=el("li");li.append(el("code",null,c.short),el("span",null,c.subject),el("small",null,c.author));ul.append(li);}
      if(plan.commit_count>20)ul.append(el("li","dsb-hint","…and "+(plan.commit_count-20)+" more"));
      s.main.append(ul);
    }
    if(plan.files?.length){
      const d=el("details","dss-files");d.append(el("summary",null,plan.file_count+" file"+(plan.file_count===1?"":"s")+" changed"));
      const ul=el("ul");for(const f of plan.files.slice(0,200))ul.append(el("li",null,f.change+": "+f.path));d.append(ul);s.main.append(d);
    }
    if(plan.blocks?.length){
      const ul=el("ul","dss-blocks");ul.setAttribute("aria-label","Why it can't be shared yet");
      for(const b of plan.blocks)ul.append(el("li",null,b.message));
      s.main.append(ul);
      const bar=el("div","dsa-bar");
      if(plan.blocks.some(b=>b.rule==="non_ff"))bar.append(btn("Get latest","primary sm",()=>doFetch()));
      if(plan.blocks.some(b=>b.rule==="classic_token"||b.rule==="expired"||b.rule==="auth"))bar.append(btn("Connect again","sm",()=>openTool?.("account")));
      if(!plan.blocks.every(b=>b.rule==="nothing"))bar.append(btn("Share it myself instead","sm",()=>doFallback(firstReason())));
      s.main.append(bar);
    }else s.main.append(el("p","dss-ok","✓ No passwords, keys, .env files, huge files or CI changes found."));
    if(plan.warnings?.length){
      const ul=el("ul","dss-warns");for(const w of plan.warnings)ul.append(el("li",w.amber?"amber":null,w.message));s.main.append(ul);
      if(plan.suggest_branch)s.main.append(btn("Share as a new branch ("+plan.suggest_branch+")","sm",()=>{branch=plan.suggest_branch;doPlan();}));
    }
    s.main.append(go);
    return s.li;
  }
  function firstReason(){
    const r=(plan?.blocks||[]).map(b=>b.rule);
    if(r.includes("secret")||r.includes("secret_file"))return "secret";
    return r.find(x=>x!=="nothing")||"manual";
  }
  // ---- step 4: share
  function stepShare(){
    const ready=plan&&plan.ok;
    const s=step(4,"Share",result?.ok?"done":ready?"now":"later");
    if(result?.ok){
      s.main.append(el("p","dss-ok","✓ "+result.message));
      const bar=el("div","dsa-bar");
      if(result.links?.branch)bar.append(extLink(result.links.branch,"Open on "+siteName()));
      if(result.links?.review)bar.append(extLink(result.links.review,"Ask for a review"));
      s.main.append(bar);return s.li;
    }
    s.main.append(el("p","dsb-hint",ready?"Only your click sends anything. "+BRAND+" never force-pushes, so nobody's work is overwritten.":"Run the check first."));
    const go=btn(ready?"Share "+plan.commit_count+" checkpoint"+(plan.commit_count===1?"":"s"):"Share","primary",()=>doShare());
    go.disabled=busy||!ready;s.main.append(go);
    return s.li;
  }
  // ---- get latest
  function latestCard(){
    const t=target();if(!t||!accounts().length||pickOpen)return null;
    const c=el("div","dss-latest");
    c.append(el("b",null,"Get latest from "+siteName()));
    if(!latest){c.append(el("p","dsb-hint","See if anyone shared new checkpoints to "+(branch||"this branch")+". Nothing changes until you choose."));}
    else{
      c.append(el("p","dsb-hint",latest.message));
      if(latest.incoming?.length){
        const ul=el("ul","dss-commits");
        for(const x of latest.incoming.slice(0,10)){const li=el("li");li.append(el("code",null,x.short),el("span",null,x.subject),el("small",null,x.author));ul.append(li);}
        c.append(ul);
      }
    }
    const bar=el("div","dsa-bar");
    const f=btn(latest?"Look again":"Get latest","sm",()=>doFetch());f.disabled=busy;bar.append(f);
    if(latest?.incoming_count){
      if(latest.state==="fast_forward")bar.append(btn("Bring them in","primary sm",()=>doPull(false)));
      else bar.append(btn("Combine both","primary sm",()=>doPull(true)));
    }
    c.append(bar);return c;
  }
  // ---- fallback: share it yourself
  function fallbackCard(){
    const fb=fallback;const c=el("div","dss-fallback");c.setAttribute("role","region");c.setAttribute("aria-label","Share it yourself");
    c.append(el("h4",null,fb.headline),el("p",null,fb.explain));
    if(fb.detail){const d=el("details","dss-detail");d.append(el("summary",null,"What "+siteName()+" said"));d.append(el("pre","dss-log",fb.detail));c.append(d);}
    for(const f of [fb.patch,fb.bundle].filter(Boolean)){
      const line=el("div","dss-file");
      line.append(el("span",null,(f.kind==="bundle"?"Saved bundle (includes pictures and other binary files): ":"Saved patch: ")));
      const code=el("code",null,f.path);code.dataset.copy="";code.dataset.copyLabel="file location";line.append(code);c.append(line);
    }
    if(!fb.patch&&!fb.bundle&&fb.code!=="push_protection"&&fb.code!=="scan_blocked"&&fb.commit_count===0)c.append(el("p","dsb-hint","There were no new checkpoints to save."));
    const tabs=el("div","dss-os");tabs.setAttribute("role","group");tabs.setAttribute("aria-label","Your computer");
    for(const [k,label] of OSES){const b=btn(label,"sm",()=>{osSel=k;draw();});b.setAttribute("aria-pressed",String(osSel===k));tabs.append(b);}
    c.append(tabs);
    const ol=el("ol","dss-steps");
    for(const s of fb.steps[osSel]||fb.steps[fb.os_default]||[]){
      const li=el("li");li.append(el("p",null,s.title));
      if(s.cmd){const pre=el("pre","dss-cmd");pre.append(el("code",null,s.cmd));li.append(pre);}
      if(s.link)li.append(extLink(s.link.url,s.link.label));
      if(s.action){
        const map={signin:["Connect again",()=>openTool?.("account")],get_latest:["Get latest",()=>doFetch()],retry:["Try again",()=>{fallback=null;doPlan();}],new_branch:["Share as a new branch",()=>{branch=(plan?.suggest_branch)||("automoto/"+new Date().toISOString().slice(0,16).replace(/[-:T]/g,""));fallback=null;doPlan();}]};
        const m=map[s.action];if(m)li.append(btn(m[0],"sm",m[1]));
      }
      ol.append(li);
    }
    c.append(ol);
    c.append(el("p","dsb-hint","Never paste your token into a terminal or a file. Git asks you to sign in through your browser."));
    c.append(btn("Close","sm",()=>{fallback=null;draw();}));
    return c;
  }

  async function doPlan(){await act(async()=>{result=null;plan=await api(BASE+"/plan",{project:project(),remote_branch:branch||null});});}
  async function doShare(){
    if(!plan?.ok)return;
    const lines=[plan.summary,"",...plan.commits.slice(0,8).map(c=>"• "+c.short+"  "+c.subject),plan.commit_count>8?"• …and "+(plan.commit_count-8)+" more":"","",
      (plan.warnings||[]).filter(w=>w.amber).map(w=>"⚠ "+w.message).join("\n"),"Force-push is never used. Share now?"].filter(x=>x!=="");
    if(!window.confirm(lines.join("\n")))return;
    await act(async()=>{
      const r=await api(BASE+"/share",{project:project(),remote_branch:plan.remote_branch,action_sha256:plan.action_sha256,confirmed:true});
      if(r.ok){result=r;fallback=null;say(r.message);}
      else{fallback=r.fallback;result=null;say(r.fallback.headline,true);}
      plan=null;await load();
    });
  }
  async function doFallback(reason){await act(async()=>{const r=await api(BASE+"/fallback",{project:project(),remote_branch:branch||null,reason});fallback=r.fallback;});}
  async function doFetch(){await act(async()=>{latest=await api(BASE+"/fetch",{project:project(),remote_branch:branch||null});});}
  async function doPull(combine){
    if(!latest)return;
    const q=combine?"Combine the website's "+latest.incoming_count+" new checkpoint(s) with yours? This makes a new checkpoint.":"Bring in "+latest.incoming_count+" new checkpoint(s) from the website?";
    if(!window.confirm(q))return;
    await act(async()=>{
      const r=await api(BASE+"/pull",{project:project(),remote_branch:branch||null,expected:latest.expected,combine,confirmed:true});
      say(r.message,!r.ok);latest=null;plan=null;
    });
  }

  function draw(){
    box.replaceChildren();
    const head=el("div","dsb-head");
    head.append(el("h3",null,"Share to GitHub or GitLab"),el("p","dsb-hint","Send your checkpoints online in four steps. Only your click shares anything."));
    box.append(head);
    if(!project()){box.append(el("p","dsb-hint","Open a project first."));return;}
    if(!st){box.append(el("p","dsb-hint","Loading…"));return;}
    if(st.error){box.append(el("p","dsa-alert bad",st.error.message));box.append(btn("Share it myself instead","sm",()=>doFallback("manual")));if(fallback)box.append(fallbackCard());return;}
    if(notice)box.append(el("p","dsa-alert"+(notice.bad?" bad":""),notice.text));
    const ol=el("ol","dsb-steps");ol.append(stepConnect(),stepPick(),stepCheck(),stepShare());box.append(ol);
    if(fallback)box.append(fallbackCard());
    const lc=latestCard();if(lc)box.append(lc);
    if(!fallback&&st.has_commits){const more=btn("Share it myself (save a .patch file)","link sm",()=>doFallback("manual"));more.disabled=busy;box.append(more);}
  }
  void load();
  return {projectChanged(){plan=null;result=null;fallback=null;latest=null;branch="";pickOpen=false;choice=null;repoText="";void load();},refresh:load};
}

/* Connect GitHub or GitLab (V46-V48 plan, PR 2): beginner guided steps for signing in with a
   fine-grained personal access token. The token goes straight to the engine, which keeps it only in
   the OS keychain (or in memory for this session when there is none). This page never stores it:
   no localStorage or sessionStorage, the field is cleared the moment Connect is pressed, and the
   engine only ever answers with a masked handle such as "ends in 4f2a". */
const BASE="/api/developer/studio/account";
const BRAND=document.querySelector('meta[name="automoto-brand-short"]')?.content||"AutoMoto";
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const btn=(text,cls,fn)=>{const b=el("button","btn "+(cls||""),text);b.type="button";if(fn)b.onclick=fn;return b;};
const NAMES={github:"GitHub",gitlab:"GitLab"};
const fmtDate=iso=>{try{return new Date(iso).toLocaleDateString(undefined,{day:"numeric",month:"short",year:"numeric"});}catch{return iso;}};

function linkLine(url,label){
  const line=el("span","copy-line dsa-url");
  const code=el("code",null,url);code.dataset.copy="";code.dataset.copyLabel=label;
  line.append(code);return line;
}
function step(n,title,state){
  const li=el("li","dsb-step s-"+state);li.append(el("span","dsb-num",state==="done"?"✓":String(n)));
  const main=el("div","dsb-step-main");main.append(el("b",null,title));li.append(main);return {li,main};
}

export function mountDeveloperAccount({api,host,status}){
  const root=host.querySelector("#dsAccountRoot");if(!root)return null;
  const box=el("section","dsb dsa");box.setAttribute("aria-label","Connect GitHub or GitLab");root.append(box);
  let st=null,provider="github",glHost="gitlab.com",busy=false,notice=null,hiddenEnv=new Set(),flow=null,addOpen=false,moreOpen=false,lastRevoke=null;
  const say=(text,bad)=>{notice={text,bad};draw();if(status)status(text,bad);};

  async function load(){
    try{st=await api(BASE+"/status");}catch(e){st={error:e.message};}
    draw();
  }
  async function act(fn){
    if(busy)return;busy=true;draw();
    try{await fn();}catch(e){say(e.message||"Something went wrong.",true);}
    finally{busy=false;await load();}
  }
  const kc=()=>st?.keychain||{};
  const where=()=>kc().available?kc().label:"memory only, until "+BRAND+" closes";

  function accountCard(a){
    const card=el("article","dsa-acct"+(a.status!=="ok"?" off":(a.warnings||[]).some(w=>w.level==="high")?" warn":""));
    const top=el("div","dsa-acct-top");
    const av=el("span","dsa-av",(a.login||"?").charAt(0).toUpperCase());av.setAttribute("aria-hidden","true");
    const who=el("div","dsa-who");
    who.append(el("b",null,a.status==="ok"?"Connected as @"+a.login:"@"+a.login+" needs a new token"),el("span",null,a.provider_name+" · "+a.host));
    top.append(av,who);card.append(top);
    if(a.status==="expired")card.append(el("p","dsa-alert bad","Your token stopped working (it expired or was deleted). Make a new one in the steps below and paste it in."));
    const dl=el("dl","dsa-facts");
    const row=(k,v,cls)=>{dl.append(el("dt",null,k));const d=el("dd",cls||null);if(v instanceof Node)d.append(v);else d.textContent=v;dl.append(d);};
    row("Ends",a.expires_at?fmtDate(a.expires_at)+(a.days_left!=null&&a.days_left>=0?" ("+a.days_left+" day"+(a.days_left===1?"":"s")+" left)":""):"Never (not recommended)",a.expires_at?null:"bad");
    if(a.scopes?.length){const p=el("span","dsa-pills");for(const s of a.scopes)p.append(el("span","dsa-pill",s));row("Access",p);}
    else row("Access",a.permissions_note||"Set on "+a.provider_name);
    row("Saved in",a.storage==="keychain"?(kc().label||"your password store"):"This session only (until "+BRAND+" closes)");
    row("Token",a.handle||"saved");
    card.append(dl);
    if(a.warnings?.length){const ul=el("ul","dsa-warn");for(const w of a.warnings){const li=el("li","w-"+w.level,w.text);ul.append(li);}card.append(ul);}
    const bar=el("div","dsa-bar");
    const chk=btn("Check again","",()=>act(async()=>{await api(BASE+"/check",{provider:a.provider,host:a.host});say("Your "+a.provider_name+" sign-in still works.");}));
    chk.disabled=busy||a.status!=="ok";
    const out=btn("Sign out","",()=>{if(!window.confirm("Sign out of "+a.provider_name+" ("+a.host+")?\n\nThe token is removed from this computer."))return;
      act(async()=>{const r=await api(BASE+"/signout",{provider:a.provider,host:a.host});lastRevoke={name:a.provider_name,...r.revoke};say("Signed out of "+a.provider_name+".");});});
    out.disabled=busy;bar.append(chk,out);card.append(bar);
    return card;
  }
  function revokeCard(){
    const c=el("div","dsa-revoke");
    c.append(el("b",null,"Turn the token off on "+lastRevoke.name+" too"),el("p","dsb-hint",lastRevoke.text),linkLine(lastRevoke.url,"tokens page address"));
    const a=el("a","btn sm","Open "+lastRevoke.name+" ↗");a.href=lastRevoke.url;a.target="_blank";a.rel="noopener noreferrer";
    const x=btn("Done","sm",()=>{lastRevoke=null;draw();});
    const bar=el("div","dsa-bar");bar.append(a,x);c.append(bar);return c;
  }
  function envCards(){
    const frag=document.createDocumentFragment();
    for(const t of (st.env_tokens||[]).filter(t=>!hiddenEnv.has(t.var))){
      const c=el("div","dsa-env");
      c.append(el("b",null,"Your "+t.provider_name+" token is saved in plain text"),
        el("p","dsb-hint",t.var+" is in "+t.where+". Anyone who can read that file can use it. Move it into "+(kc().available?kc().label:"memory for this session")+(t.can_remove&&kc().available?" and remove the line from the file.":".")));
      const bar=el("div","dsa-bar");
      const mv=btn(kc().available?"Move it to "+kc().label:"Use it for this session only","primary sm",()=>{
        if(!window.confirm("Move "+t.var+" into "+where()+"?"+(t.can_remove&&kc().available?"\n\nThe line is then deleted from "+t.where+".":"")))return;
        act(async()=>{const r=await api(BASE+"/migrate",{var:t.var,session_only:!kc().available});say(r.removed_from_file?"Moved. The plain-text line was removed.":(r.note||"Moved."));});});
      mv.disabled=busy;
      bar.append(mv,btn("Not now","sm",()=>{hiddenEnv.add(t.var);draw();}));c.append(bar);frag.append(c);
    }
    return frag;
  }
  function providerStep(){
    const s=step(1,"Choose where your code lives","done");
    const seg=el("div","dsa-seg");seg.setAttribute("role","group");seg.setAttribute("aria-label","Where your code lives");
    for(const id of ["github","gitlab"]){const b=btn(NAMES[id],"sm",()=>{provider=id;notice=null;draw();});b.setAttribute("aria-pressed",String(provider===id));seg.append(b);}
    s.main.append(seg);
    if(provider==="gitlab"){
      const row=el("div","dsa-host");
      const sel=el("select","input");sel.setAttribute("aria-label","GitLab server");
      for(const h of st.hosts?.gitlab||["gitlab.com"]){const o=el("option",null,h);o.value=h;o.selected=h===glHost;sel.append(o);}
      sel.onchange=()=>{glHost=sel.value;draw();};row.append(sel);
      if(glHost!=="gitlab.com")row.append(btn("Remove","sm",()=>{if(!window.confirm("Remove "+glHost+" from your allowed servers? Any sign-in there is removed too."))return;act(async()=>{await api(BASE+"/hosts",{action:"remove",host:glHost});glHost="gitlab.com";});}));
      s.main.append(row);
      const add=el("details","dsa-add");add.open=addOpen;add.ontoggle=()=>{addOpen=add.open;};
      add.append(el("summary",null,"Use your own GitLab server"));
      const f=el("form","dsa-host");const inp=el("input","input");inp.placeholder="gitlab.example.com";inp.setAttribute("aria-label","Your GitLab server address");inp.autocomplete="off";inp.spellcheck=false;
      const go=btn("Add server","sm");go.type="submit";f.append(inp,go);
      f.onsubmit=e=>{e.preventDefault();const v=inp.value.trim();if(!v)return;act(async()=>{const r=await api(BASE+"/hosts",{action:"add",host:v});glHost=r.gitlab.includes(v.toLowerCase())?v.toLowerCase():r.gitlab[r.gitlab.length-1];addOpen=false;say("Added "+glHost+". Tokens are only ever sent to servers on this list.");});};
      add.append(el("p","dsb-hint","https only. Tokens are only ever sent to servers on your list."),f);s.main.append(add);
    }
    return s.li;
  }
  function tokenStep(){
    const page=st.token_pages?.[provider==="github"?"github":"gitlab:"+glHost];
    const s=step(2,"Make a token on "+NAMES[provider],"now");if(!page)return s.li;
    s.main.append(el("p","dsb-hint","A token is like a key that only opens what you pick. This link fills in the least access "+BRAND+" needs:"));
    const ul=el("ul","dsa-perms");
    for(const [name,level,why] of page.permissions){const li=el("li");li.append(el("b",null,name),el("span","dsa-lvl",level),el("span",null,why));ul.append(li);}
    s.main.append(ul,el("p","dsb-hint dsa-never","Not needed: "+page.never.join(", ")+"."));
    const ol=el("ol","dsa-how");for(const t of page.steps)ol.append(el("li",null,t));s.main.append(ol);
    const a=el("a","btn primary dsa-open","Open the token page ↗");a.href=page.url;a.target="_blank";a.rel="noopener noreferrer";
    s.main.append(a,linkLine(page.url,"token page address"));
    if(provider==="github"&&st.flows?.github_device||provider==="gitlab"&&st.flows?.gitlab_pkce)s.main.append(browserSignIn());
    return s.li;
  }
  function browserSignIn(){
    const wrap=el("div","dsa-flow");
    if(flow?.user_code){
      wrap.append(el("p","dsb-hint","Enter this code on "+NAMES[provider]+":"));
      const code=el("pre","dsa-code",flow.user_code);wrap.append(code,el("p","dsb-hint dsa-never",flow.warning||""));
      const a=el("a","btn sm","Open "+NAMES[provider]+" ↗");a.href=flow.verification_uri;a.target="_blank";a.rel="noopener noreferrer";
      wrap.append(a,btn("Cancel","sm",()=>{flow=null;draw();}));return wrap;
    }
    if(flow?.authorize_url){wrap.append(el("p","dsb-hint","Finish signing in in your browser, then come back here."),btn("Cancel","sm",()=>{flow=null;draw();}));return wrap;}
    const b=btn("Or sign in with your browser","sm",()=>act(async()=>{
      const so=!kc().available;
      if(provider==="github"){flow=await api(BASE+"/device/start",{provider:"github"});poll("/device/poll",so);}
      else{flow=await api(BASE+"/pkce/start",{host:glHost});window.open(flow.authorize_url,"_blank","noopener,noreferrer");poll("/pkce/poll",so);}
    }));
    b.disabled=busy;wrap.append(b);return wrap;
  }
  function poll(path,so){
    const id=flow?.flow_id;if(!id)return;
    setTimeout(async()=>{
      if(flow?.flow_id!==id)return;
      try{const r=await api(BASE+path,{flow_id:id,session_only:so});
        if(r.status==="done"){flow=null;say("Connected as @"+r.account.login+".");await load();return;}
        poll(path,so);
      }catch(e){flow=null;say(e.message,true);}
    },Math.max(2,flow?.interval||2)*1000);
  }
  function pasteStep(){
    const s=step(3,"Paste it here","todo");
    const f=el("form","dsa-paste");f.autocomplete="off";
    const inp=el("input","input dsa-token");inp.type="password";inp.name="automoto-token";inp.autocomplete="off";inp.spellcheck=false;
    inp.setAttribute("autocapitalize","off");inp.setAttribute("autocorrect","off");inp.dataset.sensitive="";inp.dataset.lpignore="true";
    inp.placeholder=provider==="github"?"github_pat_…":"glpat-…";inp.setAttribute("aria-label","Your "+NAMES[provider]+" token");
    inp.addEventListener("input",()=>{s.li.className="dsb-step s-"+(inp.value?"now":"todo");});
    f.append(inp);
    let consent=null;
    if(!kc().available){
      const lab=el("label","dsa-consent");consent=el("input");consent.type="checkbox";
      lab.append(consent,el("span",null,"Keep me signed in until "+BRAND+" closes. This computer has no password store, so the token is kept in memory only and never saved to disk."));
      f.append(lab);
    }else f.append(el("p","dsb-hint","Saved only in "+kc().label+". Never in files, Git settings or this page."));
    const go=btn(busy?"Checking…":"Connect","primary");go.type="submit";go.disabled=busy;f.append(go);
    f.onsubmit=e=>{
      e.preventDefault();
      let t=inp.value;inp.value="";
      if(!t.trim()){say("Paste your token first.",true);return;}
      if(consent&&!consent.checked){say("Tick the box to keep the token for this session only.",true);return;}
      act(async()=>{const r=await api(BASE+"/token",{provider,host:provider==="github"?"github.com":glHost,token:t,session_only:!!consent});t="";
        moreOpen=false;say("Connected as @"+r.account.login+" on "+r.account.provider_name+".");});
      t="";
    };
    s.main.append(f);return s.li;
  }
  function draw(){
    box.replaceChildren();
    box.append(el("h3","dsb-h","Connect your account in 3 steps"),el("p","dsb-hint","So you can share your work later. Nothing is sent anywhere until you click."));
    if(!st){box.append(el("p","dsb-hint","Loading…"));return;}
    if(st.error){box.append(el("p","dsa-alert bad",st.error));return;}
    if(notice){const p=el("p","dsa-alert"+(notice.bad?" bad":" ok"),notice.text);p.setAttribute("role",notice.bad?"alert":"status");box.append(p);}
    box.append(envCards());
    if(lastRevoke)box.append(revokeCard());
    const accts=st.accounts||[];
    for(const a of accts)box.append(accountCard(a));
    const steps=el("ol","dsb-steps");steps.append(providerStep(),tokenStep(),pasteStep());
    if(accts.some(a=>a.status==="ok")){
      const more=el("details","dsa-more");more.open=moreOpen;more.ontoggle=()=>{moreOpen=more.open;};
      more.append(el("summary",null,"Connect another account"),steps);box.append(more);
      const all=btn("Sign out everywhere on this computer","sm dsa-all",()=>{if(!window.confirm("Remove every GitHub and GitLab sign-in from this computer?"))return;act(async()=>{await api(BASE+"/signout",{all:true});say("Signed out everywhere on this computer.");});});
      all.disabled=busy;box.append(all);
    }else box.append(steps);
    box.append(el("p","dsb-hint dsa-foot",kc().available?"Tokens are kept in "+kc().label+" and only sent to "+(provider==="github"?"github.com":glHost)+".":"No password store found on this computer, so sign-ins last until "+BRAND+" closes."));
  }
  draw();void load();
  return {refresh:load,getState:()=>st};
}

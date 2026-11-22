/* Developer Studio V41 + V44: real run and test results, and a live local preview.
   Nothing runs until you approve one exact command. Apps listen on 127.0.0.1 only,
   and every run has a Stop button. */
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const STATE={
  starting:["Starting…","b-no"],running:["Running","b-acc"],passed:["Passed","b-ok"],failed:["Failed","b-bad"],
  stopped:["Stopped","b-no"],exited:["Stopped by itself","b-no"],timed_out:["Time limit reached","b-bad"],
  blocked_exposed:["Blocked: not local","b-bad"],failed_to_start:["Could not start","b-bad"]
};
export function mountDeveloperRun({api,host,getProject,status,onTestResult}){
  const BASE="/api/developer/studio/run";
  const root=host.querySelector("#dsRunRoot");
  root.innerHTML='<section class="dsr" aria-label="Run and preview">'+
    '<div class="dsr-head"><div><h3>Run &amp; preview</h3><p class="dsr-note">Runs on this computer only, at 127.0.0.1. You approve each command and can stop it at any time.</p></div>'+
    '<span class="dsx-gap"></span><button type="button" class="btn sm" id="dsrRefresh">Refresh</button></div>'+
    '<div class="dsr-recipes" id="dsrRecipes" role="list"></div>'+
    '<div class="dsr-block" id="dsrApp" hidden></div>'+
    '<div class="dsr-block" id="dsrTests" hidden></div>'+
    '<p class="dsr-status" id="dsrStatus" role="status" aria-live="polite">Open a project to see how it runs.</p></section>';
  const $=id=>root.querySelector("#"+id);
  let recipes=[],trusted=false,loadedFor=null,seq=0;
  const runs={app:null,test:null};
  const listeners=new Set();
  const notify=()=>{for(const fn of listeners)try{fn();}catch(e){console.error(e);}};
  const say=(text,bad)=>{$("dsrStatus").textContent=text;$("dsrStatus").classList.toggle("bad",!!bad);};

  async function load(force=false){
    const p=getProject()?.project;
    if(!p){recipes=[];loadedFor=null;draw();say("Open a project to see how it runs.");return [];}
    if(!force&&loadedFor===p)return recipes;
    const id=++seq;
    try{
      const d=await api(BASE+"/detect?"+new URLSearchParams({project:p}));
      if(id!==seq)return recipes;
      recipes=(d.recipes||[]).slice().sort((a,b)=>(a.kind==="app"?0:1)-(b.kind==="app"?0:1));trusted=!!d.trusted;loadedFor=p;
      for(const r of d.runs||[])if(r.live&&!runs[r.kind])track(r);
      draw();notify();
      say(!recipes.length?"No start or test command found. Ask the assistant to set one up."
        :!trusted?"Allow changes for this project first. Then you can run it."
        :"Pick what to run. Nothing starts until you approve it.");
    }catch(e){if(id===seq){recipes=[];draw();say("Can't check this project: "+e.message,true);}}
    return recipes;
  }
  function draw(){
    const list=$("dsrRecipes");list.replaceChildren();
    for(const r of recipes){
      const row=el("div","dsr-recipe");row.setAttribute("role","listitem");
      const txt=el("div","dsr-recipe-t");
      txt.append(el("b",null,r.kind==="app"?"Run app · "+r.label:"Run tests · "+r.label),el("code",null,r.command));
      const busy=runs[r.kind]?.run?.live;
      const btn=el("button","btn sm"+(r.kind==="app"?" primary":""),r.kind==="app"?"▶ Run":"✓ Run tests");
      btn.type="button";btn.disabled=!r.available||!trusted||!!busy;
      btn.title=!r.available?(r.missing+" is not installed"):!trusted?"Allow changes first":busy?"Already running":"";
      btn.onclick=()=>void start(r);
      row.append(txt,el("span","dsx-gap"));
      if(!r.available)row.append(el("span","dsx-badge b-no",r.missing+" not installed"));
      row.append(btn);list.append(row);
    }
  }
  function pick(kind){return recipes.find(r=>r.kind===kind&&r.available)||recipes.find(r=>r.kind===kind)||null;}

  async function start(r){
    const p=getProject();if(!p?.project)return false;
    if(!trusted){say("Allow changes for this project first.",true);return false;}
    if(!r.available){say(r.missing+" is not installed on this computer.",true);return false;}
    const what=r.kind==="app"?"Start this app":"Run these tests";
    const where=r.kind==="app"?"\n\nIt runs on this computer only, at 127.0.0.1. Nobody else on your network can open it.":"";
    if(!window.confirm(what+" in "+p.name+"?\n\n"+r.command+where+"\n\nYou can stop it at any time."))return false;
    try{
      const run=await api(BASE+"/start",{project:p.project,recipe:r.id,command_sha256:r.command_sha256,approved:true});
      track(run);draw();
      say(r.kind==="app"?"Starting "+r.label+"…":"Running "+r.label+"…");
      return true;
    }catch(e){say("Didn't start: "+e.message,true);if(e.status===409)void load(true);return false;}
  }
  function track(run){
    const kind=run.kind;
    const box=$(kind==="app"?"dsrApp":"dsrTests");
    const st={run,since:0,box,log:null,timer:null,frameUrl:null};
    runs[kind]=st;
    box.hidden=false;box.replaceChildren();
    const head=el("div","dsr-runhead");
    const badge=el("span","dsx-badge");const title=el("b",null,kind==="app"?"App":"Tests");
    const cmd=el("code","dsr-cmd",run.label||run.command);
    const time=el("span","dsr-time");
    const stop=el("button","btn sm","Stop");stop.type="button";stop.onclick=()=>void stopRun(kind);
    head.append(title,badge,cmd,el("span","dsx-gap"),time,stop);
    box.append(head);
    if(kind==="test"){const s=el("div","dsr-summary");s.hidden=true;box.append(s);st.summary=s;}
    else{
      const pv=el("div","dsr-preview");pv.hidden=true;
      const bar=el("div","dsr-urlbar");
      const lock=el("span","dsr-lock","Local only");
      const url=el("code","dsr-url");
      const reload=el("button","btn sm","Reload");reload.type="button";
      const open=el("a","btn sm","Open in browser");open.target="_blank";open.rel="noopener noreferrer";
      bar.append(lock,url,el("span","dsx-gap"),reload,open);
      const frame=el("iframe","dsr-frame");frame.title="Live preview of your app";
      frame.setAttribute("sandbox","allow-scripts allow-forms allow-same-origin allow-popups allow-modals");
      frame.setAttribute("referrerpolicy","no-referrer");
      reload.onclick=()=>{if(st.frameUrl)frame.src=st.frameUrl;};
      pv.append(bar,frame);box.append(pv);
      Object.assign(st,{preview:pv,url,open,frame});
    }
    const details=el("details","dsr-logwrap");details.open=kind==="test";
    details.append(el("summary",null,"Output"));
    const log=el("pre","dsr-log");log.tabIndex=0;details.append(log);box.append(details);
    st.log=log;st.badge=badge;st.time=time;st.stop=stop;
    paint(st,run);
    poll(st);
  }
  function paint(st,run){
    st.run=run;
    const [label,cls]=STATE[run.status]||[run.status,"b-no"];
    st.badge.className="dsx-badge "+cls;st.badge.textContent=label;
    st.time.textContent=Math.round((run.elapsed_ms||0)/1000)+"s";
    st.stop.hidden=!run.live;
    if(run.output){
      st.log.append(document.createTextNode(run.output));
      const extra=st.log.textContent.length-60000;
      if(extra>0)st.log.textContent=st.log.textContent.slice(extra);
      st.log.scrollTop=st.log.scrollHeight;
    }
    if(typeof run.next==="number")st.since=run.next;
    if(run.kind==="app"){
      const url=run.preview_url;
      st.preview.hidden=!url;
      if(url&&st.frameUrl!==url){st.frameUrl=url;st.frame.src=url;st.url.textContent=url;st.open.href=url;say("Your app is running at "+url+". Only this computer can open it.");}
      if(!url&&st.frameUrl){st.frameUrl=null;st.frame.removeAttribute("src");}
    }else if(run.summary){
      const s=run.summary;st.summary.replaceChildren();st.summary.hidden=false;
      const chips=el("div","dsr-chips");
      chips.append(el("span","dsx-badge b-ok",s.passed+" passed"),el("span","dsx-badge "+(s.failed?"b-bad":"b-no"),s.failed+" failed"),el("span","dsx-badge b-no",s.skipped+" skipped"));
      if(!s.recognised&&!run.live)chips.append(el("span","dsr-note","Counts not recognised; see the output below."));
      st.summary.append(chips);
      if(s.failures?.length){
        const ul=el("ul","dsr-fails");
        for(const f of s.failures.slice(0,12))ul.append(el("li",null,f));
        st.summary.append(ul);
      }
    }
    if(run.reason)say(run.reason,run.status==="blocked_exposed"||run.status==="timed_out");
    notify();
  }
  function poll(st){
    clearTimeout(st.timer);
    st.timer=setTimeout(async()=>{
      const p=getProject()?.project;
      if(!p||runs[st.run.kind]!==st)return;
      try{
        const run=await api(BASE+"/status?"+new URLSearchParams({project:p,run_id:st.run.run_id,since:String(st.since)}));
        paint(st,run);
        if(run.live)poll(st);
        else finished(st,run);
      }catch(e){say("Lost track of the run: "+e.message,true);}
    },700);
  }
  function finished(st,run){
    draw();notify();
    if(run.kind==="test"){
      const s=run.summary||{};
      say(run.status==="passed"?"Tests passed: "+(s.passed||0)+" passed, "+(s.skipped||0)+" skipped."
        :run.status==="stopped"?"Tests stopped.":"Tests failed: "+(s.failed||0)+" failing. See the list above.",run.status==="failed");
      onTestResult?.({cmd:run.label||run.command,ok:run.status==="passed",done:true,output:run.output?st.log.textContent:st.log.textContent,summary:s,real:true});
    }else if(!run.reason){
      say(run.status==="stopped"?"App stopped.":"The app stopped by itself (exit code "+run.exit_code+"). Check the output.",run.status!=="stopped");
    }
  }
  async function stopRun(kind){
    const st=runs[kind];const p=getProject()?.project;if(!st||!p)return;
    st.stop.disabled=true;
    try{const run=await api(BASE+"/stop",{project:p,run_id:st.run.run_id});paint(st,run);finished(st,run);}
    catch(e){say("Couldn't stop it: "+e.message,true);}
    finally{st.stop.disabled=false;}
  }
  async function run(kind){
    await load(true);
    const r=pick(kind);
    if(!r)return null;
    return start(r);
  }
  $("dsrRefresh").addEventListener("click",()=>void load(true));
  return {
    load,run,pick,start,
    stop:kind=>stopRun(kind),
    onChange(fn){listeners.add(fn);return ()=>listeners.delete(fn);},
    getState:()=>({project:getProject(),recipes,trusted,
      app:runs.app?{...runs.app.run,log:runs.app.log?.textContent||""}:null,
      test:runs.test?{...runs.test.run,log:runs.test.log?.textContent||""}:null}),
    hasRecipe:async kind=>{await load();return !!pick(kind);},
    async projectChanged(){
      for(const k of ["app","test"]){const st=runs[k];if(st){clearTimeout(st.timer);st.box.hidden=true;st.box.replaceChildren();runs[k]=null;}}
      loadedFor=null;notify();await load(true);
    },
    async trustChanged(){await load(true);}
  };
}

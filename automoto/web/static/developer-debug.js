/* V42: step-by-step debugger (Python with debugpy, C/C++/Rust with GDB or LLDB), a crash explainer
   and a Python speed check. Nothing runs until the user presses Start and confirms. */
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const BASE="/api/developer/studio/debug";
const WORDS={running:["Running…","info"],stopped:["Paused","warn"],exited:["Finished","ok"],terminated:["Finished","ok"],
  stopped_by_user:["Stopped","idle"],adapter_crashed:["Debugger crashed","bad"],failed:["Couldn't start","bad"],timed_out:["Time limit reached","bad"],starting:["Starting…","info"]};
const REASONS={breakpoint:"It reached one of your stop points.",step:"It moved one step.",exception:"Your program hit an error.",
  pause:"You paused it.",entry:"It's at the very start.","function breakpoint":"It reached a function you asked to stop in."};

export function mountDeveloperDebug({api,host,getProject}){
  const root=host.querySelector("#dsDebugRoot");
  root.innerHTML='<section class="dsb dsd" aria-label="Find and fix bugs">'+
    '<h3 class="dsb-h">Find and fix bugs</h3>'+
    '<p class="dsb-hint">Run your program one step at a time, pause it on a line and see what every value is. Works with Python, and with C, C++ and Rust through GDB or LLDB.</p>'+
    '<ol class="dsb-steps">'+
      '<li class="dsb-step"><span class="dsb-num">1</span><div class="dsb-step-main"><b>What should run?</b>'+
        '<button id="dsDebugDetect" class="btn" type="button" disabled>Find programs</button>'+
        '<label class="dsd-field" hidden id="dsDebugPick"><span>Program</span><select id="dsDebugTarget"></select></label>'+
        '<div id="dsDebugTool" class="dsd-tool" aria-live="polite"></div></div></li>'+
      '<li class="dsb-step"><span class="dsb-num">2</span><div class="dsb-step-main"><b>Where should it pause? <span class="dsd-opt">(optional)</span></b>'+
        '<p class="dsb-hint">A stop point pauses the program on that line so you can look around. If it hits an error, it pauses there anyway.</p>'+
        '<div class="dsd-bp-add"><input id="dsDebugBpFile" placeholder="File, e.g. main.py" aria-label="File for the stop point">'+
        '<input id="dsDebugBpLine" type="number" min="1" placeholder="Line" aria-label="Line number"><button id="dsDebugBpAdd" class="btn sm" type="button">Add stop point</button></div>'+
        '<ul id="dsDebugBps" class="dsd-chips" aria-label="Stop points"></ul></div></li>'+
      '<li class="dsb-step"><span class="dsb-num">3</span><div class="dsb-step-main"><b>Start</b>'+
        '<button id="dsDebugStart" class="btn primary" type="button" disabled>Start debugging</button>'+
        '<p id="dsDebugStatus" class="dsb-hint" role="status" aria-live="polite">Open a project first.</p></div></li>'+
    '</ol>'+
    '<div id="dsDebugLive" class="dsd-live" hidden>'+
      '<div class="dsd-banner"><span id="dsDebugState" class="dsd-chip"></span><span id="dsDebugWhere" class="dsd-where"></span></div>'+
      '<div class="dsd-controls" role="toolbar" aria-label="Debugger controls">'+
        '<button class="btn sm primary" type="button" data-act="continue">Continue</button>'+
        '<button class="btn sm" type="button" data-act="next" title="Run the next line">Step over</button>'+
        '<button class="btn sm" type="button" data-act="stepIn" title="Go into the function on this line">Step into</button>'+
        '<button class="btn sm" type="button" data-act="stepOut" title="Finish this function">Step out</button>'+
        '<button class="btn sm" type="button" data-act="pause">Pause</button>'+
        '<button class="btn sm" type="button" id="dsDebugStop">Stop</button>'+
        '<button class="btn sm" type="button" id="dsDebugRestart" hidden>Restart</button></div>'+
      '<p id="dsDebugError" class="dsd-note t-bad" hidden></p>'+
      '<div class="dsd-grid">'+
        '<div class="dsd-box"><b>How it got here</b><ol id="dsDebugFrames" class="dsd-frames"></ol></div>'+
        '<div class="dsd-box"><b>Values right now</b><table class="dsd-vars"><tbody id="dsDebugVars"></tbody></table></div>'+
        '<div class="dsd-box"><b>Watch</b><p class="dsb-hint">Keep an eye on a name, like <code>total</code> or <code>user.name</code>.</p>'+
          '<div class="dsd-bp-add"><input id="dsDebugWatchIn" placeholder="Name to watch" aria-label="Name to watch"><button id="dsDebugWatchAdd" class="btn sm" type="button">Watch</button></div>'+
          '<ul id="dsDebugWatches" class="dsd-watch"></ul></div>'+
      '</div>'+
      '<details class="dsb-adv"><summary>Program output</summary><pre id="dsDebugOutput" class="ds-php-output" tabindex="0"></pre></details>'+
    '</div>'+
    '<h4 class="dsd-h">Explain a crash</h4>'+
    '<p class="dsb-hint">Paste the error or crash text. AutoMoto explains it and points to the line in your project. Nothing runs, and the text isn\'t saved.</p>'+
    '<textarea id="dsDebugCrash" class="dsd-crash" rows="5" placeholder="Paste the error here" aria-label="Crash or error text"></textarea>'+
    '<div class="dsd-bp-add"><input id="dsDebugCode" type="number" placeholder="Exit code (optional)" aria-label="Exit code"><button id="dsDebugExplain" class="btn" type="button" disabled>Explain this crash</button></div>'+
    '<div id="dsDebugCrashOut" aria-live="polite"></div>'+
    '<h4 class="dsd-h">Find what\'s slow (Python)</h4>'+
    '<p class="dsb-hint">Runs the Python program above once and shows which of your functions take the most time.</p>'+
    '<button id="dsDebugProfile" class="btn" type="button" disabled>Check speed</button>'+
    '<div id="dsDebugProfileOut" aria-live="polite"></div>'+
    '<details class="dsb-adv"><summary>Advanced details</summary><pre id="dsDebugRaw" class="ds-php-output" tabindex="0"></pre></details>'+
    '</section>';
  const $=id=>root.querySelector("#"+id);
  let found=null,session=null,timer=null,breakpoints=[],watches=[],busy=false;
  const raw=d=>{$("dsDebugRaw").textContent=JSON.stringify(d,null,2);};
  const chip=(text,tone)=>el("span","dsd-chip t-"+tone,text);
  function target(){return found?.targets.find(t=>t.path===$("dsDebugTarget").value)||null;}
  function debuggerFor(t){
    if(!found||!t)return null;
    const list=found.debuggers.filter(d=>d.kind===t.kind);
    return list.find(d=>d.status==="installed_not_executed")||list[0]||null;
  }
  function refresh(){
    const project=getProject()?.project;const t=target();const d=debuggerFor(t);
    $("dsDebugDetect").disabled=busy||!project;
    $("dsDebugExplain").disabled=!project;
    $("dsDebugStart").disabled=busy||!t||!d||d.status!=="installed_not_executed"||(session&&!["exited","terminated","stopped_by_user","adapter_crashed","failed","timed_out"].includes(session.status));
    const py=found?.debuggers.find(x=>x.name==="debugpy");
    $("dsDebugProfile").disabled=busy||!t||t.kind!=="python"||!py||py.status!=="installed_not_executed";
  }
  function showTool(){
    const box=$("dsDebugTool");box.replaceChildren();const t=target();const d=debuggerFor(t);
    if(!t)return;
    if(!$("dsDebugBpFile").value||found.targets.some(x=>x.path===$("dsDebugBpFile").value))$("dsDebugBpFile").value=t.kind==="python"?t.path:"";
    $("dsDebugBpFile").placeholder=t.kind==="python"?"File, e.g. main.py":"Source file, e.g. src/main.c";
    if(!d){box.append(el("p","dsd-note t-warn","No debugger is known for this kind of program yet."));return;}
    const line=el("p","dsd-meta");
    if(d.status==="installed_not_executed"){line.append(chip("Ready","ok")," Uses "+d.label+(d.needs?" ("+d.needs+")":"")+".");box.append(line);return;}
    line.append(chip("Not installed","bad")," "+d.label+" is needed. ");
    if(/^https?:\/\//.test(d.install_hint)){const a=el("a","dsb-link","Install guide ↗");a.href=d.install_hint;a.target="_blank";a.rel="noopener noreferrer";line.append(a);}
    else{const code=el("code","dsd-cmd",d.install_hint);code.dataset.copy=d.install_hint;code.dataset.copyLabel="command";line.append("Install it with ",code);}
    box.append(line);
  }
  function drawBps(){
    const ul=$("dsDebugBps");ul.replaceChildren();
    const results=session?.breakpoints||{};
    for(const [i,bp] of breakpoints.entries()){
      const li=el("li","dsd-bp");const state=(results[bp.path]||[]).find(r=>r.line===bp.line);
      li.append(el("span",null,bp.path+" : line "+bp.line));
      if(state&&session?.status!=="starting")li.append(chip(state.verified?"Set":"Not set","dsd-small t-"+(state.verified?"ok":"warn")));
      const x=el("button","btn sm dsd-x","×");x.type="button";x.setAttribute("aria-label","Remove stop point "+bp.path+" line "+bp.line);
      x.onclick=()=>{breakpoints.splice(i,1);drawBps();void syncBps(bp.path);};li.append(x);ul.append(li);
    }
  }
  async function syncBps(path){
    if(!session||session.status!=="stopped"&&session.status!=="running")return;
    try{const d=await api(BASE+"/breakpoints",{session_id:session.session_id,path,lines:breakpoints.filter(b=>b.path===path).map(b=>b.line)});draw(d);}catch(e){$("dsDebugStatus").textContent="Couldn't change stop points: "+e.message;}
  }
  async function detect(){
    const project=getProject()?.project;if(!project||busy)return;busy=true;refresh();
    $("dsDebugStatus").textContent="Looking for programs. Nothing runs.";
    try{
      found=await api(BASE+"/detect?project="+encodeURIComponent(project));raw(found);
      const sel=$("dsDebugTarget");sel.replaceChildren();
      for(const t of found.targets){const o=el("option",null,(t.kind==="python"?"Python: ":"Program: ")+t.path);o.value=t.path;sel.append(o);}
      $("dsDebugPick").hidden=!found.targets.length;
      $("dsDebugStatus").textContent=found.targets.length?"Pick a program, add stop points if you like, then press Start debugging.":
        "No Python files or built programs were found. Build your C, C++ or Rust program with debug info first (for example cargo build).";
      showTool();
    }catch(e){$("dsDebugStatus").textContent="Couldn't look for programs: "+e.message;}
    finally{busy=false;refresh();}
  }
  async function start(restart){
    const project=getProject()?.project;const t=target();const d=debuggerFor(t);
    if(!restart&&(!project||!t||!d))return;
    if(!getProject()?.trusted){$("dsDebugStatus").textContent="Allow changes for this project first (the switch at the top). Debugging runs your program.";return;}
    if(!window.confirm((restart?"Restart":"Run")+" "+(restart?session.target:t.path)+" in the debugger?\n\nYour program really runs on this computer, as you. It is not sandboxed. AutoMoto stops it when you press Stop or after 30 minutes."))return;
    busy=true;refresh();$("dsDebugStatus").textContent="Starting the debugger…";
    try{
      const s=restart?await api(BASE+"/restart",{session_id:session.session_id,confirmed:true}):
        await api(BASE+"/start",{project,debugger:d.name,target:t.path,expected_target_sha256:t.sha256,expected_executable:d.executable,
          expected_sha256:d.sha256,breakpoints,confirmed:true,accept_unsandboxed_execution:true});
      draw(s);$("dsDebugStatus").textContent="Debugging "+s.target+".";poll();
      if(watches.length&&!restart)void sendWatches();
    }catch(e){$("dsDebugStatus").textContent="Couldn't start: "+e.message;}
    finally{busy=false;refresh();}
  }
  function poll(){
    clearTimeout(timer);
    if(!session)return;
    const done=["exited","terminated","stopped_by_user","adapter_crashed","failed","timed_out"].includes(session.status);
    if(done)return;
    timer=setTimeout(async()=>{
      try{draw(await api(BASE+"/state?session_id="+encodeURIComponent(session.session_id)));}
      catch(e){$("dsDebugStatus").textContent=e.message;session=null;refresh();return;}
      poll();
    },session.status==="stopped"&&!session.stop?.inspecting?1500:600);
  }
  function draw(s){
    session=s;raw(s);$("dsDebugLive").hidden=false;
    const [label,tone]=WORDS[s.status]||[s.status,"idle"];
    const st=$("dsDebugState");st.className="dsd-chip t-"+tone;st.textContent=label;
    const top=s.frames?.[0];
    $("dsDebugWhere").textContent=s.status==="stopped"?(REASONS[s.stop?.reason]||"It paused.")+(top?" Now at "+(top.path||"?")+" line "+top.line+(top.name?" in "+top.name:"")+".":""):
      s.status==="exited"||s.status==="terminated"?"Your program finished"+(s.exit_code!=null?" with exit code "+s.exit_code:"")+".":"";
    const paused=s.status==="stopped",live=paused||s.status==="running";
    for(const b of root.querySelectorAll(".dsd-controls [data-act]"))b.disabled=b.dataset.act==="pause"?s.status!=="running":!paused;
    $("dsDebugStop").disabled=!live&&s.status!=="starting";
    $("dsDebugRestart").hidden=!s.restart_available;
    const err=$("dsDebugError");err.hidden=!s.error&&!s.exception;
    err.textContent=s.exception?("Error: "+(s.exception.id||"")+(s.exception.description?" – "+s.exception.description:"")):(s.error||"");
    const frames=$("dsDebugFrames");frames.replaceChildren();
    for(const f of s.frames||[]){const li=el("li",f.in_project?"in":"lib");li.append(el("b",null,f.name||"?"),el("span","dsd-meta"," "+(f.path||"(no source)")+(f.line?" : "+f.line:"")));frames.append(li);}
    if(!(s.frames||[]).length)frames.append(el("li","dsd-empty",paused?"Loading…":"Shows up when the program is paused."));
    const vars=$("dsDebugVars");vars.replaceChildren();
    for(const v of s.variables||[]){const tr=el("tr");tr.append(el("th",null,v.name),el("td",null,v.value));if(v.type)tr.title=v.type;vars.append(tr);}
    if(!(s.variables||[]).length){const tr=el("tr");tr.append(el("td","dsd-empty",paused?"No values here.":"Shows up when the program is paused."));vars.append(tr);}
    const ul=$("dsDebugWatches");ul.replaceChildren();
    for(const w of s.watches||[]){const li=el("li");li.append(el("b",null,w.expression),el("span",null," = "+(w.error?"(not available here)":w.value??"…")));
      const x=el("button","btn sm dsd-x","×");x.type="button";x.setAttribute("aria-label","Stop watching "+w.expression);
      x.onclick=()=>{watches=watches.filter(n=>n!==w.expression);void sendWatches();};li.append(x);ul.append(li);}
    $("dsDebugOutput").textContent=s.output||"";
    drawBps();refresh();
  }
  async function sendWatches(){
    if(!session){return;}
    try{draw(await api(BASE+"/watch",{session_id:session.session_id,expressions:watches}));}
    catch(e){$("dsDebugStatus").textContent="Can't watch that: "+e.message;watches.pop();}
  }
  async function control(action){
    if(!session)return;
    try{draw(await api(BASE+"/control",{session_id:session.session_id,action}));poll();}
    catch(e){$("dsDebugStatus").textContent=e.message;}
  }
  root.querySelector(".dsd-controls").addEventListener("click",e=>{const b=e.target.closest("[data-act]");if(b)void control(b.dataset.act);});
  $("dsDebugStop").onclick=async()=>{if(!session)return;try{draw(await api(BASE+"/stop",{session_id:session.session_id}));}catch(e){$("dsDebugStatus").textContent=e.message;}};
  $("dsDebugRestart").onclick=()=>void start(true);
  $("dsDebugDetect").onclick=()=>void detect();
  $("dsDebugTarget").onchange=()=>{showTool();refresh();};
  $("dsDebugStart").onclick=()=>void start(false);
  $("dsDebugBpAdd").onclick=()=>{
    const path=$("dsDebugBpFile").value.trim().replace(/^\.\//,"");const line=Number($("dsDebugBpLine").value);
    if(!path||!Number.isInteger(line)||line<1){$("dsDebugStatus").textContent="Type a file and a line number.";return;}
    if(!breakpoints.some(b=>b.path===path&&b.line===line))breakpoints.push({path,line});
    $("dsDebugBpLine").value="";drawBps();void syncBps(path);
  };
  $("dsDebugWatchAdd").onclick=()=>{const v=$("dsDebugWatchIn").value.trim();if(!v)return;if(!watches.includes(v))watches.push(v);$("dsDebugWatchIn").value="";void sendWatches();};
  $("dsDebugExplain").onclick=async()=>{
    const project=getProject()?.project;const text=$("dsDebugCrash").value;const out=$("dsDebugCrashOut");
    if(!project||!text.trim()){out.replaceChildren(el("p","dsd-note t-warn","Paste some error text first."));return;}
    const code=$("dsDebugCode").value.trim();
    try{
      const d=await api(BASE+"/crash",{project,text,exit_code:code===""?null:Number(code)});raw(d);
      const box=el("div","dsd-outcome");box.append(el("b",null,d.summary));
      if(d.first_project_frame){const p=el("p",null,"Look at ");p.append(el("code","dsd-cmd",d.first_project_frame.path+" line "+d.first_project_frame.line));box.append(p);}
      if(d.tips?.length){const ul=el("ul","dsd-tips");for(const t of d.tips)ul.append(el("li",null,t));box.append(ul);}
      if(d.frames?.length){const ol=el("ol","dsd-frames");for(const f of d.frames.slice(0,8)){const li=el("li",f.in_project?"in":"lib");li.append(el("b",null,f.function||"?"),el("span","dsd-meta"," "+(f.path||"")+(f.line?" : "+f.line:"")));ol.append(li);}box.append(ol);}
      out.replaceChildren(box);
    }catch(e){out.replaceChildren(el("p","dsd-note t-bad","Couldn't read that: "+e.message));}
  };
  $("dsDebugProfile").onclick=async()=>{
    const project=getProject()?.project;const t=target();const py=found?.debuggers.find(x=>x.name==="debugpy");const out=$("dsDebugProfileOut");
    if(!project||!t||!py)return;
    if(!getProject()?.trusted){out.replaceChildren(el("p","dsd-note t-warn","Allow changes for this project first (the switch at the top)."));return;}
    if(!window.confirm("Run "+t.path+" once to measure its speed?\n\nYour program really runs on this computer and is not sandboxed. It stops after 2 minutes."))return;
    busy=true;refresh();out.replaceChildren(el("p","dsb-hint","Measuring…"));
    try{
      const d=await api(BASE+"/profile",{project,target:t.path,expected_target_sha256:t.sha256,expected_executable:py.executable,expected_sha256:py.sha256,confirmed:true,accept_unsandboxed_execution:true});raw(d);
      const box=el("div","dsd-outcome");
      const rows=d.slowest_in_project.length?d.slowest_in_project:d.rows.slice(0,5);
      box.append(el("b",null,d.timed_out?"It took too long and was stopped.":rows.length?"Where the time goes":"Nothing measurable was found."));
      if(rows.length){const tb=el("table","dsd-vars");const body=el("tbody");
        for(const r of rows){const tr=el("tr");tr.append(el("th",null,r.function),el("td",null,(r.total_seconds??0).toFixed(3)+" s · "+r.calls+" call"+(r.calls===1?"":"s")+" · "+r.path+(r.line?":"+r.line:"")));body.append(tr);}
        tb.append(body);box.append(tb);}
      out.replaceChildren(box);
    }catch(e){out.replaceChildren(el("p","dsd-note t-bad","Couldn't measure: "+e.message));}
    finally{busy=false;refresh();}
  };
  return {projectChanged(){clearTimeout(timer);found=null;session=null;breakpoints=[];watches=[];$("dsDebugLive").hidden=true;$("dsDebugPick").hidden=true;$("dsDebugTool").replaceChildren();
    $("dsDebugCrashOut").replaceChildren();$("dsDebugProfileOut").replaceChildren();drawBps();
    $("dsDebugStatus").textContent=getProject()?.project?"Press Find programs to begin.":"Open a project first.";refresh();}};
}

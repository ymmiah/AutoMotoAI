/* Developer Studio simple views: chat-first by default, a two-pane editor on request,
   one searchable Tools & languages page, and the classic all-panels layout for experts.
   Nothing here runs code by itself: starter cards only fill the prompt, every task needs
   the trusted project and a confirmation, and Keep / Undo use the review checkpoint API. */
const BRAND=document.querySelector('meta[name="automoto-brand-short"]')?.content||"AutoMoto";
const VIEW_KEY="automoto.developer.view";
const VIEWS=new Set(["chat","editor","classic"]);
const READ=new Set(["read_file","list_dir","grep","search_files","project_inspect"]);
const WRITE=new Set(["write_file","edit_file"]);
const RUN=new Set(["run_command","run_shell"]);
const TEST_RE=/\b(test|tests|pytest|jest|vitest|mocha|unittest|go test|cargo test|dotnet test|gradlew? test|mvn test|phpunit|rspec)\b/i;
const STARTERS=[
  ["Explain project","How it works and how to run it","Inspect this workspace and explain its architecture and how to run it. Do not edit files."],
  ["Find & fix a bug","Track down a failing test","Investigate the most relevant failing test, fix the root cause and rerun focused tests. Summarise changes."],
  ["Improve code","Cleaner and more accessible","Review this project for maintainability and accessibility improvements. Make a focused change and run tests."],
  ["Add tests","Cover what matters","Identify an important untested behaviour, add focused regression tests and run them."]
];
const RUN_TESTS="Run this project's tests and summarise the results in plain language. Do not change any files.";
const RUN_APP="Start this app locally for a quick check: find its start command, run it briefly, report the local address or the error, then stop it. Do not change any files.";
// Tools & languages cards. "roots" are the existing panels each card opens; "tc" keys the
// path-only availability check in developer_review.TOOLCHAINS (no tc = built in).
const TOOLS=[
  ["typescript","TypeScript & JavaScript","Node scripts, type checks and tests","TS","#3178c6","web",["dsJavaScriptRoot"],"typescript"],
  ["frontend","Web pages","Accessibility and responsive preview","UI","#e44d8a","web",["dsFrontendRoot"],"javascript"],
  ["php","PHP & WordPress","Composer and WordPress checks","PHP","#7a86b8","web",["dsPhpRoot"],"php"],
  ["python","Python","Scripts, packages and tests","Py","#3b7bbf","data",["dsPythonRoot"],"python"],
  ["data","SQL & data","Queries, migrations and data files","SQL","#2fa39a","data",["dsDataRoot"],"sql"],
  ["science","R & Julia","Notebooks and reproducible analysis","R","#2f6fbf","data",["dsScienceRoot"],"science"],
  ["go","Go","Modules, workspaces and go test","Go","#00acd7","systems",["dsGoRoot"],"go"],
  ["rust","Rust","Cargo workspaces, build and test","Rs","#d06a3a","systems",["dsRustRoot"],"rust"],
  ["native","C & C++","CMake, compilers and tests","C++","#5e8ed6","systems",["dsNativeRoot"],"native"],
  ["jvm","Java & JVM","Maven, Gradle and Kotlin on the JVM","Jv","#e76f00","systems",["dsJvmRoot"],"jvm"],
  ["dotnet",".NET & C#","dotnet build and test","C#","#8a5cd6","systems",["dsDotnetRoot"],"dotnet"],
  ["android","Kotlin & Android","Gradle builds and the emulator","Kt","#a97bff","mobile",["dsAndroidRoot"],"android"],
  ["swift","Swift","Swift packages and Xcode projects","Sw","#f05138","mobile",["dsSwiftRoot"],"swift"],
  ["ios","iPhone apps","Build and send to Apple only when you say","iOS","#9aa3ad","mobile",["dsIosRoot"],"ios"],
  ["mobile","Flutter & React Native","Cross-platform app checks","Fl","#47c5fb","mobile",["dsMobileRoot"],"mobile"],
  ["shell","Shell & automation","Bash, PowerShell and CI scripts","$_","#4caf50","systems",["dsShellRoot"],"shell"],
  ["scripting","Ruby, Lua & Perl","Scripting languages and Groovy","Rb","#cc342d","systems",["dsScriptingRoot"],"scripting"],
  ["functional","Scala, F# & Clojure","Functional languages","λ","#dc322f","systems",["dsFunctionalRoot"],"functional"],
  ["beam","Elixir & Erlang","BEAM languages and Gleam","Ex","#6e4a7e","systems",["dsBeamRoot"],"beam"],
  ["logic","Haskell, OCaml & Prolog","Static checks and local tests","Hs","#5e5086","systems",["dsLogicRoot"],"logic"],
  ["legacy","Fortran, COBOL & more","Ada, Pascal and Assembly","For","#8d6e63","systems",["dsLegacyRoot"],"legacy"],
  ["wasm","WebAssembly","Inspect .wat and .wasm modules","Wa","#654ff0","web",["dsWasmRoot"],"wasm"],
  ["latex","LaTeX & papers","Thesis files, citations and PDF builds","TeX","#56a35b","writing",["dsLatexRoot","dsBibliographyRoot","dsTexBuildRoot"],"latex"],
  ["manuscripts","Typst & Quarto","Manuscripts and research packages","Ty","#239dad","writing",["dsManuscriptsRoot"],"typst"],
  ["language","Language detection","Which languages and frameworks a project uses","Aa","#7aa2ff","builtin",["dsLanguageRoot"],null],
  ["lsp","Language servers","Hover, definitions and diagnostics","LS","#7aa2ff","builtin",["dsLspRoot"],null],
  ["index","Search & outline","Find symbols and files across the project","⌕","#7aa2ff","builtin",["dsIndexRoot","dsNavigationRoot"],null],
  ["adapters","Build & debug adapters","Approved local build, test and debug tools","Db","#7aa2ff","builtin",["dsAdaptersRoot"],null],
  ["agent","Agent reviews & release plans","Send a review or readiness plan to the central agent",BRAND.charAt(0),"#7aa2ff","builtin",[".studio-agent-bridge"],null]
];
const CATS=[["all","All"],["installed","Installed"],["web","Web"],["mobile","Mobile"],["systems","Systems"],["data","Data & science"],["writing","Writing"],["builtin","Built in"]];

const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};

export function mountDeveloperSimple({api,host,workbench,getProject,openFile,afterFilesChanged,status}){
  const BASE="/api/developer/studio";
  const shell=host.querySelector(".ds-shell");
  const q=sel=>host.querySelector(sel);
  // Remember where moved nodes live so the classic layout can be restored exactly.
  const marks=new Map();
  function place(node,parent){
    if(!node||!parent)return;
    if(!marks.has(node)){const m=document.createComment("dsx");node.before(m);marks.set(node,m);}
    parent.append(node);
  }
  function restore(node){const m=marks.get(node);if(m&&node)m.before(node);}

  const root=el("div","dsx");root.id="dsxRoot";
  root.innerHTML=
    '<header class="dsx-head">'+
      '<h3 class="dsx-title">Developer</h3>'+
      '<div class="dsx-projwrap"><button type="button" class="dsx-pill" id="dsxProject" aria-haspopup="dialog" aria-expanded="false" aria-controls="dsxProjectPop"><span class="dsx-dot" aria-hidden="true"></span><span id="dsxProjectName">Choose a project</span><span class="dsx-caret" aria-hidden="true">▾</span></button>'+
      '<div class="dsx-pop" id="dsxProjectPop" role="dialog" aria-label="Choose project" hidden></div></div>'+
      '<button type="button" class="dsx-chip" id="dsxTrust" hidden></button>'+
      '<span class="dsx-switchwrap dsx-only-editor"><span id="dsxAllowLabel">Allow AI to edit</span><button type="button" role="switch" aria-checked="false" aria-labelledby="dsxAllowLabel" class="dsx-switch" id="dsxAllow"><span></span></button></span>'+
      '<span class="dsx-gap"></span>'+
      '<button type="button" class="btn sm dsx-only-editor" id="dsxRunApp">▶ Run app</button>'+
      '<button type="button" class="btn sm dsx-only-editor" id="dsxRunTests">✓ Run tests</button>'+
      '<button type="button" class="btn sm" id="dsxView" aria-pressed="false">Open in editor</button>'+
      '<button type="button" class="btn sm" id="dsxTools" aria-expanded="false" aria-controls="dsxToolsPage">⚙ Tools</button>'+
    '</header>'+
    '<div class="dsx-body" id="dsxBody">'+
      '<div class="dsx-editor" id="dsxEditor" aria-label="Files and editor"></div>'+
      '<section class="dsx-chat" id="dsxChat" aria-label="Coding assistant">'+
        '<div class="dsx-scroll" id="dsxScroll">'+
          '<div class="dsx-setup" id="dsxSetup" aria-label="Get started">'+
            '<p class="dsx-setup-lead">Three short steps. You can stop or undo at any time.</p>'+
            '<div class="dsx-steps">'+
              '<div class="dsx-step" id="dsxStep1"><span class="dsx-num">1</span><div><b>Open a project</b><p>Pick a folder. We only look; nothing changes yet.</p><button type="button" class="btn sm primary" id="dsxStepProject">Choose folder…</button></div></div>'+
              '<div class="dsx-step" id="dsxStep2"><span class="dsx-num">2</span><div><b>Allow changes</b><p>Let the assistant edit files here. Every change can be undone.</p><button type="button" class="btn sm" id="dsxStepTrust">Allow changes</button></div></div>'+
              '<div class="dsx-step" id="dsxStep3"><span class="dsx-num">3</span><div><b>Tell the AI what to do</b><p>“Fix a bug”, “Add tests”, “Explain this project”… in your own words.</p></div></div>'+
            '</div></div>'+
          '<h2 class="dsx-hero" id="dsxHero">What do you want to build or fix?</h2>'+
          '<div class="dsx-thread" id="dsxThread" role="log" aria-live="polite" aria-relevant="additions"></div>'+
        '</div>'+
        '<div class="dsx-dock">'+
          '<form class="dsx-composer" id="dsxComposer">'+
            '<label class="sr" for="dsxPrompt">Your request</label>'+
            '<textarea id="dsxPrompt" rows="2" maxlength="8000" placeholder="Describe it in your own words…"></textarea>'+
            '<div class="dsx-attached" id="dsxAttached"></div>'+
            '<div class="dsx-comp-row"><button type="button" class="dsx-mini" id="dsxAttach" title="Add a text file to your request">＋ Attach</button>'+
            '<input type="file" id="dsxFile" multiple hidden>'+
            '<span class="dsx-mini dsx-static" id="dsxCompProject"></span><span class="dsx-gap"></span>'+
            '<button type="button" class="btn sm" id="dsxStop" hidden>Stop</button>'+
            '<button type="submit" class="dsx-send" id="dsxSend" aria-label="Send request" disabled>↑</button></div>'+
          '</form>'+
          '<div class="dsx-starters" id="dsxStarters" aria-label="Suggested tasks"></div>'+
          '<p class="dsx-foot" id="dsxFoot">Picking a card only fills the box. Nothing runs until you press send.</p>'+
        '</div>'+
      '</section>'+
      '<aside class="dsx-review" id="dsxReview" aria-label="Review changes" hidden>'+
        '<div class="dsx-rtabs" role="tablist"><button type="button" role="tab" data-rtab="changes" class="on" aria-selected="true">Changes</button><button type="button" role="tab" data-rtab="files" aria-selected="false">Files</button><button type="button" role="tab" data-rtab="tests" aria-selected="false">Tests</button><span class="dsx-gap"></span><button type="button" class="dsx-x" id="dsxReviewClose" aria-label="Close review panel">✕</button></div>'+
        '<div class="dsx-rbody" id="dsxReviewBody"></div>'+
        '<div class="dsx-rfoot"><button type="button" class="btn sm primary" id="dsxRKeep">Keep</button><button type="button" class="btn sm" id="dsxRUndo">Undo</button><span class="dsx-gap"></span><button type="button" class="btn sm" id="dsxROpen">Open in editor</button></div>'+
      '</aside>'+
    '</div>'+
    '<section class="dsx-tools" id="dsxToolsPage" aria-label="Tools and languages" hidden>'+
      '<div class="dsx-tools-head"><div><h2>Tools &amp; languages</h2><p>Open a language when you need it. The assistant picks what it needs on its own.</p></div><span class="dsx-gap"></span><button type="button" class="btn sm" id="dsxToolsBack">Back</button></div>'+
      '<div class="dsx-tools-bar"><input type="search" class="input" id="dsxToolSearch" placeholder="Search languages and tools…" aria-label="Search languages and tools"><div class="dsx-cats" id="dsxCats" role="group" aria-label="Filter"></div></div>'+
      '<div class="dsx-detected" id="dsxDetected" hidden></div>'+
      '<div class="dsx-grid" id="dsxToolGrid"></div>'+
      '<div class="dsx-detail" id="dsxToolDetail" hidden><div class="dsx-detail-head"><button type="button" class="btn sm" id="dsxDetailBack">← All tools</button><h3 id="dsxDetailTitle"></h3></div><div id="dsxDetailBody"></div></div>'+
      '<div class="dsx-tools-foot"><span>Prefer every panel on one page?</span><button type="button" class="btn sm" id="dsxClassic">Show all panels (classic layout)</button></div>'+
    '</section>';
  const classicBar=el("div","dsx-classic-bar");
  classicBar.innerHTML='<span>Classic layout · every panel on one page.</span><button type="button" class="btn sm" id="dsxBackSimple">Back to simple view</button>';
  shell.before(root);shell.before(classicBar);
  const $=id=>root.querySelector("#"+id)||classicBar.querySelector("#"+id);
  const pageInner=host;pageInner.classList.add("dsx-page");
  host.querySelector(".studio-drop")?.setAttribute("hidden","");

  // Project picker: the existing toolbar lives in the pill's popover.
  place(q(".ds-toolbar"),$("dsxProjectPop"));
  place(q("#dsRootStrip"),$("dsxProjectPop"));
  const statusLine=q("#dsStatus");
  function togglePop(force){
    const pop=$("dsxProjectPop"),open=typeof force==="boolean"?force:pop.hidden;
    pop.hidden=!open;$("dsxProject").setAttribute("aria-expanded",String(open));
    if(open)(q("#dsPath")||pop).focus();
  }
  $("dsxProject").addEventListener("click",()=>togglePop());
  document.addEventListener("click",e=>{if(!root.isConnected)return;if(!e.target.closest?.(".dsx-projwrap,#dsxStepProject"))togglePop(false);});
  $("dsxProjectPop").addEventListener("keydown",e=>{if(e.key==="Escape"){togglePop(false);$("dsxProject").focus();}});
  const clickTrust=()=>q("#dsTrust")?.click();
  $("dsxTrust").addEventListener("click",clickTrust);
  $("dsxAllow").addEventListener("click",clickTrust);
  $("dsxStepProject").addEventListener("click",()=>togglePop(true));
  $("dsxStepTrust").addEventListener("click",clickTrust);

  // ---------------------------------------------------------------- views
  let view=VIEWS.has(localStorage.getItem(VIEW_KEY))?localStorage.getItem(VIEW_KEY):"chat";
  let toolsOpen=false;
  function setView(next,{save=true}={}){
    view=next;if(save)localStorage.setItem(VIEW_KEY,next);
    const classic=next==="classic";
    root.hidden=classic;classicBar.hidden=!classic;shell.hidden=!classic;
    pageInner.classList.toggle("dsx-classic",classic);
    root.dataset.view=next;
    if(classic){
      closeDetail();
      for(const node of marks.keys())restore(node);
      toolsOpen=false;
    }else{
      place(q(".ds-toolbar"),$("dsxProjectPop"));place(q("#dsRootStrip"),$("dsxProjectPop"));
      if(next==="editor"){place(q(".ds-columns"),$("dsxEditor"));place(statusLine,$("dsxEditor"));}
      else{restore(q(".ds-columns"));restore(statusLine);}
      $("dsxView").textContent=next==="editor"?"Back to chat":"Open in editor";
      $("dsxView").setAttribute("aria-pressed",String(next==="editor"));
      showTools(toolsOpen);
    }
    refresh();
  }
  $("dsxView").addEventListener("click",()=>setView(view==="editor"?"chat":"editor"));
  $("dsxBackSimple").addEventListener("click",()=>setView("chat"));
  $("dsxClassic").addEventListener("click",()=>{toolsOpen=false;setView("classic");});

  // ---------------------------------------------------------------- tools page
  let cat="all",toolchains=null,detected=null;
  const cats=$("dsxCats");
  for(const [id,label] of CATS){const b=el("button","dsx-cat",label);b.type="button";b.dataset.cat=id;b.setAttribute("aria-pressed",String(id===cat));cats.append(b);}
  cats.addEventListener("click",e=>{const b=e.target.closest("[data-cat]");if(!b)return;cat=b.dataset.cat;for(const x of cats.children)x.setAttribute("aria-pressed",String(x===b));drawTools();});
  $("dsxToolSearch").addEventListener("input",drawTools);
  function badge(t){
    if(!t[7])return ["Built in","b-acc"];
    const s=toolchains?.[t[7]];
    if(!s)return ["Checking…","b-no"];
    return s.installed?["Installed","b-ok"]:["Not installed","b-no"];
  }
  function drawTools(){
    const grid=$("dsxToolGrid");grid.replaceChildren();
    const term=$("dsxToolSearch").value.trim().toLowerCase();
    const want=new Set((detected?.keys)||[]);
    const items=TOOLS.filter(t=>{
      if(term&&!(t[1]+" "+t[2]).toLowerCase().includes(term))return false;
      if(cat==="installed")return !!(t[7]&&toolchains?.[t[7]]?.installed);
      return cat==="all"||t[5]===cat;
    }).sort((a,b)=>(want.has(b[0])?1:0)-(want.has(a[0])?1:0));
    for(const t of items){
      const [label,cls]=badge(t);
      const card=el("button","dsx-card");card.type="button";card.dataset.tool=t[0];
      if(want.has(t[0]))card.classList.add("suggested");
      const ic=el("span","dsx-ic",t[3]);ic.style.color=t[4];ic.style.background=t[4]+"22";
      const txt=el("span","dsx-card-t");txt.append(el("b",null,t[1]),el("span",null,t[2]));
      const foot=el("span","dsx-card-f");foot.append(el("span","dsx-badge "+cls,label),el("span","dsx-open",want.has(t[0])?"Suggested · Open":"Open"));
      const top=el("span","dsx-card-top");top.append(ic,txt);
      card.append(top,foot);card.addEventListener("click",()=>openDetail(t));grid.append(card);
    }
    if(!items.length)grid.append(el("p","dsx-empty","No tools match. Try another word."));
  }
  let detailNodes=[];
  function openDetail(t){
    closeDetail();
    $("dsxDetailTitle").textContent=t[1];
    const body=$("dsxDetailBody");
    for(const sel of t[6]){
      const node=sel.startsWith(".")?host.querySelector(sel):q("#"+sel);
      if(node){place(node,body);detailNodes.push(node);}
    }
    if(!detailNodes.length)body.append(el("p","dsx-empty","This panel is not available here."));
    $("dsxToolGrid").hidden=true;$("dsxDetected").hidden=true;root.querySelector(".dsx-tools-bar").hidden=true;
    $("dsxToolDetail").hidden=false;$("dsxDetailBack").focus();
  }
  function closeDetail(){
    for(const n of detailNodes)restore(n);detailNodes=[];
    $("dsxDetailBody").replaceChildren();
    $("dsxToolDetail").hidden=true;$("dsxToolGrid").hidden=false;root.querySelector(".dsx-tools-bar").hidden=false;
    $("dsxDetected").hidden=!detected;
  }
  $("dsxDetailBack").addEventListener("click",closeDetail);
  async function loadToolInfo(){
    try{toolchains=(await api(BASE+"/review/toolchains")).toolchains;}catch{toolchains={};}
    detected=null;
    const p=getProject();
    if(p?.project){
      try{
        const d=await api(BASE+"/language/detect",{project:p.project});
        const langs=[d.primary_language,...(d.project_languages||[]).map(x=>x.id)].filter(Boolean);
        const names=(d.frameworks||[]).map(f=>f.name||f).filter(Boolean);
        const keys=new Set();
        const map={typescript:"typescript",javascript:"typescript",python:"python",php:"php",go:"go",rust:"rust",c:"native",cpp:"native",java:"jvm",kotlin:"android",csharp:"dotnet",swift:"swift",dart:"mobile",ruby:"scripting",lua:"scripting",perl:"scripting",bash:"shell",powershell:"shell",sql:"data",r:"science",julia:"science",latex:"latex",bibtex:"latex",typst:"manuscripts",quarto:"manuscripts","wasm-text":"wasm",assembly:"legacy",html:"frontend",css:"frontend"};
        for(const l of langs)if(map[l])keys.add(map[l]);
        if(names.some(n=>/react|next|vue|svelte|angular/i.test(n)))keys.add("frontend");
        const pretty=id=>({typescript:"TypeScript",javascript:"JavaScript",python:"Python",csharp:"C#",cpp:"C++"})[id]||(id.charAt(0).toUpperCase()+id.slice(1));
        detected={keys:[...keys],text:d.primary_language?("This project uses "+pretty(d.primary_language)+(names.length?" with "+names.slice(0,3).join(", "):"")+"."):"No main language detected yet."};
      }catch{detected=null;}
    }
    const banner=$("dsxDetected");banner.replaceChildren();
    if(detected){banner.append(el("span","dsx-badge b-acc","Detected"),el("span",null,detected.text),el("span","dsx-gap"),el("span","dsx-muted","Nothing runs until you ask."));}
    banner.hidden=!detected;
    drawTools();
  }
  function showTools(open){
    toolsOpen=open;
    $("dsxToolsPage").hidden=!open;$("dsxBody").hidden=open;
    $("dsxTools").setAttribute("aria-expanded",String(open));
    if(!open)closeDetail();
  }
  $("dsxTools").addEventListener("click",()=>{showTools(!toolsOpen);if(toolsOpen){drawTools();void loadToolInfo();$("dsxToolSearch").focus();}});
  $("dsxToolsBack").addEventListener("click",()=>{showTools(false);$("dsxTools").focus();});

  // ---------------------------------------------------------------- composer
  const prompt=$("dsxPrompt"),send=$("dsxSend");
  for(const [title,sub,text] of STARTERS){
    const b=el("button","dsx-starter");b.type="button";b.dataset.prompt=text;
    b.append(el("b",null,title),el("span",null,sub));
    b.addEventListener("click",()=>{prompt.value=text;refresh();prompt.focus();});
    $("dsxStarters").append(b);
  }
  let attached=[];
  function drawAttached(){
    const box=$("dsxAttached");box.replaceChildren();
    attached.forEach((a,i)=>{const c=el("span","dsx-att",a.name);const x=el("button","dsx-att-x","✕");x.type="button";x.setAttribute("aria-label","Remove "+a.name);x.onclick=()=>{attached.splice(i,1);drawAttached();};c.append(x);box.append(c);});
  }
  async function addFiles(files){
    for(const f of [...files].slice(0,3)){
      if(f.size>64*1024){status("Attach skipped "+f.name+": larger than 64 KB.",true);continue;}
      const text=await f.text();
      if(text.includes("\u0000")){status("Attach skipped "+f.name+": not a text file.",true);continue;}
      if(attached.length>=3)break;
      attached.push({name:f.name,text});
    }
    drawAttached();
  }
  $("dsxAttach").addEventListener("click",()=>$("dsxFile").click());
  $("dsxFile").addEventListener("change",e=>{void addFiles(e.target.files);e.target.value="";});
  const comp=$("dsxComposer");
  comp.addEventListener("dragover",e=>{e.preventDefault();comp.classList.add("over");});
  comp.addEventListener("dragleave",()=>comp.classList.remove("over"));
  comp.addEventListener("drop",e=>{e.preventDefault();comp.classList.remove("over");if(e.dataTransfer?.files?.length)void addFiles(e.dataTransfer.files);});
  prompt.addEventListener("input",refresh);
  prompt.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){e.preventDefault();comp.requestSubmit();}});
  comp.addEventListener("submit",e=>{e.preventDefault();void submit(prompt.value);});
  $("dsxRunTests").addEventListener("click",()=>void submit(RUN_TESTS));
  $("dsxRunApp").addEventListener("click",()=>void submit(RUN_APP));
  $("dsxStop").addEventListener("click",async()=>{
    if(!window.confirm("Stop the current "+BRAND+" task?"))return;
    try{await workbench.cancelTask();}catch(err){status("Stop failed: "+err.message,true);}
  });

  // ---------------------------------------------------------------- task runs
  let turn=null;
  const thread=$("dsxThread");
  function scrollDown(){const s=$("dsxScroll");s.scrollTop=s.scrollHeight;}
  async function submit(text){
    const p=getProject();let note=String(text||"").trim();
    if(!p?.trusted||note.length<5||workbench.isBusy())return;
    if(attached.length)note+="\n\n"+attached.map(a=>"Attached file "+a.name+":\n```\n"+a.text+"\n```").join("\n\n");
    if(!window.confirm("Run one "+BRAND+" coding task in this project? The assistant may read, edit and test files. "+
      "Risky steps still ask you first, and you can keep or undo every change afterwards."))return;
    let checkpoint=null,checkpointError=null;
    try{checkpoint=(await api(BASE+"/review/start",{project:p.project})).checkpoint;}
    catch(err){checkpointError=err.message;}
    startTurn(String(text).trim(),checkpoint,checkpointError,p.project);
    const ok=await workbench.runTask(note,{confirmed:true});
    if(ok){prompt.value="";attached=[];drawAttached();}
    else if(turn&&!turn.done){finishTurn({message:"The task did not start.",kind:"error"});}
    refresh();
  }
  function startTurn(note,checkpoint,checkpointError,project){
    const user=el("div","dsx-msg user");user.append(el("div","dsx-bubble",note));
    const bot=el("div","dsx-msg bot");
    const av=el("span","dsx-av",BRAND.charAt(0));av.setAttribute("aria-hidden","true");
    const body=el("div","dsx-turn");bot.append(av,body);
    const card=el("div","dsx-progress");card.innerHTML='<div class="dsx-prog-head"><b>Working on it</b><span class="dsx-gap"></span><button type="button" class="btn sm dsx-prog-stop">Stop</button></div><div class="dsx-bar"><span></span></div><ol class="dsx-phases"></ol>';
    card.querySelector(".dsx-prog-stop").addEventListener("click",()=>$("dsxStop").click());
    body.append(card);thread.append(user,bot);
    turn={body,card,checkpoint,checkpointError,project,reads:new Set(),edits:new Map(),tests:new Map(),commands:new Map(),labels:[],done:false,changes:null,resolved:false};
    drawProgress();refresh();scrollDown();
  }
  function phaseState(){
    const t=turn,edited=t.edits.size,tests=[...t.tests.values()],ran=tests.filter(x=>x.done).length;
    const finished=t.done;
    const steps=[
      {label:"Planning",detail:t.reads.size?("Looked at "+t.reads.size+" file"+(t.reads.size===1?"":"s")):"Reading the project",state:(edited||tests.length||finished)?"done":"now"},
      {label:edited?("Editing "+edited+" file"+(edited===1?"":"s")):"Editing files",detail:[...t.edits.keys()].slice(0,3).map(x=>x.split("/").pop()).join(", "),state:finished||tests.length?(edited?"done":"skip"):edited?"now":"todo"},
      {label:tests.length?("Running tests "+ran+" of "+tests.length):"Running tests",detail:tests.some(x=>x.done&&!x.ok)?"Some tests failed":"",state:finished?(tests.length?"done":"skip"):tests.length?(ran===tests.length?"done":"now"):"todo"},
      {label:"Ready for your review",detail:"",state:finished?"done":"todo"}
    ];
    const pct=finished?100:tests.length?70+Math.round(25*ran/Math.max(1,tests.length)):edited?45:15;
    return {steps,pct};
  }
  function drawProgress(){
    if(!turn)return;
    const {steps,pct}=phaseState();
    turn.card.querySelector(".dsx-bar span").style.width=pct+"%";
    const list=turn.card.querySelector(".dsx-phases");list.replaceChildren();
    for(const s of steps){
      const li=el("li","dsx-ph "+s.state);
      li.append(el("span","dsx-ph-i",s.state==="done"?"✓":s.state==="now"?"◌":s.state==="skip"?"–":"○"),el("b",null,s.label));
      if(s.detail)li.append(el("span","dsx-muted",s.detail));
      list.append(li);
    }
  }
  function onEvent(ev){
    if(!turn||turn.done)return;
    const type=String(ev.type||"");
    if(type==="tool_call"){
      const name=String(ev.name||""),args=ev.args&&typeof ev.args==="object"?ev.args:{};
      const path=String(args.path||args.file||args.directory||"");
      if(READ.has(name))turn.reads.add(path||name+turn.reads.size);
      else if(WRITE.has(name)&&path)turn.edits.set(path,true);
      else if(RUN.has(name)){
        const cmd=String(args.command||args.cmd||"");
        (TEST_RE.test(cmd)?turn.tests:turn.commands).set(ev.id,{cmd,done:false,ok:null,output:""});
      }
    }else if(type==="tool_result"){
      const rec=turn.tests.get(ev.id)||turn.commands.get(ev.id);
      if(rec){rec.done=true;rec.ok=!!ev.ok;rec.output=String(ev.output||"");}
    }
    drawProgress();
  }
  function onApproval({callId,entry}){
    if(!turn)return;
    const row=el("div","dsx-approval");
    row.append(el("span",null,"Needs your OK: "+String(entry?.label||entry?.description||entry?.name||"a tool step")));
    const yes=el("button","btn sm primary","Approve once"),no=el("button","btn sm","Deny");
    yes.type=no.type="button";
    const act=allow=>{yes.disabled=no.disabled=true;void workbench.approve(callId,allow);row.append(el("span","dsx-muted",allow?"Approved":"Denied"));};
    yes.onclick=()=>act(true);no.onclick=()=>act(false);
    row.append(yes,no);turn.body.insertBefore(row,turn.card.nextSibling);scrollDown();
  }
  async function finishTurn({message,kind}){
    if(!turn||turn.done)return;
    const t=turn;t.done=true;drawProgress();
    t.card.querySelector(".dsx-prog-head b").textContent=kind==="error"?"Stopped":"Done";
    t.card.querySelector(".dsx-prog-stop").remove();
    t.card.classList.add("finished");
    const answer=el("div","dsx-answer");
    for(const para of String(message||"").split(/\n{2,}/))if(para.trim())answer.append(el("p",null,para.trim()));
    t.body.insertBefore(answer,t.card);
    if(t.checkpoint){
      try{t.changes=await api(BASE+"/review/changes?"+new URLSearchParams({project:t.project,checkpoint:t.checkpoint}));}
      catch(err){t.changes=null;t.checkpointError=err.message;}
    }
    const list=el("ul","dsx-check");
    if(t.reads.size)list.append(checkItem("✓","Read "+t.reads.size+" file"+(t.reads.size===1?"":"s")));
    for(const c of t.changes?.changes||[]){
      const li=checkItem("✓",(c.change==="added"?"Added ":c.change==="deleted"?"Deleted ":"Edited "));
      const link=el("button","dsx-link",c.path);link.type="button";link.onclick=()=>openReview("changes",c.path);
      li.append(link);
      if(c.change==="added")li.append(el("span","dsx-badge b-ok","new"));
      else if(!c.binary)li.append(el("span","dsx-badge b-acc","+"+c.added+" −"+c.removed));
      list.append(li);
    }
    for(const x of t.tests.values()){const li=checkItem(x.ok?"✓":"✗","Ran tests");li.append(el("span","dsx-badge "+(x.ok?"b-ok":"b-bad"),x.ok?"passed":"failed"));list.append(li);}
    if(list.children.length)t.body.insertBefore(list,t.card);
    const actions=el("div","dsx-actions");t.actions=actions;
    const n=t.changes?.changes?.length||0;
    if(n){
      const keep=el("button","btn sm primary","Keep changes"),undo=el("button","btn sm","Undo"),rev=el("button","btn sm","Review changes");
      keep.type=undo.type=rev.type="button";keep.dataset.act="keep";undo.dataset.act="undo";
      keep.onclick=()=>void keepTurn(t);undo.onclick=()=>void undoTurn(t);rev.onclick=()=>openReview("changes");
      actions.append(keep,undo,rev);
    }else if(t.checkpoint){
      actions.append(el("span","dsx-muted","No files changed."));
      void api(BASE+"/review/keep",{project:t.project,checkpoint:t.checkpoint}).catch(()=>{});t.resolved=true;
    }else if(t.checkpointError){
      actions.append(el("span","dsx-muted","Undo isn't available for this task: "+t.checkpointError));
    }
    t.body.insertBefore(actions,t.card);
    t.card.remove();
    afterFilesChanged?.();
    if(n)openReview("changes");
    refresh();scrollDown();prompt.focus();
  }
  function checkItem(mark,text){const li=el("li");li.append(el("span","dsx-ck "+(mark==="✗"?"bad":""),mark),el("span",null,text));return li;}
  function resolveTurn(t,text){
    t.resolved=true;t.actions.replaceChildren(el("span","dsx-muted",text));
    if(review.turn===t)drawReview();
    refresh();
  }
  async function keepTurn(t){
    if(t.resolved)return;
    try{await api(BASE+"/review/keep",{project:t.project,checkpoint:t.checkpoint});resolveTurn(t,"✓ Changes kept.");}
    catch(err){status("Keep failed: "+err.message,true);}
  }
  async function undoTurn(t){
    if(t.resolved)return;
    if(!window.confirm("Undo every change from this task? Edited and deleted files go back to how they were, and new files are removed."))return;
    try{
      const r=await api(BASE+"/review/undo",{project:t.project,checkpoint:t.checkpoint,confirmed:true});
      resolveTurn(t,"↺ Changes undone · "+r.restored.length+" restored, "+r.removed.length+" removed"+(r.skipped.length?", "+r.skipped.length+" left in place":"")+".");
      afterFilesChanged?.();
    }catch(err){status("Undo failed: "+err.message,true);}
  }

  // ---------------------------------------------------------------- review panel
  const review={tab:"changes",turn:null,focus:null};
  function openReview(tab="changes",focus=null){
    const t=[...thread.querySelectorAll(".dsx-msg.bot")].length?turnRef():null;
    if(!t)return;
    review.turn=t;review.tab=tab;review.focus=focus;
    $("dsxReview").hidden=false;root.classList.add("reviewing");drawReview();
  }
  function turnRef(){return turn;}
  function closeReview(){$("dsxReview").hidden=true;root.classList.remove("reviewing");}
  $("dsxReviewClose").addEventListener("click",closeReview);
  root.querySelector(".dsx-rtabs").addEventListener("click",e=>{const b=e.target.closest("[data-rtab]");if(!b)return;review.tab=b.dataset.rtab;drawReview();});
  $("dsxRKeep").addEventListener("click",()=>review.turn&&void keepTurn(review.turn));
  $("dsxRUndo").addEventListener("click",()=>review.turn&&void undoTurn(review.turn));
  $("dsxROpen").addEventListener("click",()=>{
    const first=review.focus||(review.turn?.changes?.changes||[]).find(c=>c.change!=="deleted")?.path;
    setView("editor");if(first)void openFile(first);
  });
  function diffBlock(c){
    const box=el("div","dsx-file");
    const head=el("div","dsx-file-h");head.append(el("code",null,c.path),el("span","dsx-gap"),
      el("span","dsx-badge "+(c.change==="added"?"b-ok":c.change==="deleted"?"b-bad":"b-acc"),c.change==="added"?"new file":c.change==="deleted"?"deleted":"+"+c.added+" −"+c.removed));
    box.append(head);
    if(c.binary||!c.diff){box.append(el("p","dsx-muted dsx-pad",c.binary?"Binary or large file: no text diff.":"No text difference."));return box;}
    const pre=el("pre","dsx-diff");
    for(const line of c.diff.split("\n").slice(2)){
      const cls=line.startsWith("@@")?"h":line.startsWith("+")?"a":line.startsWith("-")?"d":"";
      pre.append(el("span",cls,line+"\n"));
    }
    box.append(pre);return box;
  }
  function drawReview(){
    const t=review.turn,body=$("dsxReviewBody");body.replaceChildren();
    for(const b of root.querySelectorAll("[data-rtab]")){const on=b.dataset.rtab===review.tab;b.classList.toggle("on",on);b.setAttribute("aria-selected",String(on));}
    const changes=t?.changes?.changes||[];
    if(review.tab==="changes"){
      if(!changes.length)body.append(el("p","dsx-muted dsx-pad","No changes to review."));
      for(const c of changes){const b=diffBlock(c);body.append(b);if(c.path===review.focus)requestAnimationFrame(()=>b.scrollIntoView({block:"nearest"}));}
    }else if(review.tab==="files"){
      if(!changes.length)body.append(el("p","dsx-muted dsx-pad","No files changed."));
      for(const c of changes){
        const row=el("div","dsx-frow");row.append(el("code",null,c.path),el("span","dsx-gap"),el("span","dsx-muted",c.change));
        if(c.change!=="deleted"){const b=el("button","btn sm","Open");b.type="button";b.onclick=()=>{setView("editor");void openFile(c.path);};row.append(b);}
        body.append(row);
      }
    }else{
      const tests=[...(t?.tests?.values()||[])];
      if(!tests.length)body.append(el("p","dsx-muted dsx-pad","No tests ran in this task. Use Run tests in the editor view, or ask the assistant to add some."));
      for(const x of tests){
        const box=el("div","dsx-file");const head=el("div","dsx-file-h");
        head.append(el("code",null,x.cmd||"tests"),el("span","dsx-gap"),el("span","dsx-badge "+(x.ok?"b-ok":x.done?"b-bad":"b-no"),x.ok?"passed":x.done?"failed":"running"));
        box.append(head);if(x.output)box.append(el("pre","dsx-diff",x.output.slice(-3000)));body.append(box);
      }
    }
    const open=!!t&&!t.resolved&&!!changes.length;
    $("dsxRKeep").disabled=!open;$("dsxRUndo").disabled=!open;
  }

  workbench.subscribe((type,data)=>{
    if(type==="event")onEvent(data);
    else if(type==="approval")onApproval(data);
    else if(type==="finish")void finishTurn(data);
    refresh();
  });

  // ---------------------------------------------------------------- state
  function refresh(){
    const p=getProject(),trusted=!!p?.trusted,busy=workbench.isBusy();
    const name=p?.name||(p?.project?String(p.project).split(/[\\/]/).filter(Boolean).pop():"");
    $("dsxProjectName").textContent=name||"Choose a project";
    $("dsxProject").classList.toggle("empty",!p);
    $("dsxCompProject").textContent=name?"▸ "+name:"No project";
    const chip=$("dsxTrust");chip.hidden=!p;
    chip.textContent=trusted?"Changes allowed":"Read-only";
    chip.className="dsx-chip "+(trusted?"ok":"ro");
    chip.title=trusted?"The assistant may edit this project. Click to make it read-only.":"Browsing only. Click to allow changes.";
    $("dsxAllow").setAttribute("aria-checked",String(trusted));$("dsxAllow").disabled=!p;
    const setup=!trusted;
    $("dsxSetup").hidden=!setup;
    $("dsxStep1").className="dsx-step "+(p?"done":"now");
    $("dsxStep2").className="dsx-step "+(trusted?"done":p?"now":"todo");
    $("dsxStep3").className="dsx-step "+(trusted?"now":"todo");
    $("dsxStepTrust").disabled=!p;
    const empty=!thread.children.length;
    $("dsxHero").hidden=!empty||view==="editor";
    $("dsxStarters").hidden=!empty;
    root.classList.toggle("has-thread",!empty);
    $("dsxFoot").textContent=!p?"Open a project to begin. Nothing runs until you press send."
      :!trusted?"Read-only: allow changes (step 2) before the assistant can work here."
      :empty?"Picking a card only fills the box. Nothing runs until you press send."
      :"The assistant asks before anything risky. You keep or undo every change.";
    send.disabled=busy||!trusted||prompt.value.trim().length<5;
    $("dsxStop").hidden=!busy;
    $("dsxRunTests").disabled=$("dsxRunApp").disabled=busy||!trusted;
    for(const b of $("dsxStarters").children)b.disabled=busy;
  }
  setView(view,{save:false});
  return {
    projectChanged(){refresh();if(toolsOpen)void loadToolInfo();},
    refresh,
    setView
  };
}

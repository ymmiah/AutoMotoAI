/* Developer Studio simple views: chat-first by default, a two-pane editor on request,
   one searchable Tools & languages page, and the classic all-panels layout for experts.
   Nothing here runs code by itself: starter cards only fill the prompt, every task needs
   the trusted project and a confirmation, and Keep / Undo use the review checkpoint API. */
const BRAND=document.querySelector('meta[name="automoto-brand-short"]')?.content||"AutoMoto";
const VIEW_KEY="automoto.developer.view";
const CHAT_KEY="automoto.developer.chat.";
const CHAT_MAX=24;
const CHAT_BYTES=120000;
const COMPACT_MQ=typeof window!=="undefined"?window.matchMedia("(max-width: 900px)"):{matches:false,addEventListener(){}};
const isCompact=()=>COMPACT_MQ.matches;
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
  ["run","Run & preview","Run your app and tests, and see it live","▶","#4caf50","builtin",["dsRunRoot"],null],
  ["git","Git","Changes, branches, commits and conflicts","⎇","#f05033","builtin",["dsGitRoot"],null],
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

export function mountDeveloperSimple({api,host,workbench,runner,git,getProject,openFile,afterFilesChanged,status}){
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
      '<button type="button" class="btn sm" id="dsxClear" hidden>Clear chat</button>'+
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
        '<div class="dsx-sheet-handle" aria-hidden="true"></div>'+
        '<div class="dsx-rtabs" role="tablist"><button type="button" role="tab" data-rtab="changes" class="on" aria-selected="true">Changes</button><button type="button" role="tab" data-rtab="files" aria-selected="false">Files</button><button type="button" role="tab" data-rtab="tests" aria-selected="false">Tests</button><span class="dsx-gap"></span><button type="button" class="dsx-x" id="dsxReviewClose" aria-label="Close review panel">✕</button></div>'+
        '<div class="dsx-rbody" id="dsxReviewBody"></div>'+
        '<div class="dsx-rfoot"><button type="button" class="btn sm primary" id="dsxRKeep">Keep</button><button type="button" class="btn sm" id="dsxRUndo">Undo</button><span class="dsx-gap"></span><button type="button" class="btn sm" id="dsxROpen">Open in editor</button></div>'+
      '</aside>'+
    '</div>'+
    '<section class="dsx-tools" id="dsxToolsPage" aria-label="Tools and languages" hidden>'+
      '<div class="dsx-sheet-handle" aria-hidden="true"></div>'+
      '<div class="dsx-tools-head"><div><h2>Tools &amp; languages</h2><p>Open a language when you need it. The assistant picks what it needs on its own.</p></div><span class="dsx-gap"></span><button type="button" class="btn sm" id="dsxToolsBack">Back</button></div>'+
      '<div class="dsx-tools-bar"><input type="search" class="input" id="dsxToolSearch" placeholder="Search languages and tools…" aria-label="Search languages and tools"><div class="dsx-cats" id="dsxCats" role="group" aria-label="Filter"></div></div>'+
      '<div class="dsx-detected" id="dsxDetected" hidden></div>'+
      '<div class="dsx-grid" id="dsxToolGrid"></div>'+
      '<div class="dsx-detail" id="dsxToolDetail" hidden><div class="dsx-detail-head"><button type="button" class="btn sm" id="dsxDetailBack">← All tools</button><h3 id="dsxDetailTitle"></h3></div><div id="dsxDetailBody"></div></div>'+
      '<div class="dsx-tools-foot"><span>Prefer every panel on one page?</span><button type="button" class="btn sm" id="dsxClassic">Show all panels (classic layout)</button></div>'+
    '</section>'+
    '<aside class="dsx-files-sheet" id="dsxFilesSheet" aria-label="Project files" hidden>'+
      '<div class="dsx-sheet-handle" aria-hidden="true"></div>'+
      '<div class="dsx-sheet-head"><h2>Files</h2><span class="dsx-gap"></span><button type="button" class="dsx-x" id="dsxFilesClose" aria-label="Close files">✕</button></div>'+
      '<div class="dsx-sheet-body" id="dsxFilesBody"></div>'+
    '</aside>'+
    '<div class="dsx-backdrop" id="dsxBackdrop" hidden></div>'+
    '<nav class="dsx-nav" id="dsxNav" aria-label="Studio sections">'+
      '<button type="button" id="dsxNavChat" data-nav="chat" class="on" aria-current="page"><span class="dsx-nav-ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7A2.5 2.5 0 0 1 17.5 16H9l-4 4v-4.2A2.5 2.5 0 0 1 4 13.5z"/></svg></span><span>Chat</span></button>'+
      '<button type="button" id="dsxNavFiles" data-nav="files"><span class="dsx-nav-ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7.5A2.5 2.5 0 0 1 6.5 5H10l2 2h5.5A2.5 2.5 0 0 1 20 9.5v7A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5z"/></svg></span><span>Files</span></button>'+
      '<button type="button" id="dsxNavReview" data-nav="review"><span class="dsx-nav-ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 6h14M5 12h14M5 18h8"/><path d="m15 16 2 2 3-3"/></svg></span><span>Review</span><span class="dsx-nav-badge" id="dsxNavReviewBadge" hidden></span></button>'+
      '<button type="button" id="dsxNavTools" data-nav="tools"><span class="dsx-nav-ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .1 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 8 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1A2 2 0 1 1 3.3 17l.1-.1A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.1-1 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 8a1.7 1.7 0 0 0-.3-1.8L4.2 6.1A2 2 0 1 1 7 3.3l.1.1A1.7 1.7 0 0 0 8 4.6a1.7 1.7 0 0 0 1-.1 1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1A1.7 1.7 0 0 0 16 4.6a1.7 1.7 0 0 0 1.8-.3l.1-.1A2 2 0 1 1 20.7 7l-.1.1A1.7 1.7 0 0 0 19.4 8a1.7 1.7 0 0 0 .1 1 1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1 1.7 1.7 0 0 0-.1 1z"/></svg></span><span>Tools</span></button>'+
    '</nav>';
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
  let lastRealTests=null;
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
      if(isCompact()&&currentSheet==="files")closeFilesSheet({silent:true,moved:next==="editor"});
      if(next==="editor"){place(q(".ds-mobile-switch"),$("dsxEditor"));place(q(".ds-columns"),$("dsxEditor"));place(statusLine,$("dsxEditor"));}
      else{restore(q(".ds-mobile-switch"));restore(q(".ds-columns"));restore(statusLine);}
      $("dsxView").textContent=next==="editor"?"Back to chat":"Open in editor";
      $("dsxView").setAttribute("aria-pressed",String(next==="editor"));
      showTools(toolsOpen);
    }
    syncReviewOpen();
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
    $("dsxToolsPage").hidden=!open;
    if(!isCompact())$("dsxBody").hidden=open;else $("dsxBody").hidden=false;
    $("dsxTools").setAttribute("aria-expanded",String(open));
    $("dsxNavTools")?.setAttribute("aria-expanded",String(open));
    if(!open)closeDetail();
    if(isCompact()){
      if(open)armSheet("tools");
      else if(currentSheet==="tools")disarmSheet();
    }
    syncNav();
  }
  $("dsxTools").addEventListener("click",()=>{showTools(!toolsOpen);if(toolsOpen){drawTools();void loadToolInfo();if(!isCompact())$("dsxToolSearch").focus();}});
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
  // V41/V44: Run app / Run tests use the real, approval-gated runner when the project has a
  // detected command, and fall back to asking the assistant when it doesn't.
  function openTool(id){
    const t=TOOLS.find(x=>x[0]===id);if(!t)return;
    showTools(true);drawTools();void loadToolInfo();openDetail(t);
  }
  async function realRun(kind){
    if(runner&&await runner.hasRecipe(kind).catch(()=>false)){openTool("run");await runner.run(kind);return;}
    void submit(kind==="app"?RUN_APP:RUN_TESTS);
  }
  $("dsxRunTests").addEventListener("click",()=>void realRun("test"));
  $("dsxRunApp").addEventListener("click",()=>void realRun("app"));
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
    recordUser(note);saveChat();
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
    t.card.querySelector(".dsx-prog-stop")?.remove();
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
    t.reviewFiles=n?(t.changes.changes||[]).map(c=>({...c})):[]
    t.fileDecisions=t.fileDecisions||{};
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
    recordAssistant(t);saveChat();
    refresh();scrollDown();
    if(isCompact()&&n)$("dsxRKeep")?.focus();else prompt.focus();
  }
  function checkItem(mark,text){const li=el("li");li.append(el("span","dsx-ck "+(mark==="✗"?"bad":""),mark),el("span",null,text));return li;}
  function resolveTurn(t,text){
    t.resolved=true;t.resolveText=text;t.actions.replaceChildren(el("span","dsx-muted",text));
    if(review.turn===t)drawReview();
    recordAssistant(t);saveChat();
    if(isCompact())closeReview();
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
  async function keepFile(t,path){
    if(t.resolved)return;
    t.fileDecisions=t.fileDecisions||{};
    t.fileDecisions[path]="kept";
    await settleFiles(t);
  }
  async function undoFile(t,path){
    if(t.resolved)return;
    if(!window.confirm("Undo changes to "+path+"? This file goes back to how it was, or a new file is removed."))return;
    try{
      await api(BASE+"/review/undo",{project:t.project,checkpoint:t.checkpoint,confirmed:true,paths:[path]});
      t.fileDecisions=t.fileDecisions||{};
      t.fileDecisions[path]="undone";
      afterFilesChanged?.();
      await settleFiles(t);
    }catch(err){status("Undo failed: "+err.message,true);}
  }
  async function settleFiles(t){
    const files=t.reviewFiles||[];
    const pending=files.filter(c=>!t.fileDecisions?.[c.path]);
    if(pending.length){drawReview();saveChat();refresh();return;}
    try{await api(BASE+"/review/keep",{project:t.project,checkpoint:t.checkpoint});}catch(_){ /* already discarded */ }
    const kept=files.filter(c=>t.fileDecisions[c.path]==="kept").length;
    const undone=files.filter(c=>t.fileDecisions[c.path]==="undone").length;
    const parts=[];
    if(kept)parts.push(kept+" kept");
    if(undone)parts.push(undone+" undone");
    resolveTurn(t,(undone&&!kept?"↺ ":"✓ ")+parts.join(", ")+".");
  }

  // ---------------------------------------------------------------- review panel
  const review={tab:"changes",turn:null,focus:null};
  function openReview(tab="changes",focus=null){
    const t=[...thread.querySelectorAll(".dsx-msg.bot")].length?turnRef():null;
    if(!t)return;
    review.turn=t;review.tab=tab;review.focus=focus;
    $("dsxReview").hidden=false;root.classList.add("reviewing");drawReview();
    if(isCompact())armSheet("review");
    syncNav();
  }
  function turnRef(){return turn;}
  function closeReview(){
    $("dsxReview").hidden=true;root.classList.remove("reviewing");
    if(isCompact()&&currentSheet==="review")disarmSheet();
    syncNav();
  }
  $("dsxReviewClose").addEventListener("click",closeReview);
  root.querySelector(".dsx-rtabs").addEventListener("click",e=>{const b=e.target.closest("[data-rtab]");if(!b)return;review.tab=b.dataset.rtab;drawReview();});
  $("dsxRKeep").addEventListener("click",()=>review.turn&&void keepTurn(review.turn));
  $("dsxRUndo").addEventListener("click",()=>review.turn&&void undoTurn(review.turn));
  function reviewOpenLabel(){return isCompact()&&view==="editor"?"Show file":"Open in editor";}
  function syncReviewOpen(){const b=$("dsxROpen");if(b)b.textContent=reviewOpenLabel();}
  $("dsxROpen").addEventListener("click",()=>{
    const first=review.focus||(review.turn?.reviewFiles||review.turn?.changes?.changes||[]).find(c=>c.change!=="deleted"&&review.turn?.fileDecisions?.[c.path]!=="undone")?.path;
    if(view!=="editor")setView("editor");
    if(first)void openFile(first);
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
      const files=t?.reviewFiles||changes;
      if(!files.length)body.append(el("p","dsx-muted dsx-pad","No files changed."));
      for(const c of files){
        const decision=t?.fileDecisions?.[c.path];
        const row=el("div","dsx-frow");row.append(el("code",null,c.path),el("span","dsx-gap"),el("span","dsx-muted",decision||c.change));
        if(isCompact()&&!t?.resolved&&!decision){
          const keep=el("button","btn sm","Keep");keep.type="button";keep.title="Leave this file as the assistant left it";
          keep.onclick=()=>void keepFile(t,c.path);
          const undo=el("button","btn sm","Undo");undo.type="button";undo.title="Put this file back to how it was";
          undo.onclick=()=>void undoFile(t,c.path);
          row.append(keep,undo);
        }
        if(c.change!=="deleted"&&decision!=="undone"){
          const b=el("button","btn sm",isCompact()&&view==="editor"?"Show file":"Open");b.type="button";
          b.onclick=()=>{if(view!=="editor")setView("editor");void openFile(c.path);};row.append(b);
        }
        body.append(row);
      }
    }else{
      const tests=[...(t?.tests?.values()||[])];
      if(lastRealTests)tests.push(lastRealTests);
      if(!tests.length)body.append(el("p","dsx-muted dsx-pad","No tests ran in this task. Use Run tests in the editor view, or ask the assistant to add some."));
      for(const x of tests){
        const box=el("div","dsx-file");const head=el("div","dsx-file-h");
        head.append(el("code",null,x.cmd||"tests"),el("span","dsx-gap"),el("span","dsx-badge "+(x.ok?"b-ok":x.done?"b-bad":"b-no"),x.ok?"passed":x.done?"failed":"running"));
        box.append(head);
        if(x.summary){const chips=el("div","dsr-chips dsx-pad");chips.append(el("span","dsx-badge b-ok",x.summary.passed+" passed"),el("span","dsx-badge "+(x.summary.failed?"b-bad":"b-no"),x.summary.failed+" failed"),el("span","dsx-badge b-no",x.summary.skipped+" skipped"));box.append(chips);}
        if(x.output)box.append(el("pre","dsx-diff",x.output.slice(-3000)));body.append(box);
      }
    }
    const pending=(t?.reviewFiles||changes).filter(c=>!t?.fileDecisions?.[c.path]);
    const open=!!t&&!t.resolved&&!!pending.length;
    $("dsxRKeep").disabled=!open;$("dsxRUndo").disabled=!open;
    syncReviewOpen();
  }

  workbench.subscribe((type,data)=>{
    if(type==="event")onEvent(data);
    else if(type==="approval")onApproval(data);
    else if(type==="finish")void finishTurn(data);
    refresh();
  });


  // ---------------------------------------------------------------- compact sheets and tab bar (900px and below)
  let currentSheet=null,sheetCtl=null,sheetReturnFocus=null;
  const sheetEl=name=>name==="review"?$("dsxReview"):name==="files"?$("dsxFilesSheet"):name==="tools"?$("dsxToolsPage"):null;
  const focusables=node=>[...node.querySelectorAll('a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])')].filter(n=>!n.hidden&&n.offsetParent!==null);
  function disarmSheet(){
    sheetCtl?.abort();sheetCtl=null;
    const prev=currentSheet;currentSheet=null;delete root.dataset.sheet;
    $("dsxBackdrop").hidden=true;
    if(prev){const p=sheetEl(prev);p?.removeAttribute("role");p?.removeAttribute("aria-modal");}
  }
  function closeCompactSheet(){
    const name=currentSheet,back=sheetReturnFocus;
    if(name==="review")closeReview();
    else if(name==="files")closeFilesSheet();
    else if(name==="tools")showTools(false);
    else disarmSheet();
    sheetReturnFocus=null;
    if(back&&typeof back.focus==="function")try{back.focus();}catch(_){ }
    syncNav();
  }
  function trapFocus(e,panel){
    const list=focusables(panel);if(!list.length)return;
    const first=list[0],last=list[list.length-1];
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
    else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
  }
  function bindSwipe(panel,signal){
    const handle=panel.querySelector(".dsx-sheet-handle")||panel;
    let startY=null,startX=null;
    const down=e=>{startY=e.clientY;startX=e.clientX;};
    const move=e=>{
      if(startY==null)return;
      const dy=e.clientY-startY,dx=e.clientX-startX;
      if(dy>24&&Math.abs(dy)>=Math.abs(dx))e.preventDefault();
    };
    const up=e=>{
      if(startY==null)return;
      const dy=e.clientY-startY,dx=e.clientX-startX;
      startY=startX=null;
      if(dy>72&&Math.abs(dy)>=Math.abs(dx))closeCompactSheet();
    };
    handle.addEventListener("pointerdown",down,{signal});
    window.addEventListener("pointermove",move,{signal,passive:false});
    window.addEventListener("pointerup",up,{signal});
    window.addEventListener("pointercancel",()=>{startY=null;},{signal});
  }
  function armSheet(name){
    if(!isCompact())return;
    if(currentSheet&&currentSheet!==name){
      const prev=currentSheet;
      if(prev==="review"){$("dsxReview").hidden=true;root.classList.remove("reviewing");}
      else if(prev==="files")closeFilesSheet({silent:true});
      else if(prev==="tools"){toolsOpen=false;$("dsxToolsPage").hidden=true;$("dsxTools").setAttribute("aria-expanded","false");closeDetail();}
      sheetCtl?.abort();sheetCtl=null;
    }
    currentSheet=name;root.dataset.sheet=name;
    const panel=sheetEl(name);if(!panel)return;
    panel.hidden=false;
    panel.setAttribute("role","dialog");panel.setAttribute("aria-modal","true");
    $("dsxBackdrop").hidden=false;
    sheetReturnFocus=sheetReturnFocus||document.activeElement;
    sheetCtl=new AbortController();
    const sig=sheetCtl.signal;
    $("dsxBackdrop").addEventListener("click",()=>closeCompactSheet(),{signal:sig});
    document.addEventListener("keydown",e=>{
      if(!isCompact()||currentSheet!==name)return;
      if(e.key==="Escape"){e.preventDefault();closeCompactSheet();}
      if(e.key==="Tab")trapFocus(e,panel);
    },{signal:sig});
    bindSwipe(panel,sig);
    const list=focusables(panel);
    (name==="review"?$("dsxRKeep"):list[0]||panel)?.focus?.();
    syncNav();
  }
  function openFilesSheet(){
    if(toolsOpen)showTools(false);
    if(!$("dsxReview").hidden)closeReview();
    if(view==="editor"){/* keep columns available */ }
    const cols=q(".ds-columns");
    place(cols,$("dsxFilesBody"));
    host.dataset.mobilePanel="explorer";
    document.getElementById("dsShowExplorer")?.click();
    $("dsxFilesSheet").hidden=false;
    armSheet("files");
    if(!getProject())status("Open a project to browse its files.");
  }
  function closeFilesSheet({silent,moved}={}){
    const cols=$("dsxFilesBody")?.querySelector(".ds-columns");
    if(cols&&!moved){
      if(view==="editor")place(cols,$("dsxEditor"));
      else restore(cols);
    }
    $("dsxFilesSheet").hidden=true;
    if(!silent){if(currentSheet==="files")disarmSheet();syncNav();}
  }
  $("dsxFilesClose").addEventListener("click",()=>closeCompactSheet());
  $("dsxFilesBody").addEventListener("click",e=>{
    if(!isCompact()||currentSheet!=="files")return;
    const btn=e.target.closest(".ds-entry");if(!btn)return;
    if((btn.querySelector(".ds-file-icon")?.textContent||"")==="▸")return;
    queueMicrotask(()=>{
      if(view!=="editor")setView("editor");
      else place(q(".ds-columns"),$("dsxEditor"));
      closeFilesSheet({moved:true});
      document.getElementById("dsShowEditor")?.click();
      syncNav();
    });
  });
  function pendingReview(){
    const t=turn;if(!t||t.resolved)return false;
    const files=t.reviewFiles||t.changes?.changes||[];
    return files.some(c=>!t.fileDecisions?.[c.path]);
  }
  function syncNav(){
    if(!$("dsxNav"))return;
    const badge=$("dsxNavReviewBadge");
    const waiting=pendingReview();
    badge.hidden=!isCompact()||!waiting;
    badge.textContent=waiting?"1":"";
    const active=currentSheet||(view==="editor"?"files":"chat");
    for(const btn of $("dsxNav").querySelectorAll("[data-nav]")){
      const on=isCompact()&&btn.dataset.nav===active&&(btn.dataset.nav!=="review"||waiting||currentSheet==="review");
      btn.classList.toggle("on",on);
      btn.setAttribute("aria-current",on?"page":"false");
    }
    $("dsxRKeep").textContent=isCompact()?"Keep changes":"Keep";
    $("dsxRUndo").textContent=isCompact()?"Undo all":"Undo";
  }
  $("dsxNav").addEventListener("click",e=>{
    const btn=e.target.closest("[data-nav]");if(!btn||!isCompact())return;
    const go=btn.dataset.nav;
    if(go==="chat"){
      closeCompactSheet();
      if(view==="editor")setView("chat");
      syncNav();return;
    }
    if(go==="files"){openFilesSheet();return;}
    if(go==="review"){
      if(turn){openReview(review.tab||"changes");return;}
      $("dsxReview").hidden=false;root.classList.add("reviewing");
      $("dsxReviewBody").replaceChildren(el("p","dsx-muted dsx-pad","No changes to review yet. After a task, Keep or Undo will appear here."));
      $("dsxRKeep").disabled=true;$("dsxRUndo").disabled=true;
      armSheet("review");
      return;
    }
    if(go==="tools"){
      showTools(true);drawTools();void loadToolInfo();
      $("dsxToolSearch").placeholder="Search for a language, like Python…";
      $("dsxToolSearch").focus();
    }
  });

  // ---------------------------------------------------------------- chat history (per project, local only)
  let history=[];
  let loadedProject=null;
  function chatKey(){const p=getProject()?.project;return p?CHAT_KEY+p:null;}
  function recordUser(text){history.push({kind:"user",text:String(text||"")});}
  function recordAssistant(t){
    const last=history.filter(x=>x.kind==="assistant"&&x.checkpoint===t.checkpoint).pop();
    const entry={kind:"assistant",text:t.body?.querySelector(".dsx-answer")?.innerText||"",checkpoint:t.checkpoint||null,project:t.project,resolved:!!t.resolved,resolveText:t.resolveText||"",
      reviewFiles:t.reviewFiles||[],fileDecisions:t.fileDecisions||{},
      tests:[...(t.tests?.values()||[])].map(x=>({cmd:x.cmd,ok:x.ok,done:x.done,output:String(x.output||"").slice(-3000)}))};
    if(last)Object.assign(last,entry);else history.push(entry);
  }
  function saveChat(){
    const key=chatKey();if(!key)return;
    const data=history.filter(x=>x.kind!=="pending").slice(-CHAT_MAX);
    let json=JSON.stringify(data);
    while(json.length>CHAT_BYTES&&data.length>2){data.shift();json=JSON.stringify(data);}
    try{localStorage.setItem(key,json);}catch(_){ /* quota */ }
  }
  function clearChat(){
    if(history.length&&!window.confirm("Clear this project's studio chat? File changes are not undone."))return;
    thread.replaceChildren();history=[];turn=null;closeReview();
    const key=chatKey();if(key)localStorage.removeItem(key);
    refresh();
  }
  $("dsxClear").addEventListener("click",clearChat);
  function replayItem(item){
    if(item.kind==="user"){
      const user=el("div","dsx-msg user");user.append(el("div","dsx-bubble",item.text||""));thread.append(user);return;
    }
    if(item.kind!=="assistant")return;
    const bot=el("div","dsx-msg bot");
    const av=el("span","dsx-av",BRAND.charAt(0));av.setAttribute("aria-hidden","true");
    const body=el("div","dsx-turn");bot.append(av,body);
    if(item.text){const answer=el("div","dsx-answer");for(const para of String(item.text).split(/\n{2,}/))if(para.trim())answer.append(el("p",null,para.trim()));body.append(answer);}
    const files=item.reviewFiles||[];
    const list=el("ul","dsx-check");
    for(const c of files){
      const decision=item.fileDecisions?.[c.path];
      const li=checkItem("✓",(c.change==="added"?"Added ":c.change==="deleted"?"Deleted ":"Edited "));
      const link=el("button","dsx-link",c.path);link.type="button";link.onclick=()=>openReview("changes",c.path);
      li.append(link);if(decision)li.append(el("span","dsx-muted"," · "+decision));list.append(li);
    }
    if(list.children.length)body.append(list);
    const actions=el("div","dsx-actions");
    const restored={body,actions,checkpoint:item.checkpoint,project:item.project,resolved:!!item.resolved,resolveText:item.resolveText||"",reviewFiles:files,fileDecisions:item.fileDecisions||{},changes:{changes:files},tests:new Map((item.tests||[]).map((x,i)=>[x.cmd||i,x])),card:null};
    if(item.resolved)actions.append(el("span","dsx-muted",item.resolveText||"Done."));
    else if(files.length){
      const keep=el("button","btn sm primary","Keep changes"),undo=el("button","btn sm","Undo"),rev=el("button","btn sm","Review changes");
      keep.type=undo.type=rev.type="button";keep.dataset.act="keep";undo.dataset.act="undo";
      keep.onclick=()=>void keepTurn(restored);undo.onclick=()=>void undoTurn(restored);rev.onclick=()=>openReview("changes");
      actions.append(keep,undo,rev);turn=restored;
    }
    body.append(actions);thread.append(bot);
  }
  function loadChat(){
    const project=getProject()?.project||"";
    if(project===loadedProject)return;
    thread.replaceChildren();history=[];turn=null;closeReview();
    loadedProject=project;
    const key=chatKey();if(!key){refresh();return;}
    let data=[];
    try{data=JSON.parse(localStorage.getItem(key)||"[]");}catch(_){data=[];}
    if(!Array.isArray(data))data=[];
    history=data;for(const item of data)replayItem(item);
    if(turn&&turn.checkpoint&&!turn.resolved){
      void api(BASE+"/review/changes?"+new URLSearchParams({project:turn.project,checkpoint:turn.checkpoint}))
        .then(ch=>{turn.changes=ch;if(!turn.reviewFiles?.length)turn.reviewFiles=ch.changes||[];drawReview();})
        .catch(()=>{});
    }
    refresh();
  }

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
    $("dsxClear").hidden=empty||!isCompact();
    syncNav();
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
  COMPACT_MQ.addEventListener?.("change",()=>{
    if(!isCompact()&&currentSheet){
      const name=currentSheet;
      if(name==="files")closeFilesSheet();
      else if(name==="tools")showTools(false);
      else disarmSheet();
    }else if(isCompact()&&!$("dsxReview").hidden&&currentSheet!=="review")armSheet("review");
    syncReviewOpen();if(review.turn)drawReview();refresh();
  });
  setView(view,{save:false});
  return {
    projectChanged(){lastRealTests=null;loadChat();refresh();if(toolsOpen)void loadToolInfo();},
    testResult(r){lastRealTests={...r,cmd:"Last test run · "+r.cmd};if(review.turn&&review.tab==="tests"&&!$("dsxReview").hidden)drawReview();},
    openTool,
    refresh,
    setView
  };
}

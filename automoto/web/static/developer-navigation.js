/* Developer Studio V4 — local multi-root navigation, command palette, search and
 * opt-in navigation recovery. This module never saves source directly.
 */
export function mountDeveloperNavigation({api,host,editor,getProject,getDirectory,openProject,list,status}) {
  const BASE="/api/developer/studio";
  const KEY="automoto.developer.navigation.v4";
  const el=id=>host.querySelector("#"+id);
  const rootStrip=el("dsRootStrip");
  const region=el("dsNavigationRoot");
  region.innerHTML=
    '<div class="ds-v4-tools">'+
      '<button class="btn sm" type="button" id="dsPaletteOpen" aria-keyshortcuts="Control+Shift+P">Commands <span aria-hidden="true">⌘⇧P</span></button>'+
      '<label class="ds-remember"><input type="checkbox" id="dsRemember"> Remember navigation locally</label>'+
      '<button class="btn sm" type="button" id="dsRestoreSession">Resume session</button>'+
      '<button class="btn sm" type="button" id="dsClearSession">Clear saved session</button>'+
    '</div>'+
    '<form class="ds-v4-search" id="dsSearchForm" role="search" aria-label="Search approved source files">'+
      '<label for="dsSearchQuery">Search</label>'+
      '<input class="input" id="dsSearchQuery" maxlength="160" required placeholder="Literal text or filename" autocomplete="off">'+
      '<label for="dsSearchScope">In</label>'+
      '<select class="input" id="dsSearchScope" aria-label="Search type"><option value="content">File contents</option><option value="filename">File names</option></select>'+
      '<label for="dsSearchAcross">Roots</label>'+
      '<select class="input" id="dsSearchAcross" aria-label="Search roots"><option value="active">Current root</option><option value="all">All displayed roots</option></select>'+
      '<label class="ds-remember"><input type="checkbox" id="dsSearchCase"> Case sensitive</label>'+
      '<button class="btn primary sm" type="submit" id="dsSearchGo">Search</button>'+
    '</form>'+
    '<div class="ds-v4-results" id="dsResultRegion" hidden>'+
      '<p id="dsResultSummary" role="status" aria-live="polite"></p>'+
      '<div id="dsSearchResults" role="list" class="ds-results"></div>'+
      '<div class="ds-v4-replace">'+
        '<label for="dsReplaceValue">Replace with (selected source file only)</label>'+
        '<input class="input" id="dsReplaceValue" maxlength="1024" placeholder="Replacement text">'+
        '<button class="btn sm" id="dsReplaceReview" type="button" disabled>Preview replacement</button>'+
        '<button class="btn sm primary" id="dsReplaceApply" type="button" disabled>Load into editor</button>'+
      '</div>'+
      '<pre class="ds-v4-preview" id="dsReplacePreview" role="region" aria-label="Proposed changes, not yet saved" tabindex="0" hidden></pre>'+
    '</div>'+
    '<dialog id="dsCommandPalette" class="ds-palette" aria-labelledby="dsPaletteTitle">'+
      '<div class="ds-palette-heading"><h3 id="dsPaletteTitle">Developer commands</h3><button type="button" class="btn sm" id="dsPaletteClose">Close</button></div>'+
      '<label for="dsPaletteFilter">Search commands</label>'+
      '<input class="input" id="dsPaletteFilter" autocomplete="off" placeholder="Type a command">'+
      '<div id="dsPaletteItems" role="group" aria-label="Available commands"></div>'+
    '</dialog>';
  let roots=[],selected=null,proposal=null,requestSeq=0;
  let lastResultContext=null;
  const session=()=>{
    try{
      const obj=JSON.parse(localStorage.getItem(KEY)||"null");
      return obj&&obj.version===4&&typeof obj.project==="string"&&obj.project.length<=1024 &&
        Array.isArray(obj.files)&&obj.files.length<=10?obj:null;
    }catch{return null;}
  };
  const stored=session();
  el("dsRemember").checked=!!stored;
  function remember() {
    if(!el("dsRemember").checked)return;
    const current=getProject();
    if(!current)return;
    const paths=editor.openPaths().filter(x=>typeof x==="string"&&x.length<=1024).slice(0,10);
    try{
      localStorage.setItem(KEY,JSON.stringify({
        version:4,project:current.project,
        directory:getDirectory(),files:paths,
        activeFile:editor.currentFile()?.path||null
      }));
    }catch{status("Local navigation could not be stored. Browser storage may be disabled.",true);}
  }
  function updateRoots(items) {
    const seen=new Set(),selectedProject=getProject()?.project;
    roots=[];
    for(const item of items) {
      if(!item?.project||typeof item.project!=="string"||seen.has(item.project))continue;
      seen.add(item.project);
      roots.push({project:item.project,name:item.name||item.project.split(/[\\/]/).pop()||"Root"});
      if(roots.length>=8)break;
    }
    rootStrip.replaceChildren();
    for(const root of roots) {
      const button=document.createElement("button");
      button.type="button";button.className="ds-root-chip";
      button.textContent=root.name;
      button.title=root.project;
      button.setAttribute("aria-pressed",String(root.project===selectedProject));
      button.setAttribute("aria-label","Open root "+root.project);
      button.onclick=async()=>{
        const ok=await openProject(root.project);
        if(ok)remember();
      };
      rootStrip.appendChild(button);
    }
    rootStrip.hidden=!roots.length;
  }
  function renderResults(items,wasTruncated) {
    const target=el("dsSearchResults");target.replaceChildren();
    el("dsResultRegion").hidden=false;
    el("dsResultSummary").textContent=items.length+" matches"+
      (wasTruncated?" (results capped; narrow the search)":"")+". Select a result to open it.";
    for(const hit of items) {
      const button=document.createElement("button");
      button.type="button";button.className="ds-search-hit";
      const title=document.createElement("strong");
      const root=roots.find(x=>x.project===hit.project);
      title.textContent=(root?.name||"Project")+" / "+hit.path+
        (hit.line?":"+hit.line+":"+hit.column:"");
      const snippet=document.createElement("span");
      snippet.textContent=hit.preview||hit.path;
      button.append(title,snippet);
      button.addEventListener("click",()=>selectHit(hit));
      const item=document.createElement("div");item.setAttribute("role","listitem");
      item.appendChild(button);target.appendChild(item);
    }
    if(!items.length)status("No matching source files found.");
  }
  async function search() {
    const term=el("dsSearchQuery").value;
    if(!term.trim()){status("Enter a literal search term.",true);return;}
    const current=getProject();
    if(!current){status("Open an approved project before searching.",true);return;}
    const seq=++requestSeq;
    const across=el("dsSearchAcross").value==="all";
    const searchRoots=across?roots.slice(0,5):[{project:current.project,name:current.name}];
    let hits=[],capped=false,scanned=0;
    el("dsSearchGo").disabled=true;
    proposal=null;selected=null;
    el("dsReplaceApply").disabled=true;el("dsReplaceReview").disabled=true;
    el("dsReplacePreview").hidden=true;
    try{
      for(const root of searchRoots) {
        const result=await api(BASE+"/search",{
          project:root.project,directory:".",query:term,
          case_sensitive:el("dsSearchCase").checked,scope:el("dsSearchScope").value
        });
        if(seq!==requestSeq||!host.isConnected)return;
        scanned+=result.scanned_files;
        capped ||= result.truncated;
        hits.push(...result.items.map(item=>({...item,project:root.project})));
        if(hits.length>=100){hits=hits.slice(0,100);capped=true;break;}
      }
      lastResultContext={query:term,case_sensitive:el("dsSearchCase").checked};
      renderResults(hits,capped);
      status("Searched "+scanned+" eligible local source files. Search performs no writes.");
    }catch(error) {
      if(seq===requestSeq)status("Search failed: "+error.message,true);
    }finally{if(seq===requestSeq)el("dsSearchGo").disabled=false;}
  }
  async function selectHit(hit) {
    if(hit.project!==getProject()?.project) {
      const ok=await openProject(hit.project);
      if(!ok)return;
    }
    await editor.openFile(hit.path);
    if(window.matchMedia("(max-width: 720px)").matches)el("dsShowEditor").click();
    selected=hit;
    proposal=null;
    el("dsReplaceReview").disabled=el("dsSearchScope").value!=="content"||!getProject()?.trusted;
    el("dsReplaceApply").disabled=true;
    el("dsReplacePreview").hidden=true;
    remember();
    status("Selected "+hit.path+". Replace previews are confined to this file.");
  }
  async function reviewReplacement(){
    const tab=editor.currentFile(),where=getProject();
    if(!where?.trusted||!tab||tab.dirty||!lastResultContext ||
       !selected||selected.path!==tab.path||selected.project!==where.project) {
      status("Select a clean source tab in a trusted root before reviewing replacement.",true);
      return;
    }
    try{
      const review=await api(BASE+"/replace-preview",{
        project:where.project,path:tab.path,
        query:lastResultContext.query,replacement:el("dsReplaceValue").value,
        case_sensitive:lastResultContext.case_sensitive,
        expected_sha256:tab.sha256,encoding:tab.encoding
      });
      if(editor.currentFile()?.path!==tab.path ||
         editor.currentFile()?.sha256!==tab.sha256 ||
         editor.currentFile()?.dirty) {
        status("The editor changed while preparing the preview. Review again.",true);
        return;
      }
      proposal=review;
      el("dsReplacePreview").hidden=false;
      el("dsReplacePreview").textContent=review.diff||"No changes proposed.";
      el("dsReplaceApply").disabled=review.count===0;
      status(review.count+" proposed replacements. Disk remains unchanged."+
        (review.diff_truncated?" Diff preview was truncated.":""));
    }catch(error){proposal=null;el("dsReplaceApply").disabled=true;status("Replace preview refused: "+error.message,true);}
  }
  function applyReplacement(){
    if(!proposal||!window.confirm("Load this proposed text into the editor as unsaved changes? No file is saved by this action."))return;
    if(editor.applyProposal(proposal)){
      proposal=null;el("dsReplaceApply").disabled=true;
      el("dsReplacePreview").hidden=true;
      remember();
    }
  }
  async function resume(){
    const last=session();
    if(!last){status("No saved navigation session is available.");return;}
    if(!window.confirm("Resume saved local navigation? Only project paths and tab names are restored; unsaved text is never restored automatically."))return;
    const ok=await openProject(last.project);
    if(!ok)return;
    try{
      if(typeof last.directory==="string"&&last.directory!=="."&&last.directory.length<=1024)
        await list(last.directory);
      for(const file of last.files.slice(0,10)) {
        if(typeof file!=="string"||file.length>1024)continue;
        await editor.openFile(file);
      }
      if(typeof last.activeFile==="string"&&last.activeFile.length<=1024)
        await editor.openFile(last.activeFile);
      remember();
      status("Session navigation restored. Source was reloaded from disk; use manual recovery for unsaved copies.");
    }catch(error){status("Could not restore complete navigation: "+error.message,true);}
  }
  const actions=[
    ["Focus source search",()=>el("dsSearchQuery").focus()],
    ["Search file names",()=>{el("dsSearchScope").value="filename";el("dsSearchQuery").focus();}],
    ["Search all displayed roots",()=>{el("dsSearchAcross").value="all";el("dsSearchQuery").focus();}],
    ["Focus project explorer",()=>el("dsFiles").querySelector("button")?.focus()],
    ["Focus project location",()=>el("dsPath").focus()],
    ["Focus current editor",()=>el("dsMonaco .monaco-editor")?.focus()],
    ["Review current source diff",()=>el("dsDiff").click()],
    ["Split or close editor",()=>el("dsSplit").click()],
    ["Resume saved navigation",resume],
    ["Clear saved navigation",()=>el("dsClearSession").click()]
  ];
  const dialog=el("dsCommandPalette");
  function renderCommands(){
    const value=el("dsPaletteFilter").value.toLowerCase().trim();
    const list=el("dsPaletteItems");list.replaceChildren();
    for(const [name,action] of actions.filter(x=>x[0].toLowerCase().includes(value))){
      const button=document.createElement("button");
      button.type="button";button.className="ds-command";
      button.textContent=name;
      button.onclick=()=>{
        dialog.close();action();
      };
      list.appendChild(button);
    }
    if(!list.children.length){
      const empty=document.createElement("p");empty.textContent="No matching commands.";
      list.appendChild(empty);
    }
  }
  function openPalette(){
    if(!host.isConnected||dialog.open)return;
    el("dsPaletteFilter").value="";renderCommands();dialog.showModal();el("dsPaletteFilter").focus();
  }
  el("dsPaletteOpen").onclick=openPalette;
  el("dsPaletteClose").onclick=()=>dialog.close();
  el("dsPaletteFilter").oninput=renderCommands;
  el("dsPaletteFilter").onkeydown=event=>{
    if(event.key==="ArrowDown"){
      event.preventDefault();el("dsPaletteItems").querySelector("button")?.focus();
    }else if(event.key==="Enter"){
      event.preventDefault();el("dsPaletteItems").querySelector("button")?.click();
    }
  };
  el("dsPaletteItems").addEventListener("keydown",event=>{
    if(!["ArrowDown","ArrowUp"].includes(event.key))return;
    const buttons=[...el("dsPaletteItems").querySelectorAll("button")];
    const index=buttons.indexOf(document.activeElement);
    if(!buttons.length)return;
    event.preventDefault();
    buttons[(index+(event.key==="ArrowDown"?1:-1)+buttons.length)%buttons.length].focus();
  });
  const keydown=event=>{
    if(!host.isConnected)return;
    if((event.ctrlKey||event.metaKey)&&event.shiftKey&&event.key.toLowerCase()==="p"){
      event.preventDefault();event.stopPropagation();openPalette();
    }
  };
  window.addEventListener("keydown",keydown,true);
  el("dsSearchForm").addEventListener("submit",event=>{event.preventDefault();void search();});
  el("dsReplaceReview").onclick=reviewReplacement;
  el("dsReplaceApply").onclick=applyReplacement;
  el("dsRemember").onchange=()=>{
    if(el("dsRemember").checked){
      if(!window.confirm("Remember local project paths and tab names on this device? No source contents, tokens or credentials are stored.")){
        el("dsRemember").checked=false;return;
      }
      remember();status("Local navigation memory enabled.");
    }else{
      try{localStorage.removeItem(KEY);}catch{}
      status("Saved navigation removed from this browser.");
    }
  };
  el("dsRestoreSession").onclick=resume;
  el("dsClearSession").onclick=()=>{
    try{localStorage.removeItem(KEY);}catch{}
    el("dsRemember").checked=false;
    status("Saved navigation cleared. No project or source files were modified.");
  };
  const resize=el("dsPanelHandle"),columns=el("dsColumns");
  let explorerWidth=32;
  function setWidth(width){
    explorerWidth=Math.min(60,Math.max(24,width));
    columns.style.setProperty("--ds-explorer-size",explorerWidth+"%");
    resize.setAttribute("aria-valuenow",String(Math.round(explorerWidth)));
  }
  resize.addEventListener("keydown",event=>{
    let next=null;
    if(event.key==="ArrowLeft")next=explorerWidth-5;
    if(event.key==="ArrowRight")next=explorerWidth+5;
    if(event.key==="Home")next=24;
    if(event.key==="End")next=60;
    if(next!==null){event.preventDefault();setWidth(next);}
  });
  resize.addEventListener("pointerdown",event=>{
    if(window.matchMedia("(max-width: 720px)").matches)return;
    resize.setPointerCapture(event.pointerId);
    const rect=columns.getBoundingClientRect();
    const move=e=>setWidth(((e.clientX-rect.left)/rect.width)*100);
    const end=()=>{resize.removeEventListener("pointermove",move);resize.removeEventListener("pointerup",end);resize.removeEventListener("pointercancel",end);};
    resize.addEventListener("pointermove",move);
    resize.addEventListener("pointerup",end);
    resize.addEventListener("pointercancel",end);
    event.preventDefault();
  });
  function showPanel(panel){
    host.dataset.mobilePanel=panel;
    for(const [name,id]of [["explorer","dsShowExplorer"],["editor","dsShowEditor"]])
      el(id).setAttribute("aria-pressed",String(name===panel));
  }
  el("dsShowExplorer").onclick=()=>showPanel("explorer");
  el("dsShowEditor").onclick=()=>showPanel("editor");
  showPanel("explorer");
  const cleanup=()=>{
    if(host.isConnected)return;
    window.removeEventListener("keydown",keydown,true);
    window.removeEventListener("hashchange",cleanup);
    if(dialog.open)dialog.close();
  };
  window.addEventListener("hashchange",cleanup);
  return {updateRoots,remember,openPalette,resume};
}

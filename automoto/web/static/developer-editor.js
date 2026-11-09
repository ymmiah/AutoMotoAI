/* Developer Studio V2: source tabs, Unicode editor, inert highlight preview and safe saves.
 * No CDN, compiler, shell or AI invocation. Auto-save is opt-in for this session.
 */
export function mountDeveloperEditor({api,host,project,status}) {
  const BASE="/api/developer/studio";
  const root=host.querySelector("#dsEditorRoot");
  root.innerHTML=
    '<div class="ds-editor-top">'+
      '<div class="ds-tabstrip" id="dsTabs" aria-label="Open source files"></div>'+
      '<div class="ds-editor-actions">'+
        '<label for="dsEncoding">Open as</label><select class="input" id="dsEncoding" aria-label="Source file encoding">'+
        '<option value="auto">Detect UTF</option><option value="cp1252">Windows-1252</option></select>'+
        '<label for="dsLineEnding">Line endings</label><select class="input" id="dsLineEnding" aria-label="Line ending when saving">'+
        '<option value="lf">LF</option><option value="crlf">CRLF</option><option value="cr">CR</option>'+
        '<option value="none">None</option><option value="mixed">Mixed (choose to save)</option></select>'+
        '<label class="ds-auto-label"><input type="checkbox" id="dsAutosave"> Auto-save</label>'+
        '<button type="button" class="btn sm" id="dsReloadFile" disabled>Reload</button>'+
        '<button type="button" class="btn sm primary" id="dsSaveFile" disabled>Save</button>'+
      '</div></div>'+
    '<div class="ds-editor-meta"><span id="dsEditorState">Open a source file to edit.</span>'+
    '<span id="dsEditorLang">Text</span><span id="dsEditorSize"></span></div>'+
    '<div class="ds-editor-modes" role="group" aria-label="Source view">'+
      '<button type="button" class="btn sm" id="dsModeEdit" aria-pressed="true">Edit</button>'+
      '<button type="button" class="btn sm" id="dsModePreview" aria-pressed="false">Highlighted preview</button>'+
    '</div>'+
    '<label class="sr" for="dsSourceText">Source code</label>'+
    '<textarea id="dsSourceText" class="ds-source" spellcheck="false" autocorrect="off" autocapitalize="off" autocomplete="off" wrap="off" aria-label="Source code editor" disabled></textarea>'+
    '<pre class="ds-preview ds-highlight" id="dsHighlighted" tabindex="0" hidden><code id="dsHighlightCode"></code></pre>'+
    '<div class="ds-editor-footer"><span id="dsCursor">Line 1 · Column 1</span>'+
    '<span id="dsSaveHint">Saves require a trusted project and explicit confirmation.</span></div>';
  // Header labels live in the containing studio panel, outside #dsEditorRoot.
  const el=id=>host.querySelector("#"+id);
  const tabs=new Map();
  let active=null,seq=0,auto=false,timer=null,mode="edit";
  const languageMap={
    js:"javascript",jsx:"javascript",mjs:"javascript",cjs:"javascript",ts:"typescript",tsx:"typescript",
    py:"python",go:"go",rs:"rust",java:"java",kt:"kotlin",kts:"kotlin",
    swift:"swift",m:"objectivec",mm:"objectivec",cs:"csharp",
    c:"c",h:"cpp",cc:"cpp",cpp:"cpp",hpp:"cpp",
    php:"php",rb:"ruby",sh:"bash",ps1:"powershell",sql:"sql",
    html:"xml",xml:"xml",svg:"xml",css:"css",scss:"scss",
    json:"json",yml:"yaml",yaml:"yaml",toml:"ini",md:"markdown",
    tex:"latex",bib:"latex",r:"r",dart:"dart",lua:"lua"
  };
  const current=()=>active?tabs.get(active):null;
  const canSave=tab=>!!(tab && tab.dirty && !tab.saving && project()?.trusted);
  const savedKey=(tab)=>JSON.stringify([tab.path,tab.sha256,tab.text,tab.encoding,tab.newline]);
  function clearTimer(){if(timer!==null){clearTimeout(timer);timer=null;}}
  function extension(path){return(path.split(".").pop()||"").toLowerCase();}
  function cursor(){
    const field=el("dsSourceText"),start=field.selectionStart||0;
    const prefix=field.value.slice(0,start).split("\n");
    el("dsCursor").textContent="Line "+prefix.length+" · Column "+(prefix[prefix.length-1].length+1);
  }
  function showTabs(){
    const strip=el("dsTabs");strip.replaceChildren();
    if(!tabs.size){const txt=document.createElement("span");txt.className="ds-footnote";txt.textContent="No source files open";strip.appendChild(txt);}
    for(const tab of tabs.values()){
      const wrap=document.createElement("div");wrap.className="ds-tab";
      wrap.classList.toggle("active",tab.path===active);
      const select=document.createElement("button");select.type="button";
      select.textContent=tab.path.split("/").pop()+(tab.dirty?" ●":"");
      select.className="ds-tab-select";
      select.setAttribute("aria-current",tab.path===active?"page":"false");
      select.title=tab.path;
      select.onclick=()=>activate(tab.path);
      const close=document.createElement("button");close.type="button";close.className="ds-tab-close";
      close.textContent="×";close.setAttribute("aria-label","Close "+tab.path);
      close.onclick=()=>closeTab(tab.path);
      wrap.append(select,close);strip.appendChild(wrap);
    }
  }
  function update(){
    const tab=current(),field=el("dsSourceText");
    field.disabled=!tab;
    field.readOnly=!project()?.trusted;
    el("dsSaveFile").disabled=!canSave(tab);
    el("dsReloadFile").disabled=!tab;
    el("dsLineEnding").disabled=!tab;
    el("dsEncoding").disabled=false;
    el("dsModeEdit").disabled=!tab;
    el("dsModePreview").disabled=!tab;
    el("dsEditorState").textContent=!tab?"No source selected":
      tab.saving?"Saving…":tab.dirty?"Unsaved changes":tab.sha256?"Saved · SHA-256 "+tab.sha256.slice(0,12):"Read-only";
    el("dsEditorLang").textContent=tab?languageMap[extension(tab.path)]||"Plain text":"Text";
    el("dsEditorSize").textContent=tab?tab.encoding+" · "+tab.text.length+" characters":"";
    el("dsSaveHint").textContent=project()?.trusted
      ?"Ctrl/Cmd+S saves after hash verification. The original file is not silently overwritten."
      :"Trust this project before editing. Viewing never executes code.";
    showTabs();cursor();
  }
  function activate(path){
    const old=current();
    if(old){old.text=el("dsSourceText").value;}
    active=path;const tab=current();if(!tab)return;
    clearTimer();
    el("dsSourceText").value=tab.text.replace(/\r\n?/g,"\n");
    el("dsEncoding").value=tab.encoding==="cp1252"?"cp1252":"auto";
    el("dsLineEnding").value=tab.newline;
    el("dsFilename").textContent=tab.path.split("/").pop();
    el("dsFileInfo").textContent=tab.path+" · "+tab.size+" bytes · original SHA-256 "+tab.sha256;
    el("dsHighlighted").hidden=true;el("dsHighlighted").style.display="none";
    el("dsSourceText").hidden=false;el("dsSourceText").style.display="block";mode="edit";
    el("dsModeEdit").setAttribute("aria-pressed","true");
    el("dsModePreview").setAttribute("aria-pressed","false");
    update();
    if(tab.dirty && auto)schedule();
  }
  async function openFile(path,requested=null,force=false){
    const encoding=requested||el("dsEncoding").value||"auto";
    if(!project())return;
    if(tabs.has(path)&&!force){activate(path);return;}
    if(tabs.size>=10){status("Limit: close a tab before opening more than 10 source files.",true);return;}
    const request=++seq;
    try{
      const params=new URLSearchParams({project:project().project,path,encoding});
      const data=await api(BASE+"/file?"+params);
      if(!host.isConnected||request!==seq)return;
      const initial=data.text.replace(/\r\n?/g,"\n");
      tabs.set(data.path,{path:data.path,text:initial,originalText:initial,originalNewline:data.newline,
        sha256:data.sha256,size:data.size,newline:data.newline,encoding:data.encoding,dirty:false,saving:false});
      activate(data.path);
      status("Loaded "+data.path+" · "+data.encoding+" · "+data.newline+" line endings.");
    }catch(error){
      status("Cannot open source: "+error.message+". To open legacy text, select Windows-1252 and try again.",true);
    }
  }
  function changed(){
    const tab=current();if(!tab)return;
    tab.text=el("dsSourceText").value;
    tab.dirty=tab.text!==tab.originalText||tab.newline!==tab.originalNewline;
    update();
    if(auto)schedule();
  }
  function schedule(){
    clearTimer();
    if(auto && canSave(current())){const selected=active;timer=setTimeout(()=>{
      if(active===selected && canSave(current()))save(false);
    },1800);}
  }
  async function save(interactive=true){
    const tab=current(),where=project();
    if(!tab||!where||!canSave(tab))return;
    if(tab.newline==="mixed"){status("Choose LF, CRLF or CR before saving a file with mixed line endings.",true);return;}
    if(interactive && !window.confirm("Save changes to "+tab.path+"? The file will be replaced only if its disk SHA-256 is unchanged."))return;
    const text=el("dsSourceText").value;
    const oldSha=tab.sha256;
    tab.saving=true;update();
    try{
      const result=await api(BASE+"/save-file",{
        project:where.project,path:tab.path,text,
        encoding:tab.encoding,newline:tab.newline,
        expected_sha256:oldSha,confirmed:true
      });
      tab.sha256=result.sha256;tab.size=result.size;
      tab.originalText=text;tab.originalNewline=tab.newline;
      tab.dirty=tab.text!==text;
      if(!tab.dirty)tab.text=text;
      status((result.changed?"Saved":"No disk changes needed")+": "+tab.path);
      if(auto && tab.dirty)schedule();
    }catch(error){
      if(error.status===409)auto=false;
      if(error.status===409){el("dsAutosave").checked=false;clearTimer();}
      status((error.status===409?"Save blocked: the source changed on disk. Review and reload manually. ":"Save failed: ")+error.message,true);
    }finally{tab.saving=false;update();}
  }
  async function reload(requested=null){
    const tab=current(),where=project();
    if(!tab||!where)return;
    if(tab.dirty && !window.confirm("Discard unsaved changes to "+tab.path+" and reload from disk?"))return;
    const path=tab.path,encoding=requested||(tab.encoding==="cp1252"?"cp1252":"auto");
    // Keep the current tab until the replacement is fully decoded and validated.
    await openFile(path,encoding,true);
  }
  function closeTab(path){
    const tab=tabs.get(path);if(!tab)return;
    if(tab.dirty && !window.confirm("Discard unsaved changes to "+path+"?"))return;
    tabs.delete(path);
    if(active===path){active=null;activate([...tabs.keys()].at(-1)||null);}
    if(!active){el("dsSourceText").value="";el("dsFilename").textContent="Source editor";
      el("dsFileInfo").textContent="Open a source file from Explorer to begin.";}
    update();
  }
  function showHighlighted(){
    const tab=current();if(!tab)return;
    const code=el("dsHighlightCode");code.textContent=tab.text;
    const lang=languageMap[extension(tab.path)];
    try{
      if(window.hljs && window.DOMPurify){
        const highlighted=lang && window.hljs.getLanguage(lang)
          ? window.hljs.highlight(tab.text,{language:lang,ignoreIllegals:true}).value
          : window.hljs.highlightAuto(tab.text).value;
        code.innerHTML=window.DOMPurify.sanitize(highlighted,{ALLOWED_TAGS:["span"],ALLOWED_ATTR:["class"]});
      }
    }catch{code.textContent=tab.text;}
  }
  function modeSwitch(next){
    if(!current())return;
    mode=next;
    const preview=mode==="preview";
    if(preview)showHighlighted();
    const source=el("dsSourceText"),highlight=el("dsHighlighted");
    source.hidden=preview;highlight.hidden=!preview;
    source.style.display=preview?"none":"block";
    highlight.style.display=preview?"block":"none";
    el("dsModeEdit").setAttribute("aria-pressed",String(!preview));
    el("dsModePreview").setAttribute("aria-pressed",String(preview));
  }
  el("dsSourceText").addEventListener("input",changed);
  el("dsSourceText").addEventListener("keyup",cursor);
  el("dsSourceText").addEventListener("click",cursor);
  el("dsSourceText").addEventListener("keydown",event=>{
    const mod=event.ctrlKey||event.metaKey;
    if(mod && event.key.toLowerCase()==="s"){event.preventDefault();save(true);return;}
    if(event.key==="Tab"){
      event.preventDefault();
      const field=event.target,start=field.selectionStart,end=field.selectionEnd;
      if(event.shiftKey){
        const from=field.value.lastIndexOf("\n",start-1)+1;
        if(field.value.slice(from,from+2)==="  "){
          field.setRangeText("",from,from+2,"preserve");
          field.setSelectionRange(Math.max(from,start-2),Math.max(from,end-2));
        }
      }else{
        field.setRangeText("  ",start,end,"end");
      }
      changed();
    }
  });
  el("dsSaveFile").onclick=()=>save(true);
  el("dsReloadFile").onclick=()=>reload();
  el("dsLineEnding").onchange=event=>{
    const tab=current();if(!tab)return;
    tab.newline=event.target.value;
    tab.dirty=tab.text!==tab.originalText||tab.newline!==tab.originalNewline;
    update();
  };
  el("dsModeEdit").onclick=()=>modeSwitch("edit");
  el("dsModePreview").onclick=()=>modeSwitch("preview");
  el("dsEncoding").onchange=event=>{
    const tab=current();if(!tab)return;
    if(tab.dirty){el("dsEncoding").value=tab.encoding==="cp1252"?"cp1252":"auto";
      status("Save or discard unsaved edits before changing file encoding.",true);return;}
    reload(event.target.value);
  };
  el("dsAutosave").onchange=event=>{
    if(event.target.checked){
      if(!window.confirm("Enable auto-save for this session? Changes to trusted source files will be saved automatically after 1.8 seconds, with disk conflict protection.")){
        event.target.checked=false;return;
      }
      if(!project()?.trusted){event.target.checked=false;status("Trust the project to enable auto-save.",true);return;}
    }
    auto=event.target.checked;
    if(!auto)clearTimer();else schedule();
    status(auto?"Auto-save enabled for this session.":"Auto-save disabled.");
  };
  // Avoid leaving unsaved source behind during in-app navigation without warning.
  const onBeforeUnload=event=>{
    if(host.isConnected && [...tabs.values()].some(t=>t.dirty)){
      event.preventDefault();event.returnValue="";
    }
  };
  window.addEventListener("beforeunload",onBeforeUnload);
  const leaveGate=()=>![...tabs.values()].some(tab=>tab.dirty) ||
    window.confirm("You have unsaved source changes. Leave Developer Studio and discard them?");
  window.__automotoDevConfirmLeave=leaveGate;
  const cleanup=()=>{
    if(host.isConnected)return;
    window.removeEventListener("beforeunload",onBeforeUnload);
    window.removeEventListener("hashchange",cleanup);
    if(window.__automotoDevConfirmLeave===leaveGate)delete window.__automotoDevConfirmLeave;
    clearTimer();
  };
  window.addEventListener("hashchange",cleanup);
  return {
    openFile,
    reset(){
      if([...tabs.values()].some(t=>t.dirty) &&
         !window.confirm("Discard all unsaved source edits when changing project?"))return false;
      seq++; // Invalidate source fetches started for the previously open project.
      clearTimer();auto=false;el("dsAutosave").checked=false;el("dsEncoding").value="auto";
      tabs.clear();active=null;el("dsSourceText").value="";
      el("dsFilename").textContent="Source editor";el("dsFileInfo").textContent="Open a source file from Explorer to begin.";
      update();return true;
    },
    trustChanged(){if(!project()?.trusted){auto=false;el("dsAutosave").checked=false;clearTimer();}update();},
    hasUnsaved(){return [...tabs.values()].some(t=>t.dirty);}
  };
}

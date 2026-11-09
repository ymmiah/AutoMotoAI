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
        '<button type="button" class="btn sm" id="dsUndo" disabled title="Undo (Ctrl/Cmd+Z)">Undo</button>'+
        '<button type="button" class="btn sm" id="dsRedo" disabled title="Redo (Ctrl/Cmd+Shift+Z)">Redo</button>'+
        '<button type="button" class="btn sm" id="dsSplit" aria-pressed="false" disabled>Split</button>'+
        '<button type="button" class="btn sm" id="dsDiff" disabled>Review diff</button>'+
        '<button type="button" class="btn sm" id="dsSnapshot" disabled>Save recovery</button>'+
        '<button type="button" class="btn sm" id="dsRecover" disabled>Recover</button>'+
        '<label class="ds-auto-label"><input type="checkbox" id="dsRecoveryAuto"> Local recovery</label>'+
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
    '<div id="dsMonacoShell" class="ds-monaco-shell" hidden>'+
      '<div id="dsMonaco" class="ds-monaco" aria-label="Source code editor" hidden></div>'+
      '<div id="dsMonacoSplit" class="ds-monaco" aria-label="Secondary code editor" hidden></div></div>'+
    '<pre class="ds-preview ds-highlight" id="dsHighlighted" tabindex="0" hidden><code id="dsHighlightCode"></code></pre>'+
    '<pre class="ds-diff" id="dsDiffPreview" role="region" aria-label="Unsaved changes compared with disk" tabindex="0" hidden></pre>'+
    '<div class="ds-editor-footer"><span id="dsCursor">Line 1 · Column 1</span>'+
    '<span id="dsSaveHint">Saves require a trusted project and explicit confirmation.</span></div>';
  // Header labels live in the containing studio panel, outside #dsEditorRoot.
  const el=id=>host.querySelector("#"+id);
  const tabs=new Map();
  let active=null,seq=0,auto=false,timer=null,mode="edit",monacoAdapter=null,recoveryTimer=null,recoveryAuto=false,recoveryBusy=false,lastRecoveryKey="";
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
  function clearRecoveryTimer(){if(recoveryTimer!==null){clearTimeout(recoveryTimer);recoveryTimer=null;}}
  function currentFile(){
    const tab=current();
    return tab?{path:tab.path,sha256:tab.sha256,encoding:tab.encoding,
      newline:tab.newline,dirty:tab.dirty}:null;
  }
  async function storeRecovery(silent=false){
    const tab=current(),where=project();
    if(!tab||!where?.trusted||!tab.dirty||recoveryBusy)return;
    const key=JSON.stringify([where.project,tab.path,tab.sha256,tab.text,tab.newline]);
    if(key===lastRecoveryKey&&silent)return;
    recoveryBusy=true;
    try{
      const result=await api(BASE+"/snapshot",{
        project:where.project,path:tab.path,text:tab.text,
        encoding:tab.encoding,newline:tab.newline,
        expected_sha256:tab.sha256,confirmed:true
      });
      lastRecoveryKey=key;
      if(!silent)status("Private recovery snapshot recorded. Source file unchanged.");
      return result;
    }catch(error){
      status("Recovery snapshot not stored: "+error.message,true);
      if(error.status===409){recoveryAuto=false;el("dsRecoveryAuto").checked=false;clearRecoveryTimer();}
    }finally{recoveryBusy=false;}
  }
  function scheduleRecovery(){
    clearRecoveryTimer();
    if(recoveryAuto&&project()?.trusted&&current()?.dirty){
      const selected=active;
      recoveryTimer=setTimeout(()=>{
        if(active===selected&&current()?.dirty&&host.isConnected)void storeRecovery(true);
      },8000);
    }
  }
  async function recoverCopy(){
    const tab=current(),where=project();
    if(!tab||!where?.trusted)return;
    if(tab.dirty&&!window.confirm("Discard current unsaved changes to load a recovery copy?"))return;
    try{
      const params=new URLSearchParams({project:where.project,path:tab.path});
      const result=await api(BASE+"/snapshots?"+params);
      const latest=result.items?.[0];
      if(!latest){status("No private recovery snapshots found for this file.");return;}
      if(!window.confirm("Load the latest private recovery snapshot as an unsaved working copy? The disk file will not be overwritten."))return;
      const data=await api(BASE+"/recovery?"+new URLSearchParams({
        project:where.project,path:tab.path,snapshot_id:latest.snapshot_id
      }));
      if(current()!==tab)return;
      tab.text=data.text.replace(/\r\n?/g,"\n");
      tab.newline=data.newline;
      tab.dirty=tab.text!==tab.originalText||tab.newline!==tab.originalNewline;
      el("dsSourceText").value=tab.text;
      monacoAdapter?.activate(tab.path,tab.text,languageMap[extension(tab.path)]||"plaintext");
      el("dsLineEnding").value=tab.newline;
      modeSwitch("edit");
      update();
      status(data.base_sha256===tab.sha256?
        "Recovered an unsaved working copy. Review diff before saving.":
        "Recovery loaded with an older disk checksum. Refresh and reconcile before saving.",data.base_sha256!==tab.sha256);
    }catch(error){status("Recovery could not be loaded: "+error.message,true);}
  }
  async function showDiff(){
    const tab=current(),where=project();
    if(!tab||!where?.trusted)return;
    try{
      const result=await api(BASE+"/diff",{
        project:where.project,path:tab.path,text:tab.text,
        encoding:tab.encoding,newline:tab.newline,
        expected_sha256:tab.sha256,confirmed:true
      });
      modeSwitch("diff");
      el("dsDiffPreview").textContent=result.changed?result.diff:"No unsaved differences against the saved file.";
      if(result.truncated)status("Diff truncated to the first 700 lines; disk unchanged.");
      else status("Read-only diff against the saved file; no disk changes.");
    }catch(error){status("Cannot generate diff: "+error.message,true);}
  }
  function extension(path){return(path.split(".").pop()||"").toLowerCase();}
  function cursor(){
    const pos=monacoAdapter?.position();
    if(pos){el("dsCursor").textContent="Line "+pos.line+" · Column "+pos.column;return;}
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
    monacoAdapter?.setReadOnly(!project()?.trusted);
    el("dsSaveFile").disabled=!canSave(tab);
    el("dsReloadFile").disabled=!tab;
    el("dsLineEnding").disabled=!tab;
    el("dsEncoding").disabled=false;
    el("dsModeEdit").disabled=!tab;
    el("dsModePreview").disabled=!tab;
    for(const name of ["dsUndo","dsRedo","dsDiff","dsSnapshot","dsRecover"])
      el(name).disabled=!tab||!project()?.trusted;
    el("dsSplit").disabled=!tab||!monacoAdapter;
    el("dsRecoveryAuto").disabled=!project()?.trusted;
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
    clearTimer();clearRecoveryTimer();
    el("dsSourceText").value=tab.text.replace(/\r\n?/g,"\n");
    monacoAdapter?.activate(tab.path,el("dsSourceText").value,languageMap[extension(tab.path)]||"plaintext");
    el("dsEncoding").value=tab.encoding==="cp1252"?"cp1252":"auto";
    el("dsLineEnding").value=tab.newline;
    el("dsFilename").textContent=tab.path.split("/").pop();
    el("dsFileInfo").textContent=tab.path+" · "+tab.size+" bytes · original SHA-256 "+tab.sha256;
    el("dsHighlighted").hidden=true;el("dsHighlighted").style.display="none";
    el("dsDiffPreview").hidden=true;
    el("dsSourceText").hidden=!!monacoAdapter;
    el("dsSourceText").style.display=monacoAdapter?"none":"block";
    monacoAdapter?.setVisible(true);
    mode="edit";
    el("dsModeEdit").setAttribute("aria-pressed","true");
    el("dsModePreview").setAttribute("aria-pressed","false");
    update();
    if(tab.dirty && auto)schedule();
    if(tab.dirty && recoveryAuto)scheduleRecovery();
  }
  async function openFile(path,requested=null,force=false){
    const encoding=requested||el("dsEncoding").value||"auto";
    if(!project())return;
    if(tabs.has(path)&&!force){activate(path);return;}
    if(tabs.size>=10&&!tabs.has(path)){status("Limit: close a tab before opening more than 10 source files.",true);return;}
    const request=++seq;
    try{
      const params=new URLSearchParams({project:project().project,path,encoding});
      const data=await api(BASE+"/file?"+params);
      if(!host.isConnected||request!==seq)return;
      const initial=data.text.replace(/\r\n?/g,"\n");
      tabs.set(data.path,{path:data.path,text:initial,originalText:initial,originalNewline:data.newline,
        sha256:data.sha256,size:data.size,newline:data.newline,encoding:data.encoding,dirty:false,saving:false});
      // Forced reload replaces the active tab. Do not let activate() copy the
      // previous textarea value back over the fresh bytes just retrieved.
      if(force && active===data.path)active=null;
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
    if(recoveryAuto)scheduleRecovery();
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
      if(error.status===409){el("dsAutosave").checked=false;clearTimer();clearRecoveryTimer();}
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
    monacoAdapter?.remove(path);
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
    const preview=mode==="preview",diff=mode==="diff",editorView=!preview&&!diff;
    if(preview)showHighlighted();
    const source=el("dsSourceText"),highlight=el("dsHighlighted");
    source.hidden=!editorView||!!monacoAdapter;
    highlight.hidden=!preview;
    el("dsDiffPreview").hidden=!diff;
    source.style.display=(editorView&&!monacoAdapter)?"block":"none";
    highlight.style.display=preview?"block":"none";
    monacoAdapter?.setVisible(editorView);
    el("dsModeEdit").setAttribute("aria-pressed",String(editorView));
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
  el("dsUndo").onclick=()=>{
    if(!project()?.trusted)return;
    if(monacoAdapter)monacoAdapter.undo();
    else {el("dsSourceText").focus();document.execCommand("undo");changed();}
  };
  el("dsRedo").onclick=()=>{
    if(!project()?.trusted)return;
    if(monacoAdapter)monacoAdapter.redo();
    else {el("dsSourceText").focus();document.execCommand("redo");changed();}
  };
  el("dsSplit").onclick=()=>{
    if(!monacoAdapter||!current())return;
    const enabled=monacoAdapter.split(el("dsSplit").getAttribute("aria-pressed")!=="true");
    el("dsSplit").setAttribute("aria-pressed",String(enabled));
    status(enabled?"Split editor enabled; both panes share one source model. Alt+Click adds cursors.":
      "Split editor closed.");
  };
  el("dsDiff").onclick=()=>showDiff();
  el("dsSnapshot").onclick=()=>storeRecovery();
  el("dsRecover").onclick=()=>recoverCopy();
  el("dsRecoveryAuto").onchange=event=>{
    if(event.target.checked&&!window.confirm("Enable private local recovery snapshots every 8 seconds while a source file has unsaved edits? Copies remain on this computer until discarded.")){
      event.target.checked=false;return;
    }
    if(event.target.checked&&!project()?.trusted){event.target.checked=false;return;}
    recoveryAuto=event.target.checked;
    if(recoveryAuto)scheduleRecovery();else clearRecoveryTimer();
    status(recoveryAuto?"Local recovery enabled for this session.":"Automatic recovery disabled.");
  };
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
    clearTimer();clearRecoveryTimer();
    monacoAdapter?.dispose();
    monacoAdapter=null;
  };
  window.addEventListener("hashchange",cleanup);
  // V2 completion: load the bundled Monaco engine from the same authenticated
  // origin. Desktop requires the vendor files in the installed Python package.
  // Mobile or unavailable worker environments retain the accessible textarea.
  void import("./developer-monaco.js").then(({createOfflineMonaco})=>
    createOfflineMonaco({
      host,textarea:el("dsSourceText"),onChange:changed,onSave:()=>save(true),
      onCursor:(line,column)=>{el("dsCursor").textContent="Line "+line+" · Column "+column;}
    })
  ).then(adapter=>{
    if(!adapter)return;
    if(!host.isConnected){adapter.dispose();return;}
    monacoAdapter=adapter;
    const tab=current();
    if(tab)monacoAdapter.activate(tab.path,el("dsSourceText").value,
      languageMap[extension(tab.path)]||"plaintext");
    monacoAdapter.setReadOnly(!project()?.trusted);
    monacoAdapter.setVisible(mode==="edit");
    el("dsSplit").disabled=false;
    update();
  }).catch(error=>{
    if(host.isConnected)status("Monaco assets unavailable; using plain text editor. "+
      (error?.message||"Check local asset installation."),true);
  });
  function applyProposal(proposal){
    const tab=current(),where=project();
    if(!where?.trusted||!tab||tab.dirty||tab.saving||
       tab.path!==proposal.path||tab.sha256!==proposal.base_sha256||
       tab.encoding!==proposal.encoding||tab.newline!==proposal.newline){
      status("Replacement preview is stale or editor has unsaved changes. Reload and review.",true);
      return false;
    }
    tab.text=proposal.text.replace(/\\r\\n?/g,"\\n");
    tab.dirty=tab.text!==tab.originalText;
    el("dsSourceText").value=tab.text;
    monacoAdapter?.activate(tab.path,tab.text,languageMap[extension(tab.path)]||"plaintext");
    modeSwitch("edit");
    update();
    status("Proposed replacement loaded as unsaved text. Review diff and confirm Save before changing disk.");
    return true;
  }
  return {
    openFile,
    currentFile,
    openPaths:()=>[...tabs.keys()].slice(0,10),
    applyProposal,
    reset(){
      if([...tabs.values()].some(t=>t.dirty) &&
         !window.confirm("Discard all unsaved source edits when changing project?"))return false;
      seq++; // Invalidate source fetches started for the previously open project.
      clearTimer();clearRecoveryTimer();
      auto=false;recoveryAuto=false;lastRecoveryKey="";
      el("dsAutosave").checked=false;el("dsRecoveryAuto").checked=false;el("dsEncoding").value="auto";
      tabs.clear();active=null;el("dsSourceText").value="";
      monacoAdapter?.reset();
      el("dsFilename").textContent="Source editor";el("dsFileInfo").textContent="Open a source file from Explorer to begin.";
      update();return true;
    },
    trustChanged(){
      if(!project()?.trusted){
        auto=false;recoveryAuto=false;el("dsAutosave").checked=false;el("dsRecoveryAuto").checked=false;
        clearTimer();clearRecoveryTimer();
      }
      update();
    },
    hasUnsaved(){return [...tabs.values()].some(t=>t.dirty);}
  };
}

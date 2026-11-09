/* Offline Monaco editor bridge; no external URLs, no source execution.
 * Existing Developer Studio V2 API remains the only path for saving.
 */
export async function createOfflineMonaco({host,textarea,onChange,onSave,onCursor}) {
  if (!host.isConnected || typeof Worker === "undefined" ||
      window.matchMedia("(max-width: 720px)").matches) return null;
  const panel=host.querySelector("#dsMonaco");
  if (!panel) return null;
  const {monaco}=await import("/static/vendor/monaco/monaco.js");
  if (!host.isConnected) return null;
  const models=new Map();
  const splitPanel=host.querySelector("#dsMonacoSplit");
  const shell=host.querySelector("#dsMonacoShell");
  let secondary=null,splitEnabled=false;
  const narrow=window.matchMedia("(max-width: 720px)");
  let activePath=null,muted=false,enabled=true,wantedVisible=true;
  const editor=monaco.editor.create(panel,{
    value:"",language:"plaintext",readOnly:true,automaticLayout:true,
    scrollBeyondLastLine:false,minimap:{enabled:false},
    wordWrap:"off",fontSize:13,tabSize:2,
    theme:document.documentElement.dataset.theme==="light"?"vs":"vs-dark",
    accessibilitySupport:"auto",ariaLabel:"AutoMoto source code editor",
    renderWhitespace:"selection",bracketPairColorization:{enabled:true}
  });
  editor.addCommand(monaco.KeyMod.CtrlCmd|monaco.KeyCode.KeyS,()=>onSave());
  const events=[
    editor.onDidChangeModelContent(()=>{
      if (muted || !activePath) return;
      const model=editor.getModel();
      if(!model)return;
      textarea.value=model.getValue();
      onChange();
    }),
    editor.onDidChangeCursorPosition(event=>{
      if(activePath)onCursor(event.position.lineNumber,event.position.column);
    })
  ];
  const safeURI=path=>monaco.Uri.from({
    scheme:"inmemory",authority:"automoto",path:"/"+path.split("/").map(encodeURIComponent).join("/")
  });
  const adapter={
    activate(path,text,language){
      if(!enabled)return;
      let model=models.get(path);
      if(!model) {
        model=monaco.editor.createModel(text,language||"plaintext",safeURI(path));
        models.set(path,model);
      }else{
        if(model.getValue()!==text) {
          muted=true;
          try{model.setValue(text);}finally{muted=false;}
        }
        monaco.editor.setModelLanguage(model,language||"plaintext");
      }
      activePath=path;
      muted=true;
      try{editor.setModel(model);secondary?.setModel(model);}finally{muted=false;}
      editor.layout();secondary?.layout();
    },
    position(){
      const pos=editor.getPosition();
      return pos?{line:pos.lineNumber,column:pos.column}:null;
    },
    reveal(line,column){
      if(!editor.getModel())return;
      const pos={lineNumber:Math.max(1,Number(line)||1),column:Math.max(1,Number(column)||1)};
      editor.setPosition(pos);
      editor.revealPositionInCenter(pos);
      editor.focus();
    },
    setReadOnly(readOnly){
      editor.updateOptions({readOnly});
      secondary?.updateOptions({readOnly});
    },
    undo(){editor.getModel()?.undo();},
    redo(){editor.getModel()?.redo();},
    split(active){
      splitEnabled=!!active;
      if(splitEnabled&&!secondary&&splitPanel){
        secondary=monaco.editor.create(splitPanel,{
          model:editor.getModel(),readOnly:editor.getOption(monaco.editor.EditorOption.readOnly),
          automaticLayout:true,minimap:{enabled:false},scrollBeyondLastLine:false,
          fontSize:13,tabSize:2,accessibilitySupport:"auto",
          ariaLabel:"Secondary source editor",multiCursorModifier:"alt"
        });
      }
      if(secondary){
        secondary.setModel(editor.getModel());
        splitPanel.hidden=!splitEnabled;
        splitPanel.style.display=splitEnabled?"block":"none";
        panel.style.width=splitEnabled?"50%":"100%";
        secondary.layout();
        editor.layout();
      }
      return splitEnabled;
    },
    setVisible(visible){
      wantedVisible=visible;
      const useMonaco=visible&&!narrow.matches;
      panel.hidden=!useMonaco;
      panel.style.display=useMonaco?"block":"none";
      if(shell) shell.hidden=!useMonaco;
      if(splitPanel) splitPanel.hidden=!useMonaco||!splitEnabled;
      textarea.hidden=!visible||useMonaco;
      textarea.style.display=visible&&!useMonaco?"block":"none";
      if(useMonaco){
        const model=editor.getModel();
        if(model&&model.getValue()!==textarea.value){
          muted=true;
          try{model.setValue(textarea.value);}finally{muted=false;}
        }
        editor.layout();
        secondary?.layout();
      }
    },
    setTheme(theme){monaco.editor.setTheme(theme==="light"?"vs":"vs-dark");},
    remove(path){
      const model=models.get(path);
      if(model){
        if(activePath===path){editor.setModel(null);secondary?.setModel(null);activePath=null;}
        models.delete(path);model.dispose();
      }
    },
    reset(){
      editor.setModel(null);secondary?.setModel(null);activePath=null;
      for(const model of models.values())model.dispose();
      models.clear();
    },
    dispose(){
      enabled=false;
      narrow.removeEventListener("change",responsive);
      themeWatcher.disconnect();
      for(const event of events)event.dispose();
      secondary?.dispose();secondary=null;
      editor.dispose();
      for(const model of models.values())model.dispose();
      models.clear();
    }
  };
  const responsive=()=>adapter.setVisible(wantedVisible);
  narrow.addEventListener("change",responsive);
  const themeWatcher=new MutationObserver(()=>
    adapter.setTheme(document.documentElement.dataset.theme||"dark"));
  themeWatcher.observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
  adapter.setVisible(true);
  return adapter;
}

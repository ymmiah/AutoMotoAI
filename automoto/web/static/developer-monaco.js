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
  let activePath=null,muted=false,enabled=true;
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
      try{editor.setModel(model);}finally{muted=false;}
      editor.layout();
    },
    position(){
      const pos=editor.getPosition();
      return pos?{line:pos.lineNumber,column:pos.column}:null;
    },
    setReadOnly(readOnly){editor.updateOptions({readOnly});},
    setVisible(visible){
      panel.hidden=!visible;
      panel.style.display=visible?"block":"none";
      if(visible)editor.layout();
    },
    setTheme(theme){monaco.editor.setTheme(theme==="light"?"vs":"vs-dark");},
    remove(path){
      const model=models.get(path);
      if(model){if(activePath===path){editor.setModel(null);activePath=null;}models.delete(path);model.dispose();}
    },
    reset(){
      editor.setModel(null);activePath=null;
      for(const model of models.values())model.dispose();
      models.clear();
    },
    dispose(){
      enabled=false;
      for(const event of events)event.dispose();
      editor.dispose();
      for(const model of models.values())model.dispose();
      models.clear();
    }
  };
  panel.hidden=false;
  textarea.hidden=true;
  textarea.style.display="none";
  return adapter;
}

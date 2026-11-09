/* Developer Studio V7: bounded private source symbols, lexical references and outline. */
export function mountDeveloperIndex({api,host,getProject,editor,status}) {
  const BASE="/api/developer/studio/index";
  const root=host.querySelector("#dsIndexRoot");
  root.innerHTML=
    '<section class="ds-index-panel" aria-label="Source index">'+
      '<div class="ds-index-head"><h3>Source intelligence · V7</h3>'+
        '<span class="ds-readonly">LOCAL · NO EXECUTION</span></div>'+
      '<div class="ds-index-body">'+
        '<div class="ds-index-controls">'+
          '<button type="button" class="btn sm primary" id="dsIndexRefresh" disabled>Refresh source index</button>'+
          '<button type="button" class="btn sm" id="dsIndexOutline" disabled>Current file outline</button>'+
          '<label for="dsIndexQuery">Symbols</label>'+
          '<input class="input" id="dsIndexQuery" maxlength="100" placeholder="Search symbol names" disabled>'+
          '<button type="button" class="btn sm" id="dsIndexSearch" disabled>Find symbols</button>'+
        '</div>'+
        '<p id="dsIndexState" class="ds-footnote" role="status" aria-live="polite">Open a local project to index source symbols.</p>'+
        '<div id="dsIndexResults" class="ds-index-results" role="region" tabindex="0" aria-label="Symbol index results"></div>'+
        '<p class="ds-footnote">Python AST symbols are syntax-grounded. Other supported languages use approximate declarations; references are lexical occurrences, not verified semantic references. No source is uploaded or modified.</p>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id), area=el("dsIndexResults");
  let opened=null,selected=null,seq=0,busy=false;
  function state(message,bad=false){
    const node=el("dsIndexState");node.textContent=message;node.classList.toggle("ds-error",bad);
  }
  function enabled(){
    const active=!!getProject(),hasFile=active&&!!editor.currentFile();
    el("dsIndexRefresh").disabled=busy||!active;
    el("dsIndexSearch").disabled=busy||!active;
    el("dsIndexQuery").disabled=!active;
    el("dsIndexOutline").disabled=busy||!hasFile;
  }
  function clear(){area.replaceChildren();}
  function empty(message){
    clear();const node=document.createElement("p");node.className="ds-footnote";
    node.textContent=message;area.appendChild(node);
  }
  async function navigate(path,line,column){
    const project=getProject();
    if(!project||busy)return;
    await editor.openFile(path);
    // Reveal only if file was actually opened; refused dirty-tab switches remain safe.
    editor.revealLocation(path,(line||0)+1,(column||0)+1);
  }
  function results(items,kind){
    clear();
    if(!items?.length)return empty("No "+kind+" found in the indexed scope.");
    for(const item of items.slice(0,100)){
      const line=document.createElement("div");line.className="ds-index-result";
      const button=document.createElement("button");button.type="button";
      button.className="ds-index-location";
      const relative=item.path||selected||"";
      button.textContent=(item.name||item.identifier||"Occurrence")+
        " · "+relative+" : "+(item.line+1);
      button.onclick=()=>void navigate(relative,item.line,item.character);
      const detail=document.createElement("span");detail.className="ds-index-meta";
      detail.textContent=(item.parser||item.confidence||"lexical")+
        (item.kind?" · "+item.kind:"");
      line.append(button,detail);
      if(item.name&&kind!=="file outline"){
        const refs=document.createElement("button");refs.type="button";
        refs.className="btn sm";refs.textContent="Find occurrences";
        refs.setAttribute("aria-label","Find lexical occurrences of "+item.name);
        refs.onclick=()=>void references(item.name);
        line.appendChild(refs);
      }
      area.appendChild(line);
    }
  }
  async function refresh(){
    const project=getProject();if(!project||busy)return;
    const id=++seq;busy=true;enabled();state("Rehashing bounded local sources…");
    try{
      const result=await api(BASE+"/refresh",{project:project.project});
      if(id!==seq||getProject()?.project!==project.project)return;
      state(result.indexed_files+" files indexed · "+result.symbol_count+" symbols · "+
        result.reparsed_files+" changed · "+result.reused_files+" reused"+
        (result.truncated?" · partial scan":"")+".");
      empty("Index ready. Search a symbol or open the file outline.");
    }catch(error){state("Source indexing failed: "+error.message,true);}
    finally{busy=false;enabled();}
  }
  async function search(){
    const project=getProject();if(!project||busy)return;
    const id=++seq;busy=true;enabled();state("Searching indexed declarations…");
    try{
      const result=await api(BASE+"/symbols",{
        project:project.project,query:el("dsIndexQuery").value.trim()
      });
      if(id!==seq||getProject()?.project!==project.project)return;
      results(result.items,"symbols");
      state(result.items.length+" symbols found"+
        (result.truncated?" (capped or partial index)":"")+
        " · index generation "+result.generation+".");
    }catch(error){state("Symbol search failed: "+error.message,true);}
    finally{busy=false;enabled();}
  }
  async function references(identifier){
    const project=getProject();if(!project||busy)return;
    const id=++seq;busy=true;enabled();state("Looking up lexical occurrences…");
    try{
      const result=await api(BASE+"/references",{project:project.project,identifier});
      if(id!==seq||getProject()?.project!==project.project)return;
      results(result.items.map(x=>({...x,identifier})),"occurrences");
      state(result.items.length+" lexical occurrences of "+identifier+
        ". Not a semantic reference graph.");
    }catch(error){state("Reference lookup failed: "+error.message,true);}
    finally{busy=false;enabled();}
  }
  async function outline(){
    const project=getProject(),context=editor.lspContext();
    if(!project||!context||busy)return;
    const id=++seq;busy=true;enabled();state("Parsing current editor buffer…");
    try{
      const result=await api(BASE+"/outline",{project:project.project,
        path:context.path,text:context.text});
      if(id!==seq||getProject()?.project!==project.project||
        editor.currentFile()?.path!==context.path)return;
      results(result.symbols.map(x=>({...x,path:context.path,parser:result.parser})),"file outline");
      state((result.symbols?.length||0)+" definitions · parser: "+result.parser+
        (result.parse_error?" · "+result.parse_error:"")+
        " · unsaved buffer only; source unchanged.");
    }catch(error){state("Current file parsing failed: "+error.message,true);}
    finally{busy=false;enabled();}
  }
  async function projectChanged(){
    seq++;busy=false;selected=null;opened=getProject()?.project||null;
    clear();enabled();
    if(opened)await refresh();
    else state("Open a local project to index source symbols.");
  }
  function fileChanged(path){
    selected=path||null;enabled();
    if(path)void outline();
  }
  el("dsIndexRefresh").onclick=()=>void refresh();
  el("dsIndexSearch").onclick=()=>void search();
  el("dsIndexQuery").onkeydown=event=>{
    if(event.key==="Enter"){event.preventDefault();void search();}
  };
  el("dsIndexOutline").onclick=()=>void outline();
  enabled();
  return {projectChanged,fileChanged,refresh};
}

/* Developer Studio V5: evidence-backed project/language details; no tool execution. */
export function mountDeveloperLanguageIntelligence({api,host,getProject,editor,status}) {
  const BASE="/api/developer/studio/language";
  const root=host.querySelector("#dsLanguageRoot");
  root.innerHTML=
    '<section class="ds-language-panel" aria-label="Language intelligence">'+
      '<div class="ds-language-head"><h3>Language intelligence</h3>'+
        '<span class="ds-readonly">DETECTION ONLY · NO EXECUTION</span></div>'+
      '<div class="ds-language-body">'+
        '<div class="ds-language-facts">'+
          '<div><span class="ds-eyebrow">Primary language</span><strong id="dsDetectedPrimary">Not inspected</strong></div>'+
          '<div><span class="ds-eyebrow">Frameworks</span><strong id="dsDetectedFrameworks">Not inspected</strong></div>'+
          '<div><span class="ds-eyebrow">Current file</span><strong id="dsDetectedFile">No file selected</strong></div>'+
          '<div><span class="ds-eyebrow">Confidence</span><strong id="dsDetectedConfidence">Not checked</strong></div>'+
        '</div>'+
        '<div class="ds-language-controls">'+
          '<label for="dsLanguageOverride">Syntax mode for current file</label>'+
          '<select class="input" id="dsLanguageOverride" disabled><option value="">Automatic detection</option></select>'+
          '<button class="btn sm" type="button" id="dsLanguageTools" disabled>Check local tools</button>'+
        '</div>'+
        '<p class="ds-footnote" id="dsDetectedEvidence" role="status" aria-live="polite">Open an approved local project to inspect its structure.</p>'+
        '<div class="ds-language-tools" id="dsDetectedTools" aria-label="Local development toolchain checks"></div>'+
        '<p class="ds-footnote" id="dsLanguageLimits">Recognition does not establish compiler, language server or debugger compatibility.</p>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id);
  const overrides=new Map();
  const modes=new Map();
  let sequence=0, selectedPath=null, loaded=false, currentProject=null;
  const set=id=>value=>{el(id).textContent=value;};
  const primary=set("dsDetectedPrimary"), frameworks=set("dsDetectedFrameworks");
  const file=set("dsDetectedFile"), confidence=set("dsDetectedConfidence");
  const evidence=set("dsDetectedEvidence");
  const tools=el("dsDetectedTools");

  async function loadRegistry() {
    if(loaded)return;
    const registry=await api(BASE+"/registry");
    if(!root.isConnected)return;
    const select=el("dsLanguageOverride");
    for(const language of registry.languages||[]) {
      if(!language.id||!language.monaco)continue;
      const option=document.createElement("option");
      option.value=language.monaco;
      option.textContent=language.name+" ("+language.id+")";
      select.appendChild(option);
    }
    loaded=true;
  }
  function toolRows(items,wasChecked) {
    tools.replaceChildren();
    if(!items?.length) {
      const note=document.createElement("span");
      note.textContent="No toolchain requirement identified for this selection.";
      tools.appendChild(note);return;
    }
    for(const item of items) {
      const line=document.createElement("div");
      line.className="ds-language-tool";
      const name=document.createElement("strong");
      name.textContent=item.tool;
      const detail=document.createElement("span");
      detail.textContent=!wasChecked?"Not checked":item.status==="available"?
        "Executable located · version not verified":"Unavailable on the host PATH";
      line.append(name,detail);tools.appendChild(line);
    }
  }
  async function inspect(path=null,probeTools=false) {
    const workspace=getProject();
    if(!workspace)return;
    selectedPath=path;
    el("dsLanguageOverride").disabled=!path;
    el("dsLanguageTools").disabled=false;
    const id=++sequence;
    if(!loaded) {
      try{await loadRegistry();}catch(error){
        evidence("Unable to load the language catalogue: "+error.message);return;
      }
    }
    try {
      const result=await api(BASE+"/detect",{
        project:workspace.project,...(path?{path}:{}),probe_tools:!!probeTools
      });
      if(id!==sequence||!root.isConnected||getProject()?.project!==workspace.project)return;
      primary(result.primary_language||"Unknown");
      frameworks(result.frameworks?.length?result.frameworks.map(f=>f.name).join(", "):"No confirmed framework");
      const selected=result.file;
      file(path?(selected?.language||selected?.candidates?.join(" / ")||"Unknown"):"No file selected");
      confidence(selected?.confidence||"Project evidence");
      const details=[
        ...(selected?.evidence||[]),
        ...(result.frameworks||[]).flatMap(f=>f.evidence||[])
      ];
      evidence(details.length?"Evidence: "+details.join(" · "):"No decisive language or framework markers found.");
      if(result.scan_truncated)evidence(el("dsDetectedEvidence").textContent+" Project scan was bounded and may be incomplete.");
      el("dsLanguageLimits").textContent="Registry "+result.schema_version+
        " · read-only detection · no scripts run · available tools are executable-path checks only.";
      toolRows(result.toolchains||[],probeTools);
      const select=el("dsLanguageOverride");
      if(path) {
        modes.set(path,selected?.monaco||"plaintext");
        const effective=overrides.get(path)||"";
        select.value=effective;
        // Monaco is already mounted by the editor. Apply only language metadata.
        editor.setLanguageMode(path,effective||modes.get(path));
      } else select.value="";
    }catch(error){
      if(id===sequence)evidence("Language inspection unavailable: "+error.message);
    }
  }
  function reset() {
    sequence++;
    overrides.clear();modes.clear();selectedPath=null;
    primary("Not inspected");frameworks("Not inspected");file("No file selected");
    confidence("Not checked");tools.replaceChildren();
    el("dsLanguageTools").disabled=true;
    el("dsLanguageOverride").disabled=true;
    currentProject=getProject()?.project||null;
    if(currentProject)void inspect();
  }
  el("dsLanguageOverride").onchange=event=>{
    if(!selectedPath)return;
    const chosen=event.target.value;
    if(chosen)overrides.set(selectedPath,chosen);
    else overrides.delete(selectedPath);
    editor.setLanguageMode(selectedPath,chosen||modes.get(selectedPath)||"plaintext");
    status(chosen?"Syntax mode overridden for this file only. Source unchanged.":
      "Automatic syntax mode restored. Source unchanged.");
  };
  el("dsLanguageTools").onclick=()=>void inspect(selectedPath,true);
  return {inspect,reset};
}

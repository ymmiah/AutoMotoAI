/* Developer Studio V2: trusted source explorer plus conflict-safe file editor. */
import {mountDeveloperEditor} from "./developer-editor.js";
export async function mountDeveloperStudio({api,page,toast}) {
  const BASE="/api/developer/studio";
  const host=page("Developer Studio",
    "V2 · Source Editor. Work with approved local projects, edit selected source files after explicit trust, and save with SHA-256 conflict checks. No shell, build or AI execution.",
    '<div class="ds-shell">'+
      '<section class="ds-toolbar" aria-label="Choose project">'+
        '<label for="dsRoots">Approved locations</label><select id="dsRoots" class="input"><option value="">Choose a location</option></select>'+
        '<label for="dsPath">Project folder</label><input id="dsPath" class="input" type="text" maxlength="1024" placeholder="A folder inside your AutoMoto workspace or allowed roots">'+
        '<button class="btn primary" type="button" id="dsOpen">Open project</button>'+
        '<button class="btn" type="button" id="dsReload">Refresh locations</button></section>'+
      '<section class="ds-summary" aria-label="Workspace trust">'+
        '<div><span class="ds-eyebrow">CURRENT WORKSPACE</span><strong id="dsProject">No project open</strong>'+
        '<span id="dsTrustState">Select a local folder to begin.</span></div>'+
        '<button class="btn" id="dsTrust" type="button" hidden>Trust this project</button></section>'+
      '<p class="ds-warning" role="note">Source editing is permitted only for expressly trusted local folders. Every save checks the original disk checksum. No source execution or automatic cloud processing is enabled.</p>'+
      '<div class="ds-columns">'+
        '<section class="ds-panel" aria-label="Project files"><div class="ds-panel-header"><h3>Explorer</h3><button class="btn sm" type="button" id="dsParent" disabled>Up</button></div>'+
          '<p class="ds-breadcrumb" id="dsBreadcrumb">No folder selected</p>'+
          '<div id="dsFiles" class="ds-files" role="list"></div>'+
          '<p id="dsLimit" class="ds-footnote"></p></section>'+
        '<section class="ds-panel" aria-label="Source editor"><div class="ds-panel-header"><h3 id="dsFilename">Source editor</h3><span class="ds-readonly">NO EXECUTION</span></div>'+
          '<p class="ds-footnote" id="dsFileInfo">Select a source file. V2 supports UTF-8, UTF-16 BOM and explicit Windows-1252.</p>'+
          '<div id="dsEditorRoot"></div></section>'+
      '</div>'+
      '<p class="ds-status" id="dsStatus" role="status" aria-live="polite">Developer Studio V1 is ready to open an approved local project.</p>'+
    '</div>');
  const byId=id=>host.querySelector("#"+id);
  let project=null,directory=".",sequence=0;
  const editor=mountDeveloperEditor({api,host,project:()=>project,status});

  function status(message,bad=false) {
    const element=byId("dsStatus");
    if(!element)return;
    element.textContent=message;
    element.classList.toggle("ds-error",bad);
  }
  function option(select,value,label) {
    const node=document.createElement("option");
    node.value=value;node.textContent=label;select.appendChild(node);
  }
  async function locations() {
    const response=await api(BASE+"/roots");
    const select=byId("dsRoots");
    select.replaceChildren();
    option(select,"","Choose an approved location");
    const included=new Set();
    for(const item of [...response.roots,...response.recent]) {
      if(included.has(item.project))continue;
      included.add(item.project);
      option(select,item.project,(item.trusted?"Trusted: ":"Folder: ")+item.project);
    }
    if(project && included.has(project.project))select.value=project.project;
    else if(!project && response.roots.length && !byId("dsPath").value) {
      select.value=response.roots[0].project;
      byId("dsPath").value=response.roots[0].project;
    }
  }
  function showTrust() {
    byId("dsProject").textContent=project?project.project:"No project open";
    byId("dsTrustState").textContent=project
      ? project.trusted?"Trusted project · source editing enabled; code execution disabled.":"Restricted workspace · source browsing only."
      :"Select a local folder to begin.";
    byId("dsTrust").hidden=!project;
    byId("dsTrust").textContent=project?.trusted?"Revoke trust":"Trust this project";
  }
  function clearPreview() {
    byId("dsFilename").textContent="Source editor";
    byId("dsFileInfo").textContent="Choose a source file. Source editing requires trust.";
  }
  async function openProject(path) {
    try {
      const data=await api(BASE+"/open",{project:path});
      if(project?.project!==data.project && !editor.reset())return;
      project=data;
      byId("dsPath").value=data.project;
      directory=".";
      showTrust();
      clearPreview();
      await locations();
      await list(".");
      status(data.trusted?"Trusted project opened; source editing is enabled.":"Restricted project opened in read-only mode.");
    } catch(error) {
      status("Unable to open project: "+error.message,true);
    }
  }
  async function list(dir) {
    if(!project)return;
    const expected=++sequence;
    try {
      const params=new URLSearchParams({project:project.project,directory:dir});
      const result=await api(BASE+"/tree?"+params);
      if(expected!==sequence||!host.isConnected)return;
      directory=result.directory;
      byId("dsBreadcrumb").textContent=directory==="."?project.name:project.name+" / "+directory;
      byId("dsParent").disabled=directory===".";
      const area=byId("dsFiles");area.replaceChildren();
      if(!result.items.length) {
        const empty=document.createElement("p");
        empty.className="ds-footnote";empty.textContent="No browsable source files in this folder.";
        area.appendChild(empty);
      }
      for(const entry of result.items) {
        const button=document.createElement("button");
        button.className="ds-entry";
        button.type="button";
        // Keep native button semantics for keyboard and screen-reader users.
        const mark=document.createElement("span");
        mark.className="ds-file-icon";
        mark.textContent=entry.directory?"▸":"•";
        const title=document.createElement("span");
        title.className="ds-file-name";title.textContent=entry.name;
        button.append(mark,title);
        button.title=entry.path;
        button.addEventListener("click",()=>entry.directory?list(entry.path):preview(entry.path));
        area.appendChild(button);
      }
      byId("dsLimit").textContent=result.truncated?"Showing the first 200 entries. Narrow the selected folder.":"Symlinks, generated dependencies and secret paths are excluded.";
    }catch(error) {
      status("Unable to list project folder: "+error.message,true);
    }
  }
  async function preview(path) {
    if(!project)return;
    return editor.openFile(path);
  }
  byId("dsRoots").addEventListener("change",event=>{
    if(event.target.value)byId("dsPath").value=event.target.value;
  });
  byId("dsOpen").addEventListener("click",()=>openProject(byId("dsPath").value.trim()));
  byId("dsPath").addEventListener("keydown",event=>{
    if(event.key==="Enter"){event.preventDefault();openProject(byId("dsPath").value.trim());}
  });
  byId("dsReload").addEventListener("click",()=>locations().then(()=>status("Approved locations refreshed.")).catch(e=>status(e.message,true)));
  byId("dsParent").addEventListener("click",()=>{
    const parts=directory==="."?[]:directory.split("/");
    parts.pop();list(parts.join("/")||".");
  });
  byId("dsTrust").addEventListener("click",async()=>{
    if(!project)return;
    const next=!project.trusted;
    if(!window.confirm(next
      ?"Trust this project for source editing? Saves still require verification and approval. No code execution will occur."
      :"Revoke this project's trusted status? Source files will not change."))return;
    try {
      project=await api(BASE+"/trust",{project:project.project,trusted:next,confirmed:true});
      showTrust();editor.trustChanged();await locations();
      status(next?"Project trusted. Editing enabled; execution disabled.":"Project trust revoked; editing disabled.");
    }catch(error){status("Unable to change trust: "+error.message,true);}
  });
  try {
    await locations();
  }catch(error) {
    status("Developer Studio V1 is available only on the local AutoMoto installation: "+error.message,true);
  }
  return host;
}

/* Developer Studio V1: read-only local workspace browser; no source execution. */
export async function mountDeveloperStudio({api,page,toast}) {
  const BASE="/api/developer/studio";
  const host=page("Developer Studio",
    "V1 · Trusted Workspace. Browse permitted projects safely. Editing, terminal execution and AI file changes are not enabled in this milestone.",
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
      '<p class="ds-warning" role="note">Project files are previewed as inert text. V1 never edits source files or runs scripts. Trust is an explicit future-use preference, not permission to execute anything.</p>'+
      '<div class="ds-columns">'+
        '<section class="ds-panel" aria-label="Project files"><div class="ds-panel-header"><h3>Explorer</h3><button class="btn sm" type="button" id="dsParent" disabled>Up</button></div>'+
          '<p class="ds-breadcrumb" id="dsBreadcrumb">No folder selected</p>'+
          '<div id="dsFiles" class="ds-files" role="list"></div>'+
          '<p id="dsLimit" class="ds-footnote"></p></section>'+
        '<section class="ds-panel" aria-label="Read-only source preview"><div class="ds-panel-header"><h3 id="dsFilename">Source preview</h3><span class="ds-readonly">READ ONLY</span></div>'+
          '<p class="ds-footnote" id="dsFileInfo">Choose a source file. UTF-8 text files up to 128 KiB can be previewed.</p>'+
          '<pre class="ds-preview" id="dsPreview" tabindex="0">No file selected.</pre></section>'+
      '</div>'+
      '<p class="ds-status" id="dsStatus" role="status" aria-live="polite">Developer Studio V1 is ready to open an approved local project.</p>'+
    '</div>');
  const byId=id=>host.querySelector("#"+id);
  let project=null,directory=".",sequence=0;

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
      ? project.trusted?"Trusted root · source files are still read-only.":"Restricted workspace · read-only browsing."
      :"Select a local folder to begin.";
    byId("dsTrust").hidden=!project;
    byId("dsTrust").textContent=project?.trusted?"Revoke trust":"Trust this project";
  }
  function clearPreview() {
    byId("dsFilename").textContent="Source preview";
    byId("dsFileInfo").textContent="Choose a source file. UTF-8 text files up to 128 KiB can be previewed.";
    byId("dsPreview").textContent="No file selected.";
  }
  async function openProject(path) {
    try {
      const data=await api(BASE+"/open",{project:path});
      project=data;
      byId("dsPath").value=data.project;
      directory=".";
      showTrust();
      clearPreview();
      await locations();
      await list(".");
      status(data.trusted?"Trusted project opened in V1 read-only mode.":"Restricted project opened in V1 read-only mode.");
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
    try {
      const params=new URLSearchParams({project:project.project,path});
      const result=await api(BASE+"/preview?"+params);
      if(!host.isConnected)return;
      byId("dsFilename").textContent=result.path.split("/").pop()||"Source";
      byId("dsFileInfo").textContent=result.path+" · "+result.size+" bytes · SHA-256 "+result.sha256;
      byId("dsPreview").textContent=result.text;
      status("Opened inert, read-only preview: "+result.path);
    }catch(error) {
      clearPreview();
      status("Unable to preview source: "+error.message,true);
    }
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
      ?"Trust this project for future development features? V1 remains read-only."
      :"Revoke this project's trusted status? Source files will not change."))return;
    try {
      project=await api(BASE+"/trust",{project:project.project,trusted:next,confirmed:true});
      showTrust();await locations();
      status(next?"Trust recorded; V1 remains read-only.":"Project trust revoked.");
    }catch(error){status("Unable to change trust: "+error.message,true);}
  });
  try {
    await locations();
  }catch(error) {
    status("Developer Studio V1 is available only on the local AutoMoto installation: "+error.message,true);
  }
  return host;
}

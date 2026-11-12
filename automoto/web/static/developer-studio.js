/* Developer Studio V2: trusted source explorer plus conflict-safe file editor. */
import {mountDeveloperEditor} from "./developer-editor.js";
import {mountDeveloperNavigation} from "./developer-navigation.js";
import {mountDeveloperLanguageIntelligence} from "./developer-language.js";
import {mountDeveloperLSP} from "./developer-lsp.js";
import {mountDeveloperIndex} from "./developer-index.js";
import {mountDeveloperAdapters} from "./developer-adapters.js";
import {mountDeveloperLatex} from "./developer-latex.js";
import {mountDeveloperBibliography} from "./developer-bibliography.js";
import {mountDeveloperTexBuild} from "./developer-texbuild.js";
import {mountDeveloperManuscripts} from "./developer-manuscripts.js";
import {mountDeveloperJavaScript} from "./developer-javascript.js";
import {mountDeveloperFrontend} from "./developer-frontend.js";
import {mountDeveloperData} from "./developer-data.js";
import {mountDeveloperPHP} from "./developer-php.js";
import {mountDeveloperPython} from "./developer-python.js";
import {mountDeveloperGo} from "./developer-go.js";
import {mountDeveloperRust} from "./developer-rust.js";
import {mountDeveloperNative} from "./developer-native.js";
import {mountDeveloperJvm} from "./developer-jvm.js";
import {mountDeveloperDotnet} from "./developer-dotnet.js";
import {mountDeveloperAndroid} from "./developer-android.js";
import {mountDeveloperSwift} from "./developer-swift.js";
import {mountDeveloperMobile} from "./developer-mobile.js";
import {mountDeveloperShell} from "./developer-shell.js";
import {mountDeveloperScripting} from "./developer-scripting.js";
import {mountDeveloperScience} from "./developer-science.js";
import {mountDeveloperFunctional} from "./developer-functional.js";
import {mountDeveloperBeam} from "./developer-beam.js";
import {mountDeveloperLogic} from "./developer-logic.js";
export async function mountDeveloperStudio({api,page,toast}) {
  const BASE="/api/developer/studio";
  const host=page("Developer Studio",
    "V31 · Haskell, OCaml, Lisp, Scheme and Prolog alongside 30 earlier language milestones.",
    '<div class="ds-shell">'+
      '<section class="ds-toolbar" aria-label="Choose project">'+
        '<label for="dsRoots">Approved locations</label><select id="dsRoots" class="input"><option value="">Choose a location</option></select>'+
        '<label for="dsPath">Project folder</label><input id="dsPath" class="input" type="text" maxlength="1024" placeholder="A folder inside your AutoMoto workspace or allowed roots">'+
        '<button class="btn primary" type="button" id="dsOpen">Open project</button>'+
        '<button class="btn" type="button" id="dsReload">Refresh locations</button></section>'+
      '<div class="ds-v4-roots" id="dsRootStrip" role="group" aria-label="Open and approved project roots" hidden></div>'+
      '<section class="ds-summary" aria-label="Workspace trust">'+
        '<div><span class="ds-eyebrow">CURRENT WORKSPACE</span><strong id="dsProject">No project open</strong>'+
        '<span id="dsTrustState">Select a local folder to begin.</span></div>'+
        '<button class="btn" id="dsTrust" type="button" hidden>Trust this project</button></section>'+
      '<p class="ds-warning" role="note">Source editing is permitted only for expressly trusted local folders. Every save checks the original disk checksum. Language servers and external toolchain adapters run only after separate approval; these programs are not OS-sandboxed and may modify project files. No automatic cloud processing is enabled.</p>'+
      '<div id="dsLanguageRoot" aria-label="Project language and framework intelligence"></div>'+
      '<div id="dsLspRoot" aria-label="Approved local language server controls"></div>'+ 
      '<div id="dsIndexRoot" aria-label="Source symbol index and file outline"></div>'+ 
      '<div id="dsAdaptersRoot" aria-label="Explicitly approved local toolchain and debugger adapters"></div>'+ 
      '<div id="dsLatexRoot" aria-label="LaTeX multi-file thesis authoring"></div>'+ 
      '<div id="dsBibliographyRoot" aria-label="Citation evidence and bibliography preflight"></div>'+ 
      '<div id="dsTexBuildRoot" aria-label="Approved TeX build and ephemeral PDF preview"></div>'+ 
      '<div id="dsManuscriptsRoot" aria-label="Typst Quarto and source-verified Research Studio review packages"></div>'+ 
      '<div id="dsJavaScriptRoot" aria-label="Node.js JavaScript TypeScript project tasks"></div>'+ 
      '<div id="dsFrontendRoot" aria-label="Frontend project inspection, accessibility and static responsive preview"></div>'+ 
      '<div id="dsDataRoot" aria-label="Bounded SQLite and GraphQL read-only inspection"></div>'+ 
      '<div id="dsPhpRoot" aria-label="PHP and WordPress security and approved tool workflows"></div>'+ 
      '<div id="dsPythonRoot" aria-label="Python packaging, uv, type checking and approved tests"></div>'+ 
      '<div id="dsGoRoot" aria-label="Go modules workspaces profiling and approved build test vet"></div>'+ 
      '<div id="dsRustRoot" aria-label="Rust workspaces cargo clippy rustfmt and debugger review"></div>'+ 
      '<div id="dsNativeRoot" aria-label="C and C++ CMake compiler CTest and sanitiser workflows"></div>'+
      '<div id="dsJvmRoot" aria-label="Java JVM Maven Gradle JUnit and source compatibility workflows"></div>'+
      '<div id="dsDotnetRoot" aria-label="C sharp dotnet SDK NuGet MSBuild test and debugger review"></div>'+
      '<div id="dsAndroidRoot" aria-label="Kotlin Android SDK Gradle Compose and emulator inspection"></div>'+
      '<div id="dsSwiftRoot" aria-label="Swift SwiftUI Objective C SwiftPM Xcode simulator and SourceKit LSP inspection"></div>'+
      '<div id="dsMobileRoot" aria-label="Flutter Dart React Native package management device and bridge evidence"></div>'+
      '<div id="dsShellRoot" aria-label="Bash Zsh Fish PowerShell Batch script analysis and fixed fixture diagnostics"></div>'+
      '<div id="dsScriptingRoot" aria-label="Ruby Lua Perl Groovy package metadata source syntax lint and test evidence"></div>'+
      '<div id="dsScienceRoot" aria-label="R Julia MATLAB Octave scientific plotting Jupyter notebooks and reproducibility evidence"></div>'+
      '<div id="dsFunctionalRoot" aria-label="Scala F sharp Clojure source manifest and approved fixed tool evidence"></div>'+
      '<div id="dsBeamRoot" aria-label="Elixir Erlang Gleam source and fixed local BEAM tool evidence"></div>'+
      '<div id="dsLogicRoot" aria-label="Haskell OCaml Lisp Scheme Prolog source and fixed interpreter tools"></div>'+  
      '<div id="dsNavigationRoot" aria-label="Search and navigate project files"></div>'+
      '<div class="ds-mobile-switch" role="group" aria-label="Editor panels"><button type="button" id="dsShowExplorer" class="btn sm" aria-pressed="true">Explorer</button><button type="button" id="dsShowEditor" class="btn sm" aria-pressed="false">Editor</button></div>'+
      '<div class="ds-columns" id="dsColumns">'+
        '<section class="ds-panel" aria-label="Project files"><div class="ds-panel-header"><h3>Explorer</h3><div class="ds-explorer-actions"><button class="btn sm" type="button" id="dsCreate" disabled>New</button><button class="btn sm" type="button" id="dsRename" disabled>Rename</button><button class="btn sm" type="button" id="dsTrash" disabled>Archive</button><button class="btn sm" type="button" id="dsRestore" disabled>Restore</button><button class="btn sm" type="button" id="dsParent" disabled>Up</button></div></div>'+
          '<p class="ds-breadcrumb" id="dsBreadcrumb">No folder selected</p>'+
          '<div id="dsFiles" class="ds-files" role="list"></div>'+
          '<p id="dsLimit" class="ds-footnote"></p></section>'+
        '<div id="dsPanelHandle" class="ds-panel-handle" role="separator" tabindex="0" aria-label="Resize project explorer" aria-orientation="vertical" aria-valuemin="24" aria-valuemax="60" aria-valuenow="32"></div>'+
        '<section class="ds-panel" aria-label="Source editor"><div class="ds-panel-header"><h3 id="dsFilename">Source editor</h3><span class="ds-readonly">NO EXECUTION</span></div>'+
          '<p class="ds-footnote" id="dsFileInfo">Select a source file. V2 supports UTF-8, UTF-16 BOM and explicit Windows-1252.</p>'+
          '<div id="dsEditorRoot"></div></section>'+
      '</div>'+
      '<p class="ds-status" id="dsStatus" role="status" aria-live="polite">Developer Studio V1 is ready to open an approved local project.</p>'+
    '</div>');
  const byId=id=>host.querySelector("#"+id);
  let project=null,directory=".",sequence=0;
  let languageIntelligence,lsp,index,adapters,latex,bibliography,texBuild,manuscripts,javascript,frontend,dataStudio,phpStudio,pythonStudio,goStudio,rustStudio,nativeStudio,jvmStudio,dotnetStudio,androidStudio,swiftStudio,mobileStudio,shellStudio,scriptingStudio,scienceStudio,functionalStudio,beamStudio,logicStudio;
  const editor=mountDeveloperEditor({api,host,project:()=>project,status,
    onFileOpened(path){languageIntelligence?.inspect(path);lsp?.fileChanged(path);index?.fileChanged(path);latex?.fileChanged(path);bibliography?.fileChanged(path);texBuild?.fileChanged(path);manuscripts?.fileChanged(path);javascript?.fileChanged(path);frontend?.fileChanged(path);dataStudio?.fileChanged(path);phpStudio?.fileChanged(path);pythonStudio?.fileChanged(path);goStudio?.fileChanged(path);rustStudio?.fileChanged(path);nativeStudio?.fileChanged(path);jvmStudio?.fileChanged(path);dotnetStudio?.fileChanged(path);androidStudio?.fileChanged(path);swiftStudio?.fileChanged(path);mobileStudio?.fileChanged(path);shellStudio?.fileChanged(path);scriptingStudio?.fileChanged(path);scienceStudio?.fileChanged(path);functionalStudio?.fileChanged(path);beamStudio?.fileChanged(path);logicStudio?.fileChanged(path);}});
  languageIntelligence=mountDeveloperLanguageIntelligence({api,host,
    getProject:()=>project,editor,status});
  lsp=mountDeveloperLSP({api,host,getProject:()=>project,editor,status});
  index=mountDeveloperIndex({api,host,getProject:()=>project,editor,status});
  adapters=mountDeveloperAdapters({api,host,getProject:()=>project,status});
  latex=mountDeveloperLatex({api,host,getProject:()=>project,editor,status});
  bibliography=mountDeveloperBibliography({api,host,getProject:()=>project,editor,status});
  texBuild=mountDeveloperTexBuild({api,host,getProject:()=>project,editor,status});
  manuscripts=mountDeveloperManuscripts({api,host,getProject:()=>project,editor,status});
  javascript=mountDeveloperJavaScript({api,host,getProject:()=>project,editor,status});
  frontend=mountDeveloperFrontend({api,host,getProject:()=>project,editor,status});
  dataStudio=mountDeveloperData({api,host,getProject:()=>project,editor,status});
  phpStudio=mountDeveloperPHP({api,host,getProject:()=>project,editor,status});
  pythonStudio=mountDeveloperPython({api,host,getProject:()=>project,status});
  goStudio=mountDeveloperGo({api,host,getProject:()=>project,status});
  rustStudio=mountDeveloperRust({api,host,getProject:()=>project,status});
  nativeStudio=mountDeveloperNative({api,host,getProject:()=>project,status});
  jvmStudio=mountDeveloperJvm({api,host,getProject:()=>project,status});
  dotnetStudio=mountDeveloperDotnet({api,host,getProject:()=>project,status});
  androidStudio=mountDeveloperAndroid({api,host,getProject:()=>project,status});
  swiftStudio=mountDeveloperSwift({api,host,getProject:()=>project,status});
  mobileStudio=mountDeveloperMobile({api,host,getProject:()=>project,status});
  shellStudio=mountDeveloperShell({api,host,getProject:()=>project,status});
  scriptingStudio=mountDeveloperScripting({api,host,getProject:()=>project,status});
  scienceStudio=mountDeveloperScience({api,host,getProject:()=>project,status});
  functionalStudio=mountDeveloperFunctional({api,host,getProject:()=>project,status});
  beamStudio=mountDeveloperBeam({api,host,getProject:()=>project,status});
  logicStudio=mountDeveloperLogic({api,host,getProject:()=>project,status});
  const navigation=mountDeveloperNavigation({
    api,host,editor,getProject:()=>project,getDirectory:()=>directory,
    openProject,list,status
  });

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
    navigation.updateRoots([...response.roots,...response.recent,
      ...(project?[project]:[])]);
    if(project && included.has(project.project))select.value=project.project;
    else if(!project && response.roots.length && !byId("dsPath").value) {
      select.value=response.roots[0].project;
      byId("dsPath").value=response.roots[0].project;
    }
  }
  function showTrust() {
    byId("dsProject").textContent=project?project.project:"No project open";
    byId("dsTrustState").textContent=project
      ? project.trusted?"Trusted project · guarded editing enabled; language servers require separate approval.":"Restricted workspace · source browsing only."
      :"Select a local folder to begin.";
    byId("dsTrust").hidden=!project;
    byId("dsTrust").textContent=project?.trusted?"Revoke trust":"Trust this project";
    for(const name of ["dsCreate","dsRename","dsTrash","dsRestore"])
      byId(name).disabled=!project?.trusted;
  }
  function clearPreview() {
    byId("dsFilename").textContent="Source editor";
    byId("dsFileInfo").textContent="Choose a source file. Source editing requires trust.";
  }
  async function openProject(path) {
    try {
      const data=await api(BASE+"/open",{project:path});
      if(project?.project!==data.project && !editor.reset())return false;
      project=data;
      await lsp.projectChanged();
      languageIntelligence.reset();
      await index.projectChanged();
      await adapters.projectChanged();
      latex.projectChanged();
      bibliography.projectChanged();
      texBuild.projectChanged();
      manuscripts.projectChanged();
      javascript.projectChanged();
      frontend.projectChanged();
      dataStudio.projectChanged();
      phpStudio.projectChanged();
      pythonStudio.projectChanged();
      goStudio.projectChanged();
      rustStudio.projectChanged();
      nativeStudio.projectChanged();
      jvmStudio.projectChanged();
      dotnetStudio.projectChanged();
      androidStudio.projectChanged();
      swiftStudio.projectChanged();
      mobileStudio.projectChanged();
      shellStudio.projectChanged();
      scriptingStudio.projectChanged();
      scienceStudio.projectChanged();
      functionalStudio.projectChanged();
      beamStudio.projectChanged();
      logicStudio.projectChanged();
      byId("dsPath").value=data.project;
      directory=".";
      showTrust();
      clearPreview();
      await locations();
      await list(".");
      status(data.trusted?"Trusted project opened; source editing is enabled.":"Restricted project opened in read-only mode.");
      navigation.remember();
      return true;
    } catch(error) {
      status("Unable to open project: "+error.message,true);
      return false;
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
      navigation.remember();
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
    await editor.openFile(path);
    if(window.matchMedia("(max-width: 720px)").matches)byId("dsShowEditor").click();
    navigation.remember();
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
  // V3 file actions are deliberately not coupled to source text editing.
  // A dirty tab blocks file operations rather than silently discarding changes.
  const safeForOperation=()=>{
    if(!project?.trusted){status("Trust this project before changing files.",true);return false;}
    if(editor.hasUnsaved()){status("Save or close all unsaved tabs before file operations.",true);return false;}
    return true;
  };
  async function refreshAfterAction(message){
    if(editor.hasUnsaved())return;
    editor.reset();
    await list(directory);
    status(message);
  }
  byId("dsCreate").addEventListener("click",async()=>{
    if(!safeForOperation())return;
    const path=window.prompt("New source file path relative to the project (parent folder must exist):",
      directory==="."?"new-file.txt":directory+"/new-file.txt");
    if(!path)return;
    if(!window.confirm("Create an empty file at "+path+"? Existing files cannot be overwritten."))return;
    try{
      const result=await api(BASE+"/operation",{project:project.project,action:"create",path,confirmed:true});
      await refreshAfterAction("New source file created: "+result.path);
    }catch(error){status("Create refused: "+error.message,true);}
  });
  byId("dsRename").addEventListener("click",async()=>{
    if(!safeForOperation())return;
    const file=editor.currentFile();
    if(!file){status("Open an existing source file before renaming.",true);return;}
    const dest=window.prompt("New project-relative path for "+file.path+":",file.path);
    if(!dest||dest===file.path)return;
    if(!window.confirm("Rename "+file.path+" to "+dest+" without replacing any existing file?"))return;
    try{
      const result=await api(BASE+"/operation",{
        project:project.project,action:"rename",path:file.path,destination:dest,
        expected_sha256:file.sha256,confirmed:true
      });
      await refreshAfterAction("Renamed "+result.old_path+" → "+result.path);
    }catch(error){status("Rename refused: "+error.message,true);}
  });
  byId("dsTrash").addEventListener("click",async()=>{
    if(!safeForOperation())return;
    const file=editor.currentFile();
    if(!file){status("Open an existing source file before archiving.",true);return;}
    if(!window.confirm("Move "+file.path+" into private local recovery? The original is removed only after its bytes have been verified and archived."))return;
    try{
      const result=await api(BASE+"/operation",{
        project:project.project,action:"trash",path:file.path,
        expected_sha256:file.sha256,confirmed:true
      });
      await refreshAfterAction("Archived "+file.path+". Use Restore for recovery.");
    }catch(error){status("Archive refused: "+error.message,true);}
  });
  byId("dsRestore").addEventListener("click",async()=>{
    if(!safeForOperation())return;
    const path=window.prompt("Project-relative path of the archived file to restore:");
    if(!path)return;
    try{
      const lookup=new URLSearchParams({project:project.project,path});
      const archives=await api(BASE+"/trash-archives?"+lookup);
      if(!archives.items?.length){status("No local recovery archive found for "+path);return;}
      const archive=archives.items[0];
      if(!window.confirm("Restore the latest archive for "+path+" ("+archive.size+" bytes)? Existing files will never be overwritten."))return;
      const restored=await api(BASE+"/restore-trash",{
        project:project.project,path,snapshot_id:archive.archive_id,confirmed:true
      });
      await refreshAfterAction("Restored "+restored.path+" from local recovery.");
    }catch(error){status("Restore refused: "+error.message,true);}
  });

  byId("dsTrust").addEventListener("click",async()=>{
    if(!project)return;
    const next=!project.trusted;
    if(!window.confirm(next
      ?"Trust this project for source editing? Saves still require verification and approval. No code execution will occur."
      :"Revoke this project's trusted status? Source files will not change."))return;
    try {
      project=await api(BASE+"/trust",{project:project.project,trusted:next,confirmed:true});
      showTrust();editor.trustChanged();await lsp.trustChanged();await adapters.trustChanged();texBuild.trustChanged();await locations();
      status(next?"Project trusted. Editing enabled; execution disabled.":"Project trust revoked; editing disabled.");
    }catch(error){status("Unable to change trust: "+error.message,true);}
  });
  const lspCleanup=()=>{
    if(host.isConnected)return;
    window.removeEventListener("hashchange",lspCleanup);
    void lsp.stop();
  };
  window.addEventListener("hashchange",lspCleanup);
  try {
    await locations();
  }catch(error) {
    status("Developer Studio V1 is available only on the local AutoMoto installation: "+error.message,true);
  }
  return host;
}

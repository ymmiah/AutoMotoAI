/* Developer Studio V14: non-executing frontend inventory, accessibility and responsive static previews. */
export function mountDeveloperFrontend({api,host,getProject,editor,status}) {
  const root=host.querySelector("#dsFrontendRoot");
  const BASE="/api/developer/studio/frontend";
  root.innerHTML=
    '<section class="ds-fe-panel" aria-label="Frontend inspection and safe static preview">'+
      '<div class="ds-fe-heading"><h3>Web UI & frontend frameworks · V14</h3>'+
      '<span class="ds-readonly">STATIC / NO PROJECT JAVASCRIPT</span></div>'+
      '<div class="ds-fe-body">'+
        '<p class="ds-footnote">Inspect HTML, CSS, SCSS, JSX/TSX, React, Next.js, Vue, Angular, Svelte and other declared framework project files. Static HTML preview is deliberately sanitised and will not reproduce framework rendering or execute scripts, imports, external assets, package tools or network code.</p>'+
        '<div class="ds-fe-toolbar">'+
          '<button class="btn sm" id="dsFeInspect" type="button" disabled>Inspect frontend</button>'+
          '<label for="dsFeFile">Frontend source</label>'+
          '<input class="input" id="dsFeFile" maxlength="1024" placeholder="index.html or src/App.tsx" spellcheck="false">'+
          '<button class="btn sm" id="dsFeAudit" type="button" disabled>Inspect accessibility</button>'+
        '</div>'+
        '<div class="ds-fe-toolbar">'+
          '<label for="dsFeHtml">HTML preview (existing file)</label>'+
          '<input class="input" id="dsFeHtml" maxlength="1024" placeholder="index.html or dist/index.html" spellcheck="false">'+
          '<label for="dsFeCss">Local CSS (optional)</label>'+
          '<input class="input" id="dsFeCss" maxlength="1024" placeholder="styles.css" spellcheck="false">'+
          '<button class="btn sm primary" id="dsFePreview" type="button" disabled>Safe static preview</button>'+
        '</div>'+
        '<p class="ds-footnote" role="status" aria-live="polite" id="dsFeStatus">Open a project to inspect frontend files.</p>'+
        '<div class="ds-fe-findings" id="dsFeFindings" role="region" aria-label="Frontend findings" tabindex="0"></div>'+
        '<div class="ds-fe-responsive" id="dsFeResponsive" hidden>'+
          '<div class="ds-fe-toolbar" role="group" aria-label="Preview viewport width">'+
            '<button class="btn sm" id="dsFeMobile" type="button" aria-pressed="true">Mobile 375px</button>'+
            '<button class="btn sm" id="dsFeTablet" type="button" aria-pressed="false">Tablet 768px</button>'+
            '<button class="btn sm" id="dsFeDesktop" type="button" aria-pressed="false">Desktop 1440px</button>'+
            '<span id="dsFeViewport" class="ds-footnote">375px structural preview</span>'+
          '</div>'+
          '<div class="ds-fe-frame-scroll" id="dsFeFrameScroll">'+
            '<iframe id="dsFeFrame" title="Sanitised static HTML layout; scripts, network, forms and remote assets disabled" sandbox="" referrerpolicy="no-referrer"></iframe>'+
          '</div>'+
        '</div>'+
        '<p class="ds-footnote">The preview iframe has no allow-scripts or allow-same-origin permission and contains a default-deny CSP. Only a constrained subset of HTML and local CSS is copied into its srcdoc; images, forms, scripts and network assets are removed. Framework components must be built separately using V13-approved scripts, then reviewed as built HTML. Accessibility findings are heuristics, not WCAG 2.2 certification.</p>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id);
  let busy=false,sequence=0,view=375;
  const project=()=>getProject()?.project||"";
  const state=(message,bad=false)=>{
    const target=el("dsFeStatus");
    target.textContent=message;target.classList.toggle("ds-error",bad);
  };
  function clear(){el("dsFeFindings").replaceChildren();}
  function note(msg,kind="info"){
    const p=document.createElement("p");p.className="ds-fe-finding";
    p.textContent=String(msg);p.dataset.kind=kind;el("dsFeFindings").appendChild(p);
  }
  function title(msg){
    const node=document.createElement("h4");node.textContent=msg;el("dsFeFindings").appendChild(node);
  }
  function controls(){
    const can=!!project()&&!busy;
    el("dsFeInspect").disabled=!can;
    el("dsFeAudit").disabled=!can||!el("dsFeFile").value.trim();
    el("dsFePreview").disabled=!can||!el("dsFeHtml").value.trim();
  }
  function resize(w){
    view=w;
    el("dsFeFrame").style.width=w+"px";
    el("dsFeViewport").textContent=w+"px sanitised structural preview";
    for(const [id,size] of [["dsFeMobile",375],["dsFeTablet",768],["dsFeDesktop",1440]])
      el(id).setAttribute("aria-pressed",String(size===view));
  }
  function findings(data){
    clear();title("HTML heuristic accessibility checks");
    if(!data.html_issues?.length)note("No issue found by this bounded heuristic; that is not WCAG conformance.");
    for(const item of data.html_issues||[])
      note(item.code+" · line "+item.line+" · "+item.message,"warning");
    note("Source SHA-256: "+data.source_sha256);
    note(data.omitted_html_elements+" potentially active or unsupported HTML elements omitted.");
    note(data.rejected_unsafe_or_unsupported_css_declarations+
      " unsupported or potentially unsafe CSS declarations/rules omitted.");
    note("No source JS executed, no remote asset loaded, no project files modified.");
  }
  async function inspect(){
    if(!project()||busy)return;
    const expected=project(),seq=++sequence;busy=true;controls();
    state("Inspecting bounded frontend filenames and declared frameworks; no code executed.");
    try{
      const data=await api(BASE+"/inspect?"+new URLSearchParams({project:expected}));
      if(seq!==sequence||project()!==expected||!root.isConnected)return;
      clear();title("Declared frameworks and build readiness");
      if(!data.frameworks.length)note("No supported framework declaration or configuration marker detected.");
      for(const f of data.frameworks){
        note(f.name+(f.declared_version?" · declared "+f.declared_version:" · configuration marker")+
          " (installed version and rendered UI unverified)");
      }
      for(const marker of data.config_markers)note("Configuration marker: "+marker);
      note("Build script: "+(data.build_script_available?"declared; use V13 to approve a real build":"not declared"));
      title("Local HTML/CSS/SCSS/component files");
      for(const [name,count] of Object.entries(data.formats||{}))note(name+": "+count);
      for(const name of data.files.slice(0,36))note(name);
      if(data.truncated)note("Source inventory incomplete due to bounded scan.","warning");
      state("Frontend inventory complete. No package manager, framework or browser runtime executed.");
    }catch(e){state("Frontend inventory failed: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function audit(){
    if(!project()||busy)return;
    const expected=project(),seq=++sequence,source=el("dsFeFile").value.trim();
    busy=true;controls();
    state("Inspecting saved markup/source; no browser code or package tool executed.");
    try{
      const data=await api(BASE+"/audit",{project:expected,path:source});
      if(seq!==sequence||project()!==expected||!root.isConnected)return;
      clear();title(data.format+" source audit · saved file");
      for(const issue of data.issues)note(issue.code+" · line "+issue.line+" · "+issue.message,"warning");
      if(!data.issues.length)note("No heuristic issue found; real rendered WCAG conformance is not verified.");
      for(const warning of data.limitations)note(warning,"warning");
      note("SHA-256: "+data.source_sha256);
      state("Read-only source audit complete. Findings require manual browser verification.");
    }catch(e){state("Source audit failed: "+e.message,true);}
    finally{busy=false;controls();}
  }
  async function preview(){
    if(!project()||busy)return;
    const expected=project(),seq=++sequence,source=el("dsFeHtml").value.trim();
    const stylesheet=el("dsFeCss").value.trim();
    busy=true;controls();
    state("Building a bounded, inert HTML snapshot; no source JavaScript or network.");
    try{
      const data=await api(BASE+"/preview",{project:expected,path:source,
        ...(stylesheet?{stylesheet}:{})});
      if(seq!==sequence||project()!==expected||!root.isConnected)return;
      findings(data);
      const frame=el("dsFeFrame");
      // Keep the sandbox empty: never allow scripts, same-origin, top navigation,
      // downloads, popups or form submissions for source-controlled markup.
      frame.setAttribute("sandbox","");
      frame.referrerPolicy="no-referrer";
      frame.srcdoc=data.srcdoc;
      el("dsFeResponsive").hidden=false;
      resize(view);
      state("Sanitised static preview ready. This does not execute or visually reproduce a live framework app.");
    }catch(e){state("Preview rejected: "+e.message,true);}
    finally{busy=false;controls();}
  }
  function fileChanged(path){
    if(!path)return;
    if(/\.(?:html|css|scss|jsx|tsx|vue|svelte)$/i.test(path)&&!el("dsFeFile").value.trim())
      el("dsFeFile").value=path;
    if(/\.html$/i.test(path)&&!el("dsFeHtml").value.trim())el("dsFeHtml").value=path;
    controls();
  }
  function projectChanged(){
    sequence++;busy=false;clear();
    el("dsFeFile").value="";
    el("dsFeHtml").value="";
    el("dsFeCss").value="";
    el("dsFeResponsive").hidden=true;
    el("dsFeFrame").removeAttribute("srcdoc");
    view=375;resize(view);
    state("Open a project to inspect frontend files.");controls();
  }
  el("dsFeInspect").onclick=()=>void inspect();
  el("dsFeAudit").onclick=()=>void audit();
  el("dsFePreview").onclick=()=>void preview();
  for(const field of ["dsFeFile","dsFeHtml","dsFeCss"])
    el(field).addEventListener("input",controls);
  for(const [id,size] of [["dsFeMobile",375],["dsFeTablet",768],["dsFeDesktop",1440]])
    el(id).onclick=()=>resize(size);
  projectChanged();
  return {projectChanged,fileChanged};
}

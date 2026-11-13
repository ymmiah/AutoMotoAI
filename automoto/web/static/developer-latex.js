/* Developer Studio V9 — local, non-executing LaTeX thesis intelligence. */
export function mountDeveloperLatex({api,host,getProject,editor,status}) {
  const BASE="/api/developer/studio/latex";
  const root=host.querySelector("#dsLatexRoot");
  root.innerHTML=
    '<section class="ds-tex-panel" aria-label="LaTeX academic authoring tools">'+
      '<div class="ds-tex-head"><h3>LaTeX academic authoring · V9</h3><span class="ds-readonly">STATIC ANALYSIS · NO COMPILATION</span></div>'+
      '<div class="ds-tex-body">'+
        '<p class="ds-footnote">Analyse a project-local main .tex file and its included chapters/BibTeX files. Static reference checks are not the result of compiling TeX; use the separately approved texlab language server for optional live diagnostics.</p>'+
        '<div class="ds-tex-controls">'+
          '<label for="dsTexMain">Root document</label><input id="dsTexMain" class="input" maxlength="1024" placeholder="main.tex" spellcheck="false">'+
          '<button id="dsTexAnalyse" class="btn sm primary" type="button" disabled>Analyse thesis</button>'+
          '<button id="dsTexCurrent" class="btn sm" type="button" disabled>Use active .tex</button>'+
        '</div>'+
        '<p id="dsTexStatus" class="ds-footnote" role="status" aria-live="polite">Open a project to analyse LaTeX files.</p>'+
        '<div class="ds-tex-tools">'+
          '<label for="dsTexCompletionKind">Complete</label><select class="input" id="dsTexCompletionKind">'+
            '<option value="auto">All</option><option value="command">Commands</option>'+
            '<option value="environment">Environments</option><option value="label">Reference labels</option>'+
            '<option value="citation">Bibliography keys</option></select>'+
          '<input class="input" id="dsTexCompletionPrefix" maxlength="100" placeholder="Optional prefix" aria-label="Completion prefix">'+
          '<button id="dsTexComplete" class="btn sm" disabled type="button">Suggestions</button>'+
          '<label for="dsTexSnippet">Maths</label><select class="input" id="dsTexSnippet">'+
            '<option value="">Choose snippet</option><option value="inline">Inline formula</option>'+
            '<option value="equation">Numbered equation</option><option value="align">Aligned equations</option>'+
            '<option value="fraction">Fraction</option><option value="matrix">Matrix</option></select>'+
          '<button id="dsTexSnippetCopy" class="btn sm" type="button">Show snippet</button>'+
        '</div>'+
        '<div class="ds-tex-results" id="dsTexResults" tabindex="0" role="region" aria-label="LaTeX project results"></div>'+
        '<div class="ds-tex-templates"><label for="dsTexTemplate">Academic template</label>'+
          '<select class="input" id="dsTexTemplate"><option value="thesis">Multi-file thesis</option>'+
          '<option value="article">Academic article</option></select>'+
          '<button id="dsTexTemplatePreview" class="btn sm" type="button">Preview template files</button></div>'+
        '<p class="ds-footnote">Template previews and maths snippets are copy-only. They never overwrite existing source; paste into the V2 guarded editor and save explicitly.</p>'+
      '</div></section>';
  const el=id=>root.querySelector("#"+id), results=el("dsTexResults");
  let current=null, busy=false, seq=0, graph=null;
  const snippets={
    inline:"$a^2+b^2=c^2$",
    equation:"\\begin{equation}\n  E = mc^2\n  \\label{eq:energy}\n\\end{equation}",
    align:"\\begin{align}\n  a &= b+c \\\\\n  d &= e+f\n\\end{align}",
    fraction:"\\frac{numerator}{denominator}",
    matrix:"\\begin{bmatrix}\n  a & b \\\\\n  c & d\n\\end{bmatrix}"
  };
  function message(value,bad=false) {
    const target=el("dsTexStatus");
    target.textContent=value;target.classList.toggle("ds-error",bad);
  }
  function controls(){
    const hasProject=!!getProject();
    const active=editor.currentFile()?.path||"";
    el("dsTexAnalyse").disabled=busy||!hasProject||!el("dsTexMain").value.trim();
    el("dsTexCurrent").disabled=busy||!hasProject||!active.toLowerCase().endsWith(".tex");
    el("dsTexComplete").disabled=busy||!hasProject||!el("dsTexMain").value.trim();
  }
  function clear(){results.replaceChildren();}
  function paragraph(message){const p=document.createElement("p");p.className="ds-footnote";p.textContent=message;results.append(p);}
  function heading(value){const h=document.createElement("h4");h.textContent=value;results.append(h);}
  async function openLocation(item){
    const project=getProject();
    if(!project)return;
    await editor.openFile(item.path);
    editor.revealLocation(item.path,(item.line||0)+1,(item.character||0)+1);
  }
  function line(item,name,detail,target=null){
    const row=document.createElement("div");row.className="ds-tex-row";
    const label=document.createElement("button");label.className="ds-tex-location";
    label.type="button";label.textContent=name+" · "+item.path+":"+((item.line||0)+1);
    label.onclick=()=>void openLocation(item);
    const note=document.createElement("span");note.className="ds-tex-detail";note.textContent=detail||"";
    row.append(label,note);
    if(target){
      const jump=document.createElement("button");jump.type="button";jump.className="btn sm";
      jump.textContent="Go to definition";
      jump.setAttribute("aria-label","Go to definition of "+name);
      jump.onclick=()=>void openLocation(target);
      row.append(jump);
    }
    results.appendChild(row);
  }
  function showGraph(data){
    clear();
    heading("Project files");
    paragraph(data.files.length+" included .tex file(s): "+(data.files.join(", ")||"none"));
    heading("Static diagnostics ("+data.diagnostics.length+")");
    if(!data.diagnostics.length)paragraph("No static reference problems found in the analysed subset. This does not prove successful compilation.");
    for(const issue of data.diagnostics.slice(0,100))
      line(issue,issue.code,issue.message);
    heading("Sections ("+data.sections.length+")");
    for(const item of data.sections.slice(0,80))line(item,item.value,item.level);
    heading("Labels ("+data.labels.length+")");
    for(const item of data.labels.slice(0,80))line(item,item.value,"definition");
    heading("References ("+data.references.length+")");
    const defined=new Map(data.labels.map(x=>[x.value,x]));
    for(const item of data.references.slice(0,80))
      line(item,item.value,defined.has(item.value)?"resolved in scanned project":"unresolved",
        defined.get(item.value));
    heading("Citations ("+data.citations.length+")");
    const bib=new Map(data.bibliography_keys.map(x=>[x.value,x]));
    for(const item of data.citations.slice(0,80))
      line(item,item.value,bib.has(item.value)?"key found in local .bib":"not found",
        bib.get(item.value));
  }
  function payload(){
    const project=getProject();
    if(!project)return null;
    const main=el("dsTexMain").value.trim();
    if(!main)return null;
    const p={project:project.project,main};
    const editorState=editor.lspContext();
    if(editorState?.path?.endsWith(".tex")){
      p.active_path=editorState.path;
      p.active_text=editorState.text;
    }
    return p;
  }
  async function analyse(){
    const request=payload();if(!request||busy)return;
    const id=++seq;busy=true;controls();message("Checking approved local thesis files and cross-references…");
    try{
      const data=await api(BASE+"/analyse",request);
      if(id!==seq||getProject()?.project!==request.project)return;
      graph=data;showGraph(data);
      message(data.file_count+" .tex files · "+data.labels.length+" labels · "+
        data.references.length+" references · "+data.diagnostics.length+
        " static diagnostics"+(data.truncated?" · incomplete bounded scan":"")+
        ". No files compiled, uploaded or changed.");
    }catch(error){message("LaTeX project analysis failed: "+error.message,true);}
    finally{busy=false;controls();}
  }
  async function complete(){
    const request=payload();if(!request||busy)return;
    const id=++seq;busy=true;controls();
    try{
      const data=await api(BASE+"/complete",{...request,
        prefix:el("dsTexCompletionPrefix").value,
        kind:el("dsTexCompletionKind").value});
      if(id!==seq||getProject()?.project!==request.project)return;
      clear();heading("LaTeX suggestions ("+data.items.length+")");
      if(!data.items.length)paragraph("No suggestions match the selected prefix.");
      for(const item of data.items){
        const row=document.createElement("div");row.className="ds-tex-row";
        const label=document.createElement("code");label.textContent=item.label;
        const copy=document.createElement("button");copy.className="btn sm";
        copy.type="button";copy.textContent="Show text";
        copy.onclick=()=>showCopy(item.insert);
        row.append(label,copy);results.append(row);
      }
      message(data.items.length+" bounded suggestions; showing a suggestion does not edit source.");
    }catch(error){message("LaTeX completion failed: "+error.message,true);}
    finally{busy=false;controls();}
  }
  function showCopy(value){
    clear();
    heading("Copy-ready text (never applied automatically)");
    const field=document.createElement("textarea");field.className="input ds-tex-preview";
    field.readOnly=true;field.rows=Math.min(12,Math.max(3,value.split("\n").length+1));
    field.value=value;field.setAttribute("aria-label","Copy-ready LaTeX source");
    const button=document.createElement("button");button.type="button";button.className="btn sm";
    button.textContent="Select text";button.onclick=()=>{field.focus();field.select();};
    results.append(field,button);
    message("Select and copy into your editor. Saving still requires the guarded source editor.");
  }
  async function templates(){
    if(busy)return;
    busy=true;controls();
    try{
      const data=await api(BASE+"/template-preview",{id:el("dsTexTemplate").value});
      clear();heading(data.label+" — preview only");
      paragraph("Template source is original illustrative text. Replace all placeholder academic references and verify packages locally.");
      for(const file of data.files||[]){
        heading(file.path);
        const field=document.createElement("textarea");field.className="input ds-tex-preview";
        field.readOnly=true;field.rows=Math.min(12,Math.max(4,file.text.split("\n").length));
        field.value=file.text;field.setAttribute("aria-label","Template file "+file.path);
        const button=document.createElement("button");button.type="button";button.className="btn sm";
        button.textContent="Select file text";button.onclick=()=>{field.focus();field.select();};
        results.append(field,button);
      }
      message("Template preview ready. No source file was created or overwritten.");
    }catch(error){message("Template preview failed: "+error.message,true);}
    finally{busy=false;controls();}
  }
  function fileChanged(path){
    current=path||null;
    if(current?.toLowerCase().endsWith(".tex")&&!el("dsTexMain").value.trim())
      el("dsTexMain").value=current;
    controls();
  }
  function projectChanged(){
    seq++;current=null;graph=null;busy=false;el("dsTexMain").value="";
    clear();message("Open a project to analyse LaTeX files.");controls();
  }
  el("dsTexMain").addEventListener("input",controls);
  el("dsTexAnalyse").onclick=()=>void analyse();
  el("dsTexComplete").onclick=()=>void complete();
  el("dsTexCurrent").onclick=()=>{
    if(current?.endsWith(".tex"))el("dsTexMain").value=current;
    controls();void analyse();
  };
  el("dsTexSnippetCopy").onclick=()=>{
    const value=snippets[el("dsTexSnippet").value];
    if(value)showCopy(value);
  };
  el("dsTexTemplatePreview").onclick=()=>void templates();
  controls();
  return {fileChanged,projectChanged,analyse};
}

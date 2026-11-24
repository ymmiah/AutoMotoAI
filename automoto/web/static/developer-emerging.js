/* V35: Zig, Nim, Crystal, Odin, Mojo and MoonBit. Checking only reads files; the optional
   toolchain test builds AutoMoto's own tiny example program (never project code) after a
   confirmation, and only for languages AutoMoto has proved in CI. */
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const MATURITY={"stable":["Stable","ok"],"pre-1.0":["Pre-1.0","warn"],"pre-1.0 (monthly dev releases)":["Pre-1.0","warn"],"preview":["Preview","info"],"beta (pre-1.0)":["Beta","info"]};
const SUPPORT={tested:"ok",newer_than_tested:"info",older_than_tested:"warn",unrecognised:"warn",unknown:"info"};

export function mountDeveloperEmerging({api,host,getProject}){
  const root=host.querySelector("#dsEmergingRoot");
  root.innerHTML='<section class="dsb dsq" aria-label="Newer languages">'+
    '<h3 class="dsb-h">Zig, Nim, Crystal, Odin, Mojo &amp; MoonBit</h3>'+
    '<p class="dsb-hint">See which newer languages this project uses, whether they are installed on this computer, and how mature each one is. Checking only reads files.</p>'+
    '<button id="dsEmergingInspect" class="btn primary" type="button" disabled>Check this project</button>'+
    '<p id="dsEmergingStatus" class="dsb-hint" role="status" aria-live="polite">Open a project first.</p>'+
    '<div id="dsEmergingCards" class="dsq-cards"></div>'+
    '<details class="dsb-adv"><summary>Advanced details</summary><pre id="dsEmergingResults" class="ds-php-output" tabindex="0"></pre></details>'+
    '</section>';
  const $=id=>root.querySelector("#"+id);
  let busy=false,sequence=0,last=null;
  function refresh(){$("dsEmergingInspect").disabled=busy||!getProject()?.project;}
  function chip(text,tone){return el("span","dsq-chip t-"+tone,text);}
  function installLine(hint){
    const p=el("p","dsq-install");
    if(/^https?:\/\//.test(hint)){p.append("Not installed. ");const a=el("a","dsb-link","Official install guide ↗");a.href=hint;a.target="_blank";a.rel="noopener noreferrer";p.append(a);}
    else if(/\s/.test(hint)&&!/^Not supported/.test(hint)){p.append("Not installed. To install, run: ");const c=el("code","dsq-cmd",hint);c.dataset.copy=hint;c.dataset.copyLabel="command";p.append(c);}
    else p.append("Not installed. "+hint);
    return p;
  }
  function card(item){
    const c=el("article","dsq-card"+(item.files||item.manifests.length?" used":""));c.dataset.language=item.language;
    const head=el("div","dsq-head");
    const [mLabel,mTone]=MATURITY[item.maturity]||[item.maturity,"info"];
    head.append(el("b",null,item.label),chip(mLabel,mTone),el("span","dsx-gap"),
      chip(item.installed?"Installed":"Not installed",item.installed?"ok":"idle"));
    c.append(head);
    const used=item.files||item.manifests.length;
    c.append(el("p","dsq-meta",used?(item.files+" file"+(item.files===1?"":"s")+(item.manifests.length?" · "+item.manifests.join(", "):"")):"Not used in this project"));
    c.append(el("p","dsb-hint",item.summary));
    if(item.project_requires){
      const s=item.project_requirement_support;
      const p=el("p","dsq-note t-"+(SUPPORT[s.support]||"info"),"This project asks for "+item.label+" "+item.project_requires.requires+". "+s.note);
      c.append(p);
    }
    if(item.needs)c.append(el("p","dsq-meta","Also needs: "+item.needs));
    if(!item.installed&&item.host_supported!==false)c.append(installLine(item.install_hint));
    if(item.host_supported===false)c.append(el("p","dsq-note t-warn",item.install_hint));
    const result=el("div","dsq-result");result.setAttribute("aria-live","polite");
    if(item.check_offered){
      const b=el("button","btn sm","Try a tiny test program");b.type="button";b.dataset.check=item.language;
      b.onclick=()=>void check(item,b,result);
      c.append(b);
    }else if(item.installed||["mojo","moonbit"].includes(item.language)){
      c.append(el("p","dsq-meta",item.check_unavailable_reason));
    }
    c.append(result);
    return c;
  }
  async function check(item,button,result){
    const project=getProject()?.project;if(!project)return;
    if(!getProject()?.trusted){result.replaceChildren(el("p","dsq-note t-warn","Allow changes for this project first (the switch at the top). The test still won't touch your files."));return;}
    if(!window.confirm("Build and run a tiny "+item.label+" test program?\n\nIt is AutoMoto's own example, not your code. It runs in a temporary folder that is deleted afterwards. The "+item.label+" compiler itself is not sandboxed."))return;
    button.disabled=true;result.replaceChildren(el("p","dsb-hint","Building and running… the first build can take up to a minute."));
    try{
      const d=await api("/api/developer/studio/emerging/check",{project,language:item.language,
        expected_executable:item.compiler.executable,expected_sha256:item.compiler.sha256,confirmed:true,accept_unsandboxed_toolchain:true});
      const box=el("div","dsq-outcome t-"+(d.passed?"ok":"bad"));
      box.append(el("b",null,d.passed?"Works: "+item.label+" "+(d.version||"")+" built and ran the test program.":"It didn't work on this computer."));
      if(d.passed)box.append(el("p","dsb-hint",d.version_support.note));
      else box.append(el("p","dsb-hint","The compiler's own message is below. Common causes: a missing C compiler or linker, or an old version."));
      const out=el("pre","ds-php-output dsq-out",d.output||"(no output)");if(d.passed)out.hidden=true;
      box.append(out);result.replaceChildren(box);
    }catch(e){result.replaceChildren(el("p","dsq-note t-bad","Test refused: "+e.message));}
    finally{button.disabled=false;}
  }
  async function inspect(){
    const project=getProject()?.project;if(!project||busy)return;
    busy=true;const id=++sequence;refresh();
    $("dsEmergingStatus").textContent="Reading files. Nothing is run.";
    try{
      const d=await api("/api/developer/studio/emerging/inspect?"+new URLSearchParams({project}));
      if(id!==sequence||getProject()?.project!==project)return;
      last=d;
      const langs=[...d.languages].sort((a,b)=>(b.files+b.manifests.length)-(a.files+a.manifests.length));
      const used=langs.filter(x=>x.files||x.manifests.length);
      $("dsEmergingCards").replaceChildren(...langs.map(card));
      $("dsEmergingStatus").textContent=(used.length?"Found "+used.map(x=>x.label).join(", ")+".":"None of these languages are used here yet. You can still test what's installed.")+
        (d.scan_incomplete?" The project is large, so the scan stopped early.":"")+" Nothing was run.";
      $("dsEmergingResults").textContent=JSON.stringify(d,null,2);
    }catch(e){$("dsEmergingStatus").textContent="Check refused: "+e.message;}
    finally{busy=false;refresh();}
  }
  $("dsEmergingInspect").addEventListener("click",()=>void inspect());
  refresh();
  return {projectChanged(){sequence++;last=null;$("dsEmergingCards").replaceChildren();$("dsEmergingResults").textContent="";
    $("dsEmergingStatus").textContent=getProject()?.project?"Ready. Press Check this project.":"Open a project first.";refresh();},
    fileChanged:refresh,get last(){return last;}};
}

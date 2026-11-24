/* V36: Terraform, Nix, Bicep, CUE, Dockerfiles, Kubernetes YAML and shaders. Checking only reads
   files and never deploys. An optional double-check runs one offline validator on a copy of one
   file after a confirmation. */
import {ring} from "./developer-beginner.js";
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const SEV={problem:["Problem","bad"],warning:["Worth fixing","warn"],tip:["Tip","info"]};

export function mountDeveloperInfra({api,host,getProject}){
  const root=host.querySelector("#dsInfraRoot");
  root.innerHTML='<section class="dsb dsq" aria-label="Infrastructure and config files">'+
    '<h3 class="dsb-h">Infrastructure &amp; config files</h3>'+
    '<p class="dsb-hint">Terraform, Nix, Bicep, CUE, Dockerfiles, Kubernetes YAML and shaders. AutoMoto only reads and checks them. It never deploys, applies or changes any server, cluster or cloud.</p>'+
    '<button id="dsInfraInspect" class="btn primary" type="button" disabled>Check my config files</button>'+
    '<p id="dsInfraStatus" class="dsb-hint" role="status" aria-live="polite">Open a project first.</p>'+
    '<div id="dsInfraSummary"></div>'+
    '<div id="dsInfraFiles" class="dsq-cards"></div>'+
    '<details class="dsb-adv"><summary>Advanced details</summary><div id="dsInfraTools" class="dsq-tools"></div><pre id="dsInfraResults" class="ds-php-output" tabindex="0"></pre></details>'+
    '</section>';
  const $=id=>root.querySelector("#"+id);
  let busy=false,sequence=0,last=null;
  function refresh(){$("dsInfraInspect").disabled=busy||!getProject()?.project;}
  function chip(text,tone){return el("span","dsq-chip t-"+tone,text);}
  function findingRow(f){
    const li=el("li","dsq-finding");const [label,tone]=SEV[f.severity];
    const top=el("div","dsq-ftop");top.append(chip(label,tone),el("span","dsq-fline",f.line?"Line "+f.line:"Whole file"));
    li.append(top,el("p",null,f.message),el("p","dsb-hint","How to fix: "+f.fix));return li;
  }
  function summary(d){
    const total=d.files.length;const clean=d.files.filter(f=>!f.findings.some(x=>x.severity==="problem")).length;
    const c=d.counts;const tone=c.problem?"bad":"ok";
    const card=el("div","dsb-check t-"+tone);
    card.append(ring(total?clean:null,total,total?tone:"idle",total?"✓":"–"));
    const text=el("div","dsb-check-text");
    text.append(el("b",null,!total?"No config files found":c.problem?c.problem+" problem"+(c.problem===1?"":"s")+" to fix":"No problems found"),
      el("p",null,total?(clean+" of "+total+" files have no problems · "+c.warning+" worth fixing · "+c.tip+" tips"):"Nothing to check in this project."));
    const again=el("button","btn sm dsb-check-btn","Check again");again.type="button";again.onclick=()=>void inspect();
    card.append(text,again);return card;
  }
  function fileCard(f,tools){
    const c=el("article","dsq-card used");c.dataset.path=f.path;
    const head=el("div","dsq-head");head.append(el("b","dsq-path",f.path),chip(f.label,"idle"));c.append(head);
    if(!f.findings.length)c.append(el("p","dsq-note t-ok","Looks good to AutoMoto's built-in checks."));
    else{const ul=el("ul","dsq-findings");for(const x of f.findings)ul.append(findingRow(x));c.append(ul);}
    const result=el("div","dsq-result");result.setAttribute("aria-live","polite");
    for(const name of f.validators){
      const t=tools[name];const b=el("button","btn sm","Double-check with "+t.label);b.type="button";b.dataset.validator=name;
      b.onclick=()=>void validate(f,t,b,result);c.append(b);
    }
    if(!f.validators.length&&f.contents_read){
      const missing=Object.values(tools).find(t=>t.kind===f.kind&&t.status==="unavailable");
      if(missing){const p=el("p","dsq-meta");
        if(/^https?:\/\//.test(missing.install_hint)){p.append("Optional double-check: install "+missing.name+". ");const a=el("a","dsb-link","Install guide ↗");a.href=missing.install_hint;a.target="_blank";a.rel="noopener noreferrer";p.append(a);}
        else{p.append("Optional double-check: install "+missing.name+" with ");const code=el("code","dsq-cmd",missing.install_hint);code.dataset.copy=missing.install_hint;code.dataset.copyLabel="command";p.append(code);}
        c.append(p);}
    }
    c.append(result);return c;
  }
  async function validate(f,t,button,result){
    const project=getProject()?.project;if(!project)return;
    if(!getProject()?.trusted){result.replaceChildren(el("p","dsq-note t-warn","Allow changes for this project first (the switch at the top). The check still won't change your files."));return;}
    if(!window.confirm("Run "+t.label+" on a copy of "+f.path+"?\n\nCommand: "+t.command_preview.replace("<file>",f.path.split("/").pop())+"\n\nIt works on a temporary copy, offline, with no cloud logins visible. Nothing is deployed. The tool itself is not sandboxed."))return;
    button.disabled=true;result.replaceChildren(el("p","dsb-hint","Checking…"));
    try{
      const d=await api("/api/developer/studio/infra/validate",{project,path:f.path,validator:t.name,
        expected_file_sha256:f.sha256,expected_executable:t.executable,expected_sha256:t.sha256,confirmed:true,accept_unsandboxed_validator:true});
      const words={passed:"Passed: "+t.label+" found no problems.",needs_formatting:"Valid, but the formatting differs from the standard style.",problems_found:t.label+" found problems.",timed_out:"The check took too long and was stopped."};
      const box=el("div","dsq-outcome t-"+(d.result==="passed"?"ok":d.result==="needs_formatting"?"warn":"bad"));
      box.append(el("b",null,words[d.result]||d.result));
      const cmd=el("code","dsq-cmd",d.command_preview);cmd.dataset.copy=d.command_preview;cmd.dataset.copyLabel="command";
      const p=el("p","dsq-meta","Ran: ");p.append(cmd);box.append(p);
      if(d.output)box.append(el("pre","ds-php-output dsq-out",d.output));
      result.replaceChildren(box);
    }catch(e){result.replaceChildren(el("p","dsq-note t-bad","Check refused: "+e.message));}
    finally{button.disabled=false;}
  }
  async function inspect(){
    const project=getProject()?.project;if(!project||busy)return;
    busy=true;const id=++sequence;refresh();
    $("dsInfraStatus").textContent="Reading config files. Nothing is deployed or run.";
    try{
      const d=await api("/api/developer/studio/infra/inspect?"+new URLSearchParams({project}));
      if(id!==sequence||getProject()?.project!==project)return;
      last=d;
      const tools=Object.fromEntries(d.validators.map(v=>[v.name,v]));
      $("dsInfraSummary").replaceChildren(summary(d));
      const files=[...d.files].sort((a,b)=>b.findings.filter(x=>x.severity==="problem").length-a.findings.filter(x=>x.severity==="problem").length);
      const cards=files.map(f=>fileCard(f,tools));
      if(d.project_findings.length){const c=el("article","dsq-card used");const h=el("div","dsq-head");h.append(el("b",null,"Whole project"));c.append(h);
        const ul=el("ul","dsq-findings");for(const x of d.project_findings)ul.append(findingRow(x));c.append(ul);cards.push(c);}
      $("dsInfraFiles").replaceChildren(...cards);
      const list=el("ul","dsq-toollist");
      for(const v of d.validators){const li=el("li");li.append(el("b",null,v.name),chip(v.status==="installed_not_executed"?"Installed":"Not installed",v.status==="installed_not_executed"?"ok":"idle"));
        const code=el("code","dsq-cmd",v.command_preview);code.dataset.copy=v.command_preview;code.dataset.copyLabel="command";li.append(code);list.append(li);}
      $("dsInfraTools").replaceChildren(el("p","dsb-hint","Optional offline validators. Never run: "+d.never_run.join(", ")+"."),list);
      $("dsInfraStatus").textContent="Checked "+d.files.length+" file"+(d.files.length===1?"":"s")+". Nothing was deployed or changed."+(d.scan_incomplete?" The project is large, so the scan stopped early.":"");
      $("dsInfraResults").textContent=JSON.stringify(d,null,2);
    }catch(e){$("dsInfraStatus").textContent="Check refused: "+e.message;}
    finally{busy=false;refresh();}
  }
  $("dsInfraInspect").addEventListener("click",()=>void inspect());
  refresh();
  return {projectChanged(){sequence++;last=null;$("dsInfraFiles").replaceChildren();$("dsInfraSummary").replaceChildren();$("dsInfraResults").textContent="";
    $("dsInfraStatus").textContent=getProject()?.project?"Ready. Press Check my config files.":"Open a project first.";refresh();},
    fileChanged:refresh,get last(){return last;}};
}

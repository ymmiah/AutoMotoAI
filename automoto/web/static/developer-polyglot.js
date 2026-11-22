/* Project map (V37-V40, "polyglot intelligence").
   Guided steps: map your project (languages, links between files, broken links) -> what talks to
   what (frontend calls -> API routes -> data models) -> your data models -> rename safely (preview
   the impact, then an approval-gated, checksum-bound change with undo) -> packages and bindings
   (commands are shown with copy buttons, never run here).
   Everything comes from the user's own project files, which are untrusted: names, paths and lines
   reach the page only through textContent, and nothing in the project is ever run. Nothing is
   stored in the browser. */
import {ring} from "./developer-beginner.js";
const BASE="/api/developer/studio/polyglot";
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const btn=(text,cls,fn)=>{const b=el("button","btn "+(cls||""),text);b.type="button";if(fn)b.onclick=fn;return b;};
const TONE={passed:"ok",failed:"bad",none:"idle"};
const plural=(n,one,many)=>n+" "+(n===1?one:(many||one+"s"));
function step(n,title,state){
  const li=el("li","dsb-step s-"+state);li.append(el("span","dsb-num",state==="done"?"✓":String(n)));
  const main=el("div","dsb-step-main");main.append(el("b",null,title));li.append(main);return {li,main};
}
function card(passed,total,tone,title,text,fallback){
  const c=el("div","dsb-check t-"+tone);c.append(ring(passed,total,tone,fallback));
  const t=el("div","dsb-check-text");t.append(el("b",null,title),el("p",null,text));c.append(t);return c;
}
function list(items,render,empty,max){
  if(!items||!items.length)return el("p","dsb-hint",empty);
  const ul=el("ul","dsp-list");for(const i of items.slice(0,max||12))ul.append(render(i));
  if(items.length>(max||12))ul.append(el("li","dsp-more","…and "+(items.length-(max||12))+" more"));
  return ul;
}
const where=(file,line)=>file+(line?":"+line:"");
function row(main,sub){const li=el("li");li.append(el("span","dsp-main",main));if(sub)li.append(el("small",null,sub));return li;}
function field(label,value,placeholder,onInput){
  const l=el("label","dss-field");l.append(el("span",null,label));
  const i=el("input");i.value=value||"";i.placeholder=placeholder||"";i.spellcheck=false;i.autocomplete="off";
  i.oninput=()=>onInput(i.value);l.append(i);return l;
}

export function mountDeveloperPolyglot({api,host,getProject,status,openTool}){
  const root=host.querySelector("#dsPolyglotRoot");if(!root)return null;
  const box=el("section","dsb dsp");box.setAttribute("aria-label","Project map");root.append(box);
  let map=null,look=null,tr=null,pk=null,rp=null,done=null,busy=false,notice=null,lookPath="",contractOk=false;
  let oldName="",newName="",renamePath="";
  const project=()=>getProject?.()?.project||null;
  const trusted=()=>!!getProject?.()?.trusted;
  const say=(text,bad)=>{notice={text,bad};if(status)status(text,bad);};
  async function act(fn){
    if(busy)return;busy=true;notice=null;draw();
    try{await fn();}catch(e){say(e.message||"Something went wrong.",true);}
    finally{busy=false;draw();}
  }
  const go=(path,extra)=>api(BASE+path,{project:project(),...(extra||{})});
  const doMap=()=>act(async()=>{map=await go("/map");look=null;});
  const doTrace=()=>act(async()=>{tr=await go("/trace");});
  const doPackages=()=>act(async()=>{pk=await go("/packages");});
  const doLook=()=>act(async()=>{look=await go("/file",{path:lookPath.trim()});});
  const doPreview=()=>act(async()=>{done=null;contractOk=false;rp=await go("/rename/preview",{old:oldName.trim(),new:newName.trim(),path:renamePath.trim()||null});});
  async function doApply(){
    if(!rp?.action_sha256)return;
    const lines=["Rename "+rp.old+" to "+rp.new+"?","",plural(rp.places,"place")+" in "+plural(rp.files.length,"file")+" will change:",
      ...rp.files.slice(0,12).map(f=>"  "+f.path+" ("+f.count+")"),"","Comments and text in quotes are left alone. You can undo this."];
    if(!window.confirm(lines.join("\n")))return;
    await act(async()=>{done=await go("/rename/apply",{action_sha256:rp.action_sha256,confirmed:true,contract_ok:contractOk});rp=null;map=null;tr=null;say("Renamed in "+plural(done.files.length,"file")+".");});
  }
  const doUndo=()=>act(async()=>{await go("/rename/undo",{undo_id:done.undo_id});say("Put back "+plural(done.files.length,"file")+".");done=null;map=null;tr=null;});

  // ---- step 1: map your project (V37)
  function stepMap(){
    const s=step(1,"Map your project",map?"done":"now");
    if(!map){
      s.main.append(el("p","dsb-hint","Read your files to see which languages you use and how files connect. Nothing is run or changed."));
      const b=btn(busy?"Mapping…":"Map it","primary",doMap);b.disabled=busy;s.main.append(b);return s.li;
    }
    const b=map.budget;const tone=b.truncated?"busy":map.broken_count?"bad":"ok";
    const c=card(b.read,b.found,tone,plural(b.read,"file")+" read of "+b.found,
      (map.languages.slice(0,4).map(l=>l.name).join(", ")||"No code found")+" · "+plural(map.links,"link")+(map.broken_count?" · "+plural(map.broken_count,"broken link"):" · no broken links"),"–");
    const again=btn("Map again","sm dsb-check-btn",doMap);again.disabled=busy;c.append(again);s.main.append(c);
    if(b.truncated)s.main.append(el("p","dsb-hint","Your project is big, so I stopped early ("+b.notes.join(", ")+"). The rest isn't shown."));
    if(map.cross_language_links)s.main.append(el("p","dsb-hint",plural(map.cross_language_links,"link")+" cross between languages, like "+where(map.cross_language_examples[0].from)+" → "+map.cross_language_examples[0].to+"."));
    if(map.broken_count){
      const d=el("details","dsp-more-box");d.append(el("summary",null,"Broken links ("+map.broken_count+")"));
      d.append(list(map.broken,i=>row(i.spec,where(i.file,i.line)+" · "+i.why),""));s.main.append(d);
    }
    if(map.hubs.length){
      const d=el("details","dsp-more-box");d.append(el("summary",null,"Most used files"));
      d.append(list(map.hubs,i=>row(i.file,"used by "+plural(i.used_by,"file")),""));s.main.append(d);
    }
    const f=el("div","dsp-row");f.append(field("Look up a file","" +lookPath,"src/app.ts",v=>{lookPath=v;}));
    const lb=btn("Show links","sm",doLook);lb.disabled=busy;f.append(lb);s.main.append(f);
    if(look){
      const d=el("div","dsp-look");d.append(el("b",null,look.file+" ("+look.language+")"));
      d.append(el("p","dsb-hint","Uses"),list(look.uses,i=>row(i.to,"line "+i.line+(i.cross_language?" · another language":"")),"Nothing in this project."));
      d.append(el("p","dsb-hint","Used by"),list(look.used_by,i=>row(i.from,"line "+i.line),"No other file uses it."));
      if(look.broken.length)d.append(el("p","dsb-hint","Broken"),list(look.broken,i=>row(i.spec,"line "+i.line),""));
      s.main.append(d);
    }
    return s.li;
  }
  // ---- step 2: what talks to what (V38)
  function stepTrace(){
    const s=step(2,"What talks to what",tr?(tr.state==="passed"?"done":"now"):map?"now":"todo");
    s.main.append(el("p","dsb-hint","Follow your app's calls to the server code that answers them, and the data it uses."));
    if(!tr){const b=btn(busy?"Checking…":"Follow the calls","primary",doTrace);b.disabled=busy;s.main.append(b);return s.li;}
    const c=card(tr.matched,tr.countable,TONE[tr.state]||"idle",tr.summary,
      plural(tr.routes,"server route")+" found. "+tr.note,tr.state==="none"?"–":"!");
    const again=btn("Check again","sm dsb-check-btn",doTrace);again.disabled=busy;c.append(again);s.main.append(c);
    s.main.append(list(tr.chains,i=>row(i.call.method+" "+i.call.raw+" → "+(i.route.handler||i.route.framework),
      where(i.call.file,i.call.line)+" → "+where(i.route.file,i.route.line)+(i.models.length?" · data: "+i.models.join(", "):"")),"No matches yet.",8));
    if(tr.possible.length){
      const d=el("details","dsp-more-box");d.append(el("summary",null,"Maybe ("+tr.possible.length+") — not counted"));
      d.append(list(tr.possible,i=>row(i.call.raw,where(i.call.file,i.call.line)+" · "+i.why),""));s.main.append(d);
    }
    if(tr.unknown.length){
      const d=el("details","dsp-more-box");d.append(el("summary",null,"No match ("+tr.unknown.length+")"));
      d.append(list(tr.unknown,i=>row(i.call.method+" "+i.call.raw,where(i.call.file,i.call.line)+" · "+i.why),""));s.main.append(d);
    }
    if(tr.routes_without_calls.length){
      const d=el("details","dsp-more-box");d.append(el("summary",null,"Routes your app doesn't call ("+tr.routes_without_calls.length+")"));
      d.append(list(tr.routes_without_calls,i=>row(i.method+" "+i.path,where(i.file,i.line)+" · "+i.framework),""));s.main.append(d);
    }
    return s.li;
  }
  // ---- step 3: data models (V37)
  function stepModels(){
    const s=step(3,"Your data models",map?(map.models.length?"done":"now"):"todo");
    if(!map){s.main.append(el("p","dsb-hint","Map your project first."));return s.li;}
    s.main.append(list(map.models,m=>row(m.name,m.kind+" · "+where(m.file,m.line)),"No tables or models found (SQL, Prisma, Django, SQLAlchemy, TypeORM, Rails, Laravel or JPA)."));
    if(map.model_relations.length){
      const d=el("details","dsp-more-box");d.append(el("summary",null,"How they connect ("+map.model_relations.length+")"));
      d.append(list(map.model_relations,r=>row(r.from+" → "+r.to,r.how+" · "+where(r.file,r.line)),""));s.main.append(d);
    }
    return s.li;
  }
  // ---- step 4: rename safely (V39)
  function stepRename(){
    const s=step(4,"Rename safely",done?"done":"now");
    s.main.append(el("p","dsb-hint","Change a name everywhere it's used. You see every change first. Tip: save a checkpoint before you start."));
    if(!trusted())s.main.append(el("p","dsv-note","You can preview now. To change files, allow changes for this project first."));
    const f=el("div","dsp-row");
    const bar=el("div","dsa-bar");const pb=btn(busy?"Checking…":"Preview changes","primary",doPreview);
    const sync=()=>{pb.disabled=busy||!oldName.trim()||!newName.trim();};sync();bar.append(pb);
    f.append(field("Current name",oldName,"loadUsers",v=>{oldName=v;sync();}),field("New name",newName,"fetchUsers",v=>{newName=v;sync();}),
      field("Defined in (optional)",renamePath,"src/api.ts",v=>{renamePath=v;}));
    s.main.append(f);
    if(done){const u=btn("Undo rename","sm",doUndo);u.disabled=busy;bar.append(u);}
    if(git())bar.append(btn("Save a checkpoint","sm",()=>openTool?.("git")));
    s.main.append(bar);
    if(rp){
      const ok=rp.state==="ready";
      const c=card(ok?rp.files.length:0,0,ok?"ok":"bad",ok?plural(rp.places,"place")+" in "+plural(rp.files.length,"file"):"Not safe to rename yet",
        ok?"Only code changes. Comments and text in quotes stay the same.":rp.blocks[0],ok?String(rp.files.length):"!");
      s.main.append(c);
      for(const b of rp.blocks.slice(1))s.main.append(el("p","dsa-alert bad",b));
      if(rp.choices.length){
        s.main.append(el("p","dsb-hint","Pick the file you mean:"));
        const cb=el("div","dsa-bar");for(const ch of rp.choices)cb.append(btn(ch.file,"sm",()=>{renamePath=ch.file;rp=null;void doPreview();}));s.main.append(cb);
      }
      for(const w of rp.warnings)s.main.append(el("p","dsv-note",w.text+(w.files?.length&&w.kind!=="contract"?" ("+w.files.slice(0,4).join(", ")+")":"")));
      if(ok){
        s.main.append(list(rp.files,f=>{const li=row(f.path+" ("+f.count+")",f.language);
          for(const e of f.examples){const pre=el("pre","dsp-diff");pre.append(el("code",null,"- "+e.before+"\n+ "+e.after));li.append(pre);}return li;},"",10));
        if(rp.needs_contract_ok){
          const l=el("label","dsv-check");const i=el("input");i.type="checkbox";i.checked=contractOk;i.onchange=()=>{contractOk=i.checked;draw();};
          l.append(i,el("span",null,"I've checked the API route or data model note above"));s.main.append(l);
        }
        const ab=btn("Rename","primary",doApply);ab.disabled=busy||!trusted()||(rp.needs_contract_ok&&!contractOk);s.main.append(ab);
      }
    }
    if(done)s.main.append(el("p","dsa-alert ok","Renamed "+done.old+" to "+done.new+" in "+plural(done.files.length,"file")+". Use Undo rename to put it back."));
    return s.li;
  }
  const git=()=>!!host.querySelector("#dsGitRoot");
  // ---- step 5: packages and bindings (V40)
  function stepPackages(){
    const s=step(5,"Packages and bindings",pk?"done":"now");
    s.main.append(el("p","dsb-hint","See the parts of a big project, how they depend on each other and where languages meet."));
    if(!pk){const b=btn(busy?"Looking…":"Show packages","primary",doPackages);b.disabled=busy;s.main.append(b);return s.li;}
    const tools=pk.tools.map(t=>t.tool);
    s.main.append(el("p","dsb-hint",(pk.monorepo?"A project with "+plural(pk.package_count,"part"):"A single package")+(tools.length?" ("+[...new Set(tools)].join(", ")+")":"")+"."));
    for(const p of pk.packages.slice(0,12)){
      const d=el("details","dsp-pkg");const sm=el("summary");sm.append(el("b",null,p.name),el("small",null," "+p.path+" · "+p.kinds.join(", ")));d.append(sm);
      if(p.languages.length)d.append(el("p","dsb-hint",p.languages.map(l=>l.name+" "+l.files).join(" · ")));
      if(p.depends_on.length)d.append(el("p","dsb-hint","Uses: "+p.depends_on.join(", ")));
      for(const c of p.commands){d.append(el("p","dsp-cmd-label",c.label));const pre=el("pre","dss-cmd");pre.append(el("code",null,c.command));d.append(pre);}
      s.main.append(d);
    }
    if(pk.package_count>12)s.main.append(el("p","dsb-hint","…and "+(pk.package_count-12)+" more."));
    if(pk.bindings.length){const d=el("details","dsp-more-box");d.append(el("summary",null,"Where languages meet ("+pk.bindings.length+")"));
      d.append(list(pk.bindings,b=>row(b.label,where(b.file,b.line)),""));s.main.append(d);}
    if(pk.generated.length){const d=el("details","dsp-more-box");d.append(el("summary",null,"Generated files ("+pk.generated.length+") — don't edit by hand"));
      d.append(list(pk.generated,g=>row(g.file,g.why),""));s.main.append(d);}
    s.main.append(el("p","dsb-hint",pk.note));
    return s.li;
  }

  function draw(){
    box.replaceChildren();
    const head=el("div","dsb-head");
    head.append(el("h3",null,"Project map"),el("p","dsb-hint","See how your files, languages and data connect, and rename things safely. Your code is only read, never run."));
    box.append(head);
    if(!project()){box.append(el("p","dsb-hint","Open a project first."));return;}
    if(notice)box.append(el("p","dsa-alert"+(notice.bad?" bad":" ok"),notice.text));
    const ol=el("ol","dsb-steps");ol.append(stepMap(),stepTrace(),stepModels(),stepRename(),stepPackages());box.append(ol);
  }
  draw();
  return {projectChanged(){map=null;look=null;tr=null;pk=null;rp=null;done=null;notice=null;oldName="";newName="";renamePath="";lookPath="";draw();},refresh:draw};
}

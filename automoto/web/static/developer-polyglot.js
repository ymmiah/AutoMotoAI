/* Project map (V37-V40, "polyglot intelligence"), beginner face.
   Five guided steps, each with one plain sentence and one big result or action:
   map your project -> pages talking to your server -> your data -> rename something safely ->
   parts of your project. Technical evidence (file:line, link lists, binding kinds, commands) sits
   behind "Show details", collapsed by default. At most 3 items show before "Show all".
   Everything comes from the user's own project files, which are untrusted: names, paths and lines
   reach the page only through textContent, and nothing in the project is ever run. Nothing is
   stored in the browser. */
import {ring} from "./developer-beginner.js";
const BASE="/api/developer/studio/polyglot";
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const btn=(text,cls,fn)=>{const b=el("button","btn "+(cls||""),text);b.type="button";if(fn)b.onclick=fn;return b;};
const plural=(n,one,many)=>n+" "+(n===1?one:(many||one+"s"));
const VISIBLE=3;
function names(list){
  if(!list.length)return "";
  if(list.length<=2)return list.join(" and ");
  return list.slice(0,2).join(", ")+" and "+plural(list.length-2,"more","more");
}
function step(n,title,state,lead){
  const li=el("li","dsb-step s-"+state);li.append(el("span","dsb-num",state==="done"?"✓":String(n)));
  const main=el("div","dsb-step-main");main.append(el("b",null,title));
  if(lead)main.append(el("p","dsp-lead",lead));
  li.append(main);return {li,main};
}
function card(passed,total,tone,title,text,fallback,button){
  const c=el("div","dsb-check t-"+tone);c.append(ring(passed,total,tone,fallback));
  const t=el("div","dsb-check-text");t.append(el("b",null,title));if(text)t.append(el("p",null,text));c.append(t);
  if(button){button.classList.add("dsb-check-btn");c.append(button);}
  return c;
}
const code=text=>{const pre=el("pre","dsp-code");pre.append(el("code",null,text));return pre;};

export function mountDeveloperPolyglot({api,host,getProject,status,openTool}){
  const root=host.querySelector("#dsPolyglotRoot");if(!root)return null;
  const box=el("section","dsb dsp");box.setAttribute("aria-label","Project map");root.append(box);
  let map=null,look=null,tr=null,pk=null,rp=null,done=null,busy=null,notice=null,lookPath="",contractOk=false;
  let oldName="",newName="",renamePath="";
  const opened=new Set(),all=new Set();
  const project=()=>getProject?.()?.project||null;
  const trusted=()=>!!getProject?.()?.trusted;
  const say=(text,bad)=>{notice={text,bad};if(status)status(text,bad);};
  const friendly=(what,e)=>"I couldn't "+what+". "+(e?.message?e.message+" ":"")+"Try again, or open a different project.";
  async function act(what,fn){
    if(busy)return;busy=what;notice=null;draw();
    try{await fn();}catch(e){say(friendly(what,e),true);}
    finally{busy=null;draw();}
  }
  const go=(path,extra)=>api(BASE+path,{project:project(),...(extra||{})});
  const doMap=()=>act("map your project",async()=>{map=await go("/map");look=null;});
  const doTrace=()=>act("check the connections",async()=>{tr=await go("/trace");});
  const doPackages=()=>act("find the parts of your project",async()=>{pk=await go("/packages");});
  const doLook=()=>act("look up that file",async()=>{look=await go("/file",{path:lookPath.trim()});});
  const doPreview=()=>act("preview the rename",async()=>{done=null;contractOk=false;rp=await go("/rename/preview",{old:oldName.trim(),new:newName.trim(),path:renamePath.trim()||null});});
  async function doApply(){
    if(!rp?.action_sha256)return;
    const lines=["Rename "+rp.old+" to "+rp.new+"?","",plural(rp.places,"change")+" in "+plural(rp.files.length,"file")+":",
      ...rp.files.slice(0,12).map(f=>"  "+f.path+" ("+f.count+")"),"","Comments and text in quotes are left alone. You can undo this."];
    if(!window.confirm(lines.join("\n")))return;
    await act("rename it",async()=>{done=await go("/rename/apply",{action_sha256:rp.action_sha256,confirmed:true,contract_ok:contractOk});rp=null;map=null;tr=null;say("Renamed in "+plural(done.files.length,"file")+".");});
  }
  const doUndo=()=>act("undo the rename",async()=>{await go("/rename/undo",{undo_id:done.undo_id});say("Put back "+plural(done.files.length,"file")+".");done=null;map=null;tr=null;});
  const action=(label,what,fn,cls)=>{const b=btn(busy===what?"Working…":label,cls||"primary dsp-go",fn);b.disabled=!!busy;return b;};

  // Collapsed "Show details" box; it stays open across redraws.
  function details(key,label,fill){
    const d=el("details","dsp-details");d.open=opened.has(key);
    d.ontoggle=()=>{if(d.open)opened.add(key);else opened.delete(key);};
    d.append(el("summary",null,label||"Show details"));
    const body=el("div","dsp-details-body");fill(body);d.append(body);return d;
  }
  // A short list: the first 3, then "Show all (N)".
  function few(key,items,render){
    const ul=el("ul","dsp-items");const showAll=all.has(key);
    for(const i of (showAll?items:items.slice(0,VISIBLE)))ul.append(render(i));
    const wrap=el("div","dsp-few");wrap.append(ul);
    if(items.length>VISIBLE){const b=btn(showAll?"Show fewer":"Show all ("+items.length+")","link sm dsp-all",()=>{showAll?all.delete(key):all.add(key);draw();});wrap.append(b);}
    return wrap;
  }
  function item(main,sub,tone){
    const li=el("li",tone?"t-"+tone:null);li.append(el("span","dsp-item-main",main));
    if(sub)li.append(el("span","dsp-item-sub",sub));return li;
  }
  const at=(file,line)=>file+(line?" · line "+line:"");

  // ---- 1. Map your project (V37)
  function stepMap(){
    const s=step(1,"Map your project",map?"done":"now","Find the languages in your project and how its files link together.");
    if(!map){s.main.append(action("Map my project","map your project",doMap));return s.li;}
    const b=map.budget;const langs=map.languages.map(l=>l.name);
    if(!b.read){s.main.append(el("p","dsp-empty","I didn't find any code files here yet. Add some files, then map again."),action("Map again","map your project",doMap,"sm"));return s.li;}
    s.main.append(card(b.read,b.found,b.truncated?"busy":"ok","Mapped "+plural(b.read,"file"),
      (names(langs)||"No code languages found")+(b.truncated?". Your project is big, so I mapped part of it.":""),"✓",btn("Map again","sm",doMap)));
    s.main.append(el("p","dsp-fact",map.broken_count?plural(map.links,"link")+" between files · "+plural(map.broken_count,"needs","need")+" fixing"
      :plural(map.links,"link")+" between files, and none are broken."));
    s.main.append(details("map","Show details",body=>{
      if(map.broken_count){body.append(el("h5",null,"Links that point at a missing file"));
        body.append(few("broken",map.broken,i=>item(i.spec,at(i.file,i.line),"bad")));}
      if(map.hubs.length){body.append(el("h5",null,"Files used the most"));
        body.append(few("hubs",map.hubs,i=>item(i.file,"used by "+plural(i.used_by,"file"))));}
      if(map.cross_language_links){body.append(el("h5",null,"Where one language uses another"));
        body.append(few("cross",map.cross_language_examples,i=>item(i.from+" → "+i.to,"line "+i.line)));}
      if(map.languages.length){body.append(el("h5",null,"Languages"));
        body.append(few("langs",map.languages,l=>item(l.name,plural(l.files,"file"))));}
      body.append(el("h5",null,"Look up one file"));
      const f=el("div","dsp-row");const l=el("label","dss-field");l.append(el("span",null,"File"));
      const i=el("input");i.value=lookPath;i.placeholder="src/app.ts";i.spellcheck=false;i.autocomplete="off";i.oninput=()=>{lookPath=i.value;};l.append(i);
      f.append(l,action("Show links","look up that file",doLook,"sm"));body.append(f);
      if(look){
        body.append(el("p","dsp-fact",look.file+" uses "+plural(look.uses.length,"file")+" and is used by "+plural(look.used_by.length,"file")+"."));
        if(look.uses.length)body.append(few("uses",look.uses,e=>item(e.to,"line "+e.line)));
        if(look.used_by.length)body.append(few("usedby",look.used_by,e=>item(e.from,"line "+e.line)));
      }
    }));
    return s.li;
  }
  // ---- 2. Pages talking to your server (V38)
  function stepTrace(){
    const s=step(2,"Pages talking to your server",tr?(tr.state==="passed"?"done":"now"):map?"now":"todo",
      "Check that each call from your app reaches server code that answers it.");
    if(!tr){s.main.append(action("Check the connections","check the connections",doTrace));return s.li;}
    if(!tr.calls){s.main.append(el("p","dsp-empty","Your app doesn't call your own server yet, so there's nothing to check."),action("Check again","check the connections",doTrace,"sm"));return s.li;}
    const fixed=tr.unknown.filter(u=>!u.call.variable_base),changing=tr.unknown.filter(u=>u.call.variable_base);
    const missing=fixed.length;
    const title=tr.countable?tr.matched+" of "+tr.countable+" connections work":"Nothing to check for sure";
    const text=tr.state==="passed"?"Every call reaches your server.":missing?plural(missing,"call doesn't","calls don't")+" reach any server code."
      :"These calls use an address that changes while the app runs.";
    s.main.append(card(tr.matched,tr.countable,tr.state==="passed"?"ok":tr.countable?"bad":"idle",title,text,"–",btn("Check again","sm",doTrace)));
    const rows=[...fixed.map(u=>({bad:true,u})),...tr.chains.map(c=>({c})),...changing.map(u=>({maybe:true,u}))];
    s.main.append(few("trace",rows,r=>r.bad?item(r.u.call.raw,"No server code answers this","bad")
      :r.maybe?item(r.u.call.raw,"The address changes while the app runs, so I can't check it")
      :item(r.c.call.raw+"  →  "+(r.c.route.handler||"server"),r.c.models.length?"uses "+names(r.c.models):null,"ok")));
    s.main.append(details("trace","Show details",body=>{
      if(tr.chains.length){body.append(el("h5",null,"Working connections"));
        body.append(few("chains",tr.chains,c=>item(c.call.method+" "+c.call.raw,at(c.call.file,c.call.line)+" → "+at(c.route.file,c.route.line))));}
      if(tr.unknown.length){body.append(el("h5",null,"Calls with no answer"));
        body.append(few("unknown",tr.unknown,u=>item(u.call.method+" "+u.call.raw,at(u.call.file,u.call.line)+" · "+u.why)));}
      if(tr.possible.length){body.append(el("h5",null,"Maybe (not counted)"));
        body.append(el("p","dsb-hint","The address starts with something that changes, so I can't be sure."));
        body.append(few("possible",tr.possible,p=>item(p.call.raw,at(p.call.file,p.call.line))));}
      if(tr.routes_without_calls.length){body.append(el("h5",null,"Server code your app doesn't call"));
        body.append(few("lonely",tr.routes_without_calls,r=>item(r.method+" "+r.path,at(r.file,r.line))));}
      body.append(el("p","dsb-hint",tr.note));
    }));
    return s.li;
  }
  // ---- 3. Your data (V37)
  function stepModels(){
    const s=step(3,"Your data",map?"done":"todo","The tables and models where your app keeps its data.");
    if(!map){s.main.append(el("p","dsp-empty","Map your project first (step 1)."));return s.li;}
    if(!map.models.length){s.main.append(el("p","dsp-empty","I didn't find any database tables or models. That's fine if your app doesn't store data."));return s.li;}
    const uniq=[...new Set(map.models.map(m=>m.name))];
    s.main.append(el("p","dsp-big",plural(uniq.length,"kind")+" of data"));
    s.main.append(few("models",uniq,n=>item(n,null)));
    s.main.append(details("models","Show details",body=>{
      body.append(few("modeld",map.models,m=>item(m.name,m.kind+" · "+at(m.file,m.line))));
      if(map.model_relations.length){body.append(el("h5",null,"How they connect"));
        body.append(few("rels",map.model_relations,r=>item(r.from+" → "+r.to,r.how)));}
    }));
    return s.li;
  }
  // ---- 4. Rename something safely (V39)
  function stepRename(){
    const s=step(4,"Rename something safely",done?"done":"now","Change a name everywhere it's used. You see every change before anything is saved.");
    const f=el("div","dsp-row");
    const pb=action("Preview","preview the rename",doPreview);
    const sync=()=>{pb.disabled=!!busy||!oldName.trim()||!newName.trim();};sync();
    const input=(label,value,ph,set)=>{const l=el("label","dss-field");l.append(el("span",null,label));const i=el("input");i.value=value;i.placeholder=ph;i.spellcheck=false;i.autocomplete="off";i.oninput=()=>{set(i.value);sync();};l.append(i);return l;};
    f.append(input("Current name",oldName,"loadUsers",v=>{oldName=v;}),input("New name",newName,"fetchUsers",v=>{newName=v;}));
    s.main.append(f);
    s.main.append(details("renameopt","More options",body=>{
      body.append(input("Only the name defined in this file",renamePath,"src/api.ts",v=>{renamePath=v;}));
      body.append(el("p","dsb-hint","Tip: save a checkpoint first, so you can always go back."));
      body.append(btn("Save a checkpoint","sm",()=>openTool?.("git")));
    }));
    s.main.append(pb);
    if(rp){
      if(rp.state!=="ready"){
        const r=el("div","dsp-result t-bad");r.append(el("b",null,"Not safe to rename yet"),el("p",null,rp.blocks[0]||"Something doesn't look right."));s.main.append(r);
        if(rp.choices.length){
          s.main.append(el("p","dsp-lead","Which one do you mean?"));
          s.main.append(few("choices",rp.choices,ch=>{const li=el("li");li.append(btn(ch.file,"sm",()=>{renamePath=ch.file;void doPreview();}));return li;}));
        }
        if(rp.blocks.length>1)s.main.append(details("blocks","Show details",body=>{for(const b of rp.blocks.slice(1))body.append(el("p","dsb-hint",b));}));
      }else{
        const r=el("div","dsp-result t-ok");r.append(el("b",null,plural(rp.places,"change")+" in "+plural(rp.files.length,"file")),el("p",null,"Only code changes. Comments and text in quotes stay the same."));s.main.append(r);
        s.main.append(few("rfiles",rp.files,x=>item(x.path,plural(x.count,"change"))));
        s.main.append(details("rdiff","Show the changes",body=>{
          for(const x of rp.files.slice(0,10)){body.append(el("h5",null,x.path));for(const e of x.examples)body.append(code("line "+e.line+"\n- "+e.before+"\n+ "+e.after));}
          for(const w of rp.warnings)body.append(el("p","dsb-hint",w.text));
        }));
        const contract=rp.warnings.find(w=>w.kind==="contract");
        if(contract){
          s.main.append(el("p","dsp-warn","Heads up: this name is used by your server or your data. "+contract.text));
          const l=el("label","dsv-check");const i=el("input");i.type="checkbox";i.checked=contractOk;i.onchange=()=>{contractOk=i.checked;draw();};
          l.append(i,el("span",null,"I've checked this"));s.main.append(l);
        }
        if(!trusted())s.main.append(el("p","dsp-warn","To save changes, allow changes for this project first."));
        const ab=btn("Rename","primary dsp-go",doApply);ab.disabled=!!busy||!trusted()||(rp.needs_contract_ok&&!contractOk);s.main.append(ab);
      }
    }
    if(done){
      const r=el("div","dsp-result t-ok");r.append(el("b",null,"Renamed "+done.old+" to "+done.new),el("p",null,"Changed "+plural(done.files.length,"file")+"."));
      r.append(action("Undo rename","undo the rename",doUndo,"sm"));s.main.append(r);
    }
    return s.li;
  }
  // ---- 5. Parts of your project (V40)
  function stepPackages(){
    const s=step(5,"Parts of your project",pk?"done":"now","Big projects are split into parts. See each part and how to build it.");
    if(!pk){s.main.append(action("Show the parts","find the parts of your project",doPackages));return s.li;}
    if(!pk.packages.length){s.main.append(el("p","dsp-empty","This project is one simple folder, with no separate parts."));return s.li;}
    s.main.append(el("p","dsp-big",pk.package_count===1?"1 part":pk.package_count+" parts"));
    s.main.append(few("parts",pk.packages,p=>item(p.name,p.languages.slice(0,2).map(l=>l.name).join(" and ")||null)));
    const meet=[...new Set(pk.bindings.map(b=>b.label.replace(/\s*\(.*\)$/,"")))];
    if(meet.length)s.main.append(el("p","dsp-fact","Languages that work together: "+names(meet)+"."));
    if(pk.generated.length)s.main.append(el("p","dsp-fact",plural(pk.generated.length,"file is","files are")+" made by a tool, so don't edit "+(pk.generated.length===1?"it":"them")+" by hand."));
    s.main.append(details("parts","How to build each part",body=>{
      body.append(el("p","dsb-hint","Copy a command into your terminal when you're ready. AutoMoto doesn't run them."));
      for(const p of pk.packages.slice(0,all.has("cmds")?pk.packages.length:VISIBLE)){
        body.append(el("h5",null,p.name+(p.path!=="."?" ("+p.path+")":"")));
        if(p.depends_on.length)body.append(el("p","dsb-hint","Uses "+names(p.depends_on)+"."));
        for(const c of p.commands){body.append(el("p","dsp-cmd-label",c.label));body.append(code(c.command));}
        if(!p.commands.length)body.append(el("p","dsb-hint","No build steps needed."));
      }
      if(pk.packages.length>VISIBLE)body.append(btn(all.has("cmds")?"Show fewer":"Show all ("+pk.packages.length+")","link sm dsp-all",()=>{all.has("cmds")?all.delete("cmds"):all.add("cmds");draw();}));
    }));
    if(pk.bindings.length||pk.generated.length||pk.tools.length)s.main.append(details("tech","Show details",body=>{
      if(pk.tools.length){body.append(el("h5",null,"Workspace tools"));body.append(few("tools",pk.tools,t=>item(t.tool,t.file)));}
      if(pk.bindings.length){body.append(el("h5",null,"Where languages meet"));body.append(few("binds",pk.bindings,b=>item(b.label,at(b.file,b.line))));}
      if(pk.generated.length){body.append(el("h5",null,"Made by a tool"));body.append(few("gen",pk.generated,g=>item(g.file,g.why)));}
    }));
    return s.li;
  }

  function draw(){
    const y=window.scrollY;
    box.replaceChildren();
    const head=el("div","dsb-head");
    head.append(el("h3",null,"Project map"),el("p","dsb-hint","See how your project fits together. Your code is only read, never run."));
    box.append(head);
    if(!project()){box.append(el("p","dsp-empty","Open a project first, then come back here."));return;}
    if(notice)box.append(el("p","dsa-alert"+(notice.bad?" bad":" ok"),notice.text));
    const ol=el("ol","dsb-steps");ol.append(stepMap(),stepTrace(),stepModels(),stepRename(),stepPackages());box.append(ol);
    if(window.scrollY!==y)window.scrollTo(0,y);
  }
  // Draw only once the card is first shown (it lives inside Tools and is hidden otherwise), so the
  // hidden card adds no work to the Developer start screen.
  let shown=false;
  const show=()=>{shown=true;draw();};
  if("IntersectionObserver" in window){new IntersectionObserver(es=>{if(es.some(e=>e.isIntersecting))show();}).observe(root);}else show();
  const redraw=()=>{if(shown)draw();};
  return {projectChanged(){map=null;look=null;tr=null;pk=null;rp=null;done=null;notice=null;oldName="";newName="";renamePath="";lookPath="";opened.clear();all.clear();redraw();},refresh:redraw};
}

/* Developer Studio V45: local Git for the open project. Status, branches, stage,
   commit, diffs and a conflict view. Everything stays on this computer: there is
   no push, pull or fetch here. */
const BRAND=document.querySelector('meta[name="automoto-brand-short"]')?.content||"AutoMoto";
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const LABEL={modified:"changed",added:"new",deleted:"deleted",renamed:"renamed",copied:"copied",untracked:"new","type changed":"changed",conflict:"conflict"};
export function mountDeveloperGit({api,host,getProject,status,afterFilesChanged}){
  const BASE="/api/developer/studio/git";
  const root=host.querySelector("#dsGitRoot");
  root.innerHTML='<section class="dsg" aria-label="Git">'+
    '<div class="dsr-head"><div><h3>Git</h3><p class="dsr-note">Saves versions of your project on this computer. '+BRAND+' never pushes or uploads anything.</p></div>'+
    '<span class="dsx-gap"></span><button type="button" class="btn sm" id="dsgRefresh">Refresh</button></div>'+
    '<div id="dsgInit" class="dsg-empty" hidden><p>This folder isn\'t using Git yet.</p><button type="button" class="btn sm primary" id="dsgInitBtn">Start tracking with Git</button></div>'+
    '<div id="dsgMain" hidden>'+
      '<div class="dsg-branchbar"><label for="dsgBranch">Branch</label><select id="dsgBranch" class="input"></select>'+
        '<input id="dsgNewBranch" class="input" type="text" maxlength="100" placeholder="new-branch-name" aria-label="New branch name">'+
        '<button type="button" class="btn sm" id="dsgCreate">New branch</button><span class="dsx-gap"></span><span class="dsg-summary" id="dsgSummary"></span></div>'+
      '<div class="dsg-cols">'+
        '<div class="dsg-lists">'+
          '<div class="dsg-group" id="dsgConflictsBox" hidden><h4>Conflicts</h4><div id="dsgConflicts" role="list"></div></div>'+
          '<div class="dsg-group"><div class="dsg-group-h"><h4>Staged for commit</h4><span class="dsx-gap"></span><button type="button" class="btn sm" id="dsgUnstageAll">Unstage all</button></div><div id="dsgStaged" role="list"></div></div>'+
          '<div class="dsg-group"><div class="dsg-group-h"><h4>Changes</h4><span class="dsx-gap"></span><button type="button" class="btn sm" id="dsgStageAll">Stage all</button></div><div id="dsgChanges" role="list"></div></div>'+
          '<form class="dsg-commit" id="dsgCommitForm"><label for="dsgMessage">Commit message</label>'+
            '<textarea id="dsgMessage" class="input" rows="2" maxlength="5000" placeholder="Say what changed, e.g. Fix the counter button"></textarea>'+
            '<div class="dsg-ident" id="dsgIdent" hidden><input id="dsgName" class="input" maxlength="120" placeholder="Your name" aria-label="Your name for commits"><input id="dsgEmail" class="input" maxlength="200" placeholder="you@example.com" aria-label="Your email for commits"></div>'+
            '<button type="submit" class="btn sm primary" id="dsgCommit" disabled>Commit</button></form>'+
          '<div class="dsg-group"><h4>Recent commits</h4><ol class="dsg-log" id="dsgLog"></ol></div>'+
        '</div>'+
        '<div class="dsg-viewer" id="dsgViewer" aria-live="polite"><p class="dsr-note">Pick a file to see what changed.</p></div>'+
      '</div>'+
    '</div>'+
    '<p class="dsr-status" id="dsgStatus" role="status" aria-live="polite">Open a project to see its Git status.</p></section>';
  const $=id=>root.querySelector("#"+id);
  let state=null,seq=0,busy=false,branchList=[],lastError=null;
  const listeners=new Set();
  const notify=()=>{for(const fn of listeners)try{fn();}catch(e){console.error(e);}};
  const say=(text,bad)=>{$("dsgStatus").textContent=text;$("dsgStatus").classList.toggle("bad",!!bad);};
  const trusted=()=>!!getProject()?.trusted;

  async function load(){
    const p=getProject()?.project;
    if(!p){state=null;$("dsgInit").hidden=true;$("dsgMain").hidden=true;say("Open a project to see its Git status.");return;}
    const id=++seq;
    try{
      const d=await api(BASE+"/status?"+new URLSearchParams({project:p}));
      if(id!==seq)return;
      state=d;draw();notify();
    }catch(e){if(id===seq){state=null;$("dsgMain").hidden=true;$("dsgInit").hidden=true;say("Git isn't available here: "+e.message,true);notify();}}
  }
  async function act(path,body,done){
    if(busy)return null;busy=true;syncButtons();
    try{const d=await api(BASE+path,{project:getProject().project,...body});if(d&&d.repository!==undefined)state={...state,...d};draw();done&&say(done);afterFilesChanged?.();notify();return d;}
    catch(e){say(e.message,true);if(e.status===428)$("dsgIdent").hidden=false;lastError=e;notify();return null;}
    finally{busy=false;syncButtons();}
  }
  function row(f,kind){
    const r=el("div","dsg-row");r.setAttribute("role","listitem");
    const name=el("button","dsg-file",f.path);name.type="button";name.title="Show changes";
    name.onclick=()=>void (f.conflict?showConflict(f.path):showDiff(f.path,kind==="staged"));
    const tag=f.conflict?"conflict":kind==="staged"?f.index:f.worktree;
    r.append(name,el("span","dsx-gap"),el("span","dsx-badge "+(tag==="deleted"||f.conflict?"b-bad":tag==="untracked"||tag==="added"?"b-ok":"b-acc"),LABEL[tag]||tag||"changed"));
    if(f.secret_like)r.append(el("span","dsx-badge b-bad","secret?"));
    if(f.conflict){const b=el("button","btn sm","Resolve");b.type="button";b.onclick=()=>void showConflict(f.path);r.append(b);}
    else if(kind==="staged"){const b=el("button","btn sm","Unstage");b.type="button";b.onclick=()=>void act("/stage",{paths:[f.path],stage:false},"Unstaged "+f.path+".");r.append(b);}
    else{const b=el("button","btn sm","Stage");b.type="button";b.disabled=f.secret_like;b.title=f.secret_like?"Looks like a secret file":"";b.onclick=()=>void act("/stage",{paths:[f.path],stage:true},"Staged "+f.path+".");r.append(b);}
    return r;
  }
  function draw(){
    if(!state)return;
    if(!state.repository){$("dsgInit").hidden=false;$("dsgMain").hidden=true;$("dsgInitBtn").disabled=!trusted();say(trusted()?"Start tracking to save versions of your work.":"Allow changes for this project first.");return;}
    $("dsgInit").hidden=true;$("dsgMain").hidden=false;
    const files=state.files||[];
    const conflicts=files.filter(f=>f.conflict),staged=files.filter(f=>f.staged),changes=files.filter(f=>!f.conflict&&f.unstaged);
    $("dsgConflictsBox").hidden=!conflicts.length;
    $("dsgConflicts").replaceChildren(...conflicts.map(f=>row(f,"conflict")));
    $("dsgStaged").replaceChildren(...(staged.length?staged.map(f=>row(f,"staged")):[el("p","dsr-note","Nothing staged yet.")]));
    $("dsgChanges").replaceChildren(...(changes.length?changes.map(f=>row(f,"changes")):[el("p","dsr-note",state.clean?"Everything is committed.":"No other changes.")]));
    const sel=$("dsgBranch");
    void loadBranches();
    $("dsgSummary").textContent=(state.detached?"Detached at "+state.head:"On "+(state.branch||"main"))+" · "+files.length+" changed"+(conflicts.length?" · "+conflicts.length+" in conflict":"");
    const log=$("dsgLog");log.replaceChildren();
    for(const c of state.recent||[]){const li=el("li");li.append(el("code",null,c.sha),el("span",null," "+c.subject),el("span","dsr-note"," · "+c.when));log.append(li);}
    if(!(state.recent||[]).length)log.append(el("li","dsr-note","No commits yet."));
    if(state.identity&&!state.identity.configured)$("dsgIdent").hidden=false;
    say(conflicts.length?"Some files are in conflict. Pick which version to keep for each one."
      :!trusted()?"Read-only: allow changes for this project to stage and commit."
      :staged.length?staged.length+" file"+(staged.length>1?"s":"")+" ready to commit."
      :changes.length?"Stage the files you want to save, then commit.":"All saved. Nothing to commit.");
    syncButtons();
    void sel;
  }
  async function loadBranches(){
    const p=getProject()?.project;if(!p||!state?.repository)return;
    try{
      const d=await api(BASE+"/branches?"+new URLSearchParams({project:p}));
      const sel=$("dsgBranch");sel.replaceChildren();
      const list=d.branches||[];branchList=list;notify();
      if(!list.length)sel.append(new Option(state.branch||"main",state.branch||"main",true,true));
      for(const b of list)sel.append(new Option(b.name,b.name,b.current,b.current));
    }catch{}
  }
  function syncButtons(){
    const t=trusted(),s=state||{},files=s.files||[];
    const staged=files.filter(f=>f.staged).length,changes=files.filter(f=>!f.conflict&&f.unstaged&&!f.secret_like).length;
    $("dsgCommit").disabled=busy||!t||(!staged&&!s.merging)||!!s.counts?.conflicts||$("dsgMessage").value.trim().length<2;
    $("dsgCommit").textContent=staged?"Commit "+staged+" file"+(staged>1?"s":""):"Commit";
    $("dsgStageAll").disabled=busy||!t||!changes;$("dsgUnstageAll").disabled=busy||!t||!staged;
    $("dsgCreate").disabled=busy||!t||!$("dsgNewBranch").value.trim();
    $("dsgBranch").disabled=busy||!t;
  }
  function diffView(path,text,note){
    const v=$("dsgViewer");v.replaceChildren();
    const box=el("div","dsx-file");const h=el("div","dsx-file-h");h.append(el("code",null,path));if(note)h.append(el("span","dsx-gap"),el("span","dsr-note",note));box.append(h);
    if(!text){box.append(el("p","dsx-muted dsx-pad","No text difference."));v.append(box);return;}
    const pre=el("pre","dsx-diff");
    for(const line of text.split("\n")){
      if(/^(diff --git|index |--- |\+\+\+ )/.test(line))continue;
      const cls=line.startsWith("@@")?"h":line.startsWith("+")?"a":line.startsWith("-")?"d":"";
      pre.append(el("span",cls,line+"\n"));
    }
    box.append(pre);v.append(box);
  }
  async function showDiff(path,staged){
    try{
      const d=await api(BASE+"/diff?"+new URLSearchParams({project:getProject().project,path,staged:String(staged)}));
      diffView(path,d.hidden?"":d.diff,d.hidden?d.reason:staged?"staged":d.untracked?"new file":"not staged yet");
    }catch(e){diffView(path,"",e.message);}
  }
  async function showConflict(path,into,friendly=false){
    const v=into||$("dsgViewer");v.replaceChildren();
    const L=friendly?{ours:"Your version",theirs:"The other version",mine:"Use mine",their:"Use theirs",both:"Keep both",save:"Use my choices",ask:"Save "+path+" with your choices?"}
      :{ours:"Yours",theirs:"Theirs",mine:"Keep mine",their:"Keep theirs",both:"Keep both",save:"Save and mark resolved",ask:"Save "+path+" with your choices and mark it resolved?"};
    let d;
    try{d=await api(BASE+"/conflict?"+new URLSearchParams({project:getProject().project,path}));}
    catch(e){v.append(el("p","dsr-status bad",e.message));return;}
    const choices=d.blocks.map(()=>null);
    if(!friendly){const head=el("div","dsx-file-h");head.append(el("code",null,path),el("span","dsx-gap"),el("span","dsr-note",d.blocks.length+" conflict"+(d.blocks.length>1?"s":"")));v.append(head);}
    const save=el("button","btn sm primary",L.save);save.type="button";save.disabled=true;
    d.blocks.forEach((b,i)=>{
      const card=el("div","dsg-conflict");
      card.append(el("p","dsr-note",friendly?(d.blocks.length>1?"Disagreement "+(i+1)+" of "+d.blocks.length:"Both versions changed these lines:"):"Lines "+b.start_line+"–"+b.end_line));
      const cols=el("div","dsg-sides");
      const side=(title,text)=>{const c=el("div","dsg-side");c.append(el("b",null,title),el("pre",null,text||"(empty)"));return c;};
      cols.append(side(friendly?L.ours:L.ours+" · "+(b.ours_label||"current"),b.ours),side(friendly?L.theirs+(b.theirs_label?" (from "+b.theirs_label.replace(/^feature\//,"")+")":""):L.theirs+" · "+(b.theirs_label||"incoming"),b.theirs));
      card.append(cols);
      const pick=el("div","dsg-pick");pick.setAttribute("role","group");pick.setAttribute("aria-label","Choose for conflict "+(i+1));
      for(const [val,label] of [["ours",L.mine],["theirs",L.their],["both",L.both]]){
        const btn=el("button","btn sm",label);btn.type="button";btn.setAttribute("aria-pressed","false");
        btn.onclick=()=>{choices[i]=val;for(const x of pick.children)x.setAttribute("aria-pressed",String(x===btn));save.disabled=choices.some(c=>!c)||!trusted();};
        pick.append(btn);
      }
      card.append(pick);v.append(card);
    });
    save.onclick=async()=>{
      if(!window.confirm(L.ask))return;
      const done=await act("/resolve",{path,choices,expected_sha256:d.sha256,confirmed:true},"Resolved "+path+".");
      if(done)v.replaceChildren(el("p","dsr-note","Fixed "+path+". Save a checkpoint when you're ready."));
    };
    v.append(save);
  }
  $("dsgRefresh").addEventListener("click",()=>void load());
  $("dsgInitBtn").addEventListener("click",async()=>{
    if(!window.confirm("Start tracking this folder with Git? This creates a .git folder here. Nothing is uploaded."))return;
    await act("/init",{confirmed:true},"Git is now tracking this project.");
  });
  $("dsgStageAll").addEventListener("click",()=>{const paths=(state?.files||[]).filter(f=>!f.conflict&&f.unstaged&&!f.secret_like).map(f=>f.path);if(paths.length)void act("/stage",{paths,stage:true},"Staged "+paths.length+" files.");});
  $("dsgUnstageAll").addEventListener("click",()=>{const paths=(state?.files||[]).filter(f=>f.staged).map(f=>f.path);if(paths.length)void act("/stage",{paths,stage:false},"Unstaged all files.");});
  $("dsgMessage").addEventListener("input",syncButtons);
  $("dsgNewBranch").addEventListener("input",syncButtons);
  $("dsgCreate").addEventListener("click",async()=>{
    const name=$("dsgNewBranch").value.trim();if(!name)return;
    const d=await act("/branch",{name,switch:true},"Created and switched to "+name+".");
    if(d){$("dsgNewBranch").value="";await load();}
  });
  $("dsgBranch").addEventListener("change",async e=>{
    const name=e.target.value;if(!name||name===state?.branch)return;
    const d=await act("/switch",{name},"Switched to "+name+".");
    if(!d)await loadBranches(); else await load();
  });
  $("dsgCommitForm").addEventListener("submit",async e=>{
    e.preventDefault();
    const message=$("dsgMessage").value.trim();if(message.length<2)return;
    const n=(state?.files||[]).filter(f=>f.staged).length;
    if(!window.confirm("Commit "+n+" file"+(n===1?"":"s")+" on "+(state?.branch||"this branch")+"?\n\n“"+message.split("\n")[0]+"”\n\nThis saves a version on this computer only. Nothing is pushed."))return;
    const body={message,confirmed:true};
    const name=$("dsgName").value.trim(),email=$("dsgEmail").value.trim();
    if(!$("dsgIdent").hidden&&name&&email){body.author_name=name;body.author_email=email;}
    const d=await act("/commit",body,"Committed. Saved on this computer; nothing was pushed.");
    if(d){$("dsgMessage").value="";$("dsgViewer").replaceChildren(el("p","dsr-note","Committed “"+message.split("\n")[0]+"”."));syncButtons();}
  });
  async function fetchDiff(path,staged=false){
    const d=await api(BASE+"/diff?"+new URLSearchParams({project:getProject().project,path,staged:String(staged)}));
    return d.hidden?"":d.diff;
  }
  async function saveCheckpoint(message,author){
    lastError=null;
    const paths=(state?.files||[]).filter(f=>!f.conflict&&f.unstaged&&!f.secret_like).map(f=>f.path);
    if(paths.length&&!(await act("/stage",{paths,stage:true})))return null;
    const body={message,confirmed:true};
    if(author?.name&&author?.email){body.author_name=author.name;body.author_email=author.email;}
    return act("/commit",body,"Checkpoint saved on this computer. Nothing was uploaded.");
  }
  return {load,fetchDiff,saveCheckpoint,showConflict,
    init:()=>act("/init",{confirmed:true},"Git is now tracking this project."),
    newIdea:name=>act("/branch",{name,switch:true},"Now trying "+name+".").then(async d=>{if(d)await load();return d;}),
    switchTo:name=>act("/switch",{name},"Switched to "+name+".").then(async d=>{await load();return d;}),
    onChange(fn){listeners.add(fn);return ()=>listeners.delete(fn);},
    getState:()=>({state,branches:branchList,busy,lastError,trusted:trusted(),project:getProject()}),
    projectChanged(){$("dsgViewer").replaceChildren(el("p","dsr-note","Pick a file to see what changed."));void load();},trustChanged(){void load();}};
}

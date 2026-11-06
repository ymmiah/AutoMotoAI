/* Visual Studio: native exported scene renderer, editable layers and bounded GIF tracks.
   Backend renders the final preview. Edits keep source imagery unchanged. */
import {layerUnits,unitKey,toggleLayer,moveLayer,selectionBox,resizeSelection,
        selectedLayerUnits,selectionBounds,translateLayerUnits,alignLayerUnits,
        distributeLayerUnits,groupLayerUnits,ungroupLayerUnits,snapLayerDelta,
        sequenceTracks,normaliseSequence} from "./visual-studio-layers.js";
const Q=(s,r=document)=>r.querySelector(s);
const QA=(s,r=document)=>Array.from(r.querySelectorAll(s));
const copy=v=>JSON.parse(JSON.stringify(v));
const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
const NS="http://www.w3.org/2000/svg";
const PALETTES={
  "illustrated-workflow":{ink:"#22252C",muted:"#5A606B",card:"#FFFFFF",border:"#25252D",tones:["#E8DBFA","#D6E9FF","#FFF1AA"]},
  "editorial-light":{ink:"#172638",muted:"#526476",card:"#FFFFFF",border:"#DCE5E9",tones:["#E8F3F1","#E7ECFB","#FFF0CF"]},
  "premium-tech":{ink:"#F8FAFC",muted:"#C3D0E1",card:"#19283E",border:"#34465E",tones:["#203D64","#234E51","#534267"]},
  "commercial":{ink:"#2C2520",muted:"#61594F",card:"#FFFFFF",border:"#E6D8CB",tones:["#F6E3D5","#EDE1D1","#F6D9D7"]}
};
const ICONS=["check","shield","idea","chart","users","clock","target","cloud","file","image","sparkle","globe","code","lock","settings"];

function template(kind,theme){
  const p=PALETTES[theme],a=[];
  const spec={layout:"canvas",width:1280,height:720,theme,title:"Visual storytelling",
              subtitle:"Original, editable components",elements:a};
  if(kind==="blank"){spec.title="Blank canvas";return spec;}
  const makeCard=(id,x,y,w,h,title,body,ico,i)=>{
    a.push({type:"rect",group:id,x,y,w,h,fill:p.card,stroke:p.border,radius:23,auto_fill:"card",auto_stroke:"border"});
    a.push({type:"rect",group:id,x:x+20,y:y+20,w:79,h:74,fill:p.tones[i%3],radius:18,auto_fill:"tone"+(i%3)});
    a.push({type:"icon",group:id,x:x+39,y:y+35,w:43,h:43,name:ico,colour:p.ink,auto_colour:"ink"});
    a.push({type:"text",group:id,x:x+22,y:y+110,w:w-44,h:46,text:title,font_size:27,bold:true,colour:p.ink,auto_colour:"ink"});
    a.push({type:"text",group:id,x:x+22,y:y+163,w:w-44,h:39,text:body,font_size:18,colour:p.muted,auto_colour:"muted"});
  };
  if(kind==="cards"){
    spec.title="Four powerful capabilities";
    spec.subtitle="Design, preserve, validate and publish";
    const cards=[["Design system","Consistent visual language","target"],
      ["Your assets","Preserve original identity","image"],
      ["Editable output","Native shapes and text","chart"],
      ["Animation","Genuine animated GIF","sparkle"]];
    for(let i=0;i<4;i++)makeCard("card"+i,70+(i%2)*575,210+Math.floor(i/2)*220,542,205,...cards[i],i);
  }else if(kind==="poster"){
    spec.title="Original editorial poster";
    makeCard("poster",95,250,700,275,"A more visual idea","Give your message space to stand out.","idea",0);
    a.push({type:"rect",group:"feature",x:855,y:250,w:330,h:290,fill:p.tones[1],radius:30,auto_fill:"tone1"});
    a.push({type:"icon",group:"feature",x:953,y:335,w:115,h:115,name:"sparkle",colour:p.ink,auto_colour:"ink"});
  }else{
    spec.title="Intelligent processing workflow";
    spec.subtitle="From the original input to a verified result";
    const cards=[["Receive","Original document","file"],["Process","Extract information","idea"],["Validate","Check the evidence","shield"]];
    a.push({type:"line",x1:365,y1:393,x2:490,y2:393,colour:p.ink,auto_colour:"ink",
            from_group:"stage0",to_group:"stage1",stroke_width:4});
    a.push({type:"line",x1:790,y1:393,x2:915,y2:393,colour:p.ink,auto_colour:"ink",
            from_group:"stage1",to_group:"stage2",stroke_width:4});
    for(let i=0;i<3;i++)makeCard("stage"+i,65+i*425,280,300,230,...cards[i],i);
  }
  return spec;
}
function themeElements(spec,name){
  const p=PALETTES[name];spec.theme=name;
  for(const e of spec.elements){
    for(const [a,b] of [["fill","auto_fill"],["stroke","auto_stroke"],["colour","auto_colour"]]){
      const tag=e[b];if(!tag)continue;
      e[a]=tag.startsWith("tone")?p.tones[Number(tag.slice(4))%3]:p[tag];
    }
  }
}
function bounds(e){
  if(e.type==="line")return {x:Math.min(e.x1,e.x2)-7,y:Math.min(e.y1,e.y2)-7,
    w:Math.abs(e.x2-e.x1)+14||14,h:Math.abs(e.y2-e.y1)+14||14};
  return {x:e.x,y:e.y,w:e.w,h:e.h};
}
function freePosition(spec,w,h){
  // Never insert a new text label directly on top of a card, image or icon.
  // Start below the content, then search upwards in a coarse collision grid.
  if(!spec.elements.length)return {x:100,y:275};
  const occupied=spec.elements.filter(e=>e.type!=="line").map(bounds);
  const limitX=spec.width-w-45,lowest=spec.height-h-40;
  if(limitX<45||lowest<180)return null;
  for(let y=lowest;y>=190;y-=25){
    for(let x=65;x<=limitX;x+=40){
      if(occupied.every(b=>x+w<=b.x-7||x>=b.x+b.w+7||
                           y+h<=b.y-7||y>=b.y+b.h+7))return {x,y};
    }
  }
  return null;
}
function relink(spec){
  const rects=new Map(spec.elements.filter(e=>e.type==="rect"&&e.group).map(e=>[e.group,e]));
  for(const e of spec.elements){
    if(e.type!=="line"||!e.from_group||!e.to_group)continue;
    const a=rects.get(e.from_group),b=rects.get(e.to_group);if(!a||!b)continue;
    const ax=a.x+a.w/2,bx=b.x+b.w/2,ay=a.y+a.h/2,by=b.y+b.h/2;
    if(Math.abs(bx-ax)>=Math.abs(by-ay)){
      e.x1=ax<bx?a.x+a.w:a.x;e.x2=ax<bx?b.x:b.x+b.w;e.y1=ay;e.y2=by;
    }else{e.x1=ax;e.x2=bx;e.y1=ay<by?a.y+a.h:a.y;e.y2=ay<by?b.y:b.y+b.h;}
  }
}

export async function mountVisualStudio({api,page,toast,esc,icon}){
  const html='<div class="vs-studio">'+
    '<div class="vs-toolbar"><input class="input vs-name" id="vsName" value="My visual design" maxlength="100" aria-label="Design name">'+
    '<label>Template <select class="input" id="vsTemplate"><option value="workflow">Workflow</option><option value="cards">Feature cards</option><option value="poster">Poster</option><option value="blank">Blank canvas</option></select></label>'+
    '<label>Theme <select class="input" id="vsTheme"><option value="illustrated-workflow">Illustrated</option><option value="editorial-light">Editorial light</option><option value="premium-tech">Premium tech</option><option value="commercial">Commercial</option></select></label>'+
    '<button class="btn" id="vsUndo">Undo</button><button class="btn" id="vsRedo">Redo</button>'+
    '<button class="btn" id="vsInspect">'+icon("check")+' Inspect & repair</button>'+
    '<button class="btn" id="vsAIReview" title="Explicitly review with a downloaded local Ollama vision model; no cloud fallback">'+icon("sparkle")+' Local AI design review</button>'+
    '<button class="btn primary" id="vsSave">Save draft</button></div>'+
    '<div class="vs-toolbar"><button class="btn" id="vsAddText">'+icon("edit")+' Text</button>'+
    '<button class="btn" id="vsAddShape">'+icon("plus")+' Shape</button>'+
    '<button class="btn" id="vsAddIcon">'+icon("sparkle")+' Icon</button>'+
    '<select class="input vs-asset" id="vsAssets" aria-label="Uploaded original image"><option value="">Choose uploaded image</option></select>'+
    '<button class="btn" id="vsAddImage">'+icon("image")+' Place image</button>'+
    '<a class="btn" href="#/files">'+icon("folder")+' Files</a>'+
    '<span class="spacer"></span><select class="input vs-asset" id="vsDraft" aria-label="Saved designs"><option value="">Saved designs…</option></select>'+
    '<button class="btn" id="vsLoad">Open</button></div>'+
    '<div class="vs-toolbar"><input id="vsTitle" class="input" aria-label="Design title" maxlength="130" placeholder="Title" style="flex:1;min-width:160px">'+
    '<input id="vsSubtitle" class="input" aria-label="Design subtitle" maxlength="250" placeholder="Subtitle" style="flex:1;min-width:160px"></div>'+
    '<section class="vs-pages" aria-label="Document pages">'+
    '<div class="vs-pages-head"><strong>Document pages</strong><span id="vsPageCount" class="vs-small" role="status"></span></div>'+
    '<div id="vsPageTabs" class="vs-page-tabs" role="navigation" aria-label="Choose document page"></div>'+
    '<div class="vs-toolbar vs-page-controls">'+
    '<label>Page name <input class="input" id="vsPageName" maxlength="80" aria-label="Current page name"></label>'+
    '<button type="button" class="btn" id="vsPageAdd">New page</button>'+
    '<button type="button" class="btn" id="vsPageDuplicate">Duplicate page</button>'+
    '<button type="button" class="btn" id="vsPageUp">Move earlier</button>'+
    '<button type="button" class="btn" id="vsPageDown">Move later</button>'+
    '<button type="button" class="btn danger" id="vsPageDelete">Remove page</button></div></section>'+
    '<div class="vs-shell"><section class="vs-workspace"><div class="vs-stage" id="vsStage" aria-busy="true">'+
    '<img id="vsPreview" class="vs-preview" alt="Actual rendered design preview" draggable="false">'+
    '<svg class="vs-over" id="vsOverlay" aria-label="Drag an object to reposition it"></svg></div>'+
    '<div class="vs-summary"><span>Select an object or drag it. Preview updates after edits.</span><span id="vsCount"></span></div>'+
    '<p id="vsStatus" class="vs-status" role="status">Preparing preview…</p>'+
    '<div id="vsRepairReview" class="vs-repair-review" hidden role="region" aria-label="Proposed layout changes">'+
    '<h3 id="vsReviewHeading">Review proposed changes</h3><p id="vsRepairSummary" class="vs-inspector-note"></p>'+
    '<div class="vs-repair-compare">'+
    '<figure><figcaption>Before · original</figcaption><img id="vsRepairOriginal" class="vs-repair-image" alt="Original design before repairs" hidden></figure>'+
    '<figure><figcaption>After · selected changes</figcaption><img id="vsRepairImage" class="vs-repair-image" alt="Proposed design with selected repairs" hidden></figure></div>'+
    '<div class="vs-toolbar vs-repair-controls"><span id="vsRepairSelectionCount" class="vs-small" role="status"></span>'+
    '<button type="button" class="btn" id="vsRepairAll">Select all</button>'+
    '<button type="button" class="btn" id="vsRepairNone">Clear selection</button></div>'+
    '<ul id="vsRepairList" class="vs-repair-list"></ul>'+
    '<p id="vsRepairRemaining" class="vs-inspector-note" role="status"></p>'+
    '<h4 class="vs-repair-note-head">Design review notes (advisory)</h4><ul id="vsRepairNotes" class="vs-repair-list"></ul>'+
    '<div class="vs-toolbar"><button id="vsApplyRepair" class="btn primary">Apply selected repair</button>'+
    '<button id="vsDismissRepair" class="btn">Keep original</button></div></div></section>'+
    '<aside class="vs-inspector"><h3>Object inspector</h3>'+
    '<label for="vsElement" class="vs-inspector-note">Choose an element to edit</label>'+
    '<select class="input" id="vsElement" style="width:100%;margin:9px 0"></select>'+
    '<div id="vsProperties" class="vs-fields"></div>'+
    '<h3 class="vs-layer-heading">Layers <span class="vs-small">Front → back</span></h3>'+
    '<div id="vsLayers" class="vs-layers" aria-label="Visual design layers"></div>'+
    '<div class="vs-toolbar vs-multi-controls"><button class="btn" id="vsSelectAll">Select unlocked</button>'+
    '<button class="btn" id="vsClearSelection">Clear selection</button>'+
    '<span id="vsSelectedCount" class="vs-small" role="status"></span></div>'+
    '<div class="vs-toolbar vs-multi-controls">'+
    '<label>Align <select class="input" id="vsAlignMode" aria-label="Align selected layers">'+
    '<option value="left">Left</option><option value="center">Centre</option><option value="right">Right</option>'+
    '<option value="top">Top</option><option value="middle">Middle</option><option value="bottom">Bottom</option></select></label>'+
    '<button class="btn" id="vsAlign">Align</button>'+
    '<label>Distribute <select class="input" id="vsDistributeMode" aria-label="Distribute selected layers">'+
    '<option value="horizontal">Horizontally</option><option value="vertical">Vertically</option></select></label>'+
    '<button class="btn" id="vsDistribute">Distribute</button></div>'+
    '<div class="vs-toolbar vs-multi-controls"><button class="btn" id="vsGroup">Group</button>'+
    '<button class="btn" id="vsUngroup">Ungroup</button>'+
    '<label class="vs-snap-toggle"><input type="checkbox" id="vsSnap" checked> Snap on drag</label></div>'+
    '<div class="vs-toolbar" style="margin-top:12px"><button class="btn" id="vsDuplicate">Duplicate</button>'+
    '<button class="btn danger" id="vsDelete">Delete</button></div>'+
    '<p class="vs-inspector-note">Grouped components move together. Exact text stays editable. Original uploaded imagery is not AI-redrawn.</p></aside></div>'+
    '<section class="vs-export"><label>Output <select id="vsOutputMode" aria-label="Image delivery type">'+
    '<option value="flat">Single finished file</option><option value="layered">Editable layers + file</option></select></label>'+
    '<label>Format <select id="vsFormat"><option value="png">PNG image</option><option value="svg">Editable SVG</option>'+
    '<option value="pptx">Editable PowerPoint</option><option value="pdf">PDF</option><option value="jpg">JPEG</option><option value="gif">Animated GIF</option></select></label>'+
    '<label class="vs-gif-settings" hidden>Motion <select id="vsEffect"><option value="flow">Flow</option><option value="pulse">Pulse</option>'+
    '<option value="reveal">Reveal</option><option value="float">Float</option><option value="sequence">Layer timeline</option></select></label>'+
    '<label class="vs-gif-settings" hidden>Frames <input id="vsFrames" type="number" min="8" max="48" value="20"></label>'+
    '<label class="vs-gif-settings" hidden>Milliseconds/frame <input id="vsDelay" type="number" min="50" max="500" value="110"></label>'+
    '<label class="vs-gif-settings" hidden>Loop <select id="vsLoop"><option value="0">Forever</option><option value="1">Once</option><option value="3">3 times</option></select></label>'+
    '<p id="vsPageExportHint" class="vs-page-export-hint" role="status">Exporting current page.</p>'+
    '<span class="spacer"></span><button class="btn primary" id="vsExport">'+icon("download")+' Export</button>'+
    '<div id="vsOutput" class="vs-output" hidden></div></section>'+
    '<section class="vs-timeline" id="vsTimeline" hidden aria-label="Animated layer timeline">'+
    '<div class="vs-time-head"><strong>GIF scene timeline</strong>'+
    '<span>Set when each group appears; export keeps the exact timing.</span></div>'+
    '<div id="vsTracks" class="vs-tracks"></div>'+
    '<label class="vs-scrub">Preview at <output id="vsFrameLabel">0%</output>'+
    '<input id="vsPlayhead" type="range" min="0" max="99" step="1" value="0" aria-label="Preview timeline position"></label>'+
    '</section></div>';
  const root=page("Visual Studio",
       "Edit a premium visual composition, keep source photographs intact, and export a genuine animated GIF or an editable PowerPoint.",html);
  root.classList.add("vs-page");
  const at=id=>Q("#"+id,root),overlay=at("vsOverlay"),stage=at("vsStage");
  let spec=template("workflow","illustrated-workflow"),name="My visual design",selected=-1,undoStack=[],redoStack=[],dirty=false;
  let selectionKeys=new Set();
  let pages=[{name:"Page 1",spec}],activePage=0;
  let pendingRepair=null,repairRequest=0,inspectionRequest=0;
  let previewSequence=0,previewTimer=null,drag=null;
  const status=(message,bad=false)=>{at("vsStatus").textContent=message;at("vsStatus").classList.toggle("bad",bad);};
  const snap=()=>copy(spec);
  function storePage(){
    if(!pages[activePage])return;
    pages[activePage].spec=spec;
    pages[activePage]._undo=undoStack;
    pages[activePage]._redo=redoStack;
  }
  function documentPages(){
    storePage();
    return pages.map(p=>({name:p.name,spec:copy(p.spec)}));
  }
  function pageBars(){
    storePage();
    at("vsPageCount").textContent=(activePage+1)+" / "+pages.length+" · max 20";
    at("vsPageTabs").innerHTML=pages.map((p,i)=>
      '<button type="button" class="vs-page-tab" data-page-index="'+i+'"'+
      ' aria-current="'+(i===activePage?"page":"false")+'" title="'+esc(p.name)+'">'+
      '<span>'+(i+1)+'</span> '+esc(p.name)+'</button>').join("");
    at("vsPageName").value=pages[activePage].name;
    at("vsPageAdd").disabled=pages.length>=20;
    at("vsPageDuplicate").disabled=pages.length>=20;
    at("vsPageDelete").disabled=pages.length===1;
    at("vsPageUp").disabled=activePage===0;
    at("vsPageDown").disabled=activePage===pages.length-1;
    at("vsPageExportHint").textContent=pages.length>1
      ? (["pdf","pptx"].includes(at("vsFormat").value)
        ? "All "+pages.length+" pages in order; PowerPoint keeps editable text and shapes."
        : "Only page "+(activePage+1)+" exported as "+at("vsFormat").value.toUpperCase()+
          "; choose PDF or PowerPoint to export every page.")
      : "Exporting this single page.";
  }
  function openPage(index){
    if(!Number.isInteger(index)||index<0||index>=pages.length)return;
    storePage();
    if(index!==activePage){
      activePage=index;
      spec=pages[index].spec;
      undoStack=pages[index]._undo||[];
      redoStack=pages[index]._redo||[];
      selected=-1;selectionKeys.clear();
      closeRepair();
    }
    at("vsEffect").value=spec.animation?.effect||"flow";
    draw();schedule(0);
  }
  function setDocument(data){
    const incoming=data.pages||[{name:"Page 1",spec:data.spec}];
    pages=incoming.map(p=>({name:p.name,spec:p.spec}));
    activePage=0;spec=pages[0].spec;selected=-1;selectionKeys.clear();
    undoStack=[];redoStack=[];dirty=false;
    at("vsEffect").value=spec.animation?.effect||"flow";
  }
  function closeRepair(){
    ++repairRequest;
    ++inspectionRequest;
    pendingRepair=null;
    at("vsRepairReview").hidden=true;
  }
  function record(previous){
    if(JSON.stringify(previous)===JSON.stringify(spec))return;
    closeRepair();
    undoStack.push(previous);
    if(undoStack.length>40)undoStack.shift();
    redoStack=[];dirty=true;buttons();schedule();
  }
  function change(fn){
    const before=snap(),result=fn();
    if(spec.animation?.effect==="sequence"){
      const next=normaliseSequence(spec);
      if(next)spec.animation=next;
      else delete spec.animation;
    }
    record(before);draw();return result;
  }
  function buttons(){at("vsUndo").disabled=!undoStack.length;at("vsRedo").disabled=!redoStack.length;}
  function undo(){
    if(!undoStack.length)return;
    redoStack.push(snap());spec=undoStack.pop();selected=-1;selectionKeys.clear();
    at("vsEffect").value=spec.animation?.effect||"flow";
    draw();schedule();
  }
  function redo(){
    if(!redoStack.length)return;
    undoStack.push(snap());spec=redoStack.pop();selected=-1;selectionKeys.clear();
    at("vsEffect").value=spec.animation?.effect||"flow";
    draw();schedule();
  }
  function selectedUnits(){return selectedLayerUnits(spec,selectionKeys);}
  function choose(index,extend=false){
    const unit=layerUnits(spec).find(u=>u.indices.includes(index));
    if(!extend)selectionKeys.clear();
    if(unit){
      if(extend && selectionKeys.has(unit.key))selectionKeys.delete(unit.key);
      else selectionKeys.add(unit.key);
    }
    const units=selectedUnits();
    selected=units.length?(unit&&selectionKeys.has(unit.key)?index:units[0].indices[0]):-1;
    draw();
  }
  function currentUnit(index=selected){
    return layerUnits(spec).find(u=>u.indices.includes(index));
  }
  function isLocked(index=selected){return !!currentUnit(index)?.locked;}
  function drawLayers(){
    const layers=layerUnits(spec).slice().reverse();
    at("vsLayers").innerHTML=layers.map((u,order)=>{
      const active=selectionKeys.has(u.key),iconName=u.isConnector?"link":u.key.startsWith("group:")?"folder":"file";
      const label=u.label+" ("+u.indices.length+")";
      const common=' data-layer-key="'+esc(u.key)+'"';
      return '<div class="vs-layer'+(active?' active':'')+(u.hidden?' hidden-layer':'')+'">'+
        '<button class="vs-layer-name" data-layer-act="select"'+common+
        ' aria-pressed="'+String(active)+'" title="'+esc(label)+' · Shift/Ctrl-click to select multiple">'+
        icon(iconName)+' '+esc(label)+'</button>'+
        '<button class="vs-layer-btn" data-layer-act="visibility"'+common+
        ' aria-label="'+(u.hidden?'Show ':'Hide ')+esc(u.label)+'" aria-pressed="'+String(u.hidden)+'">'+
        icon(u.hidden?'eye':'eye')+'</button>'+
        '<button class="vs-layer-btn" data-layer-act="lock"'+common+
        ' aria-label="'+(u.locked?'Unlock ':'Lock ')+esc(u.label)+'" aria-pressed="'+String(u.locked)+'">'+
        icon("lock")+'</button>'+
        '<button class="vs-layer-btn" data-layer-act="front"'+common+
        ' aria-label="Move '+esc(u.label)+' forward" '+(order===0||u.isConnector||u.locked?'disabled':'')+'>'+icon("up")+'</button>'+
        '<button class="vs-layer-btn" data-layer-act="back"'+common+
        ' aria-label="Move '+esc(u.label)+' backwards" '+(order===layers.length-1||u.isConnector||u.locked?'disabled':'')+'>'+icon("down")+'</button></div>';
    }).join("")||'<p class="vs-inspector-note">No objects yet. Add text, shapes or images.</p>';
  }
  function drawTimeline(){
    const enabled=at("vsFormat").value==="gif" && at("vsEffect").value==="sequence";
    at("vsTimeline").hidden=!enabled;
    if(!enabled)return;
    const config=normaliseSequence(spec);
    if(!config){
      at("vsTracks").innerHTML='<p class="vs-inspector-note">Add a grouped workflow or feature cards to use this animation timeline.</p>';
      return;
    }
    at("vsTracks").innerHTML=config.stages.map(({group,start},index)=>
       '<label class="vs-track"><span class="vs-track-name">'+esc(group)+'</span>'+
       '<input type="range" data-track="'+index+'" min="0" max="90" step="5" value="'+Math.round(start*100)+'" aria-label="Reveal '+esc(group)+' at percent">'+
       '<output>'+Math.round(start*100)+'%</output></label>'
    ).join("");
  }
  function highlight(){
    overlay.replaceChildren();
    spec.elements.forEach((e,i)=>{
      if(e.hidden)return;
      const hit=document.createElementNS(NS,e.type==="line"?"line":"rect");
      hit.setAttribute("data-i",String(i));hit.setAttribute("class","vs-target");
      if(e.type==="line"){
        ["x1","y1","x2","y2"].forEach(k=>hit.setAttribute(k,String(e[k])));
        hit.setAttribute("stroke","transparent");hit.setAttribute("stroke-width","24");
      }else{
        hit.setAttribute("x",String(e.x));hit.setAttribute("y",String(e.y));
        hit.setAttribute("width",String(e.w));hit.setAttribute("height",String(e.h));
      }
      overlay.appendChild(hit);
    });
    const units=selectedUnits();
    if(!units.length)return;
    for(const unit of units){
      const area=selectionBox(spec,unit.indices[0]);
      if(!area)continue;
      const mark=document.createElementNS(NS,"rect");
      mark.setAttribute("class","vs-selected");
      mark.setAttribute("x",String(Math.max(0,area.x-5)));
      mark.setAttribute("y",String(Math.max(0,area.y-5)));
      mark.setAttribute("width",String(Math.min(spec.width-area.x+5,area.w+10)));
      mark.setAttribute("height",String(Math.min(spec.height-area.y+5,area.h+10)));
      overlay.appendChild(mark);
    }
    if(units.length!==1||selected<0||!spec.elements[selected]||isLocked()||
       spec.elements[selected].type==="line")return;
    const area=selectionBox(spec,selected);
    if(!area)return;
    const grip=document.createElementNS(NS,"rect");
    grip.setAttribute("data-i",String(selected));
    grip.setAttribute("data-resize","se");
    grip.setAttribute("class","vs-resize-handle");
    grip.setAttribute("x",String(clamp(area.x+area.w-8,0,spec.width-20)));
    grip.setAttribute("y",String(clamp(area.y+area.h-8,0,spec.height-20)));
    grip.setAttribute("width","20");grip.setAttribute("height","20");
    grip.setAttribute("aria-label","Drag to resize selected design element");
    overlay.appendChild(grip);
  }
  function inspector(){
    const pick=at("vsElement");
    pick.innerHTML='<option value="">Select an object</option>'+
      spec.elements.map((e,i)=>'<option value="'+i+'"'+(i===selected?' selected':'')+'>'+
        (i+1)+' · '+esc(e.type)+' '+(e.type==="text"?esc(e.text.slice(0,20)):esc(e.group||""))+'</option>').join("");
    const area=at("vsProperties");
    if(selectedUnits().length>1){
      area.innerHTML='<p class="vs-inspector-note full">Multiple layers selected. Use Align, Distribute, Group or drag to move them. Choose one layer to edit individual properties.</p>';
      return;
    }
    if(selected<0||!spec.elements[selected]){
      area.innerHTML='<p class="vs-inspector-note full">Choose an element from the canvas or this list.</p>';return;
    }
    const e=spec.elements[selected];
    let html="";
    const field=(key,label,value,type="number",full=false)=>{
      html+='<label'+(full?' class="full"':'')+'>'+esc(label)+'<input data-key="'+key+'" type="'+type+
        '" '+(type==="number"?'step="1" ':'')+'value="'+esc(value??"")+'"></label>';
    };
    if(e.type==="line"){
      for(const key of ["x1","y1","x2","y2"])field(key,key.toUpperCase(),e[key]);
      field("colour","Line colour",e.colour,"color");
    }else{
      for(const key of ["x","y","w","h"])field(key,key.toUpperCase(),e[key]);
      if(e.type==="text"){
        html+='<label class="full">Exact wording<textarea data-key="text" maxlength="1600">'+esc(e.text)+'</textarea></label>';
        field("font_size","Font size",e.font_size||22);
        field("colour","Text colour",e.colour||"#22252C","color");
      }else if(e.type==="rect"){
        field("fill","Fill",e.fill||"#FFFFFF","color");
        field("stroke","Outline",e.stroke||"#25252D","color");
        field("radius","Corners",e.radius||15);
      }else if(e.type==="icon"){
        html+='<label class="full">Icon<select data-key="name">'+ICONS.map(n=>
          '<option value="'+n+'"'+(n===e.name?' selected':'')+'>'+n+'</option>').join("")+'</select></label>';
        field("colour","Colour",e.colour||"#22252C","color");
      }else if(e.type==="image"){
        field("path","Workspace source path",e.path,"text",true);
        field("alt","Alternative text",e.alt||"Original photograph","text",true);
      }
    }
    area.innerHTML=html;
    const readonly=isLocked();
    QA("[data-key]",area).forEach(input=>{
      input.disabled=readonly;
      let start;
      input.onfocus=()=>{start=snap();};
      input.oninput=()=>{
        const key=input.dataset.key;
        const numeric=input.type==="number";
        if(numeric && (!input.value || !Number.isFinite(Number(input.value))))return;
        const value=numeric?Number(input.value):input.value;
        if(["x","y","w","h","x1","y1","x2","y2"].includes(key)){
          e[key]=clamp(value,key==="w"||key==="h"?1:0,key.startsWith("y")||key==="h"?spec.height:spec.width);
        }else if(key==="font_size"){e[key]=clamp(value,12,90);}
        else if(key==="radius"){e[key]=clamp(value,0,100);}
        else{
          e[key]=value;
          if(key==="fill")delete e.auto_fill;
          if(key==="stroke")delete e.auto_stroke;
          if(key==="colour")delete e.auto_colour;
        }
        relink(spec);highlight();schedule();
      };
      input.onchange=()=>{record(start||snap());draw();};
    });
  }
  function draw(){
    const available=new Set(layerUnits(spec).map(u=>u.key));
    selectionKeys=new Set([...selectionKeys].filter(k=>available.has(k)));
    if(!selectionKeys.size && selected>=0 && spec.elements[selected]){
      selectionKeys.add(unitKey(spec.elements[selected],selected));
    }
    if(selectionKeys.size && !selectedUnits().some(u=>u.indices.includes(selected))){
      selected=selectedUnits()[0].indices[0];
    }
    stage.style.aspectRatio=spec.width+"/"+spec.height;
    overlay.setAttribute("viewBox","0 0 "+spec.width+" "+spec.height);
    at("vsTitle").value=spec.title||"";
    at("vsSubtitle").value=spec.subtitle||"";
    at("vsTheme").value=spec.theme;
    at("vsCount").textContent=spec.elements.length+" editable elements";
    const units=selectedUnits(),allowed=units.every(u=>!u.locked&&!u.hidden&&!u.isConnector);
    at("vsSelectedCount").textContent=units.length+" layer"+(units.length===1?"":"s")+" selected";
    at("vsAlign").disabled=units.length<2||!allowed;
    at("vsDistribute").disabled=units.length<3||!allowed;
    at("vsGroup").disabled=units.length<2||!allowed||units.some(u=>u.key.startsWith("group:"));
    at("vsUngroup").disabled=units.length!==1||!allowed||!units[0].key.startsWith("group:");
    at("vsClearSelection").disabled=!units.length;
    at("vsDelete").disabled=units.length!==1||selected<0||isLocked();
    at("vsDuplicate").disabled=units.length!==1||selected<0||isLocked();
    at("vsElement").disabled=false;
    inspector();drawLayers();highlight();buttons();drawTimeline();pageBars();
  }
  function schedule(ms=450){
    // A pending proposal belongs to an exact snapshot. Any editor change,
    // including text entry before blur, invalidates its approval boundary.
    if(pendingRepair)closeRepair();
    const current=++previewSequence;
    if(previewTimer)clearTimeout(previewTimer);
    // Mark a previously rendered frame as stale immediately: users must not
    // mistake it for the artwork they are saving or exporting now.
    stage.setAttribute("aria-busy","true");
    status("Updating design preview…");
    previewTimer=setTimeout(async()=>{
      if(!root.isConnected||current!==previewSequence)return;
      stage.setAttribute("aria-busy","true");
      try{
        const body={spec,name};
        if(at("vsFormat").value==="gif" && at("vsEffect").value==="sequence" && spec.animation?.effect==="sequence"){
          body.animation=spec.animation;
          body.frame=Number(at("vsPlayhead").value)/100;
        }
        const d=await api("/api/visual/studio/preview",body);
        if(!root.isConnected||current!==previewSequence)return;
        at("vsPreview").src=d.image;
        status("Structural checks passed"+(d.adjustments.length?" · "+d.adjustments.length+" text adjustments":"")+". Review the actual appearance.");
      }catch(e){if(root.isConnected&&current===previewSequence)status("Preview problem: "+e.message,true);}
      finally{if(root.isConnected&&current===previewSequence)stage.setAttribute("aria-busy","false");}
    },ms);
  }
  function add(type){
    if(spec.elements.length>=40){toast("This canvas has 40 elements. Remove or combine objects before adding more.","bad");return;}
    if(type==="image"&&!at("vsAssets").value){toast("Upload a picture under Files and choose it first.","bad");return;}
    const dimensions={text:[400,70],rect:[250,150],icon:[85,85],image:[340,220]}[type];
    const place=freePosition(spec,...dimensions);
    if(!place){toast("No empty space for this object. Move or remove an existing object, or start a Blank canvas.","bad");return;}
    change(()=>{
      const {x,y}=place,p=PALETTES[spec.theme];
      let e;
      if(type==="text")e={type,x,y,w:400,h:70,text:"Your headline",font_size:34,colour:p.ink,auto_colour:"ink",bold:true};
      if(type==="rect")e={type,x,y,w:250,h:150,fill:p.tones[0],stroke:p.border,radius:18,auto_fill:"tone0",auto_stroke:"border"};
      if(type==="icon")e={type,x,y,w:85,h:85,name:"sparkle",colour:p.ink,auto_colour:"ink"};
      if(type==="image")e={type,x,y,w:340,h:220,path:at("vsAssets").value,alt:"Original source image"};
      spec.elements.push(e);selected=spec.elements.length-1;
      selectionKeys=new Set([unitKey(spec.elements[selected],selected)]);
    });
  }
  async function loadAssets(){
    try{
      const data=await api("/api/files?dir=uploads");
      const imgs=data.items.filter(e=>!e.dir&&/\.(png|jpg|jpeg|webp|bmp)$/i.test(e.name));
      at("vsAssets").innerHTML='<option value="">Choose uploaded image</option>'+imgs.map(e=>
        '<option value="'+esc(e.path)+'">'+esc(e.name)+'</option>').join("");
    }catch{ /* Uploads folder may not exist yet. */ }
  }
  async function loadDrafts(){
    try{
      const data=await api("/api/visual/studio/list");
      at("vsDraft").innerHTML='<option value="">Saved designs…</option>'+data.designs.map(d=>
        '<option value="'+esc(d.path)+'">'+esc(d.name)+'</option>').join("");
    }catch(e){status("Cannot list drafts: "+e.message,true);}
  }
  at("vsTemplate").onchange=e=>{
    if(dirty&&!window.confirm("Replace this design? Save your draft first if you want to keep it."))return;
    spec=template(e.target.value,spec.theme);selected=-1;selectionKeys.clear();
    dirty=true;undoStack=[];redoStack=[];
    storePage();
    draw();schedule(0);
  };
  at("vsTheme").onchange=e=>change(()=>themeElements(spec,e.target.value));
  at("vsUndo").onclick=undo;at("vsRedo").onclick=redo;
  // Reconstruct a subset from the immutable original, never from a previous
  // proposal. The server's normal preview endpoint is the final quality gate.
  function selectedRepairSpec(review){
    const candidate=copy(review.original);
    const allowed=new Set(["x","y","font_size","colour"]);
    for(const index of review.selected){
      const change=review.proposal.changes[index];
      if(!change || !allowed.has(change.field) ||
         !Number.isInteger(change.index) || change.index<0 ||
         change.index>=candidate.elements.length){
        throw new Error("Invalid repair proposal. Re-inspect the design.");
      }
      const element=candidate.elements[change.index];
      if(JSON.stringify(element[change.field])!==JSON.stringify(change.old)){
        throw new Error("The design changed since inspection. Re-inspect before applying.");
      }
      element[change.field]=change.new;
      if(change.field==="colour")delete element.auto_colour;
    }
    return candidate;
  }
  async function reviewSelection(review){
    const request=++repairRequest;
    const count=review.selected.size,maximum=review.proposal.changes.length;
    at("vsRepairSelectionCount").textContent=count+" of "+maximum+" field changes selected";
    at("vsApplyRepair").disabled=true;
    review.candidate=null;
    const picture=at("vsRepairImage");
    picture.hidden=true;
    picture.removeAttribute("src");
    if(!count){
      at("vsRepairRemaining").textContent="Choose at least one proposed change to preview it.";
      return;
    }
    try{
      const candidate=selectedRepairSpec(review);
      at("vsRepairRemaining").textContent="Checking selected changes against the actual renderer…";
      const preview=await api("/api/visual/studio/preview",{spec:candidate,name});
      if(!root.isConnected||pendingRepair!==review||request!==repairRequest)return;
      picture.src=preview.image;
      picture.hidden=false;
      review.candidate=candidate;
      at("vsApplyRepair").disabled=false;
      at("vsRepairRemaining").textContent=
        "Selected changes pass structural checks. Compare both images before applying; visual review is still required.";
    }catch(error){
      if(!root.isConnected||pendingRepair!==review||request!==repairRequest)return;
      at("vsRepairRemaining").textContent="Cannot apply this selection: "+error.message+
        ". Select other fixes or resolve the remaining issues manually.";
    }
  }
  async function presentReview(proposal,original,kind){
    const review={original,proposal,selected:new Set((proposal.changes||[]).map((_,i)=>i)),candidate:null};
    pendingRepair=review;
    const panel=at("vsRepairReview");
    panel.hidden=false;
    at("vsReviewHeading").textContent=kind==="ai"?"Local AI design review":"Review proposed changes";
    at("vsRepairSummary").textContent=proposal.summary+
      (kind==="ai"?" Model: "+proposal.model+". Suggestions are not automatically accepted.":"");
    const before=at("vsRepairOriginal");
    before.hidden=!proposal.original_preview;
    if(proposal.original_preview)before.src=proposal.original_preview;
    else before.removeAttribute("src");
    at("vsRepairList").innerHTML=(proposal.changes||[]).map((f,i)=>
      '<li><label class="vs-repair-choice"><input type="checkbox" data-repair-index="'+i+
      '" checked aria-label="Include layer '+(f.index+1)+' '+esc(f.field)+' repair"><span><b>'+
      esc(f.reason)+'</b> · Layer '+(f.index+1)+', '+esc(f.field)+
      ': '+esc(String(f.old))+' → '+esc(String(f.new))+'</span></label></li>').join("")||
      '<li>No editable change suggested. Review the design notes below.</li>';
    at("vsRepairNotes").innerHTML=(proposal.design_notes||[]).map(n=>
      '<li>'+(n.category?'<strong>'+esc(n.category)+'</strong> · ':'')+
      'Layer '+Number(n.layer)+': '+esc(n.message)+'</li>').join("")||
      '<li>No additional design-review observations.</li>';
    status(proposal.changed?"Inspect suggested changes before approval; original untouched.":
      "Review finished; no editable changes suggested. Original untouched.");
    panel.scrollIntoView({block:"nearest",behavior:"auto"});
    await reviewSelection(review);
  }
  at("vsInspect").onclick=async()=>{
    closeRepair();
    const button=at("vsInspect");button.disabled=true;
    const original=snap(),beforeSequence=previewSequence,inspection=++inspectionRequest;
    status("Inspecting layout without modifying your design…");
    try{
      const proposal=await api("/api/visual/studio/repair",{spec:original,name});
      if(!root.isConnected||beforeSequence!==previewSequence||inspection!==inspectionRequest)return;
      await presentReview(proposal,original,"repair");
    }catch(error){
      if(root.isConnected && inspection===inspectionRequest){
        closeRepair();status("Inspection failed: "+error.message,true);
      }
    }finally{if(root.isConnected)button.disabled=false;}
  };
  at("vsAIReview").onclick=async()=>{
    closeRepair();
    const button=at("vsAIReview");button.disabled=true;
    const original=snap(),beforeSequence=previewSequence,inspection=++inspectionRequest;
    // User-initiated opt in. The server only speaks to Ollama on loopback;
    // it does not send artwork to cloud providers or start a model download.
    status("Reviewing the actual canvas with your downloaded local vision model…");
    try{
      const proposal=await api("/api/visual/studio/ai-review",{spec:original,name});
      if(!root.isConnected||beforeSequence!==previewSequence||inspection!==inspectionRequest)return;
      await presentReview(proposal,original,"ai");
    }catch(error){
      if(root.isConnected && inspection===inspectionRequest){
        closeRepair();status("Local AI review unavailable: "+error.message,true);
      }
    }finally{if(root.isConnected)button.disabled=false;}
  };
  at("vsRepairList").onchange=e=>{
    const input=e.target.closest("[data-repair-index]");
    if(!input||!pendingRepair)return;
    const index=Number(input.dataset.repairIndex);
    if(!Number.isInteger(index)||index<0||index>=pendingRepair.proposal.changes.length)return;
    if(input.checked)pendingRepair.selected.add(index);
    else pendingRepair.selected.delete(index);
    void reviewSelection(pendingRepair);
  };
  at("vsRepairAll").onclick=()=>{
    if(!pendingRepair)return;
    pendingRepair.selected=new Set(pendingRepair.proposal.changes.map((_,i)=>i));
    QA("[data-repair-index]",at("vsRepairList")).forEach(input=>{input.checked=true;});
    void reviewSelection(pendingRepair);
  };
  at("vsRepairNone").onclick=()=>{
    if(!pendingRepair)return;
    pendingRepair.selected.clear();
    QA("[data-repair-index]",at("vsRepairList")).forEach(input=>{input.checked=false;});
    void reviewSelection(pendingRepair);
  };
  at("vsDismissRepair").onclick=()=>{
    closeRepair();
    status("Original design retained; no layout changes applied.");
  };
  at("vsApplyRepair").onclick=()=>{
    const review=pendingRepair;
    if(!review?.candidate||at("vsApplyRepair").disabled)return;
    const before=snap();
    // No editor state may change after inspection; schedule() closes the review
    // if anything is modified in the meantime.
    if(JSON.stringify(before)!==JSON.stringify(review.original)){
      closeRepair();
      status("Design changed since inspection; review again before applying.",true);
      return;
    }
    spec=copy(review.candidate);
    selected=-1;selectionKeys.clear();
    closeRepair();
    record(before);draw();schedule(0);
    toast("Approved selected repairs applied. Undo is available.");
  };
  at("vsAddText").onclick=()=>add("text");at("vsAddShape").onclick=()=>add("rect");
  at("vsAddIcon").onclick=()=>add("icon");at("vsAddImage").onclick=()=>add("image");
  at("vsElement").onchange=e=>choose(e.target.value===""?-1:Number(e.target.value));
  at("vsLayers").onclick=e=>{
    const button=e.target.closest("[data-layer-act]");if(!button)return;
    const key=button.dataset.layerKey,act=button.dataset.layerAct;
    const unit=layerUnits(spec).find(u=>u.key===key);if(!unit)return;
    if(act==="select"){choose(unit.indices[0],e.shiftKey||e.ctrlKey||e.metaKey);return;}
    if(act==="visibility"||act==="lock"){
      const flag=act==="visibility"?"hidden":"locked";
      change(()=>toggleLayer(spec,key,flag,flag==="hidden"?!unit.hidden:!unit.locked));
      return;
    }
    if(act==="front"||act==="back"){
      if(unit.locked)return;
      const item=spec.elements[unit.indices[0]],direction=act==="front"?1:-1;
      change(()=>{
        if(moveLayer(spec,key,direction)){
          selected=spec.elements.indexOf(item);
          selectionKeys=new Set([unitKey(spec.elements[selected],selected)]);
        }
      });
    }
  };
  // Batch controls use whole layer units, never half a card or a locked asset.
  at("vsSelectAll").onclick=()=>{
    const units=layerUnits(spec).filter(u=>!u.hidden&&!u.locked&&!u.isConnector);
    selectionKeys=new Set(units.map(u=>u.key));
    selected=units.length?units[0].indices[0]:-1;draw();
  };
  at("vsClearSelection").onclick=()=>choose(-1);
  at("vsAlign").onclick=()=>{
    const result=change(()=>{
      const ok=alignLayerUnits(spec,[...selectionKeys],at("vsAlignMode").value);
      if(ok)relink(spec);return ok;
    });
    if(!result)toast("Alignment could not be applied without moving a layer outside the canvas.","bad");
  };
  at("vsDistribute").onclick=()=>{
    const result=change(()=>{
      const ok=distributeLayerUnits(spec,[...selectionKeys],at("vsDistributeMode").value);
      if(ok)relink(spec);return ok;
    });
    if(!result)toast("Cannot distribute these layers without overlap or invalid geometry.","bad");
  };
  at("vsGroup").onclick=()=>{
    const group=change(()=>{
      const value=groupLayerUnits(spec,[...selectionKeys]);
      if(value){
        selectionKeys=new Set(["group:"+value]);
        selected=spec.elements.findIndex(e=>e.group===value);
      }
      return value;
    });
    if(!group)toast("Select two or more separate unlocked layers to group. Existing groups cannot be nested.","bad");
  };
  at("vsUngroup").onclick=()=>{
    const units=selectedUnits(),indices=units.length===1?[...units[0].indices]:[];
    const ok=change(()=>{
      const applied=ungroupLayerUnits(spec,[...selectionKeys]);
      if(applied){
        selectionKeys=new Set(indices.map(i=>unitKey(spec.elements[i],i)));
        selected=indices[0]??-1;
      }
      return applied;
    });
    if(!ok)toast("This group cannot be split while it is locked or referenced by a connector.","bad");
  };
  let trackPrevious=null;
  at("vsTracks").addEventListener("pointerdown",()=>{trackPrevious=snap();});
  at("vsTracks").addEventListener("focusin",()=>{trackPrevious=snap();});
  at("vsTracks").oninput=e=>{
    const input=e.target.closest("[data-track]");
    if(!input||spec.animation?.effect!=="sequence")return;
    const i=Number(input.dataset.track);if(!spec.animation.stages[i])return;
    spec.animation.stages[i].start=Number(input.value)/100;
    Q("output",input.parentElement).textContent=input.value+"%";
    schedule(300);
  };
  at("vsTracks").onchange=e=>{
    if(!e.target.matches("[data-track]"))return;
    record(trackPrevious||snap());trackPrevious=null;
  };
  at("vsPlayhead").oninput=e=>{
    at("vsFrameLabel").textContent=e.target.value+"%";
    schedule(300);
  };
  const gifOptions=()=>{
    const effect=at("vsEffect").value;
    const options={
      effect,frames:Number(at("vsFrames").value),
      duration_ms:Number(at("vsDelay").value),
      loop:Number(at("vsLoop").value)
    };
    if(effect==="sequence"){
      const tracks=normaliseSequence(spec);
      if(!tracks)return null;
      options.stages=tracks.stages;
    }
    return options;
  };
  function updateGifSpec(){
    if(at("vsFormat").value!=="gif")return;
    const next=gifOptions();
    if(!next){status("A layer timeline needs at least one visible grouped component.",true);return;}
    const before=snap();
    spec.animation=next;
    record(before);draw();
  }
  at("vsEffect").onchange=updateGifSpec;
  for(const id of ["vsFrames","vsDelay","vsLoop"])at(id).onchange=updateGifSpec;
  at("vsDelete").onclick=()=>{
    if(selected<0||isLocked()||selectedUnits().length!==1)return;
    change(()=>{
      const chosen=spec.elements[selected],g=chosen.group;
      spec.elements=spec.elements.filter((e,i)=>g ? e.group!==g&&e.from_group!==g&&e.to_group!==g : i!==selected);
      selected=-1;selectionKeys.clear();relink(spec);
    });
  };
  at("vsDuplicate").onclick=()=>{
    if(selected<0||isLocked()||selectedUnits().length!==1)return;
    const unit=currentUnit();
    if(spec.elements.length+(unit?.indices.length||1)>40){
      toast("Duplicating this group would exceed the 40-object canvas limit.","bad");return;
    }
    change(()=>{
      const selectedElement=spec.elements[selected],g=selectedElement.group;
      const set=g?spec.elements.filter(e=>e.group===g):[selectedElement];
      const newGroup=g?g+"-copy-"+Date.now().toString(36):null;
      set.forEach(original=>{
        const e=copy(original);
        if(newGroup)e.group=newGroup;
        if(e.type==="line"){e.x1+=30;e.x2+=30;e.y1+=30;e.y2+=30;}
        else {e.x=clamp(e.x+30,0,spec.width-e.w);e.y=clamp(e.y+30,0,spec.height-e.h);}
        spec.elements.push(e);
      });
      selected=spec.elements.length-1;
      selectionKeys=new Set([unitKey(spec.elements[selected],selected)]);
    });
  };
  for(const key of ["title","subtitle"]){
    const input=at(key==="title"?"vsTitle":"vsSubtitle");let previous;
    input.onfocus=()=>{previous=snap();};
    input.oninput=()=>{spec[key]=input.value;schedule();};
    input.onchange=()=>{record(previous||snap());};
  }
  at("vsName").oninput=e=>{name=e.target.value;};
  // Document operations never merge two page histories or mutate source
  // assets. Each page remains the same native editable canvas specification.
  at("vsPageTabs").onclick=e=>{
    const target=e.target.closest("[data-page-index]");
    if(target)openPage(Number(target.dataset.pageIndex));
  };
  at("vsPageName").onchange=e=>{
    const value=e.target.value.trim().slice(0,80)||"Page "+(activePage+1);
    if(pages[activePage].name!==value){
      pages[activePage].name=value;dirty=true;
    }
    pageBars();
  };
  at("vsPageAdd").onclick=()=>{
    if(pages.length>=20){toast("Document limit: 20 pages.","bad");return;}
    storePage();
    const blank=template("blank",spec.theme);
    blank.width=spec.width;blank.height=spec.height;
    if(spec.artboard_only)blank.artboard_only=true;
    if(spec.colours)blank.colours=copy(spec.colours);
    pages.splice(activePage+1,0,{name:"Page "+(pages.length+1),spec:blank});
    activePage++;
    spec=blank;undoStack=[];redoStack=[];
    selected=-1;selectionKeys.clear();dirty=true;
    closeRepair();draw();schedule(0);
  };
  at("vsPageDuplicate").onclick=()=>{
    if(pages.length>=20){toast("Document limit: 20 pages.","bad");return;}
    storePage();
    const source=pages[activePage],duplicate=copy(source.spec);
    const title=("Copy of "+source.name).slice(0,80);
    pages.splice(activePage+1,0,{name:title,spec:duplicate});
    activePage++;spec=duplicate;undoStack=[];redoStack=[];
    selected=-1;selectionKeys.clear();dirty=true;
    closeRepair();draw();schedule(0);
  };
  for(const [id,dir] of [["vsPageUp",-1],["vsPageDown",1]]){
    at(id).onclick=()=>{
      const other=activePage+dir;
      if(other<0||other>=pages.length)return;
      storePage();
      [pages[activePage],pages[other]]=[pages[other],pages[activePage]];
      activePage=other;dirty=true;pageBars();
    };
  }
  at("vsPageDelete").onclick=()=>{
    if(pages.length<=1)return;
    if(!window.confirm("Remove this page from the document? Its contents will be lost unless you have saved a previous draft."))return;
    storePage();
    pages.splice(activePage,1);
    activePage=Math.min(activePage,pages.length-1);
    const next=pages[activePage];
    spec=next.spec;undoStack=next._undo||[];redoStack=next._redo||[];
    selected=-1;selectionKeys.clear();dirty=true;
    closeRepair();draw();schedule(0);
  };

  at("vsFormat").onchange=()=>{
    const gif=at("vsFormat").value==="gif";
    QA(".vs-gif-settings",root).forEach(el=>{el.hidden=!gif;});
    if(gif && spec.animation){
      at("vsEffect").value=spec.animation.effect||"flow";
      at("vsFrames").value=spec.animation.frames||20;
      at("vsDelay").value=spec.animation.duration_ms||110;
      at("vsLoop").value=spec.animation.loop??0;
    }
    drawTimeline();pageBars();schedule();
  };
  at("vsSave").onclick=async()=>{
    const btn=at("vsSave");btn.disabled=true;
    try{
      const out=await api("/api/visual/studio/document/save",{name,pages:documentPages()});
      dirty=false;await loadDrafts();at("vsDraft").value=out.path;
      toast("Editable "+pages.length+"-page document saved");status("Saved "+out.path);
    }catch(e){status("Save failed: "+e.message,true);}
    finally{btn.disabled=false;}
  };
  at("vsLoad").onclick=async()=>{
    const path=at("vsDraft").value;if(!path)return;
    if(dirty&&!window.confirm("Discard unsaved changes and open the saved draft?"))return;
    try{
      const data=await api("/api/visual/studio/load?path="+encodeURIComponent(path));
      setDocument(data);name=data.name;at("vsName").value=name;
      if(pages.length>1)at("vsFormat").value="pptx";
      if(spec.animation && pages.length===1){
        at("vsFormat").value="gif";
        at("vsEffect").value=spec.animation.effect||"flow";
        at("vsFrames").value=spec.animation.frames||20;
        at("vsDelay").value=spec.animation.duration_ms||110;
        at("vsLoop").value=spec.animation.loop??0;
        QA(".vs-gif-settings",root).forEach(el=>{el.hidden=false;});
      }
      draw();schedule(0);toast("Design opened");
    }catch(e){status("Could not open saved design: "+e.message,true);}
  };
  at("vsExport").onclick=async()=>{
    const btn=at("vsExport");btn.disabled=true;
    const fmt=at("vsFormat").value;
    const animation=fmt==="gif"?gifOptions():null;
    if(fmt==="gif"&&!animation){status("Add visible groups to use the GIF layer timeline.",true);btn.disabled=false;return;}
    if(animation)spec.animation=animation;
    const output_mode=at("vsOutputMode").value;
    const wholeDocument=pages.length>1 && (fmt==="pdf"||fmt==="pptx");
    const exportName=wholeDocument?name:name+(pages.length>1?" - "+pages[activePage].name:"");
    try{
      const out=wholeDocument
        ? await api("/api/visual/studio/document/export",{
            name:exportName,pages:documentPages(),format:fmt,output_mode})
        : await api("/api/visual/studio/export",{
            spec,name:exportName,format:fmt,animation,output_mode});
      const file="/api/files/download?path="+encodeURIComponent(out.path);
      const preview="/api/files/preview?path="+encodeURIComponent(out.path);
      const box=at("vsOutput");box.hidden=false;
      const project=out.draft?'/api/files/download?path='+encodeURIComponent(out.draft):null;
      box.innerHTML='<strong>Export ready</strong> <a class="btn primary" href="'+file+'" download>'+
        icon("download")+' Download '+esc(fmt.toUpperCase())+'</a> '+
        (project?'<a class="btn" href="'+project+'" download>Download editable layers</a>':'')+
        (fmt==="gif"?'<img src="'+preview+'" alt="Live animated GIF" style="max-height:155px;max-width:220px;object-fit:contain">':"");
      await loadDrafts();toast(wholeDocument?"Document exported":"Page exported");
      status("Exported "+out.path+(wholeDocument?" · "+pages.length+" pages.":pages.length>1
        ?" · Only the active page was exported.":".")+" Refreshing the latest preview…");
      schedule(0);
    }catch(e){status("Export failed: "+e.message,true);}
    finally{btn.disabled=false;}
  };
  overlay.addEventListener("pointerdown",e=>{
    const target=e.target.closest("[data-i]");if(!target)return;
    const i=Number(target.getAttribute("data-i"));if(!spec.elements[i])return;
    if(e.shiftKey||e.ctrlKey||e.metaKey){
      choose(i,true);e.preventDefault();return;
    }
    const hit=layerUnits(spec).find(u=>u.indices.includes(i));
    if(!hit)return;
    if(!selectionKeys.has(hit.key))selectionKeys=new Set([hit.key]);
    selected=i;
    const resizing=target.dataset.resize==="se",before=snap(),initial=selectionBox(spec,selected);
    draw();e.preventDefault();
    const units=selectedUnits();
    if(units.some(u=>u.locked||u.hidden)||(!resizing&&units.some(u=>u.isConnector)&&units.length>1))return;
    if(resizing&&units.length!==1)return;
    drag={id:e.pointerId,x:e.clientX,y:e.clientY,before,initial,resizing,
          index:i,keys:[...selectionKeys]};
    overlay.setPointerCapture(e.pointerId);
  });
  overlay.addEventListener("pointermove",e=>{
    if(!drag||drag.id!==e.pointerId)return;
    const rect=overlay.getBoundingClientRect();if(!rect.width||!rect.height)return;
    const dx=Math.round((e.clientX-drag.x)*spec.width/rect.width);
    const dy=Math.round((e.clientY-drag.y)*spec.height/rect.height);
    spec=copy(drag.before);
    if(drag.resizing){
      resizeSelection(spec,drag.index,drag.initial.w+dx,drag.initial.h+dy);
      relink(spec);highlight();e.preventDefault();return;
    }
    if(drag.before.elements[drag.index]?.type!=="line"){
      const shift=at("vsSnap").checked
        ? snapLayerDelta(drag.before,drag.keys,dx,dy):{dx,dy};
      translateLayerUnits(spec,drag.keys,shift.dx,shift.dy);
    }else{
      // Preserve existing independent line dragging. Linked workflow lines
      // are still repositioned deterministically by relink().
      const original=drag.before.elements[drag.index];
      const limX=Math.min(original.x1,original.x2);
      const limY=Math.min(original.y1,original.y2);
      const maxX=Math.max(original.x1,original.x2);
      const maxY=Math.max(original.y1,original.y2);
      const shiftX=clamp(dx,-limX,spec.width-maxX);
      const shiftY=clamp(dy,-limY,spec.height-maxY);
      const item=spec.elements[drag.index];
      item.x1=original.x1+shiftX;item.x2=original.x2+shiftX;
      item.y1=original.y1+shiftY;item.y2=original.y2+shiftY;
    }
    relink(spec);highlight();e.preventDefault();
  });
  const done=e=>{
    if(!drag||drag.id!==e.pointerId)return;
    try{overlay.releasePointerCapture(e.pointerId);}catch{/* pointer cancelled */}
    record(drag.before);drag=null;draw();
  };
  overlay.addEventListener("pointerup",done);
  overlay.addEventListener("pointercancel",done);
  root.addEventListener("keydown",e=>{
    if(/^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(e.target.tagName))return;
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="z"){
      e.preventDefault();if(e.shiftKey)redo();else undo();return;
    }
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="a"){
      e.preventDefault();at("vsSelectAll").click();return;
    }
    if(e.key==="Escape"&&selectedUnits().length){
      e.preventDefault();choose(-1);return;
    }
    const arrows={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
    if(!e.ctrlKey&&!e.metaKey&&!e.altKey&&arrows[e.key]&&selectedUnits().length){
      const amount=e.shiftKey?10:1,delta=arrows[e.key];
      if(selectedUnits().some(u=>u.locked||u.hidden||u.isConnector))return;
      e.preventDefault();
      change(()=>{if(translateLayerUnits(spec,[...selectionKeys],delta[0]*amount,delta[1]*amount))relink(spec);});
    }
  });
  draw();schedule(0);
  await Promise.all([loadAssets(),loadDrafts()]);
  const openImage=sessionStorage.getItem("automoto_visual_open_image");
  const openDraft=sessionStorage.getItem("automoto_visual_open_draft");
  if(openImage||openDraft){
    sessionStorage.removeItem("automoto_visual_open_image");
    sessionStorage.removeItem("automoto_visual_open_draft");
    try{
      const result=openDraft
        ? await api("/api/visual/studio/load?path="+encodeURIComponent(openDraft))
        : await api("/api/visual/studio/import",{path:openImage});
      setDocument(result);
      name=result.name||"Imported image";
      at("vsName").value=name;
      if(pages.length>1)at("vsFormat").value="pptx";
      selected=spec.elements.findIndex(e=>e.type==="image");
      selectionKeys=selected>=0?new Set([unitKey(spec.elements[selected],selected)]):new Set();
      undoStack=[];redoStack=[];dirty=false;
      at("vsOutputMode").value="layered";
      draw();schedule(0);
      status(result.note||"Source artwork opened as editable Visual Studio layers.");
      if(result.draft)await loadDrafts();
    }catch(e){status("Could not open this image: "+e.message,true);}
  }
}

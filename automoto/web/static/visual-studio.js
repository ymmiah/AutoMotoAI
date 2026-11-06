/* Visual Studio: native exported scene renderer, editable layers and bounded GIF tracks.
   Backend renders the final preview. Edits keep source imagery unchanged. */
import {layerUnits,toggleLayer,moveLayer,selectionBox,resizeSelection,
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
    '<div class="vs-shell"><section class="vs-workspace"><div class="vs-stage" id="vsStage" aria-busy="true">'+
    '<img id="vsPreview" class="vs-preview" alt="Actual rendered design preview" draggable="false">'+
    '<svg class="vs-over" id="vsOverlay" aria-label="Drag an object to reposition it"></svg></div>'+
    '<div class="vs-summary"><span>Select an object or drag it. Preview updates after edits.</span><span id="vsCount"></span></div>'+
    '<p id="vsStatus" class="vs-status" role="status">Preparing preview…</p></section>'+
    '<aside class="vs-inspector"><h3>Object inspector</h3>'+
    '<label for="vsElement" class="vs-inspector-note">Choose an element to edit</label>'+
    '<select class="input" id="vsElement" style="width:100%;margin:9px 0"></select>'+
    '<div id="vsProperties" class="vs-fields"></div>'+
    '<h3 class="vs-layer-heading">Layers <span class="vs-small">Front → back</span></h3>'+
    '<div id="vsLayers" class="vs-layers" aria-label="Visual design layers"></div>'+
    '<div class="vs-toolbar" style="margin-top:12px"><button class="btn" id="vsDuplicate">Duplicate</button>'+
    '<button class="btn danger" id="vsDelete">Delete</button></div>'+
    '<p class="vs-inspector-note">Grouped components move together. Exact text stays editable. Original uploaded imagery is not AI-redrawn.</p></aside></div>'+
    '<section class="vs-export"><label>Format <select id="vsFormat"><option value="png">PNG image</option><option value="svg">Editable SVG</option>'+
    '<option value="pptx">Editable PowerPoint</option><option value="pdf">PDF</option><option value="jpg">JPEG</option><option value="gif">Animated GIF</option></select></label>'+
    '<label class="vs-gif-settings" hidden>Motion <select id="vsEffect"><option value="flow">Flow</option><option value="pulse">Pulse</option>'+
    '<option value="reveal">Reveal</option><option value="float">Float</option><option value="sequence">Layer timeline</option></select></label>'+
    '<label class="vs-gif-settings" hidden>Frames <input id="vsFrames" type="number" min="8" max="48" value="20"></label>'+
    '<label class="vs-gif-settings" hidden>Milliseconds/frame <input id="vsDelay" type="number" min="50" max="500" value="110"></label>'+
    '<label class="vs-gif-settings" hidden>Loop <select id="vsLoop"><option value="0">Forever</option><option value="1">Once</option><option value="3">3 times</option></select></label>'+
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
  let previewSequence=0,previewTimer=null,drag=null;
  const status=(message,bad=false)=>{at("vsStatus").textContent=message;at("vsStatus").classList.toggle("bad",bad);};
  const snap=()=>copy(spec);
  function record(previous){
    if(JSON.stringify(previous)===JSON.stringify(spec))return;
    undoStack.push(previous);
    if(undoStack.length>40)undoStack.shift();
    redoStack=[];dirty=true;buttons();schedule();
  }
  function change(fn){
    const before=snap();fn();
    if(spec.animation?.effect==="sequence"){
      const next=normaliseSequence(spec);
      if(next)spec.animation=next;
      else delete spec.animation;
    }
    record(before);draw();
  }
  function buttons(){at("vsUndo").disabled=!undoStack.length;at("vsRedo").disabled=!redoStack.length;}
  function undo(){
    if(!undoStack.length)return;
    redoStack.push(snap());spec=undoStack.pop();selected=-1;
    at("vsEffect").value=spec.animation?.effect||"flow";
    draw();schedule();
  }
  function redo(){
    if(!redoStack.length)return;
    undoStack.push(snap());spec=redoStack.pop();selected=-1;
    at("vsEffect").value=spec.animation?.effect||"flow";
    draw();schedule();
  }
  function currentUnit(index=selected){
    return layerUnits(spec).find(u=>u.indices.includes(index));
  }
  function isLocked(index=selected){return !!currentUnit(index)?.locked;}
  function drawLayers(){
    const layers=layerUnits(spec).slice().reverse();
    at("vsLayers").innerHTML=layers.map((u,order)=>{
      const active=u.indices.includes(selected),iconName=u.isConnector?"link":u.key.startsWith("group:")?"folder":"file";
      const label=u.label+" ("+u.indices.length+")";
      const common=' data-layer-key="'+esc(u.key)+'"';
      return '<div class="vs-layer'+(active?' active':'')+(u.hidden?' hidden-layer':'')+'">'+
        '<button class="vs-layer-name" data-layer-act="select"'+common+' title="'+esc(label)+'">'+
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
    if(selected<0||!spec.elements[selected]||spec.elements[selected].hidden)return;
    const e=spec.elements[selected];
    const chosen=e.group?spec.elements.filter(a=>a.group===e.group):[e];
    const xs=chosen.map(a=>bounds(a)),x=Math.min(...xs.map(a=>a.x)),y=Math.min(...xs.map(a=>a.y));
    const right=Math.max(...xs.map(a=>a.x+a.w)),bottom=Math.max(...xs.map(a=>a.y+a.h));
    const mark=document.createElementNS(NS,"rect");
    mark.setAttribute("class","vs-selected");mark.setAttribute("x",String(Math.max(0,x-5)));
    mark.setAttribute("y",String(Math.max(0,y-5)));mark.setAttribute("width",String(Math.min(spec.width-x+5,right-x+10)));
    mark.setAttribute("height",String(Math.min(spec.height-y+5,bottom-y+10)));
    overlay.appendChild(mark);
    if(!isLocked() && e.type!=="line"){
      const grip=document.createElementNS(NS,"rect");
      grip.setAttribute("data-i",String(selected));
      grip.setAttribute("data-resize","se");
      grip.setAttribute("class","vs-resize-handle");
      grip.setAttribute("x",String(clamp(right-8,0,spec.width-20)));
      grip.setAttribute("y",String(clamp(bottom-8,0,spec.height-20)));
      grip.setAttribute("width","20");
      grip.setAttribute("height","20");
      grip.setAttribute("aria-label","Drag to resize selected design element");
      overlay.appendChild(grip);
    }
  }
  function inspector(){
    const pick=at("vsElement");
    pick.innerHTML='<option value="">Select an object</option>'+
      spec.elements.map((e,i)=>'<option value="'+i+'"'+(i===selected?' selected':'')+'>'+
        (i+1)+' · '+esc(e.type)+' '+(e.type==="text"?esc(e.text.slice(0,20)):esc(e.group||""))+'</option>').join("");
    const area=at("vsProperties");
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
    stage.style.aspectRatio=spec.width+"/"+spec.height;
    overlay.setAttribute("viewBox","0 0 "+spec.width+" "+spec.height);
    at("vsTitle").value=spec.title||"";
    at("vsSubtitle").value=spec.subtitle||"";
    at("vsTheme").value=spec.theme;
    at("vsCount").textContent=spec.elements.length+" editable elements";
    at("vsDelete").disabled=selected<0||isLocked();
    at("vsDuplicate").disabled=selected<0||isLocked();
    at("vsElement").disabled=false;
    inspector();drawLayers();highlight();buttons();drawTimeline();
  }
  function schedule(ms=450){
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
    spec=template(e.target.value,spec.theme);selected=-1;dirty=false;undoStack=[];redoStack=[];
    draw();schedule(0);
  };
  at("vsTheme").onchange=e=>change(()=>themeElements(spec,e.target.value));
  at("vsUndo").onclick=undo;at("vsRedo").onclick=redo;
  at("vsAddText").onclick=()=>add("text");at("vsAddShape").onclick=()=>add("rect");
  at("vsAddIcon").onclick=()=>add("icon");at("vsAddImage").onclick=()=>add("image");
  at("vsElement").onchange=e=>{selected=e.target.value===""?-1:Number(e.target.value);draw();};
  at("vsLayers").onclick=e=>{
    const button=e.target.closest("[data-layer-act]");if(!button)return;
    const key=button.dataset.layerKey,act=button.dataset.layerAct;
    const unit=layerUnits(spec).find(u=>u.key===key);if(!unit)return;
    if(act==="select"){selected=unit.indices[0];draw();return;}
    if(act==="visibility"||act==="lock"){
      const flag=act==="visibility"?"hidden":"locked";
      change(()=>toggleLayer(spec,key,flag,flag==="hidden"?!unit.hidden:!unit.locked));
      return;
    }
    if(act==="front"||act==="back"){
      if(unit.locked)return;
      const item=spec.elements[selected],direction=act==="front"?1:-1;
      change(()=>{
        if(moveLayer(spec,key,direction)){
          if(item)selected=spec.elements.indexOf(item);
          else selected=layerUnits(spec).find(u=>u.key===key)?.indices[0]??-1;
        }
      });
    }
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
    if(selected<0||isLocked())return;
    change(()=>{
      const chosen=spec.elements[selected],g=chosen.group;
      spec.elements=spec.elements.filter((e,i)=>g ? e.group!==g&&e.from_group!==g&&e.to_group!==g : i!==selected);
      selected=-1;relink(spec);
    });
  };
  at("vsDuplicate").onclick=()=>{
    if(selected<0||isLocked())return;
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
    });
  };
  for(const key of ["title","subtitle"]){
    const input=at(key==="title"?"vsTitle":"vsSubtitle");let previous;
    input.onfocus=()=>{previous=snap();};
    input.oninput=()=>{spec[key]=input.value;schedule();};
    input.onchange=()=>{record(previous||snap());};
  }
  at("vsName").oninput=e=>{name=e.target.value;};
  at("vsFormat").onchange=()=>{
    const gif=at("vsFormat").value==="gif";
    QA(".vs-gif-settings",root).forEach(el=>{el.hidden=!gif;});
    if(gif && spec.animation){
      at("vsEffect").value=spec.animation.effect||"flow";
      at("vsFrames").value=spec.animation.frames||20;
      at("vsDelay").value=spec.animation.duration_ms||110;
      at("vsLoop").value=spec.animation.loop??0;
    }
    drawTimeline();schedule();
  };
  at("vsSave").onclick=async()=>{
    const btn=at("vsSave");btn.disabled=true;
    try{
      const out=await api("/api/visual/studio/save",{name,spec});
      dirty=false;await loadDrafts();at("vsDraft").value=out.path;toast("Editable design saved");status("Saved "+out.path);
    }catch(e){status("Save failed: "+e.message,true);}
    finally{btn.disabled=false;}
  };
  at("vsLoad").onclick=async()=>{
    const path=at("vsDraft").value;if(!path)return;
    if(dirty&&!window.confirm("Discard unsaved changes and open the saved draft?"))return;
    try{
      const data=await api("/api/visual/studio/load?path="+encodeURIComponent(path));
      spec=data.spec;name=data.name;at("vsName").value=name;selected=-1;dirty=false;undoStack=[];redoStack=[];
      if(spec.animation){
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
    try{
      const out=await api("/api/visual/studio/export",{spec,name,format:fmt,animation});
      const file="/api/files/download?path="+encodeURIComponent(out.path);
      const draft="/api/files/download?path="+encodeURIComponent(out.draft);
      const preview="/api/files/preview?path="+encodeURIComponent(out.path);
      const box=at("vsOutput");box.hidden=false;
      box.innerHTML='<strong>Export ready</strong> <a class="btn primary" href="'+file+'" download>'+
        icon("download")+' Download '+esc(fmt.toUpperCase())+'</a> '+
        '<a class="btn" href="'+draft+'" download>Editable design specification</a>'+
        (fmt==="gif"?'<img src="'+preview+'" alt="Live animated GIF" style="max-height:155px;max-width:220px;object-fit:contain">':"");
      dirty=false;loadDrafts();toast("Design exported");status("Saved "+out.path+" and its provenance record.");
    }catch(e){status("Export failed: "+e.message,true);}
    finally{btn.disabled=false;}
  };
  overlay.addEventListener("pointerdown",e=>{
    const target=e.target.closest("[data-i]");if(!target)return;
    const i=Number(target.getAttribute("data-i"));if(!spec.elements[i])return;
    const resizing=target.dataset.resize==="se";
    selected=i;
    const before=snap(),initial=selectionBox(spec,selected);
    draw();e.preventDefault();
    if(isLocked())return;
    drag={id:e.pointerId,x:e.clientX,y:e.clientY,before,initial,resizing};
    overlay.setPointerCapture(e.pointerId);
  });
  overlay.addEventListener("pointermove",e=>{
    if(!drag||drag.id!==e.pointerId)return;
    const rect=overlay.getBoundingClientRect();if(!rect.width||!rect.height)return;
    const dx=Math.round((e.clientX-drag.x)*spec.width/rect.width);
    const dy=Math.round((e.clientY-drag.y)*spec.height/rect.height);
    if(drag.resizing){
      spec=copy(drag.before);
      resizeSelection(spec,selected,drag.initial.w+dx,drag.initial.h+dy);
      relink(spec);highlight();e.preventDefault();return;
    }
    const orig=drag.before.elements[selected],g=orig.group;
    const ids=drag.before.elements.reduce((a,item,i)=>{
      if(g&&item.group===g||!g&&i===selected)a.push(i);return a;
    },[]);
    const boxes=ids.map(i=>bounds(drag.before.elements[i]));
    const left=Math.min(...boxes.map(b=>b.x)),top=Math.min(...boxes.map(b=>b.y));
    const right=Math.max(...boxes.map(b=>b.x+b.w)),bottom=Math.max(...boxes.map(b=>b.y+b.h));
    const tx=clamp(dx,Math.ceil(-left),Math.floor(spec.width-right));
    const ty=clamp(dy,Math.ceil(-top),Math.floor(spec.height-bottom));
    for(const i of ids){
      const item=spec.elements[i],base=drag.before.elements[i];
      if(item.type==="line"){item.x1=base.x1+tx;item.x2=base.x2+tx;item.y1=base.y1+ty;item.y2=base.y2+ty;}
      else {item.x=base.x+tx;item.y=base.y+ty;}
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
    if(!(e.ctrlKey||e.metaKey)||e.key.toLowerCase()!=="z")return;
    if(/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName))return;
    e.preventDefault();if(e.shiftKey)redo();else undo();
  });
  draw();schedule(0);
  await Promise.all([loadAssets(),loadDrafts()]);
}

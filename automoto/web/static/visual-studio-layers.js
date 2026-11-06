/* Pure layer and resize operations for AutoMoto Visual Studio.
   A group's editable contents move together; source image pixels are never modified. */
const clamp=(n,lo,hi)=>Math.max(lo,Math.min(n,hi));
export const unitKey=(element,index)=>element.group?"group:"+element.group:"item:"+index;

export function layerUnits(spec){
  const units=[],byKey=new Map();
  (spec.elements||[]).forEach((element,index)=>{
    const key=unitKey(element,index);
    if(!byKey.has(key)){
      const unit={key,indices:[],label:element.group||element.type+" "+(index+1),
                  hidden:!!element.hidden,locked:!!element.locked,first:index,
                  isConnector:element.type==="line"};
      units.push(unit);byKey.set(key,unit);
    }
    const unit=byKey.get(key);
    unit.indices.push(index);
    unit.hidden=unit.hidden&&!!element.hidden;
    unit.locked=unit.locked||!!element.locked;
  });
  return units;
}

export function toggleLayer(spec,key,flag,next){
  if(!["hidden","locked"].includes(flag))throw Error("unsupported layer control");
  const unit=layerUnits(spec).find(u=>u.key===key);
  if(!unit)return false;
  for(const i of unit.indices)spec.elements[i][flag]=!!next;
  return true;
}

export function moveLayer(spec,key,direction){
  if(![-1,1].includes(direction))return false;
  const all=layerUnits(spec);
  // Keep linked connectors behind the blocks they join so they never cover copy.
  const connectors=all.filter(u=>u.isConnector);
  const units=all.filter(u=>!u.isConnector);
  const pos=units.findIndex(u=>u.key===key);
  const other=pos+direction;
  if(pos<0||other<0||other>=units.length)return false;
  [units[pos],units[other]]=[units[other],units[pos]];
  spec.elements=[...connectors,...units].flatMap(u=>u.indices.map(i=>spec.elements[i]));
  return true;
}

export function box(element){
  if(element.type==="line"){
    return {x:Math.min(element.x1,element.x2),y:Math.min(element.y1,element.y2),
            w:Math.abs(element.x2-element.x1),h:Math.abs(element.y2-element.y1)};
  }
  return {x:element.x,y:element.y,w:element.w,h:element.h};
}

export function selectionBox(spec,index){
  const chosen=spec.elements[index];if(!chosen)return null;
  const selected=chosen.group?
    spec.elements.filter(e=>e.group===chosen.group&&e.type!=="line"):[chosen];
  const bounds=selected.map(box);
  const x=Math.min(...bounds.map(v=>v.x)),y=Math.min(...bounds.map(v=>v.y));
  return {x,y,w:Math.max(...bounds.map(v=>v.x+v.w))-x,
              h:Math.max(...bounds.map(v=>v.y+v.h))-y};
}

export function resizeSelection(spec,index,width,height){
  const e=spec.elements[index];if(!e||e.locked||e.type==="line")return false;
  const group=e.group;
  const ids=spec.elements.map((it,i)=>group&&it.group===group?i:!group&&i===index?i:-1).filter(i=>i>=0);
  if(ids.some(i=>spec.elements[i].locked))return false;
  const original=selectionBox(spec,index);
  if(!original||original.w<5||original.h<5)return false;
  // Bounded, proportional group geometry. Text remains real and can be
  // independently edited; quality checks reject any remaining overflow.
  const targetW=clamp(width,Math.max(28,original.w*.55),Math.min(spec.width-original.x,original.w*3));
  const targetH=clamp(height,Math.max(28,original.h*.55),Math.min(spec.height-original.y,original.h*3));
  const sx=targetW/original.w,sy=targetH/original.h;
  for(const i of ids){
    const it=spec.elements[i];
    if(it.type==="line")continue;
    it.x=Number((original.x+(it.x-original.x)*sx).toFixed(2));
    it.y=Number((original.y+(it.y-original.y)*sy).toFixed(2));
    it.w=Number(Math.max(1,it.w*sx).toFixed(2));
    it.h=Number(Math.max(1,it.h*sy).toFixed(2));
    if(it.type==="icon"){
      const side=Math.min(it.w,it.h);it.w=side;it.h=side;
    }
  }
  return true;
}

export function sequenceTracks(spec){
  return layerUnits(spec)
    .filter(u=>u.key.startsWith("group:")&&!u.hidden)
    .map(u=>u.key.slice(6))
    .filter(Boolean).slice(0,12);
}

export function normaliseSequence(spec){
  const groups=sequenceTracks(spec);
  if(!groups.length)return null;
  const old=spec.animation?.effect==="sequence"?spec.animation.stages||[]:[];
  const previous=new Map(old.filter(x=>x&&typeof x.group==="string").map(x=>[x.group,x.start]));
  return {
    effect:"sequence",
    frames:Math.max(8,Math.min(48,Number(spec.animation?.frames)||20)),
    duration_ms:Math.max(50,Math.min(500,Number(spec.animation?.duration_ms)||110)),
    loop:Math.max(0,Math.min(20,Number(spec.animation?.loop)||0)),
    stages:groups.map((group,i)=>({
      group,start:clamp(Number(previous.get(group)??(groups.length===1?0.35:i/groups.length)),0,0.9)
    }))
  };
}

/* v7: selection operates on WHOLE layer units. Never create nested groups or
   accidentally transform a locked or hidden child of a selected group. */
export function selectedLayerUnits(spec,keys){
  const wanted=new Set(keys);
  return layerUnits(spec).filter(u=>wanted.has(u.key));
}

export function selectionBounds(spec,keys){
  const units=selectedLayerUnits(spec,keys);
  const ids=units.flatMap(u=>u.indices).filter(i=>spec.elements[i].type!=="line");
  if(!ids.length)return null;
  const rectangles=ids.map(i=>box(spec.elements[i]));
  const x=Math.min(...rectangles.map(b=>b.x)),y=Math.min(...rectangles.map(b=>b.y));
  return {x,y,w:Math.max(...rectangles.map(b=>b.x+b.w))-x,
              h:Math.max(...rectangles.map(b=>b.y+b.h))-y};
}

function editableUnits(spec,keys,min=1){
  const units=selectedLayerUnits(spec,keys);
  if(units.length<min || units.length!==new Set(keys).size)return null;
  if(units.some(u=>u.hidden||u.locked||u.isConnector||
      u.indices.some(i=>spec.elements[i].type==="line"||spec.elements[i].hidden||spec.elements[i].locked)))return null;
  return units;
}

function unitBounds(spec,u){
  const rects=u.indices.filter(i=>spec.elements[i].type!=="line").map(i=>box(spec.elements[i]));
  if(!rects.length)return null;
  const x=Math.min(...rects.map(b=>b.x)),y=Math.min(...rects.map(b=>b.y));
  return {x,y,w:Math.max(...rects.map(b=>b.x+b.w))-x,
                h:Math.max(...rects.map(b=>b.y+b.h))-y};
}

function translate(spec,unit,dx,dy){
  for(const i of unit.indices){
    const e=spec.elements[i];
    e.x=Number((e.x+dx).toFixed(2));
    e.y=Number((e.y+dy).toFixed(2));
  }
}

export function translateLayerUnits(spec,keys,dx,dy){
  const units=editableUnits(spec,keys);
  if(!units||![dx,dy].every(Number.isFinite))return false;
  const area=selectionBounds(spec,keys);
  if(!area)return false;
  const x=clamp(dx,-area.x,spec.width-area.x-area.w);
  const y=clamp(dy,-area.y,spec.height-area.y-area.h);
  if(!x&&!y)return false;
  for(const unit of units)translate(spec,unit,x,y);
  return true;
}

export function alignLayerUnits(spec,keys,alignment){
  const units=editableUnits(spec,keys,2);
  if(!units || !["left","center","right","top","middle","bottom"].includes(alignment))return false;
  const boxes=units.map(u=>unitBounds(spec,u));
  if(boxes.some(b=>!b))return false;
  const anchor=boxes[0],moves=[];
  const at=(b,kind)=>{
    if(kind==="left")return b.x;
    if(kind==="center")return b.x+b.w/2;
    if(kind==="right")return b.x+b.w;
    if(kind==="top")return b.y;
    if(kind==="middle")return b.y+b.h/2;
    return b.y+b.h;
  };
  const value=at(anchor,alignment),horizontal=["left","center","right"].includes(alignment);
  for(const b of boxes){
    const offset=value-at(b,alignment);
    const dx=horizontal?offset:0,dy=horizontal?0:offset;
    if(b.x+dx<0||b.y+dy<0||b.x+b.w+dx>spec.width||b.y+b.h+dy>spec.height)return false;
    moves.push({dx,dy});
  }
  if(moves.every(m=>!m.dx&&!m.dy))return false;
  units.forEach((unit,i)=>translate(spec,unit,moves[i].dx,moves[i].dy));
  return true;
}

export function distributeLayerUnits(spec,keys,axis){
  const units=editableUnits(spec,keys,3);
  if(!units||!["horizontal","vertical"].includes(axis))return false;
  const horizontal=axis==="horizontal";
  const ordered=units.map(u=>({unit:u,b:unitBounds(spec,u)}))
    .sort((a,b)=>(horizontal?a.b.x-b.b.x:a.b.y-b.b.y));
  const start=horizontal?ordered[0].b.x:ordered[0].b.y;
  const end=horizontal?
    ordered[ordered.length-1].b.x+ordered[ordered.length-1].b.w:
    ordered[ordered.length-1].b.y+ordered[ordered.length-1].b.h;
  const occupied=ordered.reduce((a,item)=>a+(horizontal?item.b.w:item.b.h),0);
  const gap=(end-start-occupied)/(ordered.length-1);
  if(gap<0)return false; // Never knowingly overlap a set of distributed layers.
  let cursor=start;const moves=[];
  for(const {b} of ordered){
    const original=horizontal?b.x:b.y,offset=cursor-original;
    const dx=horizontal?offset:0,dy=horizontal?0:offset;
    if(b.x+dx<0||b.y+dy<0||b.x+b.w+dx>spec.width||b.y+b.h+dy>spec.height)return false;
    moves.push({dx,dy});cursor+=(horizontal?b.w:b.h)+gap;
  }
  if(moves.every(m=>Math.abs(m.dx)<.01&&Math.abs(m.dy)<.01))return false;
  ordered.forEach(({unit},i)=>translate(spec,unit,moves[i].dx,moves[i].dy));
  return true;
}

export function groupLayerUnits(spec,keys){
  const units=editableUnits(spec,keys,2);
  if(!units||units.some(u=>u.key.startsWith("group:") || u.indices.length!==1))return null;
  const existing=new Set(spec.elements.map(e=>e.group).filter(Boolean));
  let n=1;while(existing.has("studio_group_"+n))n++;
  const name="studio_group_"+n;
  for(const u of units)spec.elements[u.indices[0]].group=name;
  return name;
}

export function ungroupLayerUnits(spec,keys){
  const units=editableUnits(spec,keys,1);
  if(!units||units.length!==1)return false;
  const unit=units[0];
  if(!unit.key.startsWith("group:"))return false;
  const name=unit.key.slice(6);
  // Relational workflow links must not lose their referenced group.
  if(spec.elements.some(e=>e.type==="line"&&(e.from_group===name||e.to_group===name)))return false;
  for(const i of unit.indices)delete spec.elements[i].group;
  return true;
}

export function snapLayerDelta(spec,keys,dx,dy,{grid=8,threshold=7}={}){
  const units=editableUnits(spec,keys);
  const area=selectionBounds(spec,keys);
  if(!units||!area||![dx,dy].every(Number.isFinite))return {dx,dy};
  const wanted=new Set(units.flatMap(u=>u.indices));
  const others=layerUnits(spec).filter(u=>!u.hidden&&!u.isConnector &&
    u.indices.every(i=>!wanted.has(i))).map(u=>unitBounds(spec,u)).filter(Boolean);
  function snap(axis,d){
    const horizontal=axis==="x",size=horizontal?spec.width:spec.height;
    const pos=horizontal?area.x:area.y,length=horizontal?area.w:area.h;
    const margin=Math.max(12,Math.round(size*.052));
    const targets=[0,margin,size/2,size-margin,size];
    for(const b of others){
      const start=horizontal?b.x:b.y,span=horizontal?b.w:b.h;
      targets.push(start,start+span/2,start+span);
    }
    let best=0,nearest=threshold+.01;
    for(const offset of [0,length/2,length]){
      const current=pos+d+offset;
      for(const target of targets){
        const delta=target-current,abs=Math.abs(delta);
        if(abs<=threshold && abs<nearest && pos+d+delta>=0 &&
           pos+d+delta+length<=size){best=delta;nearest=abs;}
      }
      if(grid>0){
        const delta=Math.round(current/grid)*grid-current,abs=Math.abs(delta);
        if(abs<=threshold && abs<nearest && pos+d+delta>=0 &&
           pos+d+delta+length<=size){best=delta;nearest=abs;}
      }
    }
    return clamp(d+best,-pos,size-pos-length);
  }
  return {dx:snap("x",dx),dy:snap("y",dy)};
}

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

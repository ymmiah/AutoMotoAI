/* Pure keyframe timeline editing. Editor never applies motion to the native art. */
import {sequenceTracks} from "./visual-studio-layers.js";

const VALUE_LIMITS={dx:[-250,250],dy:[-250,250],scale:[0.5,1.5],
                    opacity:[0,1],rotation:[-45,45]};
export const MOTION_FIELDS=Object.freeze(["dx","dy","scale","opacity","rotation"]);
export const MOTION_EASINGS=Object.freeze(["linear","ease-in","ease-out","ease-in-out"]);
const clamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
const copy=x=>JSON.parse(JSON.stringify(x));
function defaultKeys(){
  return [
    {at:0,dx:-24,dy:0,scale:0.94,opacity:0.35,rotation:-4,easing:"ease-out"},
    {at:1,dx:0,dy:0,scale:1,opacity:1,rotation:0,easing:"linear"}
  ];
}
export function normaliseMotion(spec){
  const groups=sequenceTracks(spec);
  if(!groups.length)return null;
  const old=spec.animation?.effect==="keyframes"&&Array.isArray(spec.animation.tracks)
    ? spec.animation.tracks:[];
  const byGroup=new Map(old.filter(t=>t&&typeof t.group==="string").map(t=>[t.group,t]));
  const frames=clamp(Math.round(Number(spec.animation?.frames)||20),8,48);
  const duration_ms=clamp(Math.round(Number(spec.animation?.duration_ms)||110),50,500);
  const loop=clamp(Math.round(Number(spec.animation?.loop)||0),0,20);
  return {effect:"keyframes",frames,duration_ms,loop,
    tracks:groups.map(group=>{
      const track=byGroup.get(group);
      const valid=track&&Array.isArray(track.keyframes)&&track.keyframes.length>=2&&
        track.keyframes.length<=6&&track.keyframes.every(k=>
        k&&Number.isFinite(k.at)&&Number.isFinite(k.dx)&&Number.isFinite(k.dy)&&
        Number.isFinite(k.scale)&&Number.isFinite(k.opacity)&&Number.isFinite(k.rotation)&&
        MOTION_EASINGS.includes(k.easing)&&
        MOTION_FIELDS.every(field=>k[field]>=VALUE_LIMITS[field][0]&&k[field]<=VALUE_LIMITS[field][1]))
        &&track.keyframes.every((k,i,a)=>i===0||k.at>a[i-1].at)
        &&track.keyframes[0].at===0&&track.keyframes.at(-1).at===1;
      return {group,keyframes:valid?copy(track.keyframes):defaultKeys()};
    })};
}
export function addMotionKey(config,group,at){
  const next=copy(config),track=next.tracks.find(t=>t.group===group);
  const position=Math.round(Number(at)*100)/100;
  if(!track||!Number.isFinite(position)||position<=0||position>=1||
     track.keyframes.length>=6||
     track.keyframes.some(k=>Math.abs(k.at-position)<0.005))return null;
  let i=track.keyframes.findIndex(k=>k.at>position);
  if(i<1)return null;
  const l=track.keyframes[i-1],r=track.keyframes[i],ratio=(position-l.at)/(r.at-l.at);
  const interpolated={at:position,easing:"ease-in-out"};
  for(const field of MOTION_FIELDS)interpolated[field]=
    Math.round((l[field]+(r[field]-l[field])*ratio)*100)/100;
  track.keyframes.splice(i,0,interpolated);
  return next;
}
export function removeMotionKey(config,group,index){
  const next=copy(config),track=next.tracks.find(t=>t.group===group);
  if(!track||!Number.isInteger(index)||index<=0||index>=track.keyframes.length-1)return null;
  track.keyframes.splice(index,1);
  return next;
}
export function editMotionKey(config,group,index,field,value){
  const next=copy(config),track=next.tracks.find(t=>t.group===group);
  if(!track||!Number.isInteger(index)||index<0||index>=track.keyframes.length)return null;
  const key=track.keyframes[index];
  if(field==="easing"){
    if(!MOTION_EASINGS.includes(value))return null;
    key.easing=value;
  }else if(field==="at"){
    const pos=Number(value);
    if(!Number.isFinite(pos)||index===0||index===track.keyframes.length-1||
       pos<=track.keyframes[index-1].at||pos>=track.keyframes[index+1].at)return null;
    key.at=Math.round(pos*100)/100;
    if(key.at<=track.keyframes[index-1].at||key.at>=track.keyframes[index+1].at)return null;
  }else{
    const range=VALUE_LIMITS[field],n=Number(value);
    if(!range||!Number.isFinite(n)||n<range[0]||n>range[1])return null;
    key[field]=n;
  }
  return next;
}

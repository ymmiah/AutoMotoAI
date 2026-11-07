// Pure, deterministic keyframe model tests: no model download or network.
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
(async()=>{
  const root=path.resolve(__dirname,'../../../automoto/web/static');
  const layerCode=readFileSync(path.join(root,'visual-studio-layers.js'),'utf8');
  const layerUri='data:text/javascript;base64,'+Buffer.from(layerCode).toString('base64');
  const code=readFileSync(path.join(root,'visual-studio-motion.js'),'utf8')
    .replace('from "./visual-studio-layers.js"', 'from "'+layerUri+'"');
  const motion=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
  const spec={
    layout:'canvas',width:800,height:500,
    elements:[
      {type:'rect',group:'alpha',x:60,y:80,w:200,h:140},
      {type:'text',group:'alpha',x:70,y:100,w:140,h:70,text:'Original copy'},
      {type:'rect',group:'beta',x:420,y:80,w:200,h:140},
      {type:'text',group:'beta',x:450,y:100,w:140,h:70,text:'Other copy'},
      {type:'image',group:'beta',x:460,y:200,w:80,h:50,path:'uploads/photo.png',locked:true},
    ],
  };
  const before=JSON.stringify(spec);
  const configuration=motion.normaliseMotion(spec);
  assert.equal(configuration.effect,'keyframes');
  assert.deepEqual(configuration.tracks.map(t=>t.group),['alpha','beta']);
  assert.equal(configuration.tracks[0].keyframes.length,2);
  assert.equal(configuration.tracks[0].keyframes[0].at,0);
  assert.equal(configuration.tracks[0].keyframes[1].at,1);
  assert.equal(configuration.frames,20);
  assert.equal(configuration.duration_ms,110);
  const inserted=motion.addMotionKey(configuration,'alpha',.5);
  assert.equal(inserted.tracks[0].keyframes.length,3);
  assert.equal(configuration.tracks[0].keyframes.length,2,
    'editing must not mutate the input animation');
  assert.equal(inserted.tracks[0].keyframes[1].at,.5);
  assert.equal(motion.addMotionKey(inserted,'alpha',.5),null,
    'duplicate keyframe position refused');
  assert.equal(motion.addMotionKey(inserted,'alpha',0),null,
    'endpoint keys are not replaced');
  const moved=motion.editMotionKey(inserted,'alpha',1,'dx',45);
  assert.equal(moved.tracks[0].keyframes[1].dx,45);
  assert.equal(inserted.tracks[0].keyframes[1].dx,-12);
  assert.equal(motion.editMotionKey(moved,'alpha',1,'rotation',90),null);
  assert.equal(motion.editMotionKey(moved,'alpha',1,'opacity',-1),null);
  assert.equal(motion.editMotionKey(moved,'alpha',1,'easing','eval(alert(1))'),null);
  assert.equal(motion.editMotionKey(moved,'alpha',1,'at',1),null);
  assert.equal(motion.editMotionKey(moved,'alpha',0,'at',.4),null);
  const intermediate=motion.editMotionKey(moved,'alpha',1,'at',.6);
  assert.equal(intermediate.tracks[0].keyframes[1].at,.6);
  assert.equal(motion.removeMotionKey(intermediate,'alpha',0),null);
  assert.equal(motion.removeMotionKey(intermediate,'alpha',2),null);
  const restored=motion.removeMotionKey(intermediate,'alpha',1);
  assert.equal(restored.tracks[0].keyframes.length,2);
  assert.equal(JSON.stringify(spec),before,
    'keyframe editing must never rewrite original artwork or photo paths');
  assert.equal(spec.elements[4].path,'uploads/photo.png');
  const switched=structuredClone(spec);
  switched.animation=inserted;
  const again=motion.normaliseMotion(switched);
  assert.equal(again.tracks[0].keyframes.length,3,
    'saved native timeline must reopen with its exact keyframe values');
  assert.equal(again.tracks[0].keyframes[1].at,.5);
  console.log('Visual Studio v10 keyframe model assertions passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});

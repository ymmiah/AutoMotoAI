// Pure geometry regressions against the exact JS module loaded by Visual Studio.
// This test needs Node only, no model, browser or local server.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');

(async () => {
  const source = readFileSync(path.resolve(__dirname, '../../../automoto/web/static/visual-studio-layers.js'), 'utf8');
  const layer = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
  const spec = (elements) => ({width:800,height:500,layout:'canvas',elements:structuredClone(elements)});
  const item = (x,y,w=80,h=60,other={})=>({type:'rect',x,y,w,h,fill:'#FFFFFF',...other});
  const snapshot = v=>JSON.stringify(v);

  {
    const s=spec([item(40,50,100,60,{group:'card'}),{type:'text',x:55,y:70,w:50,h:30,
      font_size:16,text:'Exact wording',colour:'#111111',group:'card'},item(280,70)]);
    const keys=['group:card','item:2'];
    assert.deepEqual(layer.selectedLayerUnits(s,keys).map(x=>x.indices),[[0,1],[2]]);
    assert.deepEqual(layer.selectionBounds(s,keys),{x:40,y:50,w:320,h:80});
    assert.equal(layer.translateLayerUnits(s,keys,15,20),true);
    assert.deepEqual([s.elements[0].x,s.elements[1].x,s.elements[2].x],[55,70,295]);
    assert.equal(s.elements[1].text,'Exact wording');
    assert.equal(layer.translateLayerUnits(s,['group:card','item:2'],500,0),true);
    assert.ok(s.elements.every(x=>x.x+x.w<=800),'translated objects must fit on canvas');
  }
  {
    const s=spec([item(30,60),item(300,200),item(500,350)]);
    assert.equal(layer.alignLayerUnits(s,['item:0','item:1'],'left'),true);
    assert.equal(s.elements[0].x,s.elements[1].x);
    assert.equal(s.elements[2].x,500);
    assert.equal(layer.distributeLayerUnits(s,['item:0','item:1','item:2'],'diagonal'),false);
  }
  {
    const s=spec([item(50,100,50,50),item(200,240,50,50),item(550,380,50,50)]);
    const original=snapshot(s);
    assert.equal(layer.distributeLayerUnits(s,['item:0','item:1','item:2'],'horizontal'),true);
    assert.equal(s.elements[1].x,300);
    assert.equal(s.elements[1].y,240);
    assert.notEqual(snapshot(s),original);
  }
  {
    const s=spec([item(100,100),item(302,280)]);
    const snap=layer.snapLayerDelta(s,['item:0'],195,0,{grid:0,threshold:8});
    assert.equal(snap.dx,202,'nearby alignment guide should snap selected left edge');
    assert.equal(layer.translateLayerUnits(s,['item:0'],snap.dx,snap.dy),true);
    assert.equal(s.elements[0].x,302);
  }
  {
    const s=spec([item(50,50),item(200,200,{w:80}),item(390,350)]);
    assert.equal(layer.groupLayerUnits(s,['item:0','item:1']),'studio_group_1');
    assert.equal(s.elements[0].group,'studio_group_1');
    assert.equal(s.elements[1].group,'studio_group_1');
    assert.equal(layer.layerUnits(s).length,2);
    assert.equal(layer.groupLayerUnits(s,['group:studio_group_1','item:2']),null,
      'nested/flattened grouping is deliberately unsupported');
    assert.equal(layer.ungroupLayerUnits(s,['group:studio_group_1']),true);
    assert.ok(s.elements.slice(0,2).every(x=>!x.group));
  }
  {
    const s=spec([item(40,40,{w:70}),item(300,300),item(160,180,80,60,{locked:true})]);
    const before=snapshot(s);
    assert.equal(layer.translateLayerUnits(s,['item:0','item:2'],30,0),false);
    assert.equal(layer.alignLayerUnits(s,['item:0','item:2'],'left'),false);
    assert.equal(layer.groupLayerUnits(s,['item:0','item:2']),null);
    assert.equal(snapshot(s),before,'never partially mutate protected selections');
  }
  {
    const s=spec([item(40,50,110,60,{group:'stage0'}),item(360,55),
      {type:'line',x1:150,y1:70,x2:360,y2:70,from_group:'stage0',to_group:'stage1'}]);
    assert.equal(layer.ungroupLayerUnits(s,['group:stage0']),false,
      'group referenced by workflow connector cannot be split');
    assert.equal(s.elements[0].group,'stage0');
  }
  {
    const s=spec([item(100,100,80,80),{type:'image',x:260,y:120,w:150,h:100,
      path:'uploads/original.png',alt:'Original image'}]);
    const p=s.elements[1].path;
    assert.equal(layer.translateLayerUnits(s,['item:0','item:1'],20,35),true);
    assert.equal(s.elements[1].path,p);
    assert.equal(s.elements[1].w,150);
    assert.equal(s.elements[1].h,100);
  }
  {
    const s=spec([item(0,50,30,60),item(700,100,100,60)]);
    const before=snapshot(s);
    assert.equal(layer.alignLayerUnits(s,['item:0','item:1'],'center'),false,
      'out-of-canvas alignment must fail atomically');
    assert.equal(snapshot(s),before);
  }
  console.log('Visual Studio v7 layer geometry: all assertions passed.');
})().catch(err=>{console.error(err);process.exitCode=1;});

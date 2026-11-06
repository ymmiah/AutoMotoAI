// Deterministic v9 brand-kit regressions. No API, model, filesystem writes or network.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
(async () => {
  const code = readFileSync(path.resolve(__dirname,
    '../../../automoto/web/static/visual-studio-brands.js'), 'utf8');
  const brand = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
  const colours = {background:'#F8F9F7',ink:'#172638',muted:'#526476',
    accent:'#246D83',card:'#FFFFFF',border:'#DCE5E9',
    tone0:'#E8F3F1',tone1:'#E7ECFB',tone2:'#FFF0CF'};
  const kit = {name:'Test identity',colours,heading_size:36,body_size:19,logo:'uploads/logo.png'};
  const initial = {layout:'canvas',width:800,height:500,theme:'editorial-light',
    elements:[
      {type:'text',x:50,y:80,w:320,h:90,text:'Exact source wording',font_size:26,
       colour:'#444444',auto_colour:'ink',style_role:'heading'},
      {type:'text',x:50,y:190,w:360,h:65,text:'Original body text',font_size:22,
       colour:'#777777',auto_colour:'muted',style_role:'body'},
      {type:'rect',x:40,y:260,w:280,h:150,fill:'#DADADA',auto_fill:'tone0',
       stroke:'#888888',auto_stroke:'border'},
      {type:'text',x:420,y:80,w:320,h:60,text:'Manually styled',font_size:29,
       colour:'#AABBCC'},
      {type:'image',x:420,y:250,w:160,h:90,path:'uploads/original.png',
       alt:'Original pixels and identity',locked:true},
      {type:'rect',x:620,y:330,w:80,h:50,fill:'#123456',auto_fill:'tone1',locked:true},
      {type:'rect',x:330,y:310,w:50,h:40,fill:'#654321',auto_fill:'tone2',hidden:true}
    ]};
  const spec=structuredClone(initial),original=JSON.stringify(initial);
  assert.equal(brand.applyBrandKit(spec,kit),true);
  assert.equal(spec.elements[0].colour,colours.ink);
  assert.equal(spec.elements[0].font_size,36);
  assert.equal(spec.elements[0].text,'Exact source wording');
  assert.equal(spec.elements[1].colour,colours.muted);
  assert.equal(spec.elements[1].font_size,19);
  assert.equal(spec.elements[2].fill,colours.tone0);
  assert.equal(spec.elements[2].stroke,colours.border);
  assert.deepEqual(spec.elements[3],initial.elements[3],
    'manual typography and colours cannot be changed by a brand kit');
  for(const i of [4,5,6])assert.deepEqual(spec.elements[i],initial.elements[i],
    'source images, locked and hidden layers are untouched');
  assert.deepEqual(spec.colours,Object.fromEntries(
    brand.BRAND_COLOUR_KEYS.slice(0,6).map(k=>[k,colours[k]])));
  assert.equal(spec.brand_style.name,'Test identity');
  assert.equal(JSON.stringify(initial),original,'caller-owned input remains unchanged');
  assert.equal(brand.applyBrandKit(spec,kit),false,
    'applying the same kit again must not create duplicate edits');
  assert.equal(brand.brandTextRole(spec.elements[3],'body'),true);
  assert.equal(spec.elements[3].style_role,'body');
  assert.equal(brand.brandTextRole(spec.elements[3],'manual'),true);
  assert.equal(Object.hasOwn(spec.elements[3],'style_role'),false);
  assert.equal(brand.brandTextRole(spec.elements[4],'heading'),false,
    'image sources can never be treated as brand text');
  const badKit=structuredClone(kit);
  badKit.colours.accent='red;url(https://example.invalid)';
  assert.throws(()=>brand.applyBrandKit(structuredClone(initial),badKit),/Invalid brand colours/);
  const badFont=structuredClone(kit);
  badFont.heading_size=150;
  assert.throws(()=>brand.paletteFromKit(badFont),/typography/);
  const separate=[structuredClone(initial),structuredClone(initial)];
  brand.applyBrandKit(separate[1],kit);
  assert.deepEqual(separate[0],initial,'brand application is page-scoped unless explicitly repeated');
  console.log('Visual Studio v9 brand kit field-preservation assertions passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});

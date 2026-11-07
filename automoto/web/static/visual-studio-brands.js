/* Reusable brand styling for native canvas objects. No network or file writes.
   Only token-tagged properties and explicitly assigned typography roles change. */
export const BRAND_COLOUR_KEYS=Object.freeze([
  "background","ink","muted","accent","card","border","tone0","tone1","tone2"
]);
const HEX=/^#[0-9a-fA-F]{6}$/;
const token=(kind,raw)=>{
  if(typeof raw!=="string")return null;
  const value=raw.startsWith("tone")?raw:""+raw;
  return kind==="colour"||kind==="fill"||kind==="stroke" ? value : null;
};
export function paletteFromKit(kit){
  if(!kit||!kit.colours||BRAND_COLOUR_KEYS.some(key=>!HEX.test(kit.colours[key]||"")))throw Error("Invalid brand colours");
  if(!Number.isInteger(kit.heading_size)||kit.heading_size<12||kit.heading_size>90||
     !Number.isInteger(kit.body_size)||kit.body_size<12||kit.body_size>90)throw Error("Invalid typography scale");
  return Object.fromEntries(BRAND_COLOUR_KEYS.map(key=>[key,kit.colours[key].toUpperCase()]));
}
export function applyBrandKit(spec,kit){
  const c=paletteFromKit(kit);
  if(spec.layout!=="canvas"||!Array.isArray(spec.elements))throw Error("Brand kits require an editable canvas");
  const previous=JSON.stringify(spec);
  // Every canvas keeps its native base theme for backward-compatible renderer
  // semantics; all six override tokens are validated by the same renderer.
  spec.colours=Object.fromEntries(BRAND_COLOUR_KEYS.slice(0,6).map(key=>[key,c[key]]));
  spec.brand_style={name:kit.name,heading_size:kit.heading_size,body_size:kit.body_size};
  for(const e of spec.elements){
    if(!e||e.locked||e.hidden)continue;
    for(const [property,auto] of [["fill","auto_fill"],["stroke","auto_stroke"],["colour","auto_colour"]]){
      const key=e[auto];
      if(typeof key==="string"&&Object.hasOwn(c,key)){
        e[property]=c[key];
      }
    }
    if(e.type==="text"&&(e.style_role==="heading"||e.style_role==="body")){
      e.font_size=e.style_role==="heading"?kit.heading_size:kit.body_size;
    }
  }
  return JSON.stringify(spec)!==previous;
}
export function brandTextRole(element,role){
  if(!element||element.type!=="text"||element.locked||!["heading","body","manual"].includes(role))return false;
  if(role==="manual")delete element.style_role;
  else element.style_role=role;
  return true;
}

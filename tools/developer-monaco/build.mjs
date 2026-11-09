/* Create deterministic offline ESM Monaco editor and worker assets.
 * Outputs are committed to the project, rather than downloaded at runtime.
 */
import { build } from "esbuild";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dir=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(dir,"../..");
const target=path.join(root,"automoto/web/static/vendor/monaco");
const packageRoot=path.join(dir,"node_modules/monaco-editor");
const pinned="0.57.0";
const meta=JSON.parse(readFileSync(path.join(packageRoot,"package.json"),"utf8"));
if(meta.version!==pinned)throw new Error("Unexpected Monaco version: "+meta.version);
if(!existsSync(path.join(packageRoot,"LICENSE")))throw new Error("Monaco licence absent");
const vs=path.join(packageRoot,"esm/vs");
const input=(part)=>path.join(vs,part);
const entries=[
  {in:path.join(dir,"entry.mjs"),out:"monaco"},
  {in:input("editor/editor.worker.js"),out:"editor.worker"},
  {in:input("language/json/json.worker.js"),out:"json.worker"},
  {in:input("language/css/css.worker.js"),out:"css.worker"},
  {in:input("language/html/html.worker.js"),out:"html.worker"},
  {in:input("language/typescript/ts.worker.js"),out:"ts.worker"}
];
for(const e of entries)if(!existsSync(e.in))throw new Error("Missing Monaco worker: "+e.in);
rmSync(target,{recursive:true,force:true});
mkdirSync(target,{recursive:true});
await build({
  entryPoints:entries,outdir:target,entryNames:"[name]",assetNames:"assets/[name]-[hash]",
  format:"esm",platform:"browser",target:["es2022"],bundle:true,minify:true,
  splitting:false,sourcemap:false,write:true,legalComments:"external",
  loader:{".ttf":"file",".woff":"file",".woff2":"file",".svg":"dataurl"},
  logLevel:"warning"
});
cpSync(path.join(packageRoot,"LICENSE"),path.join(target,"MONACO-LICENSE.txt"));
const required=["monaco.js","monaco.css","editor.worker.js","ts.worker.js",
"json.worker.js","css.worker.js","html.worker.js","MONACO-LICENSE.txt"];
for(const name of required)if(!existsSync(path.join(target,name)))throw new Error("Bundled asset missing: "+name);
const files={};
function scan(folder,prefix=""){
  for(const file of readdirSync(folder,{withFileTypes:true})){
    if(file.name==="manifest.json")continue;
    if(file.isDirectory())scan(path.join(folder,file.name),prefix+file.name+"/");
    else if(file.isFile()){
      const source=path.join(folder,file.name),buf=readFileSync(source);
      files[prefix+file.name]={size:statSync(source).size,sha256:createHash("sha256").update(buf).digest("hex")};
    }
  }
}
scan(target);
writeFileSync(path.join(target,"manifest.json"),JSON.stringify({
  name:"automoto-offline-monaco",version:pinned,format:"esm",
  files:Object.fromEntries(Object.entries(files).sort(([a],[b])=>a.localeCompare(b)))
},null,2)+"\n");
console.log("Vendored Monaco "+pinned+" ("+Object.keys(files).length+" assets), no runtime network dependency.");

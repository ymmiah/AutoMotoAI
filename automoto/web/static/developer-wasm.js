/* V33: WebAssembly source evidence, no execution. */
export function mountDeveloperWasm({api,host,getProject}){
  const root=host.querySelector("#dsWasmRoot");
  root.innerHTML='<section class="ds-php-panel" aria-label="WebAssembly tooling">'+
    '<div class="ds-php-head"><h3>WebAssembly · WAT / WASM / WIT / WASI / Components</h3>'+
    '<span class="ds-readonly">INSPECTION ONLY</span></div>'+
    '<div class="ds-php-body"><p class="ds-footnote">Source fingerprints, WIT/WAT declarations, binary header evidence, WASI risk indicators and installed runtime availability. Does not build, run or validate a module.</p>'+
    '<button id="dsWasmInspect" class="btn sm" type="button" disabled>Inspect WebAssembly</button>'+
    '<p id="dsWasmStatus" role="status" aria-live="polite">Open a local project.</p>'+
    '<pre id="dsWasmResults" class="ds-php-output" tabindex="0"></pre></div></section>';
  const el=id=>root.querySelector("#"+id);
  let busy=false,sequence=0;
  function refresh(){el("dsWasmInspect").disabled=busy||!getProject()?.project;}
  async function inspect(){
    const project=getProject()?.project;if(!project||busy)return;
    busy=true;const id=++sequence;refresh();
    el("dsWasmStatus").textContent="Inspecting without running WebAssembly.";
    try{
      const d=await api("/api/developer/studio/wasm/inspect?"+
        new URLSearchParams({project}));
      if(id!==sequence||getProject()?.project!==project)return;
      el("dsWasmResults").textContent=JSON.stringify(d,null,2);
      el("dsWasmStatus").textContent="Inspection complete. Runtime and sandbox unverified.";
    }catch(e){el("dsWasmStatus").textContent="Inspection refused: "+e.message;}
    finally{busy=false;refresh();}
  }
  el("dsWasmInspect").addEventListener("click",()=>void inspect());
  refresh();
  return {projectChanged(){sequence++;el("dsWasmResults").textContent="";refresh();},
          fileChanged:refresh};
}

/* V43: can this computer run emulators and simulators, what's plugged in, and is signing set up?
   Checking only reads files and runs a few fixed read-only commands. Devices count as ready only
   after the user presses Verify. AutoMoto never starts an emulator or simulator. */
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const BASE="/api/developer/studio/devices";
const STATUS={ready:["Ready","ok"],probably_ready:["Probably ready","ok"],missing:["Not set up","warn"],needs_setup:["Needs setup","warn"],
  needs_permission:["Needs permission","warn"],problem:["Problem","bad"],warning:["Worth fixing","warn"],unsupported_host:["Not possible here","bad"],
  not_verified:["Not verified","warn"],not_checked:["Not checked","idle"],unknown:["Unknown","idle"],none:["Nothing plugged in","idle"]};
const OS={linux:"Linux",macos:"macOS",windows:"Windows"};

export function mountDeveloperDevices({api,host,getProject}){
  const root=host.querySelector("#dsDevicesRoot");
  root.innerHTML='<section class="dsb dsd" aria-label="Devices, emulators and signing">'+
    '<h3 class="dsb-h">Devices, emulators &amp; signing</h3>'+
    '<p class="dsb-hint">Check whether this computer can run Android emulators and the iPhone Simulator, find USB boards, and see if app signing is set up. AutoMoto only looks. It never starts an emulator or changes a device.</p>'+
    '<button id="dsDevicesCheck" class="btn primary" type="button">Check this computer</button>'+
    '<p id="dsDevicesStatus" class="dsb-hint" role="status" aria-live="polite"></p>'+
    '<div id="dsDevicesCards" class="dsd-cards"></div>'+
    '<h4 class="dsd-h">Phones, emulators and simulators</h4>'+
    '<p class="dsb-hint">Start your emulator or plug in your phone first, then find it here. Press Verify to make sure it really answers.</p>'+
    '<button id="dsDevicesFind" class="btn" type="button">Find devices</button>'+
    '<ul id="dsDevicesList" class="dsd-devices" aria-live="polite"></ul>'+
    '<details class="dsb-adv"><summary>Advanced details</summary><pre id="dsDevicesRaw" class="ds-php-output" tabindex="0"></pre></details>'+
    '</section>';
  const $=id=>root.querySelector("#"+id);
  const raw=d=>{$("dsDevicesRaw").textContent=JSON.stringify(d,null,2);};
  const chip=(status)=>{const [t,tone]=STATUS[status]||[status,"idle"];const c=el("span","dsd-chip t-"+tone,t);c.dataset.status=status;return c;};
  function fixLine(item){
    const box=document.createDocumentFragment();
    if(item.fix)box.append(el("p","dsd-meta","What to do: "+item.fix));
    if(item.command){const p=el("p","dsd-meta");const code=el("code","dsd-cmd",item.command);code.dataset.copy=item.command;code.dataset.copyLabel="command";p.append(code);box.append(p);}
    if(item.link){const a=el("a","dsb-link","Guide ↗");a.href=item.link;a.target="_blank";a.rel="noopener noreferrer";const p=el("p","dsd-meta");p.append(a);box.append(p);}
    return box;
  }
  function card(item,key,extra){
    const c=el("article","dsd-card");c.dataset.check=key;
    const head=el("div","dsd-head");head.append(el("b",null,item.title),chip(item.status));c.append(head,el("p",null,item.text));
    if(extra)c.append(extra);
    if(item.image_warning)c.append(el("p","dsd-note t-warn",item.image_warning));
    c.append(fixLine(item));return c;
  }
  async function check(){
    $("dsDevicesCheck").disabled=true;$("dsDevicesStatus").textContent="Checking. Nothing is started.";
    try{
      const project=getProject()?.project;
      const d=await api(BASE+"/diagnose"+(project?"?project="+encodeURIComponent(project):""));raw(d);
      const cards=$("dsDevicesCards");cards.replaceChildren();
      cards.append(el("p","dsd-meta","This computer: "+(OS[d.host.os]||d.host.os)+" on "+d.host.arch+"."));
      cards.append(card(d.virtualization,"virtualization"));
      const a=d.android_emulator;
      const avd=a.virtual_devices?.length?el("p","dsd-meta","Virtual devices: "+a.virtual_devices.join(", ")):null;
      cards.append(card(a,"android_emulator",avd));
      cards.append(card(d.ios_simulator,"ios_simulator"));
      const s=d.serial_hardware;
      const ports=s.ports?.length?el("ul","dsd-ports"):null;
      for(const p of s.ports||[])ports.append(el("li",null,p.port+(p.description?" · "+p.description:"")));
      cards.append(card(s,"serial_hardware",ports));
      for(const [i,item] of d.signing.entries()){
        let extra=null;
        if(item.findings?.length){extra=el("ul","dsd-ports");for(const f of item.findings)extra.append(el("li",null,f.path+" line "+f.line+": "+f.setting+" (value hidden)"));}
        else if(item.files?.length){extra=el("ul","dsd-ports");for(const f of item.files)extra.append(el("li",null,f));}
        cards.append(card(item,"signing-"+i,extra));
      }
      $("dsDevicesStatus").textContent=project?"Checked this computer and the signing setup of "+project.split(/[\\/]/).pop()+".":"Checked this computer. Open a project to also check its signing setup.";
    }catch(e){$("dsDevicesStatus").textContent="Couldn't check: "+e.message;}
    finally{$("dsDevicesCheck").disabled=false;}
  }
  async function find(){
    const list=$("dsDevicesList");$("dsDevicesFind").disabled=true;list.replaceChildren(el("li","dsd-empty","Looking…"));
    try{
      const d=await api(BASE+"/list");raw(d);list.replaceChildren();
      for(const dev of d.devices){
        const li=el("li","dsd-device");li.dataset.device=dev.id;
        const head=el("div","dsd-head");
        head.append(el("b",null,dev.name||dev.id),el("span","dsd-meta",dev.kind==="ios_simulator"?"iPhone Simulator · "+dev.runtime:dev.kind==="android"?"Android · "+dev.id:"iPhone · "+dev.id),
          el("span","dsd-chip t-"+(dev.verified?"ok":"idle"),dev.verified?"Verified":"Seen, not verified"));
        const out=el("div","dsd-result");out.setAttribute("aria-live","polite");
        li.append(head);
        if(dev.kind==="android"||dev.kind==="ios_simulator"){
          const b=el("button","btn sm","Verify");b.type="button";b.onclick=()=>void verify(dev,b,out,head.lastChild);li.append(b);
        }else li.append(el("p","dsd-meta","Use Phone control to check an iPhone."));
        li.append(out);list.append(li);
      }
      if(!d.devices.length)list.append(el("li","dsd-empty","No devices found. Start an emulator or plug in a phone with USB debugging on, then try again."));
      for(const msg of [d.android_error,d.simulator_error].filter(Boolean))list.append(el("li","dsd-empty",msg));
    }catch(e){list.replaceChildren(el("li","dsd-note t-bad","Couldn't look for devices: "+e.message));}
    finally{$("dsDevicesFind").disabled=false;}
  }
  async function verify(dev,button,out,badge){
    button.disabled=true;out.replaceChildren(el("p","dsb-hint","Asking the device to answer…"));
    try{
      const r=await api(BASE+"/verify",{kind:dev.kind,id:dev.id});raw(r);
      const box=el("div","dsd-outcome t-"+(r.verified?"ok":"warn"));box.append(el("b",null,r.verified?"Verified":"Not ready yet"),el("p",null,r.text));
      box.append(fixLine(r));out.replaceChildren(box);
      badge.className="dsd-chip t-"+(r.verified?"ok":"warn");badge.textContent=r.verified?"Verified":"Not ready";
    }catch(e){out.replaceChildren(el("p","dsd-note t-bad",e.message));}
    finally{button.disabled=false;}
  }
  $("dsDevicesCheck").onclick=()=>void check();
  $("dsDevicesFind").onclick=()=>void find();
  return {projectChanged(){$("dsDevicesCards").replaceChildren();$("dsDevicesStatus").textContent="";}};
}

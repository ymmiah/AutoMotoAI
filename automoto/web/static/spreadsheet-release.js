/* V8 release and recovery centre. No destructive restore, external upload or publication.
   Backend owns all validation and source paths. Dynamic content is always text. */
export function mountSpreadsheetRelease({host,api,status}){
  host.innerHTML=`
    <div class="sr-shell">
      <header class="sr-hero"><div><span class="sr-kicker">AUTOMOTO AI · RELEASE ASSURANCE · V8</span>
        <h3>Recovery & release readiness</h3>
        <p>Protect private business records with bounded, verifiable local backups and recover independent copies without overwriting originals.</p></div>
        <button type="button" class="btn" id="srRefresh">Refresh checks</button>
      </header>
      <p class="sr-disclosure" role="note"><strong>Development build, not a certified release.</strong>
        Archive files are not encrypted or externally signed; store downloaded copies securely.
        A successful hash comparison is not proof against someone who can replace the archive and its checksum.
        Restoring never replaces the active workflow audit database, posts transactions, sends invoices or publishes this application.</p>
      <div class="sr-columns">
        <section class="sr-panel" aria-labelledby="srReadinessTitle">
          <div class="sr-heading"><h4 id="srReadinessTitle">Release gates</h4><span id="srReleaseStatus">Not assessed</span></div>
          <p class="sr-muted">Readiness is deliberately blocked until manual platform, recovery, security and accessibility checks are completed.</p>
          <div id="srChecks" class="sr-checks" role="list" aria-live="polite"></div>
        </section>
        <section class="sr-panel" aria-labelledby="srBackupTitle">
          <h4 id="srBackupTitle">Private archive</h4>
          <p class="sr-muted">Create an offline ZIP containing supported saved spreadsheets, basic invoices, commercial documents, customer contacts, financial records and a consistent copy of the V7 audit database if present.</p>
          <button type="button" class="btn primary" id="srCreate">Create private recovery archive</button>
          <label for="srBackups">Previously created archives
            <select class="input" id="srBackups"><option value="">Choose an archive</option></select>
          </label>
          <div class="sr-actions">
            <button type="button" class="btn" id="srVerify">Verify selected archive</button>
            <a class="btn" id="srDownload" hidden>Download ZIP</a>
          </div>
          <div id="srArchiveInfo" class="sr-info" aria-live="polite">No archive selected.</div>
        </section>
      </div>
      <section class="sr-panel" aria-labelledby="srRestoreTitle">
        <h4 id="srRestoreTitle">Non-destructive recovery drill</h4>
        <p class="sr-muted">Recovery creates brand-new saved record files with new random filenames.
          The original files remain unchanged, and archived audit evidence is placed in a separate recovery folder — never activated as current approvals.
          Restore is not a substitute for an independently tested off-device backup.</p>
        <label for="srAcknowledgement">Type <strong>RESTORE COPIES</strong> to confirm
          <input class="input" id="srAcknowledgement" placeholder="RESTORE COPIES" autocomplete="off" spellcheck="false" maxlength="14" />
        </label>
        <label class="sr-confirm"><input id="srNoOverwrite" type="checkbox">
          I understand this creates new copies only and does not replace original data or the active workflow audit.</label>
        <div class="sr-actions"><button type="button" class="btn" id="srRestore">Verify and restore independent copies</button></div>
        <div id="srRestoreResult" class="sr-info" aria-live="polite"></div>
      </section>
      <p class="sr-status" id="srStatus" role="status" aria-live="polite">No backup or restore action has been performed.</p>
    </div>`;
  const el=id=>host.querySelector("#"+id);
  let backups=[];
  function message(text,error=false){
    el("srStatus").textContent=text;
    el("srStatus").classList.toggle("sr-error",error);
    if(error)status(text,true);
  }
  function selected(){
    return backups.find(item=>item.path===el("srBackups").value)||null;
  }
  function archiveStatus(){
    const file=selected(),download=el("srDownload");
    download.hidden=!file;
    if(file){
      download.href="/api/files/download?path="+encodeURIComponent(file.path);
      download.textContent="Download backup ZIP";
      download.setAttribute("download","");
      el("srArchiveInfo").textContent=file.path+" · "+file.bytes+" bytes · SHA-256 "+file.sha256;
    }else{
      download.removeAttribute("href");el("srArchiveInfo").textContent="No archive selected.";
    }
  }
  function showReadiness(report){
    el("srReleaseStatus").textContent=report.release_ready?"Ready":"Release blocked";
    const target=el("srChecks");target.replaceChildren();
    const descriptions={
      workspace:"Private workspace",workflow_audit:"Review audit integrity",
      backup_available:"Private backup present",
      native_installer_manual:"Installed desktop acceptance",
      offline_model_manual:"Offline local-model acceptance",
      accessibility_manual:"Keyboard and screen-reader review",
      security_review_manual:"Threat model and vulnerability review",
      restore_drill_manual:"Recovery drill and off-device evidence"
    };
    for(const [key,grade] of Object.entries(report.checks||{})){
      const item=document.createElement("div");item.className="sr-check";item.setAttribute("role","listitem");
      const name=document.createElement("span");name.textContent=descriptions[key]||key.replaceAll("_"," ");
      const state=document.createElement("strong");state.textContent=String(grade).replaceAll("_"," ");
      state.className=grade==="pass"||grade==="verified"?"sr-pass":"sr-pending";
      item.append(name,state);target.append(item);
    }
  }
  async function refresh(preferred){
    const [checks,list]=await Promise.all([
      api("/api/spreadsheets/release/readiness"),
      api("/api/spreadsheets/release/list")
    ]);
    if(!host.isConnected)return;
    showReadiness(checks);
    backups=list.backups||[];
    const chooser=el("srBackups"),current=preferred||chooser.value;
    chooser.replaceChildren();
    const empty=document.createElement("option");empty.value="";empty.textContent="Choose an archive";chooser.append(empty);
    for(const item of backups){
      const option=document.createElement("option");
      option.value=item.path;option.textContent=item.path.split("/").pop()+" · "+item.bytes+" bytes";
      chooser.append(option);
    }
    if(backups.some(x=>x.path===current))chooser.value=current;
    archiveStatus();
  }
  el("srBackups").onchange=()=>{archiveStatus();el("srRestoreResult").replaceChildren();};
  el("srRefresh").onclick=async()=>{
    try{await refresh();message("Release status and private archives refreshed.");}
    catch(error){message("Could not read release checks: "+error.message,true);}
  };
  el("srCreate").onclick=async()=>{
    if(!window.confirm("Create an unencrypted private ZIP recovery archive of supported saved records and optional audit evidence? No originals will change."))return;
    try{
      message("Creating a bounded, offline recovery archive…");
      const result=await api("/api/spreadsheets/release/create",{});
      await refresh(result.path);
      message("Archive created: "+result.records+" saved record(s), original data unchanged. Download it and protect it offline.");
    }catch(error){message("Backup failed: "+error.message,true);}
  };
  el("srVerify").onclick=async()=>{
    const backup=selected();
    if(!backup){message("Select an archive to verify.",true);return;}
    try{
      message("Checking archive contents and source file hashes…");
      const result=await api("/api/spreadsheets/release/verify",{path:backup.path,sha256:backup.sha256});
      el("srArchiveInfo").textContent="Integrity verified · "+result.records+
        " saved record(s) · workflow history "+(result.workflow_history_included?"included":"not present")+
        " · created "+result.created_at+". Not externally signed or encrypted.";
      message("Archive contents match manifest and saved SHA-256. No records changed.");
    }catch(error){message("Archive integrity failed: "+error.message,true);}
  };
  el("srRestore").onclick=async()=>{
    const backup=selected();
    if(!backup){message("Select a verified archive.",true);return;}
    if(el("srAcknowledgement").value.trim()!=="RESTORE COPIES"||!el("srNoOverwrite").checked){
      message("Enter RESTORE COPIES and confirm new-copy recovery before continuing.",true);return;
    }
    if(!window.confirm("Restore only new saved record copies from this archive? This will NOT overwrite originals or replace active audit history."))return;
    try{
      message("Rechecking archive and restoring independent draft copies…");
      const result=await api("/api/spreadsheets/release/restore",{
        path:backup.path,sha256:backup.sha256,
        acknowledgement:"RESTORE COPIES",confirm_no_overwrite:true
      });
      const panel=el("srRestoreResult");panel.replaceChildren();
      const first=document.createElement("strong");
      first.textContent=result.records+" private record(s) recovered without overwriting originals.";
      panel.append(first);
      if(result.archived_workflow_evidence){
        const info=document.createElement("p");info.textContent=
          "Inactive workflow evidence: "+result.archived_workflow_evidence;
        panel.append(info);
      }
      const list=document.createElement("ul");
      for(const file of result.restored||[]){
        const item=document.createElement("li");
        item.textContent=file.original+" → "+file.recovered;list.append(item);
      }
      panel.append(list);
      el("srAcknowledgement").value="";el("srNoOverwrite").checked=false;
      await refresh(backup.path);
      message("Recovery completed. Originals, workflow approvals and financial entries remain unchanged.");
    }catch(error){message("Restore rejected: "+error.message,true);}
  };
  refresh().catch(error=>message("Release checks unavailable: "+error.message,true));
  return {refresh};
}

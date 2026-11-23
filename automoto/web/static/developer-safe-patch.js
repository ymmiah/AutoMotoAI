/* V51: explicit, single-file patch review. Never invokes the AI or a shell.
   Source bytes are saved only by the server's SHA-checked editor after Apply. */

const make=(tag,cls,text)=>{
  const node=document.createElement(tag);
  if(cls)node.className=cls;
  if(text!=null)node.textContent=String(text);
  return node;
};

export function mountDeveloperSafePatch({api,host,getProject,editor,status}){
  const box=host.querySelector("#dsPatchRoot");
  if(!box)return;
  box.classList.add("dsp");
  box.setAttribute("aria-label","Review and undo a small code patch");
  box.append(make("h3",null,"Safe patch"),make("p","dsp-intro",
    "Change one exact piece of an existing source file. Preview the diff, then choose Apply or Dismiss. Undo is available after applying, unless the file changes again."));

  const form=make("form","dsp-form");
  const pathLabel=make("label",null,"Project-relative file path");
  const path=make("input","input");
  path.name="path";path.required=true;path.maxLength=1024;path.placeholder="src/example.py";
  const useCurrent=make("button","btn sm","Use open file");useCurrent.type="button";
  useCurrent.onclick=()=>{
    const file=editor?.currentFile?.();
    if(file?.path){path.value=file.path;notice("Using "+file.path+".");}
    else notice("Open a source file in the editor first.",true);
  };
  pathLabel.append(path,useCurrent);
  const oldLabel=make("label",null,"Find this exact code (one occurrence)");
  const oldText=make("textarea","input");oldText.rows=4;oldText.maxLength=8000;oldText.required=true;
  oldText.spellcheck=false;oldLabel.append(oldText);
  const newLabel=make("label",null,"Replace with");
  const newText=make("textarea","input");newText.rows=4;newText.maxLength=8000;
  newText.spellcheck=false;newLabel.append(newText);
  const preview=make("button","btn sm primary","Preview patch");preview.type="submit";
  form.append(pathLabel,oldLabel,newLabel,preview);
  box.append(form);

  const result=make("section","dsp-result");result.hidden=true;
  const resultTitle=make("strong",null,"Patch preview");
  const diff=make("pre","ds-diff dsp-diff");
  diff.setAttribute("aria-label","Source diff; minus removes, plus adds");
  const controls=make("div","dsp-actions");
  const apply=make("button","btn sm primary","Apply patch");apply.type="button";
  const dismiss=make("button","btn sm","Dismiss");dismiss.type="button";
  controls.append(apply,dismiss);
  const undo=make("button","btn sm","Undo applied patch");undo.type="button";undo.hidden=true;
  const message=make("p","dsp-message");message.setAttribute("role","status");message.setAttribute("aria-live","polite");
  result.append(resultTitle,diff,controls,undo);
  box.append(result,message);
  let planned=null,undoRecord=null,busy=false;
  const notice=(txt,bad=false)=>{message.textContent=txt;message.classList.toggle("dsp-bad",bad);status?.(txt,bad);};
  const project=()=>getProject()?.project||null;
  const valid=record=>record&&getProject()?.trusted&&record.project===project()&&record.path===path.value.trim();
  const clear=()=>{planned=null;result.hidden=true;apply.disabled=false;undo.hidden=true;};
  const lock=(value)=>{busy=value;preview.disabled=value;apply.disabled=value;undo.disabled=value;};

  form.addEventListener("submit",async e=>{
    e.preventDefault();if(busy)return;
    clear();undoRecord=null;
    const p=project(),target=path.value.trim();
    if(!p||!getProject()?.trusted){notice("Open and trust a project before previewing.",true);return;}
    lock(true);
    try{
      const source=await api("/api/developer/studio/file?"+new URLSearchParams({
        project:p,path:target,encoding:"auto"
      }));
      if(project()!==p||path.value.trim()!==target)throw Error("Project or file changed during preview.");
      const patch=await api("/api/developer/studio/patch/preview",{
        project:p,path:target,expected_sha256:source.sha256,
        old_fragment:oldText.value,new_fragment:newText.value
      });
      planned={project:p,path:target,token:patch.token};
      diff.textContent=patch.diff;
      resultTitle.textContent="Preview · "+patch.changed_lines+" changed lines · "+
        (patch.syntax_checked?"Python syntax checked":"No syntax parser for this file");
      result.hidden=false;
      notice("Preview ready. Nothing has been written to disk.");
    }catch(err){notice("Patch refused: "+String(err?.message||"Unable to preview"),true);}
    finally{lock(false);}
  });
  dismiss.onclick=()=>{clear();notice("Patch dismissed. File unchanged.");};
  apply.onclick=async()=>{
    if(busy||!valid(planned)){notice("Plan is stale or project changed. Preview again.",true);return;}
    if(!window.confirm("Apply this exact patch to "+planned.path+"? The source must still match the preview."))return;
    lock(true);
    try{
      const r=await api("/api/developer/studio/patch/apply",{...planned,confirmed:true});
      undoRecord={project:planned.project,path:planned.path,token:r.undo_id};
      planned=null;apply.disabled=true;undo.hidden=false;
      notice("Patch applied. Use Undo if needed; no commands or shares were run.");
    }catch(err){notice("Apply blocked: "+String(err?.message||"Unknown error")+". Preview again.",true);planned=null;}
    finally{lock(false);apply.disabled=!!(!planned);};
  };
  undo.onclick=async()=>{
    if(busy||!valid(undoRecord)){notice("Project or file changed. Undo is blocked.",true);return;}
    if(!window.confirm("Undo the exact patch to "+undoRecord.path+"? This is refused if the file changed again."))return;
    lock(true);
    try{
      await api("/api/developer/studio/patch/undo",{...undoRecord,confirmed:true});
      notice("Patch undone. The original source is restored.");
      clear();undoRecord=null;
    }catch(err){notice("Undo blocked: "+String(err?.message||"Unknown error")+". No other changes were overwritten.",true);}
    finally{lock(false);}
  };
  return {reset(){clear();undoRecord=null;path.value="";oldText.value="";newText.value="";message.textContent="";}};
}

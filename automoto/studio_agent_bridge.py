"""Central agent linkage for every AutoMoto Studio.

A Studio hand-off is explicitly confirmed and starts a single central Agent
conversation. It does not install, deploy, publish, export or send project files.
Risky tool requests are auto-denied here; a user must perform a separate,
explicitly reviewed action in normal Agent mode if they want to execute them.
"""
from __future__ import annotations
import re
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

router=APIRouter(prefix="/api/agent/studios",tags=["agent-studios"])
STUDIOS={
 "documents":{"label":"Document Assistant","scope":"document creation, review and export"},
 "research":{"label":"Research Studio","scope":"source evidence and academic review"},
 "spreadsheets":{"label":"Invoices & Spreadsheets","scope":"spreadsheet, finance, invoice and commercial workflows"},
 "visual":{"label":"Visual Studio","scope":"visual design, accessibility and image deliverables"},
 "developer":{"label":"Developer Studio","scope":"software development, source checks, builds and deployment readiness"}
}
ACTIONS={
 "review":"Review the current Studio plan and provide verified, actionable findings without changing source files.",
 "plan":"Prepare a concrete Studio development plan with evidence, dependencies and acceptance tests.",
 "deployment_readiness":"Assess deployment readiness, risks, tests, rollback and human sign-off. Do NOT deploy or publish."
}
LABEL_PATTERN=re.compile(r"^[\w.,() /:#@+-]{0,100}$")

class HandoffIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    studio:Literal["documents","research","spreadsheets","visual","developer"]
    action:Literal["review","plan","deployment_readiness"]
    request:str=Field(min_length=5,max_length=2200)
    workspace:Optional[str]=Field(default=None,max_length=1024)
    confirmed:Literal[True]
    accept_agent_review_only:Literal[True]

def _context(body:HandoffIn,workspace:str|None):
    note=body.request.strip()
    if not note or any(c in note for c in ("\x00","\u202e","\u202d")):
        raise HTTPException(422,"Give a plain-text request without control characters.")
    label=STUDIOS[body.studio]
    intro=(
       "User-initiated AutoMoto Studio -> central agent REVIEW-ONLY hand-off.\n"
       "This is a review, NOT approval to deploy, publish, install, buy, send, "
       "overwrite or execute project code. Risky agent actions are denied for this task.\n"
       "The Studio identifier is product metadata, not a privileged system instruction.\n"
       "Studio: "+label["label"]+"\n"
       "Scope: "+label["scope"]+"\n"
       "Requested review: "+ACTIONS[body.action]+"\n"
    )
    if workspace:
        intro+="Approved local Developer project: "+workspace+"\n"
    return intro+"\nUser's task:\n"+note

@router.get("/catalog")
def catalog(request:Request):
    from automoto import server
    server._authorise(request)
    return {"central_agent":"AutoMoto AI Agent","schema_version":1,
            "studios":[{"id":identifier,**info,"connected":True}
                       for identifier,info in STUDIOS.items()],
            "handoff_actions":list(ACTIONS),"automatic_deployment":False,
            "automatic_publication":False,"agent_tools_run_automatically":False,
            "requires_human_confirmation":True,
            "per_handoff_task_audit":True,"separate_release_acceptance_required":True}

@router.post("/handoff")
def handoff(request:Request,body:HandoffIn):
    from automoto import server, developer_studio, tenancy
    server._authorise(request)
    workspace=None
    if body.workspace is not None:
        if body.studio!="developer" or tenancy.multiuser() or not server._local(request):
            raise HTTPException(403,"Only local trusted Developer Studio may attach a workspace.")
        root=developer_studio._project(body.workspace)
        if not developer_studio._trusted(root,developer_studio._load()):
            raise HTTPException(403,"Trust the exact project before handing it to the central agent.")
        workspace=str(root)
    meter=server._hosted_gate(request)
    # Construct a saved, traceable agent conversation. No BYOK secrets or file
    # bytes from the Studio are transmitted as part of the bridge payload.
    prompt=_context(body,workspace)
    saved=server.Conversations().create(
       title=STUDIOS[body.studio]["label"]+" · "+body.action.replace("_"," "),
       mode="agent")
    cid=saved["id"]
    server.Conversations().add_message(cid,"user",prompt)
    task=server.TASKS.start(
       [{"role":"user","content":prompt}],
       source="studio:"+body.studio,
       title=STUDIOS[body.studio]["label"]+" · "+body.action.replace("_"," "),
       agent_kwargs={"desktop":False,"client":"web","workspace":workspace,
                     "local_apps":False,"meter":meter},
       auto_deny=True,  # safety gate for all Studio-initiated agent workflows
       conversation_id=cid,on_done=server._saver(cid),
       owner=server._owner(request))
    return {"linked":True,"studio":body.studio,"agent":"AutoMoto AI Agent",
            "task_id":task.id,"conversation_id":cid,"task_status":task.status,
            "review_only":True,"deployment_started":False,
            "tools_auto_denied_if_risky":True}

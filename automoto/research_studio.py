"""Research Studio V1 — private, evidence-first projects over existing document retrieval.

Not a new crawler or AI source generator. Reuses the Document Assistant's
checksum-pinned, bounded local extraction; only verified source excerpts are
persisted. No browsing, external model, source-file modification or citations
constructed from guessed bibliographic details.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automoto import document_research, document_workspace
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/research/studio", tags=["research-studio"])
PROJECT_FILE = re.compile(r"^research-[0-9a-f]{24}\.research\.json$")
MAX_PROJECT = 65_000
MAX_PROJECTS = 150
SCHEMA = "research-studio-v1"
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=3, max_length=120)
    question: str = Field(..., min_length=3, max_length=320)
    notes: str = Field("", max_length=1400)
    sources: list[document_research.PinnedSource] = Field(..., min_length=1, max_length=5)
    mode: Literal["evidence", "outline"] = "evidence"

    @model_validator(mode="after")
    def valid_project(self):
        if (not self.title.strip() or not self.question.strip()
                or CONTROL.search(self.title) or CONTROL.search(self.question)
                or CONTROL.search(self.notes)):
            raise ValueError("Research title, question and notes must be printable.")
        if len({source.path for source in self.sources}) != len(self.sources):
            raise ValueError("Research sources must be distinct.")
        return self


def _folder(create: bool = False) -> Path:
    root = document_workspace._root()
    parent = root / "artifacts"
    folder = parent / "research"
    if parent.is_symlink() or folder.is_symlink():
        raise HTTPException(403, "Research storage may not be a symlink.")
    if create:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if folder.exists() and (not folder.is_dir() or not folder.resolve().is_relative_to(root)):
        raise HTTPException(403, "Research storage must remain in your private workspace.")
    return folder


def _file(raw: str) -> Path:
    prefix = "artifacts/research/"
    if not isinstance(raw, str) or len(raw) > 110 or not raw.startswith(prefix):
        raise HTTPException(403, "Only saved private research projects can be opened.")
    name = raw[len(prefix):]
    if not PROJECT_FILE.fullmatch(name):
        raise HTTPException(403, "Invalid saved research project name.")
    file = _folder() / name
    if file.is_symlink() or not file.is_file():
        raise HTTPException(404, "Saved research project not found.")
    return file


def _read(path: Path) -> dict:
    if path.stat().st_size > MAX_PROJECT:
        raise HTTPException(413, "Saved research project exceeds the safe limit.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise ValueError("Unsupported research schema.")
        project = ProjectIn.model_validate(data["project"])
        evidence = data["result"]
        if not isinstance(evidence, dict) or not isinstance(evidence.get("evidence"), list):
            raise ValueError("Research evidence is malformed.")
        if evidence.get("source_count") != len(project.sources) or not evidence.get("read_only"):
            raise ValueError("Research source count is inconsistent.")
        return data
    except (UnicodeError, OSError, ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(422, "Saved research project is corrupt.") from None


def _status(project: ProjectIn) -> list[dict]:
    sources = []
    for src in project.sources:
        try:
            path = document_research._source_path(src.path)
            state = ("current" if document_workspace._sha(path) == src.sha256
                     else "changed")
        except (HTTPException, OSError, UnicodeError):
            state = "missing_or_unavailable"
        sources.append({"path": src.path, "sha256": src.sha256, "status": state})
    return sources


def _evaluate(project: ProjectIn, request: Request) -> dict:
    # Reuse the existing source extraction, source hashing, excerpt positioning,
    # lexical retrieval and no-invented-citation safeguards verbatim.
    query = document_research.ResearchIn(
        query=project.question, sources=project.sources, mode=project.mode)
    return document_research.query_documents(query, request)


@router.get("/sources")
def sources(request: Request):
    _auth(request)
    listing = document_workspace.list_documents(request)["documents"]
    return {"sources": [
        {"name": item["name"], "path": item["path"], "kind": item["kind"],
         "bytes": item["size"]}
        for item in listing
        if (item["path"].endswith(".document.json")
            or item["path"].lower().endswith((".txt", ".md", ".docx", ".pdf")))
    ], "supported": ["PDF", "DOCX", "Markdown", "TXT", "native Document Assistant drafts"],
       "uploads_read_only": True, "internet_used": False}


@router.get("/list")
def list_projects(request: Request):
    _auth(request)
    folder = _folder()
    if not folder.is_dir():
        return {"projects": []}
    projects = []
    for file in sorted(folder.iterdir(), key=lambda p: p.name, reverse=True):
        if not PROJECT_FILE.fullmatch(file.name) or file.is_symlink() or not file.is_file():
            continue
        try:
            data = _read(file)
        except HTTPException:
            continue
        projects.append({
            "path": "artifacts/research/" + file.name, "title": data["project"]["title"],
            "question": data["project"]["question"],
            "created_at": data["created_at"],
            "source_count": len(data["project"]["sources"]),
            "evidence_count": len(data["result"]["evidence"]),
        })
        if len(projects) == 100:
            break
    return {"projects": projects}


@router.get("/open")
def open_project(request: Request, path: str):
    _auth(request)
    file = _file(path)
    data = _read(file)
    project = ProjectIn.model_validate(data["project"])
    return {
        "path": path, "project": project.model_dump(mode="json"),
        "result": data["result"], "saved_at": data["created_at"],
        "source_status": _status(project), "source_files_modified": False,
        "historical_evidence": True,
        "warning": "This is saved evidence, not verified current fact. Rerun retrieval if sources have changed.",
    }


@router.post("/query")
def query_project(body: ProjectIn, request: Request):
    _auth(request)
    report = _evaluate(body, request)
    return {
        "project": body.model_dump(mode="json"), "result": report,
        "source_status": _status(body), "saved": False,
        "no_cloud_model": True, "source_files_modified": False,
    }


@router.post("/save")
def save_project(body: ProjectIn, request: Request):
    _auth(request)
    folder = _folder(create=True)
    count = sum(1 for item in folder.iterdir()
                if item.is_file() and not item.is_symlink()
                and PROJECT_FILE.fullmatch(item.name))
    if count >= MAX_PROJECTS:
        raise HTTPException(413, "Research workspace limit reached (150 saved projects).")
    report = _evaluate(body, request)  # recompute; never accept client-written evidence
    payload = {
        "schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": body.model_dump(mode="json"),
        "result": report,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_PROJECT:
        raise HTTPException(413, "Research evidence exceeds private project limits.")
    target = folder / f"research-{secrets.token_hex(12)}.research.json"
    document_workspace._atomic_file(target, raw)
    return {
        "path": "artifacts/research/" + target.name,
        "sha256": hashlib.sha256(raw).hexdigest(), "source_count": len(body.sources),
        "evidence_count": len(report["evidence"]), "create_only": True,
        "applied": False, "verified_citations_only": True,
        "warning": "Evidence excerpts are extracted text, not independently verified facts.",
    }

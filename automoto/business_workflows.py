"""V7 local workflow reviews and hash-chained append-only audit events.

Never changes a source record, marks invoices issued, posts financial activity,
sends communications, executes tools or authorises payments. Hosted accounts
operate only within their own existing tenant workspace. A cryptographic hash
chain provides detectable *in-place* log alteration, not external notarisation.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automoto import tenancy
from automoto.document_workspace import _root
from automoto.spreadsheet_workspace import _storage
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/spreadsheets/workflows", tags=["business-workflows"])
NAME = re.compile(r"^[a-z0-9-]{1,48}-[0-9a-f]{12}\.(sheet|commercial|finance)\.json$")
ID = re.compile(r"^[0-9a-f]{24}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
ROOT_HASH = "0" * 64
LIMIT_BYTES = 850_000
MAX_REQUESTS = 500
SOURCE_SCHEMAS = {"sheet": "spreadsheet-v1", "commercial": "commercial-v4",
                  "finance": "finance-v5"}
BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class CreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str = Field(..., min_length=28, max_length=300)
    source_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    related_path: str = Field(..., min_length=28, max_length=300)
    related_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    purpose: Literal["evidence_handoff", "business_review", "cash_reconciliation_review"]
    note: str = Field(..., min_length=10, max_length=650)
    confirm_review_only: Literal[True]

    @model_validator(mode="after")
    def validate_note(self):
        if BAD.search(self.note) or not self.note.strip() or self.source_path == self.related_path:
            raise ValueError("Notes must be printable and source records must be different.")
        return self


class DecideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: str = Field(..., pattern=r"^[0-9a-f]{24}$")
    expected_event_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    action: Literal["approve", "reject", "cancel"]
    reason: str = Field(..., min_length=5, max_length=500)
    confirm_review_only: Literal[True]

    @model_validator(mode="after")
    def validate_reason(self):
        if BAD.search(self.reason) or not self.reason.strip():
            raise ValueError("A meaningful printable decision reason is required.")
        return self


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _actor(request: Request) -> tuple[str, str]:
    """Authentication is already checked. Never trust a client-supplied role."""
    if tenancy.multiuser():
        user = getattr(request.state, "user", None)
        if user is None or getattr(user, "role", "") not in ("user", "admin"):
            raise HTTPException(403, "Authenticated hosted identity required.")
        return str(user.id), user.role
    return "local-owner", "admin"


def _can_decide(actor_id: str, role: str, requester: str, action: str) -> bool:
    if action == "cancel":
        return actor_id == requester
    return role == "admin" and action in ("approve", "reject")


def _store(create: bool = False) -> Path:
    root = _root()
    parent = root / "artifacts"
    directory = parent / "workflows"
    if parent.is_symlink() or directory.is_symlink():
        raise HTTPException(403, "Workflow storage must not use symlinks.")
    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.exists() and (not directory.is_dir() or not directory.resolve().is_relative_to(root)):
        raise HTTPException(403, "Workflow storage must remain private.")
    path = directory / "workflow-events-v7.sqlite3"
    if path.is_symlink() or path.exists() and not path.is_file():
        raise HTTPException(403, "Invalid workflow database path.")
    return path


def _connect() -> sqlite3.Connection:
    path = _store(create=True)
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS workflows (
          id TEXT PRIMARY KEY,
          purpose TEXT NOT NULL,
          source_path TEXT NOT NULL, source_sha256 TEXT NOT NULL,
          related_path TEXT NOT NULL, related_sha256 TEXT NOT NULL,
          note TEXT NOT NULL, requester TEXT NOT NULL, requester_role TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          workflow_id TEXT NOT NULL REFERENCES workflows(id),
          action TEXT NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL,
          note TEXT NOT NULL, created_at TEXT NOT NULL,
          previous_hash TEXT NOT NULL, request_digest TEXT NOT NULL, event_hash TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_workflow ON events(workflow_id, id);
    """)
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows ACLs are managed by the desktop installation.
    return db


def _source(raw: str) -> dict:
    prefix = "artifacts/spreadsheets/"
    if not isinstance(raw, str) or not raw.startswith(prefix) or len(raw) > 300:
        raise HTTPException(403, "Only private saved spreadsheet/business records are supported.")
    name = raw[len(prefix):]
    found = NAME.fullmatch(name)
    if not found:
        raise HTTPException(403, "Unsupported private saved record name.")
    path = _storage() / name
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "Referenced saved record was not found.")
    if not path.resolve().is_relative_to(_root()):
        raise HTTPException(403, "Referenced file escapes this workspace.")
    if path.stat().st_size > LIMIT_BYTES:
        raise HTTPException(413, "Referenced record exceeds safe bounds.")
    content = path.read_bytes()
    try:
        doc = json.loads(content)
        if not isinstance(doc, dict) or doc.get("schema") != SOURCE_SCHEMAS[found.group(1)] \
                or not isinstance(doc.get("data"), dict):
            raise ValueError("Unexpected record schema")
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise HTTPException(422, "Referenced private record is invalid.") from None
    return {"path": raw, "kind": found.group(1),
            "sha256": hashlib.sha256(content).hexdigest(), "name": name}


def _request_digest(row: sqlite3.Row) -> str:
    """Bind original evidence paths, fingerprints, reviewer and reason to every event."""
    keys = ("id", "purpose", "source_path", "source_sha256", "related_path",
            "related_sha256", "note", "requester", "requester_role", "created_at")
    record = {key: row[key] for key in keys}
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _chain_fields(workflow_id: str, action: str, actor: str, actor_role: str,
                  note: str, created_at: str, previous_hash: str,
                  request_digest: str) -> dict:
    return {"workflow_id": workflow_id, "action": action, "actor": actor,
            "actor_role": actor_role, "note": note, "created_at": created_at,
            "previous_hash": previous_hash, "request_digest": request_digest}


def _hash_event(fields: dict) -> str:
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _verify(db: sqlite3.Connection) -> dict:
    expected = ROOT_HASH
    count = 0
    bindings = {row["id"]: _request_digest(row) for row in db.execute("SELECT * FROM workflows")}
    for record in db.execute("SELECT workflow_id,action,actor,actor_role,note,created_at,"
                             "previous_hash,request_digest,event_hash FROM events ORDER BY id"):
        fields = _chain_fields(*[record[key] for key in
            ("workflow_id", "action", "actor", "actor_role", "note",
             "created_at", "previous_hash", "request_digest")])
        if (record["request_digest"] != bindings.get(record["workflow_id"])
                or record["previous_hash"] != expected
                or _hash_event(fields) != record["event_hash"]):
            raise HTTPException(409, "Workflow audit history failed the integrity check.")
        expected = record["event_hash"]
        count += 1
    total = db.execute("SELECT COUNT(*) FROM workflows").fetchone()[0]
    opened = db.execute("SELECT COUNT(*) FROM events WHERE action='requested'").fetchone()[0]
    if total != opened:
        raise HTTPException(409, "Workflow requests and audit events are inconsistent.")
    for row in db.execute("SELECT id FROM workflows"):
        events = db.execute("SELECT action FROM events WHERE workflow_id=? ORDER BY id",
                            (row["id"],)).fetchall()
        actions = [e["action"] for e in events]
        if not actions or actions[0] != "requested" or len(actions) > 2 \
                or any(a not in ("approved", "rejected", "cancelled") for a in actions[1:]):
            raise HTTPException(409, "Workflow event sequence is invalid.")
    return {"valid": True, "event_count": count, "workflows": total,
            "latest_event_hash": expected, "verification": "SHA-256 hash chain, not externally notarised"}


def _append(db: sqlite3.Connection, wf_id: str, action: str, actor: str,
            role: str, note: str) -> str:
    last = db.execute("SELECT event_hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
    previous = last["event_hash"] if last else ROOT_HASH
    request = db.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    if request is None:
        raise HTTPException(409, "Workflow request disappeared before audit entry.")
    binding = _request_digest(request)
    fields = _chain_fields(wf_id, action, actor, role, note, _now(), previous, binding)
    digest = _hash_event(fields)
    db.execute("INSERT INTO events(workflow_id,action,actor,actor_role,note,created_at,previous_hash,request_digest,event_hash)"
               " VALUES(?,?,?,?,?,?,?,?,?)",
               (wf_id, action, actor, role, note, fields["created_at"], previous, binding, digest))
    return digest


def _detail(db: sqlite3.Connection, wf_id: str) -> dict:
    if not ID.fullmatch(wf_id):
        raise HTTPException(422, "Invalid workflow identifier.")
    row = db.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Workflow not found.")
    events = [dict(e) for e in db.execute(
        "SELECT action, actor, actor_role, note, created_at, previous_hash, request_digest, event_hash "
        "FROM events WHERE workflow_id=? ORDER BY id", (wf_id,))]
    state = "pending" if len(events) == 1 else events[-1]["action"]
    return {**dict(row), "status": state, "events": events,
            "last_event_hash": events[-1]["event_hash"], "approved": state == "approved",
            "effect": "Review acknowledgement only; no source mutations or financial posting."}


@router.get("/sources")
def sources(request: Request):
    _auth(request)
    folder = _storage()
    found = []
    if folder.is_dir():
        for path in sorted(folder.iterdir(), key=lambda p: p.name, reverse=True):
            if path.is_symlink() or not path.is_file() or not NAME.fullmatch(path.name):
                continue
            if len(found) >= 150:
                break
            try:
                found.append(_source(path.relative_to(_root()).as_posix()))
            except (HTTPException, OSError, UnicodeError):
                continue
    return {"sources": found, "readonly": True, "single_user_local_approvals": True}


@router.get("/list")
def list_workflows(request: Request):
    _auth(request)
    actor, role = _actor(request)
    with closing(_connect()) as db:
        _verify(db)
        rows = db.execute("SELECT id FROM workflows ORDER BY created_at DESC,id DESC LIMIT 100").fetchall()
        return {"workflows": [_detail(db, row["id"]) for row in rows],
                "permissions": {"actor": actor, "role": role,
                                "can_approve": role == "admin"},
                "approval_changes_source": False, "bank_connected": False}


@router.get("/detail")
def detail(workflow_id: str, request: Request):
    _auth(request)
    with closing(_connect()) as db:
        _verify(db)
        return _detail(db, workflow_id)


@router.get("/verify")
def verify(request: Request):
    _auth(request)
    with closing(_connect()) as db:
        return _verify(db)


@router.post("/create")
def create(body: CreateIn, request: Request):
    _auth(request)
    actor, role = _actor(request)
    left = _source(body.source_path)
    right = _source(body.related_path)
    if left["sha256"] != body.source_sha256 or right["sha256"] != body.related_sha256:
        raise HTTPException(409, "Source record changed. Refresh before creating a review.")
    if left["kind"] == right["kind"]:
        raise HTTPException(422, "A workflow must link two different business modules.")
    if body.purpose == "cash_reconciliation_review" and \
            "finance" not in (left["kind"], right["kind"]):
        raise HTTPException(422, "Cash review requires a financial snapshot.")
    with closing(_connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            _verify(db)
            if db.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] >= MAX_REQUESTS:
                raise HTTPException(413, "V7 workflow limit reached.")
            # Recheck in case either file changed after the first read.
            if _source(body.source_path)["sha256"] != body.source_sha256 \
                    or _source(body.related_path)["sha256"] != body.related_sha256:
                raise HTTPException(409, "A referenced record changed during review setup.")
            wf_id = secrets.token_hex(12)
            db.execute("INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?,?,?)", (
                wf_id, body.purpose, left["path"], left["sha256"], right["path"],
                right["sha256"], body.note.strip(), actor, role, _now()))
            _append(db, wf_id, "requested", actor, role, body.note.strip())
            db.commit()
            return {**_detail(db, wf_id), "requires_explicit_decision": True}
        except Exception:
            db.rollback()
            raise


@router.post("/decide")
def decide(body: DecideIn, request: Request):
    _auth(request)
    actor, role = _actor(request)
    with closing(_connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            _verify(db)
            review = _detail(db, body.workflow_id)
            if review["status"] != "pending":
                raise HTTPException(409, "This review has already been decided.")
            if review["last_event_hash"] != body.expected_event_hash:
                raise HTTPException(409, "Review changed since loading. Refresh before deciding.")
            if not _can_decide(actor, role, review["requester"], body.action):
                raise HTTPException(403, "Your role does not permit this workflow decision.")
            if body.action == "approve":
                for side in ("source", "related"):
                    source = _source(review[side+"_path"])
                    if source["sha256"] != review[side+"_sha256"]:
                        raise HTTPException(409, "A source record changed: approval is blocked.")
            event = {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}[body.action]
            digest = _append(db, review["id"], event, actor, role, body.reason.strip())
            db.commit()
            return {"id": review["id"], "status": event, "last_event_hash": digest,
                    "sources_modified": False, "financial_postings": 0,
                    "issued": False, "sent": False, "paid": False}
        except Exception:
            db.rollback()
            raise

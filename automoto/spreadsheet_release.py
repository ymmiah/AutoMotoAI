"""V8 release hardening: offline, bounded, source-preserving recovery and readiness.

No cloud, scheduled background action, data deletion or active workflow DB replacement.
Backups are intentionally NOT encrypted or externally signed. Protect exported copies.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from automoto import business_workflows, commercial_documents, financial_intelligence, spreadsheet_workspace
from automoto.document_workspace import _root
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/spreadsheets/release", tags=["spreadsheet-release"])
BACKUP_RE = re.compile(r"^recovery-[0-9a-f]{24}\.zip$")
RECORD_RE = re.compile(
    r"^[a-z0-9-]{1,48}-[0-9a-f]{12}\.(sheet|invoice|commercial|contact|finance)\.json$"
)
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_FILES = 150
MAX_ITEM = 900_000
MAX_WORKFLOW = 6_000_000
MAX_RAW = 12_000_000
MAX_ARCHIVE = 15_000_000
MAX_LIST = 50
KIND = {
    "sheet": ("spreadsheet-v1", spreadsheet_workspace.BookIn),
    "invoice": ("invoice-v1", spreadsheet_workspace.InvoiceIn),
    "commercial": ("commercial-v4", commercial_documents.CommercialIn),
    "contact": ("contact-v4", commercial_documents.Party),
    "finance": ("finance-v5", financial_intelligence.FinanceBook),
}


class ArchiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(..., min_length=42, max_length=150)
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class RestoreIn(ArchiveIn):
    acknowledgement: Literal["RESTORE COPIES"]
    confirm_no_overwrite: Literal[True]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _rel(path: Path) -> str:
    return path.relative_to(_root()).as_posix()


def _directory(create: bool = False) -> Path:
    root = _root()
    parent = root / "artifacts"
    directory = parent / "recovery"
    if parent.is_symlink() or directory.is_symlink():
        raise HTTPException(403, "Recovery directories cannot be symlinks.")
    if create:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.exists() and (not directory.is_dir()
                               or not directory.resolve().is_relative_to(root)):
        raise HTTPException(403, "Recovery storage must be private.")
    return directory


def _private_read(path: Path, limit: int) -> bytes:
    """Bound memory; refuse symlinks on platforms supporting O_NOFOLLOW."""
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(_root()):
        raise HTTPException(403, "Source or backup is not a regular private workspace file.")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            with os.fdopen(fd, "rb", closefd=True) as stream:
                raw = stream.read(limit + 1)
        except Exception:
            raise
    except OSError:
        raise HTTPException(409, "Private file changed or could not be opened safely.") from None
    if len(raw) > limit:
        raise HTTPException(413, "Source exceeds the recovery size limit.")
    return raw


def _exclusive_write(path: Path, raw: bytes) -> None:
    """An actual exclusive creation, never an accidental overwrite of an existing draft."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        raise HTTPException(409, "Unexpected file collision; retry with a new name.") from None
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _validate_record(name: str, data: bytes) -> tuple[str, str]:
    match = RECORD_RE.fullmatch(name)
    if not match:
        raise HTTPException(422, "Unsupported recovery record filename.")
    suffix = match.group(1)
    schema, validator = KIND[suffix]
    try:
        doc = json.loads(data)
        if not isinstance(doc, dict) or set(doc) != {"schema", "data"} \
                or doc["schema"] != schema or not isinstance(doc["data"], dict):
            raise ValueError("Invalid saved record envelope.")
        body = validator.model_validate(doc["data"])
        # Business validation must be identical to normal creation, not just schema validation.
        if suffix == "sheet":
            spreadsheet_workspace._normalise(body)
        elif suffix == "commercial":
            commercial_documents.preview(body)
        elif suffix == "finance":
            financial_intelligence.summarise(body)
        elif suffix == "invoice":
            spreadsheet_workspace._invoice_preview(body)
    except (TypeError, ValueError, ValidationError, KeyError, AttributeError):
        raise HTTPException(422, "Recovered record failed the original schema checks.") from None
    return suffix, schema


def _snapshot_workflow() -> bytes | None:
    """SQLite backup API provides a transactionally coherent snapshot; do not copy WAL files."""
    source = business_workflows._store()
    if not source.exists():
        return None
    if source.is_symlink() or not source.is_file():
        raise HTTPException(403, "Workflow audit source is not a regular file.")
    if source.stat().st_size > MAX_WORKFLOW:
        raise HTTPException(413, "Workflow audit is too large for a V8 archive.")
    with tempfile.TemporaryDirectory(prefix="automoto-v8-sqlite-") as temporary:
        target = Path(temporary) / "workflow.sqlite3"
        with sqlite3.connect(source) as live, sqlite3.connect(target) as copy:
            live.row_factory = sqlite3.Row
            business_workflows._verify(live)
            live.backup(copy)
        data = target.read_bytes()
        if len(data) > MAX_WORKFLOW:
            raise HTTPException(413, "Workflow snapshot exceeds the backup limit.")
        _verify_workflow_bytes(data)
        return data


def _verify_workflow_bytes(data: bytes) -> None:
    if len(data) > MAX_WORKFLOW or not data.startswith(b"SQLite format 3\x00"):
        raise HTTPException(422, "Invalid workflow audit database in backup.")
    with tempfile.TemporaryDirectory(prefix="automoto-v8-verify-") as temporary:
        path = Path(temporary) / "audit.sqlite3"
        path.write_bytes(data)
        # SQLite opens an isolated private temporary copy. It never becomes the live audit log.
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            try:
                checked = db.execute("PRAGMA quick_check").fetchone()
                if not checked or checked[0] != "ok":
                    raise ValueError("SQLite integrity failure")
                business_workflows._verify(db)
            except (sqlite3.DatabaseError, ValueError, KeyError, IndexError):
                raise HTTPException(422, "Archived workflow history is invalid.") from None


def _inventory() -> list[tuple[str, bytes, str]]:
    folder = spreadsheet_workspace._storage()
    result: list[tuple[str, bytes, str]] = []
    total = 0
    if not folder.is_dir():
        return result
    for item in sorted(folder.iterdir()):
        if not RECORD_RE.fullmatch(item.name):
            continue
        if len(result) >= MAX_FILES:
            raise HTTPException(413, "More than 150 supported records; select a smaller workspace.")
        raw = _private_read(item, MAX_ITEM)
        suffix, schema = _validate_record(item.name, raw)
        total += len(raw)
        if total > MAX_RAW - MAX_WORKFLOW:
            raise HTTPException(413, "Record contents exceed the V8 archive limit.")
        result.append((item.name, raw, schema))
    return result


def _archive_path(raw: str) -> Path:
    prefix = "artifacts/recovery/"
    if not isinstance(raw, str) or not raw.startswith(prefix) or len(raw) > 150:
        raise HTTPException(403, "Only workspace-owned V8 backups may be opened.")
    name = raw[len(prefix):]
    if not BACKUP_RE.fullmatch(name):
        raise HTTPException(403, "Invalid recovery archive path.")
    return _directory() / name


def _loaded_archive(request: ArchiveIn) -> tuple[dict, dict[str, bytes], bytes]:
    raw = _private_read(_archive_path(request.path), MAX_ARCHIVE)
    if _sha(raw) != request.sha256:
        raise HTTPException(409, "The backup archive changed since it was selected.")
    entries: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            members = archive.infolist()
            if not members or len(members) > MAX_FILES + 2:
                raise ValueError("Unexpected number of ZIP members.")
            names = [entry.filename for entry in members]
            if len(names) != len(set(names)):
                raise ValueError("Duplicate ZIP entries.")
            if any(entry.is_dir() or entry.file_size > MAX_WORKFLOW or
                   entry.flag_bits & 0x1 or entry.compress_type not in
                   (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) for entry in members):
                raise ValueError("Unsupported or excessive ZIP member.")
            if sum(entry.file_size for entry in members) > MAX_RAW:
                raise ValueError("Expanded archive exceeds V8 bounds.")
            for member in members:
                name = member.filename
                if not (name == "manifest.json" or name == "workflow-audit.sqlite3"
                        or name.startswith("records/") and
                        RECORD_RE.fullmatch(name[len("records/"):])):
                    raise ValueError("Unexpected ZIP member path.")
                cap = MAX_WORKFLOW if name == "workflow-audit.sqlite3" else \
                    (MAX_ITEM if name.startswith("records/") else 100_000)
                if member.file_size > cap:
                    raise ValueError("ZIP member exceeds type limit.")
                with archive.open(member) as stream:
                    data = stream.read(cap + 1)
                if len(data) > cap:
                    raise ValueError("Decompressed member exceeds limit.")
                entries[name] = data
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError, KeyError):
        raise HTTPException(422, "Backup is not a safe V8 archive.") from None
    try:
        manifest = json.loads(entries["manifest.json"])
        if not isinstance(manifest, dict) or set(manifest) != {
            "schema", "created_at", "records", "workflow"} \
                or manifest["schema"] != "automoto-recovery-v8":
            raise ValueError("Invalid manifest.")
        files = manifest["records"]
        if not isinstance(files, list) or len(files) > MAX_FILES:
            raise ValueError("Invalid record list.")
        expected = {"manifest.json"}
        for item in files:
            if not isinstance(item, dict) or set(item) != {"name", "schema", "sha256", "size"}:
                raise ValueError("Invalid record metadata.")
            name = item["name"]
            if not isinstance(name, str) or not RECORD_RE.fullmatch(name):
                raise ValueError("Unsafe manifest filename.")
            key = "records/" + name
            expected.add(key)
            data = entries[key]
            suffix, schema = _validate_record(name, data)
            if item["schema"] != schema or item["sha256"] != _sha(data) \
                    or item["size"] != len(data):
                raise ValueError("Record content or checksum changed.")
        meta = manifest["workflow"]
        if meta is not None:
            if not isinstance(meta, dict) or set(meta) != {"sha256", "size"}:
                raise ValueError("Invalid workflow metadata.")
            db = entries["workflow-audit.sqlite3"]
            if _sha(db) != meta["sha256"] or len(db) != meta["size"]:
                raise ValueError("Workflow evidence changed.")
            _verify_workflow_bytes(db)
            expected.add("workflow-audit.sqlite3")
        if expected != set(entries):
            raise ValueError("Archive contains unexpected or missing files.")
    except (ValueError, TypeError, KeyError, AttributeError, HTTPException):
        raise HTTPException(422, "Recovery archive failed its manifest and source integrity checks.") from None
    return manifest, entries, raw


@router.get("/readiness")
def readiness(request: Request):
    _auth(request)
    root = _root()
    archive_folder = _directory()
    paths = [p for p in archive_folder.iterdir() if p.is_file()
             and not p.is_symlink() and BACKUP_RE.fullmatch(p.name)] if archive_folder.is_dir() else []
    audit = business_workflows._store()
    audit_state = "not_created"
    if audit.is_file() and not audit.is_symlink():
        try:
            with sqlite3.connect(f"file:{audit.as_posix()}?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                business_workflows._verify(db)
            audit_state = "verified"
        except (sqlite3.DatabaseError, HTTPException, OSError):
            audit_state = "failed"
    checks = {
        "workspace": "pass" if root.is_dir() else "blocked",
        "workflow_audit": audit_state,
        "backup_available": "pass" if paths else "missing",
        "native_installer_manual": "pending",
        "offline_model_manual": "pending",
        "accessibility_manual": "pending",
        "security_review_manual": "pending",
        "restore_drill_manual": "pending",
    }
    return {
        "checks": checks, "release_ready": False, "store_publication_authorised": False,
        "development_complete": False,
        "message": "Release remains blocked until cross-platform, recovery and security manual gates are signed off.",
        "offline": True, "archives": len(paths), "no_network_requests": True,
    }


@router.get("/list")
def list_backups(request: Request):
    _auth(request)
    folder = _directory()
    files = []
    if folder.is_dir():
        for item in sorted(folder.iterdir(), key=lambda p: p.name, reverse=True):
            if len(files) >= MAX_LIST:
                break
            if item.is_file() and not item.is_symlink() and BACKUP_RE.fullmatch(item.name):
                try:
                    raw = _private_read(item, MAX_ARCHIVE)
                    files.append({"path": _rel(item), "bytes": len(raw),
                                  "sha256": _sha(raw)})
                except HTTPException:
                    continue
    return {"backups": files, "encrypted": False, "records_unchanged": True}


@router.post("/create")
def create_backup(request: Request):
    _auth(request)
    records = _inventory()
    workflow = _snapshot_workflow()
    metadata = [{"name": name, "schema": schema, "sha256": _sha(data), "size": len(data)}
                for name, data, schema in records]
    manifest = {
        "schema": "automoto-recovery-v8",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "records": metadata,
        "workflow": {"sha256": _sha(workflow), "size": len(workflow)} if workflow else None,
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as archive:
        archive.writestr("manifest.json", json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        for name, data, _ in records:
            archive.writestr("records/" + name, data)
        if workflow is not None:
            archive.writestr("workflow-audit.sqlite3", workflow)
    packed = stream.getvalue()
    if len(packed) > MAX_ARCHIVE:
        raise HTTPException(413, "Generated recovery archive exceeds the size limit.")
    directory = _directory(create=True)
    path = directory / f"recovery-{secrets.token_hex(12)}.zip"
    _exclusive_write(path, packed)
    return {"path": _rel(path), "sha256": _sha(packed), "records": len(records),
            "workflow_history_included": workflow is not None, "bytes": len(packed),
            "encrypted": False, "source_files_changed": False,
            "restore_mode": "new copies only", "offline": True}


@router.post("/verify")
def verify_backup(body: ArchiveIn, request: Request):
    _auth(request)
    manifest, entries, raw = _loaded_archive(body)
    return {"valid": True, "sha256": _sha(raw), "records": len(manifest["records"]),
            "workflow_history_included": manifest["workflow"] is not None,
            "created_at": manifest["created_at"], "no_changes": True,
            "untrusted_until_verified": False,
            "warning": "Unencrypted checksum-based backup. Not externally signed or notarised."}


@router.post("/restore")
def restore_copies(body: RestoreIn, request: Request):
    _auth(request)
    manifest, entries, _ = _loaded_archive(body)
    record_folder = spreadsheet_workspace._storage(create=True)
    recovery_folder = _directory(create=True)
    created: list[Path] = []
    restored = []
    try:
        for item in manifest["records"]:
            old_name = item["name"]
            suffix = RECORD_RE.fullmatch(old_name).group(1)
            target = record_folder / f"restored-{secrets.token_hex(6)}.{suffix}.json"
            _exclusive_write(target, entries["records/" + old_name])
            created.append(target)
            restored.append({"original": "artifacts/spreadsheets/" + old_name,
                             "recovered": _rel(target), "sha256": item["sha256"]})
        evidence = None
        if manifest["workflow"] is not None:
            # Intentionally NOT activated: audited approvals must not silently reappear.
            target = recovery_folder / f"isolated-audit-{secrets.token_hex(12)}.sqlite3"
            _exclusive_write(target, entries["workflow-audit.sqlite3"])
            created.append(target)
            evidence = _rel(target)
    except Exception:
        for target in created:
            try:
                target.unlink()
            except OSError:
                pass
        raise
    return {
        "restored": restored, "records": len(restored),
        "archived_workflow_evidence": evidence,
        "live_workflow_history_replaced": False, "original_records_overwritten": False,
        "invoices_issued": False, "financial_postings": 0, "store_publication_authorised": False,
        "message": "New independent draft copies created. Existing records and active review history untouched.",
    }

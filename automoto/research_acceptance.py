"""Research Studio V7: bounded integrity audit and non-destructive recovery.

A good checksum proves byte identity against a selected hash, NOT scientific
correctness, publication permission, tamper-proof provenance or device backup.
Recovery never overwrites trusted original sources, research or studio drafts.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automoto import (document_research, document_workspace, research_ai,
                      research_comparison, research_handoffs, research_studio)
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/research/studio/acceptance", tags=["research-acceptance"])
SCHEMA = "research-recovery-v7"
NAME = re.compile(r"^backup-([a-f0-9]{24})\.recovery\.json$")
BACKUP_ID = re.compile(r"^[a-f0-9]{24}$")
MAX_BACKUPS = 16
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024
MAX_BUNDLE_BYTES = MAX_TOTAL_BYTES + 100_000
MAX_MEMBERS = 14
MAX_RECORD_BYTES = 24_000
MANUAL_GATES = (
    "Original publication, journal and DOI metadata checked by the author",
    "Every consequential claim and quotation assessed in full source context",
    "Research methods, uncertainty, copyright and academic integrity reviewed",
    "PDF/Word export, screen-reader and keyboard review on actual devices",
    "Large-document extraction gaps and performance reviewed with real sources",
    "Cross-platform installed-app and disaster-recovery exercises completed",
    "Microsoft Store release separately approved by the project owner",
)


class Selection(research_ai.ComparisonRef):
    model_config = ConfigDict(extra="forbid")
    review_path: str | None = Field(None, max_length=160)
    review_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    handoff_path: str | None = Field(None, max_length=160)
    handoff_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def paired(self):
        if ((self.review_path is None) != (self.review_sha256 is None)
                or (self.handoff_path is None) != (self.handoff_sha256 is None)):
            raise ValueError("Supply each optional private record with its current SHA-256.")
        return self


class SnapshotIn(Selection):
    acknowledgement: Literal["SAVE PRIVATE RESEARCH RECOVERY"]
    confirm_no_publication: Literal[True]


class BackupRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(..., min_length=45, max_length=140)
    sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")


class StageIn(BackupRef):
    acknowledgement: Literal["STAGE FILES WITHOUT OVERWRITING"]
    confirm_no_original_changes: Literal[True]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _folder(kind: Literal["snapshots", "staging"], create: bool = False) -> Path:
    root = document_workspace._root()
    parent = root / "artifacts"
    research = parent / "research"
    recovery = research / "recovery"
    selected = recovery / kind
    if any(p.is_symlink() for p in (parent, research, recovery, selected)):
        raise HTTPException(403, "Recovery folders must not be symbolic links.")
    if create:
        selected.mkdir(mode=0o700, parents=True, exist_ok=True)
    if selected.exists() and (not selected.is_dir()
                              or not selected.resolve().is_relative_to(root)):
        raise HTTPException(403, "Recovery must remain in the private workspace.")
    return selected


def _record_path(raw: str) -> Path:
    prefix = "artifacts/research/recovery/snapshots/"
    if not isinstance(raw, str) or not raw.startswith(prefix) or not NAME.fullmatch(raw[len(prefix):]):
        raise HTTPException(403, "Only private research recovery metadata can be opened.")
    path = _folder("snapshots") / raw[len(prefix):]
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "Recovery metadata was not found.")
    if path.stat().st_size > MAX_RECORD_BYTES:
        raise HTTPException(413, "Recovery metadata exceeds the limit.")
    return path


def _checked_file(file: Path, expected: str | None = None) -> tuple[bytes, str]:
    root = document_workspace._root()
    if (not file.is_file() or file.is_symlink() or not file.resolve().is_relative_to(root)
            or any(p.is_symlink() for p in file.parents if p != root)):
        raise HTTPException(403, "A source file is missing, symbolic or outside the workspace.")
    if file.stat().st_size > MAX_FILE_BYTES:
        raise HTTPException(413, "Recovery supports source files up to 16 MB each.")
    raw = file.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected and digest != expected:
        raise HTTPException(409, "Source file changed during research acceptance.")
    return raw, digest


def _context(body: Selection) -> tuple[dict, list[dict]]:
    """A complete V3/V5/V6 check before inspecting or copying selected bytes."""
    target = "document"
    archive = None
    if body.handoff_path:
        audit = research_handoffs._manifest_path(body.handoff_path)
        _, digest = _checked_file(audit, body.handoff_sha256)
        archive = research_handoffs._read_manifest(audit)
        if archive.get("comparison_path") != body.comparison_path or archive.get("comparison_sha256") != body.comparison_sha256:
            raise HTTPException(422, "Hand-off audit belongs to another research comparison.")
        target = archive["target"]
        recorded_review = archive.get("human_ai_review")
        if recorded_review != ({"path": body.review_path, "sha256": body.review_sha256,
                                "retained_count": recorded_review.get("retained_count"),
                                "rejected_count": recorded_review.get("rejected_count")}
                               if isinstance(recorded_review, dict) and body.review_path else None):
            raise HTTPException(422, "Hand-off AI approval does not match the selected human review.")
    ref = research_handoffs.HandoffIn(
        comparison_path=body.comparison_path, comparison_sha256=body.comparison_sha256,
        target=target, review_path=body.review_path, review_sha256=body.review_sha256,
    )
    packet = research_handoffs._packet(ref)
    if archive and any(archive.get(k) != v for k, v in packet.items()):
        raise HTTPException(422, "Archived hand-off evidence differs from the freshly verified evidence.")
    comparison = research_comparison._file(packet["comparison_path"])
    project = research_studio._file(packet["project_path"])
    entries = [
        {"role": "comparison", "path": packet["comparison_path"], "file": comparison,
         "expected": packet["comparison_sha256"]},
        {"role": "research_project", "path": packet["project_path"], "file": project,
         "expected": packet["project_sha256"]},
    ]
    for idx, item in enumerate(packet["sources"], 1):
        entries.append({
            "role": "original_source", "path": item["path"],
            "file": document_research._source_path(item["path"]),
            "expected": item["sha256"],
        })
    if body.review_path:
        review_file = research_ai._path(body.review_path, "reviews")
        _, _ = _checked_file(review_file, body.review_sha256)
        review = research_ai._read(review_file, research_ai.REVIEW_SCHEMA)
        draft = research_ai._path(review["draft_path"], "proposals")
        entries.extend([
            {"role": "human_ai_review", "path": body.review_path,
             "file": review_file, "expected": body.review_sha256},
            {"role": "unapproved_ai_proposal", "path": review["draft_path"],
             "file": draft, "expected": review["draft_sha256"]},
        ])
    if archive:
        output = research_handoffs._actual_target(archive["target_path"], target)
        entries.extend([
            {"role": "handoff_audit", "path": body.handoff_path,
             "file": research_handoffs._manifest_path(body.handoff_path), "expected": body.handoff_sha256},
            {"role": "separate_studio_draft", "path": archive["target_path"],
             "file": output, "expected": archive["target_sha256"]},
        ])
    if len(entries) > MAX_MEMBERS or len({e["path"] for e in entries}) != len(entries):
        raise HTTPException(422, "Recovery selection contains too many or duplicate artifacts.")
    return packet, entries


def _inspect(body: Selection, copy_bytes: bool) -> tuple[dict, list[tuple[dict, bytes]]]:
    started = time.monotonic()
    packet, entries = _context(body)
    copied = []
    summary = []
    total = 0
    for entry in entries:
        raw, digest = _checked_file(entry["file"], entry["expected"])
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(413, "Recovery bundle exceeds 40 MB; split the research material.")
        meta = {"role": entry["role"], "path": entry["path"],
                "sha256": digest, "bytes": len(raw)}
        summary.append(meta)
        if copy_bytes:
            copied.append((meta, raw))
    return {
        "comparison_path": packet["comparison_path"],
        "comparison_sha256": packet["comparison_sha256"],
        "checked_artifacts": summary, "checked_source_count": len(packet["sources"]),
        "checked_bytes": total, "extraction_warnings": packet["limitations"],
        "integrity": "verified_against_selected_sha256",
        "science_verified": False, "publication_ready": False, "store_release_approved": False,
        "manual_acceptance": [{"item": gate, "status": "not_certified_by_software"}
                              for gate in MANUAL_GATES],
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        "no_model_invocation": True, "no_network_request": True,
        "originals_modified": False,
    }, copied


def _decode_record(raw: bytes) -> dict:
    """Validate the V7 metadata shape even when supplied by a portable import."""
    if len(raw) > MAX_RECORD_BYTES:
        raise HTTPException(413, "Recovery metadata is too large.")
    try:
        record = json.loads(raw.decode("utf-8"))
        if (not isinstance(record, dict) or record.get("schema") != SCHEMA
                or not isinstance(record.get("files"), list)
                or not 3 <= len(record["files"]) <= MAX_MEMBERS
                or not isinstance(record.get("archive_sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", record["archive_sha256"])
                or not isinstance(record.get("created_at"), str)
                or not isinstance(record.get("selection"), dict)):
            raise ValueError("Invalid recovery record.")
        for i, entry in enumerate(record["files"]):
            if (not isinstance(entry, dict) or entry.get("member") != f"files/{i + 1:03d}"
                    or not isinstance(entry.get("path"), str)
                    or not isinstance(entry.get("role"), str)
                    or not isinstance(entry.get("sha256"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])
                    or not isinstance(entry.get("bytes"), int)
                    or isinstance(entry["bytes"], bool)
                    or not 0 <= entry["bytes"] <= MAX_FILE_BYTES):
                raise ValueError("Invalid recovery file manifest.")
        return record
    except (OSError, ValueError, UnicodeError, TypeError, KeyError):
        raise HTTPException(422, "Private recovery metadata is corrupt.") from None


def _load_record(file: Path) -> dict:
    if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_RECORD_BYTES:
        raise HTTPException(422, "Recovery metadata is missing, symbolic or oversized.")
    return _decode_record(file.read_bytes())


def _verify(ref: BackupRef) -> tuple[dict, list[tuple[dict, bytes]]]:
    file = _record_path(ref.path)
    if document_workspace._sha(file) != ref.sha256:
        raise HTTPException(409, "Recovery metadata no longer matches the selected digest.")
    record = _load_record(file)
    match = NAME.fullmatch(file.name)
    archive = file.with_name(f"backup-{match.group(1)}.research.zip")
    root = document_workspace._root()
    if (archive.is_symlink() or not archive.is_file()
            or not archive.resolve().is_relative_to(root)
            or archive.stat().st_size > MAX_BUNDLE_BYTES):
        raise HTTPException(422, "Private recovery archive is unavailable or oversized.")
    payload = archive.read_bytes()
    if hashlib.sha256(payload).hexdigest() != record["archive_sha256"]:
        raise HTTPException(409, "Recovery archive checksum mismatch.")
    return _verify_archive_bytes(record, payload)


def _verify_archive_bytes(record: dict, payload: bytes) -> tuple[dict, list[tuple[dict, bytes]]]:
    """Verify the exact portable ZIP member roster before any extraction."""
    if len(payload) > MAX_BUNDLE_BYTES:
        raise HTTPException(413, "Recovery archive is oversized.")
    if hashlib.sha256(payload).hexdigest() != record["archive_sha256"]:
        raise HTTPException(409, "Recovery archive checksum mismatch.")
    members = []
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as source:
            if source.namelist() != ["manifest.json"] + [p["member"] for p in record["files"]]:
                raise ValueError("Archive member list differs from manifest.")
            info = source.getinfo("manifest.json")
            if info.compress_type != zipfile.ZIP_STORED or info.file_size > MAX_RECORD_BYTES:
                raise ValueError("Recovery manifest has an unsafe compression or size.")
            stored = json.loads(source.read("manifest.json"))
            if stored != {"schema": SCHEMA, "files": record["files"],
                          "selection": record["selection"]}:
                raise ValueError("Archive manifest does not match the protected record.")
            total = 0
            for entry in record["files"]:
                info = source.getinfo(entry["member"])
                if (info.compress_type != zipfile.ZIP_STORED
                        or info.file_size != entry["bytes"]
                        or info.file_size > MAX_FILE_BYTES
                        or (info.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError("Recovery file has unsafe type, size or compression.")
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise ValueError("Archive exceeds total verified size.")
                raw = source.read(info, pwd=None)
                if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                    raise ValueError("Archive member checksum mismatch.")
                members.append((entry, raw))
    except (OSError, ValueError, KeyError, RuntimeError, EOFError, zipfile.BadZipFile, json.JSONDecodeError):
        raise HTTPException(422, "Recovery contents failed exact integrity validation.") from None
    return record, members



def _write_archive(target: Path, payload: bytes) -> None:
    """Own fixed-size archive writer; Document Assistant's 20 MB output cap is unrelated."""
    if len(payload) > MAX_BUNDLE_BYTES:
        raise HTTPException(413, "Recovery archive exceeds the 40 MB data limit.")
    document_workspace._quota_check(len(payload))
    temp = target.with_name(".working-" + secrets.token_hex(8) + ".part")
    try:
        with temp.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists() or target.is_symlink():
            raise HTTPException(409, "Recovery archive destination already exists.")
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)

@router.post("/audit")
def audit(body: Selection, request: Request):
    _auth(request)
    result, _ = _inspect(body, copy_bytes=False)
    return result


@router.post("/snapshot")
def snapshot(body: SnapshotIn, request: Request):
    _auth(request)
    directory = _folder("snapshots", create=True)
    if sum(1 for p in directory.iterdir() if NAME.fullmatch(p.name)
           and p.is_file() and not p.is_symlink()) >= MAX_BACKUPS:
        raise HTTPException(413, "Private research recovery archive limit reached (16).")
    report, copied = _inspect(body, copy_bytes=True)
    # Recheck V3/V5/V6 records after reading and before making a recovery copy.
    _context(body)
    manifest = {
        "schema": SCHEMA, "selection": body.model_dump(
            exclude={"acknowledgement", "confirm_no_publication"}, mode="json"),
        "files": [{**meta, "member": f"files/{i:03d}"}
                  for i, (meta, _) in enumerate(copied, 1)],
    }
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as dest:
        dest.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False,
                                                  separators=(",", ":")))
        for entry, (_, raw) in zip(manifest["files"], copied):
            dest.writestr(entry["member"], raw)
    payload = data.getvalue()
    if len(payload) > MAX_BUNDLE_BYTES:
        raise HTTPException(413, "Recovery archive exceeded its private storage limit.")
    record = {**manifest, "created_at": _now(),
              "archive_sha256": hashlib.sha256(payload).hexdigest(),
              "publication_ready": False, "originals_modified": False}
    raw_record = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw_record) > MAX_RECORD_BYTES:
        raise HTTPException(413, "Recovery metadata is too large.")
    token = secrets.token_hex(12)
    archive = directory / f"backup-{token}.research.zip"
    file = directory / f"backup-{token}.recovery.json"
    try:
        _write_archive(archive, payload)
        try:
            document_workspace._atomic_file(file, raw_record)
        except Exception:
            archive.unlink(missing_ok=True)
            raise
    except OSError:
        raise HTTPException(500, "Unable to save the private recovery snapshot.") from None
    return {"path": file.relative_to(document_workspace._root()).as_posix(),
            "sha256": hashlib.sha256(raw_record).hexdigest(),
            "archive_path": archive.relative_to(document_workspace._root()).as_posix(),
            "archive_sha256": record["archive_sha256"],
            "file_count": len(copied), "checked_bytes": report["checked_bytes"],
            "create_only": True, "source_files_modified": False, "published": False}


@router.get("/list")
def list_snapshots(request: Request):
    _auth(request)
    folder = _folder("snapshots")
    items = []
    if folder.is_dir():
        for p in sorted(folder.iterdir(), key=lambda x: x.name, reverse=True):
            if p.is_symlink() or not p.is_file() or not NAME.fullmatch(p.name):
                continue
            try:
                record = _load_record(_record_path("artifacts/research/recovery/snapshots/" + p.name))
                items.append({"path": p.relative_to(document_workspace._root()).as_posix(),
                              "sha256": document_workspace._sha(p),
                              "created_at": record["created_at"],
                              "file_count": len(record["files"])})
            except HTTPException:
                items.append({"path": p.relative_to(document_workspace._root()).as_posix(),
                              "sha256": document_workspace._sha(p),
                              "created_at": "", "file_count": 0,
                              "warning": "Recovery metadata needs investigation."})
            if len(items) >= MAX_BACKUPS:
                break
    return {"snapshots": items, "limit": MAX_BACKUPS}


@router.post("/verify")
def verify(body: BackupRef, request: Request):
    _auth(request)
    record, files = _verify(body)
    return {
        "valid_against_recorded_hashes": True, "file_count": len(files),
        "archive_sha256": record["archive_sha256"],
        "restored": False, "original_files_modified": False,
        "warning": "Archive integrity does not establish source truth, current source status or an independently signed backup.",
    }


@router.post("/stage")
def stage(body: StageIn, request: Request):
    _auth(request)
    record, files = _verify(body)
    folder = _folder("staging", create=True)
    staging = folder / ("stage-" + secrets.token_hex(12))
    staging.mkdir(mode=0o700)
    try:
        data_dir = staging / "files"
        data_dir.mkdir(mode=0o700)
        for item, content in files:
            target = data_dir / item["member"].split("/")[-1]
            document_workspace._atomic_file(target, content)
        result = {"schema": SCHEMA, "created_at": _now(),
                  "source_backup": body.path, "source_archive_sha256": record["archive_sha256"],
                  "files": record["files"],
                  "restored_into_trusted_locations": False,
                  "requires_manual_review": True}
        document_workspace._atomic_file(staging / "staged-manifest.json",
            json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:
        shutil.rmtree(staging)
        raise
    return {
        "staging_path": staging.relative_to(document_workspace._root()).as_posix(),
        "file_count": len(files), "original_files_modified": False,
        "published": False, "requires_manual_review": True,
        "warning": "Files are recovered into a private quarantine folder only, not to their original or trusted application paths.",
    }

"""Research Studio V8: password-encrypted, portable and safely staged research recovery.

The only portable payload is authenticated AES-256-GCM ciphertext. A scrypt KDF
derives a fresh per-export key from a user-owned passphrase. Decrypted original
research never enters trusted workspace paths automatically, even on a fresh PC.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from automoto import document_workspace, research_acceptance
from automoto.visual_studio import _auth

router = APIRouter(prefix="/api/research/studio/portable", tags=["research-portable"])
MAGIC = b"AMRC8\x00\x01\x00"
AAD_CONTEXT = b"AutoMoto Research Studio V8 encrypted portable recovery"
SALT_LEN, NONCE_LEN = 16, 12
HEADER_LEN = len(MAGIC) + SALT_LEN + NONCE_LEN
N = 2 ** 15
MAX_CAPSULE_BYTES = research_acceptance.MAX_BUNDLE_BYTES + research_acceptance.MAX_RECORD_BYTES + 512
MAX_SNAPSHOTS = 16
MAX_RECORD_BYTES = 2048
FILENAME = re.compile(r"^capsule-([a-f0-9]{24})\.amrc8$")
RECORD = re.compile(r"^capsule-([a-f0-9]{24})\.json$")
PREFIX = "artifacts/research/recovery/portable/"
MIN_PASSWORD_CHARS = 16
MAX_PASSWORD_BYTES = 256


class CreateIn(research_acceptance.BackupRef):
    model_config = ConfigDict(extra="forbid")
    passphrase: SecretStr = Field(..., repr=False)
    acknowledgement: Literal["ENCRYPT PORTABLE BACKUP"]
    confirm_user_will_store_separately: Literal[True]


def _password(value: SecretStr | str) -> bytes:
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    if not isinstance(raw, str) or len(raw) < MIN_PASSWORD_CHARS:
        raise HTTPException(422, "Use a unique recovery passphrase of at least 16 characters.")
    data = raw.encode("utf-8")
    if len(data) > MAX_PASSWORD_BYTES:
        raise HTTPException(422, "Recovery passphrase is too long.")
    return data


def _key(password: bytes, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=N, r=8, p=1).derive(password)


def _seal(blob: bytes, password: bytes) -> bytes:
    if len(blob) > MAX_CAPSULE_BYTES - HEADER_LEN - 16:
        raise HTTPException(413, "Recovery is too large for portable encryption.")
    salt, nonce = os.urandom(SALT_LEN), os.urandom(NONCE_LEN)
    header = MAGIC + salt + nonce
    encrypted = AESGCM(_key(password, salt)).encrypt(nonce, blob, AAD_CONTEXT + header)
    return header + encrypted


def _unseal(payload: bytes, password: bytes) -> bytes:
    if (len(payload) > MAX_CAPSULE_BYTES or len(payload) < HEADER_LEN + 16
            or payload[:len(MAGIC)] != MAGIC):
        raise HTTPException(422, "Unsupported, truncated or oversized research capsule.")
    header, encrypted = payload[:HEADER_LEN], payload[HEADER_LEN:]
    salt = header[len(MAGIC):len(MAGIC) + SALT_LEN]
    nonce = header[-NONCE_LEN:]
    try:
        return AESGCM(_key(password, salt)).decrypt(nonce, encrypted, AAD_CONTEXT + header)
    except InvalidTag:
        # Do not leak whether a particular password or ciphertext was wrong.
        raise HTTPException(422, "Incorrect recovery passphrase or damaged encrypted capsule.") from None


def _pack(record: bytes, archive: bytes) -> bytes:
    if len(record) > research_acceptance.MAX_RECORD_BYTES or len(archive) > research_acceptance.MAX_BUNDLE_BYTES:
        raise HTTPException(413, "Research recovery material exceeds portable limits.")
    return len(record).to_bytes(4, "big") + record + archive


def _verified_contents(payload: bytes, password: bytes):
    plain = _unseal(payload, password)
    if len(plain) < 4:
        raise HTTPException(422, "Portable research package is incomplete.")
    record_len = int.from_bytes(plain[:4], "big")
    if not 1 <= record_len <= research_acceptance.MAX_RECORD_BYTES:
        raise HTTPException(422, "Portable research metadata length is invalid.")
    if len(plain) - 4 - record_len > research_acceptance.MAX_BUNDLE_BYTES:
        raise HTTPException(413, "Portable research archive exceeds size limits.")
    raw_record, archive = plain[4:4 + record_len], plain[4 + record_len:]
    record = research_acceptance._decode_record(raw_record)
    record, files = research_acceptance._verify_archive_bytes(record, archive)
    return record, files


def _folder(create=False) -> Path:
    root = document_workspace._root()
    # Reuse V7's validated private recovery directory boundary.
    parent = research_acceptance._folder("snapshots")
    directory = parent.parent / "portable"
    if directory.is_symlink() or parent.parent.is_symlink():
        raise HTTPException(403, "Portable recovery folder cannot be a symbolic link.")
    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.exists() and (not directory.is_dir()
                               or not directory.resolve().is_relative_to(root)):
        raise HTTPException(403, "Portable recovery must remain in the private workspace.")
    return directory


def _path(value: str, *, kind: Literal["capsule", "record"]) -> Path:
    regex = FILENAME if kind == "capsule" else RECORD
    if not isinstance(value, str) or not value.startswith(PREFIX) or not regex.fullmatch(value[len(PREFIX):]):
        raise HTTPException(403, "Only exact private portable recovery paths are accepted.")
    file = _folder() / value[len(PREFIX):]
    if file.is_symlink() or not file.is_file():
        raise HTTPException(404, "Private recovery file does not exist.")
    if file.stat().st_size > (MAX_CAPSULE_BYTES if kind == "capsule" else MAX_RECORD_BYTES):
        raise HTTPException(413, "Private portable file exceeds its size limit.")
    return file


def _metadata(path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) > MAX_RECORD_BYTES:
        raise HTTPException(413, "Portable recovery record is oversized.")
    try:
        item = json.loads(raw)
        if (not isinstance(item, dict) or item.get("schema") != "research-portable-v8"
                or not isinstance(item.get("created_at"), str)
                or not isinstance(item.get("sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
                or not isinstance(item.get("files"), int)
                or isinstance(item["files"], bool)
                or not 3 <= item["files"] <= research_acceptance.MAX_MEMBERS):
            raise ValueError("Invalid portable metadata.")
    except (UnicodeError, ValueError, TypeError, KeyError):
        raise HTTPException(422, "Private portable metadata is malformed.") from None
    return item


def _sidecar(capsule_path: Path) -> Path:
    return capsule_path.with_suffix(".json")


def _write_large(target: Path, data: bytes):
    if len(data) > MAX_CAPSULE_BYTES:
        raise HTTPException(413, "Portable capsule is oversized.")
    document_workspace._quota_check(len(data))
    temporary = target.with_name(".working-" + secrets.token_hex(12) + ".part")
    try:
        with temporary.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if target.is_symlink() or target.exists():
            raise HTTPException(409, "Portable output already exists.")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


@router.post("/create")
def create(body: CreateIn, request: Request):
    _auth(request)
    password = _password(body.passphrase)
    directory = _folder(create=True)
    if sum(1 for p in directory.iterdir() if RECORD.fullmatch(p.name)
           and p.is_file() and not p.is_symlink()) >= MAX_SNAPSHOTS:
        raise HTTPException(413, "Portable recovery limit reached (16 private exports).")
    # V7 verifies every member, full hashes and the selected backup's metadata.
    record, members = research_acceptance._verify(body)
    backup_meta = research_acceptance._record_path(body.path)
    raw_record = backup_meta.read_bytes()
    archive = backup_meta.with_suffix(".research.zip")
    # The archive name does NOT equal the metadata name with_suffix: derive from V7 ID.
    token = research_acceptance.NAME.fullmatch(backup_meta.name).group(1)
    archive = backup_meta.with_name("backup-" + token + ".research.zip")
    if archive.is_symlink() or not archive.is_file():
        raise HTTPException(422, "Verified source ZIP disappeared.")
    raw_zip = archive.read_bytes()
    if hashlib.sha256(raw_zip).hexdigest() != record["archive_sha256"]:
        raise HTTPException(409, "Recovery archive changed before portable encryption.")
    # Verify once more immediately against the exact bytes we will encrypt.
    research_acceptance._verify_archive_bytes(record, raw_zip)
    capsule = _seal(_pack(raw_record, raw_zip), password)
    name = "capsule-" + secrets.token_hex(12)
    output = directory / (name + ".amrc8")
    sidecar = directory / (name + ".json")
    meta = {"schema": "research-portable-v8",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sha256": hashlib.sha256(capsule).hexdigest(), "files": len(members)}
    raw_meta = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    try:
        _write_large(output, capsule)
        try:
            document_workspace._atomic_file(sidecar, raw_meta)
        except Exception:
            output.unlink(missing_ok=True)
            raise
    except OSError:
        raise HTTPException(500, "Failed to save encrypted portable research copy.") from None
    return {"path": PREFIX + output.name, "sha256": meta["sha256"],
            "file_count": len(members), "encrypted": True,
            "format": "amrc8-aes-256-gcm-scrypt",
            "originals_modified": False, "store_release_approved": False,
            "instruction": "Download this encrypted capsule and save a separate copy outside this device. Without the passphrase the backup cannot be recovered."}


@router.get("/list")
def list_capsules(request: Request):
    _auth(request)
    items = []
    directory = _folder()
    if directory.is_dir():
        for file in sorted(directory.iterdir(), key=lambda x: x.name, reverse=True):
            if file.is_symlink() or not file.is_file() or not RECORD.fullmatch(file.name):
                continue
            try:
                meta = _metadata(file)
                capsule = file.with_suffix(".amrc8")
                if capsule.is_symlink() or not capsule.is_file() or capsule.stat().st_size > MAX_CAPSULE_BYTES:
                    continue
                items.append({"path": PREFIX + capsule.name, "sha256": meta["sha256"],
                              "created_at": meta["created_at"], "file_count": meta["files"]})
            except HTTPException:
                continue
            if len(items) >= MAX_SNAPSHOTS:
                break
    return {"capsules": items, "ciphertext_only": True}


@router.get("/download")
def download(request: Request, path: str, sha256: str):
    _auth(request)
    if not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise HTTPException(422, "Select an exact recovery digest.")
    file = _path(path, kind="capsule")
    record = _metadata(_sidecar(file))
    if record["sha256"] != sha256 or document_workspace._sha(file) != sha256:
        raise HTTPException(409, "Encrypted portable capsule changed since selection.")
    return FileResponse(file, filename=file.name, media_type="application/octet-stream",
                        headers={"Cache-Control": "no-store",
                                 "X-Content-Type-Options": "nosniff"})


async def _uploaded(request: Request):
    _auth(request)  # authenticate BEFORE parsing potentially large multipart content
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "multipart/form-data":
        raise HTTPException(415, "Use a multipart upload of an encrypted .amrc8 capsule.")
    try:
        content_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise HTTPException(413, "Invalid upload content length.") from None
    if content_length > MAX_CAPSULE_BYTES + 8192:
        raise HTTPException(413, "Portable capsule upload exceeds the size limit.")
    async with request.form(max_files=1, max_fields=4, max_part_size=2048) as fields:
        file = fields.get("capsule")
        password = fields.get("passphrase")
        if not isinstance(file, UploadFile):
            raise HTTPException(422, "Choose an encrypted research capsule.")
        if not isinstance(file.filename, str) or len(file.filename) > 240 or not file.filename.lower().endswith(".amrc8"):
            raise HTTPException(422, "Choose a supported .amrc8 file.")
        key = _password(password)
        payload = await file.read(MAX_CAPSULE_BYTES + 1)
        if len(payload) > MAX_CAPSULE_BYTES:
            raise HTTPException(413, "Encrypted capsule is oversized.")
        expected = fields.get("expected_sha256")
        if expected is not None:
            if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
                raise HTTPException(422, "Expected capsule fingerprint is invalid.")
            if hashlib.sha256(payload).hexdigest() != expected:
                raise HTTPException(409, "Uploaded capsule changed since its earlier inspection.")
        return payload, key, {
            "acknowledgement": fields.get("acknowledgement"),
            "confirm_no_overwrite": fields.get("confirm_no_overwrite"),
        }


@router.post("/inspect")
async def inspect(request: Request):
    payload, key, _ = await _uploaded(request)
    record, files = _verified_contents(payload, key)
    return {
        "capsule_sha256": hashlib.sha256(payload).hexdigest(),
        "file_count": len(files),
        "file_roles": [{"role": f["role"], "path": f["path"],
                        "bytes": f["bytes"], "sha256": f["sha256"]} for f, _ in files],
        "verified_against_encrypted_manifest": True, "originals_modified": False,
        "trust_status": "quarantined_not_reinstated",
        "manual_review_required": True, "release_authorised": False,
        "warning": "Correct passphrase authenticates encrypted bytes only; source scholarship and authorship require independent verification.",
    }


@router.post("/stage")
async def stage(request: Request):
    payload, key, flags = await _uploaded(request)
    if flags["acknowledgement"] != "STAGE ENCRYPTED BACKUP" or flags["confirm_no_overwrite"] != "true":
        raise HTTPException(422, "Separate approval is required before staging an imported capsule.")
    record, files = _verified_contents(payload, key)
    folder = research_acceptance._folder("staging", create=True)
    destination = folder / ("stage-" + secrets.token_hex(12))
    destination.mkdir(mode=0o700)
    try:
        data_dir = destination / "files"
        data_dir.mkdir(mode=0o700)
        for file, content in files:
            destination_file = data_dir / file["member"].split("/")[-1]
            document_workspace._atomic_file(destination_file, content)
        manifest = {"schema": "research-portable-v8-staged", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "source_capsule_sha256": hashlib.sha256(payload).hexdigest(),
                    "original_record": record,
                    "files": record["files"], "restored_into_trusted_locations": False,
                    "source_accuracy_verified": False, "requires_manual_review": True}
        document_workspace._atomic_file(destination / "staged-manifest.json",
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:
        shutil.rmtree(destination)
        raise
    return {"staging_path": destination.relative_to(document_workspace._root()).as_posix(),
            "file_count": len(files), "source_capsule_sha256": hashlib.sha256(payload).hexdigest(),
            "encrypted_transport": True, "original_files_modified": False,
            "restored_into_trusted_locations": False, "published": False,
            "manual_review_required": True}

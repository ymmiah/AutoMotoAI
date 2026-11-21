"""V33 WebAssembly evidence: bounded inert WAT/WASM/WASI/component inspection.

No WASM, WAT, build script, component, runtime or external tool is executed.
An untrusted WASM module is never treated as sandboxed merely because it is WASM.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil

from fastapi import APIRouter, HTTPException, Request

from automoto import developer_index as index
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/wasm", tags=["developer-wasm"])
MAX_FILES = 120
MAX_TEXT = 256 * 1024
MAX_BINARY = 4 * 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
TEXT_EXTENSIONS = {".wat", ".wit"}
BINARY_EXTENSIONS = {".wasm"}
MANIFESTS = {"wasm-pack.toml", "wit.toml", "component.toml"}
TOOLS = ("wasmtime", "wasm-tools", "wat2wasm", "wasm2wat", "wasm-pack", "cargo-component")
FUNC = re.compile(r"(?m)\((?:func|import|export|component|world|interface)\b[^\n)]{0,180}")
RISK = re.compile(r"(?i)\b(?:wasi_snapshot_preview1|wasi:filesystem|wasi:sockets|sock_open|path_open|fd_write|http)\b")


def _read(root: Path, relative: str, limit: int) -> bytes:
    target = studio._path(root, relative)
    if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
        raise HTTPException(403, "Linked WebAssembly source is forbidden.")
    try:
        with target.open("rb") as handle:
            if not target.is_file():
                raise HTTPException(403, "Only regular files are supported.")
            data = handle.read(limit + 1)
    except OSError as exc:
        raise HTTPException(403, "Unable to read WebAssembly source.") from exc
    if len(data) > limit:
        raise HTTPException(413, "WebAssembly file exceeds bounded inspection limit.")
    return data


def _inspect(root: Path) -> dict:
    files, manifests, total, incomplete = [], [], 0, False
    digest = hashlib.sha256(b"automoto-v33-wasm-inventory\0")
    for name, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        leaf = Path(name).name
        suffix = Path(name).suffix.lower()
        manifest = leaf in MANIFESTS
        if not manifest and suffix not in TEXT_EXTENSIONS | BINARY_EXTENSIONS:
            continue
        if len(files) + len(manifests) >= MAX_FILES:
            incomplete = True
            break
        data = _read(root, name, MAX_BINARY if suffix == ".wasm" else MAX_TEXT)
        total += len(data)
        if total > MAX_TOTAL:
            incomplete = True
            break
        sha = hashlib.sha256(data).hexdigest()
        digest.update(name.encode() + b"\0" + sha.encode() + b"\0")
        if manifest:
            manifests.append({"path": name, "sha256": sha, "bytes": len(data),
                              "evaluated": False, "dependencies_installed": False})
            continue
        if suffix == ".wasm":
            valid_magic = data.startswith(b"\0asm") and len(data) >= 8
            version = int.from_bytes(data[4:8], "little") if valid_magic else None
            classification = ("core_module" if version == 1 else
                              "component_candidate" if version == 13 else "unknown")
            files.append({"path": name, "kind": "wasm_binary", "sha256": sha,
                          "bytes": len(data), "valid_magic": valid_magic,
                          "binary_version": version, "classification": classification,
                          "validated": False, "executed": False,
                          "imports_verified": False, "wasi_permissions_granted": False})
        else:
            text = data.decode("utf-8", errors="replace")
            files.append({"path": name, "kind": "wat" if suffix == ".wat" else "wit",
                          "sha256": sha, "bytes": len(data),
                          "declarations": FUNC.findall(text[:64000])[:30],
                          "risk_signals": [{"line": text[:m.start()].count("\n")+1,
                                            "kind": "possible WASI/host access"}
                                           for m in list(RISK.finditer(text[:64000]))[:12]],
                          "validated": False, "executed": False})
    # Reject symlinked control files that a walker may silently skip.
    for name in MANIFESTS:
        target = root / name
        if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked WebAssembly manifest is forbidden.")
    tools = [{"name": name, "status": "installed_not_executed" if shutil.which(name)
              else "unavailable"} for name in TOOLS]
    return {"schema": "1.0.0", "files": files, "manifests": manifests,
            "inventory_sha256": digest.hexdigest(), "scan_incomplete": incomplete,
            "toolchains": tools, "project_trusted": studio._trusted(root, studio._load()),
            "source_executed": False, "build_started": False, "runtime_started": False,
            "component_linked": False, "network_started": False,
            "wasi_permissions_granted": False, "deployment_started": False,
            "central_agent_studio": "developer",
            "limitations": ("WASM magic/version detection is not binary validation. "
                            "WIT/WAT declarations are heuristic. WASI preview versions, "
                            "component model compatibility, runtime permissions and "
                            "sandbox boundaries require independent toolchain and "
                            "host capability checks. No build/runtime output is claimed.")}


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))

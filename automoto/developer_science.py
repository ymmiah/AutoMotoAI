"""Developer Studio V28 — evidence-first R, Julia, Octave scientific experiments.

Discovery reads bounded data, source, notebooks and package locks without
executing them. An approved experiment runs only the fixed per-language
fixture paths in an ephemeral copy and validates its numerical output against
a separately computed Decimal reference. Interpreters are NOT sandboxed.
"""
from __future__ import annotations

import base64
import csv
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_jvm as jvm
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/science", tags=["developer-science"])
SCHEMA = "1.0.0"
LOCK = threading.Lock()
MAX_FILES = 90
MAX_SOURCE = 196 * 1024
MAX_DATA = 128 * 1024
MAX_NOTEBOOK = 256 * 1024
MAX_TOTAL = 3 * 1024 * 1024
TIMEOUT = 110
EXPERIMENT = "experiment.json"
SCRIPTS = {
    "r": "experiments/compute.R",
    "julia": "experiments/compute.jl",
    "octave": "experiments/compute.m",
}
EXECUTABLES = {"r": "Rscript", "julia": "julia", "octave": "octave"}
TOOLS = ("Rscript", "R", "julia", "octave", "matlab", "jupyter", "quarto")
LOCKFILES = ("renv.lock", "Project.toml", "Manifest.toml", "octave-packages.json")
DATA = "data/measurements.csv"
OUTPUT = re.compile(
    r"(?m)^V28_(R|JULIA|OCTAVE)_PASS count=(\d{1,4}) "
    r"sum=(-?\d{1,9}(?:\.\d{1,9})?) mean=(-?\d{1,9}(?:\.\d{1,9})?)\s*$"
)
VALUE = re.compile(r"-?\d{1,7}(?:\.\d{1,6})?\Z")
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,59}\Z")


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    task: Literal["version", "reproduce"]
    language: Literal["r", "julia", "octave"]
    tool: Literal["Rscript", "julia", "octave"]
    expected_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_toolchain_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_scientific_code_and_network_risk: Literal[True]


def _type(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if path == EXPERIMENT or path in LOCKFILES:
        return "manifest"
    if path == DATA:
        return "data"
    if path in SCRIPTS.values():
        return "source"
    if path.endswith(".ipynb") and (
            path.startswith("notebooks/") and path.count("/") == 1):
        return "notebook"
    if path.startswith("experiments/") and path.count("/") == 1 and (
            name.endswith((".R", ".r", ".jl", ".m"))):
        return "source"
    return None


def _inventory(root: Path) -> tuple[dict, str, bool]:
    found, digest = {}, hashlib.sha256(b"automoto-v28-scientific-inventory\0")
    size, incomplete = 0, False
    for name, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        kind = _type(name)
        if kind is None:
            continue
        if len(found) >= MAX_FILES:
            incomplete = True
            break
        limit = (MAX_NOTEBOOK if kind == "notebook" else
                 MAX_DATA if kind == "data" else MAX_SOURCE)
        _, sha, bytes_read = jvm._read(root, name, limit)
        size += bytes_read
        if size > MAX_TOTAL:
            incomplete = True
            break
        found[name] = {"path": name, "kind": kind, "bytes": bytes_read,
                       "sha256": sha}
        digest.update(name.encode() + b"\0" + sha.encode() + b"\0")
    for name in [EXPERIMENT, DATA, *SCRIPTS.values(), *LOCKFILES]:
        path = root / name
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise HTTPException(403, "Linked scientific source or data is forbidden.")
    return found, digest.hexdigest(), incomplete


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise HTTPException(422, "Experimental values must be finite decimals.")
    token = str(value)
    if not VALUE.fullmatch(token):
        raise HTTPException(422, "Experimental decimal exceeds bounded precision or range.")
    try:
        d = Decimal(token)
    except InvalidOperation as exc:
        raise HTTPException(422, "Invalid experimental decimal.") from exc
    return d


def _reference(root: Path, items: dict) -> tuple[dict | None, list[str]]:
    if EXPERIMENT not in items:
        return None, ["No root experiment.json: scientific execution unavailable."]
    raw = jvm._read(root, EXPERIMENT, MAX_SOURCE)[0]
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise HTTPException(422, "Invalid experiment.json.") from exc
    if (not isinstance(data, dict) or set(data) !=
            {"version", "name", "dataset", "column", "expected", "scripts"}):
        raise HTTPException(422, "Unexpected or missing experiment metadata.")
    if (type(data["version"]) is not int or data["version"] != 1 or
            not isinstance(data["name"], str) or not NAME.fullmatch(data["name"]) or
            data["dataset"] != DATA or data["column"] != "value" or
            not isinstance(data["scripts"], dict) or data["scripts"] != SCRIPTS):
        raise HTTPException(422, "Experiment must use the reviewed fixed dataset and scripts.")
    if not isinstance(data["expected"], dict) or set(data["expected"]) != {
            "count", "sum", "mean"}:
        raise HTTPException(422, "Experiment expected values must be count/sum/mean.")
    if type(data["expected"]["count"]) is not int:
        raise HTTPException(422, "Expected count must be an integer.")
    expected_count = data["expected"]["count"]
    if not 2 <= expected_count <= 500:
        raise HTTPException(422, "Expected experiment count out of range.")
    expected_sum = _decimal(data["expected"]["sum"])
    expected_mean = _decimal(data["expected"]["mean"])
    if DATA not in items:
        return None, ["Experiment dataset is missing."]
    raw_data = jvm._read(root, DATA, MAX_DATA)[0]
    try:
        csv_file = csv.reader(io.StringIO(raw_data, newline=""), strict=True)
        heading = next(csv_file, None)
        rows = list(csv_file)
    except (csv.Error, UnicodeError) as exc:
        raise HTTPException(422, "Invalid or oversized experimental CSV.") from exc
    if heading != ["value"] or not 2 <= len(rows) <= 500:
        raise HTTPException(422, "Data must be a value-column CSV with 2–500 observations.")
    if any(len(row) != 1 for row in rows):
        raise HTTPException(422, "Experimental CSV must contain exactly one numeric column.")
    numeric = [_decimal(row[0]) for row in rows]
    with localcontext() as ctx:
        ctx.prec = 34
        total = sum(numeric, Decimal(0))
        mean = total / len(numeric)
    agrees = (expected_count == len(numeric) and expected_sum == total
              and abs(expected_mean - mean) <= Decimal("0.000001"))
    reference = {
        "name": data["name"], "dataset": DATA, "column": "value",
        "source": SCRIPTS, "rows": len(numeric),
        "calculated_count": len(numeric), "calculated_sum": str(total),
        "calculated_mean": str(mean),
        "expected": data["expected"],
        "expected_matches_data": agrees,
        "manifest_sha256": items[EXPERIMENT]["sha256"],
        "data_sha256": items[DATA]["sha256"],
        "source_sha256": {
            lang: items[file]["sha256"] if file in items else None
            for lang, file in SCRIPTS.items()},
    }
    warnings = [] if agrees else ["Manifest expected values do not match Decimal computation."]
    for lang, path in SCRIPTS.items():
        if path not in items:
            warnings.append(f"Missing {lang} fixture: {path}.")
    return reference, warnings


def _notebooks(root: Path, items: dict) -> list[dict]:
    result = []
    for file, info in items.items():
        if info["kind"] != "notebook":
            continue
        try:
            data = json.loads(jvm._read(root, file, MAX_NOTEBOOK)[0])
        except (ValueError, RecursionError) as exc:
            raise HTTPException(422, "Invalid scientific notebook JSON.") from exc
        if not isinstance(data, dict) or data.get("nbformat") != 4:
            raise HTTPException(422, "Unsupported Jupyter notebook format.")
        cells = data.get("cells")
        if not isinstance(cells, list) or len(cells) > 65:
            raise HTTPException(422, "Notebook cells exceed inspection bounds.")
        if any(not isinstance(cell, dict) or
               cell.get("cell_type") not in ("code", "markdown", "raw")
               for cell in cells):
            raise HTTPException(422, "Malformed notebook cell.")
        meta = data.get("metadata", {})
        if not isinstance(meta, dict):
            raise HTTPException(422, "Invalid notebook metadata.")
        kernel = meta.get("kernelspec") or {}
        if not isinstance(kernel, dict):
            kernel = {}
        result.append({"path": file, "sha256": info["sha256"],
                       "cells": len(cells),
                       "code_cells": sum(c["cell_type"] == "code" for c in cells),
                       "kernel_declared": str(kernel.get("name", ""))[:60],
                       "outputs_not_trusted": True,
                       "executed": False})
    return result


def _packages(root: Path, items: dict) -> dict:
    result = {"locks": {}, "parsed_only": True, "packages_installed": False}
    for filename in LOCKFILES:
        if filename not in items:
            continue
        entry = {"sha256": items[filename]["sha256"],
                 "bytes": items[filename]["bytes"],
                 "verified_runtime_packages": False}
        if filename == "renv.lock":
            try:
                data = json.loads(jvm._read(root, filename, MAX_SOURCE)[0])
            except (ValueError, RecursionError) as exc:
                raise HTTPException(422, "Invalid R renv.lock JSON.") from exc
            pkgs = data.get("Packages", {}) if isinstance(data, dict) else {}
            if not isinstance(pkgs, dict) or len(pkgs) > 250:
                raise HTTPException(422, "R package lockfile exceeds safe structure limit.")
            entry["declared_versions"] = {
                str(name)[:75]: str(value.get("Version", ""))[:30]
                for name, value in list(pkgs.items())[:80] if isinstance(value, dict)}
        else:
            entry["declared_versions"] = {}
        result["locks"][filename] = entry
    return result


def _tools(root: Path) -> tuple[list[dict], str]:
    items, digest = [], hashlib.sha256(b"automoto-v28-scientific-tools\0")
    for name in TOOLS:
        path = shutil.which(name)
        if not path:
            item = {"name": name, "status": "unavailable"}
        elif Path(path).suffix.casefold() in (".cmd", ".bat", ".ps1"):
            item = {"name": name, "status": "shell_wrapper_blocked"}
        else:
            try:
                item = {"name": name, "status": "installed_not_executed",
                        **adapters._fingerprint(str(Path(path).absolute()), root)}
            except HTTPException:
                item = {"name": name, "status": "untrusted_executable"}
        items.append(item)
        digest.update(name.encode() + b"\0" + item["status"].encode() + b"\0"
                      + item.get("sha256", "").encode() + b"\0"
                      + item.get("executable", "").encode())
    return items, digest.hexdigest()


def _inspect(root: Path) -> dict:
    files, inventory_sha, incomplete = _inventory(root)
    reference, warnings = _reference(root, files)
    notebooks = _notebooks(root, files)
    packages = _packages(root, files)
    tools, tool_sha = _tools(root)
    if incomplete:
        warnings.append("Bounded scientific inventory incomplete; execution refused.")
    return {"schema": SCHEMA, "files": list(files.values()),
            "experiment": reference, "notebooks": notebooks, "packages": packages,
            "toolchains": tools, "inventory_sha256": inventory_sha,
            "toolchain_sha256": tool_sha, "warnings": warnings,
            "scan_incomplete": incomplete,
            "safe_to_offer_reproduction": bool(reference and
                                               reference["expected_matches_data"] and
                                               not warnings and not incomplete),
            "project_trusted": studio._trusted(root, studio._load()),
            "plot_preview_status": "not_rendered_during_inspection",
            "plot_engine": "R PNG graphics supported in a consented fixture; other languages numerical-only.",
            "matlab": "Proprietary MATLAB runtime discovery only; execution not admitted.",
            "notebook_policy": "Bounded Jupyter JSON metadata, never evaluate cells or trust saved outputs.",
            "execution": "Not performed during inspection; external interpreters are unsandboxed.",
            "source_executed": False, "package_manager_invoked": False,
            "dataset_modified": False, "notebook_executed": False,
            "deployment_started": False, "central_agent_studio": "developer",
            "agent_deployment_handoff_required": True,
            "platform": sys.platform}


def _stage(root: Path, files: list[dict], dest: Path) -> None:
    total = 0
    for entry in files:
        path = entry["path"]
        if path.startswith("/") or "\\" in path or ".." in path.split("/"):
            raise HTTPException(403, "Unsafe scientific input path.")
        target = studio._path(root, path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(target, flags)
            with os.fdopen(fd, "rb") as handle:
                meta = os.fstat(handle.fileno())
                if not stat.S_ISREG(meta.st_mode) or meta.st_size != entry["bytes"]:
                    raise HTTPException(409, "Experiment source changed size or type.")
                raw = handle.read(entry["bytes"] + 1)
        except OSError as exc:
            raise HTTPException(403, "Experiment input staging refused.") from exc
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise HTTPException(409, "Scientific source or dataset changed after consent.")
        total += len(raw)
        if total > MAX_TOTAL:
            raise HTTPException(413, "Experiment staging exceeds size cap.")
        output = dest / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(raw)


def _env(root: Path, tmp: Path) -> dict:
    env = adapters._environment(root)
    for name in ("home", "tmp", "r-libs", "julia-depot", "octave-home"):
        (tmp / name).mkdir(mode=0o700)
    env.update({
        "HOME": str(tmp / "home"), "TMPDIR": str(tmp / "tmp"),
        "R_LIBS_USER": str(tmp / "r-libs"),
        "R_ENVIRON_USER": str(tmp / "home" / "missing-Renviron"),
        "R_PROFILE_USER": str(tmp / "home" / "missing-Rprofile"),
        "R_HISTFILE": str(tmp / "home" / "Rhistory"),
        "JULIA_DEPOT_PATH": str(tmp / "julia-depot"),
        "JULIA_PKG_OFFLINE": "true", "JULIA_NUM_THREADS": "1",
        "OCTAVE_HISTFILE": str(tmp / "home" / "octave_history"),
        "GNUTERM": "dumb", "CI": "true",
        "TZ": "UTC",
    })
    return env


def _commands(lang: str, exe: str, stage: Path) -> tuple[list[str], list[str]]:
    # Entrypoints are fixed and cannot be controlled by the API caller.
    versions = {
        "r": [exe, "--version"],
        "julia": [exe, "--version"],
        "octave": [exe, "--version"],
    }
    commands = {
        "r": [exe, "--vanilla", SCRIPTS["r"]],
        "julia": [exe, "--startup-file=no", "--history-file=no",
                  "--project=@stdlib", SCRIPTS["julia"]],
        "octave": [exe, "--no-gui", "--no-init-file", "--no-site-file",
                   "--no-history", "--quiet", SCRIPTS["octave"]],
    }
    return versions[lang], commands[lang]


def _run(root: Path, body: RunIn) -> dict:
    adapters._trusted(root)
    before = _inspect(root)
    if (before["inventory_sha256"] != body.expected_inventory_sha256 or
            before["toolchain_sha256"] != body.expected_toolchain_sha256):
        raise HTTPException(409, "Scientific sources or toolchain changed after consent.")
    expected_tool = EXECUTABLES[body.language]
    if body.tool != expected_tool:
        raise HTTPException(422, "Requested tool does not match the selected language.")
    tool = next((x for x in before["toolchains"]
                 if x["name"] == expected_tool and
                 x["status"] == "installed_not_executed"), None)
    if (not tool or tool.get("executable") != body.expected_executable or
            tool.get("sha256") != body.expected_sha256):
        raise HTTPException(409, "Approved scientific executable fingerprint differs.")
    if body.task == "reproduce" and (
            not before["safe_to_offer_reproduction"] or
            not before["experiment"]["source_sha256"][body.language]):
        raise HTTPException(409, "Scientific experiment is missing or not reproducible.")
    with tempfile.TemporaryDirectory(prefix="automoto-science28-") as dirname:
        tmp = Path(dirname)
        stage = tmp / "project"
        stage.mkdir(mode=0o700)
        if body.task == "reproduce":
            _stage(root, before["files"], stage)
            (stage / "outputs").mkdir(mode=0o700)
        env = _env(root, tmp)
        version, computation = _commands(body.language, tool["executable"], stage)
        commands = [version] if body.task == "version" else [version, computation]
        output, began = [], time.monotonic()
        for cmd in commands:
            current = _inspect(root)
            if (current["inventory_sha256"] != body.expected_inventory_sha256 or
                    current["toolchain_sha256"] != body.expected_toolchain_sha256):
                raise HTTPException(409, "Scientific inputs changed during execution.")
            adapters._trusted(root)
            budget = TIMEOUT - (time.monotonic() - began)
            if budget < 5:
                output.append({"status": "timeout", "output": "Overall experiment time limit exceeded.",
                               "elapsed_ms": 0, "exit_code": None})
                break
            result = native._execute(stage, cmd, env, timeout=int(budget))
            output.append(result)
            if result["status"] != "completed":
                break
        last = output[-1]
        result = {"task": body.task, "language": body.language,
                  "status": last["status"], "exit_code": last["exit_code"],
                  "output": "\n".join(x["output"] for x in output)[:native.MAX_OUTPUT],
                  "tool_version_output": output[0]["output"][:2000],
                  "tool_sha256": tool["sha256"],
                  "inventory_sha256": before["inventory_sha256"],
                  "source_sha256": before["experiment"]["source_sha256"][body.language]
                  if before["experiment"] else None,
                  "manifest_sha256": before["experiment"]["manifest_sha256"]
                  if before["experiment"] else None,
                  "data_sha256": before["experiment"]["data_sha256"]
                  if before["experiment"] else None,
                  "package_locks": before["packages"]["locks"],
                  "elapsed_ms": sum(x["elapsed_ms"] for x in output),
                  "temporary_project_deleted": True,
                  "external_code_unsandboxed": True, "os_network_isolation": False,
                  "notebook_executed": False, "package_installation_started": False,
                  "original_dataset_modified": "not_verified",
                  "deployment_started": False, "agent_handoff_created": False,
                  "central_agent_studio": "developer"}
        if body.task != "reproduce":
            return result
        reference = before["experiment"]
        match = OUTPUT.search(last["output"]) if last["status"] == "completed" else None
        valid = False
        if match and match.group(1) == body.language.upper():
            try:
                counted = int(match.group(2))
                total = _decimal(match.group(3))
                mean = _decimal(match.group(4))
                valid = (counted == reference["calculated_count"] and
                         abs(total - Decimal(reference["calculated_sum"])) < Decimal("0.000001")
                         and abs(mean - Decimal(reference["calculated_mean"])) < Decimal("0.000001"))
            except (InvalidOperation, HTTPException):
                valid = False
        result["reproduced"] = valid
        result["reference"] = reference
        if last["status"] == "completed" and not valid:
            result["status"] = "validation_failed"
        plot = stage / "outputs" / "plot.png"
        result["plot_png_sha256"] = None
        result["plot_base64"] = None
        if body.language == "r" and plot.is_file() and not plot.is_symlink():
            raw = plot.read_bytes() if plot.stat().st_size <= 180 * 1024 else b""
            if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) > 500:
                result["plot_png_sha256"] = hashlib.sha256(raw).hexdigest()
                result["plot_base64"] = base64.b64encode(raw).decode("ascii")
        return result


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/run")
def run(request: Request, body: RunIn):
    studio._auth(request)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "A scientific experiment is already executing.")
    try:
        return _run(studio._project(body.project), body)
    finally:
        LOCK.release()

"""Built-in offline models: GGUF files run by a pinned llama.cpp ``llama-server``.

Nothing here asks the user to install Ollama, Python, or llama.cpp. The first download
fetches the pinned runtime (and the chosen model) from the internet. After that, chat
uses only files already on this computer.

Full Moonshot Kimi K2 is listed so the size is honest, and it is not offered as a
download: the Q4 weights are hundreds of gigabytes. Smaller Kimi variants are.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, BinaryIO

from automoto import home

RUNTIME_TAG = "b12360"
RUNTIME_REPO = "https://github.com/ggml-org/llama.cpp/releases/download/b12360"
# GitHub release asset digests for llama.cpp b12360 CPU builds (13 Nov 2026).
_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("win32", "AMD64"): ("llama-b12360-bin-win-cpu-x64.zip",
                         "eae1726047e0eaa707b1302929d196c999b96c2f243b21aea6e93bcebacc4e17"),
    ("win32", "ARM64"): ("llama-b12360-bin-win-cpu-arm64.zip",
                         "269794d34c6d8f5c827f4558442ee28ae07b03a5daf64da8ce112ea477bef4fc"),
    ("darwin", "arm64"): ("llama-b12360-bin-macos-arm64.tar.gz",
                          "e815561e9621c606388d4538101d56fcf317cdec6ce8f2bbd1bf14f0df29925e"),
    ("darwin", "x86_64"): ("llama-b12360-bin-macos-x64.tar.gz",
                           "ed329ff7f4048dbfbc401909926a6c6f49114fc7cb7860ed9c7976fadcc11a34"),
    ("linux", "x86_64"): ("llama-b12360-bin-ubuntu-x64.tar.gz",
                          "b60dc211e4ba206bb04bbc9eb06294364c43d0aab8fc308c44a361477466ba4c"),
    ("linux", "aarch64"): ("llama-b12360-bin-ubuntu-arm64.tar.gz",
                           "a8e2783d74e3e77c4f5e31fbe88e6365c98dffbeb203a1031737121764b62a2a"),
}
_ID = re.compile(r"^[a-z][a-z0-9.-]{0,48}$")
_CUSTOM = re.compile(r"^custom-[a-z0-9-]{1,40}$")
_MAGIC = b"GGUF"
_MAX_GGUF = 80 * 1024 ** 3
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_PROC: subprocess.Popen[Any] | None = None
_PROC_PORT: int | None = None
_PROC_MODEL: str | None = None


@dataclass(frozen=True)
class GGUFModel:
    id: str
    family: str
    label: str
    repo: str
    filename: str
    download_gb: float
    min_ram_gb: float
    comfort_ram_gb: float
    params: str
    tools: bool
    note: str
    license: str
    downloadable: bool = True


# Sizes are the Q4_K_M files named below (checked against the Hugging Face repos, Nov 2026).
CATALOG: tuple[GGUFModel, ...] = (
    GGUFModel(
        "kimi-k2", "Kimi", "Kimi K2 (full, about 1 trillion parameters)",
        "bartowski/moonshotai_Kimi-K2-Instruct-0905-GGUF", "",
        624, 640, 640, "~1T MoE", True,
        "Moonshot's full Kimi K2, even as Q4, is about 624 GB and is split across many files. "
        "A normal PC cannot run it. Use a smaller Kimi row instead.",
        "Modified MIT (Moonshot Kimi K2)", downloadable=False,
    ),
    GGUFModel(
        "kimi-vl-a3b", "Kimi", "Kimi-VL A3B Thinking (Q4)",
        "ggml-org/Kimi-VL-A3B-Thinking-2506-GGUF", "Kimi-VL-A3B-Thinking-2506-Q4_K_M.gguf",
        10.0, 16, 24, "16B, about 3B active", True,
        "Moonshot's open Kimi-VL model. About 16 billion parameters with about 3 billion active, "
        "quantised to Q4_K_M. Text chat works offline. This download does not include the separate "
        "image projector, so pictures are not understood.",
        "MIT (Moonshot Kimi-VL)",
    ),
    GGUFModel(
        "kimi-k2-distill-32b", "Kimi", "Kimi K2 thinking distill, 32B (Q4)",
        "mradermacher/Qwen3-32B-Kimi-K2-Thinking-Distill-GGUF",
        "Qwen3-32B-Kimi-K2-Thinking-Distill.Q4_K_M.gguf",
        19.9, 32, 40, "32B distill", True,
        "A community distill of Kimi K2's thinking style into Qwen3 32B. It is not Moonshot's "
        "original trillion-parameter weights. Q4_K_M is about 20 GB and wants about 32 GB of memory.",
        "Community quant of a Qwen3 distill",
    ),
    GGUFModel(
        "qwen2.5-0.5b", "Qwen", "Qwen 2.5 0.5B Instruct (Q4)",
        "Qwen/Qwen2.5-0.5B-Instruct-GGUF", "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        0.4, 2, 4, "0.5B", True,
        "Tiny and fast. Fine for short chats. Weak at long tasks.",
        "Apache-2.0",
    ),
    GGUFModel(
        "qwen2.5-1.5b", "Qwen", "Qwen 2.5 1.5B Instruct (Q4)",
        "Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        1.1, 4, 6, "1.5B", True,
        "Small and quick. Suitable for simple writing and short tasks.",
        "Apache-2.0",
    ),
    GGUFModel(
        "qwen2.5-3b", "Qwen", "Qwen 2.5 3B Instruct (Q4)",
        "Qwen/Qwen2.5-3B-Instruct-GGUF", "qwen2.5-3b-instruct-q4_k_m.gguf",
        2.0, 6, 8, "3B", True,
        "A practical everyday model on a laptop CPU.",
        "Apache-2.0",
    ),
    GGUFModel(
        "qwen2.5-7b", "Qwen", "Qwen 2.5 7B Instruct (Q4)",
        "bartowski/Qwen2.5-7B-Instruct-GGUF", "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        4.7, 8, 16, "7B", True,
        "Stronger writing and tool steps. Tight on 8 GB; 16 GB is comfortable.",
        "Apache-2.0",
    ),
    GGUFModel(
        "llama-3.2-1b", "Llama", "Llama 3.2 1B Instruct (Q4)",
        "bartowski/Llama-3.2-1B-Instruct-GGUF", "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        0.8, 4, 6, "1B", True,
        "Meta's small Llama 3.2. Short chats and simple tasks.",
        "Llama 3.2 Community License",
    ),
    GGUFModel(
        "llama-3.2-3b", "Llama", "Llama 3.2 3B Instruct (Q4)",
        "bartowski/Llama-3.2-3B-Instruct-GGUF", "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        2.0, 6, 8, "3B", True,
        "A small Llama that can follow everyday instructions.",
        "Llama 3.2 Community License",
    ),
    GGUFModel(
        "llama-3.1-8b", "Llama", "Llama 3.1 8B Instruct (Q4)",
        "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF", "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        4.9, 10, 16, "8B", True,
        "A stronger general Llama. Needs about 16 GB to feel comfortable.",
        "Llama 3.1 Community License",
    ),
    GGUFModel(
        "mistral-7b", "Mistral", "Mistral 7B Instruct v0.3 (Q4)",
        "bartowski/Mistral-7B-Instruct-v0.3-GGUF", "Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
        4.4, 8, 16, "7B", True,
        "Mistral's 7B instruct model, Q4_K_M. Solid writing on a 16 GB PC.",
        "Apache-2.0",
    ),
    GGUFModel(
        "gemma-3-1b", "Gemma", "Gemma 3 1B (Q4)",
        "bartowski/google_gemma-3-1b-it-GGUF", "google_gemma-3-1b-it-Q4_K_M.gguf",
        0.8, 4, 6, "1B", False,
        "Google's small Gemma 3. Good for short chats. Tool steps use the slower text format.",
        "Gemma Terms of Use",
    ),
    GGUFModel(
        "gemma-3-4b", "Gemma", "Gemma 3 4B (Q4)",
        "bartowski/google_gemma-3-4b-it-GGUF", "google_gemma-3-4b-it-Q4_K_M.gguf",
        3.3, 8, 12, "4B", False,
        "A larger Gemma 3. Better writing than the 1B, still no native tool calling.",
        "Gemma Terms of Use",
    ),
    GGUFModel(
        "deepseek-r1-1.5b", "DeepSeek", "DeepSeek R1 distill Qwen 1.5B (Q4)",
        "bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF", "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        1.1, 4, 6, "1.5B distill", True,
        "A small reasoning distill. Slower per answer because it thinks, and weaker than the 8B.",
        "MIT",
    ),
    GGUFModel(
        "deepseek-r1-8b", "DeepSeek", "DeepSeek R1 distill Llama 8B (Q4)",
        "bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF", "DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf",
        4.9, 10, 16, "8B distill", True,
        "A stronger reasoning distill. Expect slower answers on a CPU.",
        "MIT",
    ),
    GGUFModel(
        "phi-3.5-mini", "Phi", "Phi-3.5 mini Instruct (Q4)",
        "bartowski/Phi-3.5-mini-instruct-GGUF", "Phi-3.5-mini-instruct-Q4_K_M.gguf",
        2.4, 6, 8, "3.8B", True,
        "Microsoft's small Phi-3.5. A good fit for an 8 GB laptop.",
        "MIT",
    ),
    GGUFModel(
        "phi-4-mini", "Phi", "Phi-4 mini Instruct (Q4)",
        "bartowski/microsoft_Phi-4-mini-instruct-GGUF", "microsoft_Phi-4-mini-instruct-Q4_K_M.gguf",
        2.5, 6, 8, "3.8B", True,
        "Microsoft's newer small Phi. Similar size to Phi-3.5 mini.",
        "MIT",
    ),
)


def by_id(model_id: str) -> GGUFModel | None:
    for model in CATALOG:
        if model.id == model_id:
            return model
    return None


def valid_id(model_id: str) -> bool:
    if not isinstance(model_id, str) or ".." in model_id or "/" in model_id or "\\" in model_id:
        return False
    if not _ID.match(model_id):
        return False
    return by_id(model_id) is not None or bool(_CUSTOM.match(model_id))


def models_dir() -> Path:
    path = home.home() / "models" / "gguf"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_dir() -> Path:
    path = home.base() / "llama" / RUNTIME_TAG
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path() -> Path:
    return models_dir() / "index.json"


def _load_index() -> dict[str, Any]:
    try:
        data = json.loads(_index_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _save_index(data: dict[str, Any]) -> None:
    path = _index_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _selected() -> str | None:
    try:
        from automoto import settings

        value = settings.get("gguf_model")
    except Exception:
        return None
    return value if isinstance(value, str) and valid_id(value) else None


def _installed_path(model_id: str) -> Path | None:
    entry = _load_index().get(model_id)
    if isinstance(entry, dict) and entry.get("file"):
        path = models_dir() / str(entry["file"])
        if path.is_file() and _inside(path, models_dir()):
            return path
    model = by_id(model_id)
    if model and model.filename:
        path = models_dir() / model.filename
        if path.is_file():
            return path
    return None


def installed_ids() -> list[str]:
    found = []
    for model in CATALOG:
        if model.downloadable and _installed_path(model.id):
            found.append(model.id)
    for key, entry in _load_index().items():
        if key in found or not _CUSTOM.match(key):
            continue
        if isinstance(entry, dict) and _installed_path(key):
            found.append(key)
    return found


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _free_gb() -> float | None:
    try:
        return shutil.disk_usage(models_dir()).free / 1024 ** 3
    except OSError:
        return None


def assess(model: GGUFModel, hw: dict[str, Any], *, free_gb: float | None = None,
           installed: bool = False) -> dict[str, Any]:
    """Whether this computer can run (and, if needed, download) the model."""
    if not model.downloadable:
        return {"can_run": False, "can_download": False, "reason": model.note}
    reasons: list[str] = []
    can_run = True
    ram = hw.get("ram_gb")
    if ram is None:
        reasons.append(
            f"This computer's memory size could not be read. {model.label} needs about "
            f"{model.min_ram_gb:.0f} GB. Download it only if you have that much."
        )
    elif ram + 0.6 < model.min_ram_gb:
        can_run = False
        reasons.append(
            f"This computer has about {ram:.0f} GB of memory. {model.label} needs about "
            f"{model.min_ram_gb:.0f} GB, so it would stall instead of answering."
        )
    elif model.comfort_ram_gb and ram + 0.6 < model.comfort_ram_gb:
        reasons.append(
            f"It can run in about {ram:.0f} GB, but {model.comfort_ram_gb:.0f} GB would be more "
            "comfortable. Answers will be slower."
        )
    can_download = can_run or installed
    if not installed and free_gb is not None and free_gb < model.download_gb + 0.5:
        can_download = False
        reasons.append(
            f"The file is about {model.download_gb:g} GB and this disk has about {free_gb:.0f} GB free."
        )
    if not reasons and can_run:
        reasons.append(f"About {model.download_gb:g} GB on disk and {model.min_ram_gb:.0f} GB of memory.")
    return {"can_run": can_run, "can_download": can_download and model.downloadable,
            "reason": " ".join(reasons)}


def recommend(hw: dict[str, Any] | None = None) -> dict[str, Any]:
    from automoto import local_llm

    hw = hw or local_llm.hardware()
    free = _free_gb()
    present = set(installed_ids())
    rows = []
    runnable_tools: list[GGUFModel] = []
    for model in CATALOG:
        fit = assess(model, hw, free_gb=free, installed=model.id in present)
        row = {**asdict(model), **fit, "installed": model.id in present,
               "bytes": (_installed_path(model.id).stat().st_size if model.id in present else None)}
        rows.append(row)
        if model.downloadable and model.tools and fit["can_run"]:
            runnable_tools.append(model)
    ram = hw.get("ram_gb") or 0
    comfortable = [model for model in runnable_tools if ram + 0.6 >= model.comfort_ram_gb] or runnable_tools
    best = max(comfortable, key=lambda model: (model.min_ram_gb, model.id)).id if comfortable else None
    if best is None:
        for row in rows:
            if row["downloadable"] and row["can_run"]:
                best = row["id"]
                break
    if best:
        why = (f"This computer has about {ram:.0f} GB of memory. " if ram else
               "Memory size could not be read. ") + "The built-in engine runs a GGUF file on the CPU. No Ollama install is required."
    else:
        why = "No curated model fits the memory that could be read on this computer."
    return {"best": best, "why": why, "hardware": hw, "free_gb": None if free is None else round(free, 1),
            "models": rows}


def _asset() -> tuple[str, str]:
    machine = platform.machine()
    if machine in ("AMD64", "x86_64", "x64"):
        machine = "AMD64" if sys.platform == "win32" else "x86_64"
    if machine in ("ARM64", "aarch64") and sys.platform == "win32":
        machine = "ARM64"
    if machine == "arm64" and sys.platform == "linux":
        machine = "aarch64"
    found = _ASSETS.get((sys.platform, machine))
    if not found:
        raise ValueError(
            f"No built-in engine build is published for {sys.platform} {platform.machine()}. "
            "You can still import a GGUF file and point LOCAL_LLM_URL at a llama.cpp server you start yourself."
        )
    return found


def runtime_status() -> dict[str, Any]:
    binary = _find_binary(runtime_dir())
    try:
        asset, digest = _asset()
        supported = True
    except ValueError as exc:
        asset, digest, supported = "", "", False
        message = str(exc)
    else:
        message = ""
    running = _PROC is not None and _PROC.poll() is None
    return {"tag": RUNTIME_TAG, "installed": binary is not None, "running": running,
            "binary": str(binary) if binary else None, "asset": asset, "sha256": digest,
            "supported": supported, "message": message, "port": _PROC_PORT if running else None}


def _find_binary(root: Path) -> Path | None:
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    if not root.is_dir():
        return None
    for path in root.rglob(name):
        if path.is_file() and _inside(path, root):
            return path
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path, *, expected: str | None, job: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "AutoMotoAI"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - pinned https host
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        digest = hashlib.sha256()
        with tmp.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if job in _JOBS:
                    percent = int(100 * done / total) if total else 0
                    _JOBS[job]["percent"] = percent
                    _JOBS[job]["bytes"] = done
        got = digest.hexdigest()
    if expected and got != expected:
        tmp.unlink(missing_ok=True)
        raise ValueError("The download did not match the pinned checksum, so it was discarded.")
    tmp.replace(dest)


def _safe_extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                target = (dest / info.filename).resolve()
                if not _inside(target, dest) or info.filename.startswith(("/", "\\")):
                    raise ValueError("The engine archive contained an unsafe path.")
            zf.extractall(dest)
        return
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            target = (dest / member.name).resolve()
            if not _inside(target, dest) or member.name.startswith(("/", "\\")):
                raise ValueError("The engine archive contained an unsafe path.")
            if member.issym() or member.islnk():
                raise ValueError("The engine archive contained a link, which was refused.")
        tf.extractall(dest)


def ensure_runtime() -> dict[str, Any]:
    """Download the pinned llama.cpp CPU build once. Later chats do not need the network."""
    current = runtime_status()
    if current["installed"]:
        return {**current, "downloaded": False}
    if not current["supported"]:
        raise ValueError(current["message"])
    name, digest = current["asset"], current["sha256"]
    archive = runtime_dir() / name
    url = f"{RUNTIME_REPO}/{name}"
    _JOBS["runtime"] = {"id": "runtime", "state": "downloading", "percent": 0, "error": None}
    try:
        _download(url, archive, expected=digest, job="runtime")
        _safe_extract(archive, runtime_dir())
        archive.unlink(missing_ok=True)
    except Exception as exc:
        _JOBS["runtime"] = {"id": "runtime", "state": "error", "percent": 0, "error": str(exc)[:300]}
        raise
    binary = _find_binary(runtime_dir())
    if binary is None:
        raise ValueError("The engine archive did not contain llama-server.")
    if sys.platform != "win32":
        binary.chmod(binary.stat().st_mode | 0o755)
    _JOBS["runtime"] = {"id": "runtime", "state": "done", "percent": 100, "error": None}
    return {**runtime_status(), "downloaded": True}


def _record(model_id: str, filename: str, *, label: str, family: str, source: str) -> None:
    data = _load_index()
    data[model_id] = {"file": filename, "label": label, "family": family, "source": source}
    _save_index(data)


def pull(model_id: str) -> dict[str, Any]:
    model = by_id(model_id)
    if model is None or not model.downloadable:
        raise ValueError("That model is not in the downloadable catalog.")
    fit = assess(model, _hw(), free_gb=_free_gb(), installed=False)
    if not fit["can_download"]:
        raise ValueError(fit["reason"])
    if _installed_path(model.id):
        return {"id": model.id, "state": "done", "percent": 100}
    with _LOCK:
        job = _JOBS.get(model.id)
        if job and job.get("state") == "downloading":
            return dict(job)
        _JOBS[model.id] = {"id": model.id, "state": "downloading", "percent": 0, "error": None}

    def run() -> None:
        dest = models_dir() / model.filename
        url = f"https://huggingface.co/{model.repo}/resolve/main/{model.filename}"
        try:
            _download(url, dest, expected=None, job=model.id)
            if dest.read_bytes()[:4] != _MAGIC:
                dest.unlink(missing_ok=True)
                raise ValueError("The file is not a GGUF model.")
            _record(model.id, model.filename, label=model.label, family=model.family, source=model.repo)
            _JOBS[model.id] = {"id": model.id, "state": "done", "percent": 100, "error": None}
        except Exception as exc:  # noqa: BLE001 - shown to the user
            _JOBS[model.id] = {"id": model.id, "state": "error", "percent": 0, "error": str(exc)[:300]}

    threading.Thread(target=run, daemon=True, name=f"gguf-pull-{model.id}").start()
    return dict(_JOBS[model.id])


def _hw() -> dict[str, Any]:
    from automoto import local_llm

    return local_llm.hardware()


def _slug(name: str) -> str:
    stem = Path(name).stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:40] or "model"
    return f"custom-{slug}"


def import_file(source: Path, *, label: str | None = None) -> dict[str, Any]:
    path = Path(source).expanduser()
    if path.suffix.lower() != ".gguf":
        raise ValueError("Import a file that ends in .gguf.")
    if not path.is_file():
        raise ValueError("That path is not a file.")
    if path.stat().st_size < 32 or path.stat().st_size > _MAX_GGUF:
        raise ValueError("That file is not a usable GGUF size.")
    with path.open("rb") as handle:
        if handle.read(4) != _MAGIC:
            raise ValueError("That file does not start with the GGUF marker, so it was not imported.")
    model_id = _slug(path.name)
    dest_name = f"{model_id}.gguf"
    dest = models_dir() / dest_name
    if _inside(path, models_dir()):
        dest = path
        dest_name = path.name
    else:
        shutil.copy2(path, dest)
    _record(model_id, dest_name, label=label or path.stem, family="Custom", source="import")
    return {"id": model_id, "file": dest_name, "label": label or path.stem}


def import_stream(handle: BinaryIO, filename: str) -> dict[str, Any]:
    if not filename or not filename.lower().endswith(".gguf"):
        raise ValueError("Choose a .gguf file.")
    model_id = _slug(filename)
    dest = models_dir() / f"{model_id}.gguf"
    tmp = dest.with_suffix(".part")
    size = 0
    try:
        with tmp.open("wb") as out:
            first = handle.read(4)
            if first != _MAGIC:
                raise ValueError("That file does not start with the GGUF marker, so it was not imported.")
            out.write(first)
            size = 4
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > _MAX_GGUF:
                    raise ValueError("That file is larger than 80 GB, so it was not imported.")
                out.write(chunk)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    _record(model_id, dest.name, label=Path(filename).stem, family="Custom", source="upload")
    return {"id": model_id, "file": dest.name, "bytes": size}


def delete(model_id: str) -> dict[str, Any]:
    path = _installed_path(model_id)
    if path is None or not _inside(path, models_dir()):
        raise ValueError("That model is not downloaded.")
    if _PROC_MODEL and Path(_PROC_MODEL).resolve() == path.resolve():
        stop()
    path.unlink()
    data = _load_index()
    data.pop(model_id, None)
    _save_index(data)
    if _selected() == model_id:
        from automoto import settings

        settings.update({"gguf_model": None})
    return {"ok": True, "id": model_id}


def use(model_id: str) -> dict[str, Any]:
    if _installed_path(model_id) is None:
        raise ValueError("Download the model before switching to it.")
    model = by_id(model_id)
    hw = _hw()
    if model:
        fit = assess(model, hw, installed=True)
        if not fit["can_run"]:
            raise ValueError(fit["reason"])
    from automoto import settings

    settings.update({"gguf_model": model_id})
    stop()
    return {"id": model_id, "selected": True}


def jobs() -> dict[str, Any]:
    return {key: dict(value) for key, value in _JOBS.items()}


def catalog_view() -> dict[str, Any]:
    rec = recommend()
    custom = []
    index = _load_index()
    for model_id in installed_ids():
        if by_id(model_id):
            continue
        entry = index.get(model_id) or {}
        path = _installed_path(model_id)
        custom.append({"id": model_id, "family": "Custom", "label": entry.get("label") or model_id,
                       "download_gb": round((path.stat().st_size if path else 0) / 1024 ** 3, 2),
                       "min_ram_gb": None, "note": "Imported GGUF file.", "license": "The file you supplied",
                       "downloadable": False, "installed": True, "can_run": True, "can_download": False,
                       "reason": "Imported from this computer. AutoMoto cannot promise it will fit in memory.",
                       "bytes": path.stat().st_size if path else 0})
    return {**rec, "custom": custom, "selected": _selected(), "runtime": runtime_status(), "jobs": jobs()}


def server_url() -> str | None:
    if _PROC is not None and _PROC.poll() is None and _PROC_PORT:
        return f"http://127.0.0.1:{_PROC_PORT}/v1"
    return None


def active_filename() -> str | None:
    selected = _selected()
    path = _installed_path(selected) if selected else None
    return path.name if path else None


def ready() -> bool:
    return _installed_path(_selected() or "") is not None


def build_command(binary: Path, model: Path, port: int, ctx: int) -> list[str]:
    threads = max(1, min(os.cpu_count() or 2, 8))
    return [str(binary), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
            "-c", str(ctx), "-t", str(threads)]


def _context(hw: dict[str, Any]) -> int:
    ram = hw.get("ram_gb") or 0
    return 8192 if ram >= 16 else 4096


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def stop() -> None:
    global _PROC, _PROC_PORT, _PROC_MODEL
    proc = _PROC
    _PROC = None
    _PROC_PORT = None
    _PROC_MODEL = None
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def ensure_running() -> str:
    """Start llama-server for the selected model. Returns the OpenAI-compatible base URL."""
    global _PROC, _PROC_PORT, _PROC_MODEL
    selected = _selected()
    model = _installed_path(selected or "")
    if model is None:
        raise ValueError("Choose a downloaded model in Settings > Offline AI first.")
    if _PROC is not None and _PROC.poll() is None and _PROC_MODEL == str(model) and _PROC_PORT:
        return f"http://127.0.0.1:{_PROC_PORT}/v1"
    stop()
    info = ensure_runtime()
    binary = Path(info["binary"] or "")
    if not binary.is_file():
        raise ValueError(info.get("message") or "The built-in engine is not available on this computer.")
    port = _free_port()
    ctx = _context(_hw())
    command = build_command(binary, model, port, ctx)
    if "127.0.0.1" not in command:
        raise ValueError("The engine must listen on this computer only.")
    options: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                               "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        options["start_new_session"] = True
    _PROC = subprocess.Popen(command, **options)
    _PROC_PORT = port
    _PROC_MODEL = str(model)
    url = f"http://127.0.0.1:{port}/v1"
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if _PROC.poll() is not None:
            stop()
            raise ValueError("The built-in engine stopped while loading the model. Pick a smaller model.")
        try:
            with urllib.request.urlopen(url + "/models", timeout=2) as response:  # noqa: S310 - loopback
                if response.status == 200:
                    return url
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.4)
    stop()
    raise ValueError("The model did not finish loading. It may be too large for this computer.")


def test_model(model_id: str) -> dict[str, Any]:
    """Load one downloaded model and ask it for a short reply. No network after the files exist."""
    if _installed_path(model_id) is None:
        raise ValueError("That model is not downloaded yet.")
    from automoto import settings

    previous = _selected()
    settings.update({"gguf_model": model_id})
    if previous != model_id:
        stop()
    started = time.monotonic()
    try:
        url = ensure_running()
        body = {"model": active_filename() or model_id,
                "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                "max_tokens": 16, "temperature": 0}
        request = urllib.request.Request(url.rstrip("/") + "/chat/completions",
                                         data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310 - loopback
            data = json.loads(response.read().decode("utf-8") or "{}")
    except ValueError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError(f"The model did not answer: {exc}") from exc
    choices = data.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    reply = str(message.get("content") or "").strip()
    return {"ok": bool(reply), "model": model_id, "reply": reply[:150],
            "seconds": round(time.monotonic() - started, 1), "engine": "llama.cpp"}


def reset_for_tests() -> None:
    """Stop a server and forget in-memory jobs. Does not delete files."""
    stop()
    _JOBS.clear()

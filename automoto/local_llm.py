"""Offline / local AI: Ollama and any OpenAI-compatible local server (llama.cpp, LM Studio…).

Nothing here needs an API key or the internet once a model is downloaded.

* ``offline()`` - Offline mode: only local AI is used and internet tools are switched off.
  On with ``AUTOMOTO_OFFLINE=1`` or the Settings switch.
* ``hardware()`` - RAM / GPU memory of this computer (best effort, no extra packages).
* ``recommend()`` - small tool-capable models that fit this computer, best first.
* ``ollama_status()`` / ``pull()`` - talk to the local Ollama server (default
  ``http://127.0.0.1:11434``, or ``OLLAMA_HOST``) to list and download models.

Only loopback / private-network addresses are accepted for the local servers, so this
can never be turned into a way to reach arbitrary internet hosts.
"""

from __future__ import annotations

import ipaddress
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from automoto import config

DEFAULT_OLLAMA = "http://127.0.0.1:11434"
# Tools that need the internet - removed from the agent in Offline mode.
ONLINE_TOOLS = frozenset({"web_search", "fetch_url", "download_file", "service_api", "open_url"})


# ---------------------------------------------------------------------------
# Switches
# ---------------------------------------------------------------------------
def _setting(name: str) -> Any:
    try:
        from automoto import settings

        return settings.get(name)
    except Exception:
        return None


def offline() -> bool:
    """Offline mode: local AI only, no web tools."""
    v = (config.env("AUTOMOTO_OFFLINE") or "").lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return bool(_setting("offline"))


def _is_local_url(url: str) -> bool:
    try:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return False
        host = u.hostname
        if host in ("localhost",) or host.endswith(".local"):
            return True
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private or ip.is_link_local
    except ValueError:
        return False


def ollama_url() -> str:
    raw = (config.env("OLLAMA_HOST") or DEFAULT_OLLAMA).rstrip("/")
    if "://" not in raw:
        raw = "http://" + raw
    if raw.startswith("http://0.0.0.0"):  # a bind-all address means "this computer"
        raw = raw.replace("0.0.0.0", "127.0.0.1", 1)  # nosec B104
    return raw if _is_local_url(raw) else DEFAULT_OLLAMA


def local_server_url() -> str | None:
    """OpenAI-compatible local server (llama.cpp ``llama-server``, LM Studio, vLLM…), e.g.
    ``LOCAL_LLM_URL=http://127.0.0.1:8080/v1``."""
    raw = (config.env("LOCAL_LLM_URL") or "").rstrip("/")
    if not raw:
        return None
    if not _is_local_url(raw):
        return None
    return raw if raw.endswith("/v1") else raw + "/v1"


def ollama_model() -> str:
    return config.env("OLLAMA_MODEL") or _setting("local_model") or "qwen2.5:3b"


def enabled(provider_id: str) -> bool:
    """A local provider is used only when the user turned it on (no surprise localhost probing)."""
    if provider_id == "ollama":
        return bool(config.env("OLLAMA_MODEL") or _setting("local_model") or offline()
                    or (config.env("AUTOMOTO_OLLAMA") or "").lower() in ("1", "true", "yes", "on"))
    if provider_id == "local":
        return local_server_url() is not None
    return False


# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------
def _ram_gb() -> float | None:
    try:
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore[attr-defined]
            return m.ullTotalPhys / 1024 ** 3
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip()) / 1024 ** 3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except Exception:
        return None


def _gpu() -> dict[str, Any] | None:
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=8)
            line = out.stdout.strip().splitlines()[0]
            name, mem = [x.strip() for x in line.split(",")[:2]]
            return {"name": name, "vram_gb": round(int(mem) / 1024, 1), "kind": "nvidia"}
        except Exception:
            pass
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return {"name": "Apple Silicon (shared memory)", "vram_gb": None, "kind": "apple"}
    return None


def hardware() -> dict[str, Any]:
    ram = _ram_gb()
    gpu = _gpu()
    return {"ram_gb": round(ram, 1) if ram else None, "cpus": os.cpu_count(), "gpu": gpu,
            "os": platform.system(), "arch": platform.machine()}


# ---------------------------------------------------------------------------
# Model catalogue: small models that can call tools, best first within a size
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LocalModel:
    name: str
    label: str
    download_gb: float
    min_ram_gb: float
    tools: bool
    note: str


CATALOG: tuple[LocalModel, ...] = (
    LocalModel("qwen2.5:0.5b", "Qwen 2.5 0.5B", 0.4, 2, True, "Tiny and very fast. Fine for short chats; weak at tasks."),
    LocalModel("qwen2.5:1.5b", "Qwen 2.5 1.5B", 1.0, 4, True, "Small and quick. OK for simple tasks."),
    LocalModel("llama3.2:1b", "Llama 3.2 1B", 1.3, 4, True, "Small and quick."),
    LocalModel("qwen2.5:3b", "Qwen 2.5 3B", 1.9, 8, True, "Best small all-rounder. Good tool use."),
    LocalModel("llama3.2:3b", "Llama 3.2 3B", 2.0, 8, True, "Good small all-rounder."),
    LocalModel("qwen3:4b", "Qwen 3 4B", 2.5, 8, True, "Smarter, a bit slower (thinks before answering)."),
    LocalModel("qwen2.5:7b", "Qwen 2.5 7B", 4.7, 16, True, "Strong at tasks and documents."),
    LocalModel("qwen3:8b", "Qwen 3 8B", 5.2, 16, True, "Strong reasoning; slower on CPU."),
    LocalModel("llama3.1:8b", "Llama 3.1 8B", 4.9, 16, True, "Strong general model."),
    LocalModel("qwen3:14b", "Qwen 3 14B", 9.3, 32, True, "Best quality here; needs a big computer or GPU."),
)
# The one we pick: by graphics memory when there is a GPU (fast), else by RAM (CPU is slower,
# so we stay smaller). Computers report a bit less than the label (16 GB shows as ~15.5).
_GPU_BEST = ((11, "qwen3:14b"), (5.5, "qwen2.5:7b"), (2.5, "qwen2.5:3b"))
_RAM_BEST = ((30, "qwen2.5:7b"), (7, "qwen2.5:3b"), (3.5, "qwen2.5:1.5b"), (0, "qwen2.5:0.5b"))
_APPLE_BEST = ((30, "qwen3:14b"), (15, "qwen2.5:7b"), (7, "qwen2.5:3b"), (3.5, "qwen2.5:1.5b"), (0, "qwen2.5:0.5b"))


def recommend(hw: dict[str, Any] | None = None) -> dict[str, Any]:
    """Models that fit this computer. ``best`` is the one we suggest downloading first."""
    hw = hw or hardware()
    ram = hw.get("ram_gb") or 8.0
    gpu = hw.get("gpu") or {}
    vram = gpu.get("vram_gb") or 0
    apple = gpu.get("kind") == "apple"
    best = None
    if vram:
        best = next((n for tier, n in _GPU_BEST if vram >= tier), None)
    if best is None:
        best = next(n for tier, n in (_APPLE_BEST if apple else _RAM_BEST) if ram >= tier)
    budget = max(ram, vram * 2) + 1  # what can run at all (slowly is OK)
    fits = []
    for m in CATALOG:
        if m.min_ram_gb <= budget:
            d = asdict(m)
            d["fast"] = bool(vram and vram >= m.download_gb * 1.3) or (apple and m.min_ram_gb <= ram) or \
                (not vram and m.download_gb <= 2.0)
            d["recommended"] = m.name == best
            fits.append(d)
    why = (f"Your computer has about {ram:.0f} GB of memory"
           + (f" and a {gpu['name']} graphics card ({vram:.0f} GB)" if vram else
              " and no graphics card we can use" if not apple else " (Apple Silicon)")
           + f", so {best} is the best fit: quick enough and good at tasks.")
    return {"best": best, "why": why, "models": fits, "hardware": hw}


# ---------------------------------------------------------------------------
# Ollama API (local only)
# ---------------------------------------------------------------------------
def _get(path: str, timeout: float = 3.0) -> Any:
    with urllib.request.urlopen(ollama_url() + path, timeout=timeout) as r:  # noqa: S310  # nosec B310 - http(s) to a validated local address only
        return json.loads(r.read().decode("utf-8") or "{}")


def ollama_status() -> dict[str, Any]:
    """Is Ollama running, which version, and which models are already downloaded."""
    out: dict[str, Any] = {"url": ollama_url(), "running": False, "installed": shutil.which("ollama") is not None,
                           "version": None, "models": []}
    try:
        out["version"] = _get("/api/version").get("version")
        out["running"] = True
        tags = _get("/api/tags").get("models") or []
        out["models"] = [{"name": m.get("name"), "size_gb": round((m.get("size") or 0) / 1024 ** 3, 2)}
                         for m in tags]
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return out


_SAFE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,80}(:[A-Za-z0-9._\-]{1,40})?$")
_PULLS: dict[str, dict[str, Any]] = {}
_PULL_LOCK = threading.Lock()


def valid_model_name(name: str) -> bool:
    return bool(isinstance(name, str) and _SAFE_MODEL.match(name))


def pull(name: str, *, wait: bool = False) -> dict[str, Any]:
    """Start downloading ``name`` with Ollama (one download per model). Progress: :func:`pull_progress`."""
    if not valid_model_name(name):
        raise ValueError("That doesn't look like an Ollama model name (e.g. qwen2.5:3b).")
    with _PULL_LOCK:
        cur = _PULLS.get(name)
        if cur and cur.get("state") == "downloading":
            return dict(cur)
        _PULLS[name] = {"model": name, "state": "downloading", "status": "starting", "percent": 0, "error": None,
                        "started": time.time()}

    def run() -> None:
        st = _PULLS[name]
        try:
            req = urllib.request.Request(ollama_url() + "/api/pull", data=json.dumps({"model": name}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=60 * 60) as r:  # noqa: S310  # nosec B310 - http(s) to a validated local address only
                for raw in r:
                    try:
                        ev = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        continue
                    if ev.get("error"):
                        raise RuntimeError(ev["error"])
                    st["status"] = ev.get("status") or st["status"]
                    if ev.get("total"):
                        st["percent"] = int(100 * (ev.get("completed") or 0) / ev["total"])
            st.update(state="done", status="success", percent=100)
        except urllib.error.URLError:
            st.update(state="error", error="Ollama isn't running. Install it from ollama.com and open it, then try again.")
        except Exception as e:  # noqa: BLE001
            st.update(state="error", error=str(e)[:300])

    if wait:
        run()
    else:
        threading.Thread(target=run, daemon=True, name=f"ollama-pull-{name}").start()
    return dict(_PULLS[name])


def pull_progress(name: str | None = None) -> dict[str, Any]:
    if name:
        return dict(_PULLS.get(name) or {"model": name, "state": "idle"})
    return {k: dict(v) for k, v in _PULLS.items()}


def status() -> dict[str, Any]:
    """Everything the Settings page needs."""
    return {"offline": offline(), "offline_from_env": bool(config.env("AUTOMOTO_OFFLINE")),
            "model_from_env": bool(config.env("OLLAMA_MODEL")),
            "model": ollama_model(), "ollama_enabled": enabled("ollama"),
            "local_server": local_server_url(), "ollama": ollama_status(), "recommend": recommend(),
            "pulls": pull_progress()}


_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


def strip_thinking(text: str) -> str:
    """Qwen 3 and similar models may put their private reasoning in <think>…</think>."""
    return _THINK.sub("", text or "").strip() if text and "<think>" in text else (text or "")

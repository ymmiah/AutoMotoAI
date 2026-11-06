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
ONLINE_TOOLS = frozenset({"web_search", "fetch_url", "download_file", "service_api", "open_url", "discover", "read_feed"})


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


# Free, open-weights models from the Ollama library (sizes are the default download, checked Nov 2026).
# ``tools`` = the Ollama library lists tool calling for it; the others still work, through the text protocol.
CATALOG: tuple[LocalModel, ...] = (
    LocalModel("qwen2.5:0.5b", "Qwen 2.5 0.5B", 0.4, 2, True, "Tiny and very fast. Fine for short chats; weak at tasks."),
    LocalModel("qwen2.5:1.5b", "Qwen 2.5 1.5B", 1.0, 4, True, "Small and quick. OK for simple tasks."),
    LocalModel("qwen3.5:0.8b", "Qwen 3.5 0.8B", 1.3, 4, True, "Newest tiny Qwen: quick, reads images, long memory."),
    LocalModel("gemma3:1b", "Google Gemma 3 1B", 0.8, 4, False, "Short chats only; no tool calling."),
    LocalModel("llama3.2:1b", "Llama 3.2 1B", 1.3, 4, True, "Small and quick."),
    LocalModel("qwen2.5:3b", "Qwen 2.5 3B", 1.9, 8, True, "Fast small all-rounder. Good tool use, even on a CPU."),
    LocalModel("llama3.2:3b", "Llama 3.2 3B", 2.0, 8, True, "Good small all-rounder."),
    LocalModel("qwen3:4b", "Qwen 3 4B", 2.5, 8, True, "Smarter, a bit slower."),
    LocalModel("qwen3.5:2b", "Qwen 3.5 2B", 3.1, 8, True, "Newer small Qwen with image understanding."),
    LocalModel("gemma3:4b", "Google Gemma 3 4B", 3.4, 8, False, "Multilingual chat and images; no tool calling, so tasks are slower."),
    LocalModel("qwen3.5:4b", "Qwen 3.5 4B", 4.0, 8, True, "Best quality for most laptops: tools, images, long documents."),
    LocalModel("mistral:7b", "Mistral 7B", 4.4, 16, True, "Solid European all-rounder."),
    LocalModel("qwen2.5:7b", "Qwen 2.5 7B", 4.7, 16, True, "Strong at tasks and documents."),
    LocalModel("llama3.1:8b", "Llama 3.1 8B", 4.9, 16, True, "Strong general model."),
    LocalModel("deepseek-r1:8b", "DeepSeek R1 8B", 5.2, 16, True, "Reasons step by step: good at maths and logic, slower."),
    LocalModel("qwen3:8b", "Qwen 3 8B", 5.2, 16, True, "Strong reasoning; slower on CPU."),
    LocalModel("qwen3.5:9b", "Qwen 3.5 9B", 7.6, 16, True, "Excellent all-rounder for a graphics card or 32 GB PC."),
    LocalModel("gemma4:e2b", "Google Gemma 4 E2B", 7.5, 16, True, "Google's newest small model: tools, images, audio."),
    LocalModel("gemma4:12b", "Google Gemma 4 12B", 8.0, 16, True, "Google's newest: strong writing and reasoning."),
    LocalModel("gemma4:e4b", "Google Gemma 4 E4B", 9.5, 16, True, "Google's newest, more capable than E2B."),
    LocalModel("qwen3:14b", "Qwen 3 14B", 9.3, 32, True, "High quality; needs a big computer or GPU."),
    LocalModel("gpt-oss:20b", "OpenAI gpt-oss 20B", 14.0, 24, True, "OpenAI's open-weights model (Apache 2.0). Needs 16 GB+ graphics memory to be quick."),
    LocalModel("qwen3.5:27b", "Qwen 3.5 27B", 20.0, 32, True, "Near cloud quality; needs a 24 GB graphics card or a 32 GB Mac."),
)
# The one we pick: by graphics memory when there is a GPU (fast), else by RAM (CPU is slower,
# so we stay smaller). Computers report a bit less than the label (16 GB shows as ~15.5).
# Graphics memory is fast, so a card that can hold a larger tool model should use it.
# 6 GB stays on the 4B vision model; 8 GB can hold an 8B tool model without swapping.
_GPU_BEST = ((22, "qwen3.5:27b"), (11, "qwen3.5:9b"), (7.5, "qwen3:8b"), (5.5, "qwen3.5:4b"), (2.5, "qwen2.5:3b"))
_RAM_BEST = ((30, "qwen3.5:9b"), (15, "qwen3.5:4b"), (7, "qwen2.5:3b"), (3.5, "qwen2.5:1.5b"), (0, "qwen2.5:0.5b"))
_APPLE_BEST = ((30, "qwen3.5:27b"), (15, "qwen3.5:9b"), (7, "qwen2.5:3b"), (3.5, "qwen2.5:1.5b"), (0, "qwen2.5:0.5b"))
_TIER_RANK = {"limited": 0, "everyday": 1, "strong": 2}
# Tool calls on small local models wander when sampling is loose. Cap only tool turns.
TOOL_TEMPERATURE = 0.2


_HW: dict[str, Any] = {}


def _hardware_cached() -> dict[str, Any]:
    """hardware() runs nvidia-smi: do it once per process, not on every chat turn."""
    if not _HW:
        _HW.update(hardware())
    return dict(_HW)


def catalog_model(name: str) -> LocalModel | None:
    if not isinstance(name, str) or not name:
        return None
    base = name[:-7] if name.endswith(":latest") else name
    for m in CATALOG:
        if m.name == base:
            return m
    return None


def quality_tier(name: str) -> str:
    """``limited`` (short chats), ``everyday`` (files and tool steps), or ``strong`` (closest to a cloud assistant)."""
    m = catalog_model(name)
    if m is None:
        low = (name or "").lower()
        if any(s in low for s in (":0.5b", ":1b", ":1.5b", ":2b", ":0.8b")):
            return "limited"
        if any(s in low for s in (":7b", ":8b", ":9b", ":12b", ":14b", ":20b", ":27b", ":32b", ":70b")):
            return "strong"
        return "everyday"
    if not m.tools or m.min_ram_gb <= 4:
        return "limited"
    if m.min_ram_gb >= 16 or m.download_gb >= 4.5:
        return "strong"
    return "everyday"


def _strength(name: str) -> tuple[int, int]:
    m = catalog_model(name)
    return (_TIER_RANK[quality_tier(name)], CATALOG.index(m) if m is not None else 0)


def _pick_upgrade(best: str, fits: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A stronger tool model that also fits, when the default stays smaller so the computer stays responsive."""
    if quality_tier(best) == "strong":
        return None
    stronger = [m for m in fits if m["tools"] and m["name"] != best and quality_tier(m["name"]) == "strong"]
    if not stronger:
        return None
    pick = min(stronger, key=lambda m: (m["download_gb"], m["name"]))
    slow = not pick["fast"]
    note = f"{pick['name']} also fits and follows multi-step tasks more reliably"
    note += ", but it will be slower on this CPU." if slow else "."
    return {"name": pick["name"], "slow": slow, "note": note}


def recommend(hw: dict[str, Any] | None = None) -> dict[str, Any]:
    """Models that fit this computer. ``best`` is the one we suggest downloading first."""
    hw = hw or _hardware_cached()
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
                (not vram and not apple and m.download_gb <= 2.0)
            d["recommended"] = m.name == best
            d["tier"] = quality_tier(m.name)
            fits.append(d)
    tier = quality_tier(best)
    upgrade = _pick_upgrade(best, fits)
    hardware_bit = (f"Your computer has about {ram:.0f} GB of memory"
                    + (f" and a {gpu.get('name', 'graphics card')} graphics card ({vram:.0f} GB)" if vram else
                       " (Apple Silicon)" if apple else " and no graphics card we can use"))
    if tier == "limited":
        sentence = (f"{best} is the largest model that should stay responsive here. It can chat and do short tasks. "
                    "It is not as reliable as a cloud assistant on long, multi-step jobs. A computer with about "
                    "8 GB of memory can run a stronger model.")
    elif tier == "strong":
        sentence = (f"{best} is the strongest free local model that should still stay responsive here, and the "
                    "closest this computer can get to a cloud assistant without an API key.")
    else:
        sentence = (f"{best} is a practical fit for everyday assistant work: writing, files, and tool steps. "
                    "It is slower than a cloud model and can miss a step on a long job.")
    why = hardware_bit + ". " + sentence
    if upgrade:
        why += " " + upgrade["note"]
    return {"best": best, "why": why, "tier": tier, "upgrade": upgrade, "context": _context_for(hw),
            "models": fits, "hardware": hw, "quality_note": sentence}


# ---------------------------------------------------------------------------
# Ollama API (local only)
# ---------------------------------------------------------------------------
def _get(path: str, timeout: float = 3.0) -> Any:
    with urllib.request.urlopen(ollama_url() + path, timeout=timeout) as r:  # noqa: S310  # nosec B310 - http(s) to a validated local address only
        return json.loads(r.read().decode("utf-8") or "{}")


def ollama_binary() -> str | None:
    """Find Ollama even when a GUI installer hasn't refreshed the user's PATH yet."""
    found = shutil.which("ollama")
    if found:
        return found
    paths: list[str] = []
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA")
        progfiles = os.environ.get("ProgramFiles")
        if local_app:
            paths.append(os.path.join(local_app, "Programs", "Ollama", "ollama.exe"))
        if progfiles:
            paths.append(os.path.join(progfiles, "Ollama", "ollama.exe"))
    elif sys.platform == "darwin":
        paths.extend(("/Applications/Ollama.app/Contents/Resources/ollama",
                      os.path.expanduser("~/.local/bin/ollama")))
    else:
        paths.extend(("/usr/local/bin/ollama", "/usr/bin/ollama",
                      os.path.expanduser("~/.local/bin/ollama")))
    return next((candidate for candidate in paths if os.path.isfile(candidate)), None)


def ollama_status() -> dict[str, Any]:
    """Is Ollama running, which version, and which models are already downloaded."""
    out: dict[str, Any] = {"url": ollama_url(), "running": False, "installed": ollama_binary() is not None,
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


# ---------------------------------------------------------------------------
# Which model actually runs, and how (context size, tools, thinking)
# ---------------------------------------------------------------------------
_TAGS_CACHE: dict[str, Any] = {"at": 0.0, "names": None, "url": None}
_INFO_CACHE: dict[str, dict[str, Any]] = {}
DEFAULT_CONTEXT = 8192  # Ollama's own default (2-4k on most PCs) cuts off the agent's ~4k-token prompt


def installed_models(max_age: float = 5.0) -> list[str] | None:
    """Names Ollama has downloaded (cached a few seconds), or None when Ollama can't be reached."""
    now, url = time.monotonic(), ollama_url()
    if _TAGS_CACHE["names"] is not None and _TAGS_CACHE["url"] == url and now - _TAGS_CACHE["at"] < max_age:
        return list(_TAGS_CACHE["names"])
    try:
        names = [m.get("name") for m in (_get("/api/tags").get("models") or []) if m.get("name")]
    except (urllib.error.URLError, OSError, ValueError):
        names = None
    _TAGS_CACHE.update(at=now, names=names, url=url)
    return list(names) if names is not None else None


def forget_installed() -> None:
    """Call after a download or a model change so the next turn sees it at once."""
    _TAGS_CACHE.update(at=0.0, names=None, url=None)
    _INFO_CACHE.clear()


def _is_installed(name: str, names: list[str]) -> bool:
    return name in names or f"{name}:latest" in names or (name.endswith(":latest") and name[:-7] in names)


def _best_installed(names: list[str]) -> str | None:
    """The most useful downloaded model: our pick for this computer, else the biggest catalogue model
    that fits and can use tools, else any chat model (embedding models can't chat)."""
    rec = recommend()
    if _is_installed(rec["best"], names):
        return rec["best"]
    for m in reversed(rec["models"]):
        if m["tools"] and _is_installed(m["name"], names):
            return m["name"]
    for m in reversed(rec["models"]):
        if _is_installed(m["name"], names):
            return m["name"]
    return next((n for n in names if "embed" not in n.lower()), None)


def runtime_choice(names: list[str] | None = None) -> dict[str, Any]:
    """Which Ollama model a chat will really use, and whether that is a downgrade from the one the user picked.

    ``OLLAMA_MODEL`` in .env is a lock and always wins. Otherwise the Settings model (or our default) is
    used when it is downloaded. When it isn't, the best downloaded model runs instead of failing with
    "model not found" — and ``message`` says so, including when that substitute is weaker.
    """
    locked = config.env("OLLAMA_MODEL")
    chosen = locked or ollama_model()
    if locked:
        return {"model": locked, "chosen": locked, "substituted": False, "weaker": False, "message": ""}
    if names is None:
        names = installed_models()
    if not names or _is_installed(chosen, names):
        return {"model": chosen, "chosen": chosen, "substituted": False, "weaker": False, "message": ""}
    alt = _best_installed(names) or chosen
    if alt == chosen:
        return {"model": chosen, "chosen": chosen, "substituted": False, "weaker": False, "message": ""}
    weaker = _strength(alt) < _strength(chosen)
    if weaker:
        message = (f"{chosen} is not downloaded, so this chat is using {alt} instead. "
                   f"{alt} is weaker, so long tasks will be less reliable. Download {chosen} to avoid that drop.")
    else:
        message = (f"{chosen} is not downloaded, so this chat is using {alt}, which is already on this computer.")
    return {"model": alt, "chosen": chosen, "substituted": True, "weaker": weaker, "message": message}


def active_model() -> str:
    """The Ollama model a chat will really use. See :func:`runtime_choice`."""
    return runtime_choice()["model"]


def model_info(name: str) -> dict[str, Any]:
    """Capabilities (``tools``, ``thinking``, ``vision``…) and the trained context length, from
    Ollama's /api/show. Cached per model; empty when unknown (old Ollama, not downloaded)."""
    key = f"{ollama_url()}|{name}"
    if key in _INFO_CACHE:
        return _INFO_CACHE[key]
    info: dict[str, Any] = {}
    try:
        req = urllib.request.Request(ollama_url() + "/api/show", data=json.dumps({"model": name}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310  # nosec B310 - validated local address only
            data = json.loads(r.read().decode("utf-8") or "{}")
        caps = data.get("capabilities")
        if isinstance(caps, list):
            info["capabilities"] = [str(c) for c in caps]
        ctx = [v for k, v in (data.get("model_info") or {}).items() if k.endswith(".context_length")]
        if ctx and isinstance(ctx[0], int):
            info["context_length"] = ctx[0]
    except (urllib.error.URLError, OSError, ValueError):
        return {}  # not cached: Ollama may just be starting
    _INFO_CACHE[key] = info
    return info


def supports(name: str, capability: str) -> bool | None:
    """True / False when Ollama says so, None when it can't tell (then we just try)."""
    caps = model_info(name).get("capabilities")
    return None if caps is None else capability in caps


def _context_for(hw: dict[str, Any] | None) -> int:
    """8192 keeps the agent's instructions intact. Stronger machines get 16384 so multi-step tool
    transcripts are not pushed out of the window. ``LOCAL_AI_CONTEXT`` overrides this."""
    hw = _hardware_cached() if hw is None else hw
    ram = hw.get("ram_gb") or 8.0
    gpu = hw.get("gpu") or {}
    vram = gpu.get("vram_gb") or 0
    apple = gpu.get("kind") == "apple"
    if vram >= 8 or ram >= 24 or (apple and ram >= 16):
        return 16384
    return DEFAULT_CONTEXT


def context_size(name: str, hw: dict[str, Any] | None = None) -> int:
    """Context window to ask for. Never above what the model was trained with."""
    raw = config.env("LOCAL_AI_CONTEXT")
    if raw:
        try:
            want = int(raw)
        except ValueError:
            want = _context_for(hw)
    else:
        want = _context_for(hw)
    want = max(2048, want)
    trained = model_info(name).get("context_length")
    return min(want, trained) if isinstance(trained, int) and trained >= 2048 else want


def tool_temperature(requested: float) -> float:
    """Keep tool turns deterministic. Plain chat keeps the user's temperature."""
    try:
        requested = float(requested)
    except (TypeError, ValueError):
        requested = TOOL_TEMPERATURE
    return min(requested, TOOL_TEMPERATURE)


def request_options(name: str) -> dict[str, Any]:
    """Extra /api/chat fields shared by chats and the Test button, so both load the model the same way
    (a different context size makes Ollama reload the model)."""
    extra: dict[str, Any] = {"options": {"num_ctx": context_size(name)}}
    # Thinking models (Qwen 3/3.5, DeepSeek R1, gpt-oss) can spend minutes "thinking" on a laptop CPU
    # before every step. Off unless LOCAL_AI_THINK=1; only sent to models that support the switch.
    if supports(name, "thinking"):
        think = (config.env("LOCAL_AI_THINK") or "").lower() in ("1", "true", "yes", "on")
        # gpt-oss can't switch thinking off, only turn it down: it takes "low" / "medium" / "high"
        extra["think"] = ("medium" if think else "low") if name.startswith("gpt-oss") else think
    return extra


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
            forget_installed()
            from automoto import providers

            providers.clear_unavailable("ollama")  # an earlier "not found" for this model is now wrong
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


_OLLAMA_START_LOCK = threading.Lock()
_OLLAMA_CHILD: subprocess.Popen[Any] | None = None


def start_ollama() -> dict[str, Any]:
    """Start an already installed Ollama locally, only after the user requests it."""
    global _OLLAMA_CHILD
    from urllib.parse import urlparse

    u = urlparse(ollama_url())
    if u.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Automatic start is available only for Ollama running on this computer.")
    current = ollama_status()
    if current["running"]:
        return {"started": True, "already_running": True, "ollama": current}
    binary = ollama_binary()
    if not binary:
        raise ValueError("Ollama is not installed. Download the official installer from https://ollama.com/download.")
    with _OLLAMA_START_LOCK:
        if _OLLAMA_CHILD is None or _OLLAMA_CHILD.poll() is not None:
            env = os.environ.copy()
            env["OLLAMA_HOST"] = u.netloc
            options: dict[str, Any] = {"env": env, "stdin": subprocess.DEVNULL,
                                        "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if os.name == "nt":
                options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            else:
                options["start_new_session"] = True
            try:
                _OLLAMA_CHILD = subprocess.Popen([binary, "serve"], **options)
            except OSError as exc:
                raise ValueError(f"Could not start Ollama: {exc}") from exc
    for _ in range(25):
        time.sleep(0.2)
        current = ollama_status()
        if current["running"]:
            forget_installed()
            return {"started": True, "already_running": False, "ollama": current}
        if _OLLAMA_CHILD and _OLLAMA_CHILD.poll() is not None:
            break
    return {"started": False, "message": "Ollama did not become ready. Check Ollama installation and logs.",
            "ollama": current}


def test_ollama(name: str) -> dict[str, Any]:
    """Small local inference smoke test with an explicit, bounded timeout."""
    if not valid_model_name(name):
        raise ValueError("Invalid model name.")
    status = ollama_status()
    if not status["running"]:
        raise ValueError("Ollama is not running. Click Start local AI first.")
    installed = {m["name"] for m in status["models"]}
    if name not in installed and name + ":latest" not in installed:
        raise ValueError("That model is not downloaded yet.")
    # Same endpoint and options as a real chat, so a passing test also leaves the model loaded for it.
    body: dict[str, Any] = {"model": name, "messages": [{"role": "user", "content": "Reply only OK."}],
                            "stream": False, **request_options(name)}
    body["options"]["num_predict"] = 32
    request = urllib.request.Request(ollama_url() + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310  # nosec B310 - local only
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Local model could not load: {_ollama_error(exc)}") from exc
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise ValueError(f"Local model could not load: {exc}") from exc
    if data.get("error"):
        raise ValueError(str(data["error"])[:250])
    reply = strip_thinking(str((data.get("message") or {}).get("content", "")))
    from automoto import providers

    providers.clear_unavailable("ollama")
    return {"ok": True, "model": name, "reply": reply.strip()[:150], "seconds": round(time.monotonic() - started, 1),
            "context": body["options"]["num_ctx"], "tools": supports(name, "tools")}


def _ollama_error(exc: urllib.error.HTTPError) -> str:
    """Ollama's own words from an error response ({"error": "..."}), else the HTTP status."""
    try:
        data = json.loads(exc.read().decode("utf-8") or "{}")
        msg = data.get("error")
        if isinstance(msg, dict):
            msg = msg.get("message")
        if msg:
            return str(msg)[:250]
    except (OSError, ValueError):
        pass
    return f"HTTP {exc.code}"


def status() -> dict[str, Any]:
    """Everything the Settings page needs."""
    oll = ollama_status()
    if oll["running"]:
        choice = runtime_choice([m["name"] for m in oll["models"] if m.get("name")])
    else:
        chosen = ollama_model()
        choice = {"model": chosen, "chosen": chosen, "substituted": False, "weaker": False, "message": ""}
    model = choice["model"]
    options = request_options(model) if oll["running"] else {"options": {"num_ctx": _context_for(None)}}
    return {"offline": offline(), "offline_from_env": bool(config.env("AUTOMOTO_OFFLINE")),
            "model_from_env": bool(config.env("OLLAMA_MODEL")),
            "model": model, "chosen_model": choice["chosen"], "ollama_enabled": enabled("ollama"),
            "local_server": local_server_url(), "ollama": oll, "recommend": recommend(),
            "tier": quality_tier(model), "context": options["options"]["num_ctx"],
            "think": options.get("think", False),
            "substitution": choice if choice["substituted"] else None,
            "pulls": pull_progress()}


def serving_locally() -> bool:
    """True when the next answer cannot leave this computer (Offline mode, or no cloud key is configured)."""
    if offline():
        return True
    if not (enabled("ollama") or enabled("local")):
        return False
    from automoto.providers import REGISTRY

    return not any(p.key() for p in REGISTRY.values() if not p.local)


def local_task_guide(model: str | None = None) -> str:
    """Short rules appended for local models. Small models follow a short list better than a long essay."""
    name = model or active_model()
    lines = [
        "Local model operating rules:",
        "- Decide the steps yourself. Do not ask which tool to use, and do not show a tool list.",
        "- Do the work with tools. Do not say a file was created, changed, or checked until a tool result says so.",
        "- One tool call per step. After the result, call the next tool or give the final answer.",
        "- Copy tool and argument names exactly. If a call fails, change it using the error. Do not repeat the same broken call.",
        "- Keep going until the user's request is actually finished.",
    ]
    if offline():
        lines.append("- Offline mode is on: do not use or claim a web search, a download, or a cloud model.")
    cat = catalog_model(name)
    if cat is not None and not cat.tools:
        lines.append("- This model cannot call tools directly. Reply with only a fenced ```tool JSON block, then wait.")
    elif quality_tier(name) == "limited":
        lines.append("- This is a small model. Take one small step at a time and do not skip the tool call.")
    return "\n".join(lines)


_UNVERIFIED_WORK = re.compile(
    r"\b(?:i(?:'ve| have)|i(?:'m| am)) (?:just |already )?(?:created|written|saved|updated|finished|completed|generated|edited|fixed)\b"
    r"|\b(?:i(?:'ve| have)) (?:just |already )?(?:made|built) (?:the |a |your )?(?:file|document|report|spreadsheet|presentation|deck|slides?)\b"
    r"|\b(?:the|your) (?:file|document|report|spreadsheet|presentation|deck|slides?) (?:is|has been) (?:ready|saved|created|done|updated|written)\b",
    re.I)


def claims_unverified_work(text: str) -> bool:
    """True when a reply says the task is already done. Used to stop a local model skipping the tool call."""
    t = (text or "").strip()
    return bool(t) and len(t) < 1600 and bool(_UNVERIFIED_WORK.search(t))


_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


def strip_thinking(text: str) -> str:
    """Drop private reasoning. Closed ``<think>`` blocks go; an unclosed tag (the reply was cut off)
    drops the unfinished reasoning and keeps any answer written before it. A stray ``</think>``
    keeps only the answer after it."""
    if not text:
        return ""
    if "<think>" not in text and "</think>" not in text:
        return text
    text = _THINK.sub("", text)
    if "</think>" in text:
        text = text.split("</think>", 1)[-1]
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()

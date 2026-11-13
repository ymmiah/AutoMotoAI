"""Hardware-aware llama.cpp settings for the built-in offline engine.

Threads follow physical cores. Context, batch size, memory mapping, flash
attention and KV-cache quantisation are picked so a 16 GB CPU-only PC can run
a Qwen 2.5 3B or 7B Q4 model without swapping. A Vulkan, CUDA or Metal build
is selected when one is published for this computer and a GPU is present.
"""

from __future__ import annotations

from typing import Any


def physical_threads(hw: dict[str, Any] | None) -> int:
    """One llama.cpp worker per physical core. Logical CPUs count as half when SMT is on."""
    hw = hw or {}
    try:
        physical = int(hw.get("physical_cores") or 0)
    except (TypeError, ValueError):
        physical = 0
    if physical > 0:
        return physical
    try:
        logical = int(hw.get("cpus") or 0)
    except (TypeError, ValueError):
        logical = 0
    if logical <= 1:
        return 1
    return max(1, logical // 2)


def tune(hw: dict[str, Any] | None) -> dict[str, Any]:
    """Return llama-server settings for this computer. Pure: no process is started."""
    hw = hw or {}
    try:
        ram = float(hw.get("ram_gb") or 0)
    except (TypeError, ValueError):
        ram = 0.0
    gpu = hw.get("gpu") or {}
    if not isinstance(gpu, dict):
        gpu = {}
    try:
        vram = float(gpu.get("vram_gb") or 0)
    except (TypeError, ValueError):
        vram = 0.0
    kind = str(gpu.get("kind") or "")
    isa = str(hw.get("isa") or "baseline")
    threads = physical_threads(hw)
    if ram >= 32 or vram >= 12:
        context = 16384
    elif ram >= 15:
        context = 8192
    elif ram >= 7:
        context = 4096
    else:
        context = 2048
    if ram >= 15 or vram >= 6:
        batch, ubatch = 512, 256
    else:
        batch, ubatch = 256, 128
    # q8_0 keeps an 8k context next to a 7B Q4 file inside 16 GB. Smaller PCs use q4_0.
    if vram >= 8 and ram >= 24:
        kv = "f16"
    elif ram >= 12 or vram >= 4:
        kv = "q8_0"
    else:
        kv = "q4_0"
    gpu_layers = 0
    backend = "cpu"
    if kind == "nvidia" and vram >= 2:
        backend, gpu_layers = "cuda", 999
    elif kind == "apple":
        backend, gpu_layers = "metal", 999
    elif kind in {"vulkan", "amd", "intel"} or (vram >= 2 and kind not in {"", "cpu", "none"}):
        backend, gpu_layers = "vulkan", 999
    elif isa == "avx512":
        backend = "cpu-avx512"
    elif isa == "avx2":
        backend = "cpu-avx2"
    return {
        "threads": threads,
        "context": context,
        "batch": batch,
        "ubatch": ubatch,
        "mmap": True,
        "flash_attn": True,
        "kv_type": kv,
        "gpu_layers": gpu_layers,
        "backend": backend,
        "isa": isa,
    }


def command_flags(spec: dict[str, Any], *, context: int | None = None) -> list[str]:
    """llama-server flags. ``context`` overrides the tuned window when the caller already chose one."""
    ctx = int(context if context is not None else spec["context"])
    flags = [
        "-c", str(ctx),
        "-t", str(int(spec["threads"])),
        "-b", str(int(spec["batch"])),
        "-ub", str(int(spec["ubatch"])),
        "--mmap" if spec.get("mmap", True) else "--no-mmap",
    ]
    if spec.get("flash_attn"):
        flags.extend(["-fa", "on"])
    kv = str(spec.get("kv_type") or "f16")
    if kv != "f16":
        flags.extend(["-ctk", kv, "-ctv", kv])
    layers = int(spec.get("gpu_layers") or 0)
    if layers:
        flags.extend(["-ngl", str(layers)])
    return flags


def offload_with_binary(binary_name: str, spec: dict[str, Any]) -> bool:
    """GPU layer offload only when this file is a GPU build, or the Apple build (Metal)."""
    name = (binary_name or "").lower()
    if any(tag in name for tag in ("cuda", "vulkan", "metal")):
        return True
    return spec.get("backend") == "metal"


def choose_asset_key(platform: str, machine: str, spec: dict[str, Any],
                     available: dict[tuple, Any]) -> tuple:
    """Best published asset that exists. Falls back to the plain CPU build."""
    backend = str(spec.get("backend") or "cpu")
    isa = str(spec.get("isa") or "")
    order: list[tuple] = []
    if backend in {"cuda", "vulkan", "metal", "cpu-avx512", "cpu-avx2"}:
        order.append((platform, machine, backend))
    if isa == "avx512":
        order.append((platform, machine, "cpu-avx512"))
    if isa in {"avx512", "avx2"}:
        order.append((platform, machine, "cpu-avx2"))
    order.append((platform, machine))
    seen: set[tuple] = set()
    for key in order:
        if key in seen:
            continue
        seen.add(key)
        if key in available:
            return key
    return (platform, machine)

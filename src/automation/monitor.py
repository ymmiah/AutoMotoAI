"""System resource monitoring via psutil."""
from __future__ import annotations

import logging
import sys
import time
from typing import Optional

logger = logging.getLogger(__name__)

_prev_net: Optional[tuple] = None
_prev_net_time: float = 0.0


def _psutil():
    try:
        import psutil
        return psutil
    except ImportError as exc:
        raise ImportError("psutil not installed. Run: pip install psutil") from exc


def get_system_snapshot() -> dict:
    """Return a single-frame snapshot of CPU / RAM / Disk / Network."""
    global _prev_net, _prev_net_time
    ps = _psutil()

    # CPU
    cpu_percent = ps.cpu_percent(interval=0.1)
    cpu_per_core = ps.cpu_percent(percpu=True)

    # RAM
    ram = ps.virtual_memory()

    # Disk (primary partition)
    try:
        disk_path = "C:\\" if sys.platform == "win32" else "/"
        disk = ps.disk_usage(disk_path)
        disk_data = {
            "path": disk_path,
            "percent": disk.percent,
            "used_gb": round(disk.used / 1024 ** 3, 1),
            "total_gb": round(disk.total / 1024 ** 3, 1),
            "free_gb": round(disk.free / 1024 ** 3, 1),
        }
    except Exception:
        disk_data = {}

    # Network I/O rate (bytes/s)
    net = ps.net_io_counters()
    now = time.monotonic()
    if _prev_net and now - _prev_net_time > 0:
        elapsed = now - _prev_net_time
        sent_rate = int((net.bytes_sent - _prev_net[0]) / elapsed)
        recv_rate = int((net.bytes_recv - _prev_net[1]) / elapsed)
    else:
        sent_rate = recv_rate = 0
    _prev_net = (net.bytes_sent, net.bytes_recv)
    _prev_net_time = now

    return {
        "cpu": {
            "percent": cpu_percent,
            "per_core": cpu_per_core,
            "count": ps.cpu_count(logical=True),
        },
        "ram": {
            "percent": ram.percent,
            "used_gb": round(ram.used / 1024 ** 3, 1),
            "total_gb": round(ram.total / 1024 ** 3, 1),
            "available_gb": round(ram.available / 1024 ** 3, 1),
        },
        "disk": disk_data,
        "network": {
            "bytes_sent_rate": sent_rate,
            "bytes_recv_rate": recv_rate,
            "total_sent_gb": round(net.bytes_sent / 1024 ** 3, 2),
            "total_recv_gb": round(net.bytes_recv / 1024 ** 3, 2),
        },
    }


def get_top_processes(limit: int = 20) -> list[dict]:
    """Return top *limit* processes sorted by CPU usage."""
    ps = _psutil()
    procs = []
    for p in ps.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
        try:
            procs.append({
                "pid":    p.info["pid"],
                "name":   p.info["name"] or "?",
                "cpu":    p.info["cpu_percent"] or 0.0,
                "mem":    round(p.info["memory_percent"] or 0.0, 1),
                "status": p.info["status"] or "?",
            })
        except (ps.NoSuchProcess, ps.AccessDenied):
            continue
    return sorted(procs, key=lambda x: x["cpu"], reverse=True)[:limit]


def kill_process(pid: int) -> str:
    ps = _psutil()
    try:
        proc = ps.Process(pid)
        name = proc.name()
        proc.terminate()
        gone, alive = ps.wait_procs([proc], timeout=3)
        if alive:
            for p in alive:
                p.kill()
        logger.info("Killed process %d (%s)", pid, name)
        return f"Killed {name} (PID {pid})"
    except ps.NoSuchProcess:
        return f"Process {pid} not found"
    except ps.AccessDenied as exc:
        raise PermissionError(f"Cannot kill PID {pid}: {exc}") from exc


def get_disk_partitions() -> list[dict]:
    ps = _psutil()
    parts = []
    for p in ps.disk_partitions(all=False):
        try:
            usage = ps.disk_usage(p.mountpoint)
            parts.append({
                "device":      p.device,
                "mountpoint":  p.mountpoint,
                "fstype":      p.fstype,
                "percent":     usage.percent,
                "used_gb":     round(usage.used / 1024 ** 3, 1),
                "total_gb":    round(usage.total / 1024 ** 3, 1),
            })
        except (PermissionError, OSError):
            parts.append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype, "percent": 0})
    return parts

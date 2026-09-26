"""CPU, memory and disk figures for the system screen (psutil)."""
from __future__ import annotations

import os
import platform
import time

import psutil

_cache: dict = {}
_cache_at = 0.0


def _system_disk() -> str:
    if os.name == "nt":
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


def sample(max_age: float = 5.0) -> dict:
    """A cached snapshot; cheap to call every loop."""
    global _cache, _cache_at
    if _cache and time.monotonic() - _cache_at < max_age:
        return _cache
    vm = psutil.virtual_memory()
    try:
        du = psutil.disk_usage(_system_disk())
        disk = {"percent": du.percent, "used": du.used, "total": du.total}
    except OSError:
        disk = {}
    try:
        freq = psutil.cpu_freq()
        ghz = freq.current / 1000 if freq and freq.current else None
    except (OSError, NotImplementedError):
        ghz = None
    _cache = {
        "cpu": psutil.cpu_percent(interval=0.3),
        "cores": psutil.cpu_count(),
        "ghz": ghz,
        "mem": {"percent": vm.percent, "used": vm.total - vm.available, "total": vm.total},
        "disk": disk,
        "host": platform.node(),
        "uptime": time.time() - psutil.boot_time(),
    }
    _cache_at = time.monotonic()
    return _cache

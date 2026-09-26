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


# --- network ------------------------------------------------------------------

import collections  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

NET_HISTORY = collections.deque(maxlen=60)   # (rx bytes/s, tx bytes/s) every 5 s
_net_last: tuple | None = None               # (monotonic, bytes_recv, bytes_sent)
_link: dict = {}
_link_at = 0.0


def _primary_ip() -> str | None:
    """The address the default route uses. A UDP connect sends no packets."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))   # TEST-NET-1, never routed anywhere real
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _wifi_ssid() -> str | None:
    try:
        if sys.platform == "win32":
            out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True,
                                 text=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW).stdout
            state = ssid = None
            for line in out.splitlines():
                key, _, val = line.partition(":")
                key, val = key.strip(), val.strip()
                if key == "State":
                    state = val
                elif key == "SSID":
                    ssid = val
            return ssid if state == "connected" else None
        if sys.platform == "darwin":
            out = subprocess.run(["networksetup", "-getairportnetwork", "en0"],
                                 capture_output=True, text=True, timeout=3).stdout
            return out.split(":", 1)[1].strip() if "Current Wi-Fi Network" in out else None
        out = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=3).stdout
        return out.strip() or None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def link(max_age: float = 60.0) -> dict:
    """Primary interface, IP and Wi-Fi name; cached (it rarely changes)."""
    global _link, _link_at
    if _link and time.monotonic() - _link_at < max_age:
        return _link
    ip = _primary_ip()
    iface = None
    if ip:
        for name, addrs in psutil.net_if_addrs().items():
            if any(a.address == ip for a in addrs):
                iface = name
                break
    _link = {"ip": ip, "iface": iface, "ssid": _wifi_ssid()}
    _link_at = time.monotonic()
    return _link


def network(step: float = 5.0) -> dict:
    """Current rates (bytes/s), a short history, totals since boot, and the link."""
    global _net_last
    now = time.monotonic()
    io = psutil.net_io_counters()
    if _net_last is None:
        _net_last = (now, io.bytes_recv, io.bytes_sent)
    elif now - _net_last[0] >= step:
        dt = now - _net_last[0]
        NET_HISTORY.append((max(0.0, (io.bytes_recv - _net_last[1]) / dt),
                            max(0.0, (io.bytes_sent - _net_last[2]) / dt)))
        _net_last = (now, io.bytes_recv, io.bytes_sent)
    rx, tx = NET_HISTORY[-1] if NET_HISTORY else (0.0, 0.0)
    return {"rx": rx, "tx": tx, "history": list(NET_HISTORY),
            "recv_total": io.bytes_recv, "sent_total": io.bytes_sent, **link()}

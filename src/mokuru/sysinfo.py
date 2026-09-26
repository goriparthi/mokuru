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

import socket  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

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


SKIP = ("loopback", "hyper-v", "kernel debug", "wan miniport", "bluetooth",
        "wi-fi direct", "vethernet", "vswitch", "docker", "veth", "virbr", "br-")
VPN = ("vpn", "tap-", "tap ", "wireguard", "wintun", "pangp", "anyconnect", "fortinet",
       "juniper", "pulse", "openvpn", "tailscale", "zerotier", "tun", "wg", "ppp", "utun")
WIFI = ("wi-fi", "wifi", "wireless", "wlan", "802.11", "airport")

_NET_KEY = r"SYSTEM\CurrentControlSet\Control\Network\{4D36E972-E325-11CE-BFC1-08002BE10318}"
_CLASS_KEY = r"SYSTEM\CurrentControlSet\Control\Class\{4D36E972-E325-11CE-BFC1-08002BE10318}"


def _descriptions() -> dict:
    """Adapter name -> driver description (Windows registry; empty elsewhere)."""
    if sys.platform != "win32":
        return {}
    import winreg
    names, out = {}, {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _NET_KEY) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                guid = winreg.EnumKey(k, i)
                try:
                    with winreg.OpenKey(k, guid + r"\Connection") as c:
                        names[guid] = winreg.QueryValueEx(c, "Name")[0]
                except OSError:
                    pass
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _CLASS_KEY) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    with winreg.OpenKey(k, winreg.EnumKey(k, i)) as c:
                        guid = winreg.QueryValueEx(c, "NetCfgInstanceId")[0]
                        if guid in names:
                            out[names[guid]] = winreg.QueryValueEx(c, "DriverDesc")[0]
                except OSError:
                    pass
    except OSError:
        pass
    return out


def _mac_ports() -> dict:
    """Device -> hardware port name ("en0" -> "Wi-Fi") on macOS."""
    if sys.platform != "darwin":
        return {}
    try:
        out = subprocess.run(["networksetup", "-listallhardwareports"],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    ports, port = {}, None
    for line in out.splitlines():
        if line.startswith("Hardware Port:"):
            port = line.split(":", 1)[1].strip()
        elif line.startswith("Device:") and port:
            ports[line.split(":", 1)[1].strip()] = port
    return ports


def classify(name: str, desc: str = "") -> str | None:
    """'wifi', 'ethernet', 'vpn', or None for adapters not worth showing."""
    text = f"{name} {desc}".lower()
    if name.lower() == "lo" or any(k in text for k in SKIP):
        return None
    if any(k in text for k in VPN):
        return "vpn"
    if any(k in text for k in WIFI) or os.path.isdir(f"/sys/class/net/{name}/wireless"):
        return "wifi"
    if text.startswith(("ethernet", "eth", "en", "usb")) or "ethernet" in text:
        return "ethernet"
    return None


def link(max_age: float = 60.0) -> dict:
    """Active connections (Wi-Fi / Ethernet / VPN) and the LAN IP; cached."""
    global _link, _link_at
    if _link and time.monotonic() - _link_at < max_age:
        return _link
    stats, addrs = psutil.net_if_stats(), psutil.net_if_addrs()
    descs, ports = _descriptions(), _mac_ports()
    ssid = _wifi_ssid()
    links = []
    for name, st in stats.items():
        v4 = [a.address for a in addrs.get(name, [])
              if a.family == socket.AF_INET and not a.address.startswith(("169.254.", "127."))]
        if not st.isup or not v4:
            continue
        kind = classify(name, descs.get(name, "") or ports.get(name, ""))
        if kind == "wifi" and sys.platform in ("win32", "darwin") and not ssid:
            continue            # adapter up but not joined to a network
        if kind:
            links.append({"kind": kind, "name": name, "ip": v4[0],
                          "ssid": ssid if kind == "wifi" else None})
    order = {"ethernet": 0, "wifi": 1, "vpn": 2}
    links.sort(key=lambda l: (order[l["kind"]], l["name"]))
    ip = _primary_ip()
    lan = [l for l in links if l["kind"] != "vpn"]
    if lan and ip not in [l["ip"] for l in lan]:
        ip = lan[0]["ip"]       # show the LAN address, not the VPN tunnel's
    _link = {"links": links, "ip": ip, "ssid": ssid}
    _link_at = time.monotonic()
    return _link


def network() -> dict:
    """Data used since boot and the active connections."""
    io = psutil.net_io_counters()
    return {"recv_total": io.bytes_recv, "sent_total": io.bytes_sent, **link()}

"""`mokuru` command line: talks to the daemon, starting it when needed."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import config
from .device import FLAG_FIXED, FLAG_RAINBOW, MODES, SCREEN_SLOTS, Lighting

HOOK_EVENTS = {
    # Claude Code hook event -> mokuru event
    "UserPromptSubmit": "prompt",
    "PostToolUse": "tool",
    "Notification": "permission",
    "Stop": "stop",
    "SessionEnd": "end",
}


# --- daemon client ------------------------------------------------------------

def _url(path: str) -> str:
    return f"http://127.0.0.1:{config.daemon_port()}{path}"


def _request(path: str, body: dict | None = None, timeout: float = 2.0) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(_url(path), data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def daemon_running() -> bool:
    try:
        _request("/status", timeout=0.5)
        return True
    except (OSError, ValueError):
        return False


def _python_for_background() -> str:
    exe = sys.executable
    if os.name == "nt":
        w = exe[:-len("python.exe")] + "pythonw.exe" if exe.lower().endswith("python.exe") else exe
        if os.path.exists(w):
            return w
    return exe


def start_daemon(wait: float = 5.0) -> bool:
    if daemon_running():
        return True
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = open(config.LOG_FILE, "ab")
    cmd = [_python_for_background(), "-m", "mokuru", "daemon"]
    kw = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": log, "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = (subprocess.DETACHED_PROCESS
                               | subprocess.CREATE_NEW_PROCESS_GROUP
                               | subprocess.CREATE_NO_WINDOW)
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if daemon_running():
            return True
        time.sleep(0.1)
    return False


def cmd(name: str, timeout: float = 600, **args) -> dict:
    if not start_daemon():
        raise SystemExit(f"mokuru: daemon did not start (see {config.LOG_FILE})")
    res = _request("/cmd", {"cmd": name, "args": args}, timeout=timeout)
    if not res.get("ok"):
        raise SystemExit(f"mokuru: {res.get('error')}")
    return res


# --- commands -------------------------------------------------------------------

def do_hook(args) -> int:
    """Claude Code hook entry point. Must never fail or block Claude."""
    payload = {}
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            payload = json.loads(raw) if raw.strip() else {}
    except (OSError, ValueError):
        pass
    event = args.event
    if event == "permission" and payload.get("notification_type") not in (None, "permission_prompt"):
        return 0
    try:
        if not daemon_running():
            start_daemon()
        _request("/event", {"event": event, "session_id": payload.get("session_id")}, timeout=2)
    except Exception as e:
        print(f"mokuru: {e}", file=sys.stderr)
    return 0


def do_tap(args) -> int:
    """Status-line tap: save Claude Code's status JSON, then pass it on."""
    data = sys.stdin.buffer.read()
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = config.STATUS_FILE.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, config.STATUS_FILE)
    except OSError:
        pass
    if args.command:
        return subprocess.run(args.command, input=data).returncode
    try:
        s = json.loads(data)
        pct = (s.get("context_window") or {}).get("used_percentage") or 0
        cost = (s.get("cost") or {}).get("total_cost_usd") or 0
        print(f"{(s.get('model') or {}).get('display_name', 'claude')} · {pct:.0f}% · ${cost:.2f}")
    except (ValueError, AttributeError):
        print("claude")
    return 0


def do_light(args) -> int:
    if args.mode == "off":
        light = Lighting(MODES["static"], 2, 0, 0, FLAG_FIXED, (0, 0, 0))
    else:
        light = Lighting(MODES[args.mode], args.speed, args.brightness, args.option,
                         FLAG_FIXED if args.color else FLAG_RAINBOW,
                         args.color or (250, 250, 250))
    res = cmd("light", lighting=light.as_dict())
    print("lighting:", res["baseline"])
    return 0


def do_status(args) -> int:
    if not daemon_running():
        print("daemon: not running")
        return 1
    print(json.dumps(_request("/status"), indent=2))
    return 0


def do_stop(args) -> int:
    if daemon_running():
        _request("/shutdown", {})
        print("daemon stopped")
    else:
        print("daemon: not running")
    return 0


def parse_rgb(s: str):
    s = s.lstrip("#")
    if len(s) != 6:
        raise argparse.ArgumentTypeError("colour must be RRGGBB")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="mokuru", description="MOKURU AK8753 lights and LCD")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("daemon", help="run the background service in the foreground")
    sub.add_parser("tray", help="run the service with a tray icon")
    sub.add_parser("start", help="start the background service")
    sub.add_parser("stop", help="stop the background service")
    sub.add_parser("status", help="service state as JSON")
    sub.add_parser("info", help="identify the keyboard")
    sub.add_parser("clock", help="set the LCD clock to local time")
    sub.add_parser("pause", help="stop reacting to Claude Code")
    sub.add_parser("resume", help="react to Claude Code again")

    lp = sub.add_parser("light", help="set your own lighting (restored after Claude)")
    lp.add_argument("mode", choices=sorted(set(MODES) - {"per-key"}) + ["off"])
    lp.add_argument("--color", type=parse_rgb, help="RRGGBB; omit for rainbow")
    lp.add_argument("--speed", type=int, default=2, choices=range(5), help="0 fast .. 4 slow")
    lp.add_argument("--brightness", type=int, default=4, choices=range(5))
    lp.add_argument("--option", type=int, default=0, help="direction / variant")

    ip = sub.add_parser("image", help="put a picture on the LCD (~20 s)")
    ip.add_argument("file", help="image file, or 'test'")
    ip.add_argument("--slot", type=int, default=0, choices=range(SCREEN_SLOTS))

    gp = sub.add_parser("gif", help="put an animation on the LCD (~20 s a frame)")
    gp.add_argument("file", help="GIF file, or 'claude' for the built-in spark")
    gp.add_argument("--frames", type=int, default=SCREEN_SLOTS,
                    help=f"frames to keep (max {SCREEN_SLOTS}; uses slots 1..N)")
    gp.add_argument("--delay", type=int, help="frame delay in 10 ms units (default: from the GIF)")

    cp = sub.add_parser("lcd", help="Claude/system screens on the LCD: usage (on), off, or blank SLOTS")
    cp.add_argument("mode", choices=["usage", "off", "blank"])
    cp.add_argument("slots", nargs="*", type=int, help="with 'blank': slots to clear (0-4)")

    hp = sub.add_parser("hook", help="(Claude Code hook entry point)")
    hp.add_argument("event", choices=sorted(set(HOOK_EVENTS.values())))

    tp = sub.add_parser("tap", help="(status-line tap) save status JSON, pass stdin to COMMAND")
    tp.add_argument("command", nargs=argparse.REMAINDER)

    for name in ("install", "uninstall"):
        p = sub.add_parser(name, help=f"{name} integrations")
        p.add_argument("what", choices=["hooks", "autostart", "statusline", "udev", "all"])
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    c = args.cmd
    if c == "hook":
        return do_hook(args)
    if c == "tap":
        if args.command and args.command[0] == "--":
            args.command = args.command[1:]
        return do_tap(args)
    if c == "daemon":
        from .daemon import serve
        serve()
        return 0
    if c == "tray":
        if daemon_running():  # take over from a plain background daemon
            _request("/shutdown", {})
            deadline = time.monotonic() + 5
            while daemon_running() and time.monotonic() < deadline:
                time.sleep(0.1)
            time.sleep(0.5)
        from .tray import run_tray
        return run_tray()
    if c == "start":
        print("daemon running" if start_daemon() else f"failed, see {config.LOG_FILE}")
        return 0
    if c == "stop":
        return do_stop(args)
    if c == "status":
        return do_status(args)
    if c == "info":
        res = cmd("info")
        print(f"device {res['device']}  firmware {res['firmware']}  display {res['display']}")
        print("lighting:", res["lighting"])
        print("claude state:", res["state"], "(paused)" if res["paused"] else "")
        return 0
    if c == "clock":
        cmd("clock")
        print("clock set")
        return 0
    if c in ("pause", "resume"):
        config.set_paused(c == "pause")
        print("paused" if c == "pause" else "resumed")
        return 0
    if c == "light":
        return do_light(args)
    if c == "image":
        path = args.file if args.file == "test" else os.path.abspath(args.file)
        t = time.monotonic()
        cmd("image", path=path, slot=args.slot)
        print(f"uploaded in {time.monotonic() - t:.0f}s (usage card turned off; `mokuru lcd usage` to restore)")
        return 0
    if c == "gif":
        path = args.file if args.file == "claude" else os.path.abspath(args.file)
        t = time.monotonic()
        res = cmd("gif", path=path, frames=min(args.frames, SCREEN_SLOTS), delay=args.delay)
        print(f"{res['frames']} frames uploaded in {time.monotonic() - t:.0f}s "
              f"(usage card turned off; `mokuru lcd usage` to restore)")
        return 0
    if c == "lcd":
        if args.mode == "blank":
            if not args.slots or any(not 0 <= s < SCREEN_SLOTS for s in args.slots):
                raise SystemExit(f"mokuru: give slots 0..{SCREEN_SLOTS - 1} to blank")
            t = time.monotonic()
            cmd("blank", slots=args.slots)
            print(f"blanked slots {args.slots} in {time.monotonic() - t:.0f}s")
            return 0
        res = cmd("lcd", enabled=args.mode == "usage")
        print("LCD screens", "on" if res["lcd"]["enabled"] else "off")
        return 0
    if c in ("install", "uninstall"):
        from . import install
        return install.run(c, args.what)
    return 1


if __name__ == "__main__":
    sys.exit(main())

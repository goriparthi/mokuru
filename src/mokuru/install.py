"""Installers: Claude Code hooks and status line, autostart, Linux udev rule."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from . import config

CLAUDE_SETTINGS = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
MARKERS = ("mokuru", "akdeck")

HOOKS = [
    # (event, matcher, mokuru event, async)
    ("UserPromptSubmit", None, "prompt", True),
    ("PostToolUse", "*", "tool", True),
    ("Notification", "permission_prompt", "permission", True),
    ("Stop", None, "stop", True),
    ("SessionEnd", None, "end", False),
]

UDEV_RULE = ('SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3151", ATTRS{idProduct}=="5002", '
             'MODE="0660", TAG+="uaccess"\n')


def _python() -> str:
    return sys.executable.replace("\\", "/")


def _ours(hook: dict) -> bool:
    text = " ".join([hook.get("command", "")] + list(hook.get("args") or []))
    return any(m in text for m in MARKERS)


def _load_settings() -> dict:
    try:
        return json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _save_settings(s: dict) -> None:
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    if CLAUDE_SETTINGS.exists():
        backup = CLAUDE_SETTINGS.with_suffix(".json.bak-mokuru")
        if not backup.exists():
            shutil.copy2(CLAUDE_SETTINGS, backup)
    CLAUDE_SETTINGS.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")


def remove_hooks(s: dict) -> int:
    removed = 0
    hooks = s.get("hooks") or {}
    for event in list(hooks):
        groups = []
        for g in hooks[event]:
            kept = [h for h in g.get("hooks", []) if not _ours(h)]
            removed += len(g.get("hooks", [])) - len(kept)
            if kept:
                groups.append({**g, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not hooks:
        s.pop("hooks", None)
    return removed


def install_hooks() -> None:
    s = _load_settings()
    remove_hooks(s)
    hooks = s.setdefault("hooks", {})
    for event, matcher, ev, is_async in HOOKS:
        h = {"type": "command", "command": _python(),
             "args": ["-m", "mokuru", "hook", ev], "timeout": 10}
        if is_async:
            h["async"] = True
        group = {"hooks": [h]}
        if matcher:
            group = {"matcher": matcher, **group}
        hooks.setdefault(event, []).append(group)
    _save_settings(s)
    print(f"hooks installed in {CLAUDE_SETTINGS}")


def uninstall_hooks() -> None:
    s = _load_settings()
    n = remove_hooks(s)
    _save_settings(s)
    print(f"removed {n} hook(s) from {CLAUDE_SETTINGS}")


def install_statusline() -> None:
    s = _load_settings()
    line = s.get("statusLine") or {}
    current = line.get("command", "")
    if "mokuru" in current or "mokuru" in json.dumps(line.get("args", [])):
        print("status line already taps into mokuru")
        return
    tap = f'"{_python()}" -m mokuru tap'
    if current:
        new = f"{tap} -- {current}"
        print(f"wrapping your status line: {current}")
    else:
        new = tap
    s["statusLine"] = {**line, "type": "command", "command": new}
    _save_settings(s)
    print("status line now feeds the LCD usage card")
    if current.strip().endswith(".sh"):
        print("tip: a bash status line can skip the wrapper (and its Python start-up) by\n"
              "adding this after it reads stdin into $payload:\n"
              f'  mkdir -p "$HOME/.mokuru" && printf \'%s\' "$payload" > "$HOME/.mokuru/status.json"')


def uninstall_statusline() -> None:
    s = _load_settings()
    line = s.get("statusLine") or {}
    cmd = line.get("command", "")
    if "mokuru tap" not in cmd:
        print("status line does not use the mokuru wrapper")
        return
    rest = cmd.split(" -- ", 1)[1] if " -- " in cmd else ""
    if rest:
        s["statusLine"] = {**line, "command": rest}
    else:
        s.pop("statusLine", None)
    _save_settings(s)
    print("status line restored")


# --- autostart -----------------------------------------------------------------

def _autostart_target() -> list[str]:
    try:
        import pystray  # noqa: F401
        mode = "tray"
    except ImportError:
        mode = "daemon"
    from .cli import _python_for_background
    return [_python_for_background(), "-m", "mokuru", mode]


def _autostart_path() -> Path:
    if sys.platform == "win32":
        return (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu"
                / "Programs" / "Startup" / "mokuru.vbs")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / "com.goriparthi.mokuru.plist"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "mokuru.desktop"


def install_autostart() -> None:
    argv = _autostart_target()
    path = _autostart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        quoted = " ".join(f'""{a}""' for a in argv)
        path.write_text(f'CreateObject("WScript.Shell").Run "{quoted}", 0, False\n', encoding="utf-8")
    elif sys.platform == "darwin":
        args = "".join(f"    <string>{a}</string>\n" for a in argv)
        path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            '  <key>Label</key><string>com.goriparthi.mokuru</string>\n'
            f'  <key>ProgramArguments</key><array>\n{args}  </array>\n'
            '  <key>RunAtLoad</key><true/>\n'
            f'  <key>StandardErrorPath</key><string>{config.LOG_FILE}</string>\n'
            '</dict></plist>\n', encoding="utf-8")
    else:
        exec_line = " ".join(f'"{a}"' for a in argv)
        path.write_text("[Desktop Entry]\nType=Application\nName=mokuru\n"
                        f"Exec={exec_line}\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")
    print(f"autostart: {path} ({argv[-1]} at login)")


def uninstall_autostart() -> None:
    path = _autostart_path()
    try:
        path.unlink()
        print(f"removed {path}")
    except FileNotFoundError:
        print("autostart was not installed")


def install_udev() -> None:
    if not sys.platform.startswith("linux"):
        print("udev rules are Linux only; nothing to do")
        return
    print("Linux needs a udev rule so non-root users can open the keyboard. Run:\n"
          f"  echo '{UDEV_RULE.strip()}' | sudo tee /etc/udev/rules.d/99-mokuru.rules\n"
          "  sudo udevadm control --reload-rules && sudo udevadm trigger\n"
          "then replug the keyboard.")


def run(action: str, what: str) -> int:
    targets = ["hooks", "statusline", "autostart", "udev"] if what == "all" else [what]
    for t in targets:
        fn = globals()[f"{action}_{t}"] if f"{action}_{t}" in globals() else None
        if fn is None:
            print(f"nothing to {action} for {t}")
            continue
        fn()
    return 0

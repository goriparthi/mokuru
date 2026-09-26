"""Settings and small state files under ~/.mokuru."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

STATE_DIR = Path(os.environ.get("MOKURU_HOME") or Path.home() / ".mokuru")
CONFIG_FILE = STATE_DIR / "config.json"
BASELINE_FILE = STATE_DIR / "baseline.json"
STATUS_FILE = STATE_DIR / "status.json"
COSTS_FILE = STATE_DIR / "costs.json"
PAUSED_FILE = STATE_DIR / "paused"
PID_FILE = STATE_DIR / "daemon.pid"
PORT_FILE = STATE_DIR / "daemon.port"
LOG_FILE = STATE_DIR / "daemon.log"

DEFAULTS = {
    "port": 38917,          # first choice; the daemon walks up if taken
    "claude_lighting": True,   # react to Claude Code hooks
    "per_key": True,           # while working: context bar on the F-row
    "done_hold": 4.0,          # seconds of green after Claude finishes
    "dial_switcher": True,     # Ctrl + dial = app switcher (Windows)
    "colors": {
        "working": [217, 119, 87],
        "attention": [255, 0, 0],
        "done": [0, 220, 60],
    },
    "lcd": {
        "enabled": True,       # Claude screens from the status line
        # LCD slot -> screen: "session" (model, context, cost, lines) or
        # "usage" (plan limits, context, dollars today)
        "screens": {"0": "session", "1": "usage"},
        "min_interval": 300,   # seconds between uploads of one screen (~20 s of flash each)
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    try:
        return _merge(DEFAULTS, json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)


def save(cfg: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def load_baseline():
    from .device import Lighting
    try:
        return Lighting.from_dict(json.loads(BASELINE_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_baseline(light) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(json.dumps(light.as_dict()) + "\n", encoding="utf-8")


def paused() -> bool:
    return PAUSED_FILE.exists()


def set_paused(on: bool) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if on:
        PAUSED_FILE.touch()
    else:
        try:
            PAUSED_FILE.unlink()
        except OSError:
            pass


def daemon_port() -> int:
    """Where the running daemon listens (it may have skipped a taken port)."""
    try:
        return int(PORT_FILE.read_text().strip())
    except (OSError, ValueError):
        return int(load()["port"])

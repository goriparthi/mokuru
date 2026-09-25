"""Tray icon: runs the service and shows Claude's state. Needs `pystray`."""
from __future__ import annotations

import math
import sys
import threading

from PIL import Image, ImageDraw

from . import config
from .daemon import Daemon, serve
from .device import FLAG_FIXED, FLAG_RAINBOW, MODES, Lighting

STATE_COLORS = {
    "idle": (150, 150, 156), "working": (217, 119, 87),
    "attention": (230, 50, 50), "done": (60, 200, 100),
}

PRESETS = {
    "Rainbow wave": Lighting(MODES["wave"], 2, 4, 0, FLAG_RAINBOW),
    "Spectrum": Lighting(MODES["spectrum"], 2, 4, 0, FLAG_RAINBOW),
    "Claude orange": Lighting(MODES["static"], 2, 4, 0, FLAG_FIXED, (217, 119, 87)),
    "White": Lighting(MODES["static"], 2, 4, 0, FLAG_FIXED, (250, 250, 250)),
    "Off": Lighting(MODES["static"], 2, 0, 0, FLAG_FIXED, (0, 0, 0)),
}


def icon_image(rgb, disconnected: bool = False) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(12):
        a = i * math.pi / 6
        r2 = 30 if i % 2 == 0 else 22
        d.line([(32 + 8 * math.cos(a), 32 + 8 * math.sin(a)),
                (32 + r2 * math.cos(a), 32 + r2 * math.sin(a))], fill=rgb, width=6)
    if disconnected:
        d.line([(8, 56), (56, 8)], fill=(120, 120, 120), width=6)
    return img


def run_tray() -> int:
    try:
        import pystray
    except ImportError:
        print("the tray needs pystray: pip install 'mokuru[tray]'", file=sys.stderr)
        return 1

    daemon = serve(Daemon(), block=False)

    def label(_):
        info = daemon.info()
        if not info["connected"]:
            return "Keyboard not connected"
        return f"Claude: {info['state']}" + (" (paused)" if info["paused"] else "")

    def toggle_pause(icon, _):
        config.set_paused(not config.paused())

    def toggle_lcd(icon, _):
        threading.Thread(target=daemon.command, daemon=True,
                         args=("lcd", {"enabled": not daemon.cfg["lcd"]["enabled"]})).start()

    def claude_gif(icon, _):
        threading.Thread(target=daemon.command, daemon=True,
                         args=("gif", {"path": "claude"})).start()

    def preset(name):
        def go(icon, _):
            threading.Thread(target=daemon.command, daemon=True,
                             args=("light", {"lighting": PRESETS[name].as_dict()})).start()
        return go

    def quit_(icon, _):
        daemon.stop_evt.set()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(label, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Pause Claude lighting", toggle_pause,
                         checked=lambda _: config.paused()),
        pystray.MenuItem("Usage card on LCD", toggle_lcd,
                         checked=lambda _: daemon.cfg["lcd"]["enabled"]),
        pystray.MenuItem("Put Claude animation on LCD", claude_gif),
        pystray.MenuItem("My lighting", pystray.Menu(
            *[pystray.MenuItem(n, preset(n)) for n in PRESETS])),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_),
    )
    icon = pystray.Icon("mokuru", icon_image(STATE_COLORS["idle"]), "mokuru", menu)

    def refresh():
        last = None
        while not daemon.stop_evt.wait(1.0):
            info = daemon.info()
            key = (info["state"], info["connected"], info["paused"])
            if key != last:
                color = STATE_COLORS["idle"] if info["paused"] else STATE_COLORS[info["state"]]
                icon.icon = icon_image(color, not info["connected"])
                icon.title = f"mokuru: {label(None)}"
                icon.update_menu()
                last = key
        icon.stop()

    threading.Thread(target=refresh, daemon=True).start()
    icon.run()
    daemon.stop_evt.set()
    return 0

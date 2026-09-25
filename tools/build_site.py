"""Render the website's images from the real code: keyboard states and LCD cards.

    python tools/build_site.py      # writes docs/assets/*
"""
from __future__ import annotations

import colorsys
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mokuru import keys, screen  # noqa: E402
from mokuru.config import DEFAULTS  # noqa: E402

OUT = ROOT / "docs" / "assets"
LAYOUT = json.loads((ROOT / "tools" / "ak8753_layout.json").read_text(encoding="utf-8"))

SAMPLE_STATUS = {
    "model": {"display_name": "Opus 5.5"},
    "session_name": "mokuru",
    "context_window": {"used_percentage": 42},
    "cost": {"total_cost_usd": 3.18, "total_lines_added": 1284, "total_lines_removed": 97},
}


def hexc(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb)


def state_colors(state: str) -> dict:
    """Key code -> colour, the way the daemon lights the board."""
    c = DEFAULTS["colors"]
    out = {}
    if state == "working":
        pattern = keys.context_pattern(42, tuple(c["working"]))
        for code, slot in keys.KEY_SLOT.items():
            out[code] = pattern[slot * 3:slot * 3 + 3]
        # the per-key pattern is dim on hardware; lift it so it reads on screen
        out = {k: tuple(min(255, int(v * 1.6)) for v in rgb) for k, rgb in out.items()}
    elif state in ("attention", "done"):
        rgb = c["attention" if state == "attention" else "done"]
        out = {code: rgb for code in keys.KEY_SLOT}
    else:  # idle: the user's rainbow wave
        w = LAYOUT["canvas"]["width"]
        for k in LAYOUT["keys"]:
            h = (k["x"] + k["w"] / 2) / w
            out[k["code"]] = tuple(int(v * 255) for v in colorsys.hsv_to_rgb(h, 0.75, 1))
    return out


def keyboard_svg(state: str) -> str:
    colors = state_colors(state)
    W, H = LAYOUT["canvas"]["width"], LAYOUT["canvas"]["height"]
    pad = 14
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-pad} {-pad} {W + 2 * pad} {H + 2 * pad}" '
             f'role="img" aria-label="AK8753 keyboard, {state}">',
             '<defs><filter id="g" x="-50%" y="-50%" width="200%" height="200%">'
             '<feGaussianBlur stdDeviation="5"/></filter></defs>',
             f'<rect x="{-pad}" y="{-pad}" width="{W + 2 * pad}" height="{H + 2 * pad}" rx="18" fill="#1b1b1f" stroke="#2c2c33"/>']
    glow, caps = [], []
    for k in LAYOUT["keys"]:
        x, y, w, h = k["x"], k["y"], k["w"], k["h"]
        if k["type"] == "knob":
            continue
        rgb = colors.get(k["code"], (40, 40, 44))
        col = hexc(rgb)
        glow.append(f'<rect x="{x + 3}" y="{y + 3}" width="{w - 6}" height="{h - 6}" rx="6" fill="{col}" opacity=".55"/>')
        caps.append(f'<rect x="{x + 2}" y="{y + 2}" width="{w - 4}" height="{h - 4}" rx="6" fill="#26262b" '
                    f'stroke="{col}" stroke-width="2"/>')
        label = k.get("text") or ""
        if label and len(label) <= 9:
            size = 11 if len(label) <= 2 else 9
            caps.append(f'<text x="{x + w / 2}" y="{y + h / 2 + size / 3}" font-size="{size}" '
                        f'text-anchor="middle" fill="{col}" font-family="system-ui,sans-serif">{html.escape(label)}</text>')
    knob = [k for k in LAYOUT["keys"] if k["type"] == "knob"]
    kx = (min(k["x"] for k in knob) + max(k["x"] + k["w"] for k in knob)) / 2
    parts.append(f'<g filter="url(#g)">{"".join(glow)}</g>')
    parts += caps
    parts.append(f'<circle cx="{kx}" cy="26" r="24" fill="#303036" stroke="#4a4a52" stroke-width="2"/>'
                 f'<circle cx="{kx}" cy="26" r="17" fill="#26262b"/>')
    parts.append("</svg>")
    return "".join(parts)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for state in ("idle", "working", "attention", "done"):
        (OUT / f"keyboard-{state}.svg").write_text(keyboard_svg(state), encoding="utf-8", newline="\n")
    screen.preview(screen.usage_card(SAMPLE_STATUS, now=1790376000), str(OUT / "lcd-usage.png"), 2)
    screen.preview(screen.spark_frames(1)[0], str(OUT / "lcd-spark.png"), 2)
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()

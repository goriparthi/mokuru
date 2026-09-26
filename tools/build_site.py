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
    "context_window": {"used_percentage": 42, "total_input_tokens": 84000,
                       "context_window_size": 200000},
    "cost": {"total_cost_usd": 3.18, "total_lines_added": 1284, "total_lines_removed": 97},
    "rate_limits": {"five_hour": {"used_percentage": 18, "resets_at": 1790384400},
                    "seven_day": {"used_percentage": 34, "resets_at": 1790665200}},
}


SAMPLE_SYSTEM = {
    "cpu": 23, "cores": 12, "ghz": 3.4, "host": "workstation",
    "mem": {"percent": 58, "used": 18.6 * 2**30, "total": 32 * 2**30},
    "disk": {"percent": 46, "used": 438 * 2**30, "total": 953 * 2**30},
    "uptime": 2 * 86400 + 5 * 3600,
}


SAMPLE_NETWORK = {
    "recv_total": 18.4 * 2**30, "sent_total": 3.2 * 2**30, "ip": "192.168.1.20",
    "links": [{"kind": "ethernet", "name": "Ethernet", "ip": "192.168.1.20", "ssid": None},
              {"kind": "wifi", "name": "Wi-Fi", "ip": "192.168.1.21", "ssid": "home-wifi"}],
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


def _card_font(size: int, weight: str = "regular"):
    from PIL import ImageFont
    names = {"bold": ["segoeuib.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"],
             "semi": ["seguisb.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"],
             "regular": ["segoeui.ttf", "DejaVuSans.ttf", "arial.ttf"]}[weight]
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def keyboard_png(state: str, width: int):
    """The keyboard art as a raster (for share cards, which can't use SVG)."""
    from PIL import Image, ImageDraw, ImageFilter
    colors = state_colors(state)
    W, H = LAYOUT["canvas"]["width"], LAYOUT["canvas"]["height"]
    pad, ss = 14, 3                                   # supersample for smooth edges
    s = width / (W + 2 * pad) * ss
    size = (int((W + 2 * pad) * s), int((H + 2 * pad) * s))
    base = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=int(18 * s),
                        fill=(27, 27, 31, 255), outline=(44, 44, 51, 255), width=int(1.5 * s))
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    caps = []
    for k in LAYOUT["keys"]:
        if k["type"] == "knob":
            continue
        x, y = (k["x"] + pad) * s, (k["y"] + pad) * s
        w, h = k["w"] * s, k["h"] * s
        rgb = tuple(int(c) for c in colors.get(k["code"], (40, 40, 44)))
        g.rounded_rectangle([x + 3 * s, y + 3 * s, x + w - 3 * s, y + h - 3 * s],
                            radius=int(6 * s), fill=rgb + (150,))
        caps.append((x, y, w, h, rgb))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5 * s)))
    d = ImageDraw.Draw(base)
    for x, y, w, h, rgb in caps:
        d.rounded_rectangle([x + 2 * s, y + 2 * s, x + w - 2 * s, y + h - 2 * s],
                            radius=int(6 * s), fill=(38, 38, 43, 255), outline=rgb + (255,),
                            width=int(2 * s))
    knob = [k for k in LAYOUT["keys"] if k["type"] == "knob"]
    kx = ((min(k["x"] for k in knob) + max(k["x"] + k["w"] for k in knob)) / 2 + pad) * s
    ky = (26 + pad) * s
    d.ellipse([kx - 24 * s, ky - 24 * s, kx + 24 * s, ky + 24 * s],
              fill=(48, 48, 54, 255), outline=(74, 74, 82, 255), width=int(2 * s))
    d.ellipse([kx - 17 * s, ky - 17 * s, kx + 17 * s, ky + 17 * s], fill=(38, 38, 43, 255))
    return base.resize((size[0] // ss, size[1] // ss), Image.LANCZOS)


def social_card(path: Path) -> None:
    """1200x630 PNG for link previews (Slack, iMessage, X, LinkedIn, ...)."""
    import math as _m
    from PIL import Image, ImageDraw, ImageFilter
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), (15, 15, 18))
    # warm glow behind the headline
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse([200, -260, 1000, 260], fill=(90, 44, 30))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(120)), 0.55)
    d = ImageDraw.Draw(img)

    # brand
    cx, cy = 76, 70
    for i in range(12):
        a = i * _m.pi / 6
        r2 = 20 if i % 2 == 0 else 15
        d.line([(cx + 6 * _m.cos(a), cy + 6 * _m.sin(a)), (cx + r2 * _m.cos(a), cy + r2 * _m.sin(a))],
               fill=(217, 119, 87), width=5)
    d.text((108, cy), "mokuru", fill=(236, 236, 240), font=_card_font(40, "bold"), anchor="lm")
    d.text((W - 60, cy), "goriparthi.github.io/mokuru", fill=(150, 150, 160),
           font=_card_font(24), anchor="rm")

    # headline + features
    d.text((60, 128), "Make your keyboard ", fill=(236, 236, 240), font=_card_font(64, "bold"), anchor="lt")
    hw = d.textlength("Make your keyboard ", font=_card_font(64, "bold"))
    d.text((60 + hw, 128), "do more.", fill=(217, 119, 87), font=_card_font(64, "bold"), anchor="lt")
    d.text((62, 218), "Live LCD screens · scriptable lighting · dial app switcher · Claude Code on your keys",
           fill=(170, 170, 180), font=_card_font(25), anchor="lt")

    # keyboard + LCD
    kb = keyboard_png("working", 800)
    img.paste(kb, (60, 630 - kb.height - 40), kb)
    from PIL import Image as _I
    lcd = _I.frombytes("RGB", (135, 240), screen.limits_card(SAMPLE_STATUS, 11.62, 3, now=1790376000))
    lh = 318
    lcd = lcd.resize((int(135 * lh / 240), lh), _I.LANCZOS)
    fx, fy = W - lcd.width - 70, 630 - lh - 46
    frame = ImageDraw.Draw(img)
    frame.rounded_rectangle([fx - 10, fy - 10, fx + lcd.width + 10, fy + lh + 10], radius=16,
                            fill=(9, 9, 11), outline=(42, 42, 50), width=2)
    img.paste(lcd, (fx, fy))
    img.save(path, optimize=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for state in ("idle", "working", "attention", "done"):
        (OUT / f"keyboard-{state}.svg").write_text(keyboard_svg(state), encoding="utf-8", newline="\n")
    screen.preview(screen.system_card(SAMPLE_SYSTEM, now=1790376000), str(OUT / "lcd-system.png"), 2)
    screen.preview(screen.network_card(SAMPLE_NETWORK, now=1790376000), str(OUT / "lcd-network.png"), 2)
    screen.preview(screen.limits_card(SAMPLE_STATUS, 11.62, 3, now=1790376000),
                   str(OUT / "lcd-limits.png"), 2)
    social_card(OUT / "social.png")
    icon = keyboard_png("working", 360)       # square-ish touch icon from the art
    from PIL import Image
    sq = Image.new("RGB", (180, 180), (15, 15, 18))
    icon = icon.resize((172, int(icon.height * 172 / icon.width)), Image.LANCZOS)
    sq.paste(icon, (4, (180 - icon.height) // 2), icon)
    sq.save(OUT / "icon-180.png", optimize=True)
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()

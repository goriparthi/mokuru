"""Pictures for the 135x240 LCD: image loading and the live screens."""
from __future__ import annotations

import math
import time

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .device import SCREEN_H, SCREEN_SLOTS, SCREEN_W

SIZE = (SCREEN_W, SCREEN_H)
CLAUDE = (217, 119, 87)
BG = (18, 18, 20)
FG = (236, 236, 236)
DIM = (140, 140, 146)
GREEN, YELLOW, RED = (70, 200, 110), (235, 190, 60), (230, 70, 60)


def _font(size: int, bold: bool = False):
    names = (["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "Helvetica-Bold"]
             if bold else ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "Helvetica"])
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fitted(d, text: str, size: int, max_w: float, bold: bool = True):
    """The largest font up to `size` that keeps `text` within `max_w` pixels."""
    while size > 10:
        f = _font(size, bold)
        if d.textlength(text, font=f) <= max_w:
            return f
        size -= 1
    return _font(size, bold)


def fit(img: Image.Image) -> bytes:
    return ImageOps.fit(img.convert("RGB"), SIZE, Image.LANCZOS).tobytes()


def load_image(path: str) -> bytes:
    with Image.open(path) as img:
        return fit(img)


def test_pattern() -> bytes:
    """Orientation check: red top band, blue bottom, green left edge."""
    img = Image.new("RGB", SIZE, (20, 20, 20))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, SCREEN_W - 1, 39], fill=(220, 30, 30))
    d.rectangle([0, SCREEN_H - 40, SCREEN_W - 1, SCREEN_H - 1], fill=(30, 60, 220))
    d.rectangle([0, 40, 14, SCREEN_H - 41], fill=(30, 200, 60))
    d.text((50, 14), "TOP", fill=(255, 255, 255))
    d.text((40, SCREEN_H - 26), "BOTTOM", fill=(255, 255, 255))
    d.ellipse([47, 90, 87, 130], outline=CLAUDE, width=4)
    return img.tobytes()


def _level_color(pct: float):
    return GREEN if pct < 70 else YELLOW if pct < 90 else RED


def usage_card(status: dict, state: str = "idle", now: float | None = None) -> bytes:
    """Claude Code session summary from the status-line payload."""
    model = (status.get("model") or {}).get("display_name") or "claude"
    model = model.split("(")[0].strip()
    ctx = status.get("context_window") or {}
    pct = float(ctx.get("used_percentage") or 0)
    cost = float((status.get("cost") or {}).get("total_cost_usd") or 0)
    ws = status.get("workspace") or {}
    cwd = ws.get("project_dir") or ws.get("current_dir") or status.get("cwd") or ""
    project = status.get("session_name") or (
        cwd.replace("\\", "/").rstrip("/").split("/")[-1] if cwd else "")
    lines_added = (status.get("cost") or {}).get("total_lines_added")
    lines_removed = (status.get("cost") or {}).get("total_lines_removed")

    img = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(img)
    x0, x1 = 7, SCREEN_W - 7
    # header
    d.rectangle([0, 0, SCREEN_W, 32], fill=CLAUDE)
    d.text((SCREEN_W // 2, 16), "claude code", fill=(255, 255, 255),
           font=_font(18, True), anchor="mm")
    d.text((x0, 40), model.lower(), fill=FG, font=_font(22, True))
    if project:
        d.text((x0, 68), project[:14], fill=DIM, font=_font(17))
    # context: label and value share a row, bar underneath
    col = _level_color(pct)
    label = _font(15)
    room = x1 - x0 - d.textlength("context", font=label) - 6
    d.text((x0, 124), "context", fill=DIM, font=label, anchor="ls")
    d.text((x1, 126), f"{pct:.0f}%", fill=col,
           font=_fitted(d, f"{pct:.0f}%", 30, room), anchor="rs")
    d.rounded_rectangle([x0, 134, x1, 150], radius=5, outline=(70, 70, 76))
    w = int((x1 - x0 - 2) * min(pct, 100) / 100)
    if w > 0:
        d.rounded_rectangle([x0 + 1, 135, x0 + 1 + w, 149], radius=4, fill=col)
    # cost
    room = x1 - x0 - d.textlength("cost", font=label) - 6
    d.text((x0, 196), "cost", fill=DIM, font=label, anchor="ls")
    d.text((x1, 198), f"${cost:.2f}", fill=FG,
           font=_fitted(d, f"${cost:.2f}", 30, room), anchor="rs")
    # footer: lines changed, and when this card was drawn (keys show live state)
    fy = SCREEN_H - 14
    if lines_added is not None:
        f = _font(15)
        plus = f"+{lines_added}"
        d.text((x0, fy), plus, fill=GREEN, font=f, anchor="lm")
        d.text((x0 + d.textlength(plus, font=f) + 5, fy), f"-{lines_removed or 0}",
               fill=RED, font=f, anchor="lm")
    d.text((x1, fy), time.strftime("%H:%M", time.localtime(now or time.time())),
           fill=DIM, font=_font(15), anchor="rm")
    return img.tobytes()


def _tokens(n) -> str:
    n = float(n or 0)
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else f"{n:.0f}"


def _gauge(d, y: int, label: str, pct, detail: str, x0: int, x1: int) -> None:
    """56 px: label + big % on one row, a bar, then a detail line."""
    small = _font(16)
    d.text((x0, y + 23), label, fill=DIM, font=small, anchor="ls")
    if pct is None:
        d.text((x1, y + 25), "–", fill=DIM, font=_font(26, True), anchor="rs")
        pct_v, col = 0.0, DIM
    else:
        pct_v = float(pct)
        col = _level_color(pct_v)
        room = x1 - x0 - d.textlength(label, font=small) - 6
        d.text((x1, y + 25), f"{pct_v:.0f}%", fill=col,
               font=_fitted(d, f"{pct_v:.0f}%", 28, room), anchor="rs")
    d.rounded_rectangle([x0, y + 29, x1, y + 37], radius=4, outline=(70, 70, 76))
    w = int((x1 - x0 - 2) * min(pct_v, 100) / 100)
    if w > 0:
        d.rounded_rectangle([x0 + 1, y + 30, x0 + 1 + w, y + 36], radius=3, fill=col)
    if detail:
        d.text((x0, y + 53), detail, fill=DIM,
               font=_fitted(d, detail, 15, x1 - x0, False), anchor="ls")


def _reset_text(ts) -> str:
    if not ts:
        return ""
    try:
        t = time.localtime(float(ts))
    except (TypeError, ValueError, OverflowError):
        return ""
    today = time.localtime()
    same_day = t.tm_yday == today.tm_yday and t.tm_year == today.tm_year
    return "resets " + time.strftime("%H:%M" if same_day else "%a %H:%M", t)


def limits_card(status: dict, today_cost: float | None = None,
                today_sessions: int | None = None, now: float | None = None) -> bytes:
    """Plan usage (5-hour / weekly), context, and dollars."""
    limits = status.get("rate_limits") or {}
    five = limits.get("five_hour") or {}
    week = limits.get("seven_day") or {}
    ctx = status.get("context_window") or {}
    used_tokens = ctx.get("total_input_tokens")
    window = ctx.get("context_window_size")
    session_cost = float((status.get("cost") or {}).get("total_cost_usd") or 0)

    img = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(img)
    x0, x1 = 7, SCREEN_W - 7
    d.rectangle([0, 0, SCREEN_W, 22], fill=CLAUDE)
    d.text((SCREEN_W // 2, 11), "claude usage", fill=(255, 255, 255),
           font=_font(17, True), anchor="mm")

    gauges = []
    if five:
        gauges.append(("5 hour", five.get("used_percentage"), _reset_text(five.get("resets_at"))))
    gauges.append(("week", week.get("used_percentage") if week else None,
                   _reset_text(week.get("resets_at")) if week else "no limit data"))
    gauges.append(("context", ctx.get("used_percentage"),
                   f"{_tokens(used_tokens)} of {_tokens(window)}"
                   if used_tokens is not None and window else ""))
    y = 22
    for label, pct, detail in gauges:
        _gauge(d, y, label, pct, detail, x0, x1)
        y += 56

    # dollars: today across all sessions, big; this session and the time, small
    d.line([x0, y + 2, x1, y + 2], fill=(40, 40, 46))
    label = _font(16)
    today = today_cost if today_cost is not None else session_cost
    d.text((x0, y + 27), "today", fill=DIM, font=label, anchor="ls")
    room = x1 - x0 - d.textlength("today", font=label) - 6
    d.text((x1, y + 30), f"${today:.2f}", fill=FG,
           font=_fitted(d, f"${today:.2f}", 30, room), anchor="rs")
    n = today_sessions or 1
    sess = f"{n} session" + ("s" if n != 1 else "")
    clock = time.strftime("%H:%M", time.localtime(now or time.time()))
    small = _font(15)
    d.text((x1, SCREEN_H - 3), clock, fill=DIM, font=small, anchor="rs")
    d.text((x0, SCREEN_H - 3), sess, fill=DIM,
           font=_fitted(d, sess, 15, x1 - x0 - d.textlength(clock, font=small) - 6, False),
           anchor="ls")
    return img.tobytes()


SYSTEM = (90, 170, 220)


def _gb(n) -> str:
    return f"{n / 2**30:.0f}" if n >= 100 * 2**30 else f"{n / 2**30:.1f}"


def _uptime(seconds: float) -> str:
    m = int(seconds // 60)
    d, h, m = m // 1440, m // 60 % 24, m % 60
    return f"up {d}d {h}h" if d else f"up {h}h {m}m"


def system_card(stats: dict, now: float | None = None) -> bytes:
    """CPU, memory and disk. `stats` comes from sysinfo.sample()."""
    img = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(img)
    x0, x1 = 7, SCREEN_W - 7
    d.rectangle([0, 0, SCREEN_W, 22], fill=SYSTEM)
    d.text((SCREEN_W // 2, 11), "system", fill=(255, 255, 255),
           font=_font(17, True), anchor="mm")
    cpu, mem, disk = stats.get("cpu"), stats.get("mem") or {}, stats.get("disk") or {}
    cores, ghz = stats.get("cores"), stats.get("ghz")
    cpu_detail = " · ".join(x for x in (f"{cores} cores" if cores else "",
                                        f"{ghz:.1f} GHz" if ghz else "") if x)
    gauges = [
        ("cpu", cpu, cpu_detail),
        ("memory", mem.get("percent"),
         f"{_gb(mem['used'])} of {_gb(mem['total'])} GB" if mem.get("total") else ""),
        ("disk", disk.get("percent"),
         f"{_gb(disk['used'])} of {_gb(disk['total'])} GB" if disk.get("total") else ""),
    ]
    y = 22
    for label, pct, detail in gauges:
        _gauge(d, y, label, pct, detail, x0, x1)
        y += 56
    d.line([x0, y + 2, x1, y + 2], fill=(40, 40, 46))
    host = stats.get("host") or ""
    d.text((x0, y + 26), host[:14], fill=FG, font=_fitted(d, host[:14], 16, x1 - x0, True), anchor="ls")
    small = _font(15)
    clock = time.strftime("%H:%M", time.localtime(now or time.time()))
    d.text((x1, SCREEN_H - 3), clock, fill=DIM, font=small, anchor="rs")
    if stats.get("uptime"):
        d.text((x0, SCREEN_H - 3), _uptime(stats["uptime"]), fill=DIM, font=small, anchor="ls")
    return img.tobytes()


NETWORK = (140, 110, 220)
KIND_LABEL = {"ethernet": "Ethernet", "wifi": "Wi-Fi", "vpn": "VPN"}
KIND_COLOR = {"ethernet": GREEN, "wifi": GREEN, "vpn": (90, 170, 220)}


def _bytes(n: float) -> str:
    for unit, scale in (("TB", 2**40), ("GB", 2**30), ("MB", 2**20), ("kB", 2**10)):
        if n >= scale:
            v = n / scale
            return f"{v:.1f} {unit}" if v < 100 else f"{v:.0f} {unit}"
    return f"{n:.0f} B"


def _clip(d, text: str, font, width: float) -> str:
    if d.textlength(text, font=font) <= width:
        return text
    while text and d.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…" if text else ""


def network_card(net: dict, now: float | None = None) -> bytes:
    """Connections (Wi-Fi / Ethernet / VPN), IP, data used since boot, time."""
    img = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(img)
    x0, x1 = 7, SCREEN_W - 7
    d.rectangle([0, 0, SCREEN_W, 22], fill=NETWORK)
    d.text((SCREEN_W // 2, 11), "network", fill=(255, 255, 255),
           font=_font(17, True), anchor="mm")

    links = (net.get("links") or [])[:3]
    rows = links or [{"kind": None}]
    step = 24 if len(rows) < 3 else 22
    y = 25
    for l in rows:
        f = _font(19 if len(rows) < 3 else 18, True)
        if l["kind"] is None:
            dot, label = RED, "offline"
        else:
            dot, label = KIND_COLOR[l["kind"]], KIND_LABEL[l["kind"]]
        d.ellipse([x0, y + 8, x0 + 10, y + 18], fill=dot)
        d.text((x0 + 16, y + 19), label, fill=FG, font=f, anchor="ls")
        if l.get("ssid"):
            left = x0 + 16 + d.textlength(label, font=f) + 6
            sf = _font(14)
            if d.textlength(l["ssid"], font=sf) <= x1 - left:
                d.text((x1, y + 19), l["ssid"], fill=DIM, font=sf, anchor="rs")
            elif len(rows) < 3:      # room for the name on its own line
                y += 18
                nf = _font(15)
                d.text((x0 + 16, y + 17), _clip(d, l["ssid"], nf, x1 - x0 - 16), fill=DIM,
                       font=nf, anchor="ls")
            else:
                d.text((x1, y + 19), _clip(d, l["ssid"], sf, x1 - left), fill=DIM, font=sf, anchor="rs")
        y += step

    y += 4
    d.line([x0, y, x1, y], fill=(40, 40, 46))
    ip = net.get("ip") or "no address"
    d.text((x0, y + 26), ip, fill=FG, font=_fitted(d, ip, 22, x1 - x0, True), anchor="ls")
    y += 34

    d.text((x0, y + 14), "since boot", fill=DIM, font=_font(14), anchor="ls")
    y += 16
    for arrow, key, col in (("↓", "recv_total", GREEN), ("↑", "sent_total", (90, 170, 220))):
        text = _bytes(float(net.get(key) or 0))
        d.text((x0, y + 21), arrow, fill=col, font=_font(20, True), anchor="ls")
        d.text((x1, y + 21), text, fill=FG, font=_fitted(d, text, 21, x1 - x0 - 22, True), anchor="rs")
        y += 24
    clock = time.strftime("%H:%M", time.localtime(now or time.time()))
    d.text((SCREEN_W // 2, SCREEN_H - 3), clock, fill=FG, font=_font(28, True), anchor="ms")
    return img.tobytes()

def blank() -> bytes:
    return Image.new("RGB", SIZE, (0, 0, 0)).tobytes()


def preview(rgb: bytes, path: str, scale: int = 2) -> None:
    Image.frombytes("RGB", SIZE, rgb).resize(
        (SCREEN_W * scale, SCREEN_H * scale), Image.NEAREST).save(path)

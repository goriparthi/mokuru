"""Pictures for the 135x240 LCD: file/GIF loading, a usage card, a Claude mark."""
from __future__ import annotations

import math
import time

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence

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
    return ImageOps.fit(img.convert("RGB"), SIZE).tobytes()


def load_image(path: str) -> bytes:
    with Image.open(path) as img:
        return fit(img)


def load_gif(path: str, max_frames: int = SCREEN_SLOTS) -> tuple[list[bytes], int]:
    """Frames (evenly sampled down to max_frames) and a delay in ms."""
    with Image.open(path) as img:
        frames = [f.copy() for f in ImageSequence.Iterator(img)]
        durations = [f.info.get("duration", img.info.get("duration", 100)) or 100
                     for f in frames]
    total = sum(durations)
    if len(frames) > max_frames:
        step = len(frames) / max_frames
        frames = [frames[int(i * step)] for i in range(max_frames)]
    delay_ms = max(20, int(total / len(frames)))
    return [fit(f) for f in frames], delay_ms


def spark_frames(n: int = SCREEN_SLOTS) -> list[bytes]:
    """A Claude-style spark that turns a little each frame."""
    out = []
    cx, cy = SCREEN_W // 2, 100
    for k in range(n):
        img = Image.new("RGB", SIZE, BG)
        d = ImageDraw.Draw(img)
        rot = k * (math.pi / 6) / n * 2
        for i in range(12):
            a = rot + i * math.pi / 6
            r1, r2 = 14, 48 if i % 2 == 0 else 36
            d.line([(cx + r1 * math.cos(a), cy + r1 * math.sin(a)),
                    (cx + r2 * math.cos(a), cy + r2 * math.sin(a))],
                   fill=CLAUDE, width=7)
        d.text((SCREEN_W // 2, 190), "claude", fill=FG, font=_font(22, True), anchor="mm")
        d.text((SCREEN_W // 2, 214), "is working", fill=DIM, font=_font(14), anchor="mm")
        out.append(img.tobytes())
    return out


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


def preview(rgb: bytes, path: str, scale: int = 2) -> None:
    Image.frombytes("RGB", SIZE, rgb).resize(
        (SCREEN_W * scale, SCREEN_H * scale), Image.NEAREST).save(path)

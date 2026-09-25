"""Per-key lighting for the AK8753: matrix slot map and pattern builders.

The slot map was read from the keyboard's own keymap (GET 0x8A, base
layer). Colours upload in slot order, 126 slots x RGB.
"""
from __future__ import annotations

from .device import PER_KEY_SLOTS

SLOTS = {
    0: "Escape", 1: "Backquote", 2: "Tab", 3: "CapsLock", 4: "ShiftLeft", 5: "ControlLeft",
    6: "F1", 7: "Digit1", 8: "KeyQ", 9: "KeyA", 11: "MetaLeft", 12: "F2",
    13: "Digit2", 14: "KeyW", 15: "KeyS", 16: "KeyZ", 17: "AltLeft", 18: "F3",
    19: "Digit3", 20: "KeyE", 21: "KeyD", 22: "KeyX", 24: "F4", 25: "Digit4",
    26: "KeyR", 27: "KeyF", 28: "KeyC", 30: "F5", 31: "Digit5", 32: "KeyT",
    33: "KeyG", 34: "KeyV", 36: "F6", 37: "Digit6", 38: "KeyY", 39: "KeyH",
    40: "KeyB", 41: "Space", 42: "F7", 43: "Digit7", 44: "KeyU", 45: "KeyJ",
    46: "KeyN", 48: "F8", 49: "Digit8", 50: "KeyI", 51: "KeyK", 52: "KeyM",
    54: "F9", 55: "Digit9", 56: "KeyO", 57: "KeyL", 58: "Comma", 60: "F10",
    61: "Digit0", 62: "KeyP", 63: "Semicolon", 64: "Period", 65: "AltRight", 66: "F11",
    67: "Minus", 68: "BracketLeft", 69: "Quote", 70: "Slash", 71: "Fn", 72: "F12",
    73: "Equal", 74: "BracketRight", 76: "ShiftRight", 77: "ArrowLeft", 78: "Delete", 79: "Backspace",
    80: "Backslash", 81: "Enter", 82: "ArrowUp", 83: "ArrowDown", 84: "AudioVolumeMute", 87: "PageUp",
    88: "PageDown", 89: "ArrowRight", 90: "AudioVolumeUp", 91: "AudioVolumeDown", 104: "AudioVolumeMute",
}

KEY_SLOT = {name: slot for slot, name in SLOTS.items() if name != "AudioVolumeMute"}
F_ROW = [KEY_SLOT[f"F{i}"] for i in range(1, 13)]
NUMBER_ROW = [KEY_SLOT[k] for k in
              ["Digit1", "Digit2", "Digit3", "Digit4", "Digit5", "Digit6",
               "Digit7", "Digit8", "Digit9", "Digit0", "Minus", "Equal"]]


def solid(rgb) -> bytearray:
    """Every real key one colour; unused slots off."""
    out = bytearray(PER_KEY_SLOTS * 3)
    for slot in SLOTS:
        if slot < PER_KEY_SLOTS:
            out[slot * 3:slot * 3 + 3] = bytes(rgb)
    return out


def set_key(colors: bytearray, name: str, rgb) -> None:
    slot = KEY_SLOT[name]
    colors[slot * 3:slot * 3 + 3] = bytes(rgb)


def bar(colors: bytearray, slots: list[int], pct: float,
        off=(10, 10, 10)) -> None:
    """Fill `slots` left to right like a gauge: green, then yellow, then red."""
    lit = round(len(slots) * max(0.0, min(pct, 100.0)) / 100)
    for i, slot in enumerate(slots):
        if i < lit:
            t = i / max(1, len(slots) - 1)
            rgb = (int(40 + 215 * t), int(210 * (1 - t) + 30), 20)
        else:
            rgb = off
        colors[slot * 3:slot * 3 + 3] = bytes(rgb)


def context_pattern(pct: float, base=(217, 119, 87), dim: float = 0.35) -> bytes:
    """Base colour (dimmed) on every key, context usage on the F-row."""
    colors = solid(tuple(int(c * dim) for c in base))
    bar(colors, F_ROW, pct)
    set_key(colors, "Escape", base)
    return bytes(colors)


def bar_level(pct: float, keys: int = 12) -> int:
    """The number of lit bar keys: patterns only need re-uploading when this changes."""
    return round(keys * max(0.0, min(pct, 100.0)) / 100)

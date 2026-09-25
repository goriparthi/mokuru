"""Ctrl + dial = app switcher (Windows).

The dial sends Volume Up/Down/Mute like any media keys. A low-level keyboard
hook watches for them while Ctrl is held and turns them into a real Alt+Tab
session: the first click presses Alt+Tab, further clicks step through the
windows, and releasing Ctrl picks one. Ctrl + press opens Task View.
Without Ctrl the dial is untouched (volume).

The keyboard's firmware ignores its Fn layer for the dial, so this can't be
done on the keyboard itself.
"""
from __future__ import annotations

import sys
import threading

VK_TAB, VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN = 0x09, 0x10, 0x11, 0x12, 0x5B
VK_LCONTROL, VK_RCONTROL = 0xA2, 0xA3
VK_VOLUME_MUTE, VK_VOLUME_DOWN, VK_VOLUME_UP = 0xAD, 0xAE, 0xAF
DIAL_KEYS = {VK_VOLUME_UP, VK_VOLUME_DOWN, VK_VOLUME_MUTE}
CTRL_KEYS = {VK_CONTROL, VK_LCONTROL, VK_RCONTROL}


class Switcher:
    """Platform-neutral state machine; `send(vk, down)` injects a key."""

    def __init__(self, send):
        self.send = send
        self.ctrl = False
        self.switching = False

    def key(self, vk: int, down: bool) -> bool:
        """Handle one physical key event. True = swallow it."""
        if vk in CTRL_KEYS:
            if down:
                self.ctrl = True
                return False
            self.ctrl = False
            if self.switching:
                self.switching = False
                self.send(VK_MENU, False)      # releasing Ctrl picks the window
                return True
            return False
        if vk not in DIAL_KEYS or not self.ctrl:
            return False
        if not down:
            return True                        # swallow the dial's key-up too
        if vk == VK_VOLUME_MUTE:
            if not self.switching:
                self.send(VK_CONTROL, False)
                self._tap(VK_TAB, VK_LWIN)
                self.send(VK_CONTROL, True)
            return True
        if not self.switching:
            # Hand Ctrl over to Alt so Windows sees Alt+Tab, not Ctrl+Alt+Tab.
            self.send(VK_CONTROL, False)
            self.send(VK_MENU, True)
            self.switching = True
        if vk == VK_VOLUME_UP:
            self._tap(VK_TAB)
        else:
            self._tap(VK_TAB, VK_SHIFT)
        return True

    def _tap(self, vk: int, mod: int | None = None) -> None:
        if mod:
            self.send(mod, True)
        self.send(vk, True)
        self.send(vk, False)
        if mod:
            self.send(mod, False)


def start() -> threading.Thread | None:
    """Install the hook on its own thread. No-op off Windows."""
    if sys.platform != "win32":
        return None
    t = threading.Thread(target=_run_windows, name="mokuru-dial", daemon=True)
    t.start()
    return t


def _run_windows() -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    WH_KEYBOARD_LL, WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 13, 0x100, 0x101, 0x104, 0x105
    # Windows reports the dial's volume keys as injected (they come from the
    # consumer-control driver), so "injected" can't mean "ours". Our own
    # key presses carry this tag in dwExtraInfo instead.
    OUR_TAG = 0x6D6B7275  # "mkru"
    INPUT_KEYBOARD, KEYEVENTF_KEYUP, KEYEVENTF_EXTENDEDKEY = 1, 0x2, 0x1
    ULONG_PTR = ctypes.c_size_t
    LRESULT = ctypes.c_ssize_t
    EXTENDED = {VK_LWIN, VK_RCONTROL}

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = LRESULT
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    def send(vk: int, down: bool) -> None:
        flags = (0 if down else KEYEVENTF_KEYUP) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0)
        inp = INPUT(type=INPUT_KEYBOARD,
                    u=_U(ki=KEYBDINPUT(wVk=vk, dwFlags=flags, dwExtraInfo=OUR_TAG)))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    switcher = Switcher(send)
    hook = None

    @HOOKPROC
    def proc(n_code, w_param, l_param):
        if n_code == 0:
            kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if kb.dwExtraInfo != OUR_TAG:
                down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
                if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
                    try:
                        if switcher.key(kb.vkCode, down):
                            return 1
                    except Exception:
                        pass
        return user32.CallNextHookEx(hook, n_code, w_param, l_param)

    hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, kernel32.GetModuleHandleW(None), 0)
    if not hook:
        return
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

"""Background service: owns the keyboard, turns Claude Code events into lights.

One worker thread talks to the device; everything else (HTTP requests from
hooks and the CLI, the tray) only changes state or queues commands. Fast
changes (whole-board lighting) go out immediately. Flash writes (per-key
patterns, LCD frames) are rate limited and never run back to back.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, keys, screen
from .device import (DEVICE_ID, FLAG_FIXED, MODE_PER_KEY, MODES, SCREEN_SLOTS,
                     DeviceNotFound, Keyboard, Lighting)

PRIORITY = {"attention": 3, "working": 2, "done": 1, "idle": 0}
EVENT_STATE = {"prompt": "working", "permission": "attention", "stop": "done"}
SESSION_TTL = 6 * 3600


class Sessions:
    """Per-session Claude state; the board shows the most urgent one."""

    def __init__(self, done_hold: float):
        self.done_hold = done_hold
        self.by_id: dict[str, dict] = {}
        self.lock = threading.Lock()

    def event(self, event: str, sid: str, now: float | None = None) -> None:
        now = now or time.time()
        with self.lock:
            if event == "end":
                self.by_id.pop(sid, None)
                return
            cur = self.by_id.get(sid, {}).get("state", "idle")
            if event == "tool":
                # A tool finishing only means something right after a
                # permission prompt; a late async hook must not undo "done".
                if cur != "attention":
                    return
                new = "working"
            elif event in EVENT_STATE:
                new = EVENT_STATE[event]
            else:
                return
            self.by_id[sid] = {"state": new, "t": now}

    def current(self, now: float | None = None) -> str:
        now = now or time.time()
        best = "idle"
        with self.lock:
            for sid, s in list(self.by_id.items()):
                if now - s["t"] > SESSION_TTL:
                    del self.by_id[sid]
                    continue
                state = s["state"]
                if state == "done" and now - s["t"] > self.done_hold:
                    state = "idle"
                if PRIORITY[state] > PRIORITY[best]:
                    best = state
        return best

    def snapshot(self) -> dict:
        with self.lock:
            return {k: dict(v) for k, v in self.by_id.items()}


class Daemon:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or config.load()
        self.sessions = Sessions(self.cfg["done_hold"])
        self.cmds: queue.Queue = queue.Queue()
        self.kb: Keyboard | None = None
        self.stop_evt = threading.Event()
        self.state = "idle"
        self.shown_state = None       # state whose lighting is on the board
        self.applied: Lighting | None = None
        self.baseline: Lighting | None = config.load_baseline()
        self.per_key_level: int | None = None
        self.status: dict = {}
        self._status_mtime = 0.0
        self.lcd_last_upload = 0.0
        self.lcd_last_key = None
        self.lcd_busy = False
        self.last_error = ""
        self._last_connect_try = 0.0
        self._clock_day = None

    # --- public, thread safe -----------------------------------------------

    def event(self, event: str, sid: str = "default") -> None:
        self.sessions.event(event, sid or "default")

    def command(self, cmd: str, args: dict, timeout: float = 600) -> dict:
        done = threading.Event()
        box: dict = {}
        self.cmds.put((cmd, args, box, done))
        if not done.wait(timeout):
            return {"ok": False, "error": "timed out"}
        return box

    def info(self) -> dict:
        return {
            "connected": self.kb is not None,
            "state": self.state,
            "paused": config.paused(),
            "sessions": self.sessions.snapshot(),
            "lighting": self.applied.as_dict() if self.applied else None,
            "baseline": self.baseline.as_dict() if self.baseline else None,
            "per_key_level": self.per_key_level,
            "context_pct": self._context_pct(),
            "lcd": {"enabled": self.cfg["lcd"]["enabled"], "busy": self.lcd_busy,
                    "last_upload": self.lcd_last_upload},
            "error": self.last_error,
        }

    # --- worker ------------------------------------------------------------

    def run(self) -> None:
        while not self.stop_evt.is_set():
            try:
                if self.kb is None:
                    self._connect()
                self._drain_commands()
                self._read_status()
                self.state = self.sessions.current()
                if self.kb is not None:
                    self._apply_state(allow_flash=True)
                    self._maybe_clock()
                    self._maybe_lcd()
            except (OSError, ValueError) as e:
                self._disconnect(f"device error: {e}")
            except Exception as e:  # keep the service alive
                self.last_error = f"{type(e).__name__}: {e}"
            self.stop_evt.wait(0.1)
        if self.kb is not None:
            try:
                self._show_idle()
            except Exception:
                pass
            self.kb.close()

    def _connect(self) -> None:
        if time.monotonic() - self._last_connect_try < 3:
            return
        self._last_connect_try = time.monotonic()
        try:
            kb = Keyboard()
        except (DeviceNotFound, OSError) as e:
            self.last_error = str(e)
            return
        dev_id, _ = kb.identify()
        if dev_id != DEVICE_ID:
            kb.close()
            self.last_error = f"unexpected device id {dev_id}"
            return
        self.kb = kb
        self.last_error = ""
        self.applied = None
        self.shown_state = None
        self.per_key_level = None  # can't read it back; re-upload when needed
        self._clock_day = None
        cur = kb.get_lighting()
        ours = [self._state_lighting(s) for s in ("working", "attention", "done")]
        if cur.mode == MODE_PER_KEY or cur in ours:
            # Left over from a previous run (or a crash): put the user's back.
            self._show_idle()
        elif self.baseline is None:
            self._capture_baseline()

    def _disconnect(self, why: str) -> None:
        self.last_error = why
        if self.kb is not None:
            self.kb.close()
        self.kb = None

    # --- lighting ----------------------------------------------------------

    def _capture_baseline(self) -> None:
        """Remember the user's own lighting, unless it is one of ours."""
        cur = self.kb.get_lighting()
        if self.applied is not None and cur == self.applied:
            return
        if cur.mode == MODE_PER_KEY:
            return
        self.baseline = cur
        config.save_baseline(cur)

    def _show_idle(self) -> None:
        if self.baseline is not None:
            self.kb.set_lighting(self.baseline)
            self.applied = self.baseline

    def _state_lighting(self, state: str) -> Lighting:
        c = self.cfg["colors"]
        if state == "attention":
            return Lighting(MODES["breathing"], 0, 4, 0, FLAG_FIXED, tuple(c["attention"]))
        if state == "done":
            return Lighting(MODES["static"], 2, 4, 0, FLAG_FIXED, tuple(c["done"]))
        return Lighting(MODES["breathing"], 1, 4, 0, FLAG_FIXED, tuple(c["working"]))

    def _apply_state(self, allow_flash: bool) -> None:
        state = "idle" if (config.paused() or not self.cfg["claude_lighting"]) else self.state
        if state == "idle":
            if self.shown_state not in (None, "idle"):
                self._show_idle()
            self.shown_state = "idle"
            return
        if self.shown_state in (None, "idle"):
            self._capture_baseline()
        want = self._state_lighting(state)
        if state == "working" and self.cfg["per_key"]:
            level = keys.bar_level(self._context_pct())
            if self.per_key_level != level and allow_flash and self.kb.flash_ready():
                pattern = keys.context_pattern(self._context_pct(),
                                               tuple(self.cfg["colors"]["working"]))
                self.kb.set_per_key(pattern, 0)
                self.per_key_level = level
            if self.per_key_level == level:
                want = Lighting(MODE_PER_KEY, 2, 4, 0, FLAG_FIXED, (0, 200, 200))
        if want != self.applied:
            self.kb.set_lighting(want)
            self.applied = want
        self.shown_state = state

    def _maybe_clock(self) -> None:
        day = time.strftime("%Y-%m-%d")
        if self._clock_day != day:
            self.kb.set_clock()
            self._clock_day = day

    # --- status line / LCD ---------------------------------------------------

    def _read_status(self) -> None:
        path = config.STATUS_FILE
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime == self._status_mtime:
            return
        try:
            self.status = json.loads(path.read_text(encoding="utf-8"))
            self._status_mtime = mtime
        except (OSError, ValueError):
            pass

    def _context_pct(self) -> float:
        try:
            return float((self.status.get("context_window") or {}).get("used_percentage") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _lcd_key(self):
        s = self.status
        cost = float((s.get("cost") or {}).get("total_cost_usd") or 0)
        return ((s.get("model") or {}).get("display_name"),
                int(self._context_pct() // 5), round(cost / 0.05))

    def _maybe_lcd(self) -> None:
        lcd = self.cfg["lcd"]
        if not lcd["enabled"] or not self.status or self.state == "attention":
            return
        key = self._lcd_key()
        if key == self.lcd_last_key:
            return
        if time.time() - self.lcd_last_upload < lcd["min_interval"]:
            return
        if not self.kb.flash_ready():
            return
        card = screen.usage_card(self.status, self.state)
        self._upload_frames([card], lcd["slot"], delay=0)
        self.lcd_last_key = key
        self.lcd_last_upload = time.time()

    def _between_pages(self) -> None:
        """Mid-upload: keep the lights honest without touching flash."""
        self.state = self.sessions.current()
        self._apply_state(allow_flash=False)

    def _upload_frames(self, frames: list[bytes], first_slot: int, delay: int) -> None:
        self.lcd_busy = True
        try:
            n = len(frames)
            for i, rgb in enumerate(frames):
                slot = first_slot + i if n > 1 else first_slot
                self.kb.upload_frame(rgb, slot, frames=n, delay=delay,
                                     between_pages=self._between_pages)
        finally:
            self.lcd_busy = False

    # --- commands ------------------------------------------------------------

    def _drain_commands(self) -> None:
        while True:
            try:
                cmd, args, box, done = self.cmds.get_nowait()
            except queue.Empty:
                return
            try:
                box.update(self._run_command(cmd, args))
                box.setdefault("ok", True)
            except Exception as e:
                box.update({"ok": False, "error": f"{type(e).__name__}: {e}"})
            finally:
                done.set()

    def _need_kb(self) -> Keyboard:
        if self.kb is None:
            raise RuntimeError(self.last_error or "keyboard not connected")
        return self.kb

    def _run_command(self, cmd: str, a: dict) -> dict:
        if cmd == "info":
            kb = self._need_kb()
            dev_id, fw = kb.identify()
            return {"device": dev_id, "firmware": f"{fw:04x}",
                    "display": f"{kb.display_version():04x}",
                    "lighting": kb.get_lighting().as_dict(), **self.info()}
        if cmd == "light":
            light = Lighting.from_dict(a["lighting"])
            self.baseline = light
            config.save_baseline(light)
            if self.shown_state in (None, "idle"):
                self._need_kb().set_lighting(light)
                self.applied = light
            return {"baseline": light.as_dict()}
        if cmd == "clock":
            self._need_kb().set_clock()
            return {}
        if cmd == "image":
            self._need_kb()
            rgb = screen.test_pattern() if a["path"] == "test" else screen.load_image(a["path"])
            self._set_lcd_auto(False)
            self._upload_frames([rgb], int(a.get("slot", 0)), 0)
            return {}
        if cmd == "gif":
            self._need_kb()
            if a["path"] == "claude":
                frames, delay_ms = screen.spark_frames(int(a.get("frames", SCREEN_SLOTS))), 120
            else:
                frames, delay_ms = screen.load_gif(a["path"], int(a.get("frames", SCREEN_SLOTS)))
            delay = max(1, min(255, int(a.get("delay") or delay_ms // 10)))
            self._set_lcd_auto(False)
            self._upload_frames(frames, 0, delay)
            return {"frames": len(frames), "delay": delay}
        if cmd == "lcd":
            self._set_lcd_auto(bool(a["enabled"]))
            self.lcd_last_key = None
            self.lcd_last_upload = 0
            return {"lcd": self.cfg["lcd"]}
        if cmd in ("pause", "resume"):
            config.set_paused(cmd == "pause")
            return {"paused": config.paused()}
        raise ValueError(f"unknown command {cmd!r}")

    def _set_lcd_auto(self, enabled: bool) -> None:
        self.cfg["lcd"]["enabled"] = enabled
        config.save(self.cfg)


# --- HTTP front door (localhost only) ---------------------------------------

def make_handler(daemon: Daemon):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _json(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n))
            except ValueError:
                return {}

        def do_GET(self):
            if self.path == "/status":
                self._json(200, daemon.info())
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            # Browsers can't send JSON here without a CORS preflight we never
            # answer, so a web page can't drive the keyboard.
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._json(415, {"error": "application/json only"})
                return
            body = self._body()
            if self.path == "/event":
                daemon.event(str(body.get("event", "")), str(body.get("session_id") or "default"))
                self._json(200, {"ok": True})
            elif self.path == "/cmd":
                self._json(200, daemon.command(str(body.get("cmd")), body.get("args") or {}))
            elif self.path == "/shutdown":
                self._json(200, {"ok": True})
                threading.Thread(target=daemon.stop_evt.set, daemon=True).start()
            else:
                self._json(404, {"error": "not found"})

    return Handler


_lock_handle = None


def _single_instance() -> bool:
    """Hold an exclusive lock on ~/.mokuru/daemon.lock for the process lifetime."""
    global _lock_handle
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    f = open(config.STATE_DIR / "daemon.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _lock_handle = f
    return True


def serve(daemon: Daemon | None = None, block: bool = True) -> Daemon:
    if not _single_instance():
        raise SystemExit("mokuru: another daemon is already running")
    daemon = daemon or Daemon()
    server = None
    base = int(daemon.cfg["port"])
    for port in range(base, base + 20):
        # Windows can refuse a port for reasons that aren't "in use"
        # (reserved ranges, endpoint security), so walk to a free one.
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(daemon))
            break
        except OSError:
            continue
    if server is None:
        raise OSError(f"no free port in {base}..{base + 19}")
    server.daemon_threads = True
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    config.PID_FILE.write_text(str(os.getpid()))
    config.PORT_FILE.write_text(str(server.server_address[1]))
    threading.Thread(target=server.serve_forever, name="mokuru-http", daemon=True).start()
    if daemon.cfg.get("dial_switcher"):
        from . import dialswitch
        dialswitch.start()
    worker = threading.Thread(target=daemon.run, name="mokuru-device", daemon=True)
    worker.start()

    def _stop_server():
        daemon.stop_evt.wait()
        server.shutdown()
        for f in (config.PID_FILE, config.PORT_FILE):
            try:
                f.unlink()
            except OSError:
                pass

    threading.Thread(target=_stop_server, daemon=True).start()
    if block:
        try:
            while worker.is_alive():
                worker.join(0.5)
        except KeyboardInterrupt:
            daemon.stop_evt.set()
            worker.join(5)
    return daemon

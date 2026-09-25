"""HID protocol for the MOKURU AK8753 (ROYUAN gen2 command set, yc3123 chip).

Protocol reference: https://github.com/dniminenn/sharkfin/blob/master/docs/PROTOCOL.md

Everything is a 64-byte HID feature report, report ID 0, on the vendor
collection (usage page 0xFFFF, usage 2). Screen frames need the USB cable.

Deliberately absent: 0xAC (erases every stored picture), 0x7F and 0x30
(firmware boot entry). Nothing in this package can send them.
"""
from __future__ import annotations

import datetime
import threading
import time
from dataclasses import dataclass

import hid

VID = 0x3151
PIDS = {0x5002}
USAGE_PAGE, USAGE = 0xFFFF, 0x02
REPORT_LEN = 64
DEVICE_ID = 3177  # sharkfin/vendor record "yc3123_dj_ka8753_a_3m"

WRITE_GAP = 0.012     # faster stalls the control endpoint
PAGE_GAP = 0.005      # between screen pages
FLASH_PAGE_GAP = 0.1  # between per-key pages
FLASH_SETTLE = 2.0    # after anything that commits to flash
FLASH_COOLDOWN = 10.0  # minimum spacing between flash uploads

SCREEN_W, SCREEN_H, SCREEN_SLOTS = 135, 240, 5
PER_KEY_SLOTS = 126

# Lighting flags nibble for device 3177 (vendor table: rainbow 8, fixed 7).
FLAG_FIXED, FLAG_RAINBOW = 7, 8
MODE_PER_KEY = 13

MODES = {
    "static": 1, "breathing": 2, "spectrum": 3, "wave": 4, "ripple": 5,
    "stars": 6, "flow": 7, "shadow": 8, "layers": 9, "sine": 10,
    "spring": 11, "neon": 12, "per-key": 13, "radiant": 14, "loop": 15,
    "grid": 16, "snowfall": 17, "meteor": 18, "silent-snow": 19,
}

FORBIDDEN_OPCODES = {0xAC, 0x2C, 0x7F, 0x30, 0x31}


class DeviceNotFound(RuntimeError):
    pass


class RelayTimeout(OSError):
    """The 2.4 GHz receiver didn't hand a packet over (keyboard asleep or away)."""


# 2.4 GHz receiver opcodes (answered by the dongle itself, not relayed).
RX_STATUS, RX_SELECT, RX_RELEASE, RX_TARGET_KEYBOARD = 0xF7, 0xF6, 0xFC, 0x0A


def checksum(buf: bytearray, upto: int) -> None:
    """Store 0xFF - (sum of buf[:upto]) at buf[upto]."""
    buf[upto] = 0xFF - (sum(buf[:upto]) & 0xFF)


def packet(opcode: int, payload: bytes = b"", bit8: bool = False) -> bytearray:
    if opcode in FORBIDDEN_OPCODES:
        raise ValueError(f"opcode {opcode:#04x} is destructive and not allowed")
    buf = bytearray(REPORT_LEN)
    buf[0] = opcode
    buf[1:1 + len(payload)] = payload
    checksum(buf, 8 if bit8 else 7)
    return buf


@dataclass
class Lighting:
    mode: int
    speed: int = 2        # wire value: 0 fastest .. 4 slowest
    brightness: int = 4   # 0..4
    option: int = 0       # direction / variant, or per-key slot in mode 13
    flags: int = FLAG_FIXED
    rgb: tuple = (250, 250, 250)

    def packet(self) -> bytearray:
        r, g, b = self.rgb
        return packet(0x07, bytes([self.mode, self.speed, self.brightness,
                                   (self.option << 4) | self.flags, r, g, b]),
                      bit8=True)

    @classmethod
    def from_reply(cls, r: bytes) -> "Lighting":
        if r[0] != 0x87:
            raise RuntimeError(f"unexpected lighting reply {bytes(r[:9]).hex()}")
        return cls(r[1], r[2], r[3], r[4] >> 4, r[4] & 0x0F, (r[5], r[6], r[7]))

    def as_dict(self) -> dict:
        return {"mode": self.mode, "speed": self.speed,
                "brightness": self.brightness, "option": self.option,
                "flags": self.flags, "rgb": list(self.rgb)}

    @classmethod
    def from_dict(cls, d: dict) -> "Lighting":
        return cls(d["mode"], d["speed"], d["brightness"], d["option"],
                   d["flags"], tuple(d["rgb"]))


def clock_packet(when: datetime.datetime) -> bytearray:
    pkt = packet(0x28)
    pkt[8:15] = bytes([when.year >> 8, when.year & 0xFF, when.month,
                       when.day, when.hour, when.minute, when.second])
    return pkt


def rgb565_column_major(rgb: bytes, w: int, h: int) -> bytes:
    """Row-major RGB triples -> column-major RGB565, high byte first."""
    if len(rgb) != w * h * 3:
        raise ValueError(f"need {w}x{h} RGB ({w * h * 3} bytes), got {len(rgb)}")
    out = bytearray(w * h * 2)
    o = 0
    for x in range(w):
        i = x * 3
        for _ in range(h):
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            out[o] = v >> 8
            out[o + 1] = v & 0xFF
            o += 2
            i += w * 3
    return bytes(out)


def screen_packets(data: bytes, slot: int, frames: int = 1, delay: int = 0,
                   box: tuple | None = None) -> tuple[bytearray, list[bytearray]]:
    """Announce packet and page packets for one frame (yc3123 layout)."""
    left, top, right, bottom = box or (0, 0, SCREEN_W, SCREEN_H)
    n = len(data)
    ann = packet(0xA5, bytes([slot, frames, delay, n & 0xFF, (n >> 8) & 0xFF, 0]))
    ann[8:19] = bytes([left & 0xFF, top & 0xFF, right & 0xFF, bottom & 0xFF,
                       left >> 8, top >> 8, right >> 8, bottom >> 8,
                       (n >> 16) & 0xFF, (n >> 24) & 0xFF, 0])
    pages = []
    for page, off in enumerate(range(0, n, 56)):
        chunk = data[off:off + 56]
        pkt = packet(0x25, bytes([slot, frames, delay, page & 0xFF, page >> 8,
                                  len(chunk)]))
        pkt[8:8 + len(chunk)] = chunk
        pages.append(pkt)
    return ann, pages


def per_key_packets(colors: bytes, slot: int = 0) -> list[bytearray]:
    """126 keys x RGB in matrix-slot order, 7 pages (gen2 USERPIC)."""
    blob = bytes(colors[:PER_KEY_SLOTS * 3]).ljust(PER_KEY_SLOTS * 3, b"\0")
    pkts = []
    for page, off in enumerate(range(0, len(blob), 56)):
        chunk = blob[off:off + 56]
        pkt = bytearray(REPORT_LEN)
        pkt[0:6] = bytes([0x0C, slot, 0xFF, page, len(chunk),
                          1 if off + 56 >= len(blob) else 0])
        checksum(pkt, 7)
        pkt[8:8 + len(chunk)] = chunk
        pkts.append(pkt)
    return pkts


class Keyboard:
    """One open AK8753. Thread-safe: every wire exchange takes the lock."""

    def __init__(self, path: bytes | None = None, wireless: bool = False):
        if path is None:
            found = find_device()
            if found is None:
                raise DeviceNotFound("MOKURU AK8753 not found (USB cable or 2.4 GHz dongle)")
            path, wireless = found
        self.dev = hid.device()
        self.dev.open_path(path)
        self.path = path
        self.wireless = wireless
        self.lock = threading.RLock()
        self._last_write = 0.0
        self._last_flash = 0.0

    def close(self) -> None:
        try:
            self.dev.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- wire ------------------------------------------------------------

    def _raw_send(self, pkt: bytes) -> None:
        with self.lock:
            wait = WRITE_GAP - (time.monotonic() - self._last_write)
            if wait > 0:
                time.sleep(wait)
            self.dev.send_feature_report(bytes([0]) + bytes(pkt))
            self._last_write = time.monotonic()

    def _raw_read(self) -> bytes:
        with self.lock:
            reply = bytes(self.dev.get_feature_report(0, REPORT_LEN + 1))
        if len(reply) == REPORT_LEN + 1 and reply[0] == 0:
            reply = reply[1:]
        return reply

    def send(self, pkt: bytes) -> None:
        if self.wireless:
            self._relay(pkt, want_reply=False)
        else:
            self._raw_send(pkt)

    def roundtrip(self, pkt: bytes) -> bytes:
        if self.wireless:
            return self._relay(pkt, want_reply=True)
        with self.lock:
            self._raw_send(pkt)
            time.sleep(0.01)
            return self._raw_read()

    # --- 2.4 GHz relay -----------------------------------------------------

    def receiver_status(self) -> bytes:
        with self.lock:
            self._raw_send(packet(RX_STATUS))
            time.sleep(0.02)
            return self._raw_read()

    def _wait_receiver(self, ready) -> bytes:
        for _ in range(10):
            r = self.receiver_status()
            if ready(r):
                return r
            time.sleep(0.05)
        raise RelayTimeout("2.4 GHz receiver not ready (is the keyboard awake?)")

    def _relay(self, pkt: bytes, want_reply: bool) -> bytes:
        """Receiver handshake: ready -> select keyboard -> packet [-> reply]."""
        with self.lock:
            self._wait_receiver(lambda r: r[5] == 1)
            self._raw_send(packet(RX_SELECT, bytes([RX_TARGET_KEYBOARD])))
            self._raw_send(pkt)
            if not want_reply:
                time.sleep(0.07)
                return b""
            self._wait_receiver(lambda r: r[0] == 1)
            self._raw_send(packet(RX_RELEASE))
            time.sleep(0.01)
            return self._raw_read()

    def battery(self) -> int | None:
        """Keyboard battery percent, over 2.4 GHz only (the cable has no reading)."""
        if not self.wireless:
            return None
        r = self.receiver_status()
        return r[1] if r[3] == 0 else None

    def flash_ready(self) -> bool:
        return time.monotonic() - self._last_flash >= FLASH_COOLDOWN

    def _flash_wait(self) -> None:
        wait = FLASH_COOLDOWN - (time.monotonic() - self._last_flash)
        if wait > 0:
            time.sleep(wait)

    # --- reads -----------------------------------------------------------

    def identify(self) -> tuple[int, int]:
        r = self.roundtrip(packet(0x8F))
        return int.from_bytes(r[1:5], "little"), (r[8] << 8) | r[7]

    def display_version(self) -> int:
        r = self.roundtrip(packet(0xAD))
        return (r[2] << 8) | r[1]

    def get_lighting(self) -> Lighting:
        return Lighting.from_reply(self.roundtrip(packet(0x87)))

    def read_keymap(self) -> list[tuple]:
        """Base layer of the active profile: 128 slots of 4-byte key codes."""
        with self.lock:
            profile = self.roundtrip(packet(0x84))[1]
            raw = b""
            for page in range(8):
                raw += self.roundtrip(packet(0x8A, bytes([profile, 0xFF, page, 0])))
        return [tuple(raw[i * 4:i * 4 + 4]) for i in range(128)]

    def read_fn_layer(self, os_layer: int = 0) -> list[tuple]:
        """Fn layer of the active profile (os_layer 0 = Windows, 1 = macOS)."""
        with self.lock:
            profile = self.roundtrip(packet(0x84))[1]
            raw = b""
            for page in range(8):
                raw += self.roundtrip(packet(0x90, bytes([os_layer, profile, 0xFF, page])))
        return [tuple(raw[i * 4:i * 4 + 4]) for i in range(128)]

    # --- writes ----------------------------------------------------------

    def set_fn_key(self, slot: int, value: tuple, os_layer: int = 0) -> None:
        """One Fn-layer slot. `value` is 4 bytes, e.g. (0, mod, usage, mod2)."""
        with self.lock:
            profile = self.roundtrip(packet(0x84))[1]
            self._flash_wait()
            pkt = packet(0x10, bytes([os_layer, profile, slot]))
            pkt[8:12] = bytes(value)
            self.send(pkt)
            time.sleep(0.5)
            self._last_flash = time.monotonic() - FLASH_COOLDOWN + 1.0

    def set_lighting(self, light: Lighting) -> None:
        self.send(light.packet())

    def set_clock(self, when: datetime.datetime | None = None) -> None:
        self.send(clock_packet(when or datetime.datetime.now()))

    def set_per_key(self, colors: bytes, slot: int = 0) -> None:
        """Upload a per-key pattern (flash). Show it with mode 13, option=slot."""
        with self.lock:
            self._flash_wait()
            for pkt in per_key_packets(colors, slot):
                self.send(pkt)
                time.sleep(FLASH_PAGE_GAP)
            time.sleep(FLASH_SETTLE)
            self._last_flash = time.monotonic()

    def upload_frame(self, rgb: bytes, slot: int, frames: int = 1,
                     delay: int = 0, box: tuple | None = None,
                     between_pages=None) -> int:
        """Upload one RGB frame (row major, box-sized) to the display.

        `between_pages`, if given, is called every 64 pages with the lock
        released so urgent commands (lighting) can go out mid-upload.
        Returns the number of pages sent.
        """
        if self.wireless:
            raise RuntimeError("LCD pictures need the USB cable")
        left, top, right, bottom = box or (0, 0, SCREEN_W, SCREEN_H)
        data = rgb565_column_major(rgb, right - left, bottom - top)
        ann, pages = screen_packets(data, slot, frames, delay, box)
        self._flash_wait()
        with self.lock:
            for _ in range(10):
                try:
                    if self.roundtrip(ann)[1] == 1:
                        break
                except OSError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("the display did not accept the frame")
        for i, pkt in enumerate(pages):
            self.send(pkt)
            time.sleep(PAGE_GAP)
            if between_pages and i % 64 == 63:
                between_pages()
        time.sleep(FLASH_SETTLE)
        self._last_flash = time.monotonic()
        return len(pages)


def is_receiver_status(r: bytes) -> bool:
    """A receiver status has a device-kind byte a keyboard reply can't produce."""
    return len(r) >= 9 and r[0] != RX_STATUS and r[6] in (1, 2, 3)


def find_device() -> tuple[bytes, bool] | None:
    """(path, wireless). The cable wins; otherwise any 0x3151 receiver."""
    vendor = [d for d in hid.enumerate(VID)
              if d["usage_page"] == USAGE_PAGE and d["usage"] in (1, 2)]
    for d in vendor:
        if d["product_id"] in PIDS and d["usage"] == USAGE:
            return d["path"], False
    for d in vendor:
        if d["product_id"] in PIDS:
            continue
        dev = hid.device()
        try:
            dev.open_path(d["path"])
            pkt = packet(RX_STATUS)
            dev.send_feature_report(bytes([0]) + bytes(pkt))
            time.sleep(0.02)
            r = bytes(dev.get_feature_report(0, REPORT_LEN + 1))
            if len(r) == REPORT_LEN + 1 and r[0] == 0:
                r = r[1:]
            if is_receiver_status(r):
                return d["path"], True
        except OSError:
            pass
        finally:
            dev.close()
    return None


def present_paths() -> set:
    """Paths of the vendor collections currently plugged in (cheap to call)."""
    return {d["path"] for d in hid.enumerate(VID) if d["usage_page"] == USAGE_PAGE}


def cable_present() -> bool:
    return any(d["product_id"] in PIDS and d["usage_page"] == USAGE_PAGE
               for d in hid.enumerate(VID))


def find_path() -> bytes | None:
    found = find_device()
    return found[0] if found else None

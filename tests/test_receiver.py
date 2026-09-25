import pytest

from mokuru import device
from mokuru.device import Keyboard, RelayTimeout


class FakeReceiver:
    """Speaks the dongle handshake; relays keyboard packets to a fake keyboard."""

    def __init__(self, keyboard_awake=True):
        self.awake = keyboard_awake
        self.selected = False
        self.pending = None      # keyboard reply waiting for RELEASE
        self.out = None          # what the next GET returns
        self.relayed = []

    def status(self):
        r = bytearray(64)
        r[0] = 1 if self.pending is not None else 0
        r[1] = 87                # battery
        r[3] = 0 if self.awake else 1
        r[5] = 1 if self.awake else 0
        r[6] = 1                 # keyboard
        return bytes(r)

    def send_feature_report(self, data):
        pkt = bytes(data[1:])
        op = pkt[0]
        if op == device.RX_STATUS:
            self.out = self.status()
        elif op == device.RX_SELECT:
            self.selected = pkt[1] == device.RX_TARGET_KEYBOARD
        elif op == device.RX_RELEASE:
            self.out, self.pending = self.pending, None
        else:
            assert self.selected, "keyboard packet without SELECT"
            self.selected = False
            self.relayed.append(pkt)
            if op & 0x80:        # a GET: the keyboard answers with an echo
                self.pending = bytes([op]) + b"\x42" * 63

    def get_feature_report(self, report_id, n):
        return [0] + list(self.out)

    def close(self):
        pass


def open_fake(rx):
    kb = Keyboard.__new__(Keyboard)
    kb.dev, kb.wireless = rx, True
    import threading
    kb.lock = threading.RLock()
    kb._last_write = kb._last_flash = 0.0
    return kb


def test_get_goes_through_the_relay_handshake():
    rx = FakeReceiver()
    kb = open_fake(rx)
    r = kb.roundtrip(device.packet(0x87))
    assert r[0] == 0x87 and rx.relayed[0][0] == 0x87


def test_set_is_relayed_without_waiting_for_a_reply():
    rx = FakeReceiver()
    kb = open_fake(rx)
    kb.set_lighting(device.Lighting(1, 2, 4, 0, 7, (255, 0, 0)))
    assert rx.relayed[0][0] == 0x07


def test_battery_and_status_detection():
    rx = FakeReceiver()
    kb = open_fake(rx)
    assert kb.battery() == 87
    assert device.is_receiver_status(rx.status())
    assert not device.is_receiver_status(device.packet(0x8F))


def test_sleeping_keyboard_times_out():
    kb = open_fake(FakeReceiver(keyboard_awake=False))
    with pytest.raises(RelayTimeout):
        kb.roundtrip(device.packet(0x87))


def test_lcd_refuses_wireless():
    kb = open_fake(FakeReceiver())
    with pytest.raises(RuntimeError):
        kb.upload_frame(bytes(135 * 240 * 3), 0)

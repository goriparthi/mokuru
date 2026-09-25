import datetime

import pytest

from mokuru import device, keys
from mokuru.device import Lighting


def test_checksum_bit7():
    pkt = device.packet(0x8F)
    assert pkt[0] == 0x8F and pkt[7] == 0xFF - 0x8F
    assert len(pkt) == 64


def test_lighting_uses_bit8_checksum():
    pkt = Lighting(4, 2, 4, 0, 8, (250, 250, 250)).packet()
    assert list(pkt[:8]) == [0x07, 4, 2, 4, 0x08, 250, 250, 250]
    assert pkt[8] == 0xFF - (sum(pkt[:8]) & 0xFF)


def test_lighting_roundtrips_through_reply():
    light = Lighting(2, 1, 4, 0, 7, (217, 119, 87))
    reply = bytes([0x87]) + bytes(light.packet()[1:8])
    assert Lighting.from_reply(reply) == light
    assert Lighting.from_dict(light.as_dict()) == light


def test_destructive_opcodes_are_refused():
    for op in (0xAC, 0x2C, 0x7F, 0x30, 0x31):
        with pytest.raises(ValueError):
            device.packet(op)


def test_clock_fields_sit_past_the_checksum():
    pkt = device.clock_packet(datetime.datetime(2026, 9, 25, 11, 31, 41))
    assert pkt[0] == 0x28 and pkt[7] == 0xFF - 0x28
    assert list(pkt[8:15]) == [0x07, 0xEA, 9, 25, 11, 31, 41]


def reference_pixels(rgb, w, h):
    out = bytearray()
    for x in range(w):
        for y in range(h):
            i = (y * w + x) * 3
            v = ((rgb[i] >> 3) << 11) | ((rgb[i + 1] >> 2) << 5) | (rgb[i + 2] >> 3)
            out += bytes([v >> 8, v & 0xFF])
    return bytes(out)


def test_pixels_are_column_major_rgb565():
    w, h = 3, 2
    rgb = bytes(range(w * h * 3))
    assert device.rgb565_column_major(rgb, w, h) == reference_pixels(rgb, w, h)
    red = bytes([255, 0, 0]) * (w * h)
    assert device.rgb565_column_major(red, w, h)[:2] == b"\xf8\x00"


def test_screen_packets_match_the_confirmed_layout():
    data = bytes(135 * 240 * 2)
    ann, pages = device.screen_packets(data, slot=4)
    n = len(data)
    assert list(ann[:7]) == [0xA5, 4, 1, 0, n & 0xFF, n >> 8, 0]
    assert list(ann[8:19]) == [0, 0, 135, 240, 0, 0, 0, 0, 0, 0, 0]
    assert len(pages) == 1158
    assert list(pages[1][:7]) == [0x25, 4, 1, 0, 1, 0, 56]
    assert pages[-1][6] == n - 56 * 1157


def test_animation_frames_carry_count_and_delay():
    ann, pages = device.screen_packets(bytes(112), slot=2, frames=3, delay=50)
    assert list(ann[1:4]) == [2, 3, 50]
    assert list(pages[0][1:4]) == [2, 3, 50]


def test_per_key_pages():
    pkts = device.per_key_packets(bytes(range(256)) + bytes(122))
    assert len(pkts) == 7
    assert list(pkts[0][:6]) == [0x0C, 0, 0xFF, 0, 56, 0]
    assert list(pkts[6][:6]) == [0x0C, 0, 0xFF, 6, 42, 1]
    assert pkts[0][7] == 0xFF - (sum(pkts[0][:7]) & 0xFF)


def test_context_pattern_lights_the_f_row():
    empty = keys.context_pattern(0)
    full = keys.context_pattern(100)
    assert len(full) == 378
    f12 = keys.KEY_SLOT["F12"] * 3
    assert empty[f12:f12 + 3] == bytes((10, 10, 10))
    assert full[f12] > 200  # red end of the gauge
    esc = keys.KEY_SLOT["Escape"] * 3
    assert full[esc:esc + 3] == bytes((217, 119, 87))
    assert keys.bar_level(50) == 6

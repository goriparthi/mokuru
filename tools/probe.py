"""Standalone read-only probe for the MOKURU AK8753 (ROYUAN gen2 / yc3123).

Sends GET opcodes only: identify (0x8F), display version (0xAD),
lighting (0x87). Nothing here writes to the keyboard.
"""
import time

import hid

VID = 0x3151
USAGE_PAGE = 0xFFFF
REPORT_LEN = 64


def checksum_bit7(buf):
    buf[7] = 0xFF - (sum(buf[:7]) & 0xFF)
    return buf


def packet(opcode, payload=b""):
    buf = bytearray(REPORT_LEN)
    buf[0] = opcode
    buf[1:1 + len(payload)] = payload
    return checksum_bit7(buf)


def roundtrip(dev, pkt):
    dev.send_feature_report(bytes([0]) + bytes(pkt))
    time.sleep(0.02)
    reply = bytes(dev.get_feature_report(0, REPORT_LEN + 1))
    if len(reply) == REPORT_LEN + 1 and reply[0] == 0:
        reply = reply[1:]
    return reply


def hexs(b, n=16):
    return " ".join(f"{x:02x}" for x in b[:n])


def main():
    devices = [d for d in hid.enumerate(VID) if d["vendor_id"] == VID]
    if not devices:
        print("No 0x3151 devices found.")
        return
    print("HID collections:")
    for d in devices:
        print(f"  pid={d['product_id']:04x} if={d['interface_number']} "
              f"page={d['usage_page']:04x} usage={d['usage']:02x} "
              f"{d['product_string']!r}")

    targets = [d for d in devices if d["usage_page"] == USAGE_PAGE]
    for d in targets:
        print(f"\nProbing if={d['interface_number']} usage={d['usage']:02x}")
        dev = hid.device()
        try:
            dev.open_path(d["path"])
        except OSError as e:
            print("  open failed:", e)
            continue
        try:
            r = roundtrip(dev, packet(0x8F))
            print("  identify 0x8F:", hexs(r))
            if r and r[0] == 0x8F:
                dev_id = int.from_bytes(r[1:5], "little")
                fw = (r[8] << 8) | r[7]
                print(f"  -> device id {dev_id} (expect 3177), firmware {fw:04x}")
            r = roundtrip(dev, packet(0xAD))
            print("  display 0xAD:  ", hexs(r))
            if r and r[0] == 0xAD:
                print(f"  -> display fw {(r[2] << 8) | r[1]:04x}")
            r = roundtrip(dev, packet(0x87))
            print("  lighting 0x87: ", hexs(r))
            if r and r[0] == 0x87:
                print(f"  -> mode {r[1]} speed {r[2]} bright {r[3]} "
                      f"opt/flags {r[4]:02x} rgb {r[5]:02x}{r[6]:02x}{r[7]:02x}")
        except OSError as e:
            print("  error:", e)
        finally:
            dev.close()


if __name__ == "__main__":
    main()

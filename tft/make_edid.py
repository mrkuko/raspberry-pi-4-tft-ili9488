#!/usr/bin/env python3
"""Build a 128-byte EDID that advertises one mode: 480x320 @ 60 Hz.

The vc4 HDMI driver rejects modes with a pixel clock below ~25 MHz, and a plain 480x320 mode is only ~11 MHz.
So the mode keeps a 480x320 active area but uses large blanking (800 x 525 total) to reach 25.2 MHz:

  pixel clock 25.2 MHz = 800 x 525 x 60 Hz
  horizontal: 480 active + 48 front porch + 96 sync + 176 back porch = 800
  vertical:   320 active + 10 front porch +  2 sync + 193 back porch = 525

The kernel then creates /dev/fb0 at exactly 480x320 (fbcon: 60x20 characters with the 8x16 font).

Usage: make_edid.py [OUTPUT]   (default: 480x320.bin next to this script)
"""
import os
import sys

PCLK_KHZ = 25200
H_ACTIVE, H_FRONT, H_SYNC, H_BACK = 480, 48, 96, 176
V_ACTIVE, V_FRONT, V_SYNC, V_BACK = 320, 10, 2, 193
H_BLANK = H_FRONT + H_SYNC + H_BACK          # 320
V_BLANK = V_FRONT + V_SYNC + V_BACK          # 205
W_MM, H_MM = 74, 50                          # roughly a 3.5 inch panel


def dtd():
    d = bytearray(18)
    clk = PCLK_KHZ // 10                     # units of 10 kHz
    d[0], d[1] = clk & 0xFF, clk >> 8
    d[2], d[3] = H_ACTIVE & 0xFF, H_BLANK & 0xFF
    d[4] = ((H_ACTIVE >> 8) << 4) | (H_BLANK >> 8)
    d[5], d[6] = V_ACTIVE & 0xFF, V_BLANK & 0xFF
    d[7] = ((V_ACTIVE >> 8) << 4) | (V_BLANK >> 8)
    d[8], d[9] = H_FRONT & 0xFF, H_SYNC & 0xFF
    d[10] = ((V_FRONT & 0xF) << 4) | (V_SYNC & 0xF)
    d[11] = ((H_FRONT >> 8) << 6) | ((H_SYNC >> 8) << 4) | ((V_FRONT >> 4) << 2) | (V_SYNC >> 4)
    d[12], d[13] = W_MM & 0xFF, H_MM & 0xFF
    d[14] = ((W_MM >> 8) << 4) | (H_MM >> 8)
    d[15] = d[16] = 0                        # no borders
    d[17] = 0x18                             # digital separate sync, negative hsync and vsync
    return bytes(d)


def descriptor(tag, payload):
    body = bytes([0, 0, 0, tag, 0]) + payload
    return body.ljust(18, b"\x20")[:18]


def build():
    e = bytearray(128)
    e[0:8] = bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])
    mfg = (20 << 10) | (6 << 5) | 20         # "TFT"
    e[8], e[9] = mfg >> 8, mfg & 0xFF
    e[10], e[11] = 0x01, 0x00                # product code
    e[16], e[17] = 1, 36                     # week 1 of 2026
    e[18], e[19] = 1, 3                      # EDID 1.3
    e[20] = 0x80                             # digital input
    e[21], e[22] = 7, 5                      # size in cm
    e[23] = 0x78                             # gamma 2.2
    e[24] = 0x0A                             # RGB colour display, first DTD is the preferred mode
    e[25:35] = bytes([0xEE, 0x91, 0xA3, 0x54, 0x4C, 0x99, 0x26, 0x0F, 0x50, 0x54])   # sRGB chromaticity
    for i in range(38, 54, 2):               # unused standard timings
        e[i], e[i + 1] = 0x01, 0x01
    e[54:72] = dtd()
    # range limits: 55-65 Hz vertical, 30-33 kHz horizontal, max 30 MHz pixel clock, range limits only
    e[72:90] = descriptor(0xFD, bytes([55, 65, 30, 33, 3, 0x01, 0x0A]))
    e[90:108] = descriptor(0xFC, b"TFT480x320\n")
    e[108:126] = bytes([0, 0, 0, 0x10, 0]) + bytes(13)       # dummy descriptor
    e[126] = 0                               # no extension blocks
    e[127] = (-sum(e[:127])) & 0xFF          # checksum
    return bytes(e)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "480x320.bin")
    edid = build()
    assert len(edid) == 128 and sum(edid) % 256 == 0
    with open(out, "wb") as f:
        f.write(edid)
    refresh = PCLK_KHZ * 1000 / ((H_ACTIVE + H_BLANK) * (V_ACTIVE + V_BLANK))
    print(f"wrote {out}: {H_ACTIVE}x{V_ACTIVE} total {H_ACTIVE + H_BLANK}x{V_ACTIVE + V_BLANK}, "
          f"{PCLK_KHZ / 1000:.1f} MHz, {refresh:.2f} Hz")

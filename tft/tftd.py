#!/usr/bin/env python3
"""tftd: mirror a virtual X screen (Xvfb 480x320) onto an ILI9488 SPI TFT.

Xvfb is started with `-fbdir /dev/shm/tft`, which exposes the screen as an XWD file
(Xvfb_screen0) that we mmap. Each frame we find the changed rows and push only
those to the display over SPI (18-bit colour, 3 bytes per pixel).

Wiring (BCM): CS=GPIO8 (kernel), DC=GPIO24, RESET=GPIO25, MOSI=GPIO10, SCK=GPIO11, LED=3V3.
Usage: tftd.py [--fb PATH] [--speed HZ] [--madctl 0x28] [--fps N]
"""
import argparse
import struct
import time

import lgpio
import numpy as np
import spidev

DC, RST = 24, 25
W, H = 480, 320                       # landscape (MADCTL with MV bit set)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--fb", default="/dev/shm/tft/Xvfb_screen0")
    p.add_argument("--speed", type=int, default=32_000_000)
    # MV|BGR = 0x28. If the picture is mirrored or upside down try 0x68, 0xA8 or 0xE8.
    p.add_argument("--madctl", type=lambda s: int(s, 0), default=0x28)
    p.add_argument("--fps", type=int, default=30)
    return p.parse_args()


class Tft:
    def __init__(self, speed, madctl):
        self.h = lgpio.gpiochip_open(0)
        lgpio.gpio_claim_output(self.h, DC, 0)
        lgpio.gpio_claim_output(self.h, RST, 1)
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.mode = 0
        self.spi.max_speed_hz = speed
        self.init(madctl)

    def cmd(self, c, *params):
        lgpio.gpio_write(self.h, DC, 0)
        self.spi.writebytes([c])
        if params:
            lgpio.gpio_write(self.h, DC, 1)
            self.spi.writebytes(list(params))

    def init(self, madctl):
        h = self.h
        lgpio.gpio_write(h, RST, 1); time.sleep(0.01)
        lgpio.gpio_write(h, RST, 0); time.sleep(0.02)
        lgpio.gpio_write(h, RST, 1); time.sleep(0.15)
        c = self.cmd
        c(0x01); time.sleep(0.15)
        c(0x11); time.sleep(0.15)
        c(0xE0, 0x00, 0x03, 0x09, 0x08, 0x16, 0x0A, 0x3F, 0x78, 0x4C, 0x09, 0x0A, 0x08, 0x16, 0x1A, 0x0F)
        c(0xE1, 0x00, 0x16, 0x19, 0x03, 0x0F, 0x05, 0x32, 0x45, 0x46, 0x04, 0x0E, 0x0D, 0x35, 0x37, 0x0F)
        c(0xC0, 0x17, 0x15)
        c(0xC1, 0x41)
        c(0xC5, 0x00, 0x12, 0x80)
        c(0x36, madctl)
        c(0x3A, 0x66)
        c(0xB0, 0x00)
        c(0xB1, 0xA0)
        c(0xB4, 0x02)
        c(0xB6, 0x02, 0x02)
        c(0xE9, 0x00)
        c(0xF7, 0xA9, 0x51, 0x2C, 0x82)
        c(0x29); time.sleep(0.1)

    def blit(self, x0, x1, y0, y1, rgb):
        """Draw the rectangle [x0,x1) x [y0,y1); rgb is bytes of RGB triples, row by row."""
        self.cmd(0x2A, x0 >> 8, x0 & 0xFF, (x1 - 1) >> 8, (x1 - 1) & 0xFF)
        self.cmd(0x2B, y0 >> 8, y0 & 0xFF, (y1 - 1) >> 8, (y1 - 1) & 0xFF)
        self.cmd(0x2C)
        lgpio.gpio_write(self.h, DC, 1)
        self.spi.writebytes2(rgb)


def open_xwd(path):
    """mmap an Xvfb XWD screen file as an (H, W, 4) BGRX array."""
    with open(path, "rb") as f:
        hdr = struct.unpack(">25I", f.read(100))
    header_size, ncolors = hdr[0], hdr[19]
    width, height, bpp, bpl = hdr[4], hdr[5], hdr[11], hdr[12]
    if bpp != 32 or (width, height) != (W, H):
        raise RuntimeError(f"unexpected XWD screen {width}x{height}x{bpp}, need {W}x{H}x32")
    offset = header_size + ncolors * 12
    raw = np.memmap(path, dtype=np.uint8, mode="r", offset=offset, shape=(height, bpl))
    return raw.reshape(height, width, 4)


def main():
    a = parse_args()
    tft = Tft(a.speed, a.madctl)
    frame_time = 1.0 / a.fps
    prev = None
    screen = None
    while True:
        t0 = time.monotonic()
        if screen is None:
            try:
                screen = open_xwd(a.fb)
                prev = None
            except (FileNotFoundError, struct.error, ValueError):
                time.sleep(0.5)
                continue
        cur = np.array(screen)                 # snapshot
        if prev is None:
            tft.blit(0, W, 0, H, np.ascontiguousarray(cur[:, :, 2::-1]).tobytes())
        else:
            diff = (cur != prev).any(axis=2)
            rows = np.flatnonzero(diff.any(axis=1))
            if rows.size:
                cols = np.flatnonzero(diff.any(axis=0))
                y0, y1 = int(rows[0]), int(rows[-1]) + 1
                x0, x1 = int(cols[0]), int(cols[-1]) + 1
                tft.blit(x0, x1, y0, y1, np.ascontiguousarray(cur[y0:y1, x0:x1, 2::-1]).tobytes())
        prev = cur
        dt = time.monotonic() - t0
        if dt < frame_time:
            time.sleep(frame_time - dt)


if __name__ == "__main__":
    main()

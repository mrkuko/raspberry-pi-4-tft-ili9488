#!/usr/bin/env python3
"""Fill the SPI TFT with red, green, blue to test whether it responds (ILI9488 init, 18-bit colour).

Wiring (BCM): CS=GPIO8 (kernel), DC=GPIO24, RESET=GPIO25, MOSI=GPIO10, SCK=GPIO11, LED=3V3.
Needs: sudo apt install -y python3-spidev python3-lgpio
Run: sudo python3 fill_test.py
Expected: screen flashes red, green, blue (1 s each) if ILI9488-compatible.
If it stays white/black, try changing INIT_BGR or the controller; report what you see.
"""
import time
import lgpio
import spidev

DC, RST = 24, 25
W, H = 320, 480            # native portrait orientation

h = lgpio.gpiochip_open(0)
lgpio.gpio_claim_output(h, DC, 0)
lgpio.gpio_claim_output(h, RST, 1)

spi = spidev.SpiDev()
spi.open(0, 0)
spi.mode = 0
spi.max_speed_hz = 16_000_000


def cmd(c, *params):
    lgpio.gpio_write(h, DC, 0)
    spi.writebytes([c])
    if params:
        lgpio.gpio_write(h, DC, 1)
        spi.writebytes(list(params))


def fill(r, g, b):
    cmd(0x2A, 0, 0, (W - 1) >> 8, (W - 1) & 0xFF)
    cmd(0x2B, 0, 0, (H - 1) >> 8, (H - 1) & 0xFF)
    cmd(0x2C)
    lgpio.gpio_write(h, DC, 1)
    spi.writebytes2(bytes([r, g, b]) * (W * H))


# hardware reset
lgpio.gpio_write(h, RST, 1); time.sleep(0.01)
lgpio.gpio_write(h, RST, 0); time.sleep(0.02)
lgpio.gpio_write(h, RST, 1); time.sleep(0.15)

cmd(0x01); time.sleep(0.15)            # software reset
cmd(0x11); time.sleep(0.15)            # sleep out
cmd(0xE0, 0x00, 0x03, 0x09, 0x08, 0x16, 0x0A, 0x3F, 0x78, 0x4C, 0x09, 0x0A, 0x08, 0x16, 0x1A, 0x0F)  # gamma +
cmd(0xE1, 0x00, 0x16, 0x19, 0x03, 0x0F, 0x05, 0x32, 0x45, 0x46, 0x04, 0x0E, 0x0D, 0x35, 0x37, 0x0F)  # gamma -
cmd(0xC0, 0x17, 0x15)                  # power control 1
cmd(0xC1, 0x41)                        # power control 2
cmd(0xC5, 0x00, 0x12, 0x80)            # VCOM
cmd(0x36, 0x48)                        # memory access control (BGR)
cmd(0x3A, 0x66)                        # 18-bit colour (the only mode ILI9488 SPI supports)
cmd(0xB0, 0x00)                        # interface mode
cmd(0xB1, 0xA0)                        # frame rate
cmd(0xB4, 0x02)                        # display inversion
cmd(0xB6, 0x02, 0x02)                  # display function
cmd(0xE9, 0x00)
cmd(0xF7, 0xA9, 0x51, 0x2C, 0x82)      # adjust control 3
cmd(0x29); time.sleep(0.1)             # display on

for name, rgb in (("red", (255, 0, 0)), ("green", (0, 255, 0)), ("blue", (0, 0, 255))):
    print("fill", name)
    fill(*rgb)
    time.sleep(1)

spi.close()
lgpio.gpiochip_close(h)

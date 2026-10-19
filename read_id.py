#!/usr/bin/env python3
"""Read the ID registers of the SPI TFT to identify the LCD controller.

Wiring (BCM): CS=GPIO8, DC=GPIO24, RESET=GPIO25, MOSI=GPIO10, MISO=GPIO9, SCK=GPIO11.
Needs: sudo apt install -y python3-spidev python3-lgpio
Expected: ILI9488 -> 00 94 88 (0xD3), ILI9486 -> 00 94 86, ST7796 -> 00 77 96
"""
import time
import lgpio
import spidev

CS, DC, RST = 8, 24, 25

h = lgpio.gpiochip_open(0)
for pin, level in ((DC, 0), (RST, 1)):
    lgpio.gpio_claim_output(h, pin, level)

# The SPI kernel driver usually owns GPIO8 (CE0). Try to drive CS ourselves so it
# stays low across cmd + read; if it is busy, fall back to the kernel-driven CS.
try:
    lgpio.gpio_claim_output(h, CS, 1)
    manual_cs = True
except lgpio.error:
    manual_cs = False
print("CS mode:", "manual GPIO" if manual_cs else "kernel (CS toggles between cmd and read)")

spi = spidev.SpiDev()
spi.open(0, 0)
spi.mode = 0
spi.no_cs = manual_cs
spi.max_speed_hz = 1_000_000

# hardware reset
lgpio.gpio_write(h, RST, 1); time.sleep(0.01)
lgpio.gpio_write(h, RST, 0); time.sleep(0.02)
lgpio.gpio_write(h, RST, 1); time.sleep(0.15)


def read_reg(cmd, n):
    if manual_cs:
        lgpio.gpio_write(h, CS, 0)
    lgpio.gpio_write(h, DC, 0)
    spi.xfer2([cmd])
    lgpio.gpio_write(h, DC, 1)
    data = spi.xfer2([0x00] * n)
    if manual_cs:
        lgpio.gpio_write(h, CS, 1)
    return " ".join(f"{b:02x}" for b in data)


print("RDDID   (0x04):", read_reg(0x04, 4), " # first byte is dummy")
print("ID4     (0xD3):", read_reg(0xD3, 4), " # first byte is dummy")
print("Status  (0x09):", read_reg(0x09, 5))
print("ID1/2/3 (DA/DB/DC):", read_reg(0xDA, 2), "|", read_reg(0xDB, 2), "|", read_reg(0xDC, 2))

spi.close()
lgpio.gpiochip_close(h)

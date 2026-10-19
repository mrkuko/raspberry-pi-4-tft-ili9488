"""Minimal XPT2046 (ADS7846-compatible) resistive touch reader over spidev, no IRQ pin needed.

Touch is detected from pressure: z = z1 + 4095 - z2 (about 0 when untouched). Wiring: T_CS on CE1
(/dev/spidev0.1), T_CLK/T_DIN/T_DO shared with the display SPI bus.
"""
import spidev

RAW_MIN, RAW_MAX = 100, 4000
CH_X, CH_Y, CH_Z1, CH_Z2 = 0xD0, 0x90, 0xB0, 0xC0   # start | channel | 12-bit | differential | power-down


class XPT2046:
    def __init__(self, bus=0, dev=1, speed=1_000_000, z_threshold=400):
        self.z_threshold = z_threshold
        self.spi = spidev.SpiDev()
        self.spi.open(bus, dev)
        self.spi.mode = 0
        self.spi.max_speed_hz = speed

    def _raw(self, cmd):
        r = self.spi.xfer2([cmd, 0, 0])
        return ((r[1] << 8) | r[2]) >> 3

    def _channel(self, cmd, n=3):
        self._raw(cmd)                                  # first conversion after a channel switch is unreliable
        vals = sorted(self._raw(cmd) for _ in range(n))
        return vals[n // 2]                             # median

    def pressure(self):
        z1 = self._channel(CH_Z1, 1)
        z2 = self._channel(CH_Z2, 1)
        return z1 + 4095 - z2 if z1 else 0

    def read(self):
        """Return (x, y, z, pressed). x/y are raw 0..4095 and only valid when pressed."""
        z = self.pressure()
        if z < self.z_threshold:
            return 0, 0, z, False
        x, y = self._channel(CH_X), self._channel(CH_Y)
        # lift-off / contact bounce gives readings pinned at the ADC limits (e.g. 0,4095): drop them
        if not (RAW_MIN <= x <= RAW_MAX and RAW_MIN <= y <= RAW_MAX):
            return 0, 0, z, False
        return x, y, z, True

    def close(self):
        self.spi.close()

#!/usr/bin/env python3
"""inputd: forward physical keyboard/mouse (evdev) into the virtual X screen (Xvfb :1) via XTEST.

Also handles mode hotkeys without SSH:
  Ctrl+Alt+F1 -> `tftmode terminal`
  Ctrl+Alt+F2 -> `tftmode gui`
  Ctrl+Alt+F3 -> `tftmode console` (real tty1 console, kernel framebuffer)

X keycodes = Linux evdev keycode + 8 (standard evdev XKB keycodes), so no keysym mapping is needed.
Needs: python3-evdev python3-xlib. Run as root (reads /dev/input/event*).
"""
import json
import os
import selectors
import subprocess
import time

import evdev
from evdev import ecodes as e
from Xlib import X, display
from Xlib.ext import xtest

from xpt2046 import XPT2046

DISPLAY = ":1"
RESCAN_S = 3.0
W, H = 480, 320
DEBUG = bool(os.environ.get("TFT_DEBUG"))
TOUCH_Z = int(os.environ.get("TFT_TOUCH_Z", "400"))   # pressure threshold, tune with TFT_DEBUG=1
TOUCH_ENABLED = os.environ.get("TFT_TOUCH", "on").lower() != "off"   # "off" for builds without touch wiring
TOUCH_POLL_S = 0.01
CAL_FILE = "/etc/default/tft-touch.json"   # written by calibrate.py: {"matrix": [a,b,c,d,e,f]}

BUTTONS = {e.BTN_LEFT: 1, e.BTN_MIDDLE: 2, e.BTN_RIGHT: 3}
CTRL = {e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL}
ALT = {e.KEY_LEFTALT, e.KEY_RIGHTALT}


def is_input_device(dev):
    caps = dev.capabilities()
    keys = caps.get(e.EV_KEY, [])
    has_keyboard = e.KEY_A in keys and e.KEY_ENTER in keys
    has_mouse = e.EV_REL in caps and e.BTN_LEFT in keys
    has_touch = (e.BTN_TOUCH in keys
                 and any(code == e.ABS_X for code, _ in caps.get(e.EV_ABS, [])))
    return has_keyboard or has_mouse or has_touch


def load_matrix():
    """Affine map raw touch -> screen: sx = a*rx + b*ry + c, sy = d*rx + e*ry + f."""
    try:
        with open(CAL_FILE) as f:
            m = json.load(f)["matrix"]
        if len(m) == 6:
            return m
    except (OSError, ValueError, KeyError):
        pass
    return [W / 4095, 0, 0, 0, H / 4095, 0]    # uncalibrated guess


class Forwarder:
    def __init__(self):
        self.d = None
        self.held = set()
        self.rx = self.ry = 0
        self.touch_down = False
        self.touch_changed = False
        self.touch_moved = False
        self.matrix = load_matrix()

    def connect(self):
        try:
            self.d = display.Display(DISPLAY)
            if not self.d.has_extension("XTEST"):
                raise RuntimeError("no XTEST")
        except Exception as exc:
            self.d = None
            if DEBUG:
                print(f"inputd: X connect failed: {exc!r}", flush=True)
        return self.d is not None

    def fake(self, kind, detail, **kw):
        if self.d is None and not self.connect():
            return
        try:
            xtest.fake_input(self.d, kind, detail, **kw)
            self.d.sync()
        except Exception:
            self.d = None

    def handle(self, ev):
        if ev.type == e.EV_KEY:
            if ev.value in (0, 1):
                (self.held.add if ev.value else self.held.discard)(ev.code)
            if self.hotkey(ev):
                return
            if ev.code == e.BTN_TOUCH:
                self.touch_down = bool(ev.value)
                self.touch_changed = True
                if self.touch_down:
                    self.matrix = load_matrix()        # pick up fresh calibration
            elif ev.code in BUTTONS:
                self.fake(X.ButtonPress if ev.value else X.ButtonRelease, BUTTONS[ev.code])
            elif ev.code < 256 and ev.value in (0, 1, 2):
                if ev.value == 2:          # autorepeat: X generates its own repeats
                    return
                self.fake(X.KeyPress if ev.value else X.KeyRelease, ev.code + 8)
        elif ev.type == e.EV_ABS:
            if ev.code == e.ABS_X:
                self.rx = ev.value
                self.touch_moved = True
            elif ev.code == e.ABS_Y:
                self.ry = ev.value
                self.touch_moved = True
        elif ev.type == e.EV_SYN and ev.code == e.SYN_REPORT:
            self.flush_touch()
        elif ev.type == e.EV_REL:
            if ev.code == e.REL_X:
                self.fake(X.MotionNotify, True, x=ev.value, y=0)
            elif ev.code == e.REL_Y:
                self.fake(X.MotionNotify, True, x=0, y=ev.value)
            elif ev.code == e.REL_WHEEL:
                b = 4 if ev.value > 0 else 5
                for _ in range(abs(ev.value)):
                    self.fake(X.ButtonPress, b)
                    self.fake(X.ButtonRelease, b)

    def flush_touch(self):
        if not (self.touch_changed or self.touch_moved):
            return
        if self.touch_down:
            a, b, c, d, e_, f = self.matrix
            sx = min(W - 1, max(0, round(a * self.rx + b * self.ry + c)))
            sy = min(H - 1, max(0, round(d * self.rx + e_ * self.ry + f)))
            if DEBUG:
                print(f"touch raw=({self.rx},{self.ry}) -> screen=({sx},{sy}) x_ok={self.d is not None}", flush=True)
            self.fake(X.MotionNotify, False, x=sx, y=sy)      # absolute move
        if self.touch_changed:
            self.fake(X.ButtonPress if self.touch_down else X.ButtonRelease, 1)
        self.touch_changed = self.touch_moved = False

    def hotkey(self, ev):
        modes = {e.KEY_F1: "terminal", e.KEY_F2: "gui", e.KEY_F3: "console"}
        if ev.value != 1 or ev.code not in modes:
            return False
        if not (self.held & CTRL and self.held & ALT):
            return False
        mode = modes[ev.code]
        subprocess.Popen(["/usr/local/bin/tftmode", mode])
        return True


def poll_touch(fwd, touch, st):
    """Read the XPT2046 over SPI and feed the shared touch state; debounce down/up."""
    x, y, z, pressed = touch.read()
    if pressed:
        st["down"] += 1
        st["up"] = 0
        fwd.rx, fwd.ry = x, y
        fwd.touch_moved = True
    else:
        st["up"] += 1
        st["down"] = 0
    if not fwd.touch_down and st["down"] >= 2:
        fwd.touch_down = True
        fwd.touch_changed = True
        fwd.matrix = load_matrix()
    elif fwd.touch_down and st["up"] >= 3:
        fwd.touch_down = False
        fwd.touch_changed = True
    if DEBUG and (pressed or fwd.touch_changed):
        print(f"xpt2046 raw=({x},{y}) z={z} pressed={pressed}", flush=True)
    fwd.flush_touch()


def main():
    sel = selectors.DefaultSelector()
    open_paths = {}
    fwd = Forwarder()
    last_scan = 0.0
    touch = None
    touch_state = {"down": 0, "up": 0}
    last_touch_try = last_poll = 0.0
    while True:
        now = time.monotonic()
        if TOUCH_ENABLED and touch is None and now - last_touch_try > 5.0:
            last_touch_try = now
            try:
                touch = XPT2046(z_threshold=TOUCH_Z)
                print("inputd: XPT2046 touch on /dev/spidev0.1", flush=True)
            except OSError:
                touch = None
        if now - last_scan > RESCAN_S:
            last_scan = now
            for path in evdev.list_devices():
                if path in open_paths:
                    continue
                try:
                    dev = evdev.InputDevice(path)
                    if is_input_device(dev):
                        sel.register(dev, selectors.EVENT_READ)
                        open_paths[path] = dev
                        print(f"inputd: using {dev.path} ({dev.name})", flush=True)
                except OSError:
                    pass
        for key, _ in sel.select(timeout=TOUCH_POLL_S if touch else 1.0):
            dev = key.fileobj
            try:
                for ev in dev.read():
                    fwd.handle(ev)
            except OSError:                     # device unplugged
                sel.unregister(dev)
                open_paths.pop(dev.path, None)
        if touch is not None and time.monotonic() - last_poll >= TOUCH_POLL_S:
            last_poll = time.monotonic()
            try:
                poll_touch(fwd, touch, touch_state)
            except OSError:
                touch = None


if __name__ == "__main__":
    main()

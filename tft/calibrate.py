#!/usr/bin/env python3
"""Touch calibration for the 480x320 TFT. Run on the Pi:  sudo tftcal

Shows 4 crosshairs on the virtual screen (DISPLAY=:1); tap each one. Raw XPT2046 readings are
read over SPI (no kernel driver) and fitted to screen coordinates with a least-squares affine
transform (handles swapped/inverted axes), saved to /etc/default/tft-touch.json.
Needs: python3-tk python3-numpy python3-spidev
"""
import json
import os
import statistics
import sys
import tkinter as tk

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xpt2046 import XPT2046

W, H = 480, 320
CAL_FILE = "/etc/default/tft-touch.json"
TARGETS = [(40, 40), (W - 40, 40), (W - 40, H - 40), (40, H - 40)]
Z_THRESHOLD = int(os.environ.get("TFT_TOUCH_Z", "400"))
os.environ.setdefault("DISPLAY", ":1")

try:
    touch = XPT2046(z_threshold=Z_THRESHOLD)
except OSError as exc:
    sys.exit(f"cannot open /dev/spidev0.1 ({exc}); remove the ads7846 overlay and reboot (see README)")

root = tk.Tk()
root.overrideredirect(True)
root.geometry(f"{W}x{H}+0+0")
canvas = tk.Canvas(root, width=W, height=H, bg="black", highlightthickness=0)
canvas.pack()

raw_points = []
samples = []
state = {"i": 0, "down": False}


def draw():
    canvas.delete("all")
    x, y = TARGETS[state["i"]]
    canvas.create_line(x - 20, y, x + 20, y, fill="white", width=2)
    canvas.create_line(x, y - 20, x, y + 20, fill="white", width=2)
    canvas.create_text(W // 2, H // 2, fill="white", font=("Helvetica", 14),
                       text=f"Tap the cross {state['i'] + 1}/{len(TARGETS)}")


def finish():
    raw = np.array(raw_points, dtype=float)
    A = np.column_stack([raw, np.ones(len(raw))])
    tx = np.array([t[0] for t in TARGETS], dtype=float)
    ty = np.array([t[1] for t in TARGETS], dtype=float)
    cx, *_ = np.linalg.lstsq(A, tx, rcond=None)
    cy, *_ = np.linalg.lstsq(A, ty, rcond=None)
    matrix = [float(v) for v in (*cx, *cy)]
    err = max(np.hypot(A @ cx - tx, A @ cy - ty))
    with open(CAL_FILE, "w") as f:
        json.dump({"matrix": matrix}, f)
    msg = f"Saved. Max error {err:.1f}px"
    print(msg, matrix)
    canvas.delete("all")
    canvas.create_text(W // 2, H // 2, fill="white", font=("Helvetica", 14), text=msg)
    root.after(1500, root.destroy)


def poll():
    x, y, z, pressed = touch.read()
    if pressed:
        if not state["down"]:
            state["down"] = True
            samples.clear()
        samples.append((x, y))
    elif state["down"]:
        state["down"] = False
        if len(samples) >= 4:
            raw_points.append((statistics.median(s[0] for s in samples),
                               statistics.median(s[1] for s in samples)))
            print(f"point {len(raw_points)}: raw {raw_points[-1]} from {len(samples)} samples", flush=True)
            state["i"] += 1
            if state["i"] == len(TARGETS):
                finish()
                return
            draw()
    root.after(10, poll)


draw()
root.after(10, poll)
root.mainloop()

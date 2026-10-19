<p align="center">
  <img src="images/banner.png" alt="3.5 inch TFT display with touch on a Raspberry Pi 4" width="100%">
</p>

# Raspberry Pi 4 + 3.5" ILI9488 SPI TFT

Drives a generic 3.5" 480x320 SPI TFT module (ILI9488 controller, XPT2046 resistive touch) from a Raspberry Pi 4.
The screen can show a terminal, a small desktop, or the real tty1 console. Keyboard, mouse and touch are supported.
Everything runs in userspace on stock Raspberry Pi OS; no kernel driver for the panel is needed.

**Contents:** [Status](#status) · [How it works](#how-it-works) · [Hardware](#hardware) ·
[Build A: without touch](#build-a-without-touch) · [Build B: with touch](#build-b-with-touch) ·
[Switching between A and B](#switching-between-a-and-b) · [Usage](#usage) ·
[Real tty1 console](#real-tty1-console) · [Troubleshooting](#troubleshooting) ·
[Project layout](#project-layout) · [Open items](#open-items)

## Status

Tested on Raspberry Pi 4 Model B (8 GB), Raspberry Pi OS Lite 64-bit (Trixie), kernel 6.18.

| Feature | State |
|---|---|
| Display output (ILI9488, 18-bit colour over SPI) | working |
| Terminal and small GUI mode | working |
| Real tty1 console on the display | working; appears partway through boot, see [Real tty1 console](#real-tty1-console) |
| Keyboard and mouse | working |
| Touch (finger or stylus) | working; a stylus is more precise |
| Build without touch (`TFT_TOUCH=off`) | implemented, not tested on hardware |
| Clean install with `tft/install.sh` on a fresh card | not tested end to end |
| Mouse cursor on the display | not available (the Xvfb framebuffer has no cursor) |

## How it works

### Constraints
- The ILI9488 accepts only 18-bit colour over 4-wire SPI (3 bytes per pixel). The usual `fbtft` and `mipi-dbi`
  setups assume 16-bit colour and produce garbage on this panel.
- `fbcp-ili9341`, which copies the HDMI framebuffer to an SPI display, depends on DispmanX, which current
  Raspberry Pi OS no longer has.
- The kernel `ads7846` touch overlay did not work with this module (see [Troubleshooting](#troubleshooting)).

The display is therefore driven by a small userspace daemon that mirrors a 480x320 framebuffer over SPI.

### Data flow
```
  Xvfb :1  (virtual screen)  ----+
                                 +--> tftd.py --SPI0 CE0, 32 MHz--> ILI9488
  /dev/fb0 (tty1 console)  ------+

  keyboard / mouse (evdev) ----+
                               +--> inputd.py --XTEST--> Xvfb :1
  touch (XPT2046, SPI0 CE1) ---+
```

### Display (`tftd.py`)
1. The source is either the Xvfb screen or the kernel framebuffer `/dev/fb0` (`--source xwd|fb`).
   Xvfb is started with `-fbdir /dev/shm/tft`, so it keeps the screen in a memory-mapped XWD file.
2. Thirty times per second the daemon snapshots the frame, compares it with the previous one and sends only the
   bounding rectangle of the changed pixels. The first frame is sent in full.
3. Pixels are converted to RGB and sent as 3 bytes each (the ILI9488 uses the upper 6 bits of every byte).
   Both 32-bit BGRX and 16-bit RGB565 sources are handled.
4. Commands are sent with the DC pin (GPIO24) low and data with DC high. `0x2A` and `0x2B` set the column and row
   window, `0x2C` starts the memory write. Reset is a pulse on GPIO25.
5. Init sequence: software reset, sleep out, gamma tables, power and VCOM, `0x36` memory access control
   (rotation, mirroring, BGR), `0x3A = 0x66` (18-bit colour), frame rate, inversion, display on.
6. Chip select (GPIO8, CE0) is owned by the kernel SPI driver, so userspace cannot hold it low across a
   command and a read. This is why reading registers (`read_id.py`) returns only zeros. Writes are not affected.

### Input (`inputd.py`)
- **Keyboard and mouse:** events are read from `/dev/input/event*` with `evdev` and injected into Xvfb with the
  XTEST extension. Xvfb has no input devices of its own. X keycodes equal Linux keycodes plus 8, so no keymap is
  needed. The layout is set with `setxkbmap` from `KBD_LAYOUT`.
- **Mode hotkeys:** Ctrl+Alt+F1 runs `tftmode terminal`, F2 runs `tftmode gui`, F3 runs `tftmode console`.
- **Touch (`xpt2046.py`):** the XPT2046 is read directly over `/dev/spidev0.1` (T_CS on CE1) instead of through
  the kernel driver. The T_IRQ pin is not used. A touch is detected from pressure, `z = z1 + 4095 - z2`
  (about 0 when untouched). X and Y are the median of three conversions. Readings pinned at the ADC limits
  (outside 100..4000, typical at finger lift) are dropped. A touch starts after 2 consecutive polls above the
  threshold (`TFT_TOUCH_Z`, default 400) and ends after 3 below it. The panel is polled every 10 ms.
- **Calibration:** raw 12-bit coordinates are mapped to pixels by an affine transform
  `sx = a*rx + b*ry + c`, `sy = d*rx + e*ry + f`, stored in `/etc/default/tft-touch.json` and reloaded on every
  new touch. `calibrate.py` (`sudo tftcal`) shows four crosses 40 px from the corners, takes the median raw point
  of each tap and fits the six coefficients by least squares, which also handles swapped or mirrored axes.
- Touch is delivered to Xvfb as an absolute pointer move plus button 1 press and release.

### Modes and services
A mode is whatever runs on the screen.

| Mode | What runs |
|---|---|
| `terminal` | `xterm` 80x24 on the virtual screen (the 6x13 font fills 480x312 px) |
| `gui` | Openbox, tint2 panel and an xterm on the virtual screen |
| `console` | the kernel console on tty1, mirrored from `/dev/fb0` |

| Service | Role |
|---|---|
| `tft-xvfb` | virtual X screen |
| `tftd` | mirrors the active screen to the display |
| `tft-input` | keyboard, mouse and touch forwarding |
| `tft-mode-terminal`, `tft-mode-gui` | the two X modes (mutually exclusive) |
| `tft-boot` | starts the last used mode at boot |

`tftmode <mode>` stops the running mode, switches the `tftd` source, restarts it and starts the new mode.
The last mode is stored as `TFT_MODE` in `/etc/default/tft`. Other settings in that file: `KBD_LAYOUT`,
`TFT_TOUCH` (`on` or `off`) and `TFT_SOURCE` (`xwd` or `fb`, set by `tftmode`).

## Hardware

- Raspberry Pi 4 Model B.
- 3.5" TFT SPI module, 480x320, red PCB marked "3.5'' TFT SPI 480X320 V1.0", with a single 14-pin header
  (it does not plug onto the Pi; jumper wires are required). It resembles the LCDWiki MSP3520/MSP3521 family and
  similar modules such as the Elecrow DLS24035B. It has an on-board 3.3 V regulator and a micro-SD slot whose pads
  are not routed to the header, so the slot is unusable.
- LCD controller: ILI9488 or compatible, confirmed by the working init sequence. Touch controller: XPT2046 (resistive).

Header pins, left to right as printed on the board:
`VCC, GND, CS, RESET, DC/RS, SDI(MOSI), SCK, LED, SDO(MISO), T_CLK, T_CS, T_DIN, T_DO, T_IRQ`

<table>
  <tr>
    <td width="50%"><img src="images/board-header-labels.jpg" alt="Display header with pin labels"></td>
    <td width="50%"><img src="images/board-back.jpg" alt="Back of the 3.5 inch TFT board"></td>
  </tr>
  <tr>
    <td align="center"><sub>14-pin header and silkscreen labels</sub></td>
    <td align="center"><sub>Back of the board: micro-SD slot (unused) and the touch controller</sub></td>
  </tr>
</table>

Pi pin numbers below are physical header pins. Pins 19, 21, 23 and 24 are the SPI0 bus; pin 26 is its second
chip select.

## Build A: without touch

Eight wires. A ninth wire (SDO) is optional and not needed.

### A1. Wiring
Power the Pi off while wiring.

| Display | Pi pin | Pi GPIO |
|---|---|---|
| VCC | 1 | 3V3 |
| GND | 6 | GND |
| LED | 17 | 3V3 |
| DC/RS | 18 | GPIO24 |
| SDI (MOSI) | 19 | GPIO10 |
| RESET | 22 | GPIO25 |
| SCK | 23 | GPIO11 |
| CS | 24 | GPIO8 (CE0) |

VCC and LED go to 3.3 V, never to 5 V (pins 2 and 4). The `T_*` pins stay unconnected. The diagram also shows the
optional SDO wire on pin 21.

![Wiring without touch](diagrams/wiring-display.png)

On power-up the backlight turns on white. That only confirms power, not the data lines.

### A2. Prepare the Pi
1. Flash Raspberry Pi OS Lite (64-bit) with Raspberry Pi Imager. In its settings set the hostname, user and
   password and Wi-Fi, and enable SSH.
2. Boot the Pi and log in over SSH: `ssh <user>@<pi-ip>`.
3. Update: `sudo apt update && sudo apt full-upgrade -y`.

### A3. Install
From the computer holding this repository:
```bash
scp -r tft <user>@<pi-ip>:~/
ssh <user>@<pi-ip>
cd ~/tft
sudo bash install.sh
sudo tfttouch off          # no touch wiring: do not poll the touch chip
sudo reboot
```
`install.sh` installs the packages (Xvfb, xterm, Openbox, tint2, Python libraries), enables SPI
(`raspi-config nonint do_spi 0`), copies the programs to `/opt/tft/`, creates the systemd services and installs the
`tftmode`, `tfttouch` and `tftcal` commands. `tftd` logs errors until the first reboot because `/dev/spidev0.0`
only appears after SPI is enabled and the Pi has restarted.

### A4. Verify
After the reboot:
1. `ls /dev/spidev*` lists `/dev/spidev0.0` (and `0.1`).
2. The display shows a terminal with a shell prompt.
3. Typing on a keyboard attached to the Pi works. `sudo tftmode gui` switches to the desktop, Ctrl+Alt+F1 returns.
4. Service state: `systemctl status tftd tft-xvfb tft-input --no-pager`. Logs: `journalctl -u tftd -n 30`.

Standalone hardware test, independent of the services: stop the daemon with `sudo systemctl stop tftd`, copy
`fill_test.py` to the Pi and run `sudo python3 fill_test.py`. The screen should flash red, green and blue.
Restart the daemon afterwards with `sudo systemctl start tftd`.

If the picture is mirrored or upside down, add `--madctl 0x68` (or `0xA8`, `0xE8`) to the `ExecStart` line of
`tftd.service`.

## Build B: with touch

Build A plus the touch wiring and a calibration. 13 wires in total.

### B1. Wiring
Add to the Build A wiring:

| Display | Pi pin | Pi GPIO | Note |
|---|---|---|---|
| T_CS | 26 | GPIO7 (CE1) | touch chip select |
| T_CLK | 23 | GPIO11 | shares the pin with SCK (two wires) |
| T_DIN | 19 | GPIO10 | shares the pin with SDI (two wires) |
| T_DO | 21 | GPIO9 (MISO) | touch data out |
| T_IRQ | 11 | GPIO17 | optional, not used by the software |

- The display's SDO must not be connected to pin 21. T_DO uses that pin, and the LCD's SDO may not release the line.
- Pins 19 and 23 carry two wires each. Use a breadboard row or a splitter; two Dupont connectors do not fit on one pin.

![Wiring with touch](diagrams/wiring-display-touch.png)

### B2. Install
On a fresh Pi follow A2 and A3, but skip `sudo tfttouch off` (touch is on by default). On a Pi that already runs
Build A, add the wires and run:
```bash
sudo tfttouch on
ls /dev/spidev*            # expect spidev0.0 and spidev0.1
```
If the Pi was previously set up with the kernel `ads7846` overlay, run `sudo bash ~/tft/touch-userspace.sh` and
reboot. The script removes the overlays that hide `/dev/spidev*`.

### B3. Check raw touch input
```bash
sudo systemctl stop tft-input
sudo TFT_DEBUG=1 python3 -u /opt/tft/inputd.py
```
Touching the screen should print lines such as `xpt2046 raw=(3197,2788) z=851 pressed=True`, and
`pressed=False` when released. Stop with Ctrl+C and run `sudo systemctl start tft-input`.
- No output: the chip is not answering. Check T_CS (26), T_DO (21), T_DIN (19), T_CLK (23) and that SDO is not on pin 21.
- Output without touching, or missed touches: adjust `TFT_TOUCH_Z` (for example 300 or 600) in the environment of
  `tft-input`. The `z` value in the debug output shows the idle and pressed levels.

### B4. Calibrate
```bash
sudo tftcal
```
Four crosses appear on the display. Tap the centre of each in turn, preferably with a stylus. The command prints
`Saved. Max error N px`; a few pixels up to about 8 to 10 px is typical for a resistive panel. The result is
saved to `/etc/default/tft-touch.json` and applies immediately.

## Switching between A and B

| Change | Steps |
|---|---|
| B to A (remove touch) | Unplug the `T_*` wires, `sudo tfttouch off`. |
| A to B (add touch) | Power off, remove SDO from pin 21 if present, add the wires from B1, `sudo tfttouch on`, `sudo tftcal`. |

## Usage

| Task | Command |
|---|---|
| Terminal mode | `sudo tftmode terminal` |
| Desktop mode | `sudo tftmode gui` |
| tty1 console | `sudo tftmode console` (see [Real tty1 console](#real-tty1-console)) |
| Switch from the Pi's keyboard | Ctrl+Alt+F1 terminal, Ctrl+Alt+F2 desktop, Ctrl+Alt+F3 console |
| Touch on or off | `sudo tfttouch on` / `sudo tfttouch off` |
| Calibrate touch | `sudo tftcal` |
| Keyboard layout | set `KBD_LAYOUT` in `/etc/default/tft` (`us`, `sk`, `cz`, ...), then `sudo tftmode <mode>` |
| Rotation or mirroring | `tftd.py --madctl 0x28` (alternatives `0x68`, `0xA8`, `0xE8`) |
| SPI speed | `tftd.py --speed 32000000` (lower it if the picture shows artefacts) |
| Apply edited files | `cd ~/tft && sudo bash install.sh` (safe to re-run), or copy single files to `/opt/tft/` and `sudo systemctl restart tftd tft-input` |

The last used mode is restored at boot. The `terminal` mode is an `xterm` running a shell of the Pi user, not
the system console.

## Real tty1 console

The `console` mode shows the kernel console (boot messages after the daemon starts, login prompt, anything on
tty1) on the display. The Pi's HDMI output is used only as a software framebuffer: no monitor or cable is
involved. The output is forced to a 480x320 mode, the kernel console renders into `/dev/fb0` at exactly that
size (60x20 characters with the 8x16 font), and `tftd --source fb` copies the framebuffer to the SPI display.

A plain `video=HDMI-A-1:480x320@60D` does not work. The kernel log reports
`User-defined mode not supported: "480x320": 60 11153 ...` because the vc4 HDMI driver rejects pixel clocks
below about 25 MHz, and a 480x320 mode needs only 11.15 MHz. Instead, `tft/make_edid.py` builds a 128-byte EDID
(`tft/480x320.bin`) with a 480x320 active area and large blanking (800x525 total, 25.2 MHz, 60 Hz). It is loaded
through `drm.edid_firmware`, and `video=HDMI-A-1:D` forces the connector on without a monitor.

Setup, after `install.sh` has run:
```bash
cd ~/tft
sudo bash console-setup.sh        # installs /lib/firmware/edid/480x320.bin and edits cmdline.txt
sudo reboot
cat /sys/class/graphics/fb0/virtual_size        # expect 480,320
sudo tftmode console                            # or Ctrl+Alt+F3 on the Pi's keyboard
```
- The script keeps a backup as `/boot/firmware/cmdline.txt.bak-console` and keeps `cmdline.txt` on one line.
- The framebuffer is 16 bpp (RGB565, stride 960); `tftd` reads 16 and 32 bpp framebuffers.
- For a connector other than `HDMI-A-1`: `CONNECTOR=HDMI-A-2 sudo -E bash console-setup.sh`.
- To revert: `sudo bash console-setup.sh --undo` and reboot. If the Pi does not boot, edit `cmdline.txt` on the
  SD card's boot partition from another computer.
- A monitor connected to that HDMI port would be forced to the same EDID.
- `tftd` is a normal systemd service, so the display stays blank until it starts partway through boot. Earlier
  kernel messages are not shown.
- In `console` mode typing goes straight to the kernel console. Touch has no effect there. In `terminal` and `gui`
  mode the active virtual console is switched to an unused one so keystrokes do not reach the tty1 login.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Plain white screen, only the backlight | `tftd` is failing, for example `/dev/spidev0.0` is missing | `ls /dev/spidev*` and `journalctl -u tftd`. Ensure `dtparam=spi=on` is set and no `ads7846` overlay is present in `/boot/firmware/config.txt`; reboot after enabling SPI. |
| White screen and stripes alternating in console mode | `tftd` crashes and restarts; each start resets the panel | `journalctl -u tftd`; the framebuffer must be 480x320 at 16 or 32 bpp |
| `/dev/spidev*` disappear after enabling touch | the kernel `ads7846` overlay disables spidev0 and claims CE1 | remove the overlay (`tft/touch-userspace.sh`); touch is read in userspace |
| Kernel touch device exists but `evtest` shows nothing | the driver is interrupt driven and GPIO17 (T_IRQ) never changed level, while the chip itself answered over SPI | use the userspace pressure polling. A changing `/sys/class/hwmon/hwmon2/temp0` shows the SPI link works. |
| Keyboard types nothing in the terminal | Xvfb has no input devices | `tft-input` must be running (`install.sh` sets it up) |
| `read_id.py` prints only zeros | register readback does not work on this module | not required; ignore |
| Pointer jumps to a corner at finger lift | readings pinned at the ADC limits, e.g. `(0,4095)`, at low pressure | filtered in `xpt2046.py`; default threshold is 400 |
| Touch is inaccurate | not calibrated | `sudo tftcal` |
| Phantom touches in Build A | the touch wires are not connected and the SPI line floats | `sudo tfttouch off` |
| `console-setup.sh` has no effect (`fb0` stays 1024x768) | `drm.edid_firmware` ignored or wrong connector | check `zcat /proc/config.gz \| grep EDID_FIRMWARE`, `ls /sys/class/drm/`, `dmesg \| grep -i edid` |

## Project layout

```
README.md                    this file
read_id.py                   attempt to read the LCD ID registers (returns zeros)
fill_test.py                 ILI9488 init plus red/green/blue fill, standalone display test
image.png                    Raspberry Pi 4 GPIO pinout reference
diagrams/                    wiring diagrams (PNG and SVG) without and with touch
images/                      banner and photos of the board
tft/
  install.sh                 installs packages, enables SPI, creates services and the tftmode/tfttouch/tftcal commands
  tftd.py                    mirrors the Xvfb screen or /dev/fb0 to the ILI9488 over SPI
  inputd.py                  keyboard, mouse and touch input for Xvfb, mode hotkeys
  xpt2046.py                 XPT2046 reader over spidev0.1 (pressure based, no IRQ)
  calibrate.py               four-point touch calibration
  make_edid.py, 480x320.bin  custom EDID for the console mode
  console-setup.sh           installs the EDID and edits cmdline.txt (--undo reverts)
  touch-userspace.sh         removes the old kernel touch overlays on a Pi that used them
  obsolete/                  earlier attempts (kernel ads7846 overlay, spidev0 workaround), kept for reference
```

## Open items

- Draw a mouse cursor or touch feedback on the mirrored screen.
- Run `tftd` and `inputd` as a non-root user (they currently run as root for SPI and evdev access).
- Lower latency: a C implementation or a higher SPI clock.
- Test `install.sh` on a freshly flashed card, and Build A with `tfttouch off`.
- Show early boot messages: start the mirror earlier, for example from the initramfs.

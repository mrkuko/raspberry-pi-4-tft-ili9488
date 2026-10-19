#!/bin/bash
# Install the TFT mirror daemon + two display modes (terminal / gui). Run on the Pi:
#   sudo bash install.sh
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
USER_NAME="${SUDO_USER:?run via sudo from your normal user}"
HERE="$(cd "$(dirname "$0")" && pwd)"

apt-get update
apt-get install -y xvfb xterm openbox tint2 x11-xkb-utils python3-numpy python3-spidev python3-lgpio python3-evdev python3-xlib python3-tk
raspi-config nonint do_spi 0      # enables dtparam=spi=on (/dev/spidev0.0 display, /dev/spidev0.1 touch)

install -d /opt/tft
install -m 755 "$HERE/tftd.py" /opt/tft/tftd.py
install -m 755 "$HERE/inputd.py" /opt/tft/inputd.py
install -m 755 "$HERE/xpt2046.py" /opt/tft/xpt2046.py
install -m 755 "$HERE/calibrate.py" /opt/tft/calibrate.py
cat > /usr/local/bin/tftcal <<'EOF'
#!/bin/sh
# usage: sudo tftcal   (tap the 4 crosses shown on the TFT, use a stylus)
systemctl stop tft-input
DISPLAY=:1 python3 /opt/tft/calibrate.py
systemctl start tft-input
EOF
chmod 755 /usr/local/bin/tftcal

# keyboard layout for the virtual screen (edit and `sudo tftmode <mode>` to apply; e.g. sk, cz, us)
[ -f /etc/default/tft ] || echo "KBD_LAYOUT=us" > /etc/default/tft
# touch support: on = poll the XPT2046 (touch wired), off = ignore touch (no touch wiring)
grep -q '^TFT_TOUCH=' /etc/default/tft || echo "TFT_TOUCH=on" >> /etc/default/tft
cat > /usr/local/bin/tfttouch <<'EOF'
#!/bin/sh
# usage: sudo tfttouch on|off
case "$1" in
  on|off) sed -i "s/^TFT_TOUCH=.*/TFT_TOUCH=$1/" /etc/default/tft; systemctl restart tft-input; echo "touch: $1" ;;
  *) echo "usage: sudo tfttouch on|off"; exit 1 ;;
esac
EOF
chmod 755 /usr/local/bin/tfttouch

cat > /opt/tft/gui-session.sh <<'EOF'
#!/bin/sh
# small desktop on the 480x320 virtual screen
export DISPLAY=:1
tint2 &
xterm -geometry 80x14+0+0 -fn 6x13 &
exec openbox
EOF
chmod 755 /opt/tft/gui-session.sh

cat > /etc/systemd/system/tft-xvfb.service <<EOF
[Unit]
Description=Virtual 480x320 X screen for the TFT

[Service]
User=$USER_NAME
ExecStartPre=/usr/bin/install -d -m 755 /dev/shm/tft
ExecStart=/usr/bin/Xvfb :1 -screen 0 480x320x24 -fbdir /dev/shm/tft -nolisten tcp
Restart=on-failure
EOF

cat > /etc/systemd/system/tftd.service <<'EOF'
[Unit]
Description=Mirror virtual X screen to ILI9488 SPI TFT
After=tft-xvfb.service
Wants=tft-xvfb.service

[Service]
ExecStart=/usr/bin/python3 /opt/tft/tftd.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/tft-input.service <<'EOF'
[Unit]
Description=Forward keyboard/mouse into the virtual TFT screen (+ Ctrl+Alt+F1/F2 mode hotkeys)
After=tft-xvfb.service

[Service]
EnvironmentFile=-/etc/default/tft
ExecStart=/usr/bin/python3 /opt/tft/inputd.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/tft-mode-terminal.service <<EOF
[Unit]
Description=TFT mode: terminal
Requires=tft-xvfb.service
After=tft-xvfb.service
Conflicts=tft-mode-gui.service

[Service]
User=$USER_NAME
Environment=DISPLAY=:1
EnvironmentFile=-/etc/default/tft
ExecStartPre=-/usr/bin/setxkbmap \${KBD_LAYOUT}
ExecStart=/usr/bin/xterm -geometry 80x24+0+0 -fn 6x13 -bg black -fg white -e bash -l
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/tft-mode-gui.service <<EOF
[Unit]
Description=TFT mode: small GUI
Requires=tft-xvfb.service
After=tft-xvfb.service
Conflicts=tft-mode-terminal.service

[Service]
User=$USER_NAME
Environment=DISPLAY=:1
EnvironmentFile=-/etc/default/tft
ExecStartPre=-/usr/bin/setxkbmap \${KBD_LAYOUT}
ExecStart=/opt/tft/gui-session.sh
Restart=on-failure
EOF

cat > /usr/local/bin/tftmode <<'EOF'
#!/bin/sh
# usage: sudo tftmode terminal|gui
case "$1" in
  terminal|gui)
    systemctl stop tft-mode-terminal tft-mode-gui 2>/dev/null
    systemctl restart tft-xvfb tftd
    sleep 1
    systemctl start "tft-mode-$1"
    ;;
  *) echo "usage: sudo tftmode terminal|gui"; exit 1 ;;
esac
EOF
chmod 755 /usr/local/bin/tftmode

systemctl daemon-reload
systemctl enable tftd.service tft-input.service tft-mode-terminal.service
systemctl restart tft-input.service
tftmode terminal
echo "done. Reboot once (SPI), then: sudo tftcal (touch calibration), sudo tftmode gui | terminal"

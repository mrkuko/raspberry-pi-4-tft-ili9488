#!/bin/bash
# Enable the XPT2046 touch controller (kernel ads7846 overlay on SPI0 CE1) and install the touch bits.
# Wire T_CS->pin 26 (GPIO7), T_IRQ->pin 11 (GPIO17), T_CLK/T_DIN share pins 23/19 with SCK/SDI,
# T_DO->pin 21 (display SDO must be disconnected from pin 21). Then run:  sudo bash touch-setup.sh
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
CFG=/boot/firmware/config.txt
OVERLAY="dtoverlay=ads7846,cs=1,penirq=17,penirq_pull=2,speed=1000000,keep_vref_on=1,pmax=255"

apt-get install -y python3-tk python3-evdev python3-numpy evtest

if grep -q '^dtoverlay=ads7846' "$CFG"; then
  echo "ads7846 overlay already in $CFG"
else
  cp "$CFG" "$CFG.bak-touch"
  printf '\n# 3.5" TFT touch (XPT2046) on SPI0 CE1\n%s\n' "$OVERLAY" >> "$CFG"
  echo "added overlay to $CFG (backup: $CFG.bak-touch)"
fi

install -m 755 "$HERE/inputd.py" /opt/tft/inputd.py
install -m 755 "$HERE/calibrate.py" /opt/tft/calibrate.py
cat > /usr/local/bin/tftcal <<'EOF'
#!/bin/sh
# usage: sudo tftcal   (tap the 4 crosses shown on the TFT)
DISPLAY=:1 exec python3 /opt/tft/calibrate.py
EOF
chmod 755 /usr/local/bin/tftcal
systemctl restart tft-input.service

echo "done. Reboot, then check: grep -A4 ADS7846 /proc/bus/input/devices ; then run: sudo tftcal"

#!/bin/bash
# Switch touch to userspace XPT2046 polling (no T_IRQ, no kernel ads7846 overlay).
# Removes the ads7846 + tft-spidev0 overlays so /dev/spidev0.0 (display) and /dev/spidev0.1 (touch)
# both exist again. Run on the Pi:  sudo bash touch-userspace.sh && sudo reboot
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
CFG=/boot/firmware/config.txt

apt-get install -y python3-tk python3-numpy python3-spidev python3-evdev python3-xlib

if grep -qE '^dtoverlay=(ads7846|tft-spidev0)' "$CFG"; then
  cp "$CFG" "$CFG.bak-userspace"
  sed -i -E '/^dtoverlay=(ads7846|tft-spidev0)/d; /^# 3\.5" TFT touch/d' "$CFG"
  echo "removed ads7846/tft-spidev0 overlays from $CFG (backup: $CFG.bak-userspace)"
fi
grep -q '^dtparam=spi=on' "$CFG" || { echo "dtparam=spi=on" >> "$CFG"; echo "added dtparam=spi=on"; }

install -d /opt/tft
install -m 755 "$HERE/xpt2046.py" /opt/tft/xpt2046.py
install -m 755 "$HERE/inputd.py" /opt/tft/inputd.py
install -m 755 "$HERE/calibrate.py" /opt/tft/calibrate.py

cat > /usr/local/bin/tftcal <<'EOF'
#!/bin/sh
# usage: sudo tftcal   (tap the 4 crosses shown on the TFT)
systemctl stop tft-input
DISPLAY=:1 python3 /opt/tft/calibrate.py
systemctl start tft-input
EOF
chmod 755 /usr/local/bin/tftcal

echo "done. Reboot, then check: ls /dev/spidev*  (expect spidev0.0 and spidev0.1) ; then: sudo tftcal"

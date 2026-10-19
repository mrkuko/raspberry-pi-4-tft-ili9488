#!/bin/bash
# The ads7846 overlay disables spidev0 (CE0) as well as spidev1. The display driver (tftd.py) needs
# /dev/spidev0.0, so install a tiny overlay that re-enables spidev0 AFTER ads7846. Run on the Pi:
#   sudo bash fix-spidev.sh && sudo reboot
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
CFG=/boot/firmware/config.txt
OVDIR=/boot/firmware/overlays
WORK="$(mktemp -d)"

apt-get install -y device-tree-compiler

cat > "$WORK/tft-spidev0.dts" <<'EOF'
/dts-v1/;
/plugin/;

/ {
	compatible = "brcm,bcm2835";

	fragment@0 {
		target = <&spidev0>;
		__overlay__ {
			status = "okay";
		};
	};
};
EOF

dtc -@ -I dts -O dtb -o "$OVDIR/tft-spidev0.dtbo" "$WORK/tft-spidev0.dts"
rm -rf "$WORK"

if grep -q '^dtoverlay=tft-spidev0' "$CFG"; then
  echo "tft-spidev0 already in $CFG"
else
  cp "$CFG" "$CFG.bak-spidev"
  # must come after the ads7846 line so it overrides its "disabled"
  if grep -q '^dtoverlay=ads7846' "$CFG"; then
    sed -i '/^dtoverlay=ads7846/a dtoverlay=tft-spidev0' "$CFG"
  else
    printf '\ndtoverlay=tft-spidev0\n' >> "$CFG"
  fi
  echo "added overlay to $CFG (backup: $CFG.bak-spidev)"
fi

echo "done. Reboot, then check: ls /dev/spidev*   (expect /dev/spidev0.0)"

#!/bin/bash
# Make the kernel console (tty1) render into a 480x320 framebuffer so tftd can mirror it to the TFT.
# Installs a custom EDID (480x320 with enough blanking for the vc4 pixel clock limit) and points the
# Pi's HDMI-A-1 output at it via /boot/firmware/cmdline.txt. Run on the Pi:  sudo bash console-setup.sh
# Undo: sudo bash console-setup.sh --undo
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
CMD=/boot/firmware/cmdline.txt
EDID_DIR=/lib/firmware/edid
CONNECTOR="${CONNECTOR:-HDMI-A-1}"

strip_ours() {   # remove any earlier video=/drm.edid_firmware= for our connector (cmdline.txt must stay ONE line)
  sed -i -E "1s/ video=${CONNECTOR}:[^ ]*//g; 1s/ drm\.edid_firmware=${CONNECTOR}:[^ ]*//g" "$CMD"
}

if [ "${1:-}" = "--undo" ]; then
  strip_ours
  echo "removed the console EDID options from $CMD; reboot to apply"
  cat "$CMD"
  exit 0
fi

[ -f "$HERE/480x320.bin" ] || python3 "$HERE/make_edid.py" "$HERE/480x320.bin"
if ! zcat /proc/config.gz 2>/dev/null | grep -q '^CONFIG_DRM_LOAD_EDID_FIRMWARE'; then
  echo "warning: kernel config does not show CONFIG_DRM_LOAD_EDID_FIRMWARE; drm.edid_firmware may be ignored"
fi

install -d "$EDID_DIR"
install -m 644 "$HERE/480x320.bin" "$EDID_DIR/480x320.bin"

cp "$CMD" "$CMD.bak-console"
strip_ours
# video=<connector>:D forces the output "connected" without a monitor; the EDID supplies the only mode
sed -i "1s|\$| video=${CONNECTOR}:D drm.edid_firmware=${CONNECTOR}:edid/480x320.bin|" "$CMD"

echo "backup: $CMD.bak-console"
echo "new cmdline (must be ONE line):"
cat "$CMD"
echo "now: sudo reboot, then check: cat /sys/class/graphics/fb0/virtual_size   (expect 480,320)"

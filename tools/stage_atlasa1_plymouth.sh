#!/usr/bin/env bash
# Stage branding into a rootfs. The caller rebuilds the selected kernel initrd.
set -euo pipefail
[[ $# == 1 ]] || { echo "Usage: $0 ROOTFS" >&2; exit 2; }
root=$(realpath -e "$1")
project=$(cd "$(dirname "$0")/.." && pwd)
src="$project/config/plymouth"
test -x "$root/usr/sbin/plymouthd"
test -r "$root/usr/lib/aarch64-linux-gnu/plymouth/script.so"
test -r "$root/usr/lib/aarch64-linux-gnu/plymouth/label-pango.so"
install -Dm644 "$src/atlasa1.plymouth" "$root/usr/share/plymouth/themes/atlasa1/atlasa1.plymouth"
install -Dm644 "$src/atlasa1.script" "$root/usr/share/plymouth/themes/atlasa1/atlasa1.script"
install -Dm755 "$src/start-atlasa1-plymouth" "$root/usr/lib/atlasa1/start-plymouth"
install -Dm755 "$src/init-premount" "$root/etc/initramfs-tools/scripts/init-premount/atlasa1-plymouth"
install -Dm755 "$src/initramfs-hook" "$root/etc/initramfs-tools/hooks/atlasa1-plymouth"
install -Dm644 "$src/50-atlasa1.conf" "$root/etc/systemd/system/plymouth-start.service.d/50-atlasa1.conf"
install -d "$root/etc/plymouth"
printf '%s\n' '[Daemon]' 'Theme=atlasa1' 'ShowDelay=0' 'DeviceTimeout=5' > "$root/etc/plymouth/plymouthd.conf"
printf 'AtlasA1 boot branding enabled\n' > "$root/etc/plymouth/atlasa1-enabled"
update-alternatives --root "$root" --install /usr/share/plymouth/themes/default.plymouth \
    default.plymouth /usr/share/plymouth/themes/atlasa1/atlasa1.plymouth 200
update-alternatives --root "$root" --set default.plymouth \
    /usr/share/plymouth/themes/atlasa1/atlasa1.plymouth

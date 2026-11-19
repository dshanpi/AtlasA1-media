#!/usr/bin/env bash
# Install the GNOME profile into an installed or offline Ubuntu root filesystem.
set -euo pipefail
if [[ $# != 1 ]]; then
    echo "Usage: $0 ROOTFS" >&2
    exit 2
fi
root=$(realpath -e "$1")
project=$(cd "$(dirname "$0")/.." && pwd)
profile="$project/config/gnome-wayland"
test -x "$root/usr/bin/gnome-shell"
test -r "$root/opt/atlasa1-img-wayland/runtime-gles/libEGL.so.1"
install -Dm644 "$profile/61-atlasa1-gnome.rules" "$root/etc/udev/rules.d/61-atlasa1-gnome.rules"
install -Dm644 "$profile/50-atlasa1-wayland.conf" "$root/etc/systemd/user/org.gnome.Shell@.service.d/50-atlasa1-wayland.conf"
install -Dm755 "$profile/atlasa1-gnome-session" "$root/usr/local/bin/atlasa1-gnome-session"
install -Dm644 "$profile/atlasa1-gnome.desktop" "$root/usr/share/wayland-sessions/atlasa1-gnome.desktop"

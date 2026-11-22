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
install -Dm644 "$profile/60-atlasa1-greeter-display.conf" "$root/etc/systemd/user/org.gnome.Shell@gdm.service.d/60-atlasa1-greeter-display.conf"
install -Dm755 "$profile/atlasa1-gnome-session" "$root/usr/local/bin/atlasa1-gnome-session"
install -Dm644 "$profile/atlasa1-gnome.desktop" "$root/usr/share/wayland-sessions/atlasa1-gnome.desktop"
install -Dm644 "$profile/90-atlasa1-pvr" "$root/etc/chromium.d/90-atlasa1-pvr"
install -Dm755 "$profile/atlasa1-display-default" "$root/usr/local/libexec/atlasa1-display-default"
install -Dm644 "$profile/atlasa1-display-default.desktop" "$root/etc/xdg/autostart/atlasa1-display-default.desktop"
install -Dm644 "$profile/atlasa1-display-default.desktop" "$root/usr/share/gdm/greeter/autostart/atlasa1-display-default.desktop"

# Keep the package-owned helper upgradeable behind a narrowly scoped wrapper.
helper=/usr/libexec/mutter-x11-frames
real=$helper.atlasa1-real
test -x "$root$helper"
owner=$(dpkg-divert --root "$root" --listpackage "$helper")
if [[ -z $owner ]]; then
    dpkg-divert --root "$root" --local --add --rename --divert "$real" "$helper"
elif [[ $owner != LOCAL || $(dpkg-divert --root "$root" --truename "$helper") != "$real" ]]; then
    echo "Conflicting diversion for $helper" >&2
    exit 1
fi
test -x "$root$real"
install -Dm755 "$profile/atlasa1-mutter-x11-frames" "$root$helper"

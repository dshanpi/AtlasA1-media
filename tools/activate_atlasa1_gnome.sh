#!/usr/bin/env bash
# Select the installed AtlasA1 GNOME session for the next boot, without
# stopping the current desktop or enabling automatic login.
set -euo pipefail
if [[ $# != 2 || $EUID != 0 ]]; then
    echo "Usage: sudo bash $0 DESKTOP_USER NEW_BACKUP_DIRECTORY" >&2
    exit 2
fi
user=$1
[[ $user =~ ^[a-z_][a-z0-9_-]*$ ]]
id "$user" >/dev/null
test -x /usr/sbin/gdm3
test -x /usr/local/bin/atlasa1-gnome-session
test -r /usr/share/wayland-sessions/atlasa1-gnome.desktop
test -r /opt/atlasa1-img-wayland/runtime-gles/libEGL.so.1
test -r /usr/lib/systemd/system/gdm.service
account="var/lib/AccountsService/users/$user"
test -f "/$account"
backup=$(realpath -m "$2")
mkdir -m700 -- "$backup"
tar -cpf "$backup/desktop.tar" -C / \
    etc/systemd/system/display-manager.service etc/X11/default-display-manager \
    etc/gdm3/custom.conf "$account"
python3 - "$user" <<'PY'
import configparser
from pathlib import Path
import sys
path = Path('/var/lib/AccountsService/users') / sys.argv[1]
config = configparser.ConfigParser(interpolation=None)
config.optionxform = str
config.read(path)
if not config.has_section('User'):
    config.add_section('User')
config['User']['Session'] = 'atlasa1-gnome'
config['User']['XSession'] = 'atlasa1-gnome'
config['User']['SessionType'] = 'wayland'
with path.open('w') as stream:
    config.write(stream, space_around_delimiters=False)
PY
ln -sfn /usr/lib/systemd/system/gdm.service /etc/systemd/system/display-manager.service
printf '%s\n' /usr/sbin/gdm3 > /etc/X11/default-display-manager
systemctl daemon-reload
sync
printf 'GNOME selected for next boot. Desktop backup: %s/desktop.tar\n' "$backup"
printf 'Restore with: sudo tar -xpf %q/desktop.tar -C / && sudo systemctl daemon-reload\n' "$backup"

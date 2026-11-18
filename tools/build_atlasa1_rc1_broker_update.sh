#!/bin/bash
# Package the tested broker for installations of the published Ubuntu RC1.
set -euo pipefail
if [[ $# != 2 ]]; then echo "Usage: $0 BUILT_CEDAR_BROKER OUTPUT_DEB" >&2; exit 2; fi
broker=$(realpath -e "$1")
output=$(realpath -m "$2")
[[ ! -e $output ]]
printf '%s  %s\n' 2a2790b05dd55a7463e8b11f6eed165cb4f2d904906c5ae8957527054de04f98 "$broker" | sha256sum -c -
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
chmod 0755 "$stage"
install -d "$stage/DEBIAN" "$stage/usr/lib/atlasa1-cedar" "$stage/usr/lib/systemd/system/t736-cedar.service.d"
install -m 0755 "$broker" "$stage/usr/lib/atlasa1-cedar/cedar-broker"
cat > "$stage/DEBIAN/control" <<'CONTROL'
Package: atlasa1-cedar-format-switch
Version: 1.0-1~resolute1
Architecture: arm64
Maintainer: DshanPI AtlasA1 contributors
Depends: atlasa1-player (= 0.1-5~resolute1), systemd
Section: video
Priority: optional
Description: Cedar format switching for AtlasA1 Ubuntu 26.04 RC1
 Keeps up to two decoder formats available, including at most one UHD format.
 Only one decoder can be active at a time. Reboot after installing or removing.
CONTROL
printf '[Service]\nBindReadOnlyPaths=/usr/lib/atlasa1-cedar/cedar-broker:/opt/t736-cedar-transport-v2/bin/cedar-broker\n' \
    > "$stage/usr/lib/systemd/system/t736-cedar.service.d/atlasa1-formats.conf"
export SOURCE_DATE_EPOCH=1794960000
find "$stage" -exec touch --no-dereference --date="@$SOURCE_DATE_EPOCH" {} +
dpkg-deb --root-owner-group --build "$stage" "$output"
sha256sum "$output"

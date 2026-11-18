#!/usr/bin/env bash
# Run against a configured ARM64 rootfs, natively or using host binfmt/QEMU.
set -euo pipefail
root=$(realpath -e "${1:?expected configured rootfs directory}")
test -f "$root/usr/share/doc/atlasa1-board/media-sha256.json"
chroot "$root" /bin/sh -s <<'EOS'
set -eu
export LC_ALL=C
test "$(dpkg --print-architecture)" = arm64
test "$(id -u t736)" -ne 0
id -Gn t736 | tr ' ' '\n' | grep -qx t736
id t736-cedar
test -L /etc/systemd/system/sockets.target.wants/t736-cedar.socket
test "$(stat -c %U:%a /opt/atlasa1-player/bin/ffplay)" = root:755
test "$(modinfo -k 6.18.63-t736-media-v30 -F vermagic pvrsrvkm | cut -d' ' -f1)" = 6.18.63-t736-media-v30
scratch=$(mktemp -d /tmp/atlas-media-check.XXXXXXXX)
trap 'rm -rf -- "$scratch"' EXIT
export LD_LIBRARY_PATH=/opt/t736-cedar-browser-backend-v5:/opt/t736-cedar-wc-v5/lib
export GST_PLUGIN_PATH_1_0=/opt/t736-cedar-wc-v5/lib/gstreamer-1.0
export GST_OMX_CONFIG_DIR=/opt/t736-cedar-transport-v2/config
export GST_REGISTRY_1_0="$scratch/registry.bin" GST_REGISTRY_FORK=no
for file in /opt/t736-cedar-transport-v2/bin/cedar-broker "$GST_PLUGIN_PATH_1_0/libgstomx.so" \
            /opt/t736-cedar-wc-v5/lib/libOmxCore.so /opt/t736-cedar-wc-v5/lib/libOmxVdec.so; do
    ldd -r "$file" > "$scratch/ldd"
    if grep -E 'not found|undefined symbol' "$scratch/ldd"; then exit 1; fi
done
for factory in h264parse h265parse capsfilter appsrc appsink omxh264dec omxhevcvideodec; do
    gst-inspect-1.0 "$factory" > "$scratch/$factory"
    if [ "$factory" = omxh264dec ] || [ "$factory" = omxhevcvideodec ]; then
        grep -F "$GST_PLUGIN_PATH_1_0/libgstomx.so" "$scratch/$factory"
    fi
    printf 'Found %s\n' "$factory"
done
LD_LIBRARY_PATH=/opt/atlasa1-player/lib /opt/atlasa1-player/bin/ffplay -hide_banner -decoders > "$scratch/decoders"
grep -w h264_cedar "$scratch/decoders"
grep -w hevc_cedar "$scratch/decoders"
. /opt/t736-img-ddk-24.2-x11/session.env
LD_BIND_NOW=1 /usr/lib/xorg/Xorg -version
ldd -r /usr/lib/xorg/Xorg > "$scratch/xorg"
if grep -E 'not found|undefined symbol' "$scratch/xorg"; then exit 1; fi
EOS

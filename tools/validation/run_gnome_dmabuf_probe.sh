#!/usr/bin/env bash
# Root-only laboratory runner; not an application launcher or browser backend.
# Stops the decoder socket during the test and restores its listening state.
set -euo pipefail
[[ $# == 4 && $EUID == 0 ]] || { echo "Usage (root): $0 PROBE_DIR CLIP h264|hevc NEW_LOG" >&2; exit 2; }
# Multiple runs must not share the VE or restore the service under each other.
exec 9>/run/lock/atlasa1-gnome-dmabuf-probe.lock
flock -n 9 || { echo "Another DMA-BUF probe is running" >&2; exit 1; }
bin=$(realpath -e "$1"); clip=$(realpath -e "$2"); codec=$3; log=$(realpath -m "$4")
[[ $codec == h264 || $codec == hevc ]] || exit 2
test ! -e "$log"
test -x "$bin/cedar-gnome-dmabuf-player"
test -r "$bin/ffplay-wayland-present.so"
uid=$(id -u t736); test -S "/run/user/$uid/wayland-0"
test -r /opt/t736-cedar-transport-v2/config/cedarc.conf
test -f /etc/cedarc.conf
socket_active=$(systemctl is-active t736-cedar.socket || true)
service_active=$(systemctl is-active t736-cedar.service || true)
restore() {
    if [[ $socket_active == active ]]; then systemctl start t736-cedar.socket; fi
    if [[ $service_active == active ]]; then systemctl start t736-cedar.service; fi
}
trap restore EXIT
systemctl stop t736-cedar.socket t736-cedar.service
export LD_LIBRARY_PATH=/opt/t736-gst-parser-v27/usr/lib/aarch64-linux-gnu:/opt/t736-cedar-wc-v5/lib:/opt/atlasa1-img-wayland/runtime-gles
export LIBGL_DRIVERS_PATH=/opt/atlasa1-img-wayland/lib/dri
export GST_PLUGIN_SYSTEM_PATH_1_0=/opt/t736-gst-parser-v27/selected:/usr/lib/aarch64-linux-gnu/gstreamer-1.0
export GST_PLUGIN_PATH_1_0=/opt/t736-cedar-wc-v5/lib/gstreamer-1.0
export GST_OMX_CONFIG_DIR=/opt/t736-cedar-transport-v2/config
export GST_REGISTRY_1_0="$bin/gst-diagnostic-registry.bin" GST_REGISTRY_FORK=no
export XDG_RUNTIME_DIR="/run/user/$uid" WAYLAND_DISPLAY=wayland-0
unset GST_AW_OMX_DEFAULT_ARM_AFBC AW_AFBC_MODE
args=(); [[ $codec != hevc ]] || args+=(--hevc)
set -o noclobber
{
    uname -a
    sha256sum "$bin/cedar-gnome-dmabuf-player" "$bin/ffplay-wayland-present.so" "$clip"
    # Private mount namespace: the system's /etc/cedarc.conf stays unchanged.
    timeout 100 unshare --mount --propagation private bash -c '
        set -e
        mount --bind /opt/t736-cedar-transport-v2/config/cedarc.conf /etc/cedarc.conf
        exec env ATLAS_DMA_ASYNC=1 LD_PRELOAD="$1/ffplay-wayland-present.so" "$1/cedar-gnome-dmabuf-player" "${@:2}"
    ' bash "$bin" "$clip" "${args[@]}"
} > "$log" 2>&1

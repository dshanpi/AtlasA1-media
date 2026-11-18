#!/usr/bin/env bash
# Recreate the two deployable userspace inputs directly from a configured Tina SDK.
set -euo pipefail
tina=$(realpath -e "${1:?expected configured T736 Tina SDK}")
work=$(realpath -m "${2:?expected new output directory}")
tools=$(cd "$(dirname "$0")" && pwd)
patches="$tools/../patches/cedar"
mkdir -- "$work"
export SOURCE_DATE_EPOCH=1794960000 TZ=UTC
python3 "$tools/build_gpu_userspace.py" --tina "$tina" --work "$work/gpu" --without-gnome-x11
cp "$work/gpu/t736-img-userspace-candidate_24.2.6603887-2_arm64.deb" "$work/"
python3 "$tools/build_cedar_bridge.py" --tina "$tina" --work "$work/bridge"
python3 "$tools/build_cedar_wc_candidate.py" --tina "$tina" --work "$work/wc" --bridge "$work/bridge"
# Retain the WC allocator and vendor decoder set, then rebuild the GStreamer
# plugin using all four of the board changes in the same configured source tree.
for patch in gstomx-dmabuf-fd-ownership-20261117 gstomx-validated-output-crop \
             gstomx-broker-idle gstomx-broker-state-diagnostics; do
    patch --fuzz=0 --batch -d "$work/bridge/src" -p1 -i "$patches/$patch.patch"
done
sdk="$tina/out/t736/demo_aiot/buildroot/buildroot/host"
PATH="$sdk/bin:$PATH" "$sdk/bin/ninja" -C "$work/bridge/build" -j"${JOBS:-4}"
runtime="$work/t736-cedar-wc-v5"
mkdir "$runtime"
cp -a "$work/wc/t736-cedar-wc-v1/lib" "$runtime/"
install -m 0644 "$work/bridge/build/omx/libgstomx.so" "$runtime/lib/gstreamer-1.0/libgstomx.so"
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$SOURCE_DATE_EPOCH" \
    -C "$work" -cf - t736-cedar-wc-v5 | gzip -n > "$work/t736-cedar-wc-v5.tar.gz"
(cd "$work" && sha256sum *.deb t736-cedar-wc-v5.tar.gz > SHA256SUMS)

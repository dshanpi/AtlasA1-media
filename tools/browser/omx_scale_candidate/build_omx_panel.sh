#!/bin/bash
# Pass --service-only as the second argument when the player has its own FFmpeg build.
set -euo pipefail
browser=$(realpath "$1")
base=$2
if [[ $base != --service-only ]]; then base=$(realpath "$base"); fi
mkdir "$3"
stage=$(realpath "$3")
mkdir -p "$stage/tree/tools/browser/shm_v2" "$stage/tree/tools/browser/copy_candidate" "$stage/tree/tests"
tree="$stage/tree/tools/browser"
cp "$browser"/{cedar_backend.c,cedar_backend.h,ffmpeg_cedar.c} "$tree/"
cp "$browser"/shm_v2/{cedar_client.c,cedar_client.h,cedar_broker.c,cedar_backend.h,cedar_shm.h,cedar_protocol.h} "$tree/shm_v2/"
cp "$browser/copy_candidate/cedar_parallel_copy.h" "$tree/copy_candidate/"
sed 's/^int main(void)$/static int run_baseline(void)/' "$browser/../../tests/test_cedar_shm_transport.c" \
    > "$stage/tree/tests/baseline.inc"
patch --fuzz=0 -d "$tree" -p1 < "$browser/omx_scale_candidate/omx-panel.patch"
patch --fuzz=0 -d "$tree" -p1 < "$browser/omx_scale_candidate/broker-two-formats.patch"
patch --fuzz=0 -d "$stage/tree" -p1 < "$browser/../../patches/cedar/backend-parallel-direct-slot.patch"
cp "$tree"/shm_v2/{cedar_client.c,cedar_client.h,cedar_protocol.h,cedar_shm.h} "$stage/"
cp "$tree/ffmpeg_cedar.c" "$stage/"
if [[ $base != --service-only ]]; then
    sh "$browser/panel_candidate/build_private.sh" "$base" "$stage"
fi

sdk=${T736_TINA_SDK:-/home/ubuntu/t736-aiot/tina/out/t736/demo_aiot/buildroot/buildroot/host}
sysroot="$sdk/aarch64-buildroot-linux-gnu/sysroot"
cross="$sdk/bin/aarch64-none-linux-gnu-gcc"
export PKG_CONFIG_SYSROOT_DIR="$sysroot"
export PKG_CONFIG_LIBDIR="$sysroot/usr/lib/pkgconfig:$sysroot/usr/share/pkgconfig"
read -r -a flags <<< "$("$sdk/bin/pkg-config" --cflags --libs gstreamer-app-1.0 gstreamer-video-1.0)"
ccflags=(-Werror -Wall -Wextra -std=c11 -pthread -O2)
"$cross" "${ccflags[@]}" -shared -fPIC "$tree/cedar_backend.c" "${flags[@]}" \
    -Wl,-z,relro,-z,now -o "$stage/libcedar_backend.so"
"$cross" "${ccflags[@]}" -fPIE -pie "$tree/shm_v2/cedar_broker.c" \
    -L"$stage" -lcedar_backend '-Wl,-rpath,$ORIGIN/../lib' "-Wl,-rpath-link,$sysroot/usr/lib" \
    -Wl,-z,relro,-z,now -o "$stage/cedar-broker"
cp "$browser/omx_scale_candidate/test_omx_panel.c" "$stage/tree/tests/test_omx_panel.c"
cc "${ccflags[@]}" -g -fsanitize=address,undefined -no-pie "$stage/tree/tests/test_omx_panel.c" -o "$stage/transport-host"
"$cross" "${ccflags[@]}" "$stage/tree/tests/test_omx_panel.c" -o "$stage/transport-arm"
"$stage/transport-host" > "$stage/transport-host.log" 2>&1
# Match the board's little cores; Armbian exports the older Cortex-A53 model.
QEMU_CPU=cortex-a55 qemu-aarch64-static -L "$sysroot" "$stage/transport-arm" > "$stage/transport-arm.log" 2>&1
tail -n1 "$stage"/transport-{host,arm}.log
cd "$stage"
sha256sum cedar-broker libcedar_backend.so
if [[ $base != --service-only ]]; then sha256sum libavcodec.so.61 libt736_cedar_client.so; fi

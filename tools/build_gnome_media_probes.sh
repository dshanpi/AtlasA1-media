#!/usr/bin/env bash
# Build isolated diagnostics, not a desktop package or a privileged launcher.
set -euo pipefail
if [[ $# != 4 ]]; then
    echo "Usage: $0 TINA_SOURCE TINA_SDK_HOST SDL_DEVELOPMENT_ROOT NEW_OUTPUT" >&2
    exit 2
fi
tina=$(realpath -e "$1"); sdk=$(realpath -e "$2"); sdl=$(realpath -e "$3")
out=$(realpath -m "$4"); mkdir -- "$out"
src=$(cd "$(dirname "$0")/validation" && pwd)
sysroot="$sdk/aarch64-buildroot-linux-gnu/sysroot"
gpu="$tina/platform/allwinner/display/libgpu/img-bxm/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu/wayland"
cc="$sdk/bin/aarch64-none-linux-gnu-gcc"
# The legacy Tina sysroot predates the DMA heap UAPI. Import diagnostics use
# the distribution cross compiler and its current Linux UAPI headers.
gpucc=${GPU_CC:-aarch64-linux-gnu-gcc}
export PKG_CONFIG_SYSROOT_DIR="$sysroot"
export PKG_CONFIG_LIBDIR="$sysroot/usr/lib/pkgconfig:$sysroot/usr/share/pkgconfig"
read -r -a gst <<< "$("$sdk/bin/pkg-config" --cflags --libs gstreamer-app-1.0 gstreamer-video-1.0 gstreamer-allocators-1.0)"
common=(-O2 -Wall -Wextra -Werror)
graphics=(-I"$gpu/include" -L"$gpu/usr/local/lib" -Wl,--allow-shlib-undefined -lGLESv2 -lEGL -ldl)
sdlflags=(-I"$sdl/usr/include/SDL2" -I"$sdl/usr/include/aarch64-linux-gnu" -L"$sdl/usr/lib/aarch64-linux-gnu" -lSDL2)
"$gpucc" "${common[@]}" "$src/cedar_gpu_import.c" "${graphics[@]}" -o "$out/cedar-gpu-import"
"$gpucc" "${common[@]}" -shared -fPIC "$src/cedar_gpu_import.c" "${graphics[@]}" -o "$out/libcedar_gpu_check.so"
"$cc" "${common[@]}" "$src/cedar_frame_export_probe.c" "${gst[@]}" -ldl -o "$out/cedar-frame-export-probe"
"$cc" "${common[@]}" "$src/cedar_gnome_dmabuf_player.c" "${gst[@]}" "${sdlflags[@]}" "${graphics[@]}" -o "$out/cedar-gnome-dmabuf-player"
xml="$sysroot/usr/share/wayland-protocols/stable/presentation-time/presentation-time.xml"
"$sdk/bin/wayland-scanner" client-header "$xml" "$out/presentation-time-client-protocol.h"
"$sdk/bin/wayland-scanner" private-code "$xml" "$out/presentation-time-protocol.c"
"$cc" "${common[@]}" -shared -fPIC -I"$out" -I"$sdl/usr/include/SDL2" -I"$sdl/usr/include/aarch64-linux-gnu" \
    "$src/ffplay_wayland_present.c" "$out/presentation-time-protocol.c" -lwayland-client -ldl -o "$out/ffplay-wayland-present.so"
"$cc" "${common[@]}" -shared -fPIC "$src/sdl_texture_ring.c" -ldl -o "$out/sdl-texture-ring.so"
for name in sdl_packed_yuv sdl_packed_yuv_planes; do
    "$cc" "${common[@]}" -shared -fPIC "$src/$name.c" "${graphics[@]}" -o "$out/$name.so"
done
cd "$out"
sha256sum cedar-* *.so > SHA256SUMS
cat SHA256SUMS

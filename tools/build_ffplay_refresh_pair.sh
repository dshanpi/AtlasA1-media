#!/bin/bash
# Build the baseline, refresh-only reference and native desktop player.
# The sysroot uses unpacked arm64 FFmpeg 7.1.5 and SDL2 2.32.4 runtime packages,
# plus libsdl2-dev for its architecture-specific configuration and headers.
set -euo pipefail
source=$(realpath "${1:?FFmpeg 7.1.5 source tree}")
sysroot=$(realpath "${2:?Debian arm64 library and SDL development sysroot}")
work=$(realpath -m "${3:?fresh output directory}")
patchdir=$(realpath "$(dirname "$0")/../patches/ffmpeg")
mkdir "$work"
mkdir -p "$work"/{config,objects,variant/fftools}
cd "$work/config"
cross=${CROSS_COMPILE:-aarch64-linux-gnu-}
"$source/configure" --enable-cross-compile --arch=aarch64 --target-os=linux --cross-prefix="$cross" \
    --disable-autodetect --disable-everything --disable-doc --disable-programs --enable-shared \
    --enable-avdevice --enable-avfilter --enable-network --disable-vulkan > configure.stdout
make libavutil/ffversion.h
cp "$source/fftools/ffplay.c" "$work/variant/fftools/"
(cd "$work/variant" && patch --fuzz=0 -p1 < "$patchdir/ffplay-refresh-budget.patch")
cd "$work"
cc="${cross}gcc"
flags=(-std=c17 -O2 -D_GNU_SOURCE -D_ISOC99_SOURCE -D_FILE_OFFSET_BITS=64 -I"$work/config" -I"$source"
       -I"$source/fftools" -I"$sysroot/usr/include/SDL2" -I"$sysroot/usr/include/aarch64-linux-gnu"
       -Wno-deprecated-declarations)
for unit in cmdutils opt_common ffplay_renderer ffplay; do
    "$cc" "${flags[@]}" -c "$source/fftools/$unit.c" -o "objects/$unit.o"
done
"$cc" "${flags[@]}" -c variant/fftools/ffplay.c -o objects/ffplay-fixed.o
(cd variant && patch --fuzz=0 -p1 < "$patchdir/ffplay-first-picture-audio.patch")
"$cc" "${flags[@]}" -c variant/fftools/ffplay.c -o objects/ffplay-start-sync.o
libs=(-L"$sysroot/usr/lib/aarch64-linux-gnu" -Wl,--allow-shlib-undefined -l:libavdevice.so.61
      -l:libavfilter.so.10 -l:libavformat.so.61 -l:libavcodec.so.61 -l:libswresample.so.5
      -l:libswscale.so.8 -l:libavutil.so.59 -l:libSDL2-2.0.so.0 -lm -pthread)
for mode in baseline fixed start-sync; do
    player=ffplay-$mode
    if [[ $mode == baseline ]]; then player=ffplay; fi
    "$cc" -Wl,-z,relro,-z,now -o "ffplay-$mode" "objects/$player.o" \
        objects/{cmdutils,opt_common,ffplay_renderer}.o "${libs[@]}"
done
sha256sum ffplay-baseline ffplay-fixed ffplay-start-sync > SHA256SUMS
cat SHA256SUMS

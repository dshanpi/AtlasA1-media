#!/bin/bash
# Cross-build the native AtlasA1 player without replacing Ubuntu's FFmpeg ABI.
set -euo pipefail
source_tree=$(realpath "${1:?clean FFmpeg 7.1.5 source tree}")
sdl_sysroot=$(realpath "${2:?ARM64 SDL2 ABI development sysroot}")
work=$(realpath -m "${3:?new build directory}")
tools=$(cd "$(dirname "$0")" && pwd)
mkdir "$work"
sh "$tools/player/prepare_panel_sources.sh" "$work/wrapper"
python3 "$work/wrapper/build_browser_ffmpeg.py" --source "$source_tree" --work "$work/ffmpeg" --prepare-only
src="$work/ffmpeg/src"
for patch_name in ffplay-refresh-budget ffplay-first-picture-audio; do
    patch --fuzz=0 -d "$src" -p1 < "$tools/../patches/ffmpeg/$patch_name.patch"
done
export PKG_CONFIG_SYSROOT_DIR="$sdl_sysroot"
export PKG_CONFIG_LIBDIR="$sdl_sysroot/usr/lib/aarch64-linux-gnu/pkgconfig"
cd "$work/ffmpeg/build"
"$src/configure" --prefix=/opt/atlasa1-player --arch=aarch64 --target-os=linux \
    --enable-cross-compile --cross-prefix=aarch64-linux-gnu- --pkg-config=pkg-config \
    --enable-shared --disable-static --enable-pic --disable-doc --disable-debug --disable-autodetect \
    --disable-network --disable-encoders --disable-muxers --disable-devices --disable-ffmpeg --disable-ffprobe \
    --enable-ffplay --enable-sdl2 --disable-postproc --disable-filters \
    --enable-filter=scale,format,aresample,aformat,volume,transpose,hflip,vflip,showinfo,crop,yadif \
    --enable-decoder=h264_cedar,hevc_cedar --extra-cflags="-I$sdl_sysroot/usr/include/aarch64-linux-gnu" \
    --extra-ldflags=-Wl,--allow-shlib-undefined
grep -q '^#define CONFIG_FFPLAY 1' config.h
make -j "${JOBS:-4}"
make install DESTDIR="$work/install"
prefix="$work/install/opt/atlasa1-player"
python3 "$tools/build_atlasa1_player.py" --ffplay "$prefix/bin/ffplay" \
    --avcodec "$prefix/lib/libavcodec.so.61" --avutil "$prefix/lib/libavutil.so.59" \
    --private-runtime "$prefix/lib" --output "$work/atlasa1-player_0.1-6~resolute1_arm64.deb"

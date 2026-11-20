#!/bin/bash
# Build the libavcodec.so.62 implementation selected by Ubuntu 26.04 Firefox.
set -euo pipefail
input=${1:?Pass --ubuntu-archive, a cached Ubuntu ffmpeg .dsc, or an extracted source tree}
work=$(realpath -m "${2:?Pass a new output directory}")
here=$(cd "$(dirname "$0")" && pwd)
test ! -e "$work"
mkdir -p "$work/build" "$work/lib" "$work/cedar/shm_v2"
if [[ $input == --ubuntu-archive || -f $input ]]; then
    dsc=ffmpeg_8.0.1-3ubuntu2.dsc
    if [[ $input == --ubuntu-archive ]]; then
        archive=https://archive.ubuntu.com/ubuntu/pool/universe/f/ffmpeg
        sources="$work/ubuntu-source"
        mkdir "$sources"
        while read -r digest file; do
            curl --fail --location --retry 3 --output "$sources/$file" "$archive/$file"
        done < "$here/firefox-resolute-source.sha256"
    else
        [[ $(basename -- "$input") == "$dsc" ]]
        sources=$(dirname "$(realpath -e "$input")")
    fi
    (cd "$sources" && sha256sum -c "$here/firefox-resolute-source.sha256")
    dpkg-source --no-check -x "$sources/$dsc" "$work/src"
else
    cp -a "$(realpath -e "$input")" "$work/src"
fi
source_tree="$work/src"
test "$(head -n1 "$source_tree/debian/changelog" | cut -d' ' -f2)" = '(7:8.0.1-3ubuntu2)'
cp "$here/ffmpeg_cedar.c" "$here/cedar_client.h" "$work/cedar/"
cp "$here/shm_v2/"{cedar_client.c,cedar_client.h,cedar_protocol.h,cedar_shm.h} "$work/cedar/shm_v2/"
patch --fuzz=0 -d "$work/cedar" -p3 < "$here/copy_candidate/firefox-dr1-output.patch"
case ${ATLAS_FIREFOX_PANEL_CANDIDATE:-0} in
    0) ;;
    1)
        patch --fuzz=0 -d "$work/cedar" -p2 < "$here/copy_candidate/firefox-panel-output.patch"
        patch --fuzz=0 -d "$work/cedar" -p1 < "$here/copy_candidate/firefox-panel-client.patch"
        ;;
    *) echo 'ATLAS_FIREFOX_PANEL_CANDIDATE must be 0 or 1' >&2; exit 2 ;;
esac
aarch64-linux-gnu-gcc -O2 -fPIC -shared -pthread -Wl,-z,relro,-z,now \
    -Wl,-soname,libt736_cedar_client.so -o "$work/lib/libt736_cedar_client.so" "$work/cedar/shm_v2/cedar_client.c"
cd "$work/src"
cp "$work/cedar/ffmpeg_cedar.c" "$work/cedar/shm_v2/"{cedar_client,cedar_protocol,cedar_shm}.h libavcodec/
python3 - <<'PY'
from pathlib import Path
p = Path('libavcodec/ffmpeg_cedar.c')
src = p.read_text()
# FFmpeg 8 removed the deprecated AVFrame.pkt_pos byte offset.
removed = '            frame->pkt_pos = s->timing[i].pos;\n'
assert src.count(removed) == 1
p.write_text(src.replace(removed, ''))
p = Path('libavcodec/allcodecs.c')
src = p.read_text()
for codec in ('h264', 'hevc'):
    anchor = f'extern const FFCodec ff_{codec}_decoder;'
    assert src.count(anchor) == 1
    src = src.replace(anchor, f'extern const FFCodec ff_{codec}_cedar_decoder;\n' + anchor)
p.write_text(src)
with Path('libavcodec/Makefile').open('a') as f:
    for codec in ('H264', 'HEVC'):
        f.write(f'\nOBJS-$(CONFIG_{codec}_CEDAR_DECODER) += ffmpeg_cedar.o\n')
PY
cd "$work/build"
"$work/src/configure" --arch=aarch64 --target-os=linux --enable-cross-compile \
    --cross-prefix=aarch64-linux-gnu- --enable-shared --disable-static --enable-pic \
    --disable-debug --disable-doc --disable-programs --disable-autodetect --disable-network \
    --disable-encoders --disable-muxers --disable-avformat --disable-avdevice --disable-avfilter \
    --disable-swscale --disable-swresample --enable-decoder=h264_cedar,hevc_cedar,h264,hevc \
    --enable-bsf=h264_mp4toannexb,hevc_mp4toannexb --extra-ldflags=-ldl
python3 - <<'PY'
from pathlib import Path
p = Path('libavcodec/codec_list.c')
src = p.read_text()
first = ''
for codec in ('h264', 'hevc'):
    entry = f'    &ff_{codec}_cedar_decoder,\n'
    assert src.count(entry) == 1
    src = src.replace(entry, '')
    first += entry
p.write_text(src.replace('{\n', '{\n' + first, 1))
PY
make -j"${JOBS:-6}" libavcodec/ffmpeg_cedar.o
make -j"${JOBS:-6}" libavcodec/libavcodec.so libavutil/libavutil.so
for name in libavcodec/libavcodec.so.62 libavutil/libavutil.so.60; do
    aarch64-linux-gnu-strip -o "$work/lib/${name##*/}" "${name%.*}"
done
package="$work/package"
install -Dm755 "$here/firefox-resolute" "$package/usr/bin/atlasa1-firefox"
install -Dm644 "$work/lib/libavcodec.so.62" "$package/opt/atlasa1-firefox/lib/libavcodec.so.62"
install -m644 "$work/lib/libt736_cedar_client.so" "$package/opt/atlasa1-firefox/lib/"
install -Dm644 "$source_tree/COPYING.LGPLv2.1" "$package/usr/share/doc/atlasa1-firefox-cedar/COPYING.LGPLv2.1"
install -m644 "$source_tree/debian/copyright" "$package/usr/share/doc/atlasa1-firefox-cedar/ffmpeg-copyright"
install -m644 "$here/firefox-resolute-copyright" "$package/usr/share/doc/atlasa1-firefox-cedar/copyright"
mkdir -p "$package/DEBIAN" "$package/usr/share/applications"
cat > "$package/DEBIAN/control" <<'EOF'
Package: atlasa1-firefox-cedar
Version: 8.0.1-1~resolute1
Architecture: arm64
Maintainer: AtlasA1 board project
Depends: firefox, libavutil60, libc6, atlasa1-player
Description: Cedar decoding for Firefox on the AtlasA1 Ubuntu 26.04 image
 An additional Firefox profile and a private libavcodec62 use the board's
 Cedar service for supported media in the sandboxed RDD process.
EOF
if [[ ${ATLAS_FIREFOX_PANEL_CANDIDATE:-0} == 1 ]]; then
    sed -i 's/^Version: .*/Version: 8.0.1-1~resolute1+panel1/' "$package/DEBIAN/control"
fi
cat > "$package/usr/share/applications/atlasa1-firefox.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Firefox (AtlasA1 Cedar)
Exec=atlasa1-firefox %U
Icon=firefox
Categories=Network;WebBrowser;
StartupNotify=true
EOF
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(dpkg-parsechangelog -l"$source_tree/debian/changelog" -STimestamp)}
dpkg-deb --root-owner-group -Zxz --build "$package" "$work/atlasa1-firefox-cedar_8.0.1-1.resolute1_arm64.deb"

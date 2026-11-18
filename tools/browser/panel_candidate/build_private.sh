#!/bin/sh
# Build against an ELBG-enabled AtlasA1 private FFmpeg 7.1.5 build directory.
# $1 = existing build directory; $2 = staging directory with patched sources.
set -eu
base=$(realpath "$1")
stage=$(realpath "$2")
test -f "$base/libavcodec/elbg.o"
test -f "$stage/cedar_client.c"
mkdir "$stage/build"
cp -a --reflink=auto "$base/." "$stage/build/"
cd "$stage/build"
make -n -W src/libavcodec/ffmpeg_cedar.c V=1 libavcodec/ffmpeg_cedar.o > "$stage/compile-command"
python3 - "$stage" <<'PY'
from pathlib import Path
import shlex
import subprocess
import sys

stage = Path(sys.argv[1])
source = 'src/libavcodec/ffmpeg_cedar.c'
command, = [shlex.split(line) for line in (stage / 'compile-command').read_text().splitlines()
            if line.endswith(' ' + source) and ' -c ' in line]
command[command.index(source)] = str(stage / 'ffmpeg_cedar.c')
command.insert(1, '-Isrc/libavcodec')
subprocess.run(command, check=True)
PY
make -j2 libavcodec/libavcodec.so.61 EXTRALIBS-avcodec='libavcodec/elbg.o -pthread -lm -latomic'
aarch64-linux-gnu-strip --strip-unneeded -o "$stage/libavcodec.so.61" libavcodec/libavcodec.so.61
cd "$stage"
aarch64-linux-gnu-gcc -std=gnu11 -O3 -Wall -Wextra -Werror -fPIC -shared -pthread \
    -Wl,-z,relro,-z,now -Wl,-soname,libt736_cedar_client.so \
    -o libt736_cedar_client.so cedar_client.c
sha256sum libavcodec.so.61 libt736_cedar_client.so

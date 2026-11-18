#!/bin/sh
# Make a private copy of the Cedar sources for the native player.
set -eu
browser=$(cd "$(dirname "$0")/../browser" && pwd)
mkdir -p "$1/shm_v2"
stage=$(cd "$1" && pwd)
cp "$browser/ffmpeg_cedar.c" "$stage/"
cp "$browser/shm_v2/cedar_client.h" "$browser/shm_v2/cedar_protocol.h" "$browser/shm_v2/cedar_shm.h" "$stage/shm_v2/"
cp "$browser/shm_v2/cedar_client.c" "$stage/shm_v2/"
sed -i 's/\r$//' "$stage/ffmpeg_cedar.c" "$stage"/shm_v2/*.[ch]
patch --fuzz=0 -d "$stage" -p1 < "$browser/panel_candidate/private-1080p-panel.patch"
cp "$browser/panel_candidate/cedar_panel.h" "$stage/shm_v2/"
cp "$stage/shm_v2/cedar_client.h" "$browser/build_browser_ffmpeg.py" "$stage/"

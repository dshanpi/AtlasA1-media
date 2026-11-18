# Native playback of 3840×2160 video on a 1920×1080 panel

This opt-in experiment leaves the broker on its existing protocol and opens the
Cedar session at 3840×2160. A native FFplay process targeting a 1080p panel
averages each 2×2 block in each decoded I420 plane directly from the broker's
ordinary shared memory into a private FFmpeg frame. Each delivery writes
3,110,400 bytes and SDL receives a 1920×1080 frame. The output retains the
original PTS, color range, colorspace and frame duration. This path includes a
copy and produces a 1080p display raster.

## Build

Run the following on the Linux cross-build host from the project's
`tools/browser` directory. Set `FFMPEG_BUILD` to an existing configured AtlasA1
FFmpeg 7.1.5 cross-build tree with the private decoder object and ELBG object.
The script uses a private copy and the same compiler options as that tree.

```sh
stage=$(mktemp -d)
mkdir "$stage/shm_v2"
cp ffmpeg_cedar.c "$stage/"
cp shm_v2/cedar_client.c shm_v2/cedar_client.h shm_v2/cedar_shm.h shm_v2/cedar_protocol.h "$stage/shm_v2/"
patch -d "$stage" -p1 < panel_candidate/private-1080p-panel.patch
cp "$stage"/shm_v2/* "$stage/"
cp panel_candidate/cedar_panel.h panel_candidate/test_panel*.c "$stage/"
sh panel_candidate/build_private.sh "$FFMPEG_BUILD" "$stage"
(
    cd "$stage"
    cc -O2 -fsanitize=address,undefined -o test-panel test_panel.c
    ./test-panel
    cc -O2 -fsanitize=address,undefined -pthread -o test-client test_panel_client.c
    ./test-client
    aarch64-linux-gnu-gcc -O3 -o test-panel-arm test_panel.c
    qemu-aarch64-static -L /usr/aarch64-linux-gnu ./test-panel-arm
    aarch64-linux-gnu-gcc -O3 -pthread -o test-client-arm test_panel_client.c
    qemu-aarch64-static -L /usr/aarch64-linux-gnu ./test-client-arm
)
```

## Board comparison

Put both candidate libraries into a separate directory. Run the installed
`/opt/atlasa1-player/bin/ffplay` as the desktop user with that directory
first in `LD_LIBRARY_PATH` and use the absolute candidate
`libt736_cedar_client.so` for `LD_PRELOAD`. Keep the launcher's normal
`T736_CEDAR_ENABLE=1` and `T736_CEDAR_NATIVE_PLAYER=1`, select a
1920×1080 panel or offscreen canvas, then set `T736_CEDAR_PANEL=1920x1080`.
Playback of a matching file logs
`T736_CEDAR_PROXY: decoded=3840x2160 display=1920x1080 i420-box2x2`.
The broker session log reports 3840×2160. FFmpeg's `showinfo` and the SDL
texture should report 1920×1080. Repeating the run with `T736_CEDAR_PANEL`
unset exercises the full-size path with the same libraries. Use the source
frame count, presented-frame count, presentation duration and drop counters
to compare the two runs.

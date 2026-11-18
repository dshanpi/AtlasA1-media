# FFplay cold-start audio timing

The opt-in `-wait_video_start` option holds decoded PCM until the first
filtered video frame enters FFplay's presentation queue. During this interval
the SDL callback emits silence, keeps the PCM queue intact and leaves the audio
clock unset. The wait expires after 2.5 seconds. Seeks, stream changes and video
open failure cancel it. The option applies to initially co-starting audio and
video in a seekable local MP4/Matroska file with audio as master clock.

## Build

Use an unmodified FFmpeg 7.1.5 source tree. The builder applies the refresh and
first-picture audio patches in its output directory and produces three
executables. The `ffplay-start-sync` executable contains both changes.

```sh
bash tools/build_ffplay_refresh_pair.sh "$FFMPEG_SOURCE" "$ARM64_SYSROOT" "$WORK/player"
aarch64-linux-gnu-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -fPIC -shared \
    -I"$FFMPEG_SOURCE" -I"$WORK/player/config" -I"$ARM64_SYSROOT/usr/include/SDL2" \
    -I"$ARM64_SYSROOT/usr/include/aarch64-linux-gnu" tools/validation/ffplay_start_sync_probe.c \
    -ldl -o "$WORK/ffplay-start-sync-probe.so"
```

## Reproduce the delayed first-frame comparison

Create a clip with co-starting tracks and sound from the first audio packet.

```sh
ffmpeg -v error -f lavfi -i testsrc2=size=160x90:rate=25 \
    -f lavfi -i sine=frequency=400:sample_rate=48000 -t 5 \
    -c:v libx264 -threads 1 -pix_fmt yuv420p -c:a aac av.mp4
```

On an arm64 rootfs running on hardware or under QEMU user emulation, run both
commands from the fixture directory. Point `PLAYER` at the candidate FFplay
binary and `PROBE` at the ARM64 preload library. FFplay uses a software video
decoder and dummy SDL devices in this control.

```sh
export SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=dummy SDL_RENDER_DRIVER=software
for mode in baseline gated; do
    args=()
    if [ "$mode" = gated ]; then args+=(-wait_video_start); fi
    LD_PRELOAD="$PROBE" FFPLAY_TEST_VIDEO_DELAY_MS=1500 "$PLAYER" \
        -hide_banner -loglevel verbose -autoexit -stats -sn -sync audio \
        -noframedrop -threads 1 -x 160 -y 90 "${args[@]}" -i "$PWD/av.mp4" \
        > "$mode.log" 2>&1
done
tr '\r' '\n' < gated.log | grep -E 'Waiting up|START_SYNC_PROBE'
```

The probe timestamps the first nonzero SDL PCM buffer and the first SDL
presentation containing a successfully copied video texture. Its optional
delay holds the first video filter result for a controlled period. On the
board, keep the fixture, native decoder, GPU renderer, affinity and audio
device identical across runs. Add the probe to the existing preload list.
For a natural cold-start measurement use a fresh board boot, verify that the
Cedar service has not opened an earlier decoder session, and use zero
injection delay.

The QEMU control with a 1500 ms delay measured sound 1606.688 ms before the
first SDL presentation with the default options. With the option enabled, sound
started 8.638 ms after the first presentation. These timestamps cover the SDL
callbacks. Physical HDMI and audio output latency require separate measurement.

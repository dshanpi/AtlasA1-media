# Firefox 160 on AtlasA1 Ubuntu 26.04

Firefox 160 loads `libavcodec.so.62`. The AtlasA1 Firefox package supplies the Cedar-enabled FFmpeg 8 library in `/opt/atlasa1-firefox/lib` and uses Ubuntu's `libavutil.so.60`. Its preconnected RDD client sends compressed packets to the system Cedar service and receives decoded image data. Firefox retains its RDD seccomp filter and `NoNewPrivs` setting. The package contains FFmpeg, the AtlasA1 client and the launcher. The licensed Cedar runtime comes with the RC1 board image.

## Install on RC1

```sh
sudo apt install ./atlasa1-firefox-cedar_8.0.1-1.resolute1_arm64.deb
atlasa1-firefox
```

Run the second command as the desktop user, or select **Firefox (AtlasA1 Cedar)** in the applications menu. The launcher keeps a persistent profile under `~/.mozilla/atlasa1-cedar`. For switching between 1080p H.264 and 4K HEVC, also install the `atlasa1-cedar-format-switch` add-on from the board release. [Release assets](https://github.com/dshanpi/AtlasA1-build/releases/tag/v2026.11.18-ubuntu26.04-rc1)

## Build the package

On an Ubuntu x86-64 build host with `gcc-aarch64-linux-gnu`, `binutils-aarch64-linux-gnu`, `make`, `patch`, `dpkg-dev`, `python3`, `curl` and `xz-utils`, run these commands from the AtlasA1-media checkout. Use a new output directory for each build.

```sh
bash tools/browser/build_firefox_resolute_ffmpeg.sh --ubuntu-archive out-firefox
```

The builder downloads four source files from the Ubuntu archive and checks their SHA-256 digests before extraction. For an offline build, place all four files in one directory and pass the path to `ffmpeg_8.0.1-3ubuntu2.dsc` in place of `--ubuntu-archive`. [Source digests](firefox-resolute-source.sha256)

The private FFmpeg build uses LGPL-2.1-or-later components. The Cedar client uses its upstream MIT license. The FFmpeg library has SONAME `libavcodec.so.62` and links to the distribution's `libavutil.so.60`, `libc` and `libm`.

A clean rebuild with the release build path produced a byte-identical `.deb` with SHA-256 `0e360b0c309f61a6b6562387026ea8bfe3fb7f3248672972dbc7c9781c1c29cb`. FFmpeg includes its absolute source directory in assertion strings, so a different output directory changes the package digest.

## Optional GNOME 1080p-panel candidate (not hardware-validated)

`ATLAS_FIREFOX_PANEL_CANDIDATE=1 bash tools/browser/build_firefox_resolute_ffmpeg.sh INPUT NEW_OUTPUT`
adds an experimental HEVC 3840×2160 to 1920×1080 Cedar output path, with package
version `8.0.1-1~resolute1+panel1`. The default build does not apply these patches.
Even in this candidate, scaling is disabled unless the RDD inherits
`T736_CEDAR_BROWSER_PANEL=1920x1080`. This is an explicit choice for a 1080p
display, not a full-resolution 4K mode or automatic monitor detection.

The authenticated RDD requests the existing broker's panel flag; no hardware
handle enters Firefox, and socket authentication, read-only SHM and the RDD
sandbox are preserved. The image allocator receives 1920×1080 buffers while
the original coded dimensions remain available. Firefox's source uses the
track display dimensions in `CreateFromImage`; runtime dimensions and pixels
still need verification. Software replay before the first delivered frame
restores the source dimensions. H.264 and other dimensions retain their existing
path. This candidate shares the native player's scaled HEVC context; it does
not fix retained DMA allocations or increase the context limit.

On 2026-11-20 the candidate compiled for ARM64, and applying the public patches
to the DR1 source reproduced the compiled sources byte for byte. The existing
incremental build tree was restored. Board transfer was interrupted when both
SSH and the MCP service disconnected, before installation or playback. Do not
claim frame rate, pixel correctness, seeking, or fallback acceptance yet.
Validation must explicitly pass `--decoded-size 1920 1080`; such a result is
labelled `hardware-scaled-to-1080p`, separately from original-size 4K.

## Playback measurement

The current launcher uses Firefox's global refresh clock on the AtlasA1 Wayland DDK. On GNOME/v42 at 1080p60, two controlled runs retained 59.93 and 59.41 fps, with 1/1209 and 12/1227 frames dropped; restoring the per-window Wayland clock retained 53.37 fps with 133/1203 drops. A fresh profile playing immediately after browser launch retained 53.04 fps. These are browser counters, not physical HDMI scanout acceptance, and zero-drop acceptance has not passed. [GNOME results and remaining limits](../../docs/GNOME_MEDIA.md)

For internal drop categories, add `--wayland --debug-media` to the validation command below. It starts a separate disposable profile and enables privileged diagnostic access only on that loopback test instance. It leaves the RDD sandbox enabled. `--warmup N` explicitly records an optional wait before playing; do not compare such a run with immediate startup without noting the difference.

Original-size HEVC 4K30 remains unverified on GNOME: a clean-boot hardware run retained 13.21 fps. The native player's scaled 4K context and the browser's original-size 4K context are different; the two retained slots can reject a switch with `ENOSPC`. Enlarging the slot count without fixing retained DMA allocations is not a solution. The native player's hardware scaling result is not a browser 4K result.

On the default eMMC release kernel `6.18.63-t736-media-v30`, a private 1920×1080 Xvfb server presented 685 of 1,097 frames over 18.273 seconds (37.49 fps), with 412 drops and 1,128 Cedar interrupts. The same test on temporary kernel `6.18.63-t736-hw-v34` presented 695 of 1,082 frames over 18.031 seconds (38.54 fps), with 387 drops and 1,081 interrupts. Add `--xvfb /usr/bin/Xvfb` to the test command to exercise that path on a system with Xvfb installed.

On the board, the Firefox 160 H.264 test used an isolated profile and the regular user. At 1920×1080, the 17.751-second headless measurement recorded 1,065 Cedar interrupts, 1,065 video frames and 550 browser drops. The browser retained 29.01 fps. The RDD mapped the private FFmpeg 8 codec, the Cedar client and the system FFmpeg 8 utility library. The same test using the stock browser or the FFmpeg 7 launcher recorded zero Cedar interrupts. Physical HDMI frame cadence requires separate measurement. [Board measurements](../../evidence/atlasa1-firefox160-ffmpeg8-20261118.json)

```sh
sudo python3 tools/validation/firefox_headless_playback.py /path/to/h264-1080p60.mp4 \
    --launcher /usr/bin/atlasa1-firefox --screen 1920 1080 --seconds 18 --output firefox-h264.json
```

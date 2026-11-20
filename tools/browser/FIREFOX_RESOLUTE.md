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

## Optional GNOME 1080p-panel candidate (hardware playback tested)

`ATLAS_FIREFOX_PANEL_CANDIDATE=1 bash tools/browser/build_firefox_resolute_ffmpeg.sh INPUT NEW_OUTPUT`
adds an experimental HEVC 3840×2160 to 1920×1080 Cedar output path, with package
version `8.0.1-1~resolute1+panel2`. The default build does not apply these patches.
The candidate package includes a read-only Mutter display query. At browser
launch it selects scaling only for GNOME Wayland with one physical monitor
running 1920×1080 at 59–61 Hz. Failed queries, X11, 4K outputs (including a
200% desktop scale), and multiple monitors keep the existing path. It never
changes the monitor mode. Restart Firefox after changing the display setup.
`T736_CEDAR_BROWSER_PANEL=0` explicitly disables scaling; `1920x1080` explicitly
requests it. The default non-candidate package installs no enable marker.
This is 4K source playback on a 1080p panel, not full-resolution 4K output.

The authenticated RDD requests the existing broker's panel flag; no hardware
handle enters Firefox, and socket authentication, read-only SHM and the RDD
sandbox are preserved. The image allocator receives 1920×1080 buffers while
the original coded dimensions remain available. Firefox's source uses the
track display dimensions in `CreateFromImage`; runtime `videoWidth/videoHeight`
remain 3840×2160 with 1920×1080 decoded buffers. Software replay before the first delivered frame
restores the source dimensions. H.264 and other dimensions retain their existing
path. This candidate shares the native player's scaled HEVC context; it does
not fix retained DMA allocations or increase the context limit.

On 2026-11-20 the candidate compiled for ARM64, and applying the public patches
to the DR1 source reproduced the compiled sources byte for byte. The existing
incremental build tree was restored. After the connection recovered, an isolated
candidate installation on GNOME/v42 produced 30.038, 30.011 and 29.963 fps with
zero browser drops across three approximately 20-second HEVC 4K30 windows.
The last run followed H.264 playback and reused the scaled HEVC context. A
backward seek to 5 seconds resumed hardware playback (71 frames, zero drops).
H.264 1080p60 retained original-size decoding and measured 59.817 fps with
3/1204 drops, so its strict zero-drop check remains unverified. RDD seccomp,
NoNewPrivs, PowerVR WebRender and hardware IRQs were checked.

The captured PNG has no obvious structural corruption. The fixture has no
matrix tag: Firefox uses BT709 while plain FFmpeg software conversion uses
BT601, so those RGB captures cannot serve as a colorimetric pass. Full-size
4K output, long playback, adaptive in-page switching and software fallback
remain unaccepted. A full clean build from digest-verified Ubuntu source
completed; its codec source matches the tested incremental build and the
client binary is identical. An approximately 90-second run retained 2693 frames
at 29.985 fps with zero drops in the measurement window (one startup drop
before the window), followed by a successful backward seek. A subsequent
H.264 regression retained 58.558 fps with 29/1196 drops; 1080p60 still fluctuates. A repeat through the installed launcher measured 59.977 fps with 1/1197 drops and a successful seek.

The clean libraries were repackaged with the display selector as `+panel2`
(SHA-256 `c9671d589ec91ee55f8a1a0060b6e31eaaabf8279a58625859910c7da206dfb5`)
and installed on the board. The previous package and runtime are preserved in
`/var/backups/atlasa1-firefox-before-panel2-20261120`; its `restore.sh` reinstalls
the previous package and wrapper. After the user power-cycled the board, the installed launcher automatically selected scaling again: 615 frames in 20.489 seconds, zero window drops, 30.016 fps, plus successful seek recovery. That fsynced JSON is archived. This candidate is not in a new Release image.
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

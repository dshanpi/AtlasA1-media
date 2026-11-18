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

## Playback measurement

On the default eMMC release kernel `6.18.63-t736-media-v30`, a private 1920×1080 Xvfb server presented 685 of 1,097 frames over 18.273 seconds (37.49 fps), with 412 drops and 1,128 Cedar interrupts. The same test on temporary kernel `6.18.63-t736-hw-v34` presented 695 of 1,082 frames over 18.031 seconds (38.54 fps), with 387 drops and 1,081 interrupts. Add `--xvfb /usr/bin/Xvfb` to the test command to exercise that path on a system with Xvfb installed.

On the board, the Firefox 160 H.264 test used an isolated profile and the regular user. At 1920×1080, the 17.751-second headless measurement recorded 1,065 Cedar interrupts, 1,065 video frames and 550 browser drops. The browser retained 29.01 fps. The RDD mapped the private FFmpeg 8 codec, the Cedar client and the system FFmpeg 8 utility library. The same test using the stock browser or the FFmpeg 7 launcher recorded zero Cedar interrupts. Physical HDMI frame cadence requires separate measurement. [Board measurements](../../evidence/atlasa1-firefox160-ffmpeg8-20261118.json)

```sh
sudo python3 tools/validation/firefox_headless_playback.py /path/to/h264-1080p60.mp4 \
    --launcher /usr/bin/atlasa1-firefox --screen 1920 1080 --seconds 18 --output firefox-h264.json
```

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
mkdir -p ffmpeg-source
cd ffmpeg-source
base=https://archive.ubuntu.com/ubuntu/pool/universe/f/ffmpeg
for file in ffmpeg_8.0.1-3ubuntu2.dsc ffmpeg_8.0.1.orig.tar.xz ffmpeg_8.0.1.orig.tar.xz.asc ffmpeg_8.0.1-3ubuntu2.debian.tar.xz; do
    curl -fLO "$base/$file"
done
sha256sum -c <<'SUMS'
70ac30ebbb7e89fc4ebc4438457fab7c1deea5b62986577bfb1c866fee72436e  ffmpeg_8.0.1-3ubuntu2.dsc
05ee0b03119b45c0bdb4df654b96802e909e0a752f72e4fe3794f487229e5a41  ffmpeg_8.0.1.orig.tar.xz
54ab4020bb4eb280444da74d7aabc282acf6e8500cf6feaefd9821373fa9e72c  ffmpeg_8.0.1.orig.tar.xz.asc
a32bd75677bca735105b04a0ebd190a3481e0d8c2fcacd7d9f17524e240ee879  ffmpeg_8.0.1-3ubuntu2.debian.tar.xz
SUMS
dpkg-source -x ffmpeg_8.0.1-3ubuntu2.dsc
cd ..
bash tools/browser/build_firefox_resolute_ffmpeg.sh ffmpeg-source/ffmpeg-8.0.1 out-firefox
```

The private FFmpeg build uses LGPL-2.1-or-later components. The Cedar client uses its upstream MIT license. The FFmpeg library has SONAME `libavcodec.so.62` and links to the distribution's `libavutil.so.60`, `libc` and `libm`.

## Playback measurement

An independent 1920×1080 Xvfb server on kernel `6.18.63-t736-hw-v34` presented 695 of 1,082 frames over 18.031 seconds (38.54 fps), with 387 dropped and 1,081 Cedar interrupts. Add `--xvfb /usr/bin/Xvfb` to the test command to exercise that path on a system with Xvfb installed.

On the board, the Firefox 160 H.264 test used an isolated profile and the regular user. At 1920×1080, the 17.751-second headless measurement recorded 1,065 Cedar interrupts, 1,065 video frames and 550 browser drops. The browser retained 29.01 fps. The RDD mapped the private FFmpeg 8 codec, the Cedar client and the system FFmpeg 8 utility library. The same test using the stock browser or the FFmpeg 7 launcher recorded zero Cedar interrupts. Physical HDMI frame cadence requires separate measurement. [Board measurements](../../evidence/atlasa1-firefox160-ffmpeg8-20261118.json)

```sh
sudo python3 tools/validation/firefox_headless_playback.py /path/to/h264-1080p60.mp4 \
    --launcher /usr/bin/atlasa1-firefox --screen 1920 1080 --seconds 18 --output firefox-h264.json
```

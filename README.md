# AtlasA1-media

Cedar/OMX/PVR media integration for AtlasA1 / T736. The Ubuntu 26.04 native player builds its FFmpeg 7.1.5 libraries in a private prefix and uses the system SDL2 ABI. The media overlay installs the matching Cedar service and PowerVR firmware. [Player builder](tools/build_atlasa1_resolute_player.sh) · [Overlay builder](tools/prepare_atlasa1_resolute_media.py) · [Ubuntu 26.04 build instructions](https://github.com/dshanpi/AtlasA1-build/blob/main/docs/UBUNTU_26_04.md)

For a complete image on a fresh host, use [AtlasA1-build/build.sh](https://github.com/dshanpi/AtlasA1-build/blob/main/docs/FRESH_HOST_BUILD.md). It automatically fetches the fixed public libraries and rebuilds this media integration; no private SDK path is required.

Earlier board measurements cover Cedar hardware decoding and the PowerVR GLES2 renderer. [Native player](tools/player/README.md) · [Playback measurements and display status](docs/PLAYBACK.md)

GNOME 50 / Wayland v47 完整镜像已发布，并于 2026-11-22 完成 eMMC 整盘写入、8 GiB SHA-256 回读和断电启动。PowerVR WebRender 与 Cedar 硬解已接通，但不能宣称浏览器 1080p60 或全链路零丢帧通过。主分支另修复首次显示配置与自动校时；已发布 RC1 镜像保持原始字节，安装后修复和实测限制见 [发行记录](https://github.com/dshanpi/AtlasA1-build/releases/tag/v2026.11.21-ubuntu26.04-gnome-v47-rc1)。

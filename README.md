# AtlasA1-media

Cedar/OMX/PVR media integration for AtlasA1 / T736. The Ubuntu 26.04 native player builds its FFmpeg 7.1.5 libraries in a private prefix and uses the system SDL2 ABI. The media overlay installs the matching Cedar service and PowerVR firmware. [Player builder](tools/build_atlasa1_resolute_player.sh) · [Overlay builder](tools/prepare_atlasa1_resolute_media.py) · [Ubuntu 26.04 build instructions](https://github.com/dshanpi/AtlasA1-build/blob/main/docs/UBUNTU_26_04.md)

Earlier board measurements cover Cedar hardware decoding and the PowerVR GLES2 renderer. [Native player](tools/player/README.md) · [Playback measurements and display status](docs/PLAYBACK.md)

GNOME 50 / Wayland 候选已接通 PowerVR 和 Firefox 硬件 WebRender，恢复八核调度后用户确认桌面可以正常使用。稳定 60fps 和 GNOME 冷启动镜像仍未验收，现有 Release 默认 Xfce。[候选构建、实测与限制](docs/GNOME_WAYLAND.md)

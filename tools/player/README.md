# AtlasA1 播放器

在 AtlasA1 GNOME 桌面安装 arm64 软件包后，从应用菜单选择本地文件，也可以在文件管理器中右键 MP4，选择「打开方式 → AtlasA1 播放器」。命令行支持带空格的路径。

```sh
sudo apt install ./atlasa1-player_0.1-6_arm64.deb
atlasa1-player "/home/t736/Videos/测试 1080p60.mp4"
```

播放器使用 SDL GLES2 和当前桌面会话的音频输出，保留晚到的视频帧。对于最高 3840×2160 的偶数宽高、逐行、8 位 4:2:0 H.264 或 HEVC，它会选择 Cedar 代理解码器。其他格式由发行版 FFmpeg 选择解码器。软件包提供一个可选的「打开方式」入口。

GNOME Wayland 使用独立的 `/opt/atlasa1-img-wayland` DDK，默认关闭 SDL renderer 的额外垂直同步等待，由 FFplay 调度媒体时钟。X11 仍使用原来的 X11 DDK。Ubuntu 26.04 包名为 `atlasa1-player_0.1-6~resolute1_arm64.deb`，包含私有 FFmpeg 7 运行库。

截至 2026-11-19，GNOME 下的 1080p60 / 4K30 实际显示仍有丢帧，当前声卡仍为 Dummy Output。播放器能解码和提交全部视频帧不代表实际显示和音频已通过。详细结果见 [GNOME 多媒体验收](../../docs/GNOME_MEDIA.md)。

对于音视频时间戳同时起始的本地 MP4、MOV 或 Matroska 文件，Cedar 播放器在首帧进入显示队列后开始消耗音频，最长等待 2.5 秒。这可避免冷启动时声音比画面提前。具有音画起始偏移的文件保留原来的时间安排。

播放 3840×2160 视频时，启动器读取当前桌面的物理输出模式。对于只启用一台 1920×1080 显示器的 T736，播放器首先请求 Cedar 硬件缩放。支持该模式的代理让 OMX 直接输出可见尺寸为 1920×1080 的帧，日志显示 `mode=omx-scale`。旧代理或已保留全尺寸 4K 上下文的代理使用原尺寸解码，客户端再将每个 I420 平面按 2×2 像素求平均，日志显示 `mode=shm-box`。两条路径都将 1080p 帧交给 PowerVR。若进程可以使用 CPU6 和 CPU7，播放器的线程在这两个大核上运行。4K 显示器、多显示器和无法读取显示模式时使用原尺寸帧。1080p 片源走原来的解码及调度路径，日志显示 `mode=source`。

图形和解码服务由板级镜像提供。播放器沿用当前用户的图形会话和视频代理权限。v30 实板测试使用 256 MiB Cedar 专用堆、并行写入输出帧的 direct-slot 后端、匹配的 OMX 配置及 PowerVR 用户态库。v29 默认启动项的堆上限是 128 MiB，全分辨率 4K HEVC 在该配置上没有产生硬件帧。两种内核所用的测试代理都只保留一个解码上下文，同一启动周期切换编码或分辨率可能退回软件解码。

## 构建

在 Linux 构建机上准备 FFmpeg 7.1.5 源码，以及含 Debian arm64 FFmpeg、SDL2 运行库和 SDL2 开发头文件的 sysroot。下面的命令先构建包含刷新和首帧音频同步补丁的 `ffplay-start-sync`，再构建和打包播放器专用的 Cedar 客户端和 FFmpeg 库。

```sh
private=$(mktemp -d)
bash tools/build_ffplay_refresh_pair.sh /src/ffmpeg-7.1.5 /src/debian-arm64-sysroot "$private/player"
sh tools/player/prepare_panel_sources.sh "$private/src"
python3 "$private/src/build_browser_ffmpeg.py" --source /src/ffmpeg-7.1.5 --work "$private/ffmpeg"
python3 tools/build_atlasa1_player.py \
  --ffplay "$private/player/ffplay-start-sync" \
  --avcodec "$private/ffmpeg/install/opt/t736-browser-ffmpeg/lib/libavcodec.so.61" \
  --avutil "$private/ffmpeg/install/opt/t736-browser-ffmpeg/lib/libavutil.so.59" \
  --output /tmp/atlasa1-player_0.1-6_arm64.deb
```

软件包依赖 Debian 13 的 FFmpeg 7.1 运行库，以及板级已经安装的 PowerVR 和 Cedar 服务。原生客户端核对监听端和共享帧的属主，播放器通过服务接收只读的普通内存帧。安装和卸载可通过系统包管理器完成。

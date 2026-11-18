# AtlasA1 播放器

在 AtlasA1 GNOME 桌面安装 arm64 软件包后，从应用菜单选择本地文件，也可以在文件管理器中右键 MP4，选择「打开方式 → AtlasA1 播放器」。命令行支持带空格的路径。

```sh
sudo apt install ./atlasa1-player_0.1-2_arm64.deb
atlasa1-player "/home/t736/Videos/测试 1080p60.mp4"
```

播放器使用 SDL GLES2 和当前桌面会话的音频输出，保留晚到的视频帧。对于最高 3840×2160 的偶数宽高、逐行、8 位 4:2:0 H.264 或 HEVC，它会选择 Cedar 代理解码器。其他格式由发行版 FFmpeg 选择解码器。软件包提供一个可选的「打开方式」入口。

播放 3840×2160 视频时，启动器读取当前桌面的物理输出模式。对于只启用一台 1920×1080 显示器的 T736，Cedar 解码原尺寸视频，客户端将每个 I420 平面按 2×2 像素求平均，再把 1920×1080 帧交给 PowerVR。若进程可以使用 CPU6 和 CPU7，播放器的线程在这两个大核上运行。4K 显示器、多显示器和无法读取显示模式时使用原尺寸帧。1080p 片源走原来的解码及调度路径。

图形和解码服务由板级镜像提供。播放器沿用当前用户的图形会话和视频代理权限。v30 实板测试使用 256 MiB Cedar 专用堆、并行写入输出帧的 direct-slot 后端、匹配的 OMX 配置及 PowerVR 用户态库。v29 默认启动项的堆上限是 128 MiB，全分辨率 4K HEVC 在该配置上没有产生硬件帧。两种内核所用的测试代理都只保留一个解码上下文，同一启动周期切换编码或分辨率可能退回软件解码。

## 构建

在 Linux 构建机使用 `tools/build_ffplay_refresh_pair.sh` 生成 `ffplay-fixed`。以下命令在临时目录中给播放器的 Cedar 客户端与解码器应用补丁，并从 FFmpeg 7.1.5 源码构建私有运行库。打包工具将四个运行文件放到 `/opt/atlasa1-player`。

```sh
private=$(mktemp -d)
sh tools/player/prepare_panel_sources.sh "$private/src"
python3 "$private/src/build_browser_ffmpeg.py" --source /src/ffmpeg-7.1.5 --work "$private/ffmpeg"
python3 tools/build_atlasa1_player.py \
  --ffplay /tmp/player-pair/ffplay-fixed \
  --avcodec "$private/ffmpeg/install/opt/t736-browser-ffmpeg/lib/libavcodec.so.61" \
  --avutil "$private/ffmpeg/install/opt/t736-browser-ffmpeg/lib/libavutil.so.59" \
  --output /tmp/atlasa1-player_0.1-2_arm64.deb
```

软件包依赖 Debian 13 的 FFmpeg 7.1 运行库，以及板级已经安装的 PowerVR 和 Cedar 服务。原生客户端核对监听端和共享帧的属主，播放器通过服务接收只读的普通内存帧。安装和卸载可通过系统包管理器完成。

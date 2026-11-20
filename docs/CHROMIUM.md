# AtlasA1 GNOME 下的 Chromium

2026-11-20 在 `6.18.63-t736-gnome-v45`、GNOME Wayland 和 Chromium
`156.0.8078.73-1xtradeb1.2604.1` 上确认：普通 Chromium 原先使用 llvmpipe
软件合成，H.264 使用 `FFmpegVideoDecoder` 软件解码。Firefox 的 Cedar 适配
不适用于该 Chromium 二进制，不能据 Firefox 结果宣布 Chromium 硬解通过。

## 已落地的 GPU 修复

`config/gnome-wayland/90-atlasa1-pvr` 由 Chromium 官方启动脚本加载。
仅在 Wayland 会话且厂家 GLES 库存在时，选择已验证的 PowerVR 库和
ANGLE GLES 后端，并指定 `/dev/dri/renderD128`。没有关闭浏览器/GPU 沙箱，
没有更改桌面分辨率、用户 profile 或系统 libEGL。

`tools/stage_atlasa1_gnome_wayland.sh ROOTFS` 会将配置装入
`ROOTFS/etc/chromium.d/90-atlasa1-pvr`。实板已经安装；**需退出所有 Chromium
进程后重新启动**，旧窗口不会因配置文件变化自动切换库。本次未关闭用户浏览器。
回退只需移走该配置文件，再完整重启 Chromium。

实测渲染器变为 `ANGLE (Imagination Technologies, PowerVR B-Series BXM-4-64,
OpenGL ES 3.2 build 24.2@6603887)`，GPU sandbox 为 true，GPU 进程崩溃次数为 0。
GPU 合成、光栅化和 WebGL 已启用。

| 同一 H.264 1080p60 片源 | 测量时间 | 总帧 / 丢帧 | 浏览器未丢弃帧计数 / 秒 |
| --- | --- | --- | --- |
| 原始 Chromium、llvmpipe | 18.486 s | 1003 / 544 | 24.83 |
| 独立 PowerVR 环境实验 | 18.445 s | 1095 / 86 | 54.70 |
| 安装正式启动配置后复测 | 18.061 s | 1049 / 146 | 50.00 |
| 安装配置后截图及运行中 GPU 复核 | 18.485 s | 1064 / 124 | 50.85 |

测试保留用户其他应用，负载未固定。这是有限时间的浏览器计数，不是 HDMI
物理呈现帧率；结果仍未达到 1080p60 验收要求。四次的 `kVideoDecoderName`
均为 `FFmpegVideoDecoder`，`kIsPlatformVideoDecoder=false`。

第四轮截图确认视频测试图案正常；播放结束再次读取的 GPU 信息仍为 PowerVR、
sandbox=true、processCrashCount=0，没有在播放中回落到 llvmpipe。

## 尚未接通的硬件解码

- 当前 Chromium 的 VA-API 初始化失败。`vainfo --display drm --device
  /dev/dri/renderD128` 查找 `pvr_drv_video.so` 失败；现有 PowerVR 图形库没有
  提供 Cedar VA-API 解码后端。板上没有可用的 V4L2 视频解码节点。
- `chrome://gpu` / CDP 的 `video_decode=enabled` 只是功能开关。实测支持的
  硬解配置为空、播放器使用软件解码，不能把开关当作通过。
- HEVC 4K30 样片被 `FFmpegDemuxer` 判为不支持的视频轨并跳过，音频仍播放。
  `videoWidth=0`、视频帧计数为 0。验证器 v2 已明确将这种情况标为
  `FAILED_NO_VIDEO`；v1 原始记录仅表示计数采集完毕，不是播放通过。
- 当前二进制没有动态链接可替换的 libavcodec/libavformat/libavutil，也没有
  独立 libffmpeg.so。不能直接套用 Firefox 的私有 FFmpeg 库。
- 对应 XtraDeb 源码包的 `debian/rules` 确认 arm64 同时构建了 VA-API 和
  V4L2 路径。缺的是与现有 Cedar 服务的适配，不是少一个启动参数。
- Tina 包含 `chromium-browser-gst_120.0.6099.224-6_arm64.deb`，其中有
  `VmxGstVideoDecoder` 和 OMX 入口；本轮没有找到相应浏览器 C++ 源码。
  未将其安装覆盖当前 Chromium，其厂家启动脚本的 `--no-sandbox` 也未采用。

下一阶段应在可重建的当前 Chromium 中接入独立 Cedar 解码服务，并保留
沙箱、原始压缩包回退、seek/flush、EOS、格式切换和视频帧生命周期约束。
另一方案是完整实现 Chromium 兼容的 VA-API/V4L2 适配，包括 surface、参考帧、
同步和缓冲导出；创建一个设备节点或伪造能力枚举不构成实现。
整编 Chromium 前需安排构建空间：本次构建机仅余 4.2 GiB，尚未启动整编。

## 复测

以 GNOME 桌面用户运行，需要 `python3-websocket`、`ffprobe`、当前 Wayland
会话和已知片源。验证器创建独立 profile，只在 loopback 提供该片源，保存
CDP 媒体事件和 GPU 信息，结束时只终止自己的测试进程组。

```sh
python3 tools/validation/chromium_playback.py \
  --fixture /path/to/h264-1080p60.mp4 \
  --output /tmp/chromium-h264-new-run.json --seconds 18
```

输出路径必须不存在，片源须比测量窗口长至少 5 秒。硬解验收还须补齐实际
Cedar 解码证据、视频轨和解码器选择、正确画面、丢帧、音画同步、拖动和切流。

原始记录在 `evidence/gnome-media-20261119/chromium-*-20261120.json`。
本次只更新候选源码、实板启动配置及测试记录，没有重新发布完整系统镜像。

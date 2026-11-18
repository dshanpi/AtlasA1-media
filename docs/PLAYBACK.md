# AtlasA1 播放与显示实测

## Ubuntu 26.04 的 Firefox 160

从 Release 下载 `atlasa1-firefox-cedar_8.0.1-1.resolute1_arm64.deb`，运行 `sudo apt install ./atlasa1-firefox-cedar_8.0.1-1.resolute1_arm64.deb` 后，普通用户可从应用菜单打开 **Firefox (AtlasA1 Cedar)**。也可以直接运行 `atlasa1-firefox`。它使用独立配置和与 Firefox 160 匹配的 FFmpeg 8 解码库。[安装与源码构建](../tools/browser/FIREFOX_RESOLUTE.md)

同一段 1080p60 H.264 已在 Firefox 沙箱中使用 Cedar 硬解。独立 X11 虚拟屏上的 18.03 秒内，Cedar 产生 1081 次中断，浏览器播放 1082 帧，其中呈现 695 帧、丢弃 387 帧，平均呈现 38.54 fps。Firefox headless 测得 29.01 fps。浏览器呈现仍未达到 60 fps，以上测试均未占用 HDMI 桌面。[实板帧数和 RDD 沙箱记录](../evidence/atlasa1-firefox160-ffmpeg8-20261118.json)

## Ubuntu 26.04 的本地播放器

RC1 的本地播放器版本为 `0.1-5~resolute1`。在整盘烧录后，H.264 1080p60 与 HEVC 4K30（硬件缩至 1080p）分别以 PowerVR 离屏提交了 1500 和 750 帧。原版服务只保留一种格式，播放上述 4K 后再开 1080p 会回退软件解码。[RC1 整盘实测](../evidence/atlasa1-ubuntu26-rc1-installed-validation-20261118.json)

更新后的 Cedar 服务最多保留两种解码配置，其中最多一种为 UHD。不同编码、尺寸或缩放模式会占用不同配置，硬件每次处理一个播放会话。在同一次启动中切换 HEVC 4K30 → H.264 1080p60 → HEVC 4K30，三段均使用硬件解码，累计 3000 次 VE 中断，全部帧提交至 PowerVR。两次切换后播放 25 秒片段分别耗时 25.63 秒和 25.53 秒，零丢帧。测试使用虚拟音频设备。[切流实板记录](../evidence/atlasa1-cedar-format-switch-20261118.json)

已有 RC1 可安装 `atlasa1-cedar-format-switch_1.0-1.resolute1_arm64.deb`，在下次开机时生效。卸载该包并重启可恢复镜像自带的服务。重新构建镜像会把修正编入 Cedar 服务。[更新包构建脚本](../tools/build_atlasa1_rc1_broker_update.sh)

## 早期开发镜像

板上已安装「AtlasA1 播放器」0.1-4，MP4 的默认应用为 `atlasa1-player.desktop`。双击本地 MP4 即可播放，也可以执行 `atlasa1-player "/path/to/video.mp4"`。以普通用户从正式入口播放 25 秒的 HEVC 4K30 + AAC 样片，启动器自动选择 1080p 和 CPU6–7，OMX 在解码时缩小画面。实测 750 次 VE 中断、播放器零丢帧、音画偏差 P95 为 32 ms，进程在 26.619 秒后正常退出。 [播放器使用与构建](../tools/player/README.md) · [软件包构建记录](../evidence/atlasa1-player-start-sync-package-20261118.json) · [正式入口实测](../evidence/media-v30-4k-omx-panel-20261118.json)

## 2026-11-18 实板结果

测试板临时启动 `6.18.63-t736-media-v30`，给 Cedar 专用堆配置 256 MiB，采用并行复制后端。桌面仍使用 1080p 显示模式。FFplay 用本地文件及独立的 PowerVR GLES2 离屏窗口测试，统计每次纹理更新后的 SDL 呈现。带音轨测试使用 SDL 虚拟音频设备。实体 HDMI 视频和扬声器播放仍待验收。 [4K 内存和解码记录](../evidence/media-v30-4k-browser-hardware-20261118.json) · [并行复制记录](../evidence/media-v30-4k-firefox-parallel-20261118.json)

| 路径 | 实测 | 结果 |
| --- | --- | --- |
| 原生 HEVC 1080p60 | 30 秒片源，修正播放器刷新等待后，两次分别在 29.952 秒和 29.961 秒内呈现全部 1800 帧。每次新增 1800 次 VE 中断，零丢帧。带 AAC 时音画偏差 P95 为 39 ms。 | 通过离屏实时播放。[记录](../evidence/media-v30-1080-playback-20261118.json) |
| HEVC 4K30 解码 | 25 秒片源，不渲染时用 21.335 秒解出全部 750 张 3840×2160 帧。 | 通过原尺寸解码。[记录](../evidence/media-v30-4k-native-playback-20261118.json) |
| 原生 HEVC 4K30，上传原尺寸纹理 | 两轮各呈现 750 帧，耗时 28.865 秒和 28.419 秒。另一次计时测得每帧纹理上传平均 30.183 ms。带 AAC 时音画偏差 P95 达 3.446 秒。 | 未达到实时播放。[记录](../evidence/media-v30-4k-native-playback-20261118.json) |
| 相同 4K30 片源，缩到 1080p | FFmpeg 常规缩放用 30.909 秒呈现 750 帧。读取共享内存时做 2×2 平均缩放，耗时 27.361 秒。两种方式的纹理上传平均 10.031 ms 和 9.969 ms。 | 仅缩小纹理仍低于 30 fps。[记录](../evidence/media-v30-4k-native-playback-20261118.json) |
| 原生 HEVC 4K30，缩到 1080p，播放器绑定两个 Cortex-A76 核心 | 两轮各呈现全部 750 帧，首帧到末帧分别为 24.951 秒和 24.948 秒。带 AAC 时为 25.025 秒，音画偏差 P95 为 33 ms。75 秒带 AAC 片源呈现全部 2250 帧，耗时 75.495 秒，2250 次 VE 中断，零丢帧，音画偏差 P95 为 38 ms。 | 通过 4K30 片源在 1080p 窗口的离屏实时播放。[记录](../evidence/media-v30-4k-native-playback-20261118.json) |
| 原生 HEVC 4K30，OMX 直接输出 1080p | 初次打开带 AAC 的 25 秒片源，音画偏差 P95 达 571 ms，进程耗时 28.081 秒。复用解码器后，25 秒和 75 秒的带音轨片源分别呈现 750 和 2250 帧，音画偏差 P95 为 36 和 35 ms。GPU 接收 1920×1080 图像。 | 首次启动的音画同步未通过，复用后通过。[记录](../evidence/media-v30-4k-omx-panel-20261118.json) |
| Firefox ESR，HEVC | 1080p60 测量窗口呈现 12/1207 帧。4K30 并行复制路径呈现 18/594 帧，把 CSS 视频框设为实际 1920×1080 后呈现 10/603 帧。 | 浏览器实时播放未通过。[1080p60](../evidence/media-v30-1080-playback-20261118.json) · [4K30](../evidence/media-v30-4k-firefox-parallel-20261118.json) · [1080p 视频框](../evidence/media-v30-4k-native-playback-20261118.json) |

为复现首帧延迟，另在已热的解码器上给第一帧人工增加 1500 ms 延迟。未启用等待时，首段 PCM 音频比首画面早 1603 ms，播放期间音画偏差 P95 为 514 ms。启用首帧等待后分别为 14 ms 和 32 ms。去掉人工延迟后分别为 15 ms 和 36 ms，三轮均完整呈现 750 帧。此前真实冷启动的 571 ms 偏差另记于上表。[板上时序对照](../evidence/media-v30-4k-omx-panel-20261118.json) · [探针及 QEMU 测试方法](../tools/validation/ffplay_start_sync.md)

同一份 HEVC 4K30 + AAC 文件循环 12 轮，11 次回到片头，300.479 秒内呈现全部 9000 帧。VE 中断增加 9000，零丢帧，音画偏差 P95 为 33 ms。呈现间隔 P95 为 38.015 ms，最长间隔 146.319 ms。播放前后及中间 12 次采样均为 36 个 DMA 对象，共 151,924,736 字节。[五分钟回放记录](../evidence/media-v30-4k-omx-panel-20261118.json)

画质对照取相同 4K HEVC 片源的前 60 帧，将 OMX 的 1080p 输出与 Debian 软件解码后做面积缩放的无损参考逐帧比较。全片段 PSNR 为 40.287 dB，平均 SSIM 为 0.991833。[对照记录](../evidence/media-v30-4k-omx-panel-20261118.json)

## 复测 4K 片源在 1080p 下的帧率

在使用上述 v30 服务配置、已启用支持 OMX 缩放的 Cedar 服务、已安装播放器 0.1-4 的板上，从本仓库根目录执行下列命令。选用 2 至 90 秒、含 AAC 音轨且声明视频帧数的本地 HEVC 3840×2160 MP4，替换 `clip` 路径。本次使用的源视频时长、帧数和 SHA-256 见实测记录。探针需要 root 读取内核和服务计数，FFplay 子进程以普通用户身份运行。 [探针源码](../tools/validation/ffplay_offscreen.py) · [实测记录](../evidence/media-v30-4k-native-playback-20261118.json)

```sh
clip="/path/to/hevc-4k30-aac.mp4"
run=$(mktemp -d)
chmod 755 "$run"
cc -O2 -shared -fPIC tools/validation/ffplay_present_trace.c -ldl -o "$run/present.so"
sudo taskset -c 6,7 python3 tools/validation/ffplay_offscreen.py "$clip" \
  --player /opt/atlasa1-player/bin/ffplay --ffmpeg-lib /opt/atlasa1-player/lib \
  --client-lib /opt/atlasa1-player/lib/libt736_cedar_client.so --renderer powervr \
  --present-trace "$run/present.so" --omx-fit --keep-frames --audio --wait-video-start \
  --output "$run/playback.json"
```

加上 `--loops 2` 可复测同一片源回到片头。正式安装的 0.1-4 实测两轮合计 1500 帧，零丢帧，首帧到末帧 49.984 秒，音画偏差 P95 为 29 ms。[复测记录](../evidence/media-v30-4k-omx-panel-20261118.json)

在仅支持原尺寸输出的旧服务上，将 `--omx-fit` 换成 `--native-fit` 可验证客户端的 2×2 缩放。0.1-2 使用该客户端缩放路径。[0.1-2 包记录](../evidence/atlasa1-player-panel-package-20261118.json) · [客户端缩放实测](../evidence/media-v30-4k-native-playback-20261118.json)

`checks.full_source_session` 校验 Cedar 接收的源尺寸，`player_filter_sizes` 记录播放器收到的图像尺寸。`sdl_present` 给出呈现帧数和首尾间隔，`wall_seconds` 包含进程启动和退出，`av_offset_p95_seconds` 为音画时钟绝对偏差的第 95 百分位数。

## 黑屏与重启

此前实板上 PVR 的内核模块索引为空，导致 GDM 无法加载已安装的驱动。修复索引后重启，驱动自动加载，出现 `/dev/dri/renderD128`。GDM 的空闲延时原为 300 秒，Xorg 的灭屏超时原为 600 秒，两处均已设为零。登录 GNOME 后每 30 秒读取显示状态，连续观察 450 秒，末次 X11 空闲时长为 636 秒。各次采样的 HDMI 均为 connected，内核 DPMS 和 Xorg 均报告 On。仍缺实体屏幕观察。 [v29 重启](../evidence/atlas-display-media-v29-reboot-20261118.json) · [登录后空闲测试](../evidence/media-v30-gnome-display-idle-20261118.json)

eMMC 默认启动 v29，其 Cedar 专用堆上限为 128 MiB。该配置下本次 4K 片源的输出缓冲分配失败。v30 的并行后端和本轮服务覆盖配置使用临时启动环境，驱动会将退役的 DMA 缓冲保留到重启。在同一启动周期切换编码或分辨率、超过本轮五分钟的稳定性、端到端零拷贝和编码仍待整条链路验收。 [v29 缓冲记录](../evidence/atlas-display-media-v29-reboot-20261118.json) · [v30 专用堆记录](../evidence/media-v30-heap-budget-build-20261118.json)

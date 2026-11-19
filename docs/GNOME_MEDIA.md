# GNOME / Wayland 多媒体验收（2026-11-19）

当前 Cedar 硬解、PowerVR 和 GNOME 50.1 已连通，但 **GNOME 下的 1080p60、浏览器高帧率、真实音频和硬件编码尚未通过完整验收**。不能把旧的 SDL 提交帧数当作 HDMI 实际显示帧数。

## 播放器修复

`atlasa1-player` 按 `WAYLAND_DISPLAY` 选择 `/opt/atlasa1-img-wayland`，X11 继续选择原有独立 DDK。Wayland 默认设置 `SDL_RENDER_VSYNC=0`，由 FFplay 的媒体时钟调度，避免额外同步等待。25 秒的 1080p60 测试片此前提交耗时 31.66 秒；关闭额外等待后约 24.93 秒，音画时钟偏差 p95 从 4.705 秒降到 0.033 秒。

这个修复消除了播放拖慢，尚未消除实际显示端的丢帧。未改变 GNOME Shell 的八核调度。

## 真实呈现测量

`tools/validation/ffplay_wayland_present.c` 是诊断 preload，针对每个新视频帧请求 `wp_presentation` 反馈。统计 requested、shown、discarded、硬件时间戳、长帧间隔；flags 使用所有反馈的交集。SDL 上传/提交耗时另行记录。该工具不随生产启动器预加载，也不声称端到端零拷贝已实现。

基线为 `6.18.63-t736-media-v30`、1080p HDMI、同一 H.264 1080p60 / HEVC 4K30 文件。原始结果见 [证据目录](../evidence/gnome-media-20261119)。

| 测试 | 结果 | 结论 |
| --- | --- | --- |
| 原生 1080p60 | 1500 次提交，1175 次显示反馈、325 次丢弃，约 47 fps | 未通过 |
| 播放器仅用 CPU6/7 | 1170 次显示反馈，约 46.9 fps | 没有改善，未用于 GNOME 调度 |
| 浏览器暂时暂停的对照 | 1164 次显示反馈，约 46.7 fps | 后台 Chromium 不是此项瓶颈的主要来源；测试后恢复 |
| 不解音频的对照 | 1163 次显示反馈，约 46.8 fps | 不是音频输出时钟单独造成 |
| 原生 4K30、OMX 缩到 1080p | 750 次提交，718 次显示反馈、32 次丢弃，约 28.8 fps | 未通过；不是 4K HDMI 输出验收 |
| Firefox Wayland 1080p60 | 约 20.25 秒，1216 帧中丢 681 帧，约 26.4 fps | 硬解及 RDD 沙箱已确认，显示性能未通过 |

浏览器测试使用临时 profile，不关闭用户浏览器。Firefox 的呈现计数与原生播放器的 Wayland 反馈分别记录，不能混为同一指标。

## 翻页与 GPU 时钟对照

v35 在 RCQ 完成之后才等待下一次 vblank，实际呈现降至约 27.5 fps，已拒绝。
v36 改为在提交前登记事件、由现有中断完成，并等翻页完成再清理旧缓冲。稳定播放时原生 1080p60 约 53.1 fps（1321/1500 帧）、时钟偏差 p95 26 ms；4K30 缩放播放约 29.1 fps（722/750 帧）。仍未达到验收要求。

v36 下改回 SDL vsync 会把 25 秒播放拖到约 28.6 秒；提高 Mutter KMS 优先级也更慢。两项均撤回。扩大播放器队列没有改善；其中第一次队列测试没有通过原生客户端身份检查并回退软件，不能当作硬件性能对照，随后使用诊断客户端重新确认硬件路径。

v37 将 GPU 从 400 MHz 调到 Tina 支持的 600 MHz，保留 900 mV 电压。修正设备树频率后，PVR 固件正常且无 HWR，但稳定 1080p60 仍约 53.0 fps，Firefox 约 28.5 fps，未带来明显收益。不将升频作为本轮默认修复。

Firefox v36 普通调度约 27.1 fps；只将临时测试 RDD 的线程放到 CPU6/7 后约 31.8 fps。测试退出后该设置随进程消失，未修改生产浏览器或 Shell 的调度。实板 CPU capacity 已正确为六个小核 430、两个大核 1024，不能将问题归因于缺失大小核容量描述。

候选补丁和可从源码准备阶段重建的入口见 [Linux 仓库候选说明](https://github.com/dshanpi/AtlasA1-linux/blob/main/patches/linux/gnome-media-20261119/README.md)。默认 Armbian 镜像构建入口没有采用这些实验补丁。

## 继续对照：调度、轮询与纹理上传

v38 增加动态抢占支持（默认仍为 none）后，在 Xorg 启动阶段出现内核 Oops，未进入性能验收。已保存串口与内核日志，并回退恢复 v36 的 GNOME。尚未查明该回归的具体根因，不能只凭相关性归咎于 PowerVR 或抢占实现。

v39 恢复原来的非抢占配置，仅保留可调 RCQ 轮询间隔；正常启动 GNOME，无该异常。相同 25 秒 H.264 1080p60 片源的稳定播放对照：

| 实验 | Wayland 实际呈现 | 决策 |
| --- | --- | --- |
| v39 默认 2000 µs 轮询 | 1308/1500，52.729 fps | 基线 |
| v39 100 µs 轮询 | 1317/1500，53.039 fps | 无明显改善，恢复 2000 µs |
| v36 三块 SDL YUV 纹理轮换 | 1326/1500，53.374 fps | 无明显改善，不默认启用 |
| v39 单纹理打包 I420 为 RGBA8 | 1331/1500，40.133 fps；播放拖至 33.14 秒 | 上传稍快但整体更慢，拒绝 |
| v39 三平面分别打包 RGBA8 | 1307/1500，52.721 fps | 无明显改善，不默认启用 |

RGBA 实验是固定 1920×1080、BT.709 limited 的诊断预加载库，不能用于任意分辨率/色彩/字幕组合。两个最终实验均通过三点 CPU/GPU 像素对照（误差 0）；首版在 Wayland 首个缓冲尚未完成全屏配置时读取屏外像素，校验失败，随后移到第十次绘制后校验。失败结果一并保留，不计入性能通过记录。完整 FFplay 日志现在与 JSON 分开保存。

当前 CPU 上传通常仍需约 7–8 ms/帧。源码另确认私有 Cedar heap 的 `attach` 只接受 VE 自身，拒绝 GPU；这是直接 DMA-BUF 共享的明确障碍，不能据此断言它是全部丢帧的唯一原因。v40 候选为外部设备使用各自的 `dma_map_sgtable`/`dma_unmap_sgtable`，保留 VE 原有 identity mapping。先用 RGB/NV12/NV21 合成帧验证 GPU 导入与像素，随后才能接实际解码帧及生命周期、同步协议；该内核改动本身不构成零拷贝播放器。

## v40：真实 DMA-BUF 到 GPU 的验证

实板对照已完成：v39 的 RGB/NV12/NV21 三种导入均返回 `EGL_BAD_ALLOC`；v40 三种导入均成功，四象限 RGB 回读误差为 0。

GStreamer OMX 的真实 H.264 输出为一个 `dmabuf` 类型的 `GstMemory`，格式 YV12，缓冲 1920×1088，裁剪为 1920×1080。直接用 `gst_dmabuf_memory_get_fd` 获取其 fd；不能用 MemAdapter 的虚拟地址表查询 GStreamer 另行映射的地址，首个查询实验失败记录已保留。

`cedar_frame_export_probe.c` 保持 `GstSample` 引用，由 GPU 导入同一个 fd，按真实 stride、plane offset 和 crop 采样。四点像素与 CPU 参考的最大误差为 1。GPU 读取结束前不释放样本，没有整帧 CPU 拷贝。

连续播放原型 `cedar_gnome_dmabuf_player.c` 已在 GNOME 下运行：

| 1080p60 原型 | 完整处理帧数 / 耗时 | Wayland 实际呈现 | 结果 |
| --- | --- | --- | --- |
| 每帧 glFinish 后释放样本 | 1500 / 25.006 秒 | 1279/1500，51.141 fps | 未通过 |
| 最多三个样本在途，EGL fence 完成后释放 | 1500 / 25.006 秒 | 1282/1500，51.261 fps | 未通过 |

干净启动后的 HEVC 4K30 异步原型：实际缓冲 3840×2176、可见画面 3840×2160，750 帧在 25.019 秒处理完；GPU 缩放到 1080p 桌面。实际呈现 743/750，29.734 fps，丢弃 7 帧，最大显示间隔 284.523 ms。仍未通过零丢帧验收，也不是 4K HDMI 输出或音画同步验收。

异步版 CPU 绘制提交均值约 0.592 ms，仍有显示丢帧；这证实消除 CPU 整帧拷贝没有单独解决 GNOME 的 60fps 问题。`wp_presentation` 使用真实 swap 前的显式 hook，未伪造 SDL 上传事件，flags 交集为 7。原型保持完整解码尺寸，图像合成/缩放仍由 GPU 执行，不宣称解码到 HDMI 扫描输出全程无拷贝。

这些是 **root 实验程序**，仅支持本轮 BT.709 limited YV12 片源；没有音频、字幕、浏览器对接或面向普通用户的权限模型，未装入正常播放器入口。运行脚本临时停止解码服务，在独立 mount namespace 使用专用 Cedar 配置，退出后恢复原服务/socket 状态；不改变设备权限。

构建入口：

```sh
bash tools/build_gnome_media_probes.sh /src/tina /src/tina/out/t736/demo_aiot/buildroot/buildroot/host /src/sdl-development-root /tmp/new-probes
sudo bash tools/validation/run_gnome_dmabuf_probe.sh /tmp/new-probes /path/to/h264-1080p60.mp4 h264 /tmp/new-playback.log
```

需要 Tina SDK 的 GStreamer 开发文件、SDL2 ARM64 开发根目录，以及系统 `aarch64-linux-gnu-gcc`（提供新版 DMA heap UAPI）。该公共诊断脚本已从源文件构建成功；内核公共候选脚本做过语法/补丁检查，尚未使用该新入口全新重建整棵内核。

最后重复 10 轮合成缓冲导入，RGB/NV12/NV21 共 30 项像素校验通过。实板当前为临时 v40 / GNOME，GPU 无 HWR 或其他故障，Shell 使用八核；测试程序均退出、解码 socket 已恢复、系统 Cedar 配置未被改写。默认启动别名仍为 v30，未发布新的 GNOME 镜像。

## 逐帧计时与 PRIME 扫描输出导入

诊断播放器支持 `ATLAS_DMA_TIMING=/path/to/new.tsv`，在内存中收集 CPU 阶段时间，播放结束后写入文件；不会每帧写磁盘。`summarize_dmabuf_timing.py` 可汇总分位数。呈现 tracer 另支持 `ATLAS_PRESENT_TIMING`，记录每个请求的显示/丢弃状态、刷新周期和序号；必须核对日志中的呈现时钟与请求时钟后才能比较跨列延迟。这些仍是诊断开关。

v40 的新一轮 1080p60 基线为 1284/1500 帧、51.326 fps。取帧（含旧 fence 等待）p95 约 0.60 ms，导入 p95 约 0.09 ms，绘制提交 p95 约 0.84 ms；trace + swap p95 约 12.70 ms、最长 217.02 ms。短时 strace 中合成器同步 ioctl 没有对应长阻塞，客户端有等待 Wayland socket 的长 ppoll。该跟踪会影响性能，不能作为验收数据。

`ATLAS_DMA_VSYNC=1 ATLAS_DMA_UNPACED=1` 对照保留 1496/1500 帧，但把 25 秒视频拖至 28.73 秒，实际呈现 52.08 fps。它只是诊断，默认仍按视频时间戳播放；不能将少丢帧、慢播放当作 60fps 成功。

显示驱动使用 `DRM_GEM_DMA_DRIVER_OPS_VMAP`，要求导入的每个 GPU 缓冲都支持 CPU vmap，而扫描输出只使用 DMA 地址。v41 改为标准 DMA PRIME 导入，保留连续地址检查及原生 dumb 缓冲 CPU 映射；导入缓冲释放已有空指针判断。实板 `Failed to vmap PRIME buffer` 错误消失，GPU 无 HWR，但暖机播放仍为 1289/1500、51.509 fps，因此不把它描述为性能问题已解决，也不宣称已实现直接扫描输出。

v42 进一步启用原有 DRM/DE 跟踪点，保持非抢占配置。构建时分别发现显示驱动和 PowerVR 的旧 `__assign_str(dst, src)` API，与 Linux 6.18 不兼容；候选补丁改为新 API 并成功构建。`run_gnome_display_trace.sh` 使用独立 trace instance，只在诊断播放期间记录，退出后关闭并删除 instance；同时保存各 CPU buffer 的 overrun 统计。默认镜像配方仍未启用上述候选。

## X11 窗口边框辅助进程的崩溃循环

v42 的 DRM 跟踪中，1326 次 RCQ 提交有 1324 次在下一次 vblank 收到翻页反馈；多数掉帧间隔是下一次提交本身晚到。进程跟踪进一步发现，GNOME 不断重启发生 SIGSEGV 的 `mutter-x11-frames`，约每 0.3 秒一次。短时暂停该辅助进程后，同一 DMA-BUF 播放从约 51 fps 提升至 1486/1500 帧、59.386 fps；测试结束即恢复进程。

仅设置 `GSK_RENDERER=cairo` 仍会崩溃。最终为这个辅助进程单独禁用 GTK GL/Vulkan，并清除其继承的厂家图形库路径，保持 Cairo 渲染。窗口边框辅助进程持续存活，诊断播放为 1489/1500 帧、59.504 fps；仍有 11 帧丢弃，不宣称零丢帧验收。GNOME Shell、应用和视频的 GPU 环境没有被全局清除。

`stage_atlasa1_gnome_wayland.sh` 通过本地 `dpkg-divert` 保留包管理的原始辅助程序，再安装单独的启动包装脚本；拒绝覆盖其他已有 diversion。更新软件包会更新被转移的原程序，重复执行安装入口保持同一 diversion。

此后首次正式播放器测试因多轮诊断累计耗尽 256 MiB Cedar heap 而回退软件（内核明确报告 quota exceeded），成绩无效。必须在干净启动后复测普通用户播放器和浏览器；不能拿 root DMA-BUF 原型的帧数替代它们的验收。

保留该修复再次临时冷启动 v42 后，普通用户播放结果如下。使用正式播放器的 `-wait_video_start -noframedrop` 行为，音频为 dummy 设备上的 AAC 时钟，屏幕仍为 1080p。

| 路径 | 解码/提交 | 实际呈现 | 验收边界 |
| --- | --- | --- | --- |
| 原生 H.264 1080p60 | 1500 帧，播放器丢帧 0，25.40 秒含启动 | 1468/1500，59.551 fps | 显示环节仍丢 32 帧；音视频时钟偏差 p95 39 ms |
| 原生 HEVC 4K30，OMX 缩到 1080p | 750 帧，播放器丢帧 0，26.70 秒含启动 | 747/750，呈现跨度 24.54 秒 | 仍丢 3 帧；不是原尺寸 4K HDMI 输出；时钟偏差 p95 38 ms |
| Firefox H.264 1080p60 | 硬解、RDD 沙箱和正常播放速度确认 | 19.54 秒中 1176 帧丢 407，保留约 39.35 fps | 浏览器 60fps 未通过 |
| Firefox 仅临时 RDD 使用 CPU6/7 | 硬解与沙箱确认 | 1204 帧丢 452，约 37.46 fps | 无收益；没有写入浏览器默认配置 |

4K 的 30.4 fps 数字来自呈现反馈跨度，包含初始追赶，不能解读成片源帧率改变或高于 30fps 的性能保证。正式播放器两个测试均被验证器标记为 `not_verified`，原因是显示环节仍有丢帧。辅助进程在重启后的 346 秒状态检查时仍为同一 PID，GPU 错误计数全为零，Shell 使用 CPU0–7。没有开启新的默认启动项或发布 GNOME 镜像。

## 音频与编码

当前 PipeWire 仅有 `Dummy Output`，内核没有 ALSA 声卡。AAC 解码和时钟推进不等于实际出声；新版验证器会单独记录 sink，并在只有虚拟设备时拒绝把会话音频标为通过。

HDMI 音频需要补齐 T736 I2S3、DMA、音频时钟/复位、ASoC 以及 HDMI codec 连接。Tina 板级参考为 `i2s3_plat@2535000`、DMA request 6、`sndhdmi`。显示驱动内已有音频配置函数，不等于内核声卡已注册。

编码器与解码器使用不同硬件资源。当前 `t736-cedar-wc` 只支持解码 mode 2/4；Tina 编码器位于 `ve2@1c10000`，使用 SPI48、VE_ENC 电源域和独立编码时钟。尚未创建编码器内核设备或执行真实编码，不能通过安装 `libvencoder.so` 宣称编码支持。

## 实验包安装教训

v35 候选初次安装时，顶层 `lib/` 目录替换了 Ubuntu 的 `/lib -> usr/lib` 链接，造成新程序无法执行。已从现有 v30 initramfs 的恢复 shell 还原链接、保留原目录，并重新验证 SSH、桌面和 PowerVR。此操作没有重刷磁盘镜像。

后续候选使用 `usr/lib/modules/<version>` 布局，先解包到独立暂存目录，再复制该版本的模块和 boot 文件。安装前后检查 `/lib` 仍为链接；不向系统根目录直接解包带顶层 `lib/` 的归档。实验期间默认启动别名保持指向 v30。

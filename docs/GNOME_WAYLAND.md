# AtlasA1 GNOME 50 / Wayland candidate

2026-11-22 更新：v47 GNOME 整盘镜像已发布，并完成 eMMC 写入、完整 8 GiB 回读和断电启动。首次显示默认值与自动校时的问题已在主分支和板上修复，原始 RC1 镜像未改写。浏览器 1080p60 空闲复测约 59.39 fps、丢 12 帧；4K HEVC 缩放至 1080p 约 29.92 fps、丢 1 帧，严格零丢帧仍未通过。[最新发行验收和安装后修复](https://github.com/dshanpi/AtlasA1-build/blob/main/docs/UBUNTU_26_04.md#2026-11-21-gnome-v47-构建)。以下为早期候选记录。

2026-11-20 补充：Chromium 原先仍使用 llvmpipe。现已单独修复其 PowerVR
ANGLE GLES 渲染选择；Cedar 视频硬解尚未接入，不能沿用 Firefox 的验收结论。
配置、实测丢帧和后端缺口见 [Chromium 记录](CHROMIUM.md)。

Ubuntu 26.04 的 GNOME/Wayland 已在实板接通 PowerVR。2026-11-19 用户确认：撤销继承到应用的 CPU 绑核限制后，桌面明显改善，可以正常使用。该配置仍是候选：浏览器动画和 HDMI 呈现尚未达到稳定 60 fps，现有 RC1/v34 Release 镜像仍默认 Xfce。

本轮测试为 Linux `6.18.63-t736-media-v30`、1920×1080@60、IMG DDK `24.2.6603887`、GNOME 50.1。未修改内核或烧写 eMMC。完整测量摘要见 [实板记录](../evidence/atlasa1-gnome-wayland-20261119.json)。

## 已验证的修复

- 从同版 Tina SDK 的 `img-bxm/.../wayland` 构建独立 `atlasa1-img-wayland` 包，放在 `/opt/atlasa1-img-wayland`。X11 包继续独立保留。系统 Wayland 库和 Vulkan loader 不被厂家版本覆盖。
- udev 将 sunxi-drm 显示设备指定为 Mutter primary。默认选中 PVR card1 时，跨设备 framebuffer 导入失败且呈现很慢。
- GNOME/GTK 使用 EGL/GLES，避免启动不受支持的 Vulkan/桌面 GL 路径。正常 D-Bus 启动的“设置”已确认加载 PVR。
- X11 窗口边框辅助进程 `mutter-x11-frames` 使用单独的 Cairo 环境，禁用它的 GTK GL/Vulkan 并清除厂家库路径。继承全局 GLES 环境会导致该进程反复段错误重启，拖慢视频呈现；此例外不改变 Shell、普通 GTK 应用或播放器的 GPU 环境。后续 v42 对照与实际帧数见 [GNOME 多媒体验收](GNOME_MEDIA.md)。
- `MUTTER_DEBUG_KMS_SCHEDULING_PRIORITY=normal` 禁用 Mutter 的 KMS deadline timer；当前 sunxi-drm 的 vblank 查询可能阻塞。该设置是此组合的用户态兼容配置，未宣称内核时序缺陷已修复。
- **不绑 CPU 核心。** 曾将 Shell 主线程固定到 CPU6/7，独立测试略快，但从 Shell 启动的 Chromium 继承了该 affinity，多个进程挤在两个核上。已从配置删除并在实板恢复八核调度。
- Firefox 原生 Wayland 原先混用厂商 EGL 与系统 `libGL` 函数入口，无法建立有效 GL 上下文。Firefox 专用的 `firefox-gles/libGL.so.1` 将查找导向配套 GLES，启动器同时选择 GLES context。这个目录只加入该浏览器进程的搜索路径，不能当作系统 OpenGL/GLX 实现使用。实测硬件 WebRender 与 `PowerVR B-Series BXM-4-64` 均已确认。

## 构建与安装候选

在已配置交叉工具链和 Tina SDK 的构建机运行：

```sh
python3 tools/build_gpu_userspace.py --tina /path/to/tina \
  --platform wayland --work /path/to/new-wayland-build
```

在 AtlasA1 Ubuntu 26.04 安装 `gnome-shell gnome-session gnome-control-center gdm3 nautilus rtkit at-spi2-core evolution-data-server`，然后安装生成的 `atlasa1-img-wayland_24.2.6603887-3_arm64.deb`。GPU 内核模块/固件仍须使用同版 DDK 的已验证组合。

在本工程根目录运行：

```sh
sudo bash tools/stage_atlasa1_gnome_wayland.sh /
sudo install -m755 tools/browser/firefox-resolute /usr/bin/atlasa1-firefox
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=drm
```

stage 脚本安装 GNOME 配置、会话入口及 X11 边框辅助进程的局部包装，不更改默认显示管理器。辅助进程通过 `dpkg-divert` 保留软件包原文件，拒绝覆盖其他 diversion；离线根文件系统和重复安装均已验证。通过 GDM 选择 **AtlasA1 GNOME**。测试切换前保存工作并保留 LightDM/Xfce 回退；不要把临时自动登录配置写入发行镜像。离线根文件系统可作为 stage 的参数。

用户偏好的不息屏配置应在目标桌面用户的会话中设置：

```sh
gsettings set org.gnome.desktop.session idle-delay 0
gsettings set org.gnome.desktop.screensaver lock-enabled false
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type nothing
```

## 测量与限制

`tools/validation/gnome_wayland_browser.py --output NEW.json` 必须以桌面用户运行；它使用临时 Firefox profile，验证实际 WebRender 渲染器，并测量页面动画回调。测试专用的系统访问只用于短生命周期的本机诊断实例，未加入生产启动器。

页面 `requestAnimationFrame` 回调率不等于 HDMI 呈现率。`tools/validation/wayland_present.c` 使用 `wp_presentation` 时间戳测量实际提交反馈，需用 `wayland-scanner` 生成稳定协议 `xdg-shell` 和 `presentation-time` 的 client header/private code，再链接 `EGL GLESv2 wayland-client wayland-egl`。每次测试运行约 12 秒，必须同时记录负载和长帧数。

恢复八核调度后，在另一个 Chromium 仍运行的情况下，Firefox 测试由约 22.43 提升至 38.05 回调/秒，启动监听时间由 7.01 降至 4.13 秒。这是同机前后对照，不是无负载的严格性能基准。最终原生呈现测试约 47.60 fps；之前较低负载、仅 Shell 主线程绑核时约 53–54 fps，后者配置已撤销。

Xwayland 的 `depth 30 ... Falling back to software` 日志来自单个像素格式的探测；不能据此断言整个 Xwayland 在软件渲染。浏览器 GPU 接通不等于视频硬解、零拷贝或 60fps 播放已通过。后续 GNOME 下的播放器、Firefox 硬解和实际呈现结果见 [GNOME 多媒体验收](GNOME_MEDIA.md)。

本轮保留当前可用的 GNOME 会话，并停用自动回退定时器，避免用户操作中突然切换桌面。保存的开机默认仍是 LightDM/Xfce；未发布新的 GNOME 镜像，也未对 GDM 正常登录和冷启动做完整验收。

## 2026-11-20 实板默认启动更新

完成 v42 浏览器缩放播放测试后，实板已选择 GDM 和 `atlasa1-gnome` 会话作为默认。正常断电上电进入 v42 的 Wayland 登录界面，随后一次性测试登录已进入用户 GNOME，并立即恢复 GDM 配置；之后用户手动重启并确认系统已启动。没有开启永久自动登录；旧 v30/LightDM 配置保留在 `/var/backups/atlasa1-gnome-default-20261120`。这不改变已有 Release 镜像。

安装并验证所需会话文件后，可以显式选择下次启动使用 GNOME：

```sh
sudo bash tools/activate_atlasa1_gnome.sh t736 /var/backups/atlasa1-before-gnome
```

该入口要求新的备份目录，保存显示管理器、GDM 和账户会话设置；不重启、不停止当前桌面、不修改内核启动别名，也不启用自动登录。需要另行确保已安装与 GPU 模块匹配并经过实板测试的内核。脚本输出桌面配置的恢复命令。

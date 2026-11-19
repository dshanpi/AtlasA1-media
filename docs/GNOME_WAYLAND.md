# AtlasA1 GNOME 50 / Wayland candidate

Ubuntu 26.04 的 GNOME/Wayland 已在实板接通 PowerVR。2026-11-19 用户确认：撤销继承到应用的 CPU 绑核限制后，桌面明显改善，可以正常使用。该配置仍是候选：浏览器动画和 HDMI 呈现尚未达到稳定 60 fps，现有 RC1/v34 Release 镜像仍默认 Xfce。

本轮测试为 Linux `6.18.63-t736-media-v30`、1920×1080@60、IMG DDK `24.2.6603887`、GNOME 50.1。未修改内核或烧写 eMMC。完整测量摘要见 [实板记录](../evidence/atlasa1-gnome-wayland-20261119.json)。

## 已验证的修复

- 从同版 Tina SDK 的 `img-bxm/.../wayland` 构建独立 `atlasa1-img-wayland` 包，放在 `/opt/atlasa1-img-wayland`。X11 包继续独立保留。系统 Wayland 库和 Vulkan loader 不被厂家版本覆盖。
- udev 将 sunxi-drm 显示设备指定为 Mutter primary。默认选中 PVR card1 时，跨设备 framebuffer 导入失败且呈现很慢。
- GNOME/GTK 使用 EGL/GLES，避免启动不受支持的 Vulkan/桌面 GL 路径。正常 D-Bus 启动的“设置”已确认加载 PVR。
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

stage 脚本只安装 GNOME 配置与会话入口，不更改默认显示管理器。通过 GDM 选择 **AtlasA1 GNOME**。测试切换前保存工作并保留 LightDM/Xfce 回退；不要把临时自动登录配置写入发行镜像。离线根文件系统可作为 stage 的参数。

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

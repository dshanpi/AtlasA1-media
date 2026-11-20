# Atlas A1 boot animation

The Ubuntu rootfs configuration installs Plymouth, its script renderer and the
Atlas A1 theme before generating the initramfs. The theme is source text: a dark
background, Atlas A1 / Armbian / Ubuntu branding and three animated activity dots.

This starts in the Linux initramfs. It does not provide a U-Boot HDMI logo before
Linux initializes the display. Serial diagnostics remain available. The helper
honours `nosplash`, `plymouth.enable=0` and rescue/emergency boot modes; the
`/etc/plymouth/atlasa1-enabled` marker explicitly opts in without changing the
source U-Boot's fixed command line. Password prompts mask the entered text.

To stage into an existing rootfs, install the dependencies and run:

```sh
bash tools/stage_atlasa1_plymouth.sh /path/to/rootfs
# Rebuild the selected kernel's initramfs in that rootfs, then regenerate the
# matching U-Boot uInitrd using the image builder's existing procedure.
```

On 2026-11-20 the installed v45 board displayed the theme during a real reboot
and handed the display to GDM. Two KMS captures at 2560x1440 differed only in
the activity-dot region (1252,751)-(1307,758), confirming animation. The temporary
capture service timed out after producing both frames; it was disabled and is
not part of this theme or the rootfs recipe. Subsequent cold boots without that
service reached GDM successfully. Boot latency and its root-wait fix are
documented below; these measurements exclude SPL/U-Boot time.

Captured frame SHA-256:

- `a834ed8fcdc51686360587c46782a10be980175b0def2c083d5bbe7bf1d062e3`
- `9facabdced4706006400fd65c93e67db908e09ab4342b1e3e2cf867e61d1bb4b`

Disable by removing the marker and the Atlas systemd drop-in, selecting the
previous `default.plymouth` alternative and restoring `plymouthd.conf`, then
rebuilding the initramfs/uInitrd. Keep a copy of the original boot artifacts
when changing an installed system. No kernel, DTB or SSD partition changes are
needed to install or remove this theme.

## Root-device wait fix (Ubuntu 26.04)

Ubuntu initramfs-tools-bin 0.151ubuntu1 accepts `PARTUUID=` for its initial
lookup, but `wait-for-root.c:matching_device()` does not match that form against
later udev events. On Atlas A1 the eMMC appeared at about 7.1 seconds, while
`wait-for-root PARTUUID=... 30` ran from 4.51 to 34.51 seconds and exited 1.
The shell fallback then found the partition immediately. Plymouth had finished
showing the splash at 4.42 seconds; it was not the 30-second blocker.

`config/initramfs/atlasa1-root-wait` preserves the distribution helper inside
the initramfs and installs a wrapper translating only `PARTUUID=...` to
`/dev/disk/by-partuuid/...`. The original helper already matches udev symlinks.
Timeouts, filesystem identification, fsck and the stable partition identity
are retained. The package-owned executable in the root filesystem is unchanged.
`configure_atlasa1_resolute.sh` installs the hook before building the initramfs.

The first fixed v45 cold boot mounted root at 7.466 seconds and reached
`graphical.target` in 24.196 seconds (kernel/initramfs 7.671, userspace 16.525),
down from 51.311 seconds. GDM, PowerVR and the Cedar socket were active, with
no failed systemd units. A second cold boot, after removing temporary diagnostic
hooks, reached the graphical target in 24.036 seconds (7.631 + 16.404).
Root mounted at 7.428 seconds; the Wayland greeter was active. The measurements
are in `evidence/boot-and-cleanup-20261120/`. These are systemd/kernel timings, not a stopwatch
measurement from application of board power to a usable logged-in desktop.

For an existing installation, install the wrapper as
`/usr/lib/atlasa1/wait-for-root` and the hook as
`/etc/initramfs-tools/hooks/atlasa1-root-wait`, both mode 0755, then rebuild the
selected initramfs and its uInitrd. To undo this fix, remove the hook and rebuild
both artifacts, or restore the matching backed-up boot artifacts.

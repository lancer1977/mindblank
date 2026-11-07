---
publish: true
title: Steam Stuttering and Split Lock Fix
mindblank: true
description: Stop system-wide stutter and input freezes caused by Steam triggering kernel split lock mitigation on Linux.
tags: [how-to, linux, steam, kernel, sysctl, performance]
---

# Steam Stuttering and Split Lock Fix

## Problem
A Linux desktop suffered periodic, severe stuttering and occasional unresponsiveness. The `journalctl` logs showed a "split lock storm" triggered by Steam.

Environment where this was observed: a Cinnamon desktop on a Debian/Ubuntu-family distribution (Linux Mint style, with `snapd` installed), a recent mainline kernel, a high-core-count CPU and a high-end GPU. The fix itself is kernel-level and applies to any distro with a kernel that exposes `kernel.split_lock_mitigate` (Linux 6.2 or newer).

### Symptoms
1. System-wide lag and stuttering (mouse and audio glitches).
2. Desktop environment (Cinnamon) becoming unresponsive.
3. Rapid USB controller resets (keyboard and mouse disconnecting).
4. A backlog of `uevents` in `snapd` and `udev`.

### Root cause
A Steam thread (`CHTTPClientThre`) performs unaligned memory accesses that cross cache lines, which triggers the kernel's split lock detection.

1. The sysctl `kernel.split_lock_mitigate` defaults to `1`.
2. With that setting the kernel deliberately penalizes and stalls processes that trigger split locks, to stop them from locking the whole memory bus.
3. Because Steam triggers them so often, the penalty makes the entire system stutter.

## Fix

### 1. Check the current value
```bash
cat /proc/sys/kernel/split_lock_mitigate
```
`1` means the mitigation (penalty) is active. `0` means it is off.

### 2. Temporary fix (lost on reboot)
```bash
sudo sysctl -w kernel.split_lock_mitigate=0
```

### 3. Permanent fix
`split_lock_mitigate` is a sysctl, not a kernel command-line parameter, so it does not belong in GRUB. Put it in a sysctl drop-in file instead:

```bash
echo 'kernel.split_lock_mitigate = 0' | sudo tee /etc/sysctl.d/99-split-lock.conf
sudo sysctl --system
```

Verify, and again after the next reboot:
```bash
cat /proc/sys/kernel/split_lock_mitigate
```
It should print `0`.

### Alternative: disable detection entirely
A different mechanism is the kernel command-line option `split_lock_detect=off`, which turns off split lock detection altogether (no log lines, no penalty). Add it to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub`, then regenerate the GRUB config for your distro:

| Distro family | Command |
| --- | --- |
| Debian, Ubuntu, Mint | `sudo update-grub` |
| Arch, Fedora (BIOS or UEFI paths vary) | `sudo grub-mkconfig -o /boot/grub/grub.cfg` (Fedora: `/boot/grub2/grub.cfg`) |

Then reboot. The sysctl approach above is the lighter option and is usually enough.

### 4. Optional Steam tweaks
These may reduce how often Steam triggers the problem. Menu names can differ between Steam client versions, so check your own client:

1. Under Settings, Interface: disable GPU accelerated rendering in web views.
2. Under Settings, Library: enable a low performance mode if your client offers one.

## Why this works
With mitigation off, the kernel still notes split locks but no longer throttles the offending process, so the system handles them with a minor performance cost instead of a total stall.

## Technical details
1. Log entry to look for: `x86/split lock detection: #DB: CHTTPClientThre/... took a bus_lock trap at address: ...`
2. High-core-count CPUs and high-throughput GPUs appear more sensitive to bus stalls.
3. Related failures: the stalls can cascade into `ecryptfs` decryption errors (EINTR) and USB controller timeouts.

Documented: 2026-04-12

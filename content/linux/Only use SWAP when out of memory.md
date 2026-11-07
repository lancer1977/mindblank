---
publish: true
title: Tune vm.swappiness so swap is used only under memory pressure
mindblank: true
description: Lower the Linux vm.swappiness value so the kernel keeps data in RAM and uses swap only when memory is nearly full.
type: note
status: active
area: linux
updated: 2026-02-20
tags:
  - how-to
  - linux
  - memory
  - work
  - work/unsorted
  - work/tech
  - work/tech-linux
  - status/active
  - area/linux
---

# Tune vm.swappiness so swap is used only under memory pressure

## Problem

By default Linux is willing to move idle pages out of RAM and into swap even when plenty of memory is free. You want RAM to be used first and swap to be a fallback when memory actually runs low.

## Fix

Set the kernel parameter `vm.swappiness` to a low value. The original note recommends `0`.

### 1. Check the current value

```sh
cat /proc/sys/vm/swappiness
```

The default on most distributions is `60`.

### 2. Set it temporarily

This takes effect immediately and lasts until the next reboot. The value `10` below is only an example of a lower setting.

```sh
sudo sysctl vm.swappiness=10
```

### 3. Set it permanently

Put the setting in a drop-in file under `/etc/sysctl.d/` so it is applied at boot. Using a drop-in avoids editing the main `/etc/sysctl.conf`.

```sh
echo 'vm.swappiness=0' | sudo tee /etc/sysctl.d/99-swappiness.conf
sudo sysctl --system
```

`sysctl --system` reloads all sysctl configuration files, so the new value applies now as well as at boot.

Confirm the result:

```sh
cat /proc/sys/vm/swappiness
free -h
```

The `Swap:` row of `free -h` shows how much swap is in use.

## Why

A low `vm.swappiness` makes the kernel prefer dropping file cache and keeping application memory in RAM. Swap is still used when memory pressure becomes high, which avoids out-of-memory kills.

Note that `0` does not fully disable swap on modern kernels. The kernel still swaps under severe memory pressure. To turn swap off completely, use `sudo swapoff -a` and remove the swap entries from `/etc/fstab`. That is a separate decision from tuning swappiness.

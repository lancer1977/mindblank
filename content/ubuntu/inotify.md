---
publish: true
type: note
status: active
area: tech
updated: 2026-11-07
mindblank: true
description: Raise the Linux inotify instance and watch limits persistently when an app fails with "user limit on the number of inotify instances has been reached".
tags:
  - how-to
  - linux
  - ubuntu
  - inotify
  - work
  - work/tech
  - work/tech-linux
  - status/active
  - area/tech
---

# inotify instance limit reached (Ubuntu)

## Problem

An application fails with an error like this:

```text
System.IO.IOException: The configured user limit (128) on the number of inotify instances has been reached, or the per-process limit on the number of open file descriptors has been reached.
```

inotify is the kernel API that applications use to watch files and directories for changes. Each user has two caps:

- `fs.inotify.max_user_instances`: how many inotify instances one user can open. The error above shows the default of 128.
- `fs.inotify.max_user_watches`: how many paths the user can watch in total.

Development tools that watch many files (.NET file watchers, IDEs, bundlers) hit these caps quickly.

## Check current values

```bash
sudo sysctl -a | grep inotify
```

## Temporary fix (lasts until reboot)

```bash
sudo sysctl -w fs.inotify.max_user_instances=512
sudo sysctl -w fs.inotify.max_user_watches=524288
```

## Permanent fix

Put the same settings in a drop-in file under `/etc/sysctl.d/` and reload:

```bash
sudo tee /etc/sysctl.d/99-inotify.conf > /dev/null <<'EOF'
fs.inotify.max_user_instances=512
fs.inotify.max_user_watches=524288
EOF
sudo sysctl --system
```

Verify the live values:

```bash
sysctl fs.inotify.max_user_instances fs.inotify.max_user_watches
```

## Why

- `max_user_instances=512` raises the per-user instance cap from the default of 128, so several watcher-based tools can run at once without hitting the error.
- `max_user_watches=524288` gives a large watch budget. Values in the hundreds are far too low for a real project tree. Watches only use kernel memory once they are added.
- A drop-in file in `/etc/sysctl.d/` keeps the change separate from the distribution-managed `/etc/sysctl.conf`. Persist the same two values you tested with the temporary fix, so the setting survives reboots.

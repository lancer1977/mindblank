---
publish: true
title: Linux Mint 22.3 Audio Distortion Fix
mindblank: true
description: Stop crackling or distorted audio on Linux Mint 22.3 caused by a Homebrew PulseAudio binary conflicting with the native PipeWire stack.
tags: [how-to, linux, audio, pipewire, homebrew]
---

# Linux Mint 22.3 Audio Distortion Fix

## Summary
- Symptom: crackling/distorted audio, intermittent audio instability.
- Confirmed cause in this case: Homebrew `pulseaudio` was being launched and conflicting with Mint's native PipeWire audio stack.
- Stable fix: unlink Homebrew `pulseaudio`/`jack` binaries and restart PipeWire services.

## Quick Fix
```bash
brew unlink pulseaudio jack
systemctl --user restart pipewire pipewire-pulse wireplumber
```

## Verify
```bash
which -a pulseaudio
systemctl --user --no-pager --plain is-active pipewire pipewire-pulse wireplumber
```

Expected:
- `pulseaudio` should not resolve to `/home/linuxbrew/.linuxbrew/bin/pulseaudio`
- all three services return `active`

## If Audio Issues Return
Run:
```bash
coredumpctl --no-pager --reverse | rg -i pulseaudio | sed -n '1,20p'
ps -eo pid,cmd | rg -i "pipewire|wireplumber|pulseaudio|jackd" | rg -v rg
```

If crashes point to Homebrew path, re-apply quick fix.

## What We Saw (2026-03-28)
- Crash source:
  - `/home/linuxbrew/.linuxbrew/Cellar/pulseaudio/17.0/bin/pulseaudio --start --log-target=syslog`
- Scope:
  - launched under Chromium app scope
- PipeWire services healthy after restart:
  - `pipewire`: active
  - `pipewire-pulse`: active
  - `wireplumber`: active

## Rollback (if needed)
```bash
brew link pulseaudio jack
```

## Notes
- Earlier workaround (`apt remove libjack-jackd2-0`) was broad and removed many multimedia packages.
- Prefer PATH-level isolation (`brew unlink`) over large package removals.

---
publish: true
title: Sunshine + Moonlight on a Steam Gaming Mode PC
mindblank: true
date: 2026-11-06
tags: [how-to, gaming, linux, remote-play, sunshine, moonlight]
description: Software-only remote mouse, keyboard and screen for a Linux box that boots into Steam Gaming Mode (gamescope), plus the two errors that block a fresh Sunshine install.
---

# Sunshine + Moonlight on a Steam Gaming Mode PC

**Goal:** control a living-room / rack gaming PC (mouse, keyboard, controller,
video, audio) from a laptop, without a hardware KVM.

**Setup:** CachyOS, AMD GPU, booting straight into Steam **Gaming Mode**
(`gamescope-session`). No desktop compositor is running.

## Why Sunshine and not VNC or lan-mouse

| Option | Gives you | Works under gamescope? |
| --- | --- | --- |
| **Sunshine → Moonlight** | Video, audio, mouse, keyboard, gamepad | ✅ Input goes through `/dev/uinput` virtual devices, capture through KMS |
| Steam Remote Play | Same | ✅ but the client side needs Steam |
| lan-mouse / Deskflow | Input only | ⚠️ gamescope has an EI socket, but support is hit or miss |
| VNC (`wayvnc`) | Video and input | ❌ needs a wlroots compositor |

## Host setup (the gaming PC)

1. Install Sunshine (`sunshine` package on Arch/CachyOS). It needs
   `cap_sys_admin` for KMS capture; the package sets that already.
2. Open the ports **to your LAN only**:
   ```sh
   sudo ufw allow from 192.168.0.0/24 to any port 47984,47989,47990,48010 proto tcp comment 'Sunshine LAN'
   sudo ufw allow from 192.168.0.0/24 to any port 47998:48000 proto udp comment 'Sunshine LAN'
   ```
3. Turn off the tray icon. **Gaming Mode has no system tray, and without this
   setting Sunshine exits right after it starts:**
   ```ini
   # ~/.config/sunshine/sunshine.conf
   system_tray = disabled
   ```
   The symptom is that the service goes `inactive (dead)` with exit code 0 and the log ends with
   `Main loop has exited` / `Couldn't accept incoming connections: Operation canceled`.
4. Start it with the session:
   ```sh
   systemctl --user enable --now sunshine
   ```
5. Check from another machine:
   ```sh
   curl -s http://gaming-pc:47989/serverinfo | grep -o '<state>[^<]*'
   # <state>SUNSHINE_SERVER_FREE
   ```

## First login: the "CSRF Protection Error"

When you open the web UI at `https://<ip>:47990` from another machine, the
first-run welcome page can fail with:

> CSRF Protection Error: The request was blocked by CSRF protection…

The web UI only trusts its own default address (localhost), so allow the address you actually use:

```ini
csrf_allowed_origins = https://192.168.0.50:47990,https://gaming-pc:47990
```

Restart (`systemctl --user restart sunshine`), reload the page, and create the
admin user. That redirect to `/welcome` means no admin user exists yet.

## Pairing

1. In Moonlight on the laptop, add or select the host. It shows a 4-digit PIN.
2. In the Sunshine web UI, go to **PIN** and enter it.
3. Pick **Desktop** or **Steam Big Picture**.

## Moonlight shortcuts worth memorising

| Action | Keys |
| --- | --- |
| Disconnect (leave the game running) | `Ctrl+Alt+Shift+Q`, or controller Start+Select+L1+R1 |
| Release / recapture mouse and keyboard | `Ctrl+Alt+Shift+Z` |
| Toggle fullscreen | `Ctrl+Alt+Shift+X` |
| Stats overlay | `Ctrl+Alt+Shift+S` |
| Quit the app on the host | right-click the app tile → **Quit** |

## Gotchas

1. `steam -shutdown` under gamescope gets respawned within about a second by
   `steam-launcher`, so don't expect Steam to stay closed.
2. AV1 encoding errors in the log (`Device does not support encoding av1`) are
   harmless on RDNA2. H.264/HEVC via Vulkan get picked instead.

Related: [[Battle.net on a Steam Gaming Mode PC]]

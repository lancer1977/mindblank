---
publish: true
title: Battle.net on a Steam Gaming Mode PC
mindblank: true
date: 2026-11-06
tags: [how-to, gaming, linux, proton, battle-net, warcraft]
description: Install Battle.net (for WoW and friends) with GE-Proton as a non-Steam game, so it launches from Steam Gaming Mode, without Lutris or a desktop session.
---

# Battle.net on a Steam Gaming Mode PC

**Problem:** the PC boots into Steam Gaming Mode (gamescope). Lutris and other
desktop installers can't reliably show a window there, and whatever you
install has to appear in the Steam library.

**Approach:** run the official installer once under Proton on a hidden virtual display,
then register the result as a non-Steam game that uses the **same Proton prefix**.

## 1. Install into a Proton prefix on a virtual display

```sh
D=~/Games/battlenet; mkdir -p $D && cd $D
curl -fLo Battle.net-Setup.exe 'https://downloader.battle.net/download/getInstaller?os=win&installer=Battle.net-Setup.exe'

Xvfb :77 -screen 0 1600x900x24 & export DISPLAY=:77
export STEAM_COMPAT_DATA_PATH=$D STEAM_COMPAT_CLIENT_INSTALL_PATH=~/.steam/steam
~/.steam/steam/compatibilitytools.d/GE-Proton11-7-x86_64/proton run \
  Battle.net-Setup.exe --lang=enUS --installpath="C:\\Program Files (x86)\\Battle.net"
```

When `pfx/drive_c/Program Files (x86)/Battle.net/Battle.net Launcher.exe`
exists, it's done. The login window renders blank on the virtual display,
which is expected because it has no GPU. Kill it with `wineserver -k`.

## 2. Add it to Steam as a non-Steam game

Steam overwrites `shortcuts.vdf` while it's running, and in Gaming Mode
`steam-launcher` **respawns Steam within about a second** of `steam -shutdown`.
The trick is to wait for the old PID to exit and write immediately:

```sh
OLD=$(pgrep -x steam); steam -shutdown &
while kill -0 $OLD 2>/dev/null; do sleep 0.2; done
python add_shortcut.py   # uses the `vdf` package
```

The script does three things:

1. Appends a shortcut with `Exe` set to the quoted `Battle.net Launcher.exe` path.
   Its `appid` is `crc32(exe + name) | 0x80000000`, stored signed.
2. Adds `CompatToolMapping["<appid>"] = {name: "GE-Proton11-7-x86_64"}` to
   `~/.steam/steam/config/config.vdf`.
3. Symlinks `steamapps/compatdata/<appid>` to `~/Games/battlenet`, so Steam
   reuses the prefix that already has Battle.net installed.

Back up both `.vdf` files first.

## 3. Verify

```sh
steam "steam://rungameid/$(( (APPID<<32) | 0x02000000 ))"
pgrep -af 'Battle.net.exe'
```

Then sign in on the TV and install WoW from inside Battle.net.

Related: [[Sunshine and Moonlight on a Steam Gaming Mode PC]]

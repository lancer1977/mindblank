---
publish: true
title: Mount Batocera ROM shares from a NAS at boot
mindblank: true
description: Batocera needs its ROM folders mounted from a NAS over SMB at every boot, which a start/stop service script handles.
type: note
status: active
area: emulation
updated: 2026-11-07
tags:
  - how-to
  - batocera
  - work
  - work/unsorted
  - work/tech
  - work/tech-emulation
  - status/active
  - area/emulation
---

# Mount Batocera ROM shares from a NAS at boot

## Problem

Batocera reads games from folders under `/userdata/roms/<system>`, but the ROMs live on a NAS. Without a mount, the emulators see empty folders after every reboot. The NAS shares have to be mounted over SMB (CIFS) each time the appliance boots, and unmounted cleanly at shutdown.

Two things make a naive boot script fail silently: the target folders may not exist yet, and `start` can run before the network is up, so every `mount` fails and nothing is mounted.

## Fix

Batocera runs executable scripts in `/userdata/system/services/` with `start` at boot and `stop` at shutdown. Save the script below as `/userdata/system/services/nas-mounts`, make it executable, and enable it:

```bash
chmod +x /userdata/system/services/nas-mounts
batocera-services enable nas-mounts
batocera-services list
```

If you prefer not to use a service, the same `start` and `stop` logic also works from `/userdata/system/custom.sh`, which Batocera calls with the same arguments.

The SMB password does not go in the script. The `credentials=` option points at a file on the appliance, `/userdata/system/.smbcredentials`, which holds the NAS username and password. Create it yourself and make it readable by root only:

```bash
chmod 600 /userdata/system/.smbcredentials
```

The script creates each mount point, waits up to about 60 seconds for the NAS to answer, then mounts one share per system folder. Shares that are already mounted are skipped.

```bash
#!/bin/bash
# Mount NAS ROM shares on boot, unmount them on shutdown.

NAS="<nas-ip>"
CREDS="/userdata/system/.smbcredentials"
OPTS="rw,credentials=${CREDS},vers=3.0"

# "<share folder on NAS>:<folder under /userdata/roms>"
SHARES="
xbox:xbox
3do:3do
mugen:mugen
tg16cd:pcenginecd
segacd:segacd
saturn:saturn
dreamcast:dreamcast
gamecube:gamecube
wii:wii
wiiu:wiiu
switch:switch
ps2:ps2
ps3:ps3
"

wait_for_nas() {
    for _ in $(seq 1 30); do
        ping -c 1 -W 2 "$NAS" >/dev/null 2>&1 && return 0
        sleep 2
    done
    return 1
}

case "$1" in
    start)
        if ! wait_for_nas; then
            echo "nas-mounts: $NAS not reachable, nothing mounted"
            exit 1
        fi
        for entry in $SHARES; do
            src="${entry%%:*}"
            dst="/userdata/roms/${entry##*:}"
            mkdir -p "$dst"
            mountpoint -q "$dst" && continue
            mount -t cifs -o "$OPTS" "//${NAS}/Emulation/roms/${src}" "$dst" \
                || echo "nas-mounts: failed to mount $src"
        done
        ;;
    stop)
        for entry in $SHARES; do
            dst="/userdata/roms/${entry##*:}"
            mountpoint -q "$dst" && umount "$dst"
        done
        ;;
    *)
        echo "Usage: $0 {start|stop}"
        ;;
esac

exit 0
```

## Why this shape

1. `mkdir -p` guarantees the mount point exists, so a fresh install or a wiped `roms` folder does not break the mount.
2. The ping loop gives the network and the NAS time to come up. Without it, `start` can run first and every mount fails with no visible error.
3. `stop` unmounts only the folders this script mounted. A blanket `umount -a -t cifs,nfs` would also drop any other CIFS or NFS mounts on the box.
4. `mountpoint -q` makes `start` safe to run twice.

## Adapting it

1. Replace `<nas-ip>` with the NAS address (IP address or hostname).
2. Change `Emulation/roms` in the `mount` line if your NAS share path differs.
3. Edit the `SHARES` list: one `nas-folder:batocera-folder` pair per line. Drop systems you do not have.
4. Create the credentials file at the path given in `CREDS`. It needs `username=` and `password=` lines. Do not put those values in the script or in notes.
5. Test without rebooting: `/userdata/system/services/nas-mounts start`, then `mount | grep cifs`.

---
publish: true
title: Add your user to the docker group on Bazzite
mindblank: true
description: Make the docker group exist in /etc/group and add your user to it on Bazzite (Fedora Atomic), so docker runs without sudo.
type: note
status: active
area: infra
updated: 2026-11-07
tags:
  - how-to
  - docker
  - bazzite
  - work
  - work/tech-linux
  - status/active
  - area/infra
---

# Add your user to the docker group on Bazzite

## Problem

On Bazzite (and other Fedora Atomic images), the `docker` group is defined in `/usr/lib/group`, the image-managed group database, not in `/etc/group`. On a fresh install the group may be missing from `/etc/group`, so `sudo usermod -aG docker "$USER"` fails with `group 'docker' does not exist`.

## Fix

Copy the group entry from the image database into `/etc/group`, but only if it is not already there. The `grep -q` check makes the command safe to re-run. Then add your user to the group.

```bash
grep -q "^docker:" /etc/group || grep "^docker:" /usr/lib/group | sudo tee -a /etc/group > /dev/null
sudo usermod -aG docker "$USER"
```

Group membership is read at login, so a shell that was already open will not see the new group. Do one of the following:

- Log out and log back in (recommended, applies to every session).
- Run `newgrp docker` in the current terminal only. Other terminals still need a new login.

Verify that the group is active and that docker runs without sudo:

```bash
id -nG | tr ' ' '\n' | grep -qx docker && echo "docker group: ok"
docker ps
```

## Why

Membership in the `docker` group is root-equivalent, because any member can start a container that mounts the host filesystem. Only add accounts you trust.

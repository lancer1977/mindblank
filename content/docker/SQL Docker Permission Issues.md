---
publish: true
title: SQL Server Docker Permission Issues
mindblank: true
description: Fix a SQL Server container that fails to start or gets permission denied on a bind-mounted data directory by giving the container's UID ownership of that directory.
type: note
status: active
area: infra
updated: 2026-11-07
tags:
  - how-to
  - docker
  - sql-server
  - work
  - work/unsorted
  - work/tech
  - work/tech-docker
  - status/active
  - area/infra
---

# Problem

The SQL Server container fails to start, or its logs show permission denied errors when it writes to the bind-mounted data directory. The SQL Server image runs as the `mssql` user, UID 10001, GID 0. If the host directory is owned by your login user or by root, that user cannot write to it.

# Fix

Create the directories on the host, then give UID 10001 and GID 0 ownership. Choose a data root; `$HOME/servers` is used here as an example.

```bash
DATA_ROOT="$HOME/servers"
MSSQL_DIR="$DATA_ROOT/mssql"

# make the dirs
sudo mkdir -p "$MSSQL_DIR"/{data,log,backup,system}

# give the container user access (UID 10001, GID 0)
sudo chown -R 10001:0 "$MSSQL_DIR"/{data,log,backup,system}
sudo chmod -R 770 "$MSSQL_DIR"/{data,log,backup,system}
```

Then point the container's bind mounts at `$MSSQL_DIR/data`, `$MSSQL_DIR/log`, `$MSSQL_DIR/backup`, and `$MSSQL_DIR/system`.

# Why

The container process runs as UID 10001 and is not your host login user. Bind mounts keep the host's ownership, so the container can only write to the directories if UID 10001 owns them or has write permission through the group.

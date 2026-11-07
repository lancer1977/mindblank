---
publish: true
mindblank: true
description: Shorten long Windows paths by mapping a folder to a drive letter with the subst command.
type: solution
status: active
area: windows
updated: 2026-02-20
tags:
  - how-to
  - windows
  - subst
  - workaround
  - status/active
  - area/windows
title: Using subst to Shorten Paths
---

# Solution: Map a Folder to a Drive with `subst`

Problem: see [[01_problem_path_length]].

## Fix

Windows includes the `subst` command, which maps a folder to a drive letter. Once mapped, the drive letter acts as a short alias for the folder, so every path under it is shorter by the length of the original folder path.

## Example

Map the folder `D:\eCode` to the drive letter `E:`:

```bat
subst E: D:\eCode
```

After this, `E:\` behaves like the root of `D:\eCode`. A file at `D:\eCode\project\src\main.c` can be reached as `E:\project\src\main.c`, which is shorter and stays under the Windows path limit for tools that struggle with long paths.

`subst` mappings are per session. They disappear on reboot or sign-out. To make the mapping return automatically, see [[03_howto_persist_subst]].

To remove a mapping, run `subst E: /D`.

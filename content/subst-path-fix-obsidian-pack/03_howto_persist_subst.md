---
publish: true
type: howto
status: active
updated: 2026-02-20
title: Persisting subst Mappings
mindblank: true
description: 'Keep a subst drive mapping (for example E: to D:\eCode) in place across Windows reboots so long paths stay short.'
tags:
  - how-to
  - windows
  - subst
  - automation
---

# How-To: Persist a subst Drive Mapping

This is part 3 of the subst series. For the background on why a short drive letter helps and how to create the mapping, see [[02_solution_subst]].

## Problem
A `subst` mapping disappears at reboot, so the short drive letter has to be recreated by hand each session.

## Create the Mapping
```bat
subst E: D:\eCode
```

## Remove the Mapping
```bat
subst E: /d
```

## Fix: Persist Across Reboots

### Option A: Startup Script
Create a file such as `subst-ecode.cmd`:
```bat
@echo off
subst E: D:\eCode
```

Place it in the per-user Startup folder. Open it by pressing Win+R and running:
```
shell:startup
```

### Option B: Task Scheduler
Create a task that runs at logon. From a command prompt:
```bat
schtasks /Create /TN "SubstECode" /SC ONLOGON /TR "cmd.exe /c subst E: D:\eCode"
```

Or in the Task Scheduler GUI: Create Basic Task, set the trigger to "When I log on", the action to "Start a program", the program to `cmd.exe`, and the arguments to `/c subst E: D:\eCode`.

To remove the task later:
```bat
schtasks /Delete /TN "SubstECode" /F
```

## Why
`subst` mappings live only in the current logon session, so they must be recreated each time you sign in. Either option reruns the same command at logon.

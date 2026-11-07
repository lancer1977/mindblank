---
publish: true
type: problem
status: active
area: tooling
updated: 2026-02-20
mindblank: true
description: Explains why deep Windows directory trees cause build, git and watcher failures, and what limits cause them.
tags:
  - how-to
  - windows
  - filesystem
  - tooling
  - status/active
  - area/tooling
title: Path Length Issues on Windows
---

# Problem: Path Length Issues on Windows

Many Windows tools still struggle with very deep directory structures.

## Symptoms
- Build failures with vague file errors
- Git checkout or commit failures
- Node / Angular watcher instability
- Random "file not found" errors

## Root Cause
- Legacy MAX_PATH limits
- Tool-specific path handling bugs
- Deep nesting (node_modules, generated files, mono-repos)

## Next

Part 2 covers a workaround: mapping a short drive letter with Windows `subst` so tools see a shorter path. See [[02_solution_subst]].

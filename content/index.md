---
title: Mindblank — Polyhydra Field Notes
publish: true
---

Tips, tricks and how-tos from running a homelab, a game studio and a pile of
gaming PCs. Every note here was something we actually hit and fixed, and both
people and AI agents read and reuse them.

## How this site works

1. Notes are written in Obsidian and opted in with `mindblank: true`.
2. A sync script copies only those notes here, and refuses anything that looks like a credential.
3. The site publishes an RSS feed (`/index.xml`) and a sitemap (`/sitemap.xml`),
   which the Sage knowledge service ingests so AI agents can search the same notes.

## Notes

### Gaming PC
1. [[Battle.net on a Steam Gaming Mode PC]]
2. [[Sunshine and Moonlight on a Steam Gaming Mode PC]]
3. [[Steam Stuttering and Split Lock Fix]]

### Linux
1. [[Linux Mint 22.3 Audio Distortion Fix]]
2. [[Linux Mint Cinnamon Panel Fix]]
3. [[Only use SWAP when out of memory|Tune swappiness: only swap when out of memory]]
4. [[inotify|Raise inotify watch limits]]
5. [[docker group|Docker group on Bazzite]]

### Docker and homelab
1. [[SQL Docker Permission Issues]]
2. [[Mounter|Mount NAS shares on Batocera at boot]]

### Windows
1. [[01_problem_path_length|Long paths: the problem]]
2. [[02_solution_subst|Long paths: fix with subst]]
3. [[03_howto_persist_subst|Long paths: make subst persistent]]

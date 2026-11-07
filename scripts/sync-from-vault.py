#!/usr/bin/env python3
"""Mirror mindblank:true notes from an Obsidian vault into Quartz content/.

Only notes whose YAML frontmatter has `mindblank: true` leave the vault. The
vault's older `publish: true` flag (800+ legacy reference notes, some holding
credentials) is deliberately NOT the opt-in. Copies get `publish: true` added
so Quartz's ExplicitPublish filter accepts them. Each
candidate is scanned for credential-shaped strings and the whole sync aborts
if any are found, so a secret never reaches this public repo.

Usage: scripts/sync-from-vault.py [--vault ~/vaults/polyhydra] [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONTENT = REPO / "content"
KEEP = {"index.md"}  # owned by this repo, never overwritten or pruned
SKIP_DIRS = {".obsidian", ".git", ".trash", "node_modules", "90_Archive", "99_Scratch"}
ATTACH_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf"}

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
PUBLISH = re.compile(r"^mindblank:\s*(true|yes)\s*$", re.M | re.I)
QUARTZ_PUBLISH = re.compile(r"^publish:\s*true\s*$", re.M | re.I)
EMBED = re.compile(r"!\[\[([^\]|#]+)")
SECRET_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"\b(?:password|passwd|secret|api[_-]?key|token|client[_-]?secret)\s*[:=]\s*['\"]?[^\s'\"<>{}]{8,}",
        r"\bgh[pousr]_[A-Za-z0-9]{30,}\b",
        r"\bsk-[A-Za-z0-9_-]{20,}\b",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b",
    )
]


def is_published(text: str) -> bool:
    m = FRONTMATTER.match(text)
    return bool(m and PUBLISH.search(m.group(1)))


def walk(vault: Path):
    for p in vault.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(vault).parts):
            continue
        yield p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(Path.home() / "vaults/polyhydra"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    vault = Path(args.vault).expanduser().resolve()

    files = list(walk(vault))
    by_name = {p.name: p for p in files if p.suffix.lower() in ATTACH_EXT}
    notes: dict[Path, Path] = {}
    problems: list[str] = []

    for p in files:
        if p.suffix != ".md" or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if not is_published(text):
            continue
        # Public path = <note's own folder, slugged>/<file>; hides vault layout.
        rel = Path(re.sub(r"[^a-z0-9]+", "-", p.parent.name.lower()).strip("-") or "notes") / p.name
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                problems.append(f"{p.relative_to(vault)}: matches credential pattern {pat.pattern[:40]!r}")
        notes[rel] = p
        for name in EMBED.findall(text):
            att = by_name.get(Path(name.strip()).name)
            if att:
                notes[Path("attachments") / att.name] = att

    if problems:
        print("REFUSING to sync; possible secrets in published notes:", file=sys.stderr)
        for line in problems:
            print("  " + line, file=sys.stderr)
        return 2

    wanted = {CONTENT / rel for rel in notes}
    for rel, src in sorted(notes.items()):
        dst = CONTENT / rel
        print(f"publish  {rel}")
        if not args.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix == ".md":
                text = src.read_text(encoding="utf-8")
                fm = FRONTMATTER.match(text)
                if fm and not QUARTZ_PUBLISH.search(fm.group(1)):
                    text = text.replace("---\n", "---\npublish: true\n", 1)
                dst.write_text(text, encoding="utf-8")
            else:
                shutil.copy2(src, dst)

    for existing in sorted(CONTENT.rglob("*")):
        if existing.is_file() and existing.name not in KEEP and existing not in wanted:
            print(f"remove   {existing.relative_to(CONTENT)}")
            if not args.dry_run:
                existing.unlink()
    if not args.dry_run:
        for d in sorted((d for d in CONTENT.rglob("*") if d.is_dir()), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()

    print(f"{len(notes)} file(s) published from {vault}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

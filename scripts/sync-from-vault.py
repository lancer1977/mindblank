#!/usr/bin/env python3
"""Mirror mindblank:true notes from an Obsidian vault into Quartz content/.

Only notes whose YAML frontmatter has `mindblank: true` leave the vault. The
vault's older `publish: true` flag (800+ legacy reference notes, some holding
credentials) is deliberately NOT the opt-in. Copies get `publish: true` added
so Quartz's ExplicitPublish filter accepts them.

Fail-closed guard: every published note and every embedded attachment is
scanned for credential-shaped strings, and the whole sync aborts (exit 2)
before anything is written if one is found. Output-path collisions abort too.
Published notes that wikilink to un-opted-in vault notes print a WARN line
(or abort with --strict).

Usage: scripts/sync-from-vault.py [--vault ~/vaults/polyhydra] [--content DIR]
                                  [--dry-run] [--strict]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONTENT = REPO / "content"
KEEP = {"index.md"}  # owned by this repo, never overwritten or pruned
SKIP_DIRS = {".obsidian", ".git", ".trash", "node_modules", "90_Archive", "99_Scratch"}
ATTACH_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf"}
ENV_KEYWORDS = ("PASS", "PWD", "SECRET", "TOKEN", "KEY")

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
PUBLISH = re.compile(r"^mindblank:\s*(true|yes)\s*$", re.M | re.I)
QUARTZ_PUBLISH = re.compile(r"^publish:\s*true\s*$", re.M | re.I)
EMBED = re.compile(r"!\[\[([^\]|#]+)")
WIKILINK = re.compile(r"!?\[\[([^\]|#^\n]+)")

# Values that are obviously placeholders, not secrets. Matched against the
# captured secret value only, so `password: <your-password>` stays quiet.
PLACEHOLDER = re.compile(
    r"<[^>]*>"
    r"|\$\{[^}]*\}"
    r"|\$\([^)]*\)"
    r"|\$[A-Za-z_]\w*"
    r"|%[A-Za-z_]\w*%"
    r"|\{\{[^}]*\}\}"
    r"|x+|\*+|\.+|-+"
    r"|change[-_]?me|placeholder|redacted|\[redacted\]"
    r"|your[-_][\w-]*",
    re.I,
)


def _value_check(m: re.Match[str]) -> bool:
    return not PLACEHOLDER.fullmatch(m.group("v").strip())


def _env_check(m: re.Match[str]) -> bool:
    key = m.group("k").upper()
    value = m.group("v")
    return (
        len(value) >= 6
        and any(word in key for word in ENV_KEYWORDS)
        and not PLACEHOLDER.fullmatch(value.strip())
    )


# (label, pattern, check). A check of None means any match is a hit.
SECRET_RULES = [
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), None),
    (
        "credential assignment",
        re.compile(
            r"\b(?:password|passwd|pwd|secret|api[_-]?key|token|client[_-]?secret)\s*[:=]\s*['\"]?(?P<v>[^\s'\"<>{}]{8,})",
            re.I,
        ),
        _value_check,
    ),
    (
        "URL with embedded credentials",
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|rediss?|amqps?)://[^\s/:@'\"]*:(?P<v>[^\s/@'\"]+)@",
            re.I,
        ),
        _value_check,
    ),
    (
        "Authorization header",
        re.compile(r"\bAuthorization\s*:\s*(?:Bearer|Basic|Token)\s+(?P<v>[A-Za-z0-9._~+/=-]{12,})", re.I),
        _value_check,
    ),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), None),
    (
        "Discord webhook",
        re.compile(r"\bdiscord(?:app)?\.com/api/webhooks/(?P<v>\d+/[A-Za-z0-9_-]{8,})", re.I),
        _value_check,
    ),
    ("Discord bot token", re.compile(r"\b[MNO][A-Za-z0-9_-]{23,25}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,38}\b"), None),
    (
        "env-style assignment",
        re.compile(r"\b(?P<k>[A-Za-z_][A-Za-z0-9_]*)=['\"]?(?P<v>[^\s'\"`;,)]+)"),
        _env_check,
    ),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), None),
    ("API key (sk-)", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), None),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), None),
    ("Slack token", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b"), None),
]


def is_published(text: str) -> bool:
    m = FRONTMATTER.match(text)
    return bool(m and PUBLISH.search(m.group(1)))


def scan(where: str, text: str) -> list[str]:
    """Return one line per hit. Never includes more than a 4-char prefix of a match."""
    found: list[str] = []
    for label, pat, check in SECRET_RULES:
        for m in pat.finditer(text):
            if check is not None and not check(m):
                continue
            line = text.count("\n", 0, m.start()) + 1
            found.append(f'{where}:{line}: {label} (match starts "{m.group(0)[:4]}…")')
    return found


def walk(vault: Path):
    for p in vault.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(vault).parts):
            continue
        yield p


def note_rel(vault: Path, p: Path) -> Path:
    """Public path = <note's own folder, slugged>/<file>; root notes go to notes/."""
    if p.parent == vault:
        slug = "notes"
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", p.parent.name.lower()).strip("-") or "notes"
    return Path(slug) / p.name


PUBLISH_KEY = re.compile(r"publish\s*:", re.I)


def render_note(text: str) -> str:
    """Return the copy's text with exactly one `publish: true` frontmatter line.

    Any existing `publish:` line (e.g. `publish: false`) is dropped and replaced
    by `publish: true`, so Quartz never sees conflicting values. Notes without
    frontmatter get a fresh block. CRLF/LF line endings are preserved.
    """
    fm = FRONTMATTER.match(text)
    if not fm:
        eol = "\r\n" if "\r\n" in text else "\n"
        return "---" + eol + "publish: true" + eol + "---" + eol + text
    first_nl = text.index("\n")
    eol = "\r\n" if text[first_nl - 1] == "\r" else "\n"
    # Group 1 ends just before the closing "\n---"; for CRLF it keeps the trailing "\r".
    kept = [line.rstrip("\r") for line in fm.group(1).split("\n") if not PUBLISH_KEY.match(line.rstrip("\r"))]
    block = eol.join(["publish: true", *kept])
    return text[: first_nl + 1] + block + eol + text[fm.end(1) + 1 :]


def sync(vault: Path, content: Path, *, dry_run: bool = False, strict: bool = False) -> int:
    if not vault.is_dir():
        # Checked before anything else so a missing vault can never prune content.
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 1
    content = content.expanduser().resolve()

    files = [p for p in walk(vault) if p.is_file()]
    md_texts = {p: p.read_bytes().decode("utf-8", errors="replace") for p in files if p.suffix == ".md"}
    published = {p for p, text in md_texts.items() if is_published(text)}

    attachments_by_name: dict[str, list[Path]] = {}
    for p in files:
        if p.suffix.lower() in ATTACH_EXT:
            attachments_by_name.setdefault(p.name, []).append(p)

    stems: dict[str, list[Path]] = {}
    for p in md_texts:
        stems.setdefault(p.stem.casefold(), []).append(p)

    outputs: dict[Path, Path] = {}  # public relative path -> source file
    problems: list[str] = []
    warnings: list[str] = []

    def claim(rel: Path, src: Path) -> None:
        prev = outputs.get(rel)
        if prev is None:
            outputs[rel] = src
        elif prev != src:
            problems.append(
                f"output collision at {rel.as_posix()}: "
                f"{src.relative_to(vault).as_posix()} and {prev.relative_to(vault).as_posix()}"
            )

    for p in sorted(published):
        text = md_texts[p]
        where = p.relative_to(vault).as_posix()
        problems.extend(scan(where, text))
        claim(note_rel(vault, p), p)

        for raw in WIKILINK.findall(text):
            target = raw.strip()
            if not target or Path(target).suffix.lower() in ATTACH_EXT:
                continue
            base = Path(target).name
            if base.lower().endswith(".md"):
                base = base[:-3]
            candidates = stems.get(base.casefold(), [])
            if candidates and not any(c in published for c in candidates):
                line = f"WARN private link: {where} -> [[{target}]] (target is not opted in)"
                if line not in warnings:
                    warnings.append(line)

        for name in EMBED.findall(text):
            hits = attachments_by_name.get(Path(name.strip()).name, [])
            if len(hits) > 1:
                problems.append(f"{where}: ambiguous attachment {name.strip()!r} matches {len(hits)} files")
            elif hits:
                claim(Path("attachments") / hits[0].name, hits[0])

    for rel, src in sorted(outputs.items()):
        if src.suffix != ".md":
            # Attachments are scanned as latin-1 so binary (PDF) bytes are inspected too.
            problems.extend(scan(src.relative_to(vault).as_posix(), src.read_bytes().decode("latin-1")))

    for line in warnings:
        print(line)

    if problems or (strict and warnings):
        print("REFUSING to sync; resolve before publishing:", file=sys.stderr)
        for line in problems:
            print("  " + line, file=sys.stderr)
        if strict:
            for line in warnings:
                print("  " + line, file=sys.stderr)
        return 2

    wanted: set[Path] = set()
    for rel, src in sorted(outputs.items()):
        dst = content / rel
        wanted.add(dst)
        print(f"publish  {rel.as_posix()}")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix == ".md":
                dst.write_bytes(render_note(md_texts[src]).encode("utf-8"))
            else:
                dst.write_bytes(src.read_bytes())

    if content.is_dir():
        for existing in sorted(content.rglob("*")):
            if existing.is_file() and existing.name not in KEEP and existing not in wanted:
                print(f"remove   {existing.relative_to(content).as_posix()}")
                if not dry_run:
                    existing.unlink()
        if not dry_run:
            for d in sorted((d for d in content.rglob("*") if d.is_dir()), reverse=True):
                if not any(d.iterdir()):
                    d.rmdir()

    print(f"{len(outputs)} file(s) published from {vault}")
    return 0


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vault", default=str(Path.home() / "vaults/polyhydra"))
    ap.add_argument("--content", default=str(DEFAULT_CONTENT), help="output directory (default: repo content/)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--strict", action="store_true", help="abort on private-link warnings too")
    args = ap.parse_args(argv)
    return sync(
        Path(args.vault).expanduser().resolve(),
        Path(args.content),
        dry_run=args.dry_run,
        strict=args.strict,
    )


if __name__ == "__main__":
    sys.exit(run())

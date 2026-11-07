#!/usr/bin/env python3
"""Mirror mindblank:true notes from an Obsidian vault into Quartz content/.

Only notes whose YAML frontmatter has `mindblank: true` leave the vault. The
vault's older `publish: true` flag (800+ legacy reference notes, some holding
credentials) is deliberately NOT the opt-in. Copies get `publish: true` added
so Quartz's ExplicitPublish filter accepts them.

Private audience (--audience private): notes with `mindblank: private` (quoted
or not) are written to a runbook.db SQLite file at --db instead of content/.
Nothing is written to content/ in that mode. --upload URL then PUTs the db to
URL/api/import with the key from RUNBOOK_IMPORT_KEY or --key-file.

Fail-closed guard: every selected note and every embedded attachment is
scanned for credential-shaped strings, and the whole sync aborts (exit 2)
before anything is written if one is found. This runs identically for both
audiences. Output-path collisions abort too. Public notes that wikilink to
un-opted-in vault notes print a WARN line (or abort with --strict).

Usage: scripts/sync-from-vault.py [--vault ~/vaults/polyhydra] [--content DIR]
                                  [--dry-run] [--strict]
       scripts/sync-from-vault.py --audience private --db PATH
                                  [--vault ~/vaults/polyhydra] [--dry-run]
                                  [--upload URL [--key-file PATH]]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONTENT = REPO / "content"
KEEP = {"index.md"}  # owned by this repo, never overwritten or pruned
SKIP_DIRS = {".obsidian", ".git", ".trash", "node_modules", "90_Archive", "99_Scratch"}
ATTACH_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf"}
ENV_KEYWORDS = ("PASS", "PWD", "SECRET", "TOKEN", "KEY")
AUDIENCES = ("public", "private")
ISO_UTC = "%Y-%m-%dT%H:%M:%SZ"
IMPORT_KEY_HEADER = "X-Runbook-Import-Key"
IMPORT_PATH = "/api/import"
IMPORT_KEY_ENV = "RUNBOOK_IMPORT_KEY"

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
PUBLISH = re.compile(r"^mindblank:[ \t]*(true|yes)[ \t]*$", re.M | re.I)
PRIVATE = re.compile(r"^mindblank:[ \t]*([\"']?)private\1[ \t]*$", re.M | re.I)
QUARTZ_PUBLISH = re.compile(r"^publish:\s*true\s*$", re.M | re.I)
EMBED = re.compile(r"!\[\[([^\]|#]+)")
WIKILINK = re.compile(r"!?\[\[([^\]|#^\n]+)")
H1 = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.M)
SLUG_DROP = re.compile(r"[^a-z0-9/-]")

DB_DDL = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE notes(
  slug TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  description TEXT,
  body_md TEXT NOT NULL,
  source_path TEXT NOT NULL,
  updated_utc TEXT NOT NULL
);
CREATE VIRTUAL TABLE notes_fts USING fts5(title, description, body_md, content='notes', content_rowid='rowid');
"""

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


def normalize_eol(text: str) -> str:
    """CRLF and lone CR become LF so audience matching never depends on line endings."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def audience_of(text: str) -> str | None:
    """Which audience a note opts into, or None.

    Private is checked first, so a note carrying both markers can only be
    selected for private and never leaks into the public content/ tree.
    """
    text = normalize_eol(text)
    m = FRONTMATTER.match(text)
    if not m:
        return None
    if PRIVATE.search(m.group(1)):
        return "private"
    if PUBLISH.search(m.group(1)):
        return "public"
    return None


def is_published(text: str) -> bool:
    return audience_of(text) == "public"


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


def slug_for(vault: Path, p: Path) -> str:
    """Vault-relative path without .md, lowercased, spaces to '-', other chars removed."""
    rel = p.relative_to(vault).as_posix()
    if rel.endswith(".md"):
        rel = rel[:-3]
    return SLUG_DROP.sub("", rel.lower().replace(" ", "-"))


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


# ---------------------------------------------------------------------------
# Private audience: frontmatter fields, runbook.db writer, upload.
# ---------------------------------------------------------------------------


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def fm_scalar(fm_text: str, key: str) -> str | None:
    pat = re.compile(rf"^{re.escape(key)}[ \t]*:[ \t]*(.*?)[ \t\r]*$", re.I)
    for line in fm_text.split("\n"):
        m = pat.match(line)
        if m:
            return _unquote(m.group(1)) or None
    return None


def fm_list(fm_text: str, key: str) -> list[str]:
    """Frontmatter list as strings: inline `[a, b]`, comma string, or block `- item` lines."""
    lines = [line.rstrip("\r") for line in fm_text.split("\n")]
    pat = re.compile(rf"^{re.escape(key)}[ \t]*:[ \t]*(.*?)[ \t]*$", re.I)
    for i, line in enumerate(lines):
        m = pat.match(line)
        if not m:
            continue
        raw = m.group(1)
        if raw.startswith("["):
            items = raw[1:].rsplit("]", 1)[0].split(",")
        elif raw:
            items = raw.split(",")
        else:
            items = []
            for nxt in lines[i + 1 :]:
                bm = re.match(r"^[ \t]+-[ \t]*(.*?)[ \t]*$", nxt)
                if not bm:
                    break
                items.append(bm.group(1))
        out: list[str] = []
        for item in items:
            value = _unquote(item)
            if value and value not in out:
                out.append(value)
        return out
    return []


def note_body(text: str) -> str:
    fm = FRONTMATTER.match(text)
    return text[fm.end() :] if fm else text


class NoteRecord(NamedTuple):
    slug: str
    title: str
    category: str
    tags: list[str]
    description: str | None
    body_md: str
    source_path: str
    updated_utc: str


def build_record(vault: Path, p: Path, text: str) -> NoteRecord:
    text = normalize_eol(text)
    fm = FRONTMATTER.match(text)
    fm_text = fm.group(1) if fm else ""
    body = note_body(text)
    slug = slug_for(vault, p)
    title = fm_scalar(fm_text, "title")
    if not title:
        heading = H1.search(body)
        title = heading.group(1) if heading else p.stem
    category = slug.split("/", 1)[0] if "/" in slug else "notes"
    return NoteRecord(
        slug=slug,
        title=title,
        category=category,
        tags=fm_list(fm_text, "tags"),
        description=fm_scalar(fm_text, "description"),
        body_md=body,
        source_path=p.relative_to(vault).as_posix(),
        updated_utc=utc_iso(p.stat().st_mtime),
    )


def utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(ISO_UTC)


def write_runbook_db(db: Path, records: list[NoteRecord], generated_utc: str) -> None:
    """Write a fresh runbook.db (schema_version 1) to a temp file beside db, then os.replace it."""
    db.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".runbook-", suffix=".tmp", dir=db.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        con = sqlite3.connect(tmp)
        try:
            con.executescript(DB_DDL)
            con.executemany(
                "INSERT INTO meta(key, value) VALUES (?, ?)",
                [
                    ("schema_version", "1"),
                    ("generated_utc", generated_utc),
                    ("note_count", str(len(records))),
                ],
            )
            con.executemany(
                "INSERT INTO notes(slug, title, category, tags, description, body_md, source_path, updated_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        r.slug,
                        r.title,
                        r.category,
                        json.dumps(r.tags, ensure_ascii=False),
                        r.description,
                        r.body_md,
                        r.source_path,
                        r.updated_utc,
                    )
                    for r in records
                ],
            )
            con.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")
            con.commit()
        finally:
            con.close()
        os.replace(tmp, db)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the import key is never re-sent to another host."""

    def redirect_request(self, *args, **kwargs):  # noqa: D401 - urllib hook
        return None


LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


def upload_url_error(url: str) -> str | None:
    """Why --upload must refuse this URL, or None. Plain http only to loopback."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return "--upload must be an http or https URL"
    if parts.scheme == "http" and (parts.hostname or "").lower() not in LOOPBACK_HOSTS:
        return "--upload refuses plain http:// to a non-loopback host; use https://"
    return None


def upload_db(db: Path, base_url: str, import_key: str) -> int:
    target = base_url.rstrip("/")
    if not target.endswith(IMPORT_PATH):
        target += IMPORT_PATH
    req = urllib.request.Request(
        target,
        data=db.read_bytes(),
        method="PUT",
        headers={IMPORT_KEY_HEADER: import_key, "Content-Type": "application/vnd.sqlite3"},
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=120) as resp:
            status = resp.getcode()
    except urllib.error.HTTPError as exc:
        print(f"error: upload to {target} failed: HTTP {exc.code}", file=sys.stderr)
        return 3
    except (urllib.error.URLError, OSError) as exc:
        print(f"error: upload to {target} failed: {getattr(exc, 'reason', exc)}", file=sys.stderr)
        return 3
    if not 200 <= status < 300:
        print(f"error: upload to {target} failed: HTTP {status}", file=sys.stderr)
        return 3
    print(f"uploaded {db.name} to {target} (HTTP {status})")
    return 0


def load_import_key(key_file: str | None) -> str | None:
    if key_file:
        raw = Path(key_file).expanduser().read_text(encoding="utf-8")
    else:
        raw = os.environ.get(IMPORT_KEY_ENV)
    return (raw or "").strip() or None


def _write_private(
    vault: Path,
    published: set[Path],
    md_texts: dict[Path, str],
    *,
    db: Path,
    dry_run: bool,
    upload_url: str | None,
    import_key: str | None,
) -> int:
    records = [build_record(vault, p, md_texts[p]) for p in sorted(published, key=lambda p: slug_for(vault, p))]
    for r in records:
        print(f"index    {r.slug}")
    if dry_run:
        print(f"{len(records)} note(s) would be written to {db} (dry run)")
        return 0
    write_runbook_db(db, records, utc_iso(time.time()))
    print(f"wrote    {db} ({len(records)} note(s))")
    if upload_url is None:
        return 0
    if import_key is None:
        raise ValueError("upload requested without an import key")
    return upload_db(db, upload_url, import_key)


# ---------------------------------------------------------------------------
# Sync driver
# ---------------------------------------------------------------------------


def sync(
    vault: Path,
    content: Path,
    *,
    dry_run: bool = False,
    strict: bool = False,
    audience: str = "public",
    db: Path | None = None,
    upload_url: str | None = None,
    import_key: str | None = None,
) -> int:
    if audience not in AUDIENCES:
        raise ValueError(f"unknown audience: {audience!r}")
    if audience == "private" and db is None:
        raise ValueError("audience private requires a db path")
    if not vault.is_dir():
        # Checked before anything else so a missing vault can never prune content.
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 1
    content = content.expanduser().resolve()

    files = [p for p in walk(vault) if p.is_file()]
    md_texts = {p: p.read_bytes().decode("utf-8", errors="replace") for p in files if p.suffix == ".md"}
    published = {p for p, text in md_texts.items() if audience_of(text) == audience}

    attachments_by_name: dict[str, list[Path]] = {}
    for p in files:
        if p.suffix.lower() in ATTACH_EXT:
            attachments_by_name.setdefault(p.name, []).append(p)

    stems: dict[str, list[Path]] = {}
    for p in md_texts:
        stems.setdefault(p.stem.casefold(), []).append(p)

    outputs: dict[Path, Path] = {}  # output relative path -> source file
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

        if audience == "private":
            slug = slug_for(vault, p)
            if slug:
                claim(Path(slug), p)
            else:
                problems.append(f"{where}: cannot derive a slug from the path")
        else:
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

    if audience == "private":
        assert db is not None
        return _write_private(
            vault,
            published,
            md_texts,
            db=db.expanduser().resolve(),
            dry_run=dry_run,
            upload_url=upload_url,
            import_key=import_key,
        )

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
    ap.add_argument("--strict", action="store_true", help="abort on private-link warnings too (public only)")
    ap.add_argument(
        "--audience",
        choices=AUDIENCES,
        default="public",
        help="public: mindblank: true -> content/ (default); private: mindblank: private -> runbook.db",
    )
    ap.add_argument("--db", metavar="PATH", help="private only: where to write runbook.db")
    ap.add_argument("--upload", metavar="URL", help="private only: PUT the db to URL/api/import")
    ap.add_argument(
        "--key-file",
        metavar="PATH",
        help=f"private only, with --upload: file holding the import key (default: env {IMPORT_KEY_ENV})",
    )
    args = ap.parse_args(argv)

    vault = Path(args.vault).expanduser().resolve()

    if args.audience == "public":
        stray = [flag for flag, val in (("--db", args.db), ("--upload", args.upload), ("--key-file", args.key_file)) if val]
        if stray:
            print(f"error: {', '.join(stray)} only apply to --audience private", file=sys.stderr)
            return 1
        return sync(vault, Path(args.content), dry_run=args.dry_run, strict=args.strict)

    if not args.db:
        print("error: --audience private requires --db PATH", file=sys.stderr)
        return 1
    if args.key_file and not args.upload:
        print("error: --key-file only applies with --upload", file=sys.stderr)
        return 1

    import_key: str | None = None
    if args.upload:
        url_err = upload_url_error(args.upload)
        if url_err:
            print(f"error: {url_err}", file=sys.stderr)
            return 1
        try:
            import_key = load_import_key(args.key_file)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"error: cannot read import key file {args.key_file}: {exc.__class__.__name__}", file=sys.stderr)
            return 1
        if not import_key:
            print(f"error: no import key: set {IMPORT_KEY_ENV} or pass --key-file PATH", file=sys.stderr)
            return 1

    return sync(
        vault,
        Path(args.content),
        dry_run=args.dry_run,
        strict=args.strict,
        audience="private",
        db=Path(args.db),
        upload_url=args.upload,
        import_key=import_key,
    )


if __name__ == "__main__":
    sys.exit(run())

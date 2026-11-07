"""Acceptance tests for scripts/sync-from-vault.py (issue lancer1977/mindblank#1).

Stdlib unittest only. Every test builds a throwaway vault and content dir under
tempfile, so the real content/ tree is never touched.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import socket
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "sync-from-vault.py"

_spec = importlib.util.spec_from_file_location("sync_from_vault", SCRIPT)
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)

# Assembled at runtime so no literal credential-shaped string lives in this file.
SLACK_LIKE = "xox" + "b-1234567890-abcdefghij"
GH_LIKE = "gh" + "p_" + "a" * 36
PEM_HEADER = "-----BEGIN " + "RSA PRIVATE KEY-----"


def fm(extra: str = "", opted_in: bool = True, eol: str = "\n") -> str:
    lines = ["---", "title: Test note"]
    if opted_in:
        lines.append("mindblank: true")
    if extra:
        lines.append(extra)
    lines += ["---", ""]
    return eol.join(lines) + eol


class SyncTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.vault = root / "polyhydra"
        self.content = root / "content"
        self.vault.mkdir()
        self.content.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def reset_dirs(self) -> None:
        # Empty the vault and content dirs in place (used between subTests).
        for d in (self.vault, self.content):
            for child in d.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()

    def write(self, rel: str, text: str | bytes) -> Path:
        path = self.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_bytes(text.encode("utf-8"))
        return path

    def note(self, folder: str, name: str, body: str, *, opted_in: bool = True, extra: str = "") -> Path:
        rel = f"{folder}/{name}.md" if folder else f"{name}.md"
        return self.write(rel, fm(extra, opted_in) + body + "\n")

    def run_sync(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        argv = ["--vault", str(self.vault), "--content", str(self.content), *args]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sync.run(argv)
        return code, out.getvalue(), err.getvalue()

    def content_files(self) -> list[Path]:
        return [p for p in self.content.rglob("*") if p.is_file()]

    def assert_refused(self, body: str, *, folder: str = "Gaming PC") -> str:
        self.note(folder, "Leaky", body)
        code, _out, err = self.run_sync()
        self.assertEqual(code, 2, msg=f"expected refusal for body: {body[:30]!r}")
        self.assertIn("REFUSING", err)
        self.assertEqual(self.content_files(), [], "nothing may be written on refusal")
        return err

    def assert_allowed(self, body: str, *, folder: str = "Gaming PC") -> None:
        self.note(folder, "Clean", body)
        code, _out, err = self.run_sync()
        self.assertEqual(code, 0, msg=f"expected success; stderr={err!r}")
        self.assertTrue((self.content / "gaming-pc" / "Clean.md").is_file())


class SecretPatternTests(SyncTestCase):
    def test_url_credentials_abort_for_each_scheme(self) -> None:
        for scheme in ("postgres", "postgresql", "mysql", "mongodb", "mongodb+srv", "redis", "rediss", "amqp", "amqps"):
            with self.subTest(scheme=scheme):
                self.reset_dirs()
                self.assert_refused(f"connect: {scheme}://user:hunter2pass@db:5432/x")

    def test_refusal_message_does_not_print_full_secret(self) -> None:
        err = self.assert_refused("connect: postgres://user:hunter2pass@db:5432/x")
        self.assertNotIn("hunter2pass", err)

    def test_bearer_authorization_header_aborts(self) -> None:
        self.assert_refused("Authorization: Bearer abcdefghijklmnop1234")

    def test_jwt_aborts(self) -> None:
        self.assert_refused(
            "token dump eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        )

    def test_discord_webhook_aborts(self) -> None:
        self.assert_refused("hook: https://discord.com/api/webhooks/123456789012345678/abcDEF_ghi-jkl123")

    def test_discord_bot_token_aborts(self) -> None:
        token = "M" + "a" * 24 + ".Abcdef." + "b" * 28
        self.assert_refused(f"bot: {token}")

    def test_env_style_assignment_with_sensitive_key_aborts(self) -> None:
        for line in (
            "DB_PASS=s3cretvalue1",
            "export MY_PWD=abcd1234",
            "APP_SECRET=zzzz9999",
            "GITHUB_TOKEN=ab12cd34ef",
            "API_KEY=aaaa1111bbbb",
        ):
            with self.subTest(line=line):
                self.reset_dirs()
                self.assert_refused(line)

    def test_existing_patterns_still_abort(self) -> None:
        samples = [
            PEM_HEADER,
            "password: hunter2hunter2",
            "api_key = abcdefgh1234",
            GH_LIKE,
            "sk-" + "a" * 30,
            "AKIA" + "A" * 16,
            SLACK_LIKE,
        ]
        for sample in samples:
            with self.subTest(sample=sample[:12]):
                self.reset_dirs()
                self.assert_refused(sample)

    def test_placeholders_do_not_trigger(self) -> None:
        body = "\n".join(
            [
                "password: <your-password>",
                "TOKEN=${TOKEN}",
                "password: changeme",
                "token: xxxxxxxxxxxx",
                "postgres://user:<your-password>@db:5432/x",
                "mysql://user:${DB_PASS}@db/x",
                "secret: ...",
                "API_KEY=<key>",
                "Authorization: Bearer <token>",
            ]
        )
        self.assert_allowed(body)

    def test_legacy_publish_flag_is_not_opt_in(self) -> None:
        self.note("Legacy", "Old", "password: hunter2hunter2", opted_in=False, extra="publish: true")
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 0)
        self.assertFalse((self.content / "legacy" / "Old.md").exists())


class AttachmentScanTests(SyncTestCase):
    def test_svg_attachment_with_secret_aborts(self) -> None:
        self.write("Gaming PC/diagram.svg", "<svg><text>password=hunter2hunter2</text></svg>")
        self.note("Gaming PC", "Diagram", "![[diagram.svg]]")
        code, _out, err = self.run_sync()
        self.assertEqual(code, 2)
        self.assertIn("diagram.svg", err)
        self.assertEqual(self.content_files(), [])

    def test_pdf_attachment_with_secret_aborts(self) -> None:
        self.write("Gaming PC/manual.pdf", b"%PDF-1.4 stream " + GH_LIKE.encode() + b" endstream")
        self.note("Gaming PC", "Manual", "![[manual.pdf]]")
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 2)

    def test_clean_svg_attachment_is_copied(self) -> None:
        self.write("Gaming PC/ok.svg", "<svg><rect width='1' height='1'/></svg>")
        self.note("Gaming PC", "Pic", "![[ok.svg]]")
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 0)
        self.assertTrue((self.content / "attachments" / "ok.svg").is_file())


class PrivateLinkTests(SyncTestCase):
    def test_wikilink_to_unpublished_note_warns_without_aborting(self) -> None:
        self.note("Gaming PC", "Public", "See [[Private Thing]] for details.")
        self.note("Gaming PC", "Private Thing", "not opted in", opted_in=False)
        code, out, _err = self.run_sync()
        self.assertEqual(code, 0)
        self.assertIn("WARN private link", out)
        self.assertIn("Public", out)
        self.assertTrue((self.content / "gaming-pc" / "Public.md").is_file())

    def test_wikilink_to_published_note_does_not_warn(self) -> None:
        self.note("Gaming PC", "A", "See [[B]].")
        self.note("Gaming PC", "B", "fine")
        code, out, _err = self.run_sync()
        self.assertEqual(code, 0)
        self.assertNotIn("WARN private link", out)

    def test_strict_aborts_on_private_link(self) -> None:
        self.note("Gaming PC", "Public", "See [[Private Thing]].")
        self.note("Gaming PC", "Private Thing", "x", opted_in=False)
        code, _out, err = self.run_sync("--strict")
        self.assertEqual(code, 2)
        self.assertIn("Private Thing", err)
        self.assertEqual(self.content_files(), [])


class FrontmatterTests(SyncTestCase):
    def test_crlf_note_gets_publish_inside_frontmatter(self) -> None:
        self.write("Gaming PC/Windows.md", fm(eol="\r\n") + "Body text\r\n")
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 0)
        published = (self.content / "gaming-pc" / "Windows.md").read_bytes().decode("utf-8")
        lines = published.replace("\r\n", "\n").split("\n")
        self.assertEqual(lines[0], "---")
        close = lines.index("---", 1)
        frontmatter = lines[1:close]
        self.assertIn("publish: true", frontmatter)
        self.assertIn("mindblank: true", frontmatter)
        self.assertNotIn("publish: true", lines[close:])

    def test_existing_publish_true_is_not_duplicated(self) -> None:
        self.note("Gaming PC", "Dup", "body", extra="publish: true")
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 0)
        text = (self.content / "gaming-pc" / "Dup.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("publish: true"), 1)

    def test_existing_publish_false_is_forced_to_true(self) -> None:
        source = self.note("Gaming PC", "Off", "body", extra="publish: false")
        before = source.read_bytes()
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 0)
        text = (self.content / "gaming-pc" / "Off.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("publish: true"), 1)
        self.assertNotIn("publish: false", text)
        self.assertEqual(source.read_bytes(), before, "vault file must never be modified")

    def test_crlf_with_publish_false_is_forced_to_true(self) -> None:
        self.write("Gaming PC/OffCrlf.md", fm(extra="publish: false", eol="\r\n") + "Body\r\n")
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 0)
        published = (self.content / "gaming-pc" / "OffCrlf.md").read_bytes().decode("utf-8")
        lines = published.replace("\r\n", "\n").split("\n")
        close = lines.index("---", 1)
        frontmatter = lines[1:close]
        self.assertEqual([l for l in frontmatter if l.startswith("publish:")], ["publish: true"])
        self.assertNotIn("publish: false", published)
        self.assertEqual(published.count("\n"), published.count("\r\n"), "line endings must stay CRLF")

    def test_note_without_frontmatter_is_not_opted_in(self) -> None:
        self.write("Gaming PC/Bare.md", "Just a body with no frontmatter\n")
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 0)
        self.assertFalse((self.content / "gaming-pc" / "Bare.md").exists())

    def test_render_prepends_frontmatter_when_missing(self) -> None:
        self.assertEqual(sync.render_note("Body\n"), "---\npublish: true\n---\nBody\n")

    def test_render_replaces_publish_no_and_keeps_other_keys(self) -> None:
        text = "---\ntitle: X\npublish: no\nmindblank: true\n---\nBody\n"
        self.assertEqual(
            sync.render_note(text),
            "---\npublish: true\ntitle: X\nmindblank: true\n---\nBody\n",
        )


class CollisionTests(SyncTestCase):
    def test_two_notes_mapping_to_same_path_abort(self) -> None:
        self.note("A B", "Same", "one")
        self.note("a-b", "Same", "two")
        code, _out, err = self.run_sync()
        self.assertEqual(code, 2)
        self.assertIn("collision", err.lower())
        self.assertEqual(self.content_files(), [])

    def test_two_embedded_attachments_with_same_name_abort(self) -> None:
        self.write("One/diagram.png", b"\x89PNG one")
        self.write("Two/diagram.png", b"\x89PNG two")
        self.note("Gaming PC", "Uses", "![[diagram.png]]")
        code, _out, err = self.run_sync()
        self.assertEqual(code, 2)
        self.assertIn("diagram.png", err)


class LayoutTests(SyncTestCase):
    def test_root_note_goes_to_notes_folder(self) -> None:
        self.note("", "Loose", "body")
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 0)
        self.assertTrue((self.content / "notes" / "Loose.md").is_file())
        self.assertFalse((self.content / "polyhydra").exists())

    def test_nested_note_uses_immediate_folder_slug(self) -> None:
        self.note("01_Knowledge/Tools/Gaming PC", "Battle.net", "body")
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 0)
        self.assertTrue((self.content / "gaming-pc" / "Battle.net.md").is_file())


class SafetyTests(SyncTestCase):
    def test_dry_run_writes_and_removes_nothing(self) -> None:
        self.note("Gaming PC", "Dry", "body")
        stale = self.content / "old" / "Stale.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("stale", encoding="utf-8")
        code, out, _err = self.run_sync("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("publish  gaming-pc/Dry.md", out)
        self.assertIn("remove   old/Stale.md", out)
        self.assertFalse((self.content / "gaming-pc").exists())
        self.assertTrue(stale.exists())

    def test_real_run_prunes_stale_but_keeps_index(self) -> None:
        self.note("Gaming PC", "Keep", "body")
        (self.content / "index.md").write_text("home", encoding="utf-8")
        stale = self.content / "old" / "Stale.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("stale", encoding="utf-8")
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 0)
        self.assertTrue((self.content / "gaming-pc" / "Keep.md").is_file())
        self.assertFalse(stale.exists())
        self.assertTrue((self.content / "index.md").is_file())

    def test_missing_vault_fails_without_pruning(self) -> None:
        stale = self.content / "old" / "Stale.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("stale", encoding="utf-8")
        missing = self.vault.parent / "does-not-exist"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sync.run(["--vault", str(missing), "--content", str(self.content)])
        self.assertNotEqual(code, 0)
        self.assertTrue(stale.exists(), "a missing vault must never prune content")


IMPORT_KEY = "sample-import-key-0123456789"
IMPORT_KEY_HEADER = "X-Runbook-Import-Key"
SQLITE_MAGIC = b"SQLite format 3\x00"


class PrivateTestCase(SyncTestCase):
    """Fixtures for the --audience private path. Invented sample notes only."""

    def setUp(self) -> None:
        super().setUp()
        self.db = Path(self._tmp.name) / "out" / "runbook.db"
        self.key_file = Path(self._tmp.name) / "import.key"

    def pnote(self, folder: str, name: str, body: str, *, marker: str = "mindblank: private", extra=()) -> Path:
        rel = f"{folder}/{name}.md" if folder else f"{name}.md"
        text = "\n".join(["---", marker, *extra, "---", ""]) + "\n" + body + "\n"
        return self.write(rel, text)

    def run_private(self, *args: str) -> tuple[int, str, str]:
        return self.run_sync("--audience", "private", "--db", str(self.db), *args)

    def read_db(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db))

    def db_slugs(self) -> list[str]:
        with contextlib.closing(self.read_db()) as con:
            return [row[0] for row in con.execute("SELECT slug FROM notes ORDER BY slug")]

    def tmp_leftovers(self) -> list[str]:
        return [n for n in os.listdir(self.db.parent) if n != "runbook.db"]


class PrivateSelectionTests(PrivateTestCase):
    def test_public_excludes_private_notes(self) -> None:
        self.note("Gaming PC", "Pub", "public body")
        self.pnote("Gaming PC", "Priv", "private body")
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 0)
        self.assertTrue((self.content / "gaming-pc" / "Pub.md").is_file())
        self.assertFalse((self.content / "gaming-pc" / "Priv.md").exists())
        self.assertFalse(self.db.exists(), "public audience never writes runbook.db")

    def test_private_selects_only_private_notes(self) -> None:
        self.note("Gaming PC", "Pub", "public body")
        self.pnote("Gaming PC", "Priv", "private body", extra=("title: Priv",))
        self.note("Gaming PC", "Legacy", "legacy", extra="publish: true", opted_in=False)
        self.write("Gaming PC/Bare.md", "no frontmatter at all\n")
        code, out, err = self.run_private()
        self.assertEqual(code, 0, msg=err)
        self.assertEqual(self.db_slugs(), ["gaming-pc/priv"])
        self.assertEqual(self.content_files(), [], "private audience must not write content/")
        self.assertIn("wrote", out)

    def test_private_accepts_quoted_marker(self) -> None:
        self.pnote("Gaming PC", "Dq", "one", marker='mindblank: "private"')
        self.pnote("Gaming PC", "Sq", "two", marker="mindblank: 'private'")
        code, _out, err = self.run_private()
        self.assertEqual(code, 0, msg=err)
        self.assertEqual(self.db_slugs(), ["gaming-pc/dq", "gaming-pc/sq"])

    def test_private_note_with_mindblank_true_is_not_private(self) -> None:
        self.note("Gaming PC", "Public Only", "body")
        code, _out, _err = self.run_private()
        self.assertEqual(code, 0)
        self.assertEqual(self.db_slugs(), [])

    def test_note_with_both_markers_is_private_only(self) -> None:
        self.pnote("Gaming PC", "Both", "body", extra=("mindblank: true",))
        code, _out, _err = self.run_sync()
        self.assertEqual(code, 0)
        self.assertFalse((self.content / "gaming-pc" / "Both.md").exists())
        code, _out, _err = self.run_private()
        self.assertEqual(code, 0)
        self.assertEqual(self.db_slugs(), ["gaming-pc/both"])

    def test_secret_in_private_note_aborts_and_writes_no_db(self) -> None:
        self.pnote("Gaming PC", "Leaky", "connect: postgres://user:hunter2pass@db:5432/x")
        code, _out, err = self.run_private()
        self.assertEqual(code, 2)
        self.assertIn("REFUSING", err)
        self.assertNotIn("hunter2pass", err)
        self.assertFalse(self.db.exists())
        self.assertEqual(self.tmp_leftovers() if self.db.parent.exists() else [], [])
        self.assertEqual(self.content_files(), [])

    def test_secret_in_private_attachment_aborts(self) -> None:
        self.write("Gaming PC/diagram.svg", "<svg><text>password=hunter2hunter2</text></svg>")
        self.pnote("Gaming PC", "Diagram", "![[diagram.svg]]")
        code, _out, _err = self.run_private()
        self.assertEqual(code, 2)
        self.assertFalse(self.db.exists())

    def test_slug_collision_in_private_aborts(self) -> None:
        self.pnote("A B", "Same", "one")
        self.pnote("a-b", "Same", "two")
        code, _out, err = self.run_private()
        self.assertEqual(code, 2)
        self.assertIn("collision", err.lower())
        self.assertFalse(self.db.exists())

    def test_dry_run_private_writes_nothing(self) -> None:
        self.pnote("Gaming PC", "Dry", "body")
        code, out, _err = self.run_private("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("index    gaming-pc/dry", out)
        self.assertFalse(self.db.exists())
        self.assertFalse(self.db.parent.exists())

    def test_existing_db_is_replaced_fresh(self) -> None:
        self.db.parent.mkdir(parents=True)
        self.db.write_bytes(b"this is not a database")
        self.pnote("Gaming PC", "Only", "body")
        code, _out, err = self.run_private()
        self.assertEqual(code, 0, msg=err)
        self.assertEqual(self.db_slugs(), ["gaming-pc/only"])
        self.assertEqual(self.tmp_leftovers(), [])


class PrivateDbTests(PrivateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.pnote(
            "Gaming PC",
            "Battle Net",
            "# Battle.net setup\n\nInstall the launcher and sign in with the sample account.",
            extra=("tags: [launcher, \"game store\"]", "description: Sample description text"),
        )
        self.pnote("Gaming PC", "Other", "Unrelated content about zebras.", extra=("title: Other note",))
        code, _out, err = self.run_private()
        self.assertEqual(code, 0, msg=err)

    def test_schema_matches_contract(self) -> None:
        with contextlib.closing(self.read_db()) as con:
            names = {row[0] for row in con.execute("SELECT name FROM sqlite_master")}
            self.assertTrue({"meta", "notes", "notes_fts"} <= names)
            cols = [row[1] for row in con.execute("PRAGMA table_info(notes)")]
            self.assertEqual(
                cols, ["slug", "title", "category", "tags", "description", "body_md", "source_path", "updated_utc"]
            )
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_meta_rows(self) -> None:
        with contextlib.closing(self.read_db()) as con:
            meta = dict(con.execute("SELECT key, value FROM meta"))
        self.assertEqual(meta["schema_version"], "1")
        self.assertEqual(meta["note_count"], "2")
        self.assertRegex(meta["generated_utc"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_row_fields(self) -> None:
        with contextlib.closing(self.read_db()) as con:
            row = con.execute(
                "SELECT title, category, tags, description, body_md, source_path, updated_utc "
                "FROM notes WHERE slug = 'gaming-pc/battle-net'"
            ).fetchone()
        title, category, tags, description, body, source_path, updated = row
        self.assertEqual(title, "Battle.net setup", "title falls back to the first '# ' heading")
        self.assertEqual(category, "gaming-pc")
        self.assertEqual(json.loads(tags), ["launcher", "game store"])
        self.assertEqual(description, "Sample description text")
        self.assertNotIn("mindblank:", body, "body_md must exclude frontmatter")
        self.assertTrue(body.lstrip().startswith("# Battle.net setup"))
        self.assertEqual(source_path, "Gaming PC/Battle Net.md")
        self.assertRegex(updated, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_fts_search_finds_body_and_title(self) -> None:
        with contextlib.closing(self.read_db()) as con:
            query = "SELECT n.slug FROM notes_fts JOIN notes n ON n.rowid = notes_fts.rowid WHERE notes_fts MATCH ?"
            hits = [r[0] for r in con.execute(query, ("launcher",))]
            self.assertEqual(hits, ["gaming-pc/battle-net"])
            hits = [r[0] for r in con.execute(query, ("zebras",))]
            self.assertEqual(hits, ["gaming-pc/other"])

    def test_root_note_slug_and_category(self) -> None:
        self.pnote("", "Loose Note", "body without heading or title")
        code, _out, err = self.run_private()
        self.assertEqual(code, 0, msg=err)
        with contextlib.closing(self.read_db()) as con:
            row = con.execute("SELECT slug, category, title FROM notes WHERE slug = 'loose-note'").fetchone()
        self.assertEqual(row, ("loose-note", "notes", "Loose Note"))

    def test_slug_normalisation(self) -> None:
        self.pnote("Gaming PC", "Battle Net v2!", "body", extra=("title: Battle v2",))
        code, _out, err = self.run_private()
        self.assertEqual(code, 0, msg=err)
        self.assertIn("gaming-pc/battle-net-v2", self.db_slugs())

    def test_tags_comma_string_and_block_list(self) -> None:
        self.pnote("Gaming PC", "Commas", "body", extra=("tags: alpha, beta",))
        self.pnote("Gaming PC", "Block", "body", extra=("tags:", "  - gamma", "  - delta"))
        self.pnote("Gaming PC", "NoTags", "body")
        code, _out, err = self.run_private()
        self.assertEqual(code, 0, msg=err)
        with contextlib.closing(self.read_db()) as con:
            tags = dict(con.execute("SELECT slug, tags FROM notes"))
        self.assertEqual(json.loads(tags["gaming-pc/commas"]), ["alpha", "beta"])
        self.assertEqual(json.loads(tags["gaming-pc/block"]), ["gamma", "delta"])
        self.assertEqual(json.loads(tags["gaming-pc/notags"]), [])


class PrivateArgumentTests(PrivateTestCase):
    def test_missing_db_with_private_errors(self) -> None:
        self.pnote("Gaming PC", "Priv", "body")
        code, _out, err = self.run_sync("--audience", "private")
        self.assertNotEqual(code, 0)
        self.assertIn("--db", err)
        self.assertEqual(self.content_files(), [])

    def test_db_flags_rejected_for_public(self) -> None:
        code, _out, err = self.run_sync("--db", str(self.db))
        self.assertNotEqual(code, 0)
        self.assertIn("--audience private", err)
        self.assertFalse(self.db.exists())

    def test_key_file_requires_upload(self) -> None:
        code, _out, _err = self.run_private("--key-file", str(self.key_file))
        self.assertNotEqual(code, 0)

    def test_upload_without_any_key_errors_before_writing(self) -> None:
        self.pnote("Gaming PC", "Priv", "body")
        with mock.patch.dict(os.environ, clear=False):
            os.environ.pop("RUNBOOK_IMPORT_KEY", None)
            code, _out, err = self.run_private("--upload", "http://127.0.0.1:9")
        self.assertNotEqual(code, 0)
        self.assertIn("RUNBOOK_IMPORT_KEY", err)
        self.assertFalse(self.db.exists(), "no key means nothing is written")

    def test_upload_rejects_non_http_scheme(self) -> None:
        self.pnote("Gaming PC", "Priv", "body")
        self.key_file.write_text(IMPORT_KEY + "\n", encoding="utf-8")
        code, _out, _err = self.run_private("--upload", "file:///etc/passwd", "--key-file", str(self.key_file))
        self.assertNotEqual(code, 0)
        self.assertFalse(self.db.exists())


class CrlfAudienceTests(PrivateTestCase):
    def both(self, eol: str) -> str:
        return eol.join(["---", "mindblank: true", "mindblank: private", "---", ""]) + "body" + eol

    def test_crlf_both_markers_is_private_only(self) -> None:
        self.write("Gaming PC/Both.md", self.both("\r\n"))
        self.assertEqual(sync.audience_of(self.both("\r\n")), "private")
        code, _o, err = self.run_sync()
        self.assertEqual(code, 0, msg=err)
        self.assertEqual(self.content_files(), [], "never published publicly")
        code, _o, err = self.run_private()
        self.assertEqual(code, 0, msg=err)
        self.assertEqual(self.db_slugs(), ["gaming-pc/both"])

    def test_crlf_private_only_selected(self) -> None:
        self.write("Gaming PC/P.md", "---\r\nmindblank: private   \r\n---\r\nbody\r\n")
        code, _o, err = self.run_private()
        self.assertEqual(code, 0, msg=err)
        self.assertEqual(self.db_slugs(), ["gaming-pc/p"])

    def test_cr_only_both_markers_is_private_only(self) -> None:
        self.write("Gaming PC/Cr.md", self.both("\r"))
        self.assertEqual(sync.audience_of(self.both("\r")), "private")
        code, _o, err = self.run_sync()
        self.assertEqual(code, 0, msg=err)
        self.assertEqual(self.content_files(), [])
        code, _o, err = self.run_private()
        self.assertEqual(code, 0, msg=err)
        self.assertEqual(self.db_slugs(), ["gaming-pc/cr"])

    def test_trailing_whitespace_public_marker(self) -> None:
        self.assertEqual(sync.audience_of("---\nmindblank: true \t\n---\nx\n"), "public")

    def test_upload_refuses_plain_http_to_remote_host(self) -> None:
        self.pnote("Gaming PC", "Priv", "body")
        self.key_file.write_text(IMPORT_KEY + "\n", encoding="utf-8")
        for url in ("http://example.com", "http://192.0.2.10:8080", "http://localhost.example.com"):
            code, out, err = self.run_private("--upload", url, "--key-file", str(self.key_file))
            self.assertEqual(code, 1, msg=url)
            self.assertIn("https", err)
            self.assertNotIn(IMPORT_KEY, out + err)
        self.assertFalse(self.db.exists())

    def test_upload_url_error_allows_loopback_and_https(self) -> None:
        for url in ("http://localhost:1", "http://127.0.0.1:1", "http://[::1]:1", "https://example.com"):
            self.assertIsNone(sync.upload_url_error(url), url)


class _UploadServer:
    """Local http.server test double that records every request it receives."""

    def __init__(self, status: int = 200) -> None:
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self) -> None:  # noqa: N802 - http.server hook
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                outer.requests.append(
                    {
                        "method": "PUT",
                        "path": self.path,
                        "key": self.headers.get(IMPORT_KEY_HEADER),
                        "body": body,
                    }
                )
                payload = b'{"notes": 1}' if 200 <= status < 300 else b'{"error": "unauthorized"}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args) -> None:  # silence the default stderr access log
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class PrivateUploadTests(PrivateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.pnote("Gaming PC", "Priv", "body text for upload")
        self.key_file.write_text(IMPORT_KEY + "\n", encoding="utf-8")

    def start(self, status: int = 200) -> _UploadServer:
        server = _UploadServer(status)
        self.addCleanup(server.close)
        return server

    def test_upload_puts_db_with_key_header(self) -> None:
        server = self.start()
        code, out, err = self.run_private("--upload", server.url, "--key-file", str(self.key_file))
        self.assertEqual(code, 0, msg=err)
        self.assertEqual(len(server.requests), 1)
        req = server.requests[0]
        self.assertEqual(req["method"], "PUT")
        self.assertEqual(req["path"], "/api/import")
        self.assertEqual(req["key"], IMPORT_KEY)
        self.assertTrue(req["body"].startswith(SQLITE_MAGIC))
        self.assertEqual(req["body"], self.db.read_bytes())
        self.assertNotIn(IMPORT_KEY, out)
        self.assertNotIn(IMPORT_KEY, err)

    def test_upload_key_from_env(self) -> None:
        server = self.start()
        with mock.patch.dict(os.environ, {"RUNBOOK_IMPORT_KEY": IMPORT_KEY}):
            code, out, err = self.run_private("--upload", server.url)
        self.assertEqual(code, 0, msg=err)
        self.assertEqual(server.requests[0]["key"], IMPORT_KEY)
        self.assertNotIn(IMPORT_KEY, out + err)

    def test_upload_non_2xx_exits_nonzero(self) -> None:
        server = self.start(status=401)
        code, out, err = self.run_private("--upload", server.url, "--key-file", str(self.key_file))
        self.assertNotEqual(code, 0)
        self.assertIn("401", err)
        self.assertNotIn(IMPORT_KEY, out + err)
        self.assertTrue(self.db.exists(), "the local db is still written before upload")

    def test_upload_unreachable_exits_nonzero(self) -> None:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        code, out, err = self.run_private("--upload", f"http://127.0.0.1:{port}", "--key-file", str(self.key_file))
        self.assertNotEqual(code, 0)
        self.assertNotIn(IMPORT_KEY, out + err)

    def test_dry_run_upload_sends_nothing(self) -> None:
        server = self.start()
        code, _out, _err = self.run_private("--dry-run", "--upload", server.url, "--key-file", str(self.key_file))
        self.assertEqual(code, 0)
        self.assertEqual(server.requests, [])
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()

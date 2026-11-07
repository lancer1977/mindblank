"""Acceptance tests for scripts/sync-from-vault.py (issue lancer1977/mindblank#1).

Stdlib unittest only. Every test builds a throwaway vault and content dir under
tempfile, so the real content/ tree is never touched.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import shutil
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()

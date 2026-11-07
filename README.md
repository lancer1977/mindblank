# Mindblank: Polyhydra Field Notes

A public Quartz v4.5.2 site of tips, tricks and how-tos, for people and for AI
agents (via Sage).

## Workflow

1. Write the note in Obsidian (`~/vaults/polyhydra`) and add `mindblank: true` to its frontmatter.
2. `python3 -I scripts/sync-from-vault.py` copies **only** opted-in notes into
   `content/<folder-slug>/`, aborts if anything looks like a credential, and
   prunes notes that are no longer opted in. Use `--dry-run` to preview.
3. `npx quartz build`, then preview `public/` locally (or run `npx quartz build --serve`).
4. Commit on `dev`. Publishing happens from `main`.

The vault's older `publish: true` flag is **not** the opt-in. 800+ legacy
reference notes carry it, some with credentials. `content/index.md` belongs to
this repo.

## Machine-readable outputs

1. `/index.xml` is the RSS feed.
2. `/sitemap.xml` is the sitemap, which Sage ingests with a `sitemap` source.

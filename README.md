# Mindblank: Polyhydra Field Notes

A public Quartz v4.5.2 site of tips, tricks and how-tos, for people and for AI
agents (via Sage).

## Workflow

1. Write the note in Obsidian (`~/vaults/polyhydra`) and add `mindblank: true` to its frontmatter.
2. `python3 -I scripts/sync-from-vault.py` copies **only** opted-in notes into
   `content/<folder-slug>/`, aborts if anything looks like a credential, and
   prunes notes that are no longer opted in. Use `--dry-run` to preview.
   If a run selects zero notes (for example, an unmounted vault), it refuses to prune
   a populated `content/` and exits 2; `--allow-empty` overrides this for a deliberate wipe.
3. `npx quartz build`, then preview `public/` locally (or run `npx quartz build --serve`).
4. Commit on `dev`. Publishing happens from `main`.

The vault's older `publish: true` flag is **not** the opt-in. 800+ legacy
reference notes carry it, some with credentials. `content/index.md` belongs to
this repo.

## Recovering from an incorrect sync

A sync can publish the wrong notes or prune notes that should stay. The sync
only writes under `content/`, and `content/` is tracked in Git, so Git is the
undo. Never touch the vault to "fix" this, and never publish until the steps
below pass.

Every command here is scoped to `content/` (or named files in it). Do not use
`git reset --hard`, `git checkout .`, `git restore .` or an unscoped
`git clean`: they would also discard unrelated work.

1. **Stop and inspect.** Do not commit or re-run the sync yet.
   `git status --short content/` lists what changed: `M` overwritten,
   `D` pruned, `??` newly published.
2. **Correct the vault source first.** Fix the opt-in flag (`mindblank: true`)
   or the note in `~/vaults/polyhydra`. If you skip this, the next sync repeats
   the mistake.
3. **Pick a known-good revision.**
   - Not yet committed: it is `HEAD`.
   - Already committed: find the last good commit with
     `git log --oneline -- content/` and check it with
     `git diff <good> HEAD --stat -- content/`. Use that commit as `<good>` below.
4. **Restore tracked generated files**, path-scoped. Use `HEAD` for `<good>` if
   the bad sync is uncommitted.
   - Whole sync was wrong: `git restore --source=<good> --worktree --staged -- content/ ':!content/index.md'`
   - Only some notes: `git restore --source=<good> --worktree --staged -- "content/linux/Some Note.md"`

   This brings back overwritten files and files the sync pruned. It never
   touches `content/index.md` (repo-owned) or paths you do not name.

5. **Remove files the bad sync newly added.** Preview first, then delete only
   what is listed: `git clean -nd -- content/` then `git clean -fd -- content/`
   (add the exact paths to scope it further). If the bad sync was already
   committed, `git restore` in step 4 deletes added files too when `<good>`
   predates them; otherwise `git rm -- <path>`.
6. **Confirm it is clean.** `git status --short content/` should show only the
   changes you intend to keep. Unrelated edits elsewhere stay as they were.
7. **Re-sync and review.** `python3 -I scripts/sync-from-vault.py --dry-run`
   and check every `publish` and `remove` line is expected. Then
   `python3 -I scripts/sync-from-vault.py`, and review
   `git diff -- content/`.
8. **Verify before publishing.** `python3 -I -m unittest discover -s tests`,
   `npm run check`, then `npx quartz build`. Commit on `dev`; publishing is a
   separate step from `main`.

If a bad sync was already merged to `main` and deployed, treat it as an
incident: ask the maintainer before reverting `main`, and remove any
credential that was exposed.

## Machine-readable outputs

1. `/index.xml` is the RSS feed.
2. `/sitemap.xml` is the sitemap, which Sage ingests with a `sitemap` source.

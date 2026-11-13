# code_health — mindblank

## 2026-11-13 - Look for Trouble

**Prior passes: none.** This is the first look-for-trouble pass for this repo, so there are no prior sections. Every finding below is new and has status `active`. The stale list for every bucket is "none (first pass)".

| field            | value                                                                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------------- |
| repo             | lancer1977/mindblank                                                                                    |
| path             | /home/lancer1977/code/mindblank                                                                         |
| branch           | dev                                                                                                     |
| trigger          | requested-by-user (operator maintenance pass after a backlog burn found 0 open issues and 0 open PRs)   |
| reviewed_at_utc  | 2026-11-13T15:02:41Z                                                                                    |
| reviewed_from    | fe71d31                                                                                                 |
| scope            | whole repo: Quartz 4.5.2 site, scripts/sync-from-vault.py, tests/, runbook/ .NET app, .github/workflows |
| stale thresholds | code/tests 30 days, actions/deploy 30 days, deps 14 days, architecture 90 days                          |
| next_review_at   | 2026-11-27T00:00:00Z (earliest, deps bucket; per-bucket dates under next)                               |

### validation commands

| command                               | result                                                                                                                             |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `npm run check` (tsc + prettier)      | pass                                                                                                                               |
| `npm test` (tsx --test, quartz utils) | 48/48 pass                                                                                                                         |
| `python3 -m pytest -q tests`          | 63 passed, 21 subtests                                                                                                             |
| `behavior_proxy_scan.py tests`        | 1 hit at tests/test_sync_from_vault.py:258, judged a false positive (it asserts on the written output file, which is the behavior) |
| `unpatched_exec_scan.py .`            | 0 findings                                                                                                                         |
| `dotnet test runbook/` (local)        | did not run: NETSDK1226 "Prune Package data not found" on local SDK 10.0.114. Workstation SDK issue; CI runs it                    |
| `npm audit --omit=dev`                | 20 vulns: 13 high, 3 moderate, 4 low, 0 critical                                                                                   |
| `npm outdated`                        | ~41 packages behind                                                                                                                |

### code issues

| id  | severity | finding                                                                                                                                                                                          | area                       | evidence             |
| --- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------- | -------------------- |
| F1  | high     | Public sync prunes all of content/ when the vault dir exists but has zero opted-in notes (for example an unmounted or empty mount point). The only guard is vault.is_dir(). Recovery is git only | scripts/sync-from-vault.py | :474-477, :582-587   |
| F2  | med      | Public writes aren't atomic (direct write_bytes). A mid-run failure leaves a mixed tree. The private DB path already uses mkstemp + os.replace                                                   | scripts/sync-from-vault.py | :575-580 vs :329-371 |
| F3  | med      | Bad UTF-8 is decoded with errors="replace" and gives no warning. A UTF-8 BOM makes the frontmatter regex miss, so the note is skipped silently (found by reading the code, not reproduced)       | scripts/sync-from-vault.py | :481, :55            |
| F4  | low      | Symlinks inside the vault are followed, so a file outside the vault can be published (the secret scan still applies). Collisions on case-insensitive filesystems aren't detected                 | scripts/sync-from-vault.py | :190-194, :497-505   |
| F5  | low      | Secret rules lack Stripe sk*live*, Google AIza, GitLab glpat-, and npm npm\_ patterns                                                                                                            | scripts/sync-from-vault.py | :110-149             |

**stale:** none (first pass). **reopened:** none. **status:** active

### deployment gaps

| id  | severity | finding                                                                                                                                                                | surface                                | evidence                              |
| --- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- | ------------------------------------- |
| F10 | med      | workflow_dispatch on runbook-image.yml can run from any branch and tags `latest` and `main`, so a dispatch from dev would overwrite latest. No dev-tagged image exists | runbook-image.yml                      | :7, :33-35                            |
| F11 | low      | Dockerfile base images float (sdk:10.0, aspnet:10.0, no digest). No HEALTHCHECK, even though /healthz exists. Actions use floating major tags, not SHAs                | runbook/Dockerfile, runbook Program.cs | runbook/Dockerfile:1,8; Program.cs:36 |

**stale:** none (first pass). **reopened:** none. **status:** active

### actions gaps

| id  | severity | finding                                                                                                                                                              | surface              | evidence                         |
| --- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | -------------------------------- |
| F7  | high     | ci.yml triggers only on pull_request to dev. No CI runs on the dev->main promotion PR or on push to main. deploy.yml publishes Pages on push to main with no CI gate | ci.yml, deploy.yml   | ci.yml:4-5; deploy.yml:4-5       |
| F8  | med      | `npm run check` and `npm test` don't run in CI. Only `npx quartz build` and the python tests do                                                                      | ci.yml, package.json | ci.yml:22-23; package.json:17,19 |
| F9  | low      | runbook-unit (dotnet test) runs on every dev PR with no paths filter. Acceptable as Tier 1, but could be scoped to runbook/\*\* with a non-required-check-safe gate  | ci.yml               | :25-34                           |

**stale:** none (first pass). **reopened:** none. **status:** active

### issues gaps

| measure             | value                                                                     |
| ------------------- | ------------------------------------------------------------------------- |
| open_issue_pressure | 0 open issues, 0 open PRs at pass start / delta not computed (first pass) |
| stale_issue_risk    | 0 / none at pass start                                                    |

| id  | severity | finding                                                                                                                | owner                      |
| --- | -------- | ---------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| F17 | info     | 0 open issues and 0 open PRs at pass start. This pass created milestone "Maintenance — repo health" (#1) and issue #13 | not assigned in pass facts |

**stale:** none (first pass). **reopened:** none. **status:** active

### architectural concerns

| id  | severity | finding                                                                                                                                                                                                                                                                                                                                                                | boundary risk                                                                         | evidence                                         |
| --- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------ |
| F12 | med      | README doesn't cover the runbook, `--audience private`, `--db`, `--upload`, the `mindblank: private` marker, the deploy workflows, or the test commands. It doesn't say the runbook relies on edge auth (Traefik -> oauth2-proxy/Keycloak in homelab-gitops systems/r620/stacks/runbook). The app itself has no OIDC by design, which is correct but undocumented here | edge auth is the only access control for the runbook and is undocumented in this repo | README.md; runbook/src/Runbook/Program.cs:38-138 |
| F13 | low      | The vendored quartz/ (168 files) has had no local edits since scaffold 3c00afc, but there's no upstream remote or documented upgrade path. package.json still names it @jackyzha0/quartz 4.5.2                                                                                                                                                                         | vendored code with no documented upgrade path                                         | package.json:2,5                                 |

**stale:** none (first pass). **reopened:** none. **status:** active

### reuse and consolidation opportunities

| id  | severity | finding                                                                                            | duplicated in / candidate library                      | evidence                           |
| --- | -------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | ---------------------------------- |
| F15 | low      | Secret-regex rules are duplicated across repos. A shared rule set could be a candidate. Not diffed | dev-forge tools/secret_guard.py, channel-cheevos tests | scripts/sync-from-vault.py:110-149 |

**stale:** none (first pass). **reopened:** none. **status:** active

### dependency and worktree noise

| id  | severity | item                                                                                                                                                                                             | evidence                        |
| --- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------- |
| F14 | med      | 13 high npm audit advisories (production deps), ~41 outdated packages                                                                                                                            | `npm audit`; `npm outdated`     |
| F16 | low      | .worktrees/ isn't in .gitignore (only in .prettierignore). Commit fe71d31's message says "ignore generated content/", but content/ is still tracked, which is intentional for git-based recovery | .gitignore, .prettierignore:4-5 |

**stale:** none (first pass). **reopened:** none. **status:** active

### next

| field                    | value                                                                                                                             |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| recommended_next_slice   | F1+F6 prune guard: refuse to prune when 0 notes are selected but content/ has files, unless --allow-empty, plus a regression test |
| owner                    | Opus orchestrates; a Haiku lane implements, on dev                                                                                |
| follow_up_owner          | not specified in pass facts                                                                                                       |
| next_revisit_date        | 2026-11-27                                                                                                                        |
| next_work_picker_offered | not recorded in pass facts                                                                                                        |
| next_work_picker_choice  | pending                                                                                                                           |

Ranked next slices:

| rank | slice                                                                               | findings |
| ---- | ----------------------------------------------------------------------------------- | -------- |
| 1    | prune guard, with regression test                                                   | F1, F6   |
| 2    | CI coverage: push/PR-to-main triggers, run `npm run check` and `npm test` in ci.yml | F7, F8   |
| 3    | npm audit triage                                                                    | F14      |
| 4    | README runbook and edge-auth section                                                | F12      |

Per-bucket next review dates:

| bucket             | next review |
| ------------------ | ----------- |
| code/tests         | 2026-12-13  |
| actions/deploy     | 2026-12-13  |
| deps               | 2026-11-27  |
| docs (F12)         | 2026-12-13  |
| architecture/reuse | 2027-02-11  |

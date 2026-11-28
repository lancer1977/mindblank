# Verification strategy
- Unit: metadata validation, opt-in, credential detection, stale/superseded flags, public field allowlist.
- Contract: stable IDs, canonical version, hashes, sitemap/RSS/manifest, retraction, retrieval citations.
- Integration: isolated vault sync, Quartz build, Sage incremental ingestion and removal; no private note ingested.
- E2E: approved sample article -> preview -> test publication -> Sage retrieval -> agent answer with citation.
- Adversarial: malicious instructions in article cannot authorize tools, stale article cannot override canonical policy, denied scope fails closed, secrets and private metadata never enter public output.
- Live smoke: separately authorized public release and retrieval, rollback/retraction verified. Record exact revision, date, owner, evidence and failures; no public claims from fixtures alone.
- Demo: human reads MFD guide, agent retrieves same pattern, produces a profile proposal with citations, policy validator checks independently.
- Metrics: profile coverage, stale content, retrieval accuracy, citation coverage, ingestion lag, accidental exposure (target zero). Local workers first; no unexpected cloud spending.
Existing validation: python3 -I -m unittest discover -s tests; npm run check; npx quartz build. Do not run vault sync against real vault without inspecting dry-run.

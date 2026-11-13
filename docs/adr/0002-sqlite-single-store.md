# 2. One SQLite file outside the repo is the research store

Status: accepted (2026-11-13, rebuild)

All research data lives in `radar.db` in a user data folder (`~/ai-meme-radar-data/` by default), outside the Git checkout, so it survives pulls, branch switches and code changes. Raw Ge Fei responses are stored as JSON in `api_calls`; there is no separate raw-file tree. Normalized tables are snapshot tables that only grow when content changes.

History is append-only where it matters: assessments are revisions, feedback and link changes are events, sync units are checkpoints. That is what makes interrupted runs resumable and backtests honest.

Reports are Markdown files next to the database; the database indexes them and maps them to Lark documents.

Rejected: CSV/JSON files in the repo (the previous design). They mixed code and data, made history edits easy and resumption hard. No legacy data was migrated.

Schema versioning: `PRAGMA user_version` carries `SCHEMA_VERSION`. An empty file is initialized; the same version opens; any other version, or a non-empty file without a version, is refused with an error. Nothing is migrated, re-stamped or deleted automatically. A schema change bumps `SCHEMA_VERSION` and requires moving the old file aside. Version 3 (2026-11-13) adds ingestion timestamps; any v1/v2 store must be moved aside.

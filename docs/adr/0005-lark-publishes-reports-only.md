# 5. Lark publishes finished reports, nothing else

Status: accepted (2026-11-13, rebuild)

Local Markdown is the authoritative report. Lark Docs holds the published copy: one document per daily report and one per key opportunity, updated in place. Document ids and URLs live in `lark_docs`, so reruns update instead of duplicating. Publishing goes through `lark-cli` with the user's login. Local reports are written before publishing; a publish failure fails the run (ADR 0007) and the next run retries only the unpublished documents.

The old Lark Base sync (raw rows, batches, tracker tables) is removed. Databases, raw API data, keyword batches, website and social data, and intermediate files never leave the machine.

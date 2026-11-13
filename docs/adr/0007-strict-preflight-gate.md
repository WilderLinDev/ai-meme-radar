# 7. A strict preflight gate, no degraded runs

Status: accepted (2026-11-13)

A daily run that starts and then finds out Lark is logged out, credits are short or Instagram is behind a login wall wastes a day of research or delivers a partial one. So every `run` first checks every prerequisite, runs all independent checks, prints one consolidated PASS / FAILED report (what was seen, why it failed, what to do), and starts nothing unless all of them passed (exit 4 = NOT READY). There are no warnings and no optional services: a missing token, a locked data service, an unverifiable balance or a missing browser check is a failure.

Python checks what it can verify itself: the local environment, Ge Fei (token, catalog, `GET /api/v1/me` for authentication and balance, free page-1 data-service calls) and Lark (`lark-cli auth status --verify`, destination Wiki nodes and edit permission via `drive permission.members auth`). These are read-only: no research credits, no test documents. Destinations must be Wiki nodes because a Drive folder's edit right cannot be checked without writing. The agent checks the browser and every social platform, logged in where needed, and writes `work/DAY/preflight.browser.json`. Python only validates that report: a pass needs real research pages on the right site, from today. It never claims to know a login state.

Because the gate runs on every invocation, a resumed run is rechecked too. Finished stages stay idempotent, so passing the gate again doesn't redo them. Sync and publish failures now fail the run instead of becoming gaps, since a day that has passed the gate should not finish degraded. Lark publishing has no off switch.

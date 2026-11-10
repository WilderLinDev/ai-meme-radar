# Agent rules

Scope is already decided. Do not ask the user about it.

Use these as they are written in the repo and in `docs/routine-prompt.md`:

- Platforms, in order: TikTok, then CapCut templates, then Instagram Reels. Supporting sources are X, YouTube Shorts, and Reddit. Never Douyin.
- Creative Center: regions US, GB, AU, CA, DE, JP, KR, FR; periods 7 and 30 days; industry News & Entertainment. NL is not offered, so skip it.
- Watchlist: every account in `config/watchlist.csv`. Do not ask which accounts to add or drop.
- Report language: Chinese. Scoring: `docs/scoring.md`.
- Output: `reports/YYYY-MM/` with date-prefixed filenames. Commit and push those files.

Do not ask the user to confirm, narrow, or expand that scope.

Ask only when a login, secret, or setting required for a step is missing. Name the step, the exact key or login it needs, and what you will skip without it. Then continue the rest of the run.

If an optional value is missing, say that part is skipped. Do not ask, and do not block the run.

Run `python scripts/check_setup.py` at the start of a daily run and follow its "Blocked" and "Skipped" lists. Browser logins (TikTok Creative Center, TikTok, Instagram) are not visible to that script. If one expires mid-run, ask only for that login, skip that pull, and keep going.

# Carry forward verifiable tracker history

When Grok Bot moves to `radar`, migrate old Tracker rows once from a preserved copy of the old files. Match each row by report date and a confirmed Meme id. Carry forward the Verdict, Score, and Primary heat metric recorded for that date. Keep rows with ambiguous identity, undocumented metrics, or conflicting values in the legacy archive with the reason they could not be migrated.

Generate the Tracker with code and recompute Backtest results using the current rules and verified raw snapshots. If the evidence is incomplete, retain the applicable `pending` or `insufficient` result. For a CC index, the baseline and D+3 value must come from the same capture. Verify that rerunning the migration with identical inputs produces identical rows and results before importing them.

Starting the Tracker over would discard the context needed to evaluate prior Verdicts and count Make streaks. Carrying over the old Backtest results would preserve calculations made with the previous rules. A one-time migration keeps the recorded decisions and applies the current rules to the evidence available for each one.

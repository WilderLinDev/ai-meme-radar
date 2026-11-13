# 4. Four independent attributes and seven dimensions, no overall score

Status: accepted (2026-11-13, rebuild)

Lifecycle, decision, priority and confidence answer different questions and are set independently. Seven dimensions are each judged on their own with a level, a note and evidence. There is no weighted total: a sum invites false precision and lets a strong dimension hide a fatal one.

Accountability comes from two backtests on a tracked series fixed at assessment time (lifecycle over 7 days, opportunity decisions over 14 days) with baselines frozen in the assessment snapshot. Thresholds live in `src/radar/backtest.py` and are documented in `docs/research-method.md`.

# 日程

- 每个工作日 08:30（Asia/Shanghai），cron `30 8 * * 1-5`，允许前后 15 分钟。
- 由 Grok Bot routine 执行。完整提示词在 `docs/routine-prompt.md`。
- 默认只把当天文件写入 `reports/YYYY-MM/`。Lark Wiki 导入和 Lark Base 追加默认关闭。

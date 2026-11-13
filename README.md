# AI 视频梗雷达

每天早上回答一个问题：海外短视频里，今天哪个 AI 视频梗值得做成模板。平台顺序是 TikTok、CapCut 模板、Instagram Reels，X、YouTube Shorts、Reddit 作辅证，不看抖音。

## 快速开始

```bash
uv sync
uv run radar check
uv run pytest
```

需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。不配 Lark 也能出完整日报。

## 一天怎么跑

| 步骤 | 谁做 | 命令 / 产物 |
| --- | --- | --- |
| 预检 | 代码 | `radar check` |
| 抓数据 | Agent（浏览器） | `data/raw/YYYY-MM-DD/*.csv`、`gaps.json` |
| 登记新梗 | Agent | `data/memes.csv` |
| 校验 | 代码 | `radar ingest YYYY-MM-DD` |
| 起草 | 代码 | `radar scaffold YYYY-MM-DD` → `reports/YYYY-MM-DD/judgments.json` |
| 打分、下结论 | Agent | 填写 `judgments.json` |
| 出报告 | 代码 | `radar build YYYY-MM-DD` → 梗包、日报 md/docx、图表、追踪表、回测 |
| 交付 | Agent | `git commit` + `push`；需要时 `radar export-lark` |

完整步骤见 [docs/runbook.md](docs/runbook.md)，评分口径见 [docs/scoring.md](docs/scoring.md)，术语见 [GLOSSARY.md](GLOSSARY.md)，设计决策见 [docs/adr/](docs/adr/)。

## 目录

```
src/radar/          代码
  raw/              原始快照的表结构与读取
  analysis/         生命周期、分享率、CC 覆盖、主热度序列
  render/           同一份文档模型输出 Markdown 和 Word，外加两种图
  export/lark.py    按 config/lark-base.json 生成 Lark Base 批次
tests/              测试；fixtures/2026-11-10 是迁移过来的样例
config/             监控名单、Lark 表结构、设置示例
data/               梗名册、原始快照（raw/日期/）、追踪表、回测
reports/日期/        当天的判断、梗包、日报和图表
docs/               runbook、评分、ADR
```

原始证据、累计历史、交付物分开放：`data/raw/` 写入后不改，`data/` 下的累计表由代码维护，`reports/` 只放当天交付。

## 设置

复制 `config/settings.example.toml` 到 `~/.config/ai-meme-radar/settings.toml`（`AMR_CONFIG_DIR` 可以改目录）。只有打开 Lark 同步或改路径、字体时才需要。仓库里没有任何密钥：Lark 写入走用户自己的连接器，git push 用已有凭证。

图表默认用 `assets/fonts/NotoSansSC-Regular.otf`（不随仓库提供），找不到时自动用系统里的中文字体。

许可证 MIT（`LICENSE`）。

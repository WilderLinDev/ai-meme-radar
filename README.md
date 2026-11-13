# AI Meme Radar

AI 创作产品的趋势发现、市场研究与模板机会评估系统。每天从社交趋势、搜索需求、产品与网站、市场数据四条渠道发现正在扩散的趋势，拆出背后可复用的内容格式，判断哪些值得做成 AI 视频 / 图片 / 音频模板，并交付一份聚焦变化与行动的中文日报，以及每个重点机会的深度研究报告。

- 研究对象：趋势 → 格式 → 模板机会（多对多）
- 判断：生命周期、决策、优先级、证据可信度四项独立属性 + 七个独立维度，没有总分
- 数据：哥飞 SEO 工具箱全部 API（实时目录）+ 浏览器社交调研，统一存入本地 SQLite
- 交付：本地 Markdown 为准，飞书文档为发布副本

## 快速开始

```bash
uv sync
uv run pytest
cp config/settings.example.toml ~/.config/ai-meme-radar/settings.toml   # 填入哥飞 token，按需开启飞书
uv run python scripts/run_day.py run
```

`run` 会执行所有能执行的阶段；需要 Agent 写入研究文件时以退出码 2 停下并说明要写什么，写好后再次运行即可从断点继续。已有运行在进行时以退出码 3 退出。`status` 查看各阶段进度、日报路径和所有飞书文档的状态与链接。

## 配置

优先级：环境变量 > `settings.toml` > 默认值。所有配置只在 `src/radar/config.py` 读取。

| 环境变量 | 作用 | 对应 TOML |
| --- | --- | --- |
| `GEFEI_API_TOKEN` | 哥飞 API token（密钥，仅同步与 `call` 需要） | `[gefei] token` |
| `AMR_CONFIG_DIR` | `settings.toml` 所在目录，默认 `~/.config/ai-meme-radar/` | — |
| `AMR_DATA_DIR` | 数据目录，默认 `~/ai-meme-radar-data` | `[paths] data_dir` |
| `AMR_REPORTS_DIR` | 报告目录，默认 `<数据目录>/reports` | `[paths] reports_dir` |

飞书登录由 `lark-cli auth login` 管理，本项目不保存飞书凭据。仓库公开：不要提交 token 或真实的 `settings.toml`。

数据库没有迁移：如果代码的 `SCHEMA_VERSION` 与现有 `radar.db` 不一致，程序会拒绝打开并提示；把旧文件移开后重新运行即可生成新库。

## 文档

- `AGENTS.md`：Agent 入口，要求先读 `.agents/skills/ai-meme-radar/SKILL.md`
- `GLOSSARY.md`：术语
- `docs/research-method.md`：研究与决策框架、回测
- `docs/adr/`：架构决策

数据默认在 `~/ai-meme-radar-data/`（仓库之外）。仓库里没有任何密钥。

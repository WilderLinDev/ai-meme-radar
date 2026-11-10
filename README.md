# AI 视频梗雷达

Daily overseas AI-meme video radar. TikTok first, then CapCut, then Instagram Reels.

每个工作日早上，判断今天该不该做一个海外 AI 视频梗模板。平台顺序是 TikTok、CapCut 模板、Instagram Reels，X 发帖数、ViralRemix、Know Your Meme 等作辅证，不看抖音。TikTok Creative Center 拉 8 个地区（US、GB、AU、CA、DE、JP、KR、FR）× 7 日和 30 日的 News & Entertainment Top 100。监控名单 53 个账号（`config/watchlist.csv`）。

评分满分 100，五项各 20：热度、趋势、分享率、竞争、窗口。结论是做、观望或不做。做的推荐在 D+3 回测。Word 日报默认写进本仓库的 `reports/YYYY-MM/`。Lark Wiki 导入和 Lark Base「AI视频梗数据库」追加默认关闭，只有显式打开时才做。

完整研究步骤在 `docs/routine-prompt.md`。评分口径在 `docs/scoring.md`。

## 目录

```
docs/                         提示词、日程、数据字典、评分
scripts/                      日报流水线。reportlib/ 是图表和 Word 主题
research/                     Google Ads Keyword Planner
config/                       监控名单、Lark 表结构、设置示例
reports/2026-11/              某月的全部日报文件，不再分子目录
data/                         累计追踪表和回测
```

月份目录是一层：`reports/2026-11/`、`reports/2026-12/`。没有 `reports/2026/11/`，也没有按天再套一层文件夹。

## 命名

- Python 用小写蛇形：`build_report.py`、`sync_lark.py`。
- 文档、配置和日报产物用 kebab-case。
- 当天文件一律 `YYYY-MM-DD-<名字>.<后缀>`，直接放在月份目录里。
- 不在文件名里写版本或运行批次。报告生成器是 `scripts/build_report.py`，Word 组装是 `scripts/reportlib/docx_report.py`，Lark 同步是 `scripts/sync_lark.py`。
- 图表不进 `charts/`。例如 `reports/2026-11/2026-11-10-heat-cat-on-ultra-bee.png`。

2026-11-10 的样例包是 `reports/2026-11/2026-11-10-meme-pack.json`。

同一天还会有这些文件（跑完当天流程之后）：

- `2026-11-10-daily-report.md`
- `2026-11-10-daily-report.docx`
- `2026-11-10-cc-top100.csv`
- `2026-11-10-cc-top100-us.csv`（单地区榜，地区码小写）
- `2026-11-10-cc-hashtag-trends.csv`
- `2026-11-10-cc-hashtag-detail.json`
- `2026-11-10-heat.json`、`2026-11-10-heat.csv`
- `2026-11-10-remix-stats.csv`
- `2026-11-10-watchlist-posts.csv`

累计文件在 `data/meme-daily-tracker.csv`、`data/backtest-latest.json`、`data/backtest-latest.csv`。

`/workspace/lark`、`/workspace/tiktok_cc`、`/home/box/.secrets/google_ads.env` 是原来那台机器上的绝对路径。脚本还会在这些路径存在时读它们。新的默认路径都相对本仓库。

## 怎么跑

在仓库根目录执行。图表和 Word 主题在 `scripts/reportlib/`，`paths.reportlib` 默认就是这个位置，不用另配。依赖见 `requirements.txt`（`python-docx`、`requests`、`matplotlib`、`numpy`）。中文字体默认找 `assets/fonts/NotoSansSC-Regular.otf`，字体文件不随仓库提供。

追踪表：

```bash
python scripts/update_tracker.py \
  --pack reports/2026-11/2026-11-10-meme-pack.json \
  --heat reports/2026-11/2026-11-10-heat.csv \
  --remix reports/2026-11/2026-11-10-remix-stats.csv \
  --cc reports/2026-11/2026-11-10-cc-hashtag-trends.csv \
  --cc-ranks reports/2026-11/2026-11-10-cc-top100-us.csv
```

`--out` 默认 `data/meme-daily-tracker.csv`。`--notes` 可选。

D+3 回测：

```bash
python scripts/backtest.py \
  --as-of 2026-11-10 \
  --heat reports/2026-11/2026-11-10-heat.csv \
  --cc reports/2026-11/2026-11-10-cc-hashtag-trends.csv
```

`--tracker` 默认 `data/meme-daily-tracker.csv`。`--heat` 和 `--cc` 可以重复传入。`--json-out` 和 `--csv-out` 默认写到 `data/backtest-latest.json` 和 `.csv`。

日报 Word：

```bash
python scripts/build_report.py \
  --date 2026-11-10 \
  --pack reports/2026-11/2026-11-10-meme-pack.json \
  --md reports/2026-11/2026-11-10-daily-report.md \
  --cc-csv reports/2026-11/2026-11-10-cc-top100.csv \
  --remix-csv reports/2026-11/2026-11-10-remix-stats.csv \
  --heat-json reports/2026-11/2026-11-10-heat.json \
  --cc-trends-csv reports/2026-11/2026-11-10-cc-hashtag-trends.csv \
  --backtest-json data/backtest-latest.json
```

不传 `--out-docx` 时写到 `reports/2026-11/2026-11-10-daily-report.docx`。不传 `--chart-dir` 时 PNG 写到同一个月份目录，文件名带日期前缀。

梗包（把当天后补的证据合并进样例包用的那份结构）：

```bash
python scripts/build_meme_pack.py
```

它读 `2026-11-10` 的 `meme-pack-base.json`、`heat.json`、`cc-hashtag-detail.json`、`new-memes.json`（或旧文件名），写出 `reports/2026-11/2026-11-10-meme-pack.json`。没有这些输入时不要跑它，仓库里的样例包已经是成品。

Lark 默认关闭。下面这条命令只会提示同步未开启，不会写批次：

```bash
python scripts/sync_lark.py --as-of 2026-11-10
```

打开同步：

```bash
python scripts/sync_lark.py --as-of 2026-11-10 --sync-lark \
  --existing-keys data/lark-batches/2026-11-10-existing-keys.json
```

也可以复制 `config/settings.example.yaml` 为 `config/settings.yaml`，把 `sync_lark` 设为 `true`。`--no-lark` 强制关闭。`sync_lark.py --schema-only` 只打印表名，不要求打开同步。`--existing-keys` 给去重键列表时跳过这些行；给「去重键 → record_id」时，追踪、回测和日报索引会另写更新批次。批次在 `data/lark-batches/`，该目录不入库。真正写入 Lark 仍走用户的 Lark 连接器，仓库里没有应用密钥。

Google Ads 关键词（Keyword Planner）。凭证从环境文件读取，脚本本身没有参数：

```bash
python research/ads_keyword_smoke.py
python research/ads_keyword_research.py
```

输出在 `research/output/`，不入库。环境文件路径依次是 `$GOOGLE_ADS_ENV_FILE`、`config/settings.yaml` 里的 `google_ads.env_file`、`/home/box/.secrets/google_ads.env`、`~/.secrets/google_ads.env`。

## 凭证

Google Ads OAuth 和 Lark 登录凭证都不放进仓库。根目录 `.env.example` 只有四个空字段：`GOOGLE_ADS_CLIENT_ID`、`GOOGLE_ADS_CLIENT_SECRET`、`GOOGLE_ADS_REFRESH_TOKEN`、`GOOGLE_ADS_CUSTOMER_ID`。把填好的文件放在上面的 secrets 路径，不要提交。

`config/lark-base-schema.json` 里的 Base id 是多维表格 URL 上的标识，不是密钥。Keyword Planner 脚本里写死的 customer id 是查询使用的账号编号，不是 OAuth 密钥。

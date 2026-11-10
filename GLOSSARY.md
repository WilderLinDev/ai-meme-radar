# AI meme radar

每天回答一个问题：海外短视频里，今天哪个 AI 视频梗值得做成模板。代码标识符用英文，报告显示用中文；本文件是中英对照的唯一来源。

## 梗

**Meme（梗）**:
一种可被复用、可做成 AI 模板的短视频格式，是唯一的评分单位。
_Avoid_: trend, format, 话题

**Meme id（梗 ID）**:
梗在 Meme registry 里的唯一短名（如 `shoulder-carry`），跨天不变。
_Avoid_: canonical_id, remix_key, name

**Meme registry（梗名册）**:
所有已知梗的身份清单：ID、显示名、别名、关联话题、主热度口径。没登记的梗不存在。
_Avoid_: aliases, 别名表

**CC hashtag（CC 话题）**:
TikTok Creative Center 上的一个话题标签。它是梗的证据，不是梗本身。
_Avoid_: tag meme

**Primary heat metric（主热度口径）**:
登记时为每个梗固定的那条日热度序列，回测只看它。取值 `viralremix_new_videos`、`x_posts`、`cc_index_30d`、`none`。

**Early signal（早期信号）**:
刚起步、证据还少的梗；仍是 Meme，只是在日报里归入早期信号部分。

## 产出

**Verdict（结论）**:
对一个梗今天该不该做模板的判断，取值 `make`（做）/ `watch`（观望）/ `skip`（不做）。
_Avoid_: decision, recommendation, 建议

**Suggested verdict（建议结论）**:
按总分和窗口分门槛机械推出的结论。

**Override（否决）**:
Agent 给出的 Verdict 与 Suggested verdict 不同；必须附理由，并在日报里写明。

**Judgment（判断）**:
Agent 为一个梗写下的主观部分：五项分与理由、窗口、结论、是什么、怎么做、风险。
_Avoid_: scores file, 打分稿

**Daily decision（每日判断）**:
某一天对所有候选梗给出的 Verdict 集合，是本项目唯一的核心产出；其余一切都是它的证据或复核。
_Avoid_: digest, 日报（日报只是它的呈现形式）

**Meme pack（梗包）**:
某一天 Daily decision 的唯一结构化真源；Markdown 和 Word 日报都只是它的渲染结果。
_Avoid_: pack v5, base pack, digest json

**Report（日报）**:
由 Meme pack 渲染出的阅读版本（Markdown / Word），不含任何 Meme pack 里没有的信息。
_Avoid_: digest

## 评分

**Score（评分）**:
一个梗当天的 0–100 分，恰好等于五个 Dimension 分之和。

**Dimension（分项）**:
评分的五个 0–20 分项之一：`heat`（热度）、`trend`（趋势）、`share`（分享率）、`competition`（竞争）、`window`（窗口）。
_Avoid_: sub-score, 子分

## 证据

**Raw snapshot（原始快照）**:
某一天从某个来源抓到的原始数据，写入后不再修改。
_Avoid_: dump, run2, 抓取结果

**Gap（缺口）**:
当天应该拿到但没拿到的数据，连同原因一起记录；缺口不插值、不当作 0。
_Avoid_: missing, 空值

**Evidence tag（数字标注）**:
每个数字必须带的可信度标记：【已核实】、【第三方读数】、【估算】。

## 历史与复核

**Tracker（追踪表）**:
每个梗每天一行的累计历史，用于日环比和长曲线。
_Avoid_: history, 往期

**Backtest（回测）**:
在 D+3（自然日）用主热度复核第 D 天的 Verdict 是否站得住。
_Avoid_: 回查, validation

**Backtest result（回测结果）**:
`hit`（对）、`miss`（错）、`pending`（D+3 未到）、`insufficient`（数据不足）四者之一。

**Make streak（连续推荐）**:
同一个梗连续多天被判 `make`；只有首日计入命中率。

**Hit rate（命中率）**:
`make` 首日推荐中 hit 占 hit + miss 的比例。

**Missed rate（漏判率）**:
判为 `watch` 或 `skip` 的梗中，D+3 主热度仍明显上升的比例。
_Avoid_: false negative

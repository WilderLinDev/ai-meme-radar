# AI Meme Radar 术语表

每天发现正在扩散的互联网趋势，弄清它背后可复用的内容格式，判断哪些格式值得做成 AI 视频、图片或音频模板。代码标识符用英文，报告用中文；本文件是中英对照的唯一来源。

## 研究对象

**Trend（趋势）**:
正在扩散或刚出现的一股内容潮流，如某种 AI 宝宝跳舞视频。可以有早期信号，也可以已经退潮。
_Avoid_: meme（梗只是趋势的一种）, hashtag, topic

**Format（格式）**:
趋势背后可复用的内容或交互模式：用户给什么输入、得到什么输出（如「上传一张人像照片，生成跳舞视频」）。一个格式可对应多个趋势。
_Avoid_: template（模板是产品，格式是模式）

**Template opportunity（模板机会）**:
可以做成产品的具体机会（如「宝宝跳舞 AI 模板」）。一个机会可利用多个格式。代码里简称 opportunity。
_Avoid_: idea, product

**Entity ref（对象引用）**:
`kind:id` 形式的引用，kind 为 trend / format / opportunity / keyword / site。趋势、格式、机会的 id 为永久不变的 kebab-case。

**Link（关联）**:
两个对象之间的一条有向关系（uses、enables、drives、searched_as、targets、competitor、related、variant_of）。只追加事件，不覆盖；当前关联为每条关系的最后一个事件。

## 渠道与证据

**Channel（渠道）**:
四条并行研究渠道之一：social（社交趋势）、search（搜索需求）、product（产品与网站发现）、market（市场数据）。

**Evidence（证据）**:
一条带出处的观察：来源、链接、指标、数值、地区、样本量、指标口径、采集时间、可信度、数字标注，可选引用某次 API 调用。
_Avoid_: data point, 截图

**Evidence tag（数字标注）**:
每个数字必须带的标记：【已核实】（亲眼读到或接口原样返回）、【第三方读数】（第三方估算或口径不透明）、【估算】（我们推算的）。

**Research day（研究日）**:
一条记录所属的那一天（字段 `day`）。只能在当天写入新的研究内容；对过去或未来研究日的新写入会被拒绝。

**Observed at（观察时间）**:
原始观察发生的时间：证据的 `collected_at`、回测结果的 `outcome_at`、人工反馈里用户填写的 `at`。它不证明数据库当时已经知道。

**Ingested at（入库时间）**:
记录真正进入 `radar.db` 的时间（Asia/Shanghai 墙钟）：`ingested_at`、评估的 `created_at`、关联事件的 `at`。历史报告只看入库时间：D 日报告只用 D 日结束前入库的内容。

**Gap（缺口）**:
应拿到但没拿到的数据及原因。缺口不插值、不当作 0。

**Candidate（候选）**:
Python 从搜索、产品、市场数据里找到的、与 AI 创作相关的线索，按共享关键词或域名合并成组。候选不是判断。

## 哥飞数据

**Ge Fei catalog（哥飞接口目录）**:
从 `/api/v1/tools` 与 `/api/openapi.json` 实时读取的全部可调用接口，分组 data（数据服务）、composed（聚合分析）、raw（原始数据）、method（方法论与知识库），以及 account。

**Data service（数据服务）**:
四类批次数据：新词（keywords）、新站（launches）、网站发现（hosted）、收入数据（revenue）。不扣 SEO 积分。

**Sync unit（同步单元）**:
同步的最小可续传单位：一个批次详情、一个 28 天快照或一份收入报告。状态 done / failed / locked。

**API call record（调用记录）**:
每次调用的参数、URL、状态、requestId、实际扣除积分、时间与完整响应 JSON。

**Snapshot（快照）**:
规范化表里的一行历史记录，只有内容变化时才新增。

## 判断

**Assessment（评估）**:
Agent 对一个趋势或模板机会某天的判断：四项独立属性、七个维度、理由、假设与待解决问题。每次修改新增一个版本（revision），从不改写。
_Avoid_: score, verdict

**Lifecycle（生命周期）**: early_signal 早期信号 / emerging 上升期 / proven 已验证 / fading 衰退期。

**Decision（决策）**: build 立即做 / validate 验证 / monitor 观察 / skip 不做。

**Priority（优先级）**: P0 / P1 / P2 / P3。

**Confidence（证据可信度）**: high 高 / medium 中 / low 低。说的是证据够不够，不是机会好不好。

**Dimension（维度）**:
七个各自独立判断的维度：social_momentum 社交势能、search_demand 搜索需求、audience_participation 用户参与、template_potential 模板潜力、ai_feasibility AI 可行性、competition 竞争强度（高 = 拥挤）、timing 时机。取值 high / medium / low / unknown。没有总分。

**Key opportunity（重点机会）**:
决策为 build 或 validate，或优先级为 P0 / P1 的模板机会。每个都有深度研究报告。

**Tracked series（跟踪序列）**:
评估时固定下来、供回测判断的一条序列（某对象某指标某地区的证据序列，或某哥飞关键词的 heat_ratio）。

**Frozen snapshot（冻结快照）**:
评估入库时保存的事实、跟踪序列与基线值。回测只用它作基线。

**Feedback（人工反馈）**:
人对决策、优先级、生命周期、关联或研究方向的修改，附理由与作者。只追加；Agent 原始评估保留。

**Effective state（当前状态）**:
最新评估叠加其后的人工反馈得到的状态，并标明每项来自谁。

## 复核与交付

**Lifecycle backtest（生命周期回测）**:
7 天后跟踪序列是否按生命周期预期的方向（上升 / 持平 / 下降）变化。

**Decision backtest（决策回测）**:
14 天后跟踪序列是否支持当时对模板机会的决策。

**Daily report（日报）**:
本地 Markdown，聚焦变化与行动；未变化的对象只写一行。

**In-depth report（深度报告）**:
每个重点机会一份的 Markdown 研究报告，按生命周期调整研究重点。

**Lark document（飞书文档）**:
报告的发布副本。日报每天一份；每个重点机会一份并持续更新。本地 Markdown 为准。

# billion-context vs Neurova 上下文压缩机制代码级对照测评（2026-11-14）

> 对象：[ranxianglei/billion-context](https://github.com/ranxianglei/billion-context)（v0.1.213，含内嵌 acp-kernel），
> 克隆快照逐文件通读；对照本仓 `neurova/context/` 上下文压缩链路 + `neurova/context_pool.py` **活水上下文池**。
> 性质：只读测评，不含任何代码改动。改进项均给出影响面，待拍板后另立工单。
> **v2（同日增补）**：应用户要求，把「活水池」纳入测评对象——不是孤立看压缩，
> 而是评"压缩 × 活水池 × 语义召回"的有机整体；新增 §2.5/§2.6/§3.5、九维打分与协同改进项 B9–B13。

---

## 0. 结论先行

**总分（九维）：billion-context 8.7 / Neurova 7.3**（v1 八维口径为 9.1 vs 7.2）。

- **只看"窗口内压缩"，billion-context 明显领先**（§1–§4）：模型自决（4 个上下文工具）、
  增量折叠（growth-gate，每段内容一生只折一次）、前缀缓存第一（append-only，实测 90–94% 读占比）、
  成文教义、T1→T2→T3 递归蒸馏，且有 4.5 个月生产数据与第三方 1500 项基准背书。
- **把"活水池"算进来，格局反转了一半**：billion-context **没有外部上下文池**——它的一切
  （近期区 + 摘要块）都在窗口内，召回靠模型主动调 `search_context`/`decompress`/`acp_retrieve`，
  其论文自认"模型不会自发使用恢复工具"。Neurova 的活水池是**窗外无损归档 + 被动语义召回**：
  原文永入池（SQLite WAL+FTS5 写穿），每轮按当前输入自动取回相关历史（向量匹配 0.65 相关性门槛 +
  词法粗筛 2000 候选上限 + 分层预算 + 配对完整性校验），**不依赖模型自觉**——这恰好是
  billion-context 的结构性短板。信息保留率口径下：Neurova 池归档 R∞=100%，billion-context 块级 ρ₁≈1/8。
- **Neurova 的独有定位 = "窗内压缩 + 窗外活水"的双层体系**：折叠只动视图，原文在池里随时可被
  语义召回或确定性下钻（`covers_ref`）；折叠省下的预算与召回预算单源联动（`_retrievalBudget`），
  不会"折叠省的被召回吃回"。billion-context 没有这层，Neurova 也没有它的"模型自决 + 缓存经济"。
  **两者高度互补，不是同一件事的两个版本。**
- 因此改进方向不是"把 Neurova 改成 billion-context"，而是：**补上模型自决工具面与缓存经济（B1/B2/B5/B6），
  同时把活水池的独有优势做深（B9–B13）**——让"压缩进池、按需取水、模型主动调用"三件事彼此增强。

---

## 1. billion-context 代码级理解

### 1.1 形态与架构

TypeScript + Node.js，321 个源文件约 17 万行；核心压缩引擎 **acp-kernel** 内嵌于 `kernel/`（约 2.6 万行，纯 TS、零宿主依赖、无 I/O，state 进出皆显式传参）。它以**中间代理/插件**形态坐在任意 agent 与模型 API 之间，改写 Anthropic / OpenAI Chat / OpenAI Responses 三种 wire 协议的请求/响应流，支持 20+ 客户端（Claude Code、Codex、OpenCode、Gemini CLI、Kimi、Qwen 等）。

分层（`kernel/DESIGN.md`）：

```
CORE（纯核）：processTurn / applyCompression / resolveBoundaries /
             decompress / search / status / decideNudge
ADAPTER（每宿主一个薄适配器）：喂消息、持久化 state、渲染 nudge、注册工具
```

每轮管线（纯函数节点序）：`assign-refs → sync-blocks → merge-blocks → prune → ccr-store → filter → hide-compress-calls → nudge-inject → emergency-truncate → render-refs`（`kernel/src/pipeline.ts`）。

### 1.2 核心机制：模型驱动的增量分层压缩

**（a）模型自决。** 代理向会话注入 4 个工具（`kernel/src/compress-tools.ts`），由模型自己调用：

| 工具 | 作用 |
|---|---|
| `compress` | 把一段消息区间折叠成摘要（代理在服务端执行折叠，历史中该区间被摘要块替换） |
| `decompress` | 需要精确细节时还原区间（块级谱系可整批还原） |
| `search_context` | 对摘要块 + 可见消息做关键词检索 |
| `acp_status` | 上下文构成分解（system/tool/summary/text）+ 可压缩区间清单 |

另有 **CCR**（`kernel/src/ccr.ts`，content-cached retrieval）：超大工具结果（≥4000 token）到达即一次性存入 per-session 内容库，线上只留确定性占位符（kind/size/preview/ref），模型经 `acp_retrieve` 取回原文；超过内联阈值的导出为宿主文件（decompress-to-file），保住 KV 前缀。replace-once-at-arrival 保证占位字节不变 → 前缀缓存稳定。

**（b）增量折叠（growth-gated nudge）。** `decideNudge`（`kernel/src/compress.ts:2161`）是需求侧触发核心：注入提醒需同时满足 **占用下限**（默认 ≈0.45 窗口）**∧ 距上次压缩的增量增长 ≥ 门槛**（默认 50K，有效下限 22.5K）**∧ 存在 ≥ 最小区间的可折质量**。于是每次折叠只处理"上次压缩以来新增的已消费增量"，任何一段内容一生只被折叠一次；压缩成本是 O(增量) 而非 O(历史)。配套六条力学（论文 §4）：增量限流、**不向模型披露占用百分比**（防锚定拒绝压缩）、**模型可拒绝**（拒绝是质量阀不是失败）、压缩瞬间对源内容全注意力（compress 调用完成后即从上下文隐藏）、推荐区间带真实 token 数、每条消息有稳定 ref（`mNNNNN`）。

**（c）分层多代（pagoda）。** `CompressionBlock` 带 `tier ∈ {1,2,3}`、`generation ∈ {young,old}`、`survivedCount`（`kernel/src/state.ts:89` advanceSurvival 晋升）。T1 折消息区间；T1 质量堆积后 T2 把**块**再蒸馏（~1/4）；T3 再凝缩（~1/3）。`effectiveMessageIds` 传递性覆盖全部原始消息，谱系在任意再压缩后仍完整。效果：摘要质量随层数逐级衰减增长，单会话容量随会话长度**亚线性**消耗窗口（论文 §7 模拟：1M 窗口可承载 ~28.6B 累计输入 / 106 天）。

**（d）成文教义（doctrine）。** `kernel/src/compression-rules.ts` 把"什么必须逐字保留、什么该丢、丢不起时按什么优先级"写成版本化规则文本，随内核一起发版；任何宿主覆盖须经 `resolvePrompts({acknowledgeRisk:true})`（`kernel/src/prompts.ts:69`）——把 prompt 当代码管理。KEEP 类：带行号的完整路径、函数/类签名与承重代码行、错误原文、决策及理由、精确值、用户意图（带 ref 的逐字引用）、目标演进、开放目标（Open objectives 逐代携带）、媒体再访问句柄。DROP 类：已提取结果的冗长日志、重复读取、已消费的探索、死路（但保留一行教训）、达成结论前的往返。优先级：目标 > 决策+理由 > 精确工件 > 结论 > 教训。

**（e）安全阀。** emergency nudge（占用 ≥95%）、emergency-truncate 节点（生产 4.5 天 0 次触发）、preflight 主动压缩（模型从 1M 换到 260K 窗口时先折再转发）、受保护区（最近区/最后用户消息/首条用户消息硬钉住/压缩调用本身硬保护）、phantom-pressure 守卫（本地估算不触发紧急重写，防"按虚数毁内容"，`compress.ts:2174-2211`）、absorb-debt 银行（频繁中断会话的增长记账）。

### 1.3 证据面（论文 §6/§8 + 第三方基准）

- 生产纵向：4.5 个月、174,327 次调用、累计输入 18.76B token，204,800 窗口模型 **0 次越窗**，峰值 198,628；马拉松会话 8,584–12,049 次调用；cache 读:输入 ≈ 9.7:1，活跃节奏下读占比 94.2%。
- 质量机制实证：压缩输出中位数 185 token、97.5% ≤2K；工具主导块压缩比中位 24×；T2 再蒸馏仅触及 3.5% 的块（安全阀非常态）。
- 受控实验：计费 token −31~54%，重取回调用 −63%，召回探针与全量上下文持平；相位结构化负载下默认调优全轴最优。
- 第三方 1500 项基准：ContextBench 第一（Utilized F1 0.3097，成本 −58.3%）、LongMemEval-S 较最优 RAG +16.6%、MemoryAgentBench 1.48M-token TTL 场景 100% 存活。
- 论文自认局限：单用户观察性研究、受控 RQ1–RQ4 仍在计划、探针饱和、教义英文中心、**模型不会自发使用恢复工具**。

---

## 2. Neurova 现状（代码级）

### 2.1 压缩链路

权威链路：`neurova/agent/chat_pipeline.py`（六步管线）→ `neurova/context/orchestrator.py` `build_context`（L1183）。

| 层 | 位置 | 机制 |
|---|---|---|
| 窗口折叠 | `orchestrator.py` `_apply_window_budget` L2422 → `window_compactor.py` `compact_window` L238 | 视图 token > 窗口预算（≈窗口×36%）时触发：尾部保留 + 头部老消息 LLM 增量折叠；递进比率 0.5→+0.1 收敛；每轮摘要调用预算 1 次 |
| 增量摘要 | `summarizing_compressor.py` | previous_summary + chunk 的增量摘要；factsheet 防幻觉 + 单次 repair；失败保留旧摘要；新增 ≤4 条复用旧摘要不重调 |
| 分代/阶梯 | `orchestrator.py` `_advanceFoldGeneration` L649；`fold_resolution.py`（1:4:16 几何退避）；`fold_index.py`（covers 单源） | 旧摘要逐次降层；视图按距离多档概览；深档经 `covers_ref` 确定性下钻；`fold_integrity.py` 零丢失对账 |
| microcompact | `orchestrator.py` `_clear_old_tool_results` L2120 | 工具结果载荷 > max(8000, 窗口×0.5) 时旧结果换 `call=<id>` 指针占位 |
| 信封 | `context/envelope.py` | 记忆/经验/情感等注入打包成瞬态 `<system-reminder>` 挂末条 user 消息（不入历史，**保前缀缓存**）；超预算按固定序整块淘汰 |
| 经济性闸 | `context/compression_economics.py` | 三态判据（划算/安全线让步/不动作+原因），默认关（只观测） |
| 计量 | `context/token_estimator.py`（tiktoken o200k + 回退上界）+ `WindowTokenMeter` | 全仓单源；未校准则压缩闸不生效 |
| 触发 | 系统自动（预算阈值）+ 用户命令 `/compact`（`chat_pipeline.py` L1002 → `orchestrator.manual_compact` L2597） | **模型无压缩参与权** |

### 2.2 活水池本体（`neurova/context_pool.py`，1642 行）

设计文档：`docs/01-architecture/living_context_pool_design.md`（水池比喻：水源→去重+标签→池→向量匹配→按需取水）。

- **归档契约（永不丢失）**：`max_size` 已失效不驱逐；`resident_limit` 可选常驻上限（移出的进台账可召回）；`ledger_db`（`eviction_ledger_db.py`，SQLite WAL+FTS5）在写入咽喉 `add_context` **写穿**持久化——生产 `resident_limit=None`、`ttl_seconds=0`，即"原文全量、永不过期、跨重启可召回"（`context_pool.py:51-73` 回收契约）。
- **三层隔离**：user/agent/session 隔离 + `turn_scope`（direct/room）作用域标签，写入咽喉统一打标（`_inject_isolation_tags`）；召回侧经 `filter_by_scope` 二次闸口（orchestrator L1577）。
- **入池组件**：`ContextCollector`（收集）、`ContextConverter`（转换）、`AutoTagger`（来源标签 + 正则关键词模式打标）、`DriftSafeDeduplicator`（去重）。
- **出池组件**：`SemanticMatchDrawer`（向量语义取水器）+ `query()`（分区索引直取：source/session 分区 O(k)、关键词、tags、当前会话优先+跨会话兜底）+ `recall_evicted()`（内存台账+FTS 持久台账双源合并）+ `drilldown()`（`covers_ref` 确定性下钻折叠层）。

### 2.3 按需取水（draw）的完整路径

`draw(need, budget_tokens)`（`context_pool.py:1511`）：

1. **取数**：collect 全量 → TTL 过滤 → **排除折叠层索引节点**（`fold_index.isIndexNode`——摘要层只走确定性寻址，防"折叠摘要被再召回一次"与跨会话泄签，T-11b）；
2. **去重**：`DriftSafeDeduplicator` 精确 hash + 同源 hash 两阶段（`dedup.py:23`）；
3. **语义取水**：`SemanticMatchDrawer.draw`——零编码词法粗筛收敛候选（≤`CANDIDATE_LIMIT`=2000，`eviction_ledger_db.py:106`）→ 单趟打分（`ScoringContext.build`：need 编码 1 次、候选各 1 次、余弦批算；向量失败降级关键词刻度并告警）→ 综合分 = match 0.5 + freshness 0.2（按 `created_at` 指数退火×来源倍率）+ priority 0.2 + source 0.1 → **相关性门槛 0.65**（实测校准：无关基线 0.5，短文本泄漏带 ~0.61，相关带 ≥0.64）→ 分层预算（未读 TOOL_CALL 第 1 层绝不漏，其余第 2 层）→ **整条选取不切片**（超预算整条跳过留池）；
4. **配对完整性**：`validate_pairing` 剔除孤儿 TOOL_CALL（`context_pool.py:1540`）；
5. **作用域过滤**：`filter_by_scope`（会话/房间隔离）。

### 2.4 池-压协同的既有咬合点（"有机结合"现状）

| 咬合点 | 位置 | 说明 |
|---|---|---|
| 先归档后折叠 | orchestrator L1458 | 折叠发生在原文入池**之后**——被折消息原文可经 `[历史回忆]` 语义召回，零丢失 |
| 当轮折叠防回吸 | orchestrator L1526-1528 | 本轮刚折叠的消息 hash 当轮不召回（freshness 高分会立即命中，折叠白做）；下轮起恢复召回 |
| 预算单源联动 | `_retrievalBudget` L2216 / `_envelopeBudget` L2239 | 召回额度 = 窗口预算 − 窗口实占 − 信封固定 − 用户输入；折叠省下的 token 不会被 draw 加倍吃回（实测事故：prompt 65920 被 draw 29 条撑爆后收口）；信封与抽屉共享同一份额度，杜绝"召回了但视图里没有" |
| 视图布局缓存友好 | orchestrator L1442-1448 | 固定 system 前缀 → 对话窗口 → 语义调取块 → 本轮瞬态 → 当前输入；调取块变化只影响尾部 |
| 折叠摘要双层寻址 | `archive_summary` L967 / `drilldown` L1099 | 摘要行入池为层节点：概率召回面排除它（防重复注入），确定性面 `covers_ref` 下钻——"语义召回走原文、精确还原走引用"分工 |
| microcompact × 池 | `_clear_old_tool_results` L2120 | 被清工具结果原文在池，凭 `call=<id>` 指针经 `recall_history` 直取 |

### 2.5 与压缩无关但影响评测的池侧现状

- **语义去重未实装**：设计文档 §5 规划了"精确+模式+语义"三阶段 + 防漂移验证；代码 `dedup.py`（77 行）只有精确 hash + 同源 hash，`semantic_threshold=0.95` 参数收了没用——语义阶段缺位（保守取向，与设计文档自身对"LLM 漂移风险"的警惕一致）。
- **AutoTagger 较简陋**：固定 `KEYWORD_PATTERNS` 13 组 + 中文 2-4 字切词 + 英文 ≥3 字词，上限 10 个标签。
- **水滴向量无跨轮缓存**：设计文档 §6.3 规划了 `_drop_vectors` 缓存；实现里 `ScoringContext.build` 每轮对候选**重新编码**（候选 ≤2000 有界，但热条目跨轮重复编码）。
- **需求信号单一**：`draw(need=user_input)` 只用当前用户输入做匹配锚，任务状态/目标/近期助手语境不参与。

---

## 3. 逐维度对照

| # | 维度 | billion-context | Neurova | 差距要点 |
|---|---|---|---|---|
| 1 | 触发与时机 | 模型自决（4 工具）+ 需求侧 growth-gate（0.45 占用 ∧ 50K 增量 ∧ 最小区间），折叠落在任务步骤间隙 | 系统阈值（视图超窗口 36% 才折）+ 用户 `/compact`；经济性闸默认关 | **范式差**：任务感知 vs 容量被动 |
| 2 | 摘要质量纪律 | 成文教义：KEEP/DROP/优先级三类规则，版本化，`acknowledgeRisk` 门禁，生产迭代 3 轮 | 摘要 prompt 含 factsheet 防幻觉 + repair；无成文 KEEP/DROP 分类与优先级 | 规则资产化 vs 单次 prompt |
| 3 | 增量性与缓存经济 | 增量折叠 O(增量)；append-only，压缩只停用后缀；**cache 读占比 90–94%** | 摘要链增量（Δ≤4 复用）、信封瞬态化保前缀；但**头部折叠会重写视图前段 → 破坏 KV 前缀**；无 cache 命中率计量 | 成本结构性差距 |
| 4 | 分层与容量扩展 | T1→T2→T3 递归蒸馏 + young/old 晋升 + merge；亚线性容量（1M 窗 ~28.6B） | 代际栈（旧摘要降层）+ 1:4:16 阶梯（视图多分辨率）；**无摘要的递归再蒸馏** | 阶梯是"视图侧多档"，非"存储侧再压缩" |
| 5 | 无损回读与召回 | compress/decompress/search_context/acp_retrieve + decompress-to-file；块谱系完整；但**依赖模型主动调用**（自认模型不自发用） | 池归档 R∞=100%；recall 双工具 + **语义抽屉被动注入** + FTS 持久台账跨重启 + `covers_ref` 确定性下钻 | **Neurova 反超**：不依赖模型自觉 |
| 6 | 安全阀与鲁棒性 | 5+ 层阀门 + phantom-pressure/absorb-debt/dead-ref 墓碑/代理对清洗/首条消息钉住 | 硬顶 90%、失败保旧摘要、完整性对账、纯截断兜底；边界情形守卫较少 | BC 用大量生产事故喂出来的守卫更厚 |
| 7 | 工程化与实证 | 550+ 内核测试、论文、第三方 1500 项基准、/acp-cache 归因面板、4.5 月生产遥测 | 127 个 context 单测、审计文档、手动探针；**无外部基准、无 cache 遥测** | 证据链差距明显 |
| 8 | 架构可移植性 | 纯核零 I/O、state 进出显式、adapter 模式、20+ 宿主、3 种 wire | 进程内模块，与自有 agent 耦合；deep-module 纪律良好但不可移植 | 定位不同，BC 作为通用中间件胜出 |
| 9 | **外部记忆池（活水池本体）** | **无外部池**：一切在窗口内（近期区+摘要块）；检索=关键词 `search_context` + 按 ref 还原；仅单会话 scope；无语义召回、无被动注入 | **窗外无损池**：全量归档+FTS5 写穿+跨重启；向量语义被动召回（门槛校准+分层预算+配对校验+作用域闸）；三层隔离；预算与窗口单源联动 | **Neurova 结构性独有**；BC 论文对"外部记忆路线"的批评（写入期不可逆丢失）不适用于 Neurova——池存原文不抽取 |

---

## 4. 打分（v2，九维）

权重：触发时机 13% · 质量纪律 13% · 增量与缓存经济 14% · 分层扩展 9% · 无损回读 13% · 安全阀 9% · 工程实证 9% · 可移植性 10% · **活水池本体 10%**。

| 维度（权重） | billion-context | Neurova |
|---|---|---|
| 触发与时机（13%） | 9.0 | 6.5 |
| 摘要质量纪律（13%） | 9.0 | 7.0 |
| 增量性与缓存经济（14%） | 9.5 | 6.5 |
| 分层与容量扩展（9%） | 9.0 | 7.0 |
| 无损回读与召回（13%） | 8.5 | **9.0** |
| 安全阀与鲁棒性（9%） | 9.0 | 7.5 |
| 工程化与实证（9%） | 9.0 | 7.5 |
| 架构可移植性（10%） | 9.5 | 6.0 |
| 活水池本体（10%） | 5.5 | **8.5** |
| **加权总分** | **8.7** | **7.3** |

打分说明（诚实校准）：
- 相比 v1（8 维 9.1 vs 7.2），新增"活水池本体"维度后 BC 降至 8.7、Neurova 升至 7.3——**差距从 1.9 收窄到 1.4**，且性质变了：v1 的差距全在"压缩工程"，v2 揭示两家各占一个结构性高地（BC=窗内压缩自洽闭环；Neurova=窗外无损活水）。
- Neurova 活水池 8.5 而非 9.5 的扣分点：语义去重缺位（纯净性只有一半）、AutoTagger 简陋、水滴向量无跨轮缓存（池越大每轮编码成本越高）、需求锚只有 user_input、召回质量无持续读数（0.65 门槛靠一次性两点校准）。
- BC 活水池 5.5 而非更低：`search_context` + `decompress-to-file` + CCR 内容库事实上构成一个"会话内轻量池"，只是无语义匹配、无被动注入、不跨会话。
- BC 的"模型驱动"并非免费：小窗口下教义文本是 ~25% 固定开销（其论文自测）；依赖模型服从性；受控 RQ1–RQ4 仍在计划。Neurova 的"确定性保底折叠"在多用户产品形态下是优点而非落后。
- 两者定位不同：BC 是通用中间件（任何 agent 可挂），Neurova 是自家产品内的一环。可移植性维度对 Neurova 是"锦上添花"而非缺陷。

---

## 5. 可改进项（按优先级，均含影响面）

> B1–B8 针对**压缩链路**（v1 已列）；B9–B13 针对**池-压协同与活水池本体**（v2 新增）。
> 总原则：让"压缩进池 → 按需取水 → 模型主动调用"三件事互相增强，而不是各自为政。

### B1 · 模型可调用的压缩工具面（P0，范式补齐）
**做什么**：新增内置工具 `context_compress(ranges)` / `context_status()`（可复用现有 `recall_context_span` 作 decompress 语义），让模型在折叠判断上有参与权；`manual_compact` 的折叠机构（orchestrator L2597）已支持任意次折叠，代际栈/池归档/完整性与守卫全部现成。
**与活水池的协同**：模型调用 `context_compress` 折掉的区间**自动入池**（现有 `archive_summary`/归档咽喉），下一轮起即可被语义召回——"模型主动清账，池子兜底找回"，比 BC 的纯窗内折叠多一层保险。
**影响面**：`builtin_tools.py`、`tool_executor.py`、`context/orchestrator.py`、`api/endpoints/context.py`。
**不做的代价**：压缩时机永远与任务相位错位——预算阈值只能在"快爆了"的时候动作，模型明知某段已消费完也无法主动清账。
**决策点**：是否向所有模型开放（弱模型可能滥用 compress 制造低质量摘要）→ 建议按 agent 配置项灰度，默认关。

### B2 · 前缀缓存友好性升为一等约束（P0，成本结构）
**做什么**：先把 cache 命中率**测出来**（B6），再改折叠落位：折叠产物尽量以"停用尾部区间 + 稳定占位摘要"的方式呈现，避免每次折叠重写视图头部。信封瞬态化已是正确先例（`envelope.py` 设计说明明言保前缀），把同一纪律推广到折叠面。
**影响面**：`window_compactor.py`、`orchestrator.py` `_apply_window_budget`、`fold_resolution.py` 装配、provider 请求装配层（usage 里 cached tokens 透传）。
**不做的代价**：长会话每轮折叠都全量重算前缀，缓存读占比上不去；按主流定价（缓存读 ≈ 新输入 10%），这是账单上数倍的差距。
**风险**：改动触及视图装配核心，须以现有 127 个 context 单测 + A/B 自证护航。

### B3 · 成文压缩教义（P1，质量纪律资产化）
**做什么**：把 `summarizing_compressor.py` 的摘要 prompt 升级为**自研**的 KEEP/DROP/优先级三类规则（逐字保留类：带行号路径、签名与承重代码行、错误原文、决策+理由、精确值、用户意图、开放目标、目标演进；丢弃类：已提取结果的日志、重复读取、死路留一行教训；优先级：目标 > 决策 > 工件 > 结论 > 教训），版本化并加覆盖门禁。
**注意**：billion-context 的教义文本是 MIT 但**不可搬运**（本仓原创性红线）——只吸收"分类学 + 版本化 + 覆盖门禁"的形制，文本全部自写。
**影响面**：`summarizing_compressor.py`、`docs/`（教义文档落 `docs/01-architecture/` 并登记索引）、可加守卫测试钉住关键规则存在性。
**不做的代价**：摘要质量完全绑定在单次 prompt 措辞上，无法版本化迭代、无法在换模型时保持行为一致。

### B4 · 摘要递归再蒸馏（P1，容量亚线性）
**做什么**：给代际栈补上"老代合并再蒸馏"：当老代摘要行数/质量超过阈值时，把 k 条旧代摘要蒸馏成一条新代摘要（covers 谱系随之合并，`fold_index.py` 已是 covers 单源，`covers_ref` 支持指向合并后节点）。
**与活水池的协同**：被蒸馏合并的旧摘要行**原文仍在池中**，`covers_ref` 指向新节点即可，语义召回面不受影响——比 BC 的块合并多一层"原文随时可回"的保障。
**影响面**：`fold_index.py`、`fold_rollup.py`（后台 worker 已有在飞限制基建）、`orchestrator.py`。
**不做的代价**：超长会话中摘要行数随折叠次数线性增长，视图里"远档"越来越挤，1:4:16 阶梯的深档预算被摊薄。
**决策点**：再蒸馏是有损二次压缩，触发阈值需保守（BC 生产数据：T2 仅 3.5% 块被再蒸馏，是安全阀非常态路径）。

### B5 · 折叠时机与任务相位对齐（P1，触发升级）
**做什么**：把 `compression_economics.py` 从"默认关的观测闸"升级为**增长门**：占用 ≥ 下限 ∧ 距上次折叠增量 ≥ 门槛 ∧ 可折质量 ≥ 最小区间，三条件同时满足才折；与 B1 的模型自决形成"系统保底 + 模型主动"双通道。
**影响面**：`compression_economics.py`、`orchestrator.py` `_apply_window_budget` 触发点、配置项默认值。
**不做的代价**：继续在容量压力下"被迫折"，折叠必然切在任务中间，摘要质量与中断风险都差。

### B6 · 缓存命中率计量与归因面板（P2，B2 的前置）
**做什么**：从 provider usage 透传 cached tokens；`/api/v1/context/budget` 或 composition 面板增加"cache 读占比、miss 归因（TTL 过期/模型切换/重写）"读数。
**影响面**：llm 客户端 usage 解析、`context/budget_report.py`、`api/endpoints/context.py`、前端设置/监控页。
**不做的代价**：B2 改没改好无法验证；缓存异常（TTL、换模型）无法归因。

### B7 · 大工具结果"到达即收纳"（P2，microcompact 增强）
**做什么**：microcompact 目前在载荷超 max(8000, 窗口×0.5) 才清旧结果；可增加"到达即判定"——单条工具结果 ≥ 阈值时立刻入库换占位符（kind/size/preview/call ref），配 `recall_history` 的 call= 直取（已有）形成 CCR 等价闭环。
**与活水池的协同**：占位符携带的 `call=<id>` 指针本就指向池归档——BC 的 CCR 是"另建内容库"，Neurova 只需把既有池用足。
**影响面**：`orchestrator.py` `_clear_old_tool_results`、`tool_executor.py` 工具结果落账路径。
**不做的代价**：一轮里多个中等大小工具结果能把窗口顶高，触发不必要的整窗折叠。

### B8 · 保留率度量与召回探针基准化（P2，实证补课）
**做什么**：吸收"信息保留率 R(t)"作为质量指标（可恢复信息占比），把 `tests/manual/` 里的折叠探针升级为可重复的召回探针套件：合成马拉松负载（串行任务 + 深召回探针），对比 全量上下文 / 滑窗 / 现行折叠 三臂，产出自家基准数字。
**影响面**：`tests/performance/`（新基准套件）、`docs/08-research/`（结果落格）。
**不做的代价**：压缩质量主张永远只有单测与审计文档背书，无法与外部系统横向比较。

### B9 · 模型可调用的池检索工具（P1，与 B1 配对）
**做什么**：新增 `pool_search(query, source?, tags?)` 内置工具：走 `SemanticMatchDrawer` 的同一套打分（向量+新鲜度+优先级）对池做语义检索，把结果以工具回执还给模型。这是 BC `search_context` 的语义增强版——BC 只能关键词搜"窗口内摘要块"，Neurova 可以语义搜"全量归档池"。
**与活水池的协同**：把"被动注入"升级为"被动 + 主动"双通道：抽屉继续自动注入高相关历史（解决 BC 自认的"模型不自发召回"短板），同时给有能力主动检索的模型一个精确工具——两条通道打同一套分、走同一个池，不产生第二事实源。
**影响面**：`builtin_tools.py`、`tool_executor.py`、`context_pool.py`（draw 已支持 need/budget 入参，可直接复用）。
**不做的代价**：模型遇到"我记得之前查过 X 但抽屉没送上来"时只能整会话 `recall_history` 粗捞，精准性差且费 token。

### B10 · 抽屉需求锚增强（P1，取水质量）
**做什么**：`draw(need=user_input)` 的匹配锚目前只有当前用户输入。扩充为**复合需求锚**：用户输入 + 本轮检索产物关键词 + 近 N 轮对话要点 + agent 当前目标/任务状态（如有）。实现上在 orchestrator 构造 need 处（L1571）聚合，抽屉接口不变。
**与活水池的协同**：直接提升"取出来的水是有用的活水"——尤其用户输入很短（"继续""这样不对"）时，仅凭 user_input 的向量锚几乎无区分力，召回全靠 freshness 兜底。
**影响面**：`orchestrator.py`（need 构造）、可选 `semantic_drawer.py`（多锚加权）。
**不做的代价**：短输入轮次的召回退化为"最近优先"，长会话里远处的关键决策取不上来。
**决策点**：need 里是否纳入"当前任务状态"——需要先明确任务状态的权威来源（agent goal 字段还是对话推断）。

### B11 · 水滴向量跨轮缓存（P2，池规模成本）
**做什么**：补上设计文档 §6.3 规划的 `_drop_vectors` 缓存（按内容 hash 键控、LRU/容量上限、失效即弃）：`ScoringContext.build` 命中缓存不重编码。池归档只增不减，无缓存的每轮重编码会让语义取水成本随池规模缓慢爬升（词法粗筛已把单轮候选压到 ≤2000，但热条目仍逐轮重复编码）。
**影响面**：`semantic_drawer.py`（ScoringContext.build 增缓存层）、`eviction_ledger_db.py`（候选上限已有）。
**不做的代价**：活水池的"活"变成每轮全量重算——池越大、轮越多，取水越贵，与"无损归档"的定位冲突。

### B12 · 语义去重阶段落地（P2，池纯净性）
**做什么**：补齐设计文档 §5 的第三阶段——语义去重（阈值 0.95 起步，只对同 source 生效，配防漂移校验：去重前保留双方 hash 台账、可一键还原）。当前 `dedup.py` 只有精确+同源 hash，参数 `semantic_threshold` 收了没用。
**决策点**：语义去重有信息丢失与漂移风险（设计文档 §3.3 自己论证过），建议只在**写入期**对"同 source + 同轮次"的近重复生效，且默认关、灰度开。
**影响面**：`dedup.py`、`context_pool.py` `add_context`（入池咽喉）、新增还原台账。
**不做的代价**：多轮对话里同一事实的转述会持续堆积，占池、占召回名额、稀释相关性分数。

### B13 · 召回质量持续读数（P2，B8 的池侧配套）
**做什么**：给抽屉加持续遥测：每轮 draw 的候选规模、门槛命中数、注入条数、注入 token、（可回填的）被模型引用/采纳信号；`/api/v1/context/composition` 或 budget 面板曝光。0.65 门槛目前靠一次性两点校准，没有持续读数就无法发现漂移。
**影响面**：`semantic_drawer.py`（计数埋点）、`context_pool.py` `get_retention_stats`、`api/endpoints/context.py`。
**不做的代价**：门槛失准（泄漏或漏召）只能靠用户体感发现；B8 的基准数字也无法在日常运行中复验。

### 不应对标的点（防止过度学习）
1. **教义文本不可搬运**——原创性红线；只取形制。
2. **纯模型驱动不适合作为唯一通道**——BC 自证小窗口教义开销 ~25%、且依赖模型服从性；Neurova 面向多用户产品，确定性保底折叠必须保留，模型工具做增量通道。
3. **MITM 代理/证书劫持、自更新、多客户端适配**属于 BC 的分发形态，与 Neurova 产品形态无关，不引入。
4. BC 的证据是单用户观察性研究，其"零召回损失"结论受探针饱和限制——借鉴机制，不迷信数字。
5. **不要因为 BC 没有"池"就认为池是多余复杂度**——BC 的单专家用户场景不需要跨用户隔离与被动召回；Neurova 的产品形态（多用户、多 agent、长陪伴）正是池的价值场域。

---

## 6. 有机结合的落地次序建议

若拍板实施，建议按"先让两者互相看见，再让模型看见两者"的顺序：

1. **第一批（计量先行）**：B6（cache 计量）+ B13（召回读数）——两个改造的验证地基，纯只读面。
2. **第二批（结构改造）**：B2（缓存友好折叠）+ B5（增长门）——压缩侧的两个 P0/P1。
3. **第三批（模型接口）**：B1（压缩工具）+ B9（池检索工具）+ B3（教义）——模型获得"折"与"取"的完整主动权，B1 折掉的进池、B9 取的来自池，闭环即成。
4. **第四批（池本体深化）**：B10（需求锚）+ B11（向量缓存）+ B12（语义去重）+ B4（再蒸馏）+ B7（到达即收纳）。
5. **贯穿**：B8（保留率基准）在每批后复跑，产出对照数字。

---

## 7. 参考索引

- billion-context：`kernel/DESIGN.md`（内核契约）、`kernel/src/compress.ts`（decideNudge/applyCompression）、`kernel/src/compression-rules.ts`（教义）、`kernel/src/ccr.ts`（CCR）、`kernel/src/prompts.ts`（prompt 治理）、`src/preflight.ts`（预压缩）、`paper/…md`（论文 v0.2）、`benchmarks/third-party-1500/`（第三方基准）。
- Neurova 压缩链路：`neurova/context/orchestrator.py`、`window_compactor.py`、`summarizing_compressor.py`、`fold_resolution.py`、`fold_index.py`、`envelope.py`、`compression_economics.py`、`token_estimator.py`；`neurova/agent/chat_pipeline.py`；`neurova/tool_executor.py`（recall 双工具）；`docs/上下文三链路审计_2026-09-21.md`。
- Neurova 活水池：`neurova/context_pool.py`（归档契约/draw/query/recall_evicted/drilldown/archive_summary）、`neurova/context/semantic_drawer.py`（ScoringContext 单趟打分、0.65 门槛校准）、`neurova/context/dedup.py`、`neurova/context/auto_tagger.py`、`neurova/context/pool_index.py`、`neurova/context/pairing.py`、`neurova/context/eviction_ledger_db.py`（FTS5 台账、CANDIDATE_LIMIT）、`docs/01-architecture/living_context_pool_design.md`（设计文档：语义去重与向量缓存为规划项）。

---

## 8. 实施状态回执（2026-11-14 当日落地）

| 项 | 状态 | 落点 |
|---|---|---|
| B6 cache 计量断链 | ✅ 已落地 | cf23fa718：四处 usage 透传＋model_switches 归因 |
| B13 取水读数 | ✅ 已落地 | cf23fa718：抽屉八计数 → retention_stats → /context/stats |
| B2 冻结增量折叠 | ✅ 已落地 | df550bf1f：fold_trigger.splitFrozenCoveredPrefix＋frozen_head_rows 槽缓存 |
| B5 增长门 | ✅ 已落地 | df550bf1f：decideFoldTrigger（默认关，灰度） |
| B1 模型压缩工具 | ✅ 已落地 | 226a7d796：context_compress/context_status |
| B9 池检索工具 | ✅ 已落地 | 226a7d796：pool_search＋ContextPool.search() |
| B3 成文教义 | ✅ 已落地 | 226a7d796：compression_doctrine.py（v1.0.0，覆盖门禁） |
| B7 到达即收纳 | ✅ 已落地 | 2584dbeae：单条巨结果封顶 20000 token（尊重 T-10c 裁定） |
| B10 召回需求锚 | ✅ 已落地（实验位，默认关） | 2584dbeae：实测复合锚未重校准会泄过 0.65 门槛（0.633→0.685），故显式开启制 |
| B11 向量缓存 | ✅ 已落地 | 2584dbeae：抽屉实例级 LRU 4096 |
| B4 摘要再蒸馏 | ⚪ 重评估后暂缓 | T-11c 阶梯已把**视图**摘要质量按预算有界装配（超预算深档计入 dropped_levels、仍可下钻）——报告原判"视图近线性累积"不成立；池侧层行增长属归档本性。若未来池索引规模成为检索负担再立项 |
| B12 语义去重 | ✅ 已落地＋活体验证 | 2b308d4c1：写入期·同源·阈值 0.95·**默认关**（NEUROVA_DEDUP_SEMANTIC=1）；防漂移四件套=豁免面（高优先级/用户输入/系统指令/短文本）＋零丢失（判重条目仍写穿 FTS 台账可召回）＋还原台账（restoreDedup 一键还原）＋fail-open。**活体验证（2026-11-15，9527 开启 env）**：两条近重复聊天消息（相似度 0.9817）——第二条被判重不入常驻、还原台账 +1、判重面实测 `semantic_checks:18/dedup_total:8/restore_ledger_size:8`；默认关状态下恢复原状 |
| B8 保留率基准 | ✅ 已落地 | 88d4c4275：R(t) 探针基准（合成马拉松×三臂，受控摘要桩无 LLM、9.8s 可复跑）——folding 可恢复 1.0/视图 3336 token vs sliding 可恢复 0.1875 vs full 4624 token；真模型三臂对比留手动基准另票 |
| 追问批·窗口自适应时机 | ✅ 已落地 | f93290cb7：增长门增量门槛随预算缩放（max(下限, 预算×25%)）＋microcompact 绝对臂随窗口（max(8000, 窗口×10%)）＋视图预算钳顶 env 可调（NEUROVA_WINDOW_BUDGET_CAP，默认 100000 不变）——折叠时机全面随服务商提供的模型窗口自适应 |
| 追问批·A1 尺子按模型校准 | ✅ 已落地 | 2cd944ca3：完成侧净信号采样（同段输出文本的尺子估算 vs 账单 completion 真值）＋每模型累计均值（样本截尾钳 [0.5,2]）＋证据门槛的预算校准（样本 ≥5 且偏差超 ±15% 才在 _effectiveWindowBudget 除以因子）＋健康读数；A2（preflight）裁定不单独做——逐轮预算重钳＋转发前折叠已覆盖首转场景，残余风险归 A1 验收 |
| 追问批·A4 缓存画像自适应折叠目标 | ✅ 已落地（跑数据后实施） | 1c7896556：真库画像实测——deepseek-vision 命中 38%（缓存生效）、qiniu 632 calls 命中 1.2%、nex 122 calls 命中 0%（两个主力模型无有效前缀缓存）。据此：无有效缓存（样本 ≥20 且命中 <5%）的模型折叠目标 0.5→0.35（视图直接进账单，折深省真金）；缓存生效模型维持 0.5 保前缀。NEUROVA_CACHE_ADAPTIVE_FOLD=0 可关 |
| 跑数据·B5 增长门 | 📊 数据已采，维持默认关 | test_growth_gate_data_b5：40 轮/预算 20000 马拉松——门开峰值 8979 vs 门关 12736（-30%）、均值 -26%、可恢复率均 1.0，代价 +1 次摘要调用。机制有效、质量地板守住；但折叠=真 LLM 摘要调用（30s+ 级停顿），默认转正需生产流量观测（fold_trigger 健康面已可测 would-fire 率），暂维持灰度 |
| 跑数据·B10 召回锚 | 📊 数据已采，维持默认关 | test_recall_anchor_data_b10（真嵌入面）：价值面未复现——小池上纯输入锚"继续"已召回 3/3 同主题条目；泄漏面实锤——增强锚把与输入无关的近轮主题条目带进视图（泄漏 3 条 > 预算 ≤2）。维持默认关，探针留作回归 |
| B10 泄漏解法·双通道召回 | ✅ 已落地 | fac65b83a：输入通道（纯输入锚、0.65 门槛不变——近轮话题条目物理过不了门槛）＋近轮通道（近 2-3 轮要点为锚、0.75 更严门槛、预算 ×30% 封顶、[近轮相关] 标注）；两通道 hash 去重合并、同过作用域闸。真嵌入面复测：输入通道泄漏归零、近轮通道受控命中、短输入价值经标注通道兑现。附带实测：0.65 门槛在同质技术池无区分力（9/9 全过）——抽屉刻度校准债的数据实锤，归 B13 重标定票 |
| B13 抽屉刻度重标定 | ✅ 已落地 | c5e1b546e：嵌入模型刻度表（按向量面指纹 backend:model 给各模型基础门槛，bge=0.65 现值保持）＋在线基线自校准（表外模型按实测候选分最低值 EWMA 上浮门槛，基线+0.04，样本 ≥3 参与，钳 [0.6,0.85]）——换嵌入模型后门槛自动重适配；与动态收紧（最优分-带宽、同质池门控）两层互补。NEUROVA_DRAW_DYNAMIC_FLOOR=0 全关。同质池无关对 0.741-0.756 被滤、相关 0.856 保留（标定数据复现） |

验证面：context 全族 1088/1088、tools 不变量 78/78、agent 族 1722 通过（tkg 2 预存红在册）、
core 2091 通过；9527 真后端三轮换载活体均 [ERROR]=0、真聊天回合 SSE 全链完成。

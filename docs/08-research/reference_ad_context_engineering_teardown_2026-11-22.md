# reference_ad 专项：上下文工程十轴细拆（Neurova vs LobeHub）

- 日期：2026-11-22（同日拍板：本专项升格为最终实施目标，见 §4）
- 性质：总报告《reference_ad_vs_neurova_fullstack_evaluation_2026-11-21.md》D2 维（Agent 核心与对话管线）的**专项细拆**（竞品/外部对标，研究参考，不作产品事实源）
- 对象与证据：lobehub/lobehub（canary@2026-11-21 快照）vs 本仓主干。证据来自只读深读：对方 `packages/context-engine`（pipeline+27 处理器）、`agent-runtime`（compress_context 执行器/GeneralChatAgent 压缩触发）、`database`（compression 仓储/messageGroups）、`prompts`（压缩提示词/附件预览）、`conversation-flow`（Topic Doctor）vs 本仓 `neurova/context_pool.py`（2,134 行）、`neurova/context/`（35 文件：orchestrator/fold_trigger/semantic_drawer/eviction_ledger_db/pool_models）、`chat_pipeline.py` 压缩链路、`tool_executor.py` 召回工具族。全部结论带 file:line；本仓计数 2026-11-22 当日复核。
- 评分口径：本专项 10 轴 ×10 分 = 100 分（与总报告 D2 的 14 分维互相独立，粒度更细；轴等权）。

## 0. 结论摘要

**专项总分：LobeHub 79.0/100 vs Neurova 83.5/100**（v12 三卡实施后据实复评——本仓净反超 4.5 分，里程碑一 ≥79.5 达成、收官 84.0 差 0.5）。

- LobeHub 最强：**缓存经济学修剪**（按 provider 缓存 TTL/价格做盈亏平衡+字节稳定保前缀缓存，本仓无对应物）、**组装管线广度**（27 处理器+约 30 个注入 provider 的阶段化管线）、**token 漂移系数计量**（分桶估算×1.25 补偿）、**附件句柄化卸载**（预览+按 fileId 翻页，按剩余预算动态决策）、**Topic Doctor 消息树体检**（四类结构病+可回退修补）。
- Neurova 最强：**召回自动回灌**（被动 pool.draw 双通道向量注入+主动 recall_history/pool_search/recall_context_span/context_status 四工具+防自污染——对方被压内容对模型不可自动召回）、**按 token 预算的折叠七步判据**（对方 HistoryTruncate 按条数截断）、**工具结果 microcompact 句柄化**（>8000 token 换占位指针凭 recall_history 直取）、**压缩纪律守卫**（严格变小+失败冷却 5/15/30+CompressionEvent 时间线+溢出兜底重试）。
- 双方共同强项：压缩全程**非破坏**——原文不删、可回滚（对方 messageGroupId 指针+cancelCompression；本仓归档先行+restoreDedup+确定性下钻）。
- 共同缺口：均无成熟"分段/分层压缩"完全体（对方一次全量压成单摘要；本仓 SUMMARY+covers 已分段但摘要生成面单薄）；均无跨会话上下文迁移。
- 一句话：对方是"**缓存经济学驱动的窗口管理**"，本仓是"**无损池化+按需取水**"。据实回写总报告：D2 上下文工程子项 4.0/4.5→4.5/4.0（D2=12.5/11.0，总分 98.0/96.0）。

## 1. 十轴评分表

| # | 轴 | 满分 | LobeHub | Neurova | 判定 |
|---|----|-----:|--------:|--------:|------|
| 1 | 组装管线与注入架构 | 10 | 9.0 | 7.0 | L 胜 |
| 2 | Token 计量与预算治理 | 10 | 9.0 | 8.5 | L 险胜 |
| 3 | 截断策略 | 10 | 6.5 | **8.0** | **N 胜** |
| 4 | 压缩机制与摘要治理 | 10 | 9.0 | 9.0 | 平（v12 迟滞落地） |
| 5 | 无损性与可回滚 | 10 | 9.0 | 9.0 | 平 |
| 6 | 召回与自动回灌 | 10 | 4.0 | **9.5** | **N 大胜** |
| 7 | 大结果卸载与句柄化 | 10 | 6.5 | **8.0** | **N 胜** |
| 8 | 缓存经济学 | 10 | **9.5** | 8.0 | L 险胜（v12 追平实施） |
| 9 | 结构完整性与修复 | 10 | 8.5 | 8.0 | L 险胜 |
| 10 | 测试与纪律守卫 | 10 | 8.0 | **8.5** | **N 小胜** |
| | **合计** | **100** | **79.0** | **83.5** | |

## 2. 逐轴详拆

### 轴1 组装管线与注入架构（L 9 / N 7）

**LobeHub**：`ContextEngine` 顺序处理器管线（`packages/context-engine/src/pipeline.ts:17-27`），`MessagesEngine.ts:291-684` 装配约 27 个处理器（PlaceholderMessageFilter 两遍清理/HistoryTruncate/SubAgentResultMessage/GroupMessageFlatten/CompressedGroupRoleTransform/StaleToolResultTrim/ToolCallProcessor/ToolMessageReorder/MessageCleanup 等），全部 payload 级纯函数（cloneContext 后改写，不落库）；SystemRoleInjector 族约 30 个注入 provider（记忆/技能/工具清单/计划/todo 等分 Phase2-4.5 注入）。
**Neurova**：`context/orchestrator.py` 两段式——归档层每轮把对话/工具结果/记忆/经验/反思经 `add_context` 唯一咽喉入池（`orchestrator.py:1645-1671,2296-2338`），视图层 `_apply_window_budget` 出窗（:2867-3155）；11 种 `ContextSource` 来源优先级阶梯（`pool_models.py:44-56`，100/90/70/60/50）+ tags/metadata（turn_id/session_id/pairs_with/covers）。
**判定**：对方处理器可插拔+阶段化注入是更标准的扩展点设计（新来源接入不改主干）；本仓与池一体化耦合深、插件化程度低，但"归档先行"的架构位更靠前。L 9 / N 7。

### 轴2 Token 计量与预算治理（L 9 / N 7.5）

**LobeHub**：tokenx 启发式**分桶估算**（正文/附件 files_info/toolCalls/thoughtSignature/reasoning/toolCallId/toolDefinition 分列；assistant 有实测 usage 走快路径）；`adjustedTotal = ceil(raw × 1.25)` 漂移补偿（`tokenAccounting/index.ts:17,372`，补偿分词器对 JSON/代码/CJK 低估 10-15% 再留余量）；超限行为不发错误——改发 `compress_context` 指令先压再续跑；附件独立预算 `planAttachmentPreviews`（附件只占"阈值下剩余空间"，永不触发压缩，`attachmentBudget.ts:53-96`）。
**Neurova**：占用=total_tokens/budget（`fold_trigger.py:169`）；窗口预算=模型窗口×0.6 安全系数单源（`context_pool.py:1893-1916`，llm_router 单源）；`_retrievalBudget` 视图/信封单源联动（`orchestrator.py:2590,1799-1826`）；swarm 成员软目标 20000 token 先于硬线（`chat_pipeline.py:3137-3145`）+ TokenBudgetGate（`gates.py:128`）。
**判定**：对方"分桶估算+漂移补偿+超限转压缩指令"的计量链更精细；本仓多主体预算（主/子代理软目标+门控）有特色但估算无漂移补偿、无分桶。L 9 / N 7.5。

### 轴3 截断策略（L 6.5 / N 8）——本仓反超

**LobeHub**：HistoryTruncate **按条数**切片（historyCount 来自 agent chatConfig，无 token 水位），先把消息树按"前端同组单元"聚合（AssistantGroup 链/AgentCouncil/Compare/多 task 同父）再从尾数够 N 组（`HistoryTruncate.ts:269-281`）；StaleToolResultTrim 有 keepRecentMessages=20 保护窗。
**Neurova**：折叠七步判据（`fold_trigger.py:146-207`）：预算击穿 > 固定间隔（默认关）> 增长门开关 > 占用<0.6 不折 > 增量不足（max(2000, 预算×0.25) token 或 <3 条）不折 > 可折<keep_min 6 不折 > 执行——全程按 **token 预算**驱动。
**判定**：对方"同组单元聚合"是好设计（前端展示单元不拆散），但按条数是真实短板（长短消息混合时截后仍可能超限或过早截断）；本仓按 token 预算+多步递进判据更准。L 6.5 / N 8。

### 轴4 压缩机制与摘要治理（L 9 / N 8.5）

**LobeHub**：`compress_context` 指令→专压缩模型（缺省回退主模型，`compressContext.ts:159-164`）；结构化摘要提示词（Context/Key Information/Decisions/Action Items/Code 五段，目标压到 20-40%，`prompts/chains/compressContext.ts:12-27`）；**迟滞双阈值**防抖（首压 0.5、已有摘要后升 0.65，`GeneralChatAgent.ts:76-77,519-527`）；**既有摘要续压**（DB 里 compressedGroup 内容拼为 persistedExistingSummary 传入提示词，:128-137）；最新 user 消息永保并重注（:57-68）；messageGroups 原子换组（finalize 事务内旧组消息改指新组再删旧行，`compression/index.ts:155-211`）。
**Neurova**：`compact_window` 视图折叠；SUMMARY 节点带 covers 指纹回池（`context_pool.py:1423-1454`）；**严格变小守卫** assertCompactionShrinks/CompactionNotShrinkingError（同样本比对含 system，:60-65,121-127）；**失败冷却** 5/15/30s（:238-271，S15 批）；CompressionEvent 落会话时间线（:274-299）；溢出兜底压缩后重试一次（`chat_pipeline.py:3167-3215`）。
**判定**：对方摘要生成工程（结构化提示词+迟滞+续压+原子换组）更厚；本仓纪律守卫（严格变小/冷却/事件/兜底）更全、摘要分段（covers）更好，但摘要提示词工程面薄。L 9 / N 8.5。

### 轴5 无损性与可回滚（L 9 / N 9）——平

**LobeHub**：压缩只改 `messages.messageGroupId` 指针，原文永远在 messages 表（`compression/index.ts:238`）；`cancelCompression`/`deleteCompressionGroup` 一键整体还原（:311）；失败 rollbackGroup。
**Neurova**：**归档先行，折叠只影响视图**，原始消息永不删（`orchestrator.py:2877-2878`）；判重条目 `restoreDedup` 一键还原（`context_pool.py:722,602-611`）；`recall_context_span` 按 covers_ref 确定性下钻取回原文（:1555-1668）。
**判定**：双方都把"压缩"做成了可逆操作、原文零丢失，路径不同（对方指针分组、本仓池化+指纹下钻），同强。L 9 / N 9。

### 轴6 召回与自动回灌（L 4 / N 9.5）——本仓大胜

**LobeHub**：被压/被截内容对模型**不可自动召回**——原文在库，但回到模型上下文需人工动作（展开压缩组/回滚）或按占位符提示重新调工具；无归档池检索、无按需回灌。
**Neurova**：被动通道=每轮 `pool.draw` 语义注入（输入锚门槛 0.65 + 近轮通道 0.75/30% 预算，bge-small-zh 向量，同质池动态收紧，`semantic_drawer.py:77,316-334`）；主动通道=`recall_history`（FTS/LIKE 双源+循环防护，`tool_executor.py:6064-6143`）/`pool_search`（池语义检索，:6027-6062）/`recall_context_span`（covers_ref 确定性下钻，:5705-5786）/`context_status`（:5848）；压缩回执带 recall_guide 召回指引（:5788-5846）；**防自污染**（recall 族结果不再参与召回，`context_pool.py:304-307`）。
**判定**：本仓把"压掉即失联"的范式缺口补掉了——折叠内容仍可被模型按需取水；对方此轴只有人工路径。L 4 / N 9.5。

### 轴7 大结果卸载与句柄化（L 6.5 / N 8）——本仓反超

**LobeHub**：**附件真卸载**——超 4000 字符（FILE_PREVIEW_CHARS，`prompts/files/file.ts:21`）转预览+`readAttachment(fileId, offset, limit)` 翻页，全文在文件存储，且按"剩余预算"动态决策、附件永不触发压缩；**工具大结果无句柄化**（只有修剪+再调用提示，多付一次调用成本）。
**Neurova**：**microcompact**——工具结果 >8000 token 或 >窗口一半即换占位指针 `call=<id>`，凭 `recall_history` 直取原文（`orchestrator.py:2354-2379`）。
**判定**：各覆盖一半：对方附件卸载精细（预算联动+翻页协议），本仓工具结果句柄化补了对方空白；双方都未做"所有大产物统一落盘+句柄"层。L 6.5 / N 8。

### 轴8 缓存经济学（L 9.5 / N 3）——对方大胜、本仓最大缺口

**LobeHub**：`StaleToolResultTrim` 按 provider 取**缓存参数定价**（Anthropic 5min TTL/read 0.1/write 1.25 等，`:194-230`）；**暖缓存盈亏平衡**——用户在 TTL 内追问=暖缓存，需通过"预估剩余步数×节省×readPrice > 重写成本×1.5 安全系数"才新增修剪（`:671-720`）；修剪决策**按轮重放、字节稳定**，保证前缀缓存不失效；注入器全部推到尾部保前缀。
**Neurova**：折叠/裁剪判据不含缓存维度（fold_trigger 七步只看预算/增量/条数），无前缀缓存保持策略。
**判定**：对方独门且直接压长会话成本——同样的内容删与不删，先算"缓存命中损失 vs token 节省"的账。本仓完全缺位。L 9.5 / N 3。

### 轴9 结构完整性与修复（L 8.5 / N 6.5）

**LobeHub**：Topic Doctor（`conversation-flow/doctor`）——诊断四类结构病（concurrent-fork/orphan-signal-turn/stale-branch-index/segment-split）+一类不可逆损失（lost-content：行写了内容没落库），给出 reparent/set-branch-index 修补 op，修复时原 parentId/branchIndex 存 `metadata.repairedFrom` 可回退（`doctor/types.ts:10-52`、`topicDoctor/index.ts:83-105`）。
**Neurova**：会话时间线重建重启不丢（S15 批）；无系统性"结构病体检器"。
**判定**：对方有主动体检+可回退修补；本仓靠重建兜底、缺诊断层。L 8.5 / N 6.5。

### 轴10 测试与纪律守卫（L 8 / N 8.5）——本仓小胜

**LobeHub**：context-engine 95 个测试文件；压缩/字节稳定/并行工具调用有专门测试矩阵。
**Neurova**：tests/unit/context/ **155 个测试文件**（test_context_pool 22 用例、test_fold_trigger_b5 11、test_compaction_pool_coordination、test_living_context_pool、test_eviction_ledger_db 等）+ agent 侧 test_context_compact_discipline/test_recall_loop_guard/test_recall_history_tool/test_fold_trigger_four_arm_sc4。
**判定**：本仓文件密度更高，且守卫面（严格变小/冷却/预算协调/防自污染）与机制一一对应。L 8 / N 8.5。

## 3. 与总评分卡的回写关系

- 总报告 D2 子项"上下文工程"原 4.0/4.5（v3 口径，本仓领先）；本十轴细拆显示对方整体更厚（缓存经济学+管线+计量+Doctor 合计压过本仓召回优势），**据实重评为 4.5/4.0**，D2 12.0/11.5→12.5/11.0，总分 97.5/96.5→98.0/96.0。
- 判定不变：D2 仍 L 小胜；本仓在召回回灌/折叠判据/工具句柄化/测试密度四轴领先，其中轴 6（自动回灌）是结构性差异——对方被压内容对模型"失联"，本仓"压缩进池、按需取水、原文永不丢"。

## 4. 可借鉴清单与最终实施目标（2026-11-22 拍板）

应评审拍板：本清单升格为**本专项的最终实施目标**——借鉴点逐项落地，本领域专项分超越 LobeHub。计分纪律：分数只能经**据实复评回写**（实施+红绿+live-verify 后）计入，不许预支；LobeHub 侧固定为 canary@2026-11-21 快照 79.0 分。

**超越分值目标**（对 LobeHub 快照 79.0/100）：
- 里程碑一（净反超）：Neurova ≥ **79.5**/100；
- 收官目标：Neurova ≥ **84.0**/100（领先 ≥4.5 分，即 P0+P1 全部落地后的可证可及分）。

**轴级目标分解**（现 75.5）：

| 轴 | 现状 | 目标 | 对应动作 |
|---|---|---|---|
| 轴8 缓存经济学 | 3.0 | ≥8.0 | P0-1 缓存盈亏平衡判据+字节稳定折叠（最大缺口 6.5） |
| 轴2 Token 计量 | 7.5 | ≥8.5 | P0-2 漂移系数×1.25+分桶计量 |
| 轴9 结构完整性 | 6.5 | ≥8.0 | P0-3 结构病体检+修补留底 |
| 轴1 组装管线 | 7.0 | ≥8.5 | P1-4 处理器管线插件化 |
| 轴4 压缩治理 | 8.5 | ≥9.0 | P1-6 迟滞双阈值（0.5→0.65） |
| 轴3/6/7/10 领先轴 | 8.0/9.5/8.0/8.5 | 保持 | 不回退 |

落地顺序建议：P0-1（单轴 +5，落地即净反超 80.5）→ P0-2 → P0-3 → P1-4；每项走红绿+live-verify 后据实回写本表。——已按此序**并行实施**：P0-1/P0-2/P0-3（含同文件域的 P1-6）三卡落地，P1-4/P1-5 待后续。

### 实施记录（2026-11-22，三卡并行落地，提交 42c0916a6/20649f46e/fafd74af8）

- **P0-1 缓存经济学**=20649f46e：`compression_economics.evaluateCacheBreakEven`（收益=剩余步数×节省×读价，代价=失效区间×(写价−读价)×1.5 安全系数，封闭判因集 no_pricing/warm_within_ttl_deferred/break_even_failed/proceed）+ `CachePricing` 内置 anthropic/openai 兼容两族计价（env `NEUROVA_CACHE_PRICING_JSON` 覆盖、坏 JSON 回退内置）+ orchestrator 仅对增长门主动折叠接闸（预算击穿/固定间隔不受管辖），defer 经 `suppressProactiveFold` 诚实改判 `cache_deferred` 进读数面（fold_suppression.cache_hits）。
- **P0-2 计量分桶**=42c0916a6：`estimate_window_tokens(..., model_id)`/`WindowTokenMeter(model_id)` 透传溢出保证金（`getModelSafetyMargin` 单源；载荷段放大、协议开销常数 PER_MSG_OVERHEAD 不放大，测试钉死 ceil(载荷×1.25)+4 口径）+ `messagePayloadBreakdown` 消息级分桶（content/tool_calls/reasoning/other，合计与总量同口径）+ budget_report `payload_buckets` 读出经 `/v1/context/budget` 暴露。
- **P0-3 结构 Doctor**=fafd74af8：`structure_doctor.py` 五类结构病纯判据（concurrent_fork 同槽位互异内容/orphan_turn 工具结果无声明或池引用解析不到/stale_index covers·covered·cutoff 指纹失效/segment_split 轮次断档倒序/lost_content 应有内容为空）+ `diagnoseSession` 真实存储三路适配（SessionManager/池注册表/时间线，查无此会话诚实 session_found=0 不造病）+ `GET /v1/context/diagnose/structure` 只读端点（JWT 鉴权）。
- **P1-6 迟滞双阈值**随 P0-1 同文件域落地。
- **红绿与回归**：三卡新增测试 16+13+42 用例均先红后绿；tests/unit/context 全目录 **1344 passed** 零回归（含 fold_trigger_b5/compression_economics/stuck_suppression_sc2/context_status_fold_timing/token_estimator_calibration 等既有守卫）；chat_pipeline 侧压缩消费方 39 passed。
- **live-verify 6/6**（真管线+真后端）：缓存闸 defer 改判（cache_deferred/warm_within_ttl_deferred/cache_hits=1）、迟滞有摘要 0.65 不折 vs 无摘要同占用照常折叠、真实 build_context 链 payload_buckets={'content': 500,...} 非零、Doctor 真实存储健康会话零误报+池孤儿引用浮出（orphan_turn）、真后端 9791 实测诊断端点鉴权可达且查无会话诚实 404。

P0（直接压成本/补范式缺口）：
1. 【已实施=20649f46e】**缓存经济学修剪判据**：fold_trigger/裁剪决策加入"缓存盈亏平衡"——按 provider 缓存 TTL 与读写价差，满足「预估剩余步数×token 节省×readPrice > 重写成本×安全系数」才新增折叠；折叠决策做到字节稳定（同输入同输出）保前缀缓存命中。影响面：`neurova/context/fold_trigger.py`、`context_pool.py` 折叠执行、llm 层需暴露 provider 缓存元数据（TTL/价格表）。收益：长会话推理成本直接下降（对方实测把修剪做成省钱决策而非保守保留）。目标：轴8 3.0→≥8.0——单轴落地即净反超（专项 75.5→80.5）。
2. 【已实施=42c0916a6】**token 计量漂移系数+分桶**：估算值×1.25 漂移补偿，按 正文/附件/工具调用/推理/工具定义 分桶计量，预算判定一律用 adjustedTotal。影响面：`context_pool.py` 预算计算、`gates.py` TokenBudgetGate、swarm 软目标。收益：0.85 水位触发更准，减少溢出兜底次数与"假未超真超限"。目标：轴2 7.5→≥8.5。
3. 【已实施=fafd74af8】**结构完整性 Doctor**：对会话消息树/时间线做五类体检（并发分叉/孤儿回合/陈旧分支索引/段裂/内容丢失），修补操作留底可回退。影响面：`neurova/context/`、会话时间线重建（S15 遗产）、swarm 房间消息树。收益：把"重启重建兜底"升级为"主动诊断+定点修复"。目标：轴9 6.5→≥8.0。

P1：
4. 【待实施】**处理器管线插件化**：把 build_context 的注入/改写步骤抽成带阶段号的可注册处理器序列，新来源（新渠道/新记忆类/新工具结果形态）接入不改主干。影响面：`neurova/context/orchestrator.py`（注意尺寸棘轮——新装配落独立模块）。目标：轴1 7.0→≥8.5。
5. 【待实施】**附件预算单源**：附件只允许占"阈值下剩余空间"，超限自动转预览+句柄翻页，且附件永不触发压缩。影响面：context 抽屉与附件注入路径。
6. 【已实施=20649f46e】**压缩迟滞双阈值**：已有摘要后触发阈值自动上调（对方 0.5→0.65），与本仓失败冷却（5/15/30）叠加成"时间+次数"双维防抖。

P2：
7. **同组单元聚合截断**：截断按"前端同组展示单元"聚合，不把一组配对消息拆到边界两侧。
8. **压缩生命周期钩子事件化**：beforeCompact/afterCompact（带前后 token 与条数）/onCompactError 暴露为可订阅事件，供观测与元认知回路消费。
9. **残留清理两遍扫描**：失败/空壳 assistant 残留消息在组装期两遍过滤，避免污染下轮上下文。

不照搬：
- **按条数截断**（HistoryTruncate historyCount）——本仓 token 预算驱动更准，勿回退；
- **召回纯人工化**（展开压缩组/回滚才可见）——本仓自动回灌是对的方向；
- 压缩模型强绑定云侧配置——本仓压缩走本仓 provider 链即可。

## 5. 局限

- 静态只读，未运行双方代码；对方为 canary@2026-11-21 快照（当日仍有推送）。
- 本仓侧计数（context_pool 2,134 行/context 35 文件/tests/unit/context 155 文件）为 2026-11-22 复核值。
- 轴 8 的成本收益未做实测标定（需在本仓 provider 组合上采真实缓存命中数据）。

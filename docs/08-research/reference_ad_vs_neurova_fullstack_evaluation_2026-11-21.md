# reference_ad：LobeHub（lobehub/lobehub）vs Neurova 全方位代码级对照评测

- 日期：2026-11-21（v2：增补 D11 自我进化/RSI 维；v3：增补 D2 上下文活水池专项；v4：增补 D4 工具肌肉记忆专项；v5：多模态十轴专项细拆）
- 对象：[lobehub/lobehub](https://github.com/lobehub/lobehub)（代号 reference_ad；LobeChat 同源演进后的 agent 平台主线仓库）
- 快照：canary 分支浅克隆，版本 2.3.4，pushed_at 2026-11-21；85.9k stars / 16.3k forks；TypeScript
- 体量：124 个 pnpm 子包；ts/tsx 共 **3,777,641 行**；`*.test.*` 文件 **7,321** 个；18 种界面语言；32 条 GitHub workflow
- 定位（README 自述）："Super-Agents on Your Team"——把自主 agent 接入团队已有 IM（钉钉/飞书/企微/iMessage/Line/QQ/微信），自主干活、每周变强
- 本仓口径：Neurova 主仓（Python FastAPI 后端 + NeurUI Vue3 + 鸿蒙/安卓双端），证据由当日只读核读采集，file:line 见各节
- 性质：**竞品/外部对标，研究参考**——不作产品事实源，不引入其命名/结构与措辞

## 0. 结论摘要

**总分（11 维 120 分）：LobeHub 98.0 vs Neurova 94.0。**（v2 自进化维 L 5.5 / N 8.5；v3 活水池专项 N 上下文工程 4.0→4.5；v4 肌肉记忆专项 N 工具框架 3.0→3.5；v5 多模态专项细拆后 D8 据实重评 L 6.5→6.0 / N 3.5→7.0）

- LobeHub 是当前公开仓里**工程完成度最高**的 agent 平台之一：agent 运行时（分布式步调度/parked-resume/成本预算）、44 个全真内置工具、三档沙箱、91 家模型 provider、7,321 个测试文件、四通道桌面 OTA 发布，均为第一梯队。
- Neurova 反超的七处：**多智能体治理深度**（审批链 L0-L2/候选 CAS/依赖门控/评审相位/台账重放）、**记忆生命周期**（睡眠整理/遗忘/污染清除/纪律准入 vs 对方无遗忘无衰减）、**本体知识图谱**（对方为零）、**租户隔离的真实执行**（对方 OSS 侧 RBAC 是空壳 stub）、**MCP server 面**（对方仅 client）、**自我进化/RSI**（对方=默认关闭的受控自改进：无评测闭环、无影子/灰度、回滚靠人；本仓=门禁链+影子验证+回滚+存活探针的世代闭环）、**多模态**（v5 十轴细拆 69.0 vs 68.5 接近反超：语音双栈/屏幕视觉/OCR 本仓胜，生成广度对方胜）。
- LobeHub 领先的五处：模型接入广度（91 vs 7）、工具生态规模与执行安全分层、认证体系（17 SSO+Passkey+自建 OIDC IdP）、数据层工程（242 表 228 迁移）、工程纪律规模（e2e 性能预算/bundle 门禁/语义化发布）。多模态经 v5 细化后接近持平、本仓反超（见 D8 专项）。
- 评分不是体量加分：LobeHub 的 OSS 快照有真实短板（RBAC stub、主站 CSP 缺失、业务 API 无限流、Electron IPC 裸 socket、secret-channel 疑似未接线），均已如实扣分。

## 1. 方法与局限

- 方法：仓库浅克隆后六路并行只读深读（架构编排/工具沙箱/知识记忆/模型多模态/数据安全/工程纪律），每条关键结论须落到 file:line；Neurova 侧同日用只读核读采集对等证据（1273 个路由装饰器、2944 个后端测试文件等 15 项）。
- 评分：10 维 110 分，与仓内既往 harness 对照系列同口径；每个子项按证据给分，"待核实"不加分。
- 局限：① 静态只读，未运行对方代码；② canary 单日快照，对方迭代极快（当日仍有推送）；③ 378 万行体量下深读为抽样走读，覆盖面以六域主链路为界；④ 多模态/认证等维度部分依赖目录与类型证据，实现深度按抽读定级。

## 2. 评分卡

| # | 维度 | 满分 | LobeHub | Neurova | 判定 |
|---|------|-----:|--------:|--------:|------|
| D1 | 架构与模块化 | 12 | 10.0 | 8.0 | L 胜 |
| D2 | Agent 核心与对话管线 | 14 | 12.0 | 11.5 | L 小胜 |
| D3 | 多智能体编排 | 12 | 8.5 | 10.5 | **N 胜** |
| D4 | 工具生态与执行安全 | 14 | 12.5 | 10.5 | L 胜 |
| D5 | 知识库与 RAG | 10 | 7.0 | 6.5 | L 小胜 |
| D6 | 记忆系统 | 8 | 5.5 | 7.0 | **N 胜** |
| D7 | 多模型接入 | 10 | 9.5 | 5.5 | L 大胜 |
| D8 | 多模态 | 8 | 6.0 | 7.0 | **N 反超（v5）** |
| D9 | 数据/租户/认证/安全 | 12 | 9.0 | 8.0 | L 小胜 |
| D10 | 工程纪律 | 14 | 12.5 | 11.0 | L 胜 |
| D11 | 自我进化/RSI | 10 | 5.5 | 8.5 | **N 胜** |
| | **合计** | **120** | **98.0** | **94.0** | |

## 3. 分域详评

### D1 架构与模块化（L 10 / N 8）

**LobeHub**：pnpm monorepo 六 app（auth/cli/desktop/server/share/workbench）+ 124 包；依赖方向干净（agent-runtime 仅依赖 context-engine+types，mecha→agent-runtime+builtin-agents+builtin-tools，未见 packages 反向依赖 apps，见各 package.json）；API 双轨=tRPC 四挂载点（lambda/async/mobile/tools，`src/app/(backend)/trpc/`）+ 独立 Hono 服务（`apps/server/src/router-hono/index.ts:23-28`，standalone 端口 3011）。扣分：三轨 API（Next tRPC+Hono+mobile/tools）与根 app 巨型单体维护面大；40+ 个 builtin-tool 细粒度包需靠 mecha/database 胶水层理解，新贡献者上手成本高。
**Neurova**：领域分层清晰（api 138 端点模块/agent 106 文件/ontology 45 文件/evolution 87 文件），单进程 FastAPI 边界清楚；扣分：巨型文件集中（`neurova/agent/swarm.py` 4069 行、`evolution/rsi/orchestrator.py` 2532 行，尺寸棘轮只在守新增）、harmony 侧 41.5 万行疑含生成物。
**子项**：分层与依赖治理 3.5/2.5；API 形态与边界 3.5/3.0；复杂度控制 3.0/2.5。

### D2 Agent 核心与对话管线（L 12 / N 11）

**LobeHub**：生产级状态机 `AgentState.status = idle|running|waiting_for_human|waiting_for_async_tool|waiting_for_client|done|error|interrupted`（`packages/agent-runtime/src/types/state.ts:593-601`），parked 三态可恢复不盖 completedAt（`src/utils/status.ts:6-15`）；host 无关 step 循环（`src/loop/index.ts:37-55`），服务端 QStash 步调度+分布式锁+恢复（`apps/server/src/router-hono/agent/handlers/runStep.ts:185-215`）；指令集含 call_llm/call_tool(_batch)/exec_sub_agent(s)/request_human_prompt|select|approve/compress_context/finish（`src/types/instruction.ts:244-435`）；上下文工程=ContextEngine 25 处理器管线（`packages/context-engine/src/pipeline.ts:17-27`）+ compress_context 迟滞压缩（`agents/GeneralChatAgent.ts:513-515`）+ tokenAccounting 漂移系数 1.25。成本预算与重复调用守卫俱全。弱点：单 agent 内无 ReAct 式反思循环，反思是后台 agent（self-reflection/nightly-review）形态。
**Neurova**：增长门+主动压缩水位+溢出兜底重试+严格变小守卫+CompressionEvent 落时间线；StopGate 体系（IterationGate/TokenBudgetGate/DoomLoopGate/GoalGate，`neurova/agent/gates.py:77-394`）+ 续跑（`resumeFinishedRun` swarm.py:2321、continuation_rounds.py）；任务自评与自我模型注入（自我模型接线批）。SSE 流式管线完整。弱点：分布式调度/多实例水平扩展面弱于对方（单进程假设）。
**子项**：运行时状态机与可靠性 4.5/4.0；上下文工程 4.0/4.5；规划与反思 3.5/3.0。

#### D2 专项：上下文活水池 vs ContextEngine（v3 增补）

应评审要求，把本仓活水池与对方上下文管理单独同框。

**本仓（活水池，生产主链路默认开）**：`neurova/context_pool.py`（2134 行）+ `neurova/context/` 36 文件（orchestrator/fold_trigger/semantic_drawer/eviction_ledger_db 等）。机制链：每轮**归档先行**——整轮对话/工具结果/记忆/经验/反思经唯一写入咽喉 `add_context`（`context_pool.py:538-655`）无损入池并写穿 SQLite WAL+FTS5 台账（`eviction_ledger_db.py:57-78`，跨重启可召回）；**折叠只是视图操作，原始消息永不删**（`orchestrator.py:2877-2878`）；摘要以带 covers 指纹的 SUMMARY 节点回池，`recall_context_span` 按 covers_ref 确定性下钻取回原文（`context_pool.py:1555-1668`）；工具结果 >8000 token microcompact 成占位指针，凭 `recall_history` 直取（`orchestrator.py:2354-2379`）。召回双通道：被动=每轮 `pool.draw` 语义注入（输入锚 0.65 + 近轮 0.75/30% 预算，bge-small-zh 向量，`semantic_drawer.py:77,316-334`）；主动=`recall_history`（FTS/LIKE）/`pool_search`/`recall_context_span`/`context_status` 四工具（`tool_executor.py:5705-6143`）+ 压缩回执带 recall_guide + 防自污染（召回结果不再参与召回，`context_pool.py:304-307`）。折叠触发七步判据（`fold_trigger.py:146-207`；0.85 水位线 `chat_pipeline.py:3133-3135`）+ 溢出兜底重试 + 严格变小守卫（`context_pool.py:60-65`）+ CompressionEvent 落时间线。测试：tests/unit/context/ 160+ 文件。

**LobeHub（ContextEngine）**：约 27 个处理器全部 payload 级、不改库内原文；压缩非破坏可回滚（`markMessagesAsCompressed` 只改 messageGroupId 指针，`cancelCompression` 一键还原，`compression/index.ts:238,311`）；迟滞阈值 0.5→0.65 防压缩抖动 + 既有摘要续压 + 最新 user 消息永保；**缓存经济学修剪**是独门——StaleToolResultTrim 按 provider 缓存 TTL/价格做盈亏平衡（预估剩余步数×节省×readPrice > 重写成本×1.5 才新增修剪）且字节稳定保前缀缓存（`StaleToolResultTrim.ts:194-230,671-720`）；附件真卸载（超 4000 字符转预览+`readAttachment(fileId,offset,limit)` 翻页，按剩余预算动态决策，`attachmentBudget.ts:53-96`）；Topic Doctor 守消息树结构完整性（四类结构病诊断+可回退修补）。短板：HistoryTruncate **按条数不按 token**；**被压内容对模型不可自动召回**（原文在库，但需人工展开/回滚/重新调工具）；大工具结果无句柄化卸载；无显著性/分池机制。

**三问判定**：① 原文级找回——双方都能（原文都在存储层），但本仓**自动回灌模型上下文**（被动向量注入+主动召回工具），对方需人工动作；② 可逆降权——本仓"折叠即可逆降权"三形态成立（视图折叠原文保留/SUMMARY+covers 下钻/seen_confirmed 权重+restoreDedup），对方仅二元降档（预览/全文、修剪/原文）；③ 大结果句柄化——本仓工具结果有（microcompact 占位指针），对方附件有、工具结果无。

**子项影响**：本仓上下文工程 4.0→4.5——活水池的"自动召回回灌 + 工具结果句柄化"是对"截断+摘要"范式的结构性增量，补齐了"压掉即失联"缺口；对方的缓存经济学修剪与附件卸载亦为独门，双方各有所长，但池机制改变了被压内容的可及性。D2 合计 L 12.0 / N 11.5。

### D3 多智能体编排（L 8.5 / N 10.5）——本仓反超

**LobeHub**：GroupOrchestrationRuntime=Supervisor 状态机+Executor 循环（`packages/agent-runtime/src/groupOrchestration/GroupOrchestrationRuntime.ts:9-22`），决策 speak/broadcast/delegate/execute_task(s)（`GroupOrchestrationSupervisor.ts:24-38`）；并行子代理 exec_sub_agent(s) 带谱系 AgentRunLineage（`types/state.ts:14-40`）；异构外部 agent 接入强——heterogeneous-agents 适配 claudeCode/codex/kimiCode/codeBuddy/amp/antigravity（`packages/heterogeneous-agents/src/adapters/`）；HITL 三指令+InterventionChecker。**扣分硬伤**：投票/协商未实现（`apps/server/src/services/toolExecution/serverRuntimes/groupManagement.ts:217` "Voting is not yet implemented"），delegate 在 manifest 中被注释禁用（`builtin-tool-group-management/src/manifest.ts:66-76`）；无点对点通信；swarm 并行优化仅设计稿（`services/goal/SWARM.md:3` "Status: design, not built"）。
**Neurova**：SwarmManager（`neurova/agent/swarm.py:446`）spawn/cancelRun/cancelQueuedRun/resumeFinishedRun/steer 全链；TaskUnit（`agent/task_unit.py:22`）+审批链 L0-L2（`agent/approval_chain.py`）+依赖门控（swarm.py:1931 上游未验收→dependency_failed）+评审相位（`agent/review_gate.py`）+候选制 CAS 合并与冲突升级+H-4 事件账本与重放收敛（reconcileRunFromEvents）；房间/项目双入口；neuacp 外部代理（OpenCode/Qoder/CodeBuddy/ZCode+SSH 远程+按租户隔离的进程池）。
**判定**：对方胜在 supervisor 编排形态与外部 agent 适配广度；本仓胜在治理闭环（审批分级/候选合并/依赖门/评审/台账）与外部代理的租户隔离红线。**子项**：编排形态 3.0/3.5；治理与审批 2.5/4.0；异构外部 agent 3.0/3.0。

### D4 工具生态与执行安全（L 12.5 / N 10）

**LobeHub**：44 个 builtin-tool 全部真实现（每包 manifest+执行体，无空壳；`packages/builtin-tools/src/index.ts` 汇总），manifest 带 Zod 校验+humanIntervention+超时 clamp（`packages/types/src/tool/builtin.ts:211-289`）；双执行面（client 经 device-gateway WS+Redis 等结果，server 侧 serverRuntimes 73 文件）；MCP 仅 client（stdio+StreamableHTTP，`packages/device-mcp`，支持 MCP Apps SEP-1865 UI），**无 MCP server 面**；沙箱三档=云沙箱（market/onlyboxes）+SRT 本地沙箱（文件读写白名单+网络域名白名单+禁 PTY，`packages/device-sandbox/src/policy.ts`）+Pyodide WASM Worker；ssrf-safe-fetch 逐跳重定向过滤+体积上限（`packages/ssrf-safe-fetch/index.ts:182-213`）；凭据脱敏到 `******` 且不进模型上下文（`builtin-tool-creds/src/injectResult.ts:34-58`）；审批三层=声明式 humanIntervention+动态审计（pathScopeAudit/deleteFilesAudit 等，`builtin-tools/src/dynamicInterventionAudits.ts:13-20`）+安全黑名单 auto-run 亦不可绕过（`agent-runtime/src/core/InterventionChecker.ts:60-77`）。扣分：local-system runCommand 在用户主进程直接执行无进程级隔离（靠审批+黑名单+超时）；secret-channel HPKE 实现精良但主链路未见消费方（待核实）。
**Neurova**：ToolExecutor 单管道零旁路+curated 名册；沙箱族 `neurova/sandbox/`（code_sandbox/exec_sandbox/restricted_token/appcontainer）；凭据 keyring（`security/secret_store.py`）；webhook 验签 8 处（dingtalk/feishu/wechat_kf_crypto/telegram/qq/qclaw/xiaoyi 等）。**MCP client+server 双端**（`tool_layers/mcp_client.py`+`mcp_agent_tools_server.py`/`mcp_ontology_server.py`+`security/mcp_grants.py`）——对方没有的一半。扣分：内置工具数量与执行面规模小于对方；无云沙箱档。
**子项**：工具框架与生态规模 5.0/3.5；沙箱与隔离 3.5/2.5；MCP 2.0/3.0；凭据与审批 2.0/1.5。

#### D4 专项：工具肌肉记忆 vs 对方工具学习面（v4 增补）

应评审要求，把本仓肌肉记忆与对方"从工具使用中学习"的机制单独同框。

**本仓（肌肉记忆，默认开）**：`cognitive_layers/memory_layer/muscle_memory.py`（861 行）+ `tool_memory_integration.py`（536 行）。闭环：单源咽喉 `ToolExecutor.on_tool_executed`（`tool_executor.py:9354-9470`）记录每次工具真实成败（含 Skill 钩子与 REST 同层；治理拦截不记账防误伤）→ `MuscleMemoryItem`（工具名+查询指纹+语义向量+**上次成功参数模板**+L1/L2/L3 层级+成败计数，JSON 原子落盘按 agent 隔离）→ 每轮 pre-LLM `match_by_query`（n-gram F1×0.6 + 语义余弦×0.3 + 成功率×0.1，层内阈值 L1>0.7/L2>0.5/L3>0.3）→ 三档决策：高置信**自动执行**（免 LLM 现想参数，但仍过治理/审批，`chat_pipeline.py:1324-1394`）/ 中置信 `[工具记忆]` 建议块注入 prompt（`context/orchestrator.py:1911-1931`）/ 低置信不动作。生命周期：连击 2 次升级、30/90 天衰减、失败重置降级；防回声室（hit_only 不计成功率）、参数形状不可执行封顶 suggest、工具退役联动 do_not_execute；阈值 RSI 可调（`evolution/rsi/eval_harness.py:111-119`）。测试 79 文件覆盖。

**LobeHub（无程序性工具记忆）**：最接近的三个对应物都在"文档/观测层"——① Agent Signal 弱信号回路（同工具连续失败≥2/用户纠正≥2 → self-reflection → create/refine_skill 提案，`accumulators/selfReflection.ts:11-21`）：沉淀物是 SKILL.md 说明书，激活后整篇进 system prompt（`SkillContextProvider.ts:47-76`），靠模型"读了照做"，不改工具清单、不生成参数模板；② Expertise(SCLPT) 教训库：成熟教训单向编译为 verify_criteria（`expertise.ts:411`）——是**交付物验收判定器**，不进工具选择/参数链；③ `UsageCounter.accumulateTool` 按 byTool 记 {calls, errors, totalTimeMs}（`UsageCounter.ts:204-234`）——纯计量，无读取方反哺工具发现/排序（toolDiscovery 无 rank/score 逻辑）；agent-tracing 轨迹重放仅评测用。全仓无 tool usage/stats 表、无参数模板、无"成功调用序列固化重放"机制。

**判定**：方向上有形似者（失败信号→反思→沉淀），但对方沉淀物是"说明书"而非可执行调用模式；本仓肌肉记忆是"调用结果→结构化统计→相似任务自动取回→改变工具选择与参数→成败回流迭代"的完整程序性闭环，且自动执行不绕治理/审批。此能力对方为零。**子项影响**：工具框架与生态规模 3.0→3.5（对方仍以 44 工具规模与执行安全分层领先该子项）。D4 合计 L 12.5 / N 10.5。

### D5 知识库与 RAG（L 7 / N 6.5）

**LobeHub**：管线完整——12 个 KB 工具 API（`builtin-tool-knowledge-base/src/manifest.ts:6-295`）；文件解析两套加载器覆盖 pdf/docx/xlsx/pptx/epub/ipynb/latex/代码（`packages/file-loaders`+`apps/server/src/libs/document-loaders/`），解析在共享 worker 进程；切片=RecursiveCharacterTextSplitter 复刻，chunkSize=800/overlap=400 全局固定（`loaders/config.ts:1-6`）；异步分批 embedding 1024 维（`apps/server/src/routers/async/file.ts:112-272`）；pgvector 余弦 topK（`packages/database/src/models/chunk.ts:207-253`）+BM25 混合（ParadeDB pg_search/ES，`services/ftsSearch/index.ts:34,143`）；agent 挂载表 agents_knowledge_bases（enabled 开关）。**硬扣分**：无 rerank（`routers/lambda/chunk.ts:195` "TODO: need to rerank the chunks"）、embeddings 表仅 btree 无 ANN 索引（`schemas/rag.ts:76-96`）、无相似度阈值、文件级排序仅每文件 top3 均值、无自动 RAG 注入（纯工具触发）。
**Neurova**：本体知识图谱 45 文件（rule_engine/sparql_query/turtle·rdf_import/function_engine/decision_ledger/community_graph/vector_index，`neurova/knowledge/ontology/`）——**对方此域为零**（全仓无 ontology/KG 实现，graph 命中均为编排语义）；KnowledgeStorage+graph_bridge+端点双入口+MCP surface。扣分：文档型 RAG 的工程化（异步 embedding 任务/混合检索/评测表）不及对方系统化。
**子项**：管线完整度 3.5/3.0；检索质量机制 1.5/2.0；评测与治理 2.0/1.5。

### D6 记忆系统（L 5.5 / N 7）——本仓反超

**LobeHub**：五层记忆 activity/context/experience/identity/preference+persona（`packages/types/src/userMemory/shared.ts:48-55`）；写入经 gatekeeper LLM 过滤后按 topic 异步抽取（`memory-user-memory/src/extractors/gatekeeper.ts:12-45`）；user_memories 双 1024 维向量列带 HNSW（`schemas/userMemories/base.ts:9-57`）；实体/别名/关系边（contradicts/supersedes/mentions 等，`schemas/userMemories/edge.ts:10-53`）+consolidation 归组旧行标 superseded（`models/userMemory/consolidation.ts`）；混合召回（向量+BM25+层/标签过滤）+Locomo 基准（`memory-user-memory/benchmarks/locomo/`）。**硬扣分**：无遗忘、无时间衰减（grep decay/forget 无命中，accessedCount 只记不淘汰）。
**Neurova**：认知存储引擎（`cognitive_layers/memory_layer/cognitive_storage_engine.py:258`）+统一检索/主动召回/语义搜索；**睡眠整理**（`memory_layer/sleep.py:153 SleepConsolidation`+sleep_induction/sleep_writeback）+压缩与**污染清除**（`compression.py:58`、`pollution_purge.py`）+**纪律准入**（`memory_discipline.py:305 screenPendingProposal`、`memory_admission.py:76`）+世代失效。记忆生命周期治理（写入准入→整理→遗忘→回写）完整度高于对方。
**子项**：模型与结构 2.5/2.5；生命周期治理 1.5/3.0；召回 1.5/1.5。

### D7 多模型接入（L 9.5 / N 5.5）——差距最大维

**LobeHub**：**91 家 provider**（`packages/model-runtime/src/providers/` 目录数=runtimeMap 注册数=model-bank 枚举数，三方互证）；统一接口 LobeRuntimeAI 覆盖 chat/embeddings/generateObject/image/video/music/TTS/ASR/decision 九类（`core/BaseAI.ts:44-126`）；三大线协议（openaiChatCompletions/openaiResponses/anthropicMessages）+两个兼容工厂（589 行 `core/openaiCompatible/index.ts`），新 provider 30~60 行可接入；provider 中立流协议 ModelStreamEvent 16 类事件（`core/streams/events.ts:14-36`）；RouterRuntime 多通道路由=fallback+加权分流+attempt 级生命周期观测+错误分类续切（`core/RouterRuntime/`）；成本链路完整（usageConverters/providerReportedCost/topicUsage 落库，`core/ModelRuntime.ts:116-120` beforeChat 预算中断）；本地模型一等公民（Ollama 原生 SDK 非 OpenAI 垫片+LMStudio/vLLM/Xinference/ComfyUI）。扣分：静态模型卡仅 5 家（其余靠远端拉取+DB）；单通道内自动重试退避未见显式实现。
**Neurova**：7 provider（anthropic/gemini/openai/openrouter/ollama/lm_studio/opencode+CUSTOM，`llm/providers/types.py:16-24`）；multi_model_client chat_stream（`llm/multi_model_client.py:1086`）+capability_detector+model_rate_limiter+model_limits+presets 预设表；真流式（SSE）与成本记账已有。差距主要在广度、路由容错与协议归一层。
**子项**：provider 覆盖 4.0/1.5；协议归一与流式 3.0/2.0；路由容错与记账 2.5/2.0。

> 细分拆解（十轴逐项 + 自适应路由五级标定专论）见同目录《[reference_ad_llm_access_and_adaptive_routing_teardown_2026-11-22.md](reference_ad_llm_access_and_adaptive_routing_teardown_2026-11-22.md)》：专项口径 L 86.0 / N 70.0（/100），其中容错轴本仓反超（9.0 vs 8.5）。

### D8 多模态（L 6.0 / N 7.0）——本仓反超（v5 细化）

**LobeHub**：生成侧广度领先——图像生成 41 家 provider+完整工具链（4 API manifest、ExecutionRuntime 轮询状态机、/create/image 创作页、client/server 双执行器，`builtin-tool-image-generation/src/ExecutionRuntime/index.ts:441-587`）；视频 24 家+双层轮询+后台兜底（`videoBackgroundPolling.ts:43-60`）；音乐仅 fal 一家但产品面完整（/create/music+webhook 回调）；视觉输入协议深（parts 协议、无视觉模型占位符、SVG/AVIF 特判、工具图片回灌复查，`MessageContent.ts:132-151,552-626`）；多模态契约测试矩阵厚。**产品面断点**：TTS 有 6 家实现+完整服务端路由但聊天 UI 未接线（useBusinessTTSProvider 空桩，仅 CLI 可用）；realtime 模型纯占位（有卡片无运行时）；语音通话/RTC 无；实时听写会话端点不在仓内（云侧依赖）。
**Neurova**：语音双栈深且全线接线——TTS 3+ 引擎+流式合成+聊天流式播报（useStreamTTS）+渠道出站三形态契约（`channels/voice_egress.py`）；ASR 4 引擎+WS 流式+语音纪要+渠道入站转写（`voice_pipeline.py`）；SIP/Twilio 电话通道（无 DTMF/转接，深度中等）；AIGC 生成有实测端点矩阵——/generation/image|video|audio|text + 协议矩阵（openai-images/ark/dashscope-wan/seedance/veo/sora，`llm/generators/protocols.py:55-236`）+ aigc_studio 分镜→图→视频生产管线 + 前端三页走本仓端点；视觉输入单源链路（attachment_turn_injection→图像轮路由→图像保留→双协议切片）+真图探测；文档 OCR 三引擎同契约；**桌面屏幕视觉**（computer_use：截图+UIA+SOM+perception_gate 三闸）为差异化理解面。短板：音乐生成缺失；Gemini 原生链路收图待核实；video_to_video 无实测协议。
**子项**：生成类（图/视频/音乐） 3.0/2.0；语音（TTS/ASR/通话） 1.0/2.0（本仓反超：对方 TTS 产品面断裂、无电话通道）；视觉理解与文件解析 1.5/1.5；屏幕与设备视觉 0.5/1.5（本仓 computer use 大胜）。

> 细分拆解（十轴逐项）见同目录《[reference_ad_multimodal_teardown_2026-11-22.md](reference_ad_multimodal_teardown_2026-11-22.md)》：专项口径 LobeHub 68.5 / Neurova 69.0（/100）——生成广度对方胜、语音/屏幕视觉/OCR 本仓胜，总体接近、本仓反超；追平方案见《docs/04-plans/2026-11-22-reference-ad-multimodal-catchup-implementation-plan.md》（三批十卡，已拍板：fal/深化 SIP/三家视频协议全做用户可选/生成物入池）。

### D9 数据/租户/认证/安全（L 9 / N 8）

**LobeHub**：数据层强——242 张表、228 个 drizzle 迁移、软删+回收站+FTS outbox+autovacuum 调优（`packages/database/src/schemas/`、`migrations/`）；认证=better-auth 引擎+17 个 SSO/OAuth 提供商+Passkey/WebAuthn+magic link+Email OTP+**自建 OIDC IdP**（`apps/auth/src/libs/better-auth/define-config.ts:132-393`、`src/libs/oidc-provider/`）；API key 的工作区绑定纪律好（个人 key 禁跨工作区、签发者在职校验、RBAC 降权自动收紧，`packages/trpc/src/lambda/context.ts:281-339`）；设备链路三层纵深（deviceId 哈希+token 握手+设备端 symlink 逃逸防护，`device-identity/src/index.ts:54-79`、`device-control/src/workspaceGuard.ts:28-63`）。**硬扣分（OSS 快照）**：RBAC 系统性门禁是空壳——`business-server/src/trpc-middlewares/rbacPermission.ts:14-28` 直通 stub、`workspaceAuth.ts:18-36` 只查 workspaceId 非空，注释明言"Cloud overrides this entire module"；无数据库 RLS，行级隔离全靠应用层 WHERE；主站无实质 CSP（仅 frame-ancestors，`src/libs/next/config/define-config.ts:113-117`）；业务 API 无通用限流；Electron IPC 裸 socket 无对端鉴权（`electron-server-ipc/ipcServer.ts:35-56`）；无原生 SAML/LDAP。
**Neurova**：JWT 身份单通道（`core/identity_context.py`）+**租户校验在 API 层真实执行**（auth.py:743-751 租户提取、global_auth.py:178-190、8+ 端点文件消费；外部代理全生命周期按租户隔离为强制红线）；RBAC 角色+审计日志（security/audit_logger.py、desktop_audit、endpoints/audit.py）+webhook 验签 8 处+沙箱族+keyring。扣分：SSO 生态（OAuth 提供商矩阵/Passkey/OIDC IdP）缺位；租户隔离为字段级而非行级策略引擎。
**子项**：数据层工程 3.0/2.0；认证 3.0/1.5；租户与权限执行 1.5/2.5（**本仓反超**：对方 OSS 侧为 stub）；运行安全 1.5/2.0。

### D10 工程纪律（L 12.5 / N 11）

**LobeHub**：7321 个测试文件且分布与业务厚度匹配（database 647/model-runtime 270/heterogeneous-agents 122/context-engine 95；server 1761）；database 测试打真库（PGlite 快照，`vitest.config.mts` globalSetup）；e2e=Cucumber+Playwright 18 feature，含 P0 用户旅程+性能预算+bundle 尺寸基线门禁（`e2e/`、`.github/workflows/e2e.yml`）；32 条 workflow（包矩阵/3 分片/Windows/桌面/PR 准入/多架构 Docker/四通道桌面 OTA/语义化发布 release.yml）；静态检查自研深度高——oxlint 882 行配置+**alint 模型背书 lint**（规则=prompt+结构化输出，按误报率定级，守 pmap-over-promise-all/no-transactions-in-models/no-secret-exposure 等约 20 条架构安全判据，`packages/alint/`）+bundle 边界守卫+eslint-suppressions 保持清零；i18n 18 语言（68 namespace，i18n-extractor 静态可达 key 抽取）；AGENTS.md+30+ skills 路由+验收证据链+单文件 ≤1200 行棘轮+红绿测试写入开发纪律。扣分：knip 死码检测只扫 `src/`（packages 2191 个测试所在域不在守卫内）；i18n 无 key-parity 硬守卫测试；coverage 仅 0.5% 棘轮阈值。
**Neurova**：2944 后端测试文件（unit 2873/integration 60/e2e 12/perf 13）+前端 360 文件约 2501 用例；.cnb.yml 五门禁（static-gate/protected 单测子集/frontend 四件套/perf-gate 阻断/experience）+commit-msg 红绿证据门+protected_tests 收录门+尺寸棘轮+i18n 一致性守卫测试（11 语言）。扣分：e2e/perf 偏薄；前端 eslint 门实际不可运行（无配置无依赖，AGENTS.md 已自认）；发布通道单一。
**子项**：测试 4.5/4.0；CI/发布 4.0/3.0；静态检查与守卫 2.5/2.5；i18n 1.5/1.5。

### D11 自我进化/RSI（L 5.5 / N 8.5）——本仓反超（v2 增补）

**LobeHub**：真实存在一套受控自改进管线，但不是自主 RSI。按"触发→提案→评估→门禁→应用→验证→回滚"七环判定：
- 触发=**有**（三路）：对话内模型主动声明的意图侧信道（`builtin-tool-self-iteration/src/manifest.ts:25`，advisory 不改资源）；弱信号累加器触发每轮反思（纠正≥2/工具失败≥2/步数≥6，`apps/server/src/services/agentSignal/procedure/accumulators/selfReflection.ts:66-73`）；每晚 2-4 点 cron 复盘（`services/agentSignal/services/selfIteration/review/schedule.ts:27-30`）。
- 提案=**有**：self-reflection/nightly-review 等 mini 模型 agent 产出冻结提案（actions+快照，72h 滑动/7d 硬顶过期，`review/proposal.ts:199-230`）。
- 评估=**弱**：仅结构性 preflight（目标存在/可写/CAS 快照/重名，`review/proposalPreflight.ts`）；**eval-rubric/eval-dataset-parser 与自改进零接线**（消费方仅 agentEvalRun/taskReview/tracing replay，grep 证实 agentSignal 服务内无引用）。
- 门禁=**有**：Labs→Self-evolving 开关**默认关**（`featureGate.ts:23-27`）；apply 前用户/agent/服务端三道门复检（`briefs/selfReview.ts:397-407`）；市场技能安装与 shell 执行强制人工确认。
- 应用=**有**（双轨）：低风险直接写（记忆写入/托管技能 CAS 整体替换）；prompt 改写仅能走提案（"Never directly overwrite the prompt"，`prompts/agentSignal/selfIteration/runtime.ts:124`）。
- 验证=**无**：应用后无自动评测、无 shadow/canary（全仓 grep "canary/shadow" 仅命中 bot wake 的 shadow 模式）。
- 回滚=**有但靠人**：`receiptRollbackService.ts:212` 为用户手动接口，无指标自动回滚。

可自我修改面：能改用户记忆、Agent Signal 托管技能、经审批提案可整体替换复盘 agent 的 systemRole；**不能改**代码/工具 manifest/模型路由/其他 agent 配置/运行时；技能不可删除（`skill-maintainer/src/manifest.ts:112`）。另有第二条真实回路 **Expertise(SCLPT)**：从对话/拒绝/验收证据自动 ingest 教训→修订整合→**编译为 verify criterion 注入后续每次运行**（`aiAgent/pipeline/operationPrep.ts:870-874`）——对方"学习影响行为"最实的一条线。goal 服务的 planner/decideNextMove/machineRecovery 属任务内自主性，产出不回写能力。

**Neurova**：世代化 RSI 闭环——`evolution/rsi/` 35 文件（orchestrator 2532 行/generation_orchestrator 985 行）：门禁链（gate_chain/gate_verdict）、影子验证（shadow_verify）、回滚（rollback_manager）、存活探针（survival_probe）、部署控制器（deployment_controller，含金丝雀）、世代账本（generation_ledger）、收敛分析（convergence_analyzer）、自查提议器（self_improvement_proposer）、目标注册表（target_registry，禁改内核）+ eval_harness/task_yardstick；`closed_loop.py` EvolutionOrchestrator 981 行 + genetic_engine/skill_lifecycle/proposal_lifecycle；进化三原则（内核先于演化/候选不直改基线/裁判在演化集合外）。近期已完成全自动闭环贯通演练（总纲验收，commit e3a57aaf4）。诚实注记：机制完整但生产采纳仍早（历史 RSI 迭代的应用数与 EvalCase 立案数尚低，递归自进化一期计划已把"评测立案/跑批入口"列为整改项）。

**子项**：闭环七环完整度 2.5/3.5；可自我修改面 1.5/2.0；评测驱动 0.5/1.0；安全与发布治理 1.0/2.0。

**判定**：对方胜在幂等/CAS/审批的工程细节与"教训→验证判据编译注入"的巧思；本仓胜在闭环完备性（评测门禁/影子/灰度/回滚/世代账本）与可自我修改面广度。对方"get better every week"目前是能力上限描述而非默认事实（默认关闭+无评测闭环）。

## 4. 可借鉴清单（待拍板，非立即实施）

P0（高价值、改动面可控）：
1. **跨 provider 路由容错**：RouterRuntime 式多通道路由（fallback+加权+attempt 级观测+错误分类续切）。影响面=`neurova/llm/multi_model_client.py` 与 provider 注册表；可先把"故障切换+尝试记录"立起来，加权分流后置。
2. **检索质量三件套**：rerank 接口位、相似度阈值、向量 ANN 索引。对方代码里"TODO: need to rerank"正是本仓可做出差异的点；本仓本体图谱+向量混合检索若补 rerank/阈值，D5 可反超。
3. **auto-run 不可绕过的危险命令黑名单强制层**：独立于审批链的一层（对方 InterventionChecker 先查黑名单再查审批，`InterventionChecker.ts:60-77`），与本仓审批链 L0-L2 叠加而非替代。

P1：
4. **alint 式"模型背书 lint"**：以小模型+结构化输出守架构/安全判据（误报率定级后才可设 error）。适合守"禁裸 import 重依赖/禁绕过 ToolExecutor/禁第二身份通道"这类现有静态规则表达不了的判据。
5. **异构外部 agent 名册扩容**：对方 adapters 覆盖 claude code/codex/kimi/amp/antigravity 等；本仓 neuacp 已有 4 家，名册与目录机制可对照补齐。
6. **前端 bundle/性能基线门禁**：把本仓尺寸棘轮思路扩到 NeurUI 构建产物（对方 e2e 内做 bundle 基线对比，PR 阻断）。
7. **教训→验证判据的编译注入**：对方 Expertise(SCLPT) 把运行教训编译成 verify criterion 并注入后续每次运行（operationPrep.ts:870-874）——可接入本仓元认知回路与任务书验收判据，让"吃过亏"显式变成"下次验收项"。

P2：
8. provider 中立流事件模型（16 类事件归一）作为 llm 层协议演进参考。
9. 语义化发布与桌面 OTA 通道（本仓移动端已有发版链，桌面端可参考其四通道灰度）。
10. 验收证据链（acceptance 证据落固定可访问位置，可复用不重跑）与"每 bugfix 先红后绿"的 skills 化路由（本仓已有钩子强制，可补 skills 文档路由）。
11. **弱信号累加器触发反思**：纠正≥2/工具失败≥2/步数≥6 等廉价阈值触发每轮反思（selfReflection.ts:66-73），比定时全量反思省成本；可作本仓元认知回路的触发源补充。
12. **多模态契约测试矩阵+视频后台轮询兜底**：对方 MessageContent 全矩阵测试（视觉降级/多图/工具图片回灌/AVIF 特判，:38-989）纳入本仓 M8 契约棘轮；生成任务后台轮询兜底（videoBackgroundPolling.ts:43-60）可对照本仓 /video/status 轮询补后台兜底形态。

不照搬：
- 三轨 API 与 124 包超细粒度 monorepo（胶水层理解成本高，与本仓"单一事实源"教义相悖）；
- 云服务强依赖（QStash/Cloudflare Durable Objects/S3 OTA）——本仓自托管优先；
- local-system 主进程直执行的无隔离 shell（本仓沙箱族路线更对）；
- 静态模型卡只维护 5 家、其余靠远端拉取的模式（离线/自托管元数据不完整）。

## 5. 本仓守卫提示（对方没有、别被"补齐"掉）

1. **租户隔离真实执行**：本仓租户校验在 API 层落地且外部代理按租户强隔离；对方 OSS 是 stub。引入对方"workspaceAuth"形态时不得退化为直通。
2. **MCP server 面**：本仓双端齐备，对方仅 client；不要在对齐其工具面时删掉 server 能力。
3. **记忆遗忘/睡眠整理/纪律准入**：对方无此链路；本仓生命周期治理是差异点。
4. **本体图谱+SPARQL**：对方为零；知识域演进应以本仓图谱为主干，文档 RAG 为补充。
5. **审批分级治理（L0-L2+候选 CAS+依赖门+评审相位）**：对方群编排无投票/协商、delegate 被禁用；本仓治理深度是编排维反超的根，勿为"形态对齐"简化。

## 6. 评分复核说明

- D7 给 9.5 vs 5.5 是全场最大分差，依据是 provider 数量（91 vs 7）、协议归一层（3 线协议+16 事件 vs 单层 client）与路由容错（RouterRuntime vs 无对应物）三项均有直接证据。
- D3/D6/D9 的本仓反超均有对方代码内"自认"证据（"Voting is not yet implemented"、"Status: design, not built"、RBAC stub 注释），不是推测。
- 对方当日仍有推送（pushed_at 2026-11-21T15:06Z），本报告为当日快照结论；复评时应以当期主干重跑关键计数。
- v2（同日）：应评审指出补 D11 自我进化/RSI 维（对方侧证据来自对 agentSignal/self-iteration/skill-store/eval-rubric 簇的专项只读深读），总分口径由 10 维 110 分改为 11 维 120 分；D1–D10 各子项分未变。
- v3（同日）：应评审指出补 D2 上下文活水池专项（双方各一路专项只读深读：本仓 context_pool/context 36 文件 vs 对方 context-engine 27 处理器+压缩库+修剪链），本仓上下文工程子项 4.0→4.5，总分 89.5→90.0；其余子项分未变。
- v4（同日）：应评审指出补 D4 工具肌肉记忆专项（本仓 muscle_memory/tool_memory_integration vs 对方 agent-signal/Expertise/UsageCounter 工具学习面扫查），本仓工具框架子项 3.0→3.5，总分 90.0→90.5；其余子项分未变。
- v5（2026-11-22）：应评审要求把多模态单独拆出细化——新增专项《reference_ad_multimodal_teardown_2026-11-22.md》（十轴：L 68.5 / N 69.0，两路只读深读）。首版 D8 粗评漏计本仓 AIGC 端点/语音双栈/OCR，据实重评 D8：L 6.5→6.0 / N 3.5→7.0，总分 98.5/90.5 → 98.0/94.0；追平方案另立《2026-11-22-reference-ad-multimodal-catchup-implementation-plan.md》（三批十卡，四项已拍板：fal/深化 SIP/三家视频协议全做用户可选/生成物入池）。

# QwenPaw vs Neurova 个人助理 Harness 对照评测（2026-11-17）

> **状态（2026-11-18）**：本报告 v1–v5 采用"按 QwenPaw 个人助理形态定制"的八维标尺，对 Neurova 的规划/自我演化/可靠性等纵深能力覆盖不足。**中立结论以 [reference_d_vs_neurova_standard_harness_framework_evaluation_2026-11-18.md](reference_d_vs_neurova_standard_harness_framework_evaluation_2026-11-18.md)（主流 harness 十维框架，QwenPaw 81.5 vs Neurova 80.5）为准**；本报告保留作为"个人助理形态标尺"的专项视角，其中对 QwenPaw 的六路代码分析结论仍然有效。

> 评测对象：[agentscope-ai/QwenPaw](https://github.com/agentscope-ai/QwenPaw)（HEAD `8ac8efb8`，v2.3.0，2026-11-11 发布，37.9k stars，Apache-2.0）
> 对照基准：本仓 Neurova（main，含 S9–S13 批次后状态）
> 方法：浅克隆全量源码（修复一次中断检出后完整工作树 71.5 万行 Python + 2.5 万行 console TS），六路代码级分析（harness 引擎、记忆体系、技能/插件/多 agent、渠道/部署/测试、安全/沙箱、引擎基建），全部结论附代码证据；Neurova 侧以本仓实测规模与既有能力面为准。
> 维度说明：**未沿用** CoworkOS/AutoSwarm 报告的多 agent 协作维度。QwenPaw 的产品形态是"个人 AI 助理 harness"（全渠道接入 + 技能生态 + 本地优先 + 安全内建 + 自演化记忆），维度按该形态定制为八项，Neurova 与 QwenPaw 在同一标尺下双栏打分。

---

## 1. 执行摘要

**总分（加权，满分 100）：QwenPaw 86.5 vs Neurova 82.5。**

- QwenPaw 是迄今评测过的**体量最大、个人助理形态完成度最高的参照系**：71.5 万行 Python，18 渠道子进程隔离接入，16 技能 + 41 插件 + 7 源市场，三层记忆 + 自演化知识库，多平台内核沙箱与五件套安全体系，43 个 CI 工作流 + 918 个单测文件 + 238 个 e2e 用例。
- Neurova 在三个维度领先：**多 agent 协作治理**（9.0 vs 6.5）、**上下文/记忆/知识语义层**（9.5 vs 8.5——类脑多层级记忆 + 本体 SPARQL/规则引擎/血缘/nl2sql，均非 QwenPaw 三层记忆所能覆盖）；QwenPaw 领先在**渠道运行架构**（子进程隔离+供应链审计，10 vs 7.5）、**技能/插件市场体量**（9 vs 7.5）、**安全多平台沙箱纵深**（8.5 vs 8.0）与**部署产品化**（9 vs 8）。
- 一句话结论：**QwenPaw 证明了"个人助理 harness"的天花板工程——把渠道、技能、记忆、安全做成可运营的产品化闭环；Neurova 的差异化优势在多 agent 协作治理、类脑记忆体系与知识语义层，其余维度均有真实对等物，差距主要在"渠道子进程隔离、市场体量、多平台沙箱、一键部署打磨"四处工程完成度，非能力缺位。**

## 2. 对象画像：QwenPaw 是什么

阿里 AgentScope 团队的个人 AI 助理。核心代码在 `src/qwenpaw/`（46 个模块），关键构成：

| 域 | 规模/构成 | 关键实现 |
|---|---|---|
| `agents/` | ~8.9 万行 | react_agent（ReAct loop + 中间件）、context/scroll（2,393 行上下文管理器）、memory/（三层记忆）、skill_system、acp/（4.5k 行 Agent Communication Protocol） |
| `app/` | ~6.6 万行 | FastAPI 装配 + 51 个分域 router、渠道子进程监督、统一会话队列、cron（APScheduler）、inbox trace |
| `plugins/` | ~4.8 万行 | 18 渠道插件（telegram/feishu/dingtalk/wechat/discord/qq/slack/matrix/imessage/mqtt/sip 等，41,332 行）+ tool/memory/harness/bundle 插件 |
| `providers/` | ~2.1 万行 | 37 个内置 provider、FallbackChatModel 故障转移、per-model 限流 |
| `security/` + `sandbox/` + `governance/` | ~2.4 万行 | 工具卫兵（4 guardian + 22 条 YAML 规则）、技能扫描器（42 条双语规则）、Seatbelt/Landlock/Bubblewrap/AppContainer 多平台沙箱、两层访问策略 + SQLite 审计 |
| `loop/` + `tool_calls/` | 停止门编译器（7 种 gate）+ ToolCoordinator 单一执行所有者 | |
| `cli/`、`browser/`、`hub/`、`portability/`、`runtime/` 等 | 各 0.5–2 万行 | CLI 20+ 命令组、浏览器域、多源技能市场、跨版本移植层 |
| `console/` | 2.5 万行 TS | React + Vite + Tauri 桌面端，含 1,389 行 3D 记忆图谱 |
| 测试与 CI | tests/ 918 个单测文件（unit/contract/integration/typing 分层）、e2e/ 45 文件 238 用例 26 page object、console 685 个前端测试、43 个 GitHub 工作流、覆盖率棘轮 fail_under=50 |

定位与 Neurova 的关键差异：QwenPaw 以"**单用户个人助理**"为中心（一个实例服务一个人，多渠道触达），多 agent 是助理的分身/子任务机制；Neurova 以"**多 agent 协作平台**"为中心（团队、房间、审批、候选制、项目档案），个人助理体验是外围。

## 3. 维度体系（按 QwenPaw 形态定制，八维加权）

| # | 维度 | 权重 | 为什么设这个维度 |
|---|------|------|------------------|
| A | Agent 引擎与循环工程 | 15% | harness 的心脏：loop 结构、停止策略、工具执行漏斗 |
| B | 上下文与记忆体系 | 15% | 个人助理的核心竞争力："never forgets" |
| C | 工具/技能/插件生态 | 15% | 可扩展性是助理产品的主要交付面 |
| D | 渠道与全端接入 | 10% | QwenPaw 形态的主战场（IM 渠道 + 桌面/控制台） |
| E | 多 agent 与编排治理 | 10% | 子代理/跨系统编排能力 |
| F | 安全与隔离 | 15% | 个人助理直连 IM 与本地文件，安全是生命线 |
| G | 部署、模型接入与产品化 | 10% | 本地/云/桌面多种形态与模型自由 |
| H | 工程质量、测试与可观测 | 10% | 长期演化的可靠性基础 |

## 4. 逐维度对照

### A. Agent 引擎与循环工程 —— QwenPaw 9 / Neurova 8

**QwenPaw**（基于 AgentScope 2.0 框架 + 深度定制）：
- ReAct loop + 中间件管道；`react_agent.py` 一轮流转：压缩清洗 → 流式推理 → 工具单一漏斗 `_execute_tool_call` → stop handlers 裁决 → 可注入 continuation 续跑（`react_agent.py:331-373,1204-1511,1456-1495`）。
- **声明式停止门编译**是亮点：`loop/catalog.py:155` 白名单 7 种 gate（迭代/死循环/token 预算/超时/工具预算/定性 rubric/完成度 rubric，后两者互斥），`loop/compiler.py:11` 把用户可编辑 JSON 原子编译成有序 gate 链；`gates/doom_loop.py:37` 滑窗相似度多阶段升级（警告续跑→终止）。
- **ToolCoordinator 单一执行所有者**（`tool_calls/_coordinator.py:55`）：每调用后台 task + 流式 fan-out；offload/kill 双截止时间防挂死（`_timeout_helper.py:16`，注释点名防"清掉 deadline 永久等待"类挂死）。
- 统一溢出恢复边界（`context/overflow_recovery.py:27-71`）+ "token 保证金"（provider 溢出拒收后永久抬高估算基线，`scroll/manager.py:390-463`）+ 多模态三级降级与 strip-and-retry（`react_agent.py:1333-1441`）。
- 扣分：对 AgentScope 2.0 alpha 私有 API 深耦合（`_as_internals.py:6-14` 自述）；约 50 处 except-pass；gate 异常被吞仅 warning（`loop/gates/handler.py:100-107`）；`model_factory.py` 2,797 行巨型文件。

**Neurova**：自研 loop 管线（agent_core + loops/ + 预算阶段 + 循环目标 + `agent_loop_detection.py` 回路检测）、run 级事件账本与因果链、邮箱租约两阶段确认、机械完成闸门、状态迁移表。工程纪律强，但**停止策略未做成声明式可编译体系**，门种类少于 QwenPaw；工具执行的 offload/双截止机制亦无对等物。

### B. 上下文与记忆体系 —— QwenPaw 8.5 / Neurova 9.5

**QwenPaw 三层记忆全部有硬实现**：
1. live working context：`scroll/manager.py` 内存窗口 + write-through + 压力流水线（persist→预折叠→split 逐出→EvictionIndex 层级索引，`scroll/manager.py:507-530`）——"给模型地图而非摘要替代品"，被逐出原文可经 `recall_history` 或**沙箱 Python REPL 只读 ATTACH 历史库**取回（`memoryspace.py:3-10`）。
2. verbatim history：SQLite + FTS5 + WAL（`scroll/history.py:46-62`），recall 工具自身轮次被排除防自污染（`history.py:60-67`）。
3. 自演化知识库：ReMe（外部依赖，版本钉死 `reme-ai==0.4.2.0`）vault = 纯 Markdown（MEMORY.md 人机共编 + 日期笔记 + digest 蒸馏节点）；`auto_memory` 每隔 N 轮由 LLM 归纳、`auto_dream` cron 定期蒸馏合并（`reme_config.py:426-452`）；检索 = 向量 0.7 + BM25 RRF 融合 + wikilink 扩展。
- 扣分：ReMe import 失败仅 warning 整体禁用记忆；升级后旧 JSONL 会话文件故意不迁移成孤儿；自动召回 query 仅取末条用户消息截 50 字符。

**Neurova（经逐文件核实，v1 凭记忆低估）**：记忆/上下文/知识/认知四域合计约 **9.7 万行**（context/ 35 文件 11,993 行、cognitive_layers/ 95 文件 41,487 行、knowledge/ 139 文件 33,749 行、memory_ingest/ 22 文件 3,369 行、mem_core.py 1,550 行、context_pool.py 1,989 行等），深度不弱反强：
- **上下文工程**：`fold_trigger.py` 增长门（demand-side 主动折叠，billion-context 论文对偶实现，默认开）+ `window_compactor` 尾部保留/老消息折叠 + `compression_doctrine.py` 版本化压缩教义（留什么丢什么成文规则 + 覆盖门禁）+ `summarizing_compressor` 防幻觉 factsheet + **`fold_index.py` 折叠层 covers 派生/解析/档号**（与 QwenPaw EvictionIndex 同类的"层级索引+确定性下钻"，且明确"索引存在≠取得到"的自觉）+ eviction_ledger_db + token_estimator（图像分段计价修正）。
- **记忆检索**：`mem_core.py` 记忆温度 + **突触连接向量门控（MoE 向量索引，全库按温度分页灌入）**；`agent/retrieval_fusion.py` 链级 **RRF 融合**（图谱/记忆/知识并列按秩融合，`NEUROVA_RETRIEVAL_FUSION=rrf`）；`memory_retrieval_chain.py` 责任链多级降级 + 质量评估 + 缓存兜底；retriever_adapters/graph/knowledge/tkg 四类适配器。
- **认知层**：cognitive_layers 五层（memory_layer 含 **absence_reasoner 缺席推理、association_cues 联想线索族**、auto_classifier；growth_layer 成长分析；meta_cognition_layer；emotion_context_layer；knowledge_graph）+ `crystallized_experience_manager.py` 结晶经验检索。
- **知识语义层（QwenPaw 无对等物，v4 核实）**：`knowledge/ontology/` 40 模块 9,012 行——term_registry 术语注册、shapes/validation 校验、rule_engine、**sparql_query/turtle/rdf_import**（RDF/SPARQL 全套）、abduction 溯因、simulation、decision_ledger/derivation_ledger/accountability 治理账本、domain_packs 领域包、schema_suggester、cq_matrix、semver、upper_lite 上层本体；`mcp_ontology_server.py` 把 ontology_query/ontology_validate/fact_submit 以 MCP tools 开放（双鉴权 fail-closed，写入经 admission 唯一咽喉：逐字可核闸+新谓词候选审批+冲突三态票三层人审）；`knowledge/foundation/` 血缘（lineage）、可信度（credibility）、冲突仲裁（conflict_judge + LLM judge）、时间事实（temporal_facts）、digest_chain；`knowledge/enterprise/` ERP/lakehouse/SQL/chat/file 连接器 + **nl2sql**；rerank/ 四种重排 provider；另有 federated_kb、multi_kb_router、community_graph、hybrid 混合检索、vector_index/vector_ann/fts_index 三索引。
- **记忆分层架构（v5 核实，对照 QwenPaw"三层记忆"）**：`cognitive_layers/memory_layer/` 55+ 模块实现的是**类脑多层级记忆**，非三层存储——① **肌肉记忆三级**（`muscle_memory.py`：L1 条件反射级毫秒响应 / L2 热路径缓存秒级 / L3 原始记录需检索；关键词指纹+向量指纹混合匹配，连续成功 2 次固化进 L1，30 天未用自动降级）；② **NeuHebb 神经可塑性系统**（forge/curator/manager 三件套，Hebbian"共激活即连接"）；③ **模式结晶器**（`pattern_crystallizer.py`，以 Hebb 学习替代 LLM 调用做经验结晶）+ `crystallized_experience_manager`；④ **睡眠整合**（`sleep.py`/`sleep_writeback.py`：离线阶段语义聚类合并去冗、温度衰减遗忘、压缩归档、回写）；⑤ **温度引擎**（`temperature.py`：时间衰减+情感保护+饱和效应+**贝叶斯遗忘曲线**）；⑥ **情绪记忆**（emotion/semantic_emotion 调节温度与风格）；⑦ 因果/时序推理（causal_reasoning/temporal_reasoner）、缺席推理、联想线索族；⑧ 元认知与推理轨迹；⑨ **记忆治理**：`memory_admission.py` 写入前敏感拦截+准入清单（该记/不记/绝不记，单点包层全链路）、pollution_purge 污染清除、conflict、isolation/share_group、version_control 记忆版本控制；⑩ MemCore 门面（1,550 行）统一装配 storage/temperature/recall/buffer/evolution/growth_log/question_queue/tool_memory/muscle_memory/attachment/moe_router 十余子系统（CogArch 总线版）。
- 相对弱项：**"人机共编 Markdown 知识库 + LLM 归纳/cron 蒸馏（auto_memory/auto_dream）"的轻量自演化产品化闭环是 QwenPaw 特色**，本仓的自演化走认知层/结晶经验路径，无"用户可直接共编的 MEMORY.md"形态；记忆图谱前端可视化（QwenPaw 1,389 行 3D 力导向图）亦缺对等物。

### C. 工具/技能/插件生态 —— QwenPaw 9 / Neurova 7.5

**QwenPaw**：16 个内置技能（文档四件套/浏览器/cron/渠道消息/多 agent/元技能 make-skill 等）× 中英双语；41 个插件；技能 = YAML frontmatter + Markdown + 可选脚本，manifest 驱动的启用/渠道过滤/环境依赖/preload 渐进披露/冲突改名/分阶段安装（`skill_system/registry.py:1268,1328`、`store.py:1104-1140`）。**市场是多方源的**：默认 clawhub.ai，支持 skills.sh/GitHub/lobehub/modelscope/agentscope platform/aliyun 七源导入（`hub.py:2185`）。MCP 双向：client 侧 stdio/SSE/streamable_http 三传输、会话级 MCP 卡片注入（`acp/session_mcp.py:33-80`）；server 侧 FastMCP 暴露 23 个邮件工具。扣分：技能靠"模型念 CLI 命令"执行、缺类型化 schema 兜底；-en/-zh 双份目录连脚本都复制，漂移风险高。

**Neurova**：`skills/` 42 文件 1.42 万行 + `skill_system/` 3 文件 1,088 行，工具面有类型化 schema（这点强于 QwenPaw 的 Markdown 技能念命令）；**市场与治理体系实际存在且完整**——market_importer/market_registry/market_searcher/market_sources/market_store/market_submissions/hub_client 构成多源市场链路，skill_install_gate、skill_contract、creation_governance、permissions、sandbox_root 构成安装治理闭环。差距在于**生态体量**：内置技能数量与插件总数少于 QwenPaw（16 技能×双语 + 41 插件 + 7 源市场 vs Neurova 内置面），多渠道分发过滤、渐进披露 preload 的粒度也 simpler。

### D. 渠道与全端接入 —— QwenPaw 10 / Neurova 7.5

**QwenPaw 的主场**：18 渠道 4.1 万行，声明式契约（channel.json 携带 config_schema + capabilities 能力数组，构建期有 `scripts/pack/validate_channel_contracts.py` 校验）；**渠道跑在独立子进程**（`app/channels/process_supervisor.py:77`），LSP Content-Length 帧 + JSON-RPC 通信，握手携带协议版本/源码摘要/Python ABI/**依赖审计结果并强制通过**（`runner_host.py:44-83`）——供应链级防御；主进程保留队列/策略/Agent 执行，子进程只做平台 I/O（`isolated_proxy.py:173`）；每会话优先级队列 + 群聊按 ACL 拆批；无空壳渠道。接入面四件套：Console（React web）+ TUI + Tauri 桌面 + 全渠道 IM。

**Neurova（经逐文件核实，此前"渠道数量与深度差距大"的判断有误）**：`channels/` 59 文件 1.9 万行，覆盖 **12+ 渠道域**——飞书（774 行+auth+media）、钉钉（597 行）、企业微信（wecom 554 行 + **会话存档** wecom_archive 1,040 行 + aibot + token）、微信（12 文件族：auth/ilink/kf 客服/media/parsing/AI 生成等）、QQ（qqbot 1,425 行 + qq_ws + qq）、Telegram（9 文件族：webhook/adapter/api_client/parser/sender/commands/chat+message management）、Discord、MQTT、SIP、语音（voice ingress/egress/precheck 四件套）、小艺、qclaw。架构是深度模块：`base.py` 归一 12 种渠道事件（含群成员变更、**人工接管**），`manager.py`（1,102 行）管生命周期/健康检查，`channel_router.py` 常驻打通"入站→run 台账登记+让位闸准入→agent→回发"全链路；横切件有 **attention_budget 出站注意力预算**（同键排队/人在等就压住，D-1 甲案）、access_policy、group_leadership 群主仲裁、identity_binding、outbound_ledger、mediaIngress、message_chunker。接入面：console web + **鸿蒙/安卓原生双端**（QwenPaw 无原生移动端）。
真实差距三点：① QwenPaw 渠道**子进程隔离 + 握手期依赖审计**的运行架构 Neurova 没有（主进程内 asyncio 适配器，渠道崩溃会波及宿主）；② 渠道数量 18 vs 12+（QwenPaw 多 slack/matrix/imessage/mattermost/onebot/azure_bot）；③ QwenPaw 的声明式 channel.json 契约 + 构建期校验 vs Neurova 的 Python 基类契约。Neurova 的对等优势：语音双工、企微会话存档、出站注意力预算、群主仲裁、人工接管事件、原生移动端。

### E. 多 agent 与编排治理 —— QwenPaw 6.5 / Neurova 9

**QwenPaw**：spawn_subagent（独立 workspace → 独立技能与记忆）、git worktree fork 隔离（`fork_project.py:46-52`）、**ACP 双向**（可作为 ACP server 被 Zed/OpenCode 等外部客户端连接并全量暴露能力，也可托管外部 agent 进程，`acp/server.py`、`acp/service.py:303`）、multi_agent_collaboration/chat_with_agent 技能（后台任务返回 TASK_ID、续会话、防回环）、omp_workflows 插件五种编排模式。定位是"个人助理的分身与跨系统互操作"。**缺**：团队/房间、审批链分级、候选制合并、依赖门控、run 级事件账本、多 agent 记账与归属治理。

**Neurova 的主场**：SwarmManager 单源编排、团队/房间双入口、审批链 L0/L1/L2（判定权单源回灌）、候选制 CAS 合并与冲突升级、run 级 JSONL 事件账本与因果链重放、依赖门控、RUN_STATUS_TRANSITIONS 迁移表、子代理五工具（派活/查岗/点名/改需求/叫停）、项目协作档案聚合。**组织级多 agent 治理显著领先。**

### F. 安全与隔离 —— QwenPaw 8.5 / Neurova 8.0

**QwenPaw 五件套是真实现，纵深防御 + 内核自证**：
- 沙箱：macOS Seatbelt（sandbox-exec deny-default）、Linux Landlock 裸 syscall + Bubblewrap 命名空间双实现、Windows AppContainer/提权专用账户 + WFP 防火墙 + Job Object 三实现（`sandbox/` 1.05 万行）；子进程用**内核状态自证**隔离生效（uid_map 单映射、CapEff=0、mountinfo 根指向，`runtime_boundary.py:22-79`），不信环境变量。
- Tool Guard：4 guardian 编排 + 22 条 YAML 规则 + 1,107 行灾难性 rm 路径判定 + shell 混淆/续接/heredoc 逃逸检测；五档执行级别（STRICT/SMART/JEV/AUTO/OFF）。
- Skill Scanner：42 条中英双语签名规则（prompt 注入/命令注入/数据外发/硬编码密钥/混淆/社工/供应链/未授权工具），安装期 `scan_skill_dir_or_raise` 硬拒。
- Access Policy：builtin + user 两层规则，ALLOW/DENY/ASK/SANDBOX_FALLBACK；审批闭环完整（渠道交互卡片 + REST + 聊天命令三入口，EXACT_REQUESTER 身份策略防代批，超时即拒）；LLM 生成的泛化规则强制过安全校验，危险命令拒绝泛化（`governance/generalize.py:1-17`）。
- 审计：SQLite 审计日志（10 万条自动清理）+ Fernet + OS keychain 密钥存储。
- 扣分：guardian 异常 fail-open（`engine.py:271-278`，守卫崩溃不阻断）；沙箱默认关闭（`config.py:3244`）；Bubblewrap 无网络隔离；决策模型把完整工具脚本发云端模型（自身构成数据外发通道）；Docker 以 root 运行、认证默认关。

**Neurova（经逐文件核实）**：`security/` **44 文件 1.22 万行** + `sandbox/` 5 文件 1,501 行，纵深工程实际存在：tool_guard + tool_arg_validator + tool_param_guard + tool_circuit_breaker、command_authority/command_segments/command_syntax + **shell_normalization**（对抗 shell 混淆逃逸，与 QwenPaw ShellEvasionGuardian 同类）、**skill_scanner**、approval_manager/approval_relay/approval_continuation + hitl_surface（人在环）、rbac/permission_mode/governance + audit_logger + desktop_audit、secret_store/local_key_protection/sensitive_info/privacy_gate；沙箱有 **appcontainer.py**（Windows AppContainer + restricted_token）+ code_sandbox/exec_sandbox。加上 147 条审计修复闭环（属主门收口、注入化）与 context_firewall。
真实差距：① 沙箱**多平台覆盖**——QwenPaw 有 macOS Seatbelt、Linux Landlock/Bubblewrap、Windows 三实现并用内核状态自证隔离生效；Neurova 沙箱面以 Windows AppContainer + 受限令牌为主，macOS/Linux 内核级沙箱缺位；② QwenPaw 的审批经**渠道交互卡片**直达 IM（人不用打开控制台），Neurova 审批入口在 console/HITL 面；③ QwenPaw 技能扫描器带 42 条中英双语签名库且安装期硬拒，Neurova 的 skill_scanner 规则完备度需对齐（本次未逐条比对规则库）。

### G. 部署、模型接入与产品化 —— QwenPaw 9 / Neurova 8

**QwenPaw**：五种部署形态（PyPI 包 / Docker 多阶段 + supervisord / Tauri 桌面安装包 + PyInstaller 打包 Python 运行时 / 源码 / AgentScope Platform 托管）；本地模型运行时（Ollama/LM Studio/transformers/onnx + 自家 QwenPaw-Flash 2B~35B 系列，"no API key, no cloud dependency"）；37 个内置 provider + FallbackChatModel 故障转移 + per-model 限流隔离（60s 滑窗 QPM + Semaphore + 429 暂停，单模型 429 不拖累其他模型，`providers/rate_limiter.py`）。扣分：RoutingPolicy 是静态桩（只看 local_first/cloud_first 配置，无内容级路由，`routing_chat_model.py:34-52`）；37 provider 硬编码多点登记。

**Neurova**：docker/helm/compose 注入、web + 鸿蒙 + 安卓三端、多 provider 管理、API key 持久化。移动原生端是独有形态，但"个人一键部署 + 本地模型 + 桌面安装包"的打磨弱于 QwenPaw。

### H. 工程质量、测试与可观测 —— QwenPaw 8.5 / Neurova 8.5

**QwenPaw**：tests/ 918 个单测文件（unit/contract/integration/typing 四层）+ e2e 238 用例（26 page object、P0-P2 分级、mock/真后端双档）+ console 685 个前端测试；CI 43 个工作流（三层测试矩阵 + spam-gate + 覆盖率棘轮 fail_under=50 + 前端 bundle 预算 + pre-commit 全家桶 mypy/black/flake8/pylint + CodeQL）；文档五语言、design.md 设计语言带质量门。扣分：约 50 处 except-pass 静默降级；无 metrics/tracing 主线（observability/ 仅 237 行 Langfuse 可选插桩，审计藏在 governance）；`_app.py` 1,064 行混装多关注点；mypy 仅有 pre-commit 钩子无配置节。

**Neurova**：2,738 个测试文件 10.5 万行、A/B 零新增失败纪律、守卫测试体系（教义/契约/收集卫生）、agent_core 尺寸棘轮、真机 318 用例、vitest 2,560+、live-verify 体系、运行台账 + SSE 事件时间线。**测试纪律与治理守卫更强；CI 门禁种类（覆盖率棘轮、bundle 预算、CodeQL）少于 QwenPaw。** 两方持平。

## 5. 评分表

| 维度 | 权重 | QwenPaw | Neurova | 加权 QP | 加权 NV |
|------|------|---------|---------|---------|---------|
| A Agent 引擎与循环工程 | 15% | 9.0 | 8.0 | 13.5 | 12.0 |
| B 上下文与记忆体系 | 15% | 8.5 | 9.5 | 12.75 | 14.25 |
| C 工具/技能/插件生态 | 15% | 9.0 | 7.5 | 13.5 | 11.25 |
| D 渠道与全端接入 | 10% | 10.0 | 7.5 | 10.0 | 7.5 |
| E 多 agent 与编排治理 | 10% | 6.5 | 9.0 | 6.5 | 9.0 |
| F 安全与隔离 | 15% | 8.5 | 8.0 | 12.75 | 12.0 |
| G 部署/模型接入/产品化 | 10% | 9.0 | 8.0 | 9.0 | 8.0 |
| H 工程质量/测试/可观测 | 10% | 8.5 | 8.5 | 8.5 | 8.5 |
| **合计** | **100%** | | | **86.5** | **82.5** |

> 口径说明：维度按 QwenPaw 的产品形态定制，D 维（渠道）对 Neurova 天然不利、E 维对 QwenPaw 不利，总分代表"以个人助理 harness 完整度为标尺"的相对位置，**不是**对 Neurova 整体产品价值的判决。Neurova 若以多 agent 协作平台为标尺评测（如 CoworkOS 报告口径），结论不同。
> 修订记录：v2（2026-11-17）——应用户质疑对 Neurova 侧逐文件核实后修订 D/C/F 三维：D 5.5→7.5（channels/ 实为 59 文件 1.9 万行、12+ 渠道域，此前依据过时记忆低估）、C 7.0→7.5（市场/安装门/扫描器体系实际存在）、F 7.5→8.0（44 文件安全域 + AppContainer 沙箱 + skill_scanner 实际存在）。
> 修订记录：v3（2026-11-17）——B 维同因修订：Neurova 记忆/上下文/知识/认知四域实测约 9.7 万行（context/ 折叠分代+covers 层级索引+增长门+压缩教义、RRF 融合检索、MoE 向量门控+突触连接、cognitive_layers 五层 4.1 万行、结晶经验），QwenPaw 的 EvictionIndex 非独有；B 维 QwenPaw 9.0→8.5、Neurova 7.5→8.5，总分 87.25→86.5、79.5→81.0。
> 修订记录：v4（2026-11-17）——知识库/本体域核实：`knowledge/ontology/` 40 模块 9,012 行（SPARQL/RDF/规则引擎/溯因/治理账本/领域包）+ `mcp_ontology_server.py`（MCP 化本体读写，三层人审）+ foundation/（血缘/可信度/冲突仲裁/时间事实）+ enterprise/（ERP/lakehouse/nl2sql 连接器）——QwenPaw 知识库仅为 ReMe Markdown vault，无本体/图谱/血缘层；B 维 Neurova 8.5→9.0，总分 81.0→81.75。
> 修订记录：v5（2026-11-17）——记忆架构核实：本仓为**类脑多层级记忆**（肌肉记忆 L1/L2/L3、NeuHebb 可塑性、模式结晶、睡眠整合+回写、温度引擎+贝叶斯遗忘曲线、情绪调节、因果/时序/缺席推理、记忆准入与污染清除/版本控制），深度超过 QwenPaw"三层记忆"；B 维 Neurova 9.0→9.5，总分 81.75→82.5。

## 6. Neurova 可借鉴清单（按性价比排序）

1. **声明式停止门编译**（A/B 维）：把停止策略做成"用户可编辑 JSON → 校验互斥组 → 编译成有序 gate 链"，7 种内置 gate（迭代/死循环/token 预算/超时/工具预算/定性 rubric/完成度 rubric）。Neurova 已有 loop 检测与预算阶段，差"声明式 + 可编译 + 互斥校验"一步。
2. **工具执行 offload/kill 双截止**（A 维）：到 deadline 先 offload 后台返回占位、循环继续，kill_deadline 兜底强杀——直接防挂死。Neurova 工具执行可平移该机制。
3. **沙箱 Python recall 历史库**（B 维）：本仓 `fold_index` 已有 covers 层级索引对等物，仍缺的是 QwenPaw 的"模型可用**沙箱 Python REPL 只读 ATTACH** 历史 SQLite 库"——模型获得图灵完备的确定性回溯手段，而非只有相关性检索。
4. **人机共编 MEMORY.md + cron 蒸馏**（B 维）：QwenPaw 的 `auto_memory`（每 N 轮 LLM 归纳入当日笔记）+ `auto_dream`（cron 驱动 scan→integrate→finish 蒸馏为 digest 节点）+ 用户可直接编辑的 MEMORY.md。本仓自演化走认知层/结晶经验路径，缺"用户可见可编"的轻量入口。
5. **渠道子进程隔离 + 握手期依赖审计**（D/F 维）：渠道插件跑独立进程、JSON-RPC、握手携带依赖审计结果强制通过——同时解决渠道崩溃隔离与供应链投毒两个问题，是 Neurova 渠道面扩张时应采用的架构。
6. **技能扫描器规则库**（F 维）：Neurova 已有 `security/skill_scanner.py` 与 `skill_install_gate`，可借鉴的是 QwenPaw 的**42 条中英双语签名库**（prompt 注入/命令注入/数据外发/硬编码密钥/混淆/社工/供应链/未授权工具八类）与"扫描即硬拒"的安装期闭环——把本仓扫描器的规则面与双语覆盖对齐到该粒度。
7. **per-model 限流隔离**（G 维）：每 provider:model 独立限流器 + 429 暂停封顶 + waiter 抖动，单模型限流不拖累其他模型。
8. **审批泛化的安全校验**（F 维）：审批通过后由 LLM 生成保守泛化规则免重复审批，但危险命令（rm/sudo）拒绝泛化只记精确匹配——Neurova 审批链 L0-L2 可加这一层"审批成果复用"。
9. **覆盖率棘轮 + 前端 bundle 预算门**（H 维）：CI 覆盖率只升不降（30→45→50 阶梯有据可查）、前端产物体积预算门。

## 7. 不宜照搬项

- **技能 = Markdown + 模型念 CLI 命令**：无类型化 schema 兜底，`--agent-id` 写错即落错 workspace。Neurova 的类型化工具面更稳，勿倒退。
- **-en/-zh 全量双份技能目录**（连 Python 脚本都复制）：漂移风险高；Neurova 的 i18n 走 locale 文件对齐守卫即可。
- **guardian fail-open 与 50 处 except-pass**：与本仓"禁表面抹除"教义直接冲突。
- **决策模型云端外发完整脚本**：个人助理场景把用户工具目标发第三方模型是隐私反模式。
- **沙箱默认关闭 + Docker root 运行**：安全能力默认开才有效。

## 8. 局限性

- QwenPaw 侧结论基于 HEAD `8ac8efb8` 静态代码阅读与 6 路抽样深读，未运行其 e2e/单测，未做运行时压测；个别行号随上游推进会漂移。
- Neurova 侧评分以 main 分支当前能力面为准。v1 评分中 D/C/F/B 四维曾依据记忆档案低估（未逐文件核实本仓代码），v2/v3 已对 `neurova/channels|skills|skill_system|security|sandbox|memory|context|cognitive_layers|knowledge|mem_core` 逐目录核实规模与关键实现后修正；但 Neurova 侧仍有未逐行深读的域（如 mem_core 检索链路内部、skill_scanner 规则条数），相应结论以规模与目录结构证据为界，未越界断言。
- 渠道完成度以代码规模与能力数组/事件契约推断，未逐渠道实连验证。

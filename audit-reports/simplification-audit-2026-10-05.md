# Neurova 后端全库简化审计（2026-10-05，v2）

> 只读评审产物。两轮均未改动任何生产代码或测试（工作树见 §10）。
> **v1 的总量判断成立，性质判断有错**：v1 把约 1.3 万行"零消费者但全仓无现役替代"的码算进可删清单，
> 溯源后它们属**产品裁定**范畴。v2 按三态重划，并逐项补齐原功能与来历。

## 1. 范围与方法

| 阶段 | 做法 | 结果 |
|------|------|------|
| 一、定位 | 9 个互不重叠批次只读扫描 `neurova/` 全量 | 约 50 项零消费者候选 + 双源 + 样板清单 |
| 二、溯源 | 同候选逐项补「原功能 / 关键入口 / **来历（git 证据）** / 现役替代 / 判定」 | 改判 18 项，其中 2 项是我自己的错判 |

口径：`neurova/` 共 1027 个 `.py` / **352712 行**（文本口径；v1 初版曾对全清单 `cat`，把封面图等二进制按字节算成 359712）。

执行事故（如实记录）：

- skills+evolution 合批把"接下来我要验证……"当终报返回 → 拆两批重跑成功。
- channels+knowledge+security 组在 **150 次工具调用 / 1800 万 token** 后截断，只回 1 项 → 拆三批重跑成功。
- 尾部包组撞 **maxTurns=150** 上限，190 次调用空手而归 → 拆三批重跑成功。
- 安全能力矩阵连续两次失败（一次返回与任务无关的童话旁白，一次返回空）→ 该条由主会话自己算完，见 §3-B1。

教训：单批项数与调用预算必须显式封顶；长 prompt + 大范围会同时触发截断与失稳。

## 2. 结论概览（v2 修正）

| 态 | 含义 | 行数 | v1 归类 |
|----|------|------|---------|
| **A 可删** | 有现役实现顶上，或本身无功能 | ≈19,400 | v1 称"零消费者死码 ≈31,900" |
| **B 需人裁** | 全仓唯一实装，删即永久失去该能力 | ≈13,000 | v1 误并入可删 |
| **C 该接线** | 模块是对的，缺的是消费方 | ≈120 | v1 误并入可删 |

总量 ≈32,500，与 v1 的 3.19 万接近——**错不在数，在性质**。

新发现（见 §4）：这批死码不是渐进腐烂，而是**集中在 4 次提交的一次性事件**，其中 `7835c367`
「pyc 骨架恢复」既是大量死模块的引入源，又是若干活端点的删除现场。

## 3. 一档逐项档案

标注：✅ = 主会话独立复算；◑ = 子代理取证（给 `file:line` 与 commit，我未复算）。

### A. 可删（有现役顶替，或本身无功能）

#### A1 `neurova/api/communication_protocol.py`（622）◑
- 原功能：外部 Agent 接入的应用层协议状态机——`validate_handshake:299` 拒不支持 `1.0` 的对端、`check_rate_limit:362` 每客户端 60 秒滑窗、`process_message:432` 分派握手/心跳/类型化 handler、`get_active_sessions:587` 按超时过滤。
- 关键入口：`CommunicationProtocol:176`、`get_communication_protocol():605`。
- 来历：`7835c367`(06-04) 以 122 行骨架引入，**引入即未接线**；`34ed043c`(09-16) 只对齐签名，未接消费方。
- 现役替代：`api/endpoints/agent_communication_api.py:265/313/375` 顶了路由，但**协议语义全丢**（不校版本、不限流、无大小上限、无会话簿记）。
- 判定：删。能力被更弱但真实在跑的路由取代；日后真做长连接应重写，而非留一份无人调的状态机。

#### A2 `neurova/api/deps.py` accessor 层 + 两模型（≈190）✅
- 原功能：把 `core/*` 与 `channels/manager` 的单例取器再包一层 FastAPI 依赖（惰性 import + 失败转 503），无独有业务语义；`PaginationParams:379` 归一分页；`RequestContext:435` 打包 request_id+user+agent_id。
- 来历：`806c7047`(06-06) 一次性引入，**同批消费方就直取真源**（`endpoints/channels.py:25`、`logs.py:70`）→ 从未存在"消费方后来消失"。
- 现役替代：真源直取；分页现役为端点内联 `Query(ge=1, le=100)`；request_id 由 `middleware.py:31-35` 写、各端点自读。
- 判定：删。**连带纠错**：`deps.py:199 get_provider_manager` 同样零消费者，故 v1 §5「改用 `Depends(get_provider_manager)` 消 16 处样板」**指向了死目标**，作废。

#### A3 `neurova/api/error_codes.py`（21）◑
- 原功能：10 个 int 错误码常量 + `ErrorCodes = ErrorCode` 别名，无逻辑。
- 来历：`7835c367`(06-04) 引入，**同日即被同名超集影子覆盖**（`interfaces/api_standard.py:32` 是 `int, Enum` 超集）。
- 现役替代：`api_standard.py:30`；真实消费方（`memory/base.py:17`、`error_handlers.py:14-26`）全从那里取。
- 判定：删，**须同批清 `interfaces/__init__.py:30/32/39`**——否则删后 `interfaces.ErrorCodes` 静默变 `None`，把死码换成一个新的"对外可见却不存在"面。另注第三份 `core/error_handler.py:26`。

#### A4 `neurova/shared_core/{infrastructure,plan_orchestrator}.py`（980）✅
- 原功能：前者把 EventBus/ServiceManager/ProviderManager 装进 DCL 单例做生命周期聚合与健康上报；后者做关键词意图识别→复杂度分档→`TaskNode` 图→拓扑分层→`asyncio.gather` 并发执行。
- 来历：均**引入即未接线**；`plan_orchestrator._handle_llm_call:434` 只回名字、`_handle_tool_call:437` 不调工具，是桩。
- 现役替代：装配由 `api/app.py:335 StartupManager` + `:354 provider_manager`；DAG 分层并发由 `tool_layers/tool_orchestrator.py:140/262`（`agent_core.py:904` 实例化）。
- 判定：删。**须同批带走 `core/service_manager.py`**（其唯一生产 import 是 `infrastructure.py:25`），并改 `test_singleton_convergence.py:31/41`。三套 plan_orchestrator（本文件、`core/`、`execution_engine/`）生产侧全零 import，一并裁才符合教义第 5 条。

#### A5 `neurova/auth/{password_hasher,enhanced_user_model}.py`（971）✅
- 原功能：前者 bcrypt 优先、缺席降级 PBKDF2-SHA256(260k 轮、随机盐) + 随机密码与强度评分；后者是 JSON 文件版用户/组/配额体系（`users.json`/`quotas.json`、五档权限表 `:50`、登录失败锁定 `:36`、登录审计）。
- 来历：均**引入即未接线**。
- 现役替代：`api/auth.py:341`（同格式 PBKDF2）+ `auth/user_model.py:155`（SQLite `data/users.db`）+ `user_group_model.py` + `security/rbac.py:25`。
- **凭证存量已实证（v1 提的风险解除）**：`data/users.db` 只读查询得 `users` 表仅 1 行，`password_hash` 为 bcrypt `$2b$12$…`；`data/enhanced_user_model/` 新旧两落点均不存在；全 `data/` 无 `pbkdf2` 命中。且现役校验 `api/auth.py:402` 只认 `pbkdf2:sha256:` 前缀，对 `pbkdf2_sha256$` 一律返 False——即使曾有该格式记录，今天也已登不上，删实现不改变可达性。
- 判定：删（须同批处理 §6-4 的存根断链）。**残留不确定性**：数据根可被 `NEUROVA_DATA_DIR` 注入（`core/data_root.py:35`），桌面部署侧用户库须按同一 SQL 复测后才能落刀。

#### A6 `neurova/core/config_manager.py`（118）✅
- 原功能：内存键值 + JSON 读写 + 环境变量前缀批量导入（`load_from_env:105`，前缀默认拼成 `NEUVA_`，与全仓 `NEUROVA_` 不一致）。
- 来历：**引入即未接线**；`get_config_manager()` 工厂根本不存在，而 `docs/01-architecture/plugin-architecture-design.md:707` 仍按它存在写 import。
- 现役替代：env 口径 `core/config.py:449/462/483`；持久化配置面 `shared_config.py:39`。
- 判定：删，**并同批裁 `core/config.py:60 ConfigManager` 与 `:424 get_config_manager()`**——二者同样零生产调用（`get()` 系列直读 `os.environ`，注释里"未来接入 ConfigManager"从未发生）。只删一个等于把三份变两份。

#### A7 `neurova/execution_engine/mcp_manager.py`（425）+ `tool_layers/schemas.py`（87）◑
- 原功能：自带四套 MCP 模型的连接管理与工具发现（`_connect_stdio:213` 裸 `subprocess.Popen`、`_discover_tools:287` 手写 JSON-RPC 管道）。
- 来历：**删过又被误复活**——`fa335b27`(08-31) `git rm` 并写明"生产链路已由 `tool_layers/mcp_client.py` 全面取代，消费方为零"；两天后 `34b0678b`(09-02) 以 420 行纯新增带回，提交说明自陈"**未跟踪遗留补提交**"。
- 现役替代：`tool_layers/mcp_client.py:89-112`（官方 SDK，三分支，未知 transport 显式抛错）+ `mcp_config.py` 严格校验 + `mcp_bootstrap.py` 装配（`app.py:734` → `agent_core.py:935`）。
- 判定：删，**且属安全闭环项**：`:213` 直接 Popen `config.command`，**绕开 `mcp_config.py:40-70` 的 shell 拒绝门**；`:248/:259` 的 sse/http"连接"是假的（注释自陈"简化实现：标记为已连接"）。
- **前置动作**：守卫 `tests/unit/tools/test_t09_selfloop_face_ruling.py:138/217` 前提经查为假——`mcp_client.py` 全文不引用 `MCPConnection`，断言之所以绿是因为 `mcp_manager.py:115` 定义了**同名但不同源**的自己那份。须先立红灯改守卫再退役；`scripts/ci/tool_loop_deadline_ledger.py:233-235/250` 的落点标注也已过期（文件现 87 行）。

#### A8 `neurova/execution_layers/__init__.py` 传输半区（≈200）◑
- 原功能：远程执行传输抽象（`ExecutionTransport` ABC、HTTP/WS 实现、`TransportFactory:561`）。
- 来历：引入即未接线；`execute_skill:579` 的 `transport` 形参 `:583` **收下后函数体从不使用**——典型只写不读。
- 判定：**只删传输符号**（`:36-44/:149-182/:438-541/:561-577`）。同文件运行时半区在役（`LocalExecutor:183`、`DockerExecutor:297`、`RuntimeFactory:542`，被 `sandbox/exec_sandbox.py:421`、`tool_executor.py:5691`、`skill_system.py:702` 用），按文件判死会误杀。

#### A9 `neurova/cognitive_layers/memory_layer/` 换代残留（≈2460）✅
- 原功能（择要）：`relation_mixin` 纯内存图存储 + DFS 多层邻居 + BFS 最短路径 + 图密度统计；`search_mixin` 宣称"向量 + FTS5 全文 + 混合"三层检索；`dream_mixin` 梦境（记忆融合）报告内存 CRUD；`explainability_storage_mixin` 触发链内存存储层；`forgetting_recovery_storage_mixin` 归档/软删两条暂存队列 + 恢复率统计 + 30 天过期清理；`modules/storage_module` duck-typing 后端门面。
- 来历：见 §4 三段式。**`search_mixin._text_search:87`/`_vector_search:104` 是注释"简化实现"、恒返 `[]` 的空壳**，唯一真实算法是 `_merge_results:120` 的 RRF(k=60, 0.4/0.6)。
- 现役替代（逐条核过存在）：`modules/relation_module.py:52`（`manager.py:3542` 装配）、`graph_traversal.py:71 traverse_bfs/dfs/find_path`、`sleep.py:967 get_dream_logs`（`:950` 落盘，REST `api/endpoints/sleep.py:319`）、`manager.py:4031/4049` 归档与恢复（走 `LifecycleStage` + `_persist_memory` 落库）、`storage.py:270 MemoryStorage` + `cognitive_storage_engine.py`、`knowledge/hybrid.py:38 rrf_fusion`（单源，`semantic_search_api.py:202` 委托）。
- 判定：删。`storage_module:79-81` 属"backend 未注入即 warning + 返 None"的静默失败门面，违教义第 2 条。

#### A10 `emotion_adapter` + `conflict_detector_v2` + `bus_event` 协议面（≈570）✅
- 原功能：`emotion_adapter` 是向后兼容门面（9 方法各转发一次，带 `use_legacy` 开关）；`conflict_detector_v2` 向量+实体双阈冲突检测（同实体相反属性判矛盾、相似内容按时间判演进，属性用 `不|没|非常|很` 前缀取反）；`bus_event.MemoryModule` ABC + `ModuleHealth` 三态健康上报 + 10 个事件类型常量。
- 来历：`emotion_adapter` 属"预留兼容层但从无人迁进来"（`7835c367` 起孤立）；`conflict_detector_v2` 的唯一消费者 `result_processor.py` 在 `0c333a76`(09-21)「清退 5 组死码」中被删；`MemoryModule` 全史 `git log -S "MemoryModule)"` **零命中——从未有任何类继承它**，6 个常量亦从未有 emit。
- 现役替代：`memory_layer/emotion.py:427`（活于 `api/endpoints/memory/emotion.py:159`、`tool_executor.py:5454`）；`conflict.py:141 LegacyConflictDetector`（`agent_core.py:409` 装配，`:260` 又把别名指向它）。
- 判定：删。**`emotion_adapter:46-82` 是教义第 1/2 条的点名形态**：`except ImportError → SimpleAnalyzer` 恒返 neutral/0.0，即 consumer-only guard + 假成功。同批处理 `memory_layer/__init__.py:33` 从 v2 再导出 `ConflictDetector` 与 `conflict.py:260` 的同名遮蔽。

#### A11 `neurova/llm/{config_resolver,config_console,client}.py` + provider 静态件（≈730）◑
- 原功能：三层 LLM 配置合并（Agent 显式 > 服务商 > 系统默认，带 `_source_*` 来源追踪）；单体 JSON 上的服务商 CRUD、默认/单服务商参数与 Token 用量聚合（`test_provider_connection:192` 只回读 `enabled`，不真连）；`client.py` 是 8 行纯注释占位（自称"为保持导入兼容性"却无一行 import）。`_get_default_pydantic_models`（openai `:392`、openrouter `:450`、gemini `:294`）三处全库零调用且与上一行函数**逐字同体**。
- 来历：均引入即未接线；`_DEFAULT_MODELS` 最后一次生产读取被 `b1dfb744`(08-31) 与 `672d3a10`(09-15) 改为"失败即返空"。
- 现役替代：`agent_core.py:295-322` + `multi_model_client.py:235-298` + `llm_routing_overlay.py`；服务商 `provider_manager.py:657`；Token 统计 `core/usage_history.py`。
- 判定：删（`client.py` 是本组唯一"删了不失去任何能力"的确定项）。**`_DEFAULT_MODELS` 本体除外**——见 §3-B11。

#### A12 `neurova/llm/providers/secret_store_clean.py`（603）✅ —— **v1 归错档，已纠正**
- **v1 错判**：列进"零生产消费者"。**实为有活链**：`api/endpoints/settings.py:193/211/229/246/259/280` 六处 REST → `web_reach/credentials.py:22`（该链由 `2a5f79b8` 09-15 落地）。删除即断社交凭据存取。
- 原功能：无第三方依赖的密钥库，`SimpleCipher` 用 SHA-256 密钥流对明文做**循环 XOR** 再 base64（`:79-103`）；带过期、轮换计数与访问审计日志。
- 判定：不按死码处理，改走双源收口——先把 `credentials.py` 迁到 AES-GCM 版（`providers/secret_store.py:127-183`），再删本文件与 `test_singleton_convergence.py:28` 条目。**顺带是安全修复**：重复密钥流 XOR、无 MAC，属弱加密。

#### A13 `collaborate/{models,template}.py` + 顶层 `context.py`（≈556）✅
- 原功能：协作角色/模板枚举、带 `depends_on` 的步骤模型与拓扑排序（`models.py:89`）、模板管理器类型/标签索引与 search/clone；顶层 `context.py` 是 33 行纯 re-export 垫片。
- 来历：`collaborate/` 的失活有明确现场——`52fbe7ea`(06-03) 曾把 `collaboration_api.py:527/635/639` 的枚举类型指向本包，次日 `7835c367` 把该 API 从 970 行重写成 154 行，**意外切断**；`template.py:367` 的 `from .preset_templates import` 指向自身包内**从未存在**的文件（`git log --all` 零命中），落库首日即必抛，`:371` 吞掉后管理器恒空。
  顶层 `context.py` 更戏剧：`2482c042`(06-03) 落库时它是 **50882 字节的真实现模块**，同日 `1832a12b` 把实现迁进 `context/` 包并**清空为 0 字节**，次日 `7835c367` 又从 pyc 骨架填回这 33 行——`neurova/__pycache__/` 有 `context_cache`/`context_pool` 的 .pyc 却**无 `context.cpython-312.pyc`**，实证从未被编译执行。
- 现役替代：`agent/templates/collaboration_template.py`（行级相似度 0.819 且为严格超集）；`context/__init__.py:25-41` 已导出全部 8 个 `__all__` 成员，实测 `FileFinder.find_spec('context')` 解析到包。
- 判定：删。同批改 `tests/unit/test_refactor_imports.py:66-106/120-135` 兼容钉，与 `docs/01-architecture/FUNCTIONALITY_ANALYSIS.md:95-96/163-168`、`architecture-review-20260606.md:113` 的悬空指向。

#### A14 `channels/{wechat_message,wechat_ai,base_adapter}.py`（893）◑
- 原功能：微信/企微/公众号/iLink 消息解析与发送、去重过滤、SHA1 回调验签；文生图/图生图/文生视频/图生视频/首尾帧/视频生视频六能力（bytes 契约）+ URL 下载与临时文件；`base_adapter` 仅 re-export `ChannelAdapter`。
- 来历：`7835c367` 引入即未接线；`abecada6`(06-14) Channel 拆分建替代件；`b7c3f802`(09-14) 只修其内部 legacy 工厂调用，未接消费方。
- 现役替代：解析 `wechat_parsing.py:35/52/126/212/278/351`、发送 `wechat_messaging.py:33/50/108/131/182`、去重 `wechat_messaging.py:245`、验签 `wechat_auth.py:310`、生成 `wechat_ai_generation.py:22/69/132/181/236/293`（走 `get_generator_manager`）——经 `wechat.py:29-40` 混入（**实为 6 个 mixin，非 v1 所记 3 个**）。
- **微信验签专项核实**：`wechat_message.py:367-407` 与活路径 `wechat_auth.py:310-326` 算法同、实现非同文（差异三处：token 来源、失败处理、形参名）；**删前者后验签能力仍在活路径保留**，且守卫 `test_wechat_split.py:59` 断言 `hasattr(WeChatAdapter,'verify_signature')` 会兜住。`wecom.py:45` 是独立的四参含 encrypt 口径，不受影响。
- 判定：删，**须同批退役 `llm/generators/runtime.py:395` 的 `LegacyBytesAdapter` + 两个工厂 + `generators/__init__.py:30/32/33/49/52/53` 导出**（其生产侧唯一消费方就是 `wechat_ai.py:60/118/178/236/301/367` 与 `feishu_ai.py:50/108`）——教义第 5 条同根因扫荡。

#### A15 `neurova/knowledge/config.py`（325）◑
- 原功能：`FlowKBConfig`/`KnowledgeBaseConfig` pydantic 模型 + JSON 读写/重置/摘要。
- 来历：引入即零导入（连 `tests/` 亦零命中）；`721ef038`(09-22) 只改数据根路径。
- 现役替代：`/v1/knowledge/configs` 端点走 API 侧自有模型；embedding 口径事实源是 `neurova/embedding/onnx_embedding.py:62`（`BAAI/bge-small-zh-v1.5`），经 `knowledge/vector_index.py:39` 消费。
- 判定：删。本文件自称 `all-MiniLM-L6-v2`/dim 384（`:53-54`）是**未被读的平行第二口径**；`core/config_manager.py:7` 的"兼容 knowledge/config.py"注释是失效指向，一并清。若产品真要 faiss/MiniLM 则改接线，二选一不可并存。

#### A16 `neurova/skills/` 零消费者簇（≈2400）✅
- 原功能（择要）：`evolution_engine` 技能目标设定/指标累积/进化潜力分析/历史；`skill_chain_executor` 依赖与数据流编排 + 暂停/续跑/取消 + 步间输入输出映射；`auto_skill_improver` 按使用指标出改进提案 + A/B 提示词优化；`prompt_optimizer` 评测集驱动的确定性变体生成与迭代择优；`registry.py` 原为第二套注册表（`register(manifest,path)` 双参、`skills` 返 Tuple）；`manifest.py` 13 行别名转发。
- 来历：**不是逐个失活**——`33b71a25`(06-13) 一次提交把 `skills/__init__.py` 里 **17 条桶层侧效导入整列改为 `pass`**（diff 行 80-194 可逐条复算），一次性摘掉整条链；`:108-211` 那 15 个空 `try: pass` 就是那次手术的缝合疤。`registry.py` 的 class B 早在 `0664d3a9`(07-15) 依 ADR 0011 被删并改为 re-export，两个 dataclass 是那次删除的孤儿。
- 现役替代：`evolution/evolution_facade.py`（活链三处）、`neurflow/execution_engine.py:1331/1368` + `dag.py:141/52` + `checkpoint.py` 持久化、`builtin_tools.py:1233 orchestrate_tools`、`evolution/skill_improver.py:150`（`post_chat_pipeline.py:2765`，其注释即"根因修复：此前零调用"）、`evolution/eval/mutator.py`（`:5` 明确把 `prompt_optimizer.generate_variants` 指为"加角色段/结构段的**盲目变异**"predecessor）、`skill_system.SkillRegistry`、`manifest_{entry,provider,source}.py`。
- 判定：删（含 `models.py` 零引用类簇——16 个 `*Stats` + 15 个 `*Result` 生产引用均为 0；保留 `Skill:132`/`SkillInfo:25` 系与被链读的 `:489-491` 别名）。
- **两条附带真相**：① `tests/unit/skills/test_skills_evolution_engine.py:10-17` 导入的是**不存在的** `SkillsEvolutionEngine`/`SkillEvolutionRecord`，`_HAS_*=False` 致整文件恒跳过——"有 N 个测试通过"一类说法须按此折价；② `prompt_optimizer.py:3` 有"对齐 agent-core 的做法"字样，触 AGENTS.md 第三方对齐红线，删除即一并消除。
- **v1 路径更正**：`_has_command_substitution`/`_has_encoding_evasion` 不在 `channels/base.py`（该文件仅 261 行，`:397-413` 不存在），实际在 `security/tool_guard.py:397/:406`；误标源自 `audit-reports/complexity-report.json`。判定仍是删（`_evasion_patterns:380-391` 已覆盖同类判据并在 `guard():414` 生效）。

#### A17 `neurova/plugins/`（1451）✅
- 原功能：插件目录扫描 + 动态 import 装卸、生命周期钩子、semver 约束与权限校验的进程内插件框架。
- 来历：**曾有生产消费方**——API 端点的 `_get_plugin_manager` 注入面被 `f2094cfd`(09-12, P7) 摘掉；`ed80b725`(09-14) 按新契约重写了测试。
- 现役替代：`api/endpoints/plugin.py:37` 只是进程内字典 store，**不做真实加载**——"插件系统"对外面还在、里子是空的。
- 判定：删（连 `core/api_router.py:160` 无调用方的死钩子）。
- **pyyaml 不可随包摘**：守卫 `test_install_supply_contract.py:136` 把它钉在 `plugin_manager.py:26`，但仓内另有 4 处函数内惰性 import（`computer_use/browser_manager.py:1540`、`evolution/rsi/self_improvement_proposer.py:946`、`language/manager.py:176`、`skills/hub_client.py:695`）——守卫应改指其一，直接删会让"供给契约"变成假绿。

#### A18 `neurova/{media,language}.py 两包` + `neurova/cognitive/`（≈1300）◑
- 原功能：媒体资产 JSON 索引落盘 + 日期归档/缓存配置（`agents/{id}/workspace/media/`）；后端 11 语翻译表 + 用户语言偏好 + 翻译缓存；JSON 版认知编排（代理注册、任务流水线 `orchestrate()`、注意力、记忆）。
- 来历：`media` 有明确失活点——唯一生产消费方 `api/endpoints/media.py:144` 被 `15eb32f4`(09-11) 摘掉；`language` 引入即未接线；`cognitive` 的包内自引用在 `33b71a25` 被摘成 fail-soft 空壳。
- 现役替代：媒体由端点自持 `media_index.json`/`media_config.json`（**两套落点属平行体系**，删包顺带收口）；语言由 `NeurUI/src/i18n`（11 语守卫）+ `settings.py:37` 单键；认知由 `cognitive_layers/` + `core/cognition_orchestrator.py:315`（后者自身也仅测试引用、生产未接线）。
- 判定：删。注意"后端持久化译文库"随 `language/` 一并消失（全仓唯一实现，但现役确无调用方）；`cognitive` 与现役的差集见 §3-B14。`tests/cognitive/`（含非用例文件 `_cognition_fix.py`）违反 AGENTS.md 测试目录归属红线且未登记 `protected_tests.txt`，同批删。

#### A19 顶层四件（≈1615）✅
- `context_cache.py`(724)：对话上下文内存 LRU——四维键 `(agent,channel,user,session)`、命中计数、脏标记、批量落盘、后台写线程、上限驱逐。来历 `7835c367`，**引入即未接线**；集成测试 `test_context_cache_compression.py:34` 按已不存在的形参构造，台账 `docs/05-reports/上下文三链路修复台账_2026-09-21.md:1135` 记为预存红；唯一内部构造 `:138` 缺必填 `data_dir` 必抛 TypeError。**删**。
- `context_persistence.py`(380)：按渠道落 JSON 快照供跨会话恢复。**v1 我怀疑"跨重启持久化已消失"，实测不成立**——现役由 `context/eviction_ledger_db.py`（SQLite WAL+FTS5）+ `context_pool.py:60-66` 入池即写穿承载（`780fe050` 09-22 落地，`protected_tests.txt:327` 钉 `test_context_persistence_restart.py`）。两个 `tests/manual/context_persistence_*_90.py` 只是该工单取证脚本，只 import `EvictionLedgerDB`/`ContextPool`，零引用本模块。唯一未被覆盖的形状是"按 channel 维度列会话"（现役隔离维度改为 `session`/`chat_scope`）。**删，不构成能力丧失**。
- `voice_adapter.py`(331)：把 `TTSManager.synthesize`/`ASRManager.transcribe` 适配成统一 `adapt_process/adapt_result` 契约。唯一调用方是仓根临时脚本 `test_voice_closed_loop_simple.py`（只喂 Mock manager），被 `98b5422a`(06-09)「清理临时文件」删除 → 此后零调用。分派已在 `voice_engine.py:71` 门面内完成。**删**（含 `tests/unit/voice/test_voice_adapter.py` 261 行）。
- `neurova/expected`(0 字节)：非模块、全仓零引用。由 `98b5422a`(06-09) 以 0 字节新增，**同 commit 另新增仓根 `missing`(0 字节) 并删掉 471 行 `missing_files.txt`**——重定向残留形态坐实。**`git rm`**。

#### A20 `neurova/evolution` 门面死面与增强剪枝（≈310）✅
- 原功能：`evolution_facade` 门面模式把 orchestrator 内部组件（tool_weights/tool_lifecycle/pattern_miner/tool_synthesizer）包成 14 个单跳方法 + 全局单例；`EnhancedRatchetPruner`(155) 两阶段剪枝——候选 >20 先递归粗筛，再按 `validation_score` 细筛、剔 ≤0、留每维 top-k 并缓存 `dimension_winners`。
- 来历：门面 `on_after_tool_execution` **曾有唯一生产调用方 `agent/tool_executor.py:493`**，整块被 `7f8c7660`(06-25) 删除；其余方法全史零调用。`EnhancedRatchetPruner` 由 `b096a047`(06-08) 引入即未接线，而 `docs/01-architecture/RSI_INTEGRATION_COMPLETE.md:24` 却把它列为"集成完成"——**文档虚报**。
- 现役替代：门面直构三处（`post_chat_pipeline.py:1710`、`neurflow/builtin.py:1208`、`pattern_crystallizer.py:369`）只用 `record_experience`/`notify_pattern_crystallized`；被包装能力改走直调 `tool_executor.py:5829/5909`、`closed_loop.py:493/572`；剪枝现役是 `RecursiveRatchetPruner.recursive_prune`（`orchestrator.py:158/949`），逐参数只取单一最优。
- 判定：删死面保活面（约留 66 行；死面复算为 **12 个方法**，v1 记 10 偏低）。单例三件已被点名违 agent 级隔离（`facade:207-208`）。两阶段/按维 top-k 属"从未进生产闭环的假设性能力"，删不撤在用能力。

### B. 需人裁 —— 全仓唯一实装，删即永久失去该能力

> v1 把这一组算进了"可删"。静态上它们确实零消费者，但没有任何现役实现顶上。
> 按 v1 批量删除，等于由代码审计替产品关掉十余项能力。全部改为需人裁。

#### B1 安全域五件（约 2730 行）✅ —— 逐能力覆盖矩阵

该子任务两次失败（一次返回无关的童话旁白、一次返回空），矩阵由主会话自行取证算完。

| 能力 | 唯一实现落点 | 今日承载者 | 差集 |
|---|---|---|---|
| 提示注入检测 | cognitive_security.py:109（约 26 条中英签名，覆盖指令覆盖、角色切换、系统提示套取、分隔符注入、base64/rot13/十六进制/Unicode 混淆） | security/skill_scanner.py:169 的 PromptInjectionAnalyzer，11 条中英签名，活链在 chat_pipeline.py:1273、tool_executor.py:2355、skill_install_gate.py:232 | 现役不检测混淆编码类载荷；签名 26 → 11 |
| 敏感信息识别 | cognitive_security.py 的 SensitiveInfoDetector；data_masking.py:84（6 策略 + 8 类 PII 文本正则 + 日志/导出三出口） | privacy_gate.py:69（活于 chat_pipeline.py:2320/2486） | 现役只按键名脱敏工具参数，无手机/邮箱/身份证文本正则，**日志与导出两条通道今日无人守**（core/logger.py 无脱敏） |
| 输出侧有害内容过滤 | cognitive_security.py:289 的 OutputFilter，制爆/自伤/入侵/盗窃中英模式，命中替换为「内容已过滤」 | **今日无人守** —— 全仓 grep 该类名与替换串只命中该文件自身 | 完全缺失 |
| 危险行为 risk_score 累加与阈值裁决 | cognitive_security.py 的 CognitiveSafetyChecker（危险关键词 + 绕过尝试累加，过阈值出 is_safe） | **今日无人守** —— 其余 risk_score 命中只在同样无消费方的 autonomous_assessor.py:45 与一个外部数据转换器里 | 完全缺失 |
| 记忆写入安全裁决 | cognitive_security.py:492 的 MemorySecurityGuard | **今日无人守** —— 五个 add_memory 实现（crud.py:80、memory_layer/manager.py:2057 等）全无安全门 | 完全缺失 |
| 合规报告生成 | compliance_reporter.py:138（HTML 模板：安全概览/GDPR/等保/审计摘要/访问控制，含订阅、下载、删除） | **今日无人守** —— api 内「合规」「gdpr」零命中；audit.py 只查审计日志、不产报告 | 完全缺失 |
| 技能安全评分与评估台账 | autonomous_assessor.py:111（行为分析 + 代码质量 + 风险，加权出 SecurityScore，落历史台账） | skills/security_scanner.py:490 + skill_install_gate.py:27 覆盖模式/注入扫描与安装 DENY | **无加权评分、无评估历史台账**；该模块头注释自承"与 SkillScanner 集成"却从未 import 它 |
| 宪法规则判定引擎 | constitution.py:97（5 条默认规则，按 RuleType 关键词命中 context，产违规记录与 block/warn 动作） | constitution_router.py + constitution_persistence.py 只做规则 CRUD 与 growth.py:329 展示，**不判定**；governance.py:403 只裁命令/路径，不裁内容/伦理/歧视 | **宪法判定今日无人守** |

判定：五件全部**不得按死码退役**。其中三格（输出过滤、risk_score 裁决、记忆写入门）在全仓只有这一处实现，属"安全基线唯一实装"。
正确动作是先裁"要不要这些能力"：要，则接线进 `chat_pipeline` 的对话前后各一次调用位与 `add_memory` 入口；不要，则连同文档与测试显式退役并改规则，不能静默删。
另注：`tests/execution_engine/test_tool_engine_v2.py:86` 至今 Mock 一个生产侧已不存在的 `engine._cognitive_security` 属性，是幽灵 Mock（见 §8）。

#### B2 飞书渠道三件（640）◑
- 原功能：`feishu_message.py:28` 文本/富文本/图片/交互卡片发送与解析过滤；`feishu_media.py:21` 图片/文件上传取 image_key/file_key、媒体下载、类型判定；`feishu_ai.py:15` 飞书 AIGC 生图/生视频 + ai_chat 流式，产物经 media 上传后发送。
- 来历：均 `7835c367` 引入即未接线；`feishu.py:48-49` 注释自证"此前该 Mixin 与 MediaMixin 均为孤儿"。
- 现役替代：**部分缺**。活路径仅 `feishu.py:342` 通用 send_message（msg_type 透传）与 `:191` 解析、`:310 _download_media_bytes` 下载；**上传零替代**（全仓 upload_image/upload_file 仅被同样已死的 `feishu_ai.py:78/134` 调用），卡片/富文本/AIGC 零替代。
- 判定：需人裁。删则飞书发图、发卡片、AIGC 三条能力唯一实现消失 —— 注意这三条**今天运行期本就不存在**（未接线），所以真实选项是"接线补全该渠道"或"明确放弃飞书富媒体"，而不是清理遗留。v1 记入"1533 行可删"是错的。

#### B3 agent 呈现面三件（约 1500）◑ —— 被同一次骨架恢复误杀
- 原功能：`agent/matrix/agent_matrix.py`（562）是能力注册表之上的读模型与呈现层 —— 在线率/均等/分类计数（`get_matrix_summary:174`）、**按分类权重打分的 Agent 推荐**（`recommend_agents:214`）、能力雷达图与对比（`MatrixRenderer:418`）；`protocols/capability_discovery.py`（450）是进程内能力注册中心，11 类 × 5 级量化、倒排索引、模糊检索与 `match_task_requirements:316` 任务-能力加权匹配；`templates/{personality,preset}_templates.py`（79 + **实测 399 行，v1 记 478 有误**）是 5 套人格准则与 4 套开箱协作流程的内容资产。
- 来历：**不是从未接线，而是被误杀**。`2482c042`(06-03) 时 `collaboration_api.py:140` 起有 `from neurova.agent.matrix import get_agent_matrix`，并暴露 `/capabilities`、`/recommend`、`/matrix`、`/matrix/compare`、`/templates/preset` 等端点；次日 `7835c367` 重写该文件时**端点整批删除（24 条路由 → 6 条）**。前端零残留。
- 现役替代：**无**。近邻件均不同物（`agent_enhancement.py:131` 只回静态串、`growth.py:334` 是成长分、`capability_gap.py` 是缺口信号）。"按能力检索/匹配 Agent"与"任务→Agent 推荐"今日全无实现。
- 判定：需人裁，且 **matrix 与 capability_discovery 必须同批裁**（matrix 是后者的唯一消费者：只删 matrix 留它即只写不读；只删它留 matrix 则 matrix 直接不可用）。人格/协作模板属**内容资产删除**，若退役建议先归档进 docs/。另需清 `acp_runtime.py:97-99` 那句把能力注册推给本模块的恒假条件与虚假归属注释。

#### B4 技能域三件（约 1440）◑
- `skills/security_scanner.py`（908）：**全仓唯一的 ast.NodeVisitor 危险节点判据**（`_DangerousNodeVisitor:98`）。现役 regex 规则已等价覆盖 exec/eval/os.system/subprocess/shell=True，但抗注释误报与别名绕过（`from os import system`）只有这一处。判定：需人裁（SkillSandbox 部分无价值可先删）。
- `project_to_skill.py`（482）：从本地仓库/代码目录扫描、提取、打包成可复用技能。`a9268d92` 引入即未接线（内置装载器只扫 `skills/builtin/`，顶层文件永不可见），但摘链后仍被当活码维护 —— `c2cb809c`(09-22) 把它列入"31 个生产文件扫荡"。**现役只做"行为→技能"与外部包导入，无人从仓库目录抽技能**。判定：需人裁（能力真缺，但该实现是模板桩，接线等于重写）。
- `skill_packager.py`（274）：把技能定义 + 使用经验 + 进化历史压成可分享/可续进化的 ZIP。设计文档 `docs/09-dev-progress/module_designs/skill_system_2.0.md:332` 承诺的 `POST /api/skills/{name}/package` **从未存在**（`endpoints/skill.py` 实有 6 条路由无一匹配）。消费侧活着（market_importer 读包），**产 ZIP 侧零替代** —— 即"技能离线可携/跨机分发"处于"文档有、代码死、线上无"三不管。判定：需人裁。

#### B5 认知层五件（约 2060）✅
- `memory_layer/explainability.py`（646）：**DAG 形态**触发链追溯 —— 7 类节点的有向图、反向回溯、文本可视化、JSON 导出/导入。现役 `modules/explainability_module.py:52` 是扁平记录，无 DAG、无 import/export，且**其上游 `manager.py:3990/4004/4007` 外部调用方为零、REST 侧无 explain 端点** —— 即整条可解释性链今天不通（复算：全仓 `.explain_memory(` 零命中）。判定：需人裁，只删老文件会把断点藏得更深。
- `sleep_adapter.py`（198）：**固化结果回写记忆图谱的唯一已写好通路**（`_apply_results:134` 把 merge/archive 结果写回图谱节点）。今天两条实现各跑各的（`agent_core.py:1376 SleepConsolidation` 与 `:1424 CognitiveStorageEngine` 之间无桥），`modules/sleep_module.py` 是第三份实现。判定：需人裁，且须先在"睡眠三套并存"裁定后处置。
- `modules/emotion_conduction_module.py`（233）：**记忆之间**的情感传导（建无向邻接、按源情感值沿邻居衰减扩散、聚合多记忆情感）。活的 `emotion_context_layer/emotion_conduction.py:28` 是 **agent 级心情**传导，口径不同、非等价替代。判定：需人裁。
- `positional_encoding.py`（296）：NeRF/Fourier 频率编码，把时间/情感/重要性等连续标量升维（时间 52 维、情感 48 维），替代分段阶跃衰减。其唯一引用方 `memory_field.py` 在 `0c333a76`(09-21) 作为零消费者整删。现役时间/重要性仍由 `temperature.py` 分段曲线承担。判定：需人裁（连续频域表示今日无承载）。
- `time_awareness.py` 死方法群（约 690 / 全文件 952）：日习惯与周期模式分析、五路事件预测（周期/季节/中国节日/习惯/类别）加置信度、季节偏好。活面仅 `get_time_context_hint`（信封源，`context/envelope.py:76/97` 消费）。复算：`git log -S` 三个方法名在 `neurova/` **仅命中骨架恢复那一次**，即从未有调用方被摘 —— 属生成即未接线。判定：需人裁（保活面、删死群；若"时间感知预测"仍在路线图则接线），不可整文件退役。

#### B6 核设施两件（约 820）◑
- `core/event_bus_enhanced.py`（425）：内容级事件过滤、历史事件重播、处理器级死信与重试、单事件超时、事件链触发。**曾有唯一消费方** `evolution/event_driven.py`，该文件自身也在 `47660760`(08-27) 被判零调用方删除（`evolution/__init__.py:43` 留有注释）。现役 `core/event_bus.py` 只到 `get_event_log:292`，无 filter/重播/死信/事件链；`agent/protocols/dead_letter_queue.py` 是 ACP 消息域，不顶这个位。判定：需人裁（它服务的闭环已判死，留着的唯一理由是"将来补事件死信"，属产品决定）。
- `core/state_manager.py`（396）：点号嵌套状态树、变更日志与监听器、快照/回滚、变更事件外发。**其测试引用面本身是坏的**：`StateManager.__init__(self):62` 无任何形参，而 `tests/integration/test_event_workflow.py:26` 等多处写 `StateManager(event_bus=...)` 必 TypeError；设计文档预期的消费方 `plugins/base_plugin.py:282` 调的是本类没有的 `get_state/set_state`。现役 `api/app.py:41 AppState` 无追踪、`checkpoints/` 是文件级 git 快照，均不等价。判定：需人裁（接线不是低成本选项 —— 它与所有预期消费方的契约都不匹配，接线等于重新设计）。

#### B7 协作域两件（约 570）✅
- `coordination_decorators.py`（304）：把新鲜度预检与 glance 让位规则做成装饰器/中间件，给协作操作加"操作碰撞即拒"与"让位退避重试"两道门。**v1 指认的"现役替代"是错的**：`glance_yield_rules.py:334` 自带 `# For now, simplified version` 注释，用自己的 `_seen_sequences` 而非 SeenCursorManager；真实情况相反 —— `coordination_decorators.py:47` 是 `seen_cursor.check_freshness` 的**外部唯一调用方**（`:386` 是类内自用）。径删即断掉这条判定。判定：需人裁（偏接线），另须先修 §6-5 的 await 缺失。
- `neurflow/workflow_evaluator.py`（263）：确定性断言的工作流评估跑道 —— 5 型断言（output_contains/equals/json_path、status_equals、node_completed），逐样例执行、单例失败不中断整批，产出可序列化报告。与专用测试同 commit 新建、从未接线。现役 `neurflow_api.py:464/595` 只执行不断言，`event_recorder.py:51` 只记录不判 pass/fail —— **断言层今日无任何承载者**。判定：需人裁（`evaluate_workflow` 已直连 execution_engine，接一个端点即可活）。

#### B8 `neurova/api/api_key_manager.py`（568）✅ —— 台账已挂起待产品拍板
- 原功能：Agent×用户维度的密钥生命周期 —— `generate_key:240` 出 `secrets.token_urlsafe(36)` 明文（仅返回一次），只落 SHA-256 哈希与前 8 位 prefix；`validate_key:306` 以哈希反查 + 校 is_active/过期 + `touch():84` 记 last_used；JSON 全量落盘 + S-19 脏标记 30 秒防抖 + atexit flush；另有权限位判定、过期清理与统计。
- 来历：`7835c367` 以 94 行引入，**历史上从未有生产消费方**；后来被改的是它自己（`d444519d` 09-11 防抖、`721ef038` 09-22 落点锚定）。
- 现役替代：CRUD/哈希/用户隔离面**有**（`endpoints/openplatform_keys.py`、`agent_communication_api.py:97-107`）；但**"用键调 API"的验证消费断链** —— `openplatform_keys.py:9` 自陈 nrv_ 密钥全仓无验证方，`global_auth.py:151`、`auth.py:313` 只认 JWT/X-Service-Token。哈希反查式验证 + last_used 记账 + 权限判定 + 过期清理 + 落盘防抖 = **无现役替代**。
- 判定：需人裁。台账 `docs/资源型修复登记台账_2026-09-11.md:281-282` 已两处显式挂起（"未接线备选实现，与 openplatform_keys 双头存储 —— 先定真相源再合并/删除""nrv_ 认证入口需产品口径"）。**这条不是审计新结论，是仓内已有待决项**，不得按"零消费者"径行退役。

#### B9 `neurova/analytics/`（1266）✅
- 原功能：进程内 Agent/User/Task 指标收集器 + 假数据兜底门（ALLOW_MOCK_METRICS_ENV）。
- 复算的关键事实：**collector 只写内存 dict（`collector.py:103-107`），不落任何表**；而 `/v1/analytics`（`analytics.py:263/368/411/442`）实读 prometheus REGISTRY + SessionRepository + TokenUsageAccounting —— **两侧零交集，collector 全链无读者**。
- 唯一外部消费：`scripts/ci/perf_gate.py:390/393/400` 经 `importlib` 动态装载取一个 env 常量。
- 判定：需人裁。两条路都要动多处：接线要把 `collector.py:211/318` 的 getters 汇入四端点或导出到 `core/metrics` 的 `/metrics`；退役要删 `perf_gate.py:386-410` + 注册项 `:439`、`tests/performance/test_perf_gate_contract.py:110`、`tests/unit/analytics/` 两文件、整包，以及 `docs/01-architecture/08-project-structure.md:95` 的登记。

#### B10 `neurova/crdt/`（996）✅ —— 仍写在路线图上的能力
- 原功能：RGA 字符序列 + GSet/PNCounter/LWW/ORSet 合并语义，做富文本协同编辑与操作同步导出。
- 来历：`626e2e88`(09-20) 以 `cdt` 名引入，**内部导入漏改致整包 import 直接崩**，`9545410b`(09-21) 才修 —— 即它从未有过能跑的窗口。全仓零 Python 消费者、零测试。
- 现役替代：文档同步现由乐观锁 409 承担（`canvas_ops.py:11`、`collaboration_api.py:640`）。前端唯一相关处 `NeurUI/src/stores/collaboration.optimized.ts:22` 是**注释掉的** `@/crdt` 加 `type CRDTDocument = any` 占位，且该文件全仓零引用。
- 判定：需人裁（我**不采纳子代理的"删"**）。`docs/03-user-guide/UI开发计划.md:279` 今天仍把"使用 CRDT 或 OT"列为计划项 —— 删它是替产品关掉一条还写在路线图上的路径，这个决定不该由代码审计代做。

#### B11 `openai/openrouter._DEFAULT_MODELS`（约 150）◑
- 原功能：静态模型目录（id/name/capabilities/max_tokens/context_window/pricing），作 API 发现失败时的兜底素材。openai 5 条、openrouter 11 条。
- 判定：需人裁 —— `tests/unit/llm/test_nokey_honest_discovery.py:134` 与 `test_provider_nokey_p6d.py:30` 显式断言"默认列表保留为素材"，删数据即红两条守卫。同批可确定删的只有三份逐字同体、全库零调用的 `_get_default_pydantic_models`（A11）。

#### B12 `llm/model_route_config.py`（355）◑
- 原功能：用户/管理员/系统三级路由表持久化，按 RequestType + user_id 匹配，用 `_LEVEL_RANK` + priority + updated_at 三级排序选最优。
- 现役替代：自动路由 `llm_router.py:424`、请求级媒体覆盖 `llm_routing_overlay.py`、用户显式选定 `endpoints/model.py:439`。**"用户设定 > 管理员设定"这条优先级链无替代**；`data/` 下无其落盘目录，运行时从未写过。
- 判定：需人裁。若不做管理侧按请求类型的路由表则删（其 `RequestType:54` 与 `llm_router.py:31` 已是两份枚举，删顺带收口）；若要做，这是全仓唯一的三级路由实体，删即需重建。

#### B13 `lm_studio_provider.py`（378）◑ —— 附一条真 bug
- 原功能：LM Studio 本地服务适配，`GET {base_url}/models` 发现已加载模型、按名推断能力与上下文窗，默认 api_key 为 lm-studio、base_url 为 localhost:1234/v1。
- 复算：`git log -S '"lm_studio": LMStudioProvider"'` 与 `-S LMStudioProvider -- provider_manager.py` **均零命中 —— type_map 从未注册过它**。唯一提及处 `providers/__init__.py:79-82` 是 `33b71a25` 那次降级成的 `try: pass` 死块。
- 现役替代：`provider_manager.py:2052` 的 `cls = type_map.get(..., OpenAIProvider)` 静默回落，而 LM Studio 本身是 OpenAI 兼容端点，故**同 base_url 经 OpenAIProvider 已能跑通**。
- 判定：需人裁，且**倾向删 + 修判据**。证据：`provider_manager.py:1309/1321` 比的是 provider 类型串，但 `add_provider` 无类型校验、`ProviderType` 无 LM_STUDIO 成员，前端"LM Studio"卡实际发送的是 protocol 值 openai（`NeurUI/src/pages/ModelPage.vue:541/919`），手动添加框亦无 lm_studio 选项 —— 即**那两条 lm_studio 豁免分支不可达**。副作用是真 bug：无 key 时该卡落到 `:1326 return False`，聊天模型切换器显示灰点。不宜接线：本模块 `get_available_models:81-83` 仍回落静态默认模型，正是 `672d3a10`(09-15) 在 openai/openrouter 上根治掉的"假数据"形态。正解是按 `base_url` 本地性/category=local 重写豁免判据（教义第 5 条同根因全命中点）并删本文件。

#### B14 `neurova/recovery/` + 若干存疑待裁项 ◑/✅
- `recovery/shutdown_guard.py`：sentinel 异常关机标记 + 关停刷各 Agent 缓冲 + 崩溃后按 agent_id 恢复记忆。引入即未接线。复算：`api/app.py:62` 的 `self.shutdown_guard = None` 是**全仓唯一出现处** —— 不是"写了守卫不读"，而是从未赋过真值、也从未被读。正常关停有人（`app.py:1092 _on_shutdown` → `agent_core.py:2098` + `agent_shutdown.py` 睡眠整理与缓冲刷新），**崩掉之后没人管**：其余 sentinel 命中全属无关（`openai_loop.py:33` 流终止哨兵、`working_memory.py:64` cache-miss 哨兵），且 `recover_on_start`/`unclean`/脏标记一类零命中。判定：需人裁（可靠性缺口，见 §6-9）。
- `agent/gate_catalog.py`（151）：门控声明式配置层，pydantic `extra=forbid` 严格校验 + `describe()` 出 JSON Schema 给前端配置 UI + `compile_gates()` 先全量校验再构建。`d3300878`(09-01) 一次性提交本文件 + 其专用测试，**同批未附带任何装配点改动**；配套前端门控配置 UI 从未落地。且其 `IterationParams.max_rounds=20`/`max_tokens=100000` 等复刻 `security/agent_limits_settings.py:24-57`，是 v1 §4.1"limits 三处硬编码"的命中点之一。判定：需人裁（默认应删，除非确定做门控配置 UI —— 那是新产品决策）。
- `core/flow_orchestrator.py`（871）：一次对话的 12 阶段全链路编排仿真，带相位追踪。判定：需人裁偏删 —— 它是**自嗨模型**（`MemoryCoordinator:270` 的存取是全内存 list、`ContextMemoryBridge` 缓存自己的 deepcopy、`ToolFeedbackLoop` 注册表无人填），接线等于重写每一个相位；且 `get_flow_orchestrator:846` 无锁无 DCL 违 §3。留它只会让"全链路有编排器"这一假象继续进文档。
- **v1 一处引用错误更正**：v1 称 flow_orchestrator/state_manager "只被测试或 `scripts/demo_optimization.py` 引用" —— 实测 `grep -rn "state_manager|flow_orchestrator" scripts/` **零命中**，`demo_optimization.py` 只用 task_scheduler/monitoring/memory_layer.storage。该说法作废。

### C. 该接线 —— 模块是对的，缺的是消费方

#### C1 `endpoints/__init__.py` 两个健康检查工厂（约 40 行）✅
- 原功能：闭包工厂产出 `() -> (bool, str)` 的健康检查函数供 `HealthChecker.register` 装配。`create_llm_check:134` 看 `_app_state["llm_client"]`；`create_service_check:162` 看 `startup_manager.is_started`；`create_database_check:115` 借业务连接池 SELECT 1；`create_memory_check:148` 看 `_app_state["agents"]`。
- 来历：`7835c367` 引入，各历史树 `git grep` 除定义文件外零命中 → 引入即未接线。
- 现役替代：database **有且更强**（`app.py:103 _make_database_health_check`，裸 sqlite3 + 3s 超时、不抢业务池）；但 `app.py:132 _register_default_health_checks` **只注册 database/内存(物理内存 psutil)/磁盘** —— 所以 `/v1/health/checks` 今天**永不报"LLM 未初始化""服务未启动"**。注意 `create_memory_check` 语义是 agent 记忆系统是否就位，与现役那个 RAM 检查**同名不同物**。
- 判定：**接线**（v1 判"四个死工厂可删"是错的）。落点现成：`app.py:185` 之后追加 `health_checker.register(name="llm"/"service", check_func=create_llm_check(), check_type=CheckType.READINESS)`，`endpoints/health.py:106/126/146/166` 已在读同一注册表，零新接口；接线时把 `create_memory_check` 改名 `createAgentMemoryCheck` 以消撞名。同文件 `setup_middleware:179`（注意是 179，v1 记 178 有偏）纯转发、真源已被 `app.py:1231` 直取，判删。

#### C2 `neurova/error_logger.py`（258）✅ —— 发射侧已有去处，先裁归属
- 原功能：前端错误的结构化 JSONL 收报与读回（追加、按类型/用户/时段过滤、清空、统计、删档），落 `data/error_logs/all_errors.log`。
- 来历：**与后端接收端点同批入库**（`7835c367` 06-04，`api/app.py:614 POST /api/v1/frontend/errors`，白名单 `global_auth.py:48`），但**端点从不调本模块**。`44f2124d`(09-09) 的 JSONL 重构只改自身。
- 复算的关键事实：前端采集**已端到端接到仓外 PHP** —— `NeurUI/src/utils/errorReporter.ts:17` 默认打到 `https://www.neurova.top/error-report.php`（`e1effa8e` 09-03 引入；初始化 `App.vue:165`、Vue 钩子 `main.ts:51`），自带队列、30 秒去重、每日 100 条封顶；**前端从不打后端那个端点**（NeurUI 全量 grep `frontend/errors` 零命中）。后端侧 `analytics.py:447` 的 LLM prometheus 指标承担今日错误口径，`recent_errors` 恒空写于 `584b265b`(09-02)，UI 亦不渲该字段（`AnalyticsPage.vue:231-238` 只取 by_type）。
- 判定：需人裁，**不是"只缺接收侧所以接线"**（我上一轮的猜测已被证伪）。若把发射侧接回后端，等于造第二源，违教义第 6 条；要先裁"自托管明细 vs 官网收报"。若选自托管，三点必须同批：`app.py:614` → `write_frontend_errors` → `analytics.py:466`，并先处置 PHP 端点。
- **顺带缺陷**：`app.py:614` 是匿名可达（白名单）、收 JSON 后只 `logger.warning` 便返回 `{"status": "logged"}` 的空转端点 —— 客户端被告知"已记录"而什么都没存，且体未见长度上限。见 §6-8。

#### C3 `skills/registry.py`（54）◑
- 现状：自身注册逻辑早在 `0664d3a9`(07-15) 依 ADR 0011 被删并改为 re-export；剩两个孤儿 dataclass 与顶层 `SkillRegistry:35` 再导出。生产零导入，但 **5 个测试文件把它当稳定别名用**。
- 判定：正解是"接线式收口"—— 让测试改导规范源 `neurova.skill_system` 后删本文件，而不是保留第二入口。注意其顶层 `from neurova.skill_system import SkillRegistry` 正是 `docs/09-dev-progress/bug_tracking/circular_import_skills.md` 登记的环状导入隐患之一。

#### C4 `api/endpoints/notifications.py:83/117` 读内存假存根 ✅ —— 现役生产链断链，与退役无关
- 事实：`enhanced_users_api.py:73` 的 `_users_store = {}` 是内存假存根，而 `notifications.py:83/117` **正在读它**。
- 判定：应改接 `auth/user_model.py` 的 SQLite 真源。**须独立成批**，不与 A5 的密码哈希退役捆绑（教义第 1 条：不要在下游补判空，要修上游事实源）。

## 4. 这批死码不是熵增，而是四次大爆炸的未收尾

溯源最有价值的产出：约 50 项候选里，绝大多数能追到同几次提交。**按事件批次清理，比按模块清理有效得多。**

| 事件 | 日期 | 干了什么 | 遗留 |
|---|---|---|---|
| `7835c367` pyc 骨架恢复 | 06-04 | 从 pyc 骨架"恢复"381 个源文件（多为带 `__annotate__` 桩的反编译物）；**同日**把 `collaboration_api.py` 从 970 行重写成 154 行 | ① A 档大半成员在此引入且**从未有过消费者**；② 顺手**误杀** matrix / capability_discovery / preset 模板的 24 条端点（B3）；③ 把已被清空为 0 字节的顶层 `context.py` 用 33 行垫片填回来续命（A13）；④ `template.py:367` 的相对 import 落库首日即必抛 |
| `33b71a25` 集中摘链 | 06-13 | 把 `skills/__init__.py` 里 **17 条桶层侧效导入整列改为 pass**；把 `memory_layer/__init__.py` 的 `from .sleep_adapter import` 改成裸 pass；清空 modules 集中注册表（18 个 import → 空 docstring）；把 lm_studio 的副作用 import 降级成死块 | **38 处 try-pass 死块的主要产地**（§5）；老 mixin 文件在消费者已没了的**同一次提交**里才被补成完整实现体——"老文件全留"是恢复期副作用，不是迁移计划（A9） |
| `0c333a76` 清退 5 组死码 | 09-21 | 真删 `memory_field.py`、`result_processor.py`、`forgetting_recovery.py` | 只删了消费方，**留下** `positional_encoding.py`、`conflict_detector_v2.py` 等被孤立的实现——典型的第 5 条未扫荡 |
| `4a3c9380` 测试批量入库 | 09-04 | 解除 `.gitignore` 对 `/tests/` 的整目录忽略，809 个文件一次性 add | 把 `fd7ea92c` 那次"已确认死码但选择不删"的私人笔记**意外升格为仓库可见禁令**（B13 / `skill_generator`）——它不是一次评审过的裁决 |

零散摘链（每次只断一边）：`f2094cfd`(09-12) 摘 plugin 注入面、`15eb32f4`(09-11) 摘 media 消费方、`7f8c7660`(06-25) 摘 evolution 门面调用块、`47660760`(08-27) 连消费者一起删 event_driven、`fa335b27`(08-31) `git rm` mcp_manager 又在 `34b0678b`(09-02) 被"未跟踪遗留补提交"**复活**。

推论：`git log` 里"某文件被骨架恢复引入"或"某 import 被改成 pass"这两类改动，是后续同类审计最该优先复算的信号；本仓若做一次系统性清退，应按上面四行分组，而不是按目录分组。

## 5. 跨模块共性（单一事实源被破）

**共性一 · try-pass 死块 38 处** ✅（主会话以 AST 式扫描独立复算，与批次自报完全吻合）：
`skills/__init__.py` 15、`llm/providers/__init__.py` 11、`memory_layer/__init__.py` 4、`admin/__init__.py` 2，`auth/__init__.py`、`channels/xiaoyi.py`、`cognitive/__init__.py`、`collaboration/__init__.py`、`recovery/__init__.py`、`tts/__init__.py` 各 1（或 2）。块体只有 pass，永不抛 ImportError，except 分支不可达，且日志文案点名的模块此处从未 import。净减约 -152，风险极低，**应作为一类清扫而非 38 个孤立 bug**。

**共性二 · 鉴权与身份口径分叉**：
- `get_current_user` 有 **7 个定义分布在 3 个文件**：`api/auth.py:415/467/490/533`、`api/deps.py:38/81`、`api/endpoints/auth.py:445`；凭证方案还不一致（auth 用裸 HTTPBearer，deps 用 BearerOrQuery 支持 query token）——同一 JWT 两套可达面。**本仓风险最高的一条**，收益却只有约 -80。
- `request_id` 取值 **31 份定义 + 84 处裸调用丢弃返回值**，兜底值分四种（uuid4 / "unknown" / 空串 / None）。
- memory 域第三套 JWT 旁路见 §6-1。

**共性三 · 同一名词多份定义**（均给落点）：
- ConfigManager **三份**：`core/config.py:60`、`core/config_manager.py:21`、`shared_config.py:39`——前两份零生产调用。
- plan_orchestrator **三套**：`shared_core/`、`core/`、`execution_engine/`，生产侧全零 import。
- 错误码 **三份**：`api/error_codes.py:6`、`interfaces/api_standard.py:30`（超集，真源）、`core/error_handler.py:26`。
- StepStatus **三份**：`skills/models.py:519`、`post_chat_pipeline.py:148`、`plan_orchestrator.py:19`——后两份才是活的且互不相干。
- `SkillGenerationResult` 两份：`skills/models.py:530` 与 `skill_generator.py:17`。
- MessageChannel / ChannelConfig 两份：`channels/base.py:44/66` vs `models.py:14/167`（前者无 WEB/VOICE/CLI 且是 str,Enum），同包内混用。
- ProviderType 两份：`interfaces/provider_interface.py`（含 LOCAL、缺 OPENROUTER/CUSTOM）vs `providers/types.py`，经 registry → `triage.py:213` 可达。
- `get_global_cache` 两份同名同签名、两个全局、注册名分列 core_global/memory_global（`core/cache.py:47` 注释自认），前者无锁违 §3。
- 情感口径四份并行：EmotionType 双份（9 值重复）、arousal 表手抄副本缺 disgust/trust/anticipation、第三份效价/唤醒表、三套互不一致的"17 种 / 6 种"体系。
- 余弦相似度 **9 份手写实现**，维度不等时三种不同行为（返 0.0 / 抛 ValueError / zip 静默截断）。
- UTC 时间戳 helper **10 份、两种精度**，落库串宽不一致。
- `normalizeLabel` 与 `cosine` 各两份（strip().lower() vs NFKC+casefold+去非词字符），两者都从各自 `__init__` 导出，而前者 `:189` 自称唯一权威源。
- usage 三兄弟 + `defaultDbPath` 同名四份，PRAGMA 基线四种写法（busy_timeout=4000 / timeout=10 / timeout=3.0 / 池 30000）。
- 睡眠实现**三套并存**：`SleepConsolidation`、`CognitiveStorageEngine`、`modules/sleep_module.py`。
- 认知编排**三套**：`neurova/cognitive/`（死）、`cognitive_layers/`（活）、`core/cognition_orchestrator.py`（半死，生产未接线）。
- CORS 三处双源（`middleware.py:148` 与 `settings.py:56` 各一份 8 项白名单 + loader 两份 + methods/headers 第三四份），守卫 `test_cors_tauri_origins.py:58/72` **双向点名两个常量名**，收口须同步改测试。
- agent limits 默认值三处硬编码复刻 `security/agent_limits_settings.py:24-57`：`openai_loop.py:190-192`、`gates.py:85`、`gate_catalog.py:36-50`。
- 两套 schema 演进机制：`usage_history.py:100` 与 `auth/user_model.py:136` 仍手写 PRAGMA+ALTER、不进 `core/db_migration.py` 的 user_version 链；同目录 `agent_run_store.py:65/94` 是正确范例，AGENTS.md §3 有明文。
- 裸 env 开关绕过已立单源 resolver：`governance.py:105`、`tool_arg_validator.py:25`、`arg_grounding.py:29` 自读裸 env 且语义互斥（等于 1 vs 不等于 0），而 `governance_settings.py:104` 的 `resolve_flag` 被自身 docstring 定为唯一事实源。

**共性四 · `skill_system` 四体并存**（本仓最病态的一处，须按收口而非删重处理）：
顶层 `skill_system.py`（879 行）是唯一规范实现载体，被同名包**遮蔽**，只能靠 `spec_from_file_location` 反射加载；包 `__init__.py` 是活的代理层（生产 18 处 import），内含 **8 段逐字相同的 standalone 加载样板**（`:92/111/133/151/172/191/209/230` 共用一个 cache key）；`:283` 顶层 import 幽灵名，只因 `:279` 先触发 `__getattr__` 注 sys.modules 才不炸（`docs/architecture-model/neurova-risks.dot:24` 已登记为加载顺序耦合）；`skills/builtin/github_push/skill.py:26-39` 用**另一个** cache key 自行加载同一文件，导致同名 Skill/SkillResult 是两份不同对象；SkillResult 字段还分叉（包顶层导出 `skills/executor.py:20` 的 output，注册表返回 `skill_system.py:32` 的 data）；`SkillStatus` **三份**且包内那份每次 `__getattr__` 都新建 class 对象；`tests/unit/core/test_chain_integrity_observability.py:68` 直接伸手进 `sys.modules` 取带 `_standalone` 后缀的幽灵名，该名字已泄进 `agent_public_contract_snapshot.json:80`。

**共性五 · 巨型文件与无谓间接层**：
`tool_executor.py`(6008) 内聚族可外迁（canvas `:2423-2704`、computer/SOM/SSH `:4348-5057`、browser `:5058-5315`；canvas 十法全是 `canvas_ops.get_canvas_op_service()` 薄包装）；`agent_core.py` 的 class Agent 起于 `:987`，此前 AgentLLMClient `:122`、AgentConfig `:209`、`_NullSystem`+`wire_memory_guards`、SubSystemContainer `:442` 均非类体成员（基线 2103 对 goal 900）；`post_chat_pipeline.py:2742-3147` 的 `_step_rsi_iteration` 406 行域属 `evolution/rsi/`；`session_manager.py:1528-1961` sidecar 块 + 本文件两份原子写（`core/atomic_io.py:16` 是第三份）。
**注意守卫**：`test_builtin_tools_expansion.py:113` 要求 `_builtin_dispatch` 的值是 ToolExecutor 真实方法名 → 必须走 mixin（经 MRO），拆独立函数即红。
样板类：provider 六件套逐字节复制 base 连接层（覆盖版丢掉 `base.py:86` 的 error_category/error_hint 归一）、`_estimate_context_window` 四份同构、`probe_model_multimodal` 四份只差一个字面量；`endpoints/provider.py`+`model.py` 里 provider_manager 取器 + 503 判断复制 16 次（但注意 `deps.py:199` 那份依赖自身也零消费者，见 A2）；响应信封 321 处手写字面量 vs 已存在的 `api_standard.py:157 success_response()`；`cognitive_layers/manager.py` 17 个形状相同的 `_ensure_*` 且都不在 `self._lock`（`:194` 是 RLock）内做 DCL；裸判 None 无锁单例 15+ 处（对照正例 `canvas_ops.py:568`、`seen_cursor.py:437`）；auth 侧 4 份 DCL 同构且用 Lock 非 RLock，还在已 import threading 的文件里用 `__import__('threading')`；4 个 `*_settings` 读写骨架逐字重复；8 份同形 workflow 模板构造块；external_clients 的 `__module__` 回写样板 85 行（11 个文件逐方法手写）。

## 6. 审计中发现的缺陷（不属简化，按教义第 1/2 条不得顺手改掉）

1. **memory 域身份旁路（已修 `63e8ae8e`）** ✅ —— `endpoints/memory/base.py:38-61` 手工剥 Bearer 头 + 直调 `verify_access_token`，except Exception: pass。**调用点 29 处**、横跨 5 个文件（crud 1 / metacognition 12 / profile 4 / tkg 4 / working_memory 8），初报"35 处"是原文出现数（29 调用 + 5 导入 + 1 定义），此处更正。回落面也比初报窄：带无效/过期 token 的请求早在 S-10 就被 `get_current_user_or_default` 挡成 401（`auth.py:541-556`），真问题是**与 `_user_identity()` 口径分叉**（存量 token 第二层键被写成 default）。无鉴权依赖的路由按结构扫描实测为 **16 条**（初报"14"来自一条不严谨的正则草稿）：其中 13 条同时走旁路（本批已补依赖并单源化），另 3 条（`/emotion/types`、`/{agent_id}/metacognition`、`/{agent_id}/metacognition/stats`）不取租户数据，判据外留档。**三条更硬的现行越权面（PUT 无归属校验、DELETE 传 `agent_wide=True` 关掉两层、GET 读零写入的存储且无依赖）已同批根修，图证、A/B 与一处守卫改判说明见 [`memory-isolation-2026-10-05.md`](memory-isolation-2026-10-05.md) §六。**
2. **`self._logger` 幻影引用破坏回滚** ✅ —— `evolution/rsi/integration_manager.py:383/449` 用类内不存在的 `self._logger`（只有模块级 `logger:13`）。`:383` 位于 `:386` 回滚 setattr **之前**，抛出的 AttributeError 被 `:394` 吞掉 → "优化回执落盘失败时不回滚"，与注释承诺的安全语义正好相反。
3. **匿名可达的空转上报端点** ✅ —— `api/app.py:614 POST /api/v1/frontend/errors` 在 `global_auth.py:48` 白名单内，收 JSON 后只 `logger.warning` 便返回 `{"status": "logged"}`，**从不调 error_logger**；客户端被告知"已记录"而实际未存，体未见长度上限。
4. **现役链读内存假存根** ✅ —— `notifications.py:83/117` 读 `enhanced_users_api.py:73` 的 `_users_store = {}`。
5. **让位规则整条支路从未执行** ✅ —— `coordination_decorators.py:99` 调 `get_glance_yield_checker()` 漏 await，而工厂在 `glance_yield_rules.py:444` 确为 async def → 拿到协程对象，"操作碰撞即拒"实际空转。
6. **假委托 + API 签名断裂** ✅ —— `memory_layer/manager.py:2882/2889/2999/3005/3040/3045`（部分恒 return True）；`memory/profile.py:130/169` 传 user_id 位置参、`metacognition.py:329/412` 传 category=/top_k=，manager 形参不接受 → 必抛 TypeError，被 except Exception 折成 500；`models.py:133 UserProfile` 生产零引用。
7. **LM Studio 卡片恒灰** ✅ —— 见 B13：豁免分支不可达，无 key 时落到 `provider_manager.py:1326 return False`。
8. **依赖缺失仍返回成功** ◑ —— `channels/discord.py:255`、`qclaw.py:316`、`qclaw_service.py:77`；同形态在 `websocket.py:421` 已根修，按第 5 条应同批扫荡。
9. **崩溃后无人接管** ✅ —— `recovery/` 的 sentinel 异常关机标记与按 agent_id 恢复记忆今日零承载；正常关停有人、崩掉没人管（`self.shutdown_guard` 全仓唯一出现处即 `app.py:62` 赋 None）。
10. **睡眠周期绕过装配点改私有字段且竞态未消** ◑ —— `manager.py:3908-3969` 靠"存旧值→改 `module._consolidation_threshold`→finally 还原"实现；`sleep_module.py:264/267` 读该字段时并不持锁（锁在 `:253-255` 已释放）。
11. **只写不读的配置面** ◑ —— `cognitive_layers/settings_config.py` 有 16 个 ParamSchema 自标"【预留】…修改暂不生效"，`activation.*`(7)、`auto_context.*`(2)、`graph.time_decay`、`vector_search.*`(3) 全域零读取方；同类还有 `AdaptiveToolWeights.lifecycle_state`（写盘但 load 从不回填）与 `total_latency`（只随 JSON 往返）。删须同步 i18n 11 语言 desc_key。
12. **EventBus 只 emit 不订阅** ✅ —— `cognitive_layers` 全域零 `_bus.on(` / `.subscribe(`，`manager.py` 5 处 emit，`get_stats()` 的 bus_handlers 恒为 0；`bus_event.MemoryModule` 从未被继承且其 init(bus, config) 签名与各模块实际 init() 不符。
13. **教义第 5 条"扫荡记账未落实"** ✅ —— `b84434cf` 提交说明自称扫荡了 `injector._truncate_text` 的 char/token 常数，但该 commit 对 `injector.py` 的 hunk 里没有 chinese_ratio / `_truncate_text` 任一行；实况 `injector.py:634` 仍按 `models.py:60 chinese_ratio` 就地折算。
14. **文档虚报集成完成** ◑ —— `docs/01-architecture/RSI_INTEGRATION_COMPLETE.md:24` 把从未接线的 EnhancedRatchetPruner 列为"集成完成"。同类：`skill_system_2.0.md:332` 承诺的 package 端点从未存在；`plugin-architecture-design.md:707` 按不存在的 `get_config_manager()` 写 import；`neurflow-dev-spec.md:68` 指定的 SkillChainExecutor 从未落地。
15. **守卫自身前提为假** ◑ —— `test_t09_selfloop_face_ruling.py:138/217` 断言的"MCPConnection 同名同源"不成立（详见 A7）；此类守卫必须先红灯修正，否则它会把错误前提固化成删除阻断。
16. **幽灵测试与空测试文件** ✅ —— `tests/unit/skills/test_skills_evolution_engine.py:10-17` 导入不存在的类名致整文件恒跳过；`test_skill_security.py` 共 17 行、def test 计数 0；`test_skill.py` 15 行、0 用例；`tests/execution_engine/test_tool_engine_v2.py:86` Mock 生产侧已不存在的 `engine._cognitive_security`。**"某模块有 N 个测试通过"在本仓不构成活证据，须先复算该测试是否真跑。**
17. **回退分支注册假实现** ✅ —— `skill_system.py:844-848` executor 注册失败即回退 MemorySkill/FileOperationSkill，而 `:279-287` 的 `_search_memory` 恒返空列表、`_store_memory` 什么都没存却返回 stored=True。
18. **安全实现里的假成功与弱加密** ✅ —— `emotion_adapter.py:46-82` ImportError 兜底成恒返 neutral/0.0 的 SimpleAnalyzer；`mcp_manager.py:248/259` 的 sse/http"连接"是自陈简化、`:213` Popen 绕开 shell 拒绝门；`secret_store_clean.py:79-103` 重复密钥流 XOR 且无 MAC。
19. **懒建单例缺 DCL+RLock（§3 违规面）** ✅ —— `collaboration` 侧 15+ 处裸判 None 无锁；auth 侧 4 份用 Lock 非 RLock；`get_flow_orchestrator:846` 无锁；`manager.py` 17 个 `_ensure_*` 不在锁内；`channels/manager.py:81` 懒建单例同样缺 DCL。
20. **`neurova/expected` 与同批的 `missing`** ✅ —— 均为 0 字节重定向残留，由 `98b5422a`「清理临时文件」引入（该提交还删了 471 行的 `missing_files.txt`）。
21. **后台任务句柄丢弃 → 关停无法收敛（已修 `b5f80e9c`）** ✅ —— `_schedule_mcp_bootstrap`(`api/app.py:765`) 起的 stdio 会话，`MCPToolClient.disconnect_all`(`tool_layers/mcp_client.py:240`) **生产侧零调用方**（同批还发现 `execution_engine/mcp_manager.py:395` 的第二份 `disconnect_all` 同样零调用方，属 §3-A7 面）；portal 只能取消，而 stdio reader 取消不收敛 → `thread.join()` 永久阻塞，真进程侧是 npx 子进程泄漏。同根因第二命中点：`bootstrap_mcp` 的 `_bootstrapped` 只写不读，重复 startup 顶掉活会话。**修法**：关停先收敛任务再关会话（注册表 + 进程单例两个发现口），`_bootstrapped` 转为被读。
22. **`POST /api/v1/health/recover` 假成功（已修 `212d855c`）** ✅ —— `endpoints/health.py:179-187` 写 `# TODO: 实现恢复逻辑` 却回 `success: true` + `"Recovery triggered"`；全仓除该测试文件外零消费者（NeurUI/NeurovaHarmony 零命中）。已收成显式 501 + 点名原因（路由保留），并同批删掉失去消费者的 `RecoveryResponse` 与本就零引用的 `RegisterCheckRequest`。
23. **响应模型不接受的字段被静默丢弃（已修 `d8f86dcd`）** ✅ —— `endpoints/health.py:88-92` 给无 `message` 字段的 `HealthStatusResponse` 传 `message="Health checker not available"`，pydantic v2 默认 `extra='ignore'` → 降级原因不可观测，调用方只见 `status:"unknown"`。字段已补进模型（与同文件 `CheckResultResponse.message` 同名同默认值，不另造口径）。
24. **进程级 agents 表是跨用例耦合面** ◑ —— `enhanced_memory_search_api.py:24` 自陈"唯一事实源是 `get_app_state()['agents']`"（`request.app.state.agents` 生产恒空），于是任何跑真实 startup 的用例都会把一个真 agent 写进该表，把同进程后续 18 条（nerf 11 + semantic-search 7）带倒。本轮在新用例内按原样回填所动全局以自证隔离；**表本身的单源化/用例隔离属预存脆弱面，未放宽**。
25. **时间边界抖动** ◑ —— `tests/integration/collaboration/test_phase3_intelligence.py::TestEdgeCases::test_outbox_expired_event` 以 `expiration_ttl=0` 撞墙钟，连跑 5 次 2 负，与本轮改动无关（A/B 逐行核过），登记备查。后续单跑三次全绿，目录跑时仍偶发翻转。
26. **落盘锚点接受非路径对象并在进程 CWD 静默建塔（已修 `a9170fa9`）** ✅ —— `MagicMock` 实现了 `__fspath__`，故 `Path(mock)` 能过类型检查、其 repr 被 Windows 拆成相对目录，随后 `mkdir(parents=True)` + 写盘**全部成功**，只在 `except OSError` 留一行 debug；仓库根实际长出过 `MagicMock/SkillService().skills_dir/<id>/.lifecycle_state.json`。同契约三命中点（`skill_lifecycle.run_sweep_if_due`、`ConsolidationPlanStore.__init__`、`SkillService.__init__`）现统一收到 `data_root.require_data_path`。**读码新发现**：判据必须落在**公开入口**——放在 `_state_file()` 那层会被 `_load_last_run` 的 `except ValueError` 吞成 "last=0"，非法路径照样落盘。**另记一条治理教训**：`.gitignore:380` 的 `/MagicMock/` 与 `git log` 表明该症状至少复发三次（`84260bb4` 2026-06-08 排除、`dd03d67c` 2026-09-02「根目录二次清理 — git rm … 垃圾 + gitignore 防再生」、2026-10-04 再现），三次都停在"清理 + 忽略"，从未查落点为何漂到 CWD——按教义第 2 条，"防再生"的 ignore 是把失败改写成静默，本条是首次根修；规则保留只为防误提交，不再充当止痛。
27. **跑测卫生三件（本批取证时发现，均预存）—— 三件已全部根修** ✅ ——
28. **会话与记忆按 user_id 隔离（政策拍板后的一轮，A/C/D 已修，B 判为产品口径）** —— 政策：匿名共享 default 桶可接受，但租户键必须是 user_id。
    **A 已修 `ed015dcb`**：`home.py` 的 `_real_conversation_count()` / `_aggregate_daily()` 不带 `user_id`，而 `/home/*` 是严格门 → 已登录用户在首页看到**全体用户**的会话数与按天趋势（核过不返回标题/正文，泄露面是跨租户聚合计数）；`GET /api/v1/stats/agents` 连门都没有，补的是 `get_current_user_or_default`（此前匿名可达，加硬门会打断既有调用方）。顺带挖出 `export_stats` 用 `await get_agents_stats(request)` **把端点当普通函数复用**——依赖不会被解析，一加身份参数就抛 AttributeError 并被自己的 `except` 吞成"agents 段空"，已抽 `_agentStatsRows(callerId)` 让两侧共用。
    **C 已修 `bcbb5f69`**：会话归属判据在 `console.py` 写了 5 份（helper 本体 + `_find_session_target` + delete/rename/auto-title 各一份），收口为一处。
    **B 更正我自己的判断**：我先前把"console 面校验会话属主、chat.py `/history` 只校验 agent 归属"记成现行越权面。新加的矩阵守卫实测**推翻**了它——bob 用真身份从 6 条会话端点碰 alice 的会话，修复前就已经全部 403；而 `chat.py` 那条要成立需要"同一 agent 的两个不同用户都能过 `can_access_agent`"，该判据是 admin 全量 / owner 匹配 / 无主仅 admin，普通用户不可达。所以它只是**口径不一致 + 纵深不足**，不是漏洞；是否让 agent 属主读到他人会话属产品语义，未擅动。（同 §七 教训：代码里有分叉 ≠ 请求能走到它。）
    **D 已修 `e040304d`**：`save_message()` 建新记录写死 `user_id=""` 且无入参，两个生产写方都无法声明归属——console 的 fork 只靠"先 create 再 save"的顺序侥幸，`room_store` 则恒产出共享会话。修法：加 `user_id` 关键字参数、既有属主只回填不覆盖、**生产调用点必须显式声明**由源码守卫钉。判据形态换过一次：先做"必填无默认"，实测要拉 24 个不建模归属的测试调用点填噪声，遂改为"带缺省 + 生产侧显式（源码守卫）"。
    **本轮新登记的债**：`auth.py:415` 与 `deps.py:38` 是**两份同名不同体的 `get_current_user`**（后者额外接受 `?access_token=` 查询参数），console 用 deps 那份——它让 `dependency_overrides` 打错对象时静默失效（本轮就这么红过一次），合并属全仓鉴权口径，需单开一批。`tests/unit/test_session_round_ops.py` 单跑 7 failed（history 混入 98 条额外消息，疑跨用例共享会话目录），预存、与本批无关。
    ① `tests/unit/evolution/eval/` 挂死（`ea1da5ae`）：真因不在 runner 也不是死循环，而是三个文件传 `agent=None`，`service.py:209/327` 的 `agent or SimulatedAgent(...)` 回落成**真** LLM 客户端——**用例在发真实请求、花真实配额**，被判 `rate_limited` 后进入"≤10 次 × 间隔 10s"等待，远超 30s 用例预算被 thread 方法击杀，连累整目录。修法：目录级出站闸 + `offlineAgent`（8 处 `agent=None` 逐方法替换）。闸必须抛 **BaseException 子类**——`SimulatedAgent.run` 外层 `except Exception` 会把 AssertionError 吞成空回复，普通断言等于哑闸。
    ①附：同根因第四处 `tests/llm/test_instream_error_encoding.py`（故意喂 429 却没免等待）按 `_sleep_for_retry` docstring 预留的桩注入点收口；揭盖后 6 条全绿，说明挂死背后没藏别的缺陷。
    ② `tests/benchmarks/test_multi_agent_coordination.py` 收集期 ERROR（`ce74616b`）：模块顶层 `from neurova.agents.seen_boundary import ...`，该包本仓不存在 → `Interrupted: 1 error during collection` 使 `pytest tests/` **一条都不跑**。第 7 条比后判退役：全文 0 个 `def test`、三个基准方法**全都**依赖两个已退役模块、全仓零消费者、现役能力另有真用例在跑。修后全仓收集 `21292 tests collected` 零错误。
    ③ `tests/unit/planning/__pycache__/*.pyc` 被跟踪（首次尝试 `5193a885` **未真正交付**，`2c681e17` 才收口）：**gitignore 规则对已跟踪文件不生效**——`dd5b00be`(08-30) 批量提交带入，`472a0180`(09-22) 才补 `tests/**/__pycache__/`，规则本身没错，这两个是规则之前的既成事实，于是每次跑测稳定产生一条无关 diff，污染 `git status` 与 A/B 判据。`git rm --cached` + 新增 `test_no_run_product_is_tracked`（取 `git ls-files` 而非磁盘形态：磁盘上的 pyc 是正常产物，仓库里的才是债）。**这一条我自己踩了命令坑**：`git commit --only -- <path>` 按**工作树内容**提交该路径，与 `--cached`（磁盘保留）叠加后，删除被在盘同名文件覆盖回去，那次 commit 实际是一次 `Bin 149 -> 149` 的内容更新；提交后复跑守卫转红才暴露——删除类改动的正确形态是"状态进索引 + 不带路径的 `git commit`（只提交索引）"，且绿灯必须在落库之后复取（教义第 4 条）。
    ④ 同批新增的全局收口（`9df526b9`）：`tests/conftest.py` 里 autouse 逐用例快照仓库根顶层条目，新增即红并点名肇事用例，与 §6-26 的具体根修互补。
    **仍存疑、未处理**：429 等待重试的最坏叠加时长（10 次 × 封顶 120s）在生产里没有全局 deadline，只有"重试次数"上界——是否要给整条请求加墙钟预算属产品口径，未擅动。

## 7. 未覆盖与存疑（请勿当结论使用）

**主会话未复算**：标 ◑ 的条目全部；各类候选行数估计（依赖子代理的相似度采样与手工加总，误差可达 ±20%）。

**子代理自认未深扫**（仅结构或引用面采样）：`api/neurflow_api.py`(1781)、`marketplace.py`(1194)、`skill_pool_api.py`(1079)、`channel_config.py`(1007)、`computer.py`(948)、`governance.py`(841)、`console.py` 大部分；`knowledge/repository.py`(1394)、`security/audit_logger.py`(753)、`skill_scanner.py`(689)；`cognitive_layers/attachment_manager.py`(978)、`unified_vector_store.py`(961)、`neurova_recall.py` 大部分、`knowledge_graph/manager.py`(1218)；`llm/multi_model_client.py`(1500+)、`llm/generators/*`、`agent/{scheduler,swarm,subagent,team}`；`skills/skill_service.py`(1701)、`hub_client.py`(937)、`experience_knowledge_base.py`(849)；`core/intrinsic_motivation.py`(1044)、`cognition_orchestrator.py`(954)、`flow_orchestrator.py` 主体；尾部 15 个包（models、sync、notifications、backup、checkpoints、interfaces、tts、asr、aigc_studio、web_reach、plan_mode、benchmark、admin、guest_agent、embedding）。

**存疑判定点**：
- 全部"零消费者"判断的取证**只覆盖 py 文件**。未覆盖：NeurUI 前端按名调用、运行时字符串路由、`agent_workspaces/` 落盘脚本、`.cnb.yml` 流水线内联命令。子代理亦自陈此限。
- `providers/{capability_detector,capability_cache}.py`(845) 被 `test_capability_cache_single_source.py` 显式豁免，**不建议删**。
- `ToolExecutionManager._execute_elastic/_execute_infinite`(`:490-577`) 生产唯一入口恒传 STRICT，判为不可达但可能是预留扩展口。
- `knowledge/ingest_queue.py` 与 `channels/channel_ingress_queue.py` 的 claim/ack/nack 同构，但前者裸建表、后者走 register_migration（违 §3）；合并风险大于收益，附议不动。
- `conflict_detector_v2`、`temporal_reasoner`、`vector_index_manager`、`memory_record_store` 等"只被测试或 demo 脚本引用"者，属"待接线"还是"应删"需人裁。
- `_pydantic_compat` v1 分支、provider hasattr 门、evolution 第 6 条 state=None 可达性——均基于锁文件与类定义的**静态推断**，未实跑。
- 桌面部署侧用户库未复测（A5 的 NEUROVA_DATA_DIR 注入口）。

## 8. 复算方法与七类伪命中

对每条"零消费者 / 可删 N 行"结论，独立复算时须排除以下形态（本次全部现场遇到）：

1. **同名词不同物** —— `constitution` 的 11 处生产命中全是 `agent/builder.py` 的配置字段与 `endpoints/constitution_*`；`voice_adapter` 的 `app.py:909` 是 `channels.voice.create_voice_adapter`。
2. **相对导入指向同名他文件** —— `neurflow/templates/__init__.py:34` 的 `from .media`、`context/orchestrator.py:24` 的 `from .recovery`（指 `context/recovery.py`，11783 字节，已核实）。
3. **注释/文档字符串里的提及** —— `create_database_check` 唯一"定义外命中"是 `test_metrics_pool_observability_p0.py:135` 的说明文字。
4. **包门面再导出 ≠ 消费者** —— `shared_core/__init__.py` 只有 docstring、`auth/__init__.py:12` 的 try/except→None 只是导出面。
5. **动态装载** —— `perf_gate.py:393` 用 importlib 装载 collector，纯 import grep 会误判可删。
6. **文件级判死误杀在役符号** —— `execution_layers/__init__.py` 传输半区死、运行时半区活；`collaborate/workflow/models.py` 的 FlowPhase 死但 `:198 compute_next_run`/`:240 ScheduledTask` 被 `scheduler.py:30/304` 在役使用。**判退役必须以符号为单位，不以文件为单位。**
7. **"有测试"不等于"是活证据"** —— 幽灵 Mock、恒跳过的测试文件、断言形状而非装配的守卫（A16 / B13 / A7）。**这类是本轮改判的主要来源。**

LOC 口径统一为 py 文本行（`git ls-files | grep '\.py$' | xargs wc -l`）；对全清单 cat 会把封面图等二进制按字节算进 LOC（实测 359712 → 真值 352712；`neurova/storage/` 看似 5282 行实为 5 行代码）。子代理自报的行数与覆盖率同样要问"分母怎么来的"。

## 9. 落地路线建议（本轮不改码；若点单，按此序，每批一个 commit）

| 序 | 动作 | 候选净减 | 前置红灯 / 注意 |
|---|---|---|---|
| 1 | 全仓 38 处 try-pass 死块一类清扫；`git rm neurova/expected` | -152 | 各包 import 冒烟 + `tests/unit/core` |
| 2 | 空壳退役：`utils`/`capabilities`/`builder`/`storage/covers`（20 图零写零读） | -8 + 1.3M 资源 | 目录存在性守卫 |
| 3 | **缺陷批**：§6-1 memory 越权面、§6-2 回滚幻影、§6-5 缺 await、§6-4 存根断链 | ≈0 | **优先级高于一切简化**；每条先立红灯（跨用户隔离、落盘失败须回滚、碰撞须拒）。§6-1 已拆出图证与五条红灯，见 [`memory-isolation-2026-10-05.md`](memory-isolation-2026-10-05.md) |
| 4 | A 档"骨架恢复引入且从未接线"批：`llm/client.py`、`config_resolver`、`config_console`、`context_cache`、`context_persistence`、`voice_adapter`、顶层 `context.py`、`collaborate/{models,template}` | ≈2400 | 同批改 `test_refactor_imports.py` 兼容钉与两处 docs 悬空指向 |
| 5 | A 档"换代残留"批（cognitive_layers 八件 + 三套 plan_orchestrator + 三套 ConfigManager） | ≈4200 | 逐条核 `protected_tests.txt`；**先裁睡眠三套归属**（A9 与 B5 有耦合） |
| 6 | A 档"消费方被摘后残留"批：`plugins`、`media`、`language`、`cognitive` | ≈2700 | pyyaml 守卫须**改指**而非删 |
| 7 | 安全实现批：`mcp_manager`+`schemas`（含 shell 门闭环）、`emotion_adapter` 假成功、`secret_store_clean` 迁 AES-GCM | ≈1100 | **先修守卫假前提**；只收判据不放宽校验 |
| 8 | `skill_system` 四体收口（§5 共性四） | -230 | 契约快照 + 4 处测试改引用；须跑技能执行链活体 |
| 9 | 双源口径批：情感枚举、余弦 9 份、UTC 10 份、limits 硬编码、CORS、信封 321 处、request_id 31 份 | ≈400 | 逐条比对收口前后命中集等值；改精度会动已入库时间串 |
| 10 | 巨型文件外迁批（tool_executor mixin / agent_core 棘轮 / post_chat_pipeline / session_manager） | 总量不减，棘轮面 -2400 | **必须走 mixin**（`test_builtin_tools_expansion.py:113`）；勿经 `neurova.agent` 包门面引 |
| 11 | 鉴权 7 定义单源化（§5 共性二） | -80 | 最高风险：双跑 integration+e2e，带头/带 query 两种凭证活体 |
| — | **B 档 14 组需人裁** | ≈13,000 | **不列入任何删除批次**。需产品逐项裁"要不要这个能力"：要则接线，不要则连同文档与测试显式退役并改规则 |

净 LOC 纪律：任一批次使总 LOC 为正（如 §10 外迁、C2 接线），须在提交说明逐条列明去向；测试代码不计入。

### 9.1 已落地（审计之后的批次，按 commit 追）

| commit | 内容 | 与本报告的关系 |
|---|---|---|
| `c34db0b4` | 外部 Agent 协议判据层落地并退役 `communication_protocol.py`（生产净 -466） | §3-A 档一条 + §5 平行判据收口 |
| `dd97134c` | 审批账本与"每分钟额度"各收成一份（生产净 +132，去向逐条列明） | §5 共性三/四（并行额度源、双账本路径） |
| `f4776229` | 协调层集成测试按现状重塑（两条死导入使整目录无法收集） | §6-16 幽灵测试一类的补面 |
| `b5f80e9c` | MCP 会话关停根修（§6-21），integration 由 162s/含击杀 → 66s/零击杀 | §6-21 新增并已闭环 |
| `587c57f6` | `/health` 集成用例改打真实挂载路径、四值放宽断言收成单一状态码 | §6-22 留档未处理 |
| `212d855c` | `/v1/health/recover` 假成功收成显式 501，删 `RecoveryResponse` + 零引用的 `RegisterCheckRequest`（生产净 -15） | §6-22 闭环 |
| `d8f86dcd` | `/v1/health` 降级原因补进响应模型（原被 pydantic `extra ignore` 丢弃，生产净 +4） | §6-23 闭环 |
| `63e8ae8e` | memory 域身份单源化 + 三条 by-id 路由回到归属校验（生产净 **-64**；§9 序 3 缺陷批的 memory 条） | §6-1 闭环，含一处守卫改判 |
| `806c6f38` | agent_communication 第二份身份解析退役（`bearer` 大小写把同一枚凭证分进两个租户） | §6-1 第二命中点 |
| `c1c6c221` | 路由级门改为 JWT 与密钥合一，agent 域密钥并入 `APIKeyManager`（净 +34） | §6-1 能力缺口按拍板闭合 |
| `cf684596` | firewall 未知规则键先验后写、点名拒绝；合法键名单源取 dataclass 字段（净 +22） | 假成功族：静默 no-op 却报成功 |
| `7842ecb9` | 开放平台密钥归属改取那道门（`request.state.user_id` 全仓无人写入 → 全员同落 anonymous 桶，互相可撤） | 与 §6-1 同根因第三命中点 |
| `94af885f` | 开放平台私有密钥存储并入 `APIKeyManager`，三项机制（原子写/创建幂等/tombstone）先补短再合并后退役（净 +83） | 教义第 7 条：密钥实现三合一 |
| `04c4a42e` | 记忆增强端点身份回到那道门、7 处变更收回归属校验，并去除既有测试伪造 `request.state.user` 的中间件（净 +10） | §6-1 同根因第三命中点，详见 memory-isolation §十 |
| `a9170fa9` | 落盘锚点收成绝对路径单源（`data_root.require_data_path` 接三处：sweep 入口 / 计划仓 / 服务构造），mock 与相对串不再于进程 CWD 静默建塔（净 +32） | §6-26 新增并根修 |
| `9df526b9` | 仓库根污染守卫接线：autouse 逐用例快照顶层条目、新增即红并点名肇事用例（生产净 0，测试基建 +153） | §6-27 的 ④ 收口，与 §6-26 根修互补 |
| `ce74616b` | 退役不可加载的多智能体基准台架（0 用例 / 三方法全依赖已退役模块 / 零消费者），解开的却是 `pytest tests/` 整仓的锁；另加全仓收集零错误守卫（不进 CI 子集，避免 +60s） | §6-27 的 ② |
| `5193a885` | 新增「被跟踪产物」清点判据（取 git ls-files 而非磁盘形态）；同批想取消跟踪两个 .pyc，但被 `git commit --only` 的工作树语义抵消，**未真正交付** | §6-27 的 ③ 未闭合的一面 |
| `ea1da5ae` | 根修 eval 目录挂死：`agent=None` 回落真 LLM 客户端（用例在发真请求、花配额）；目录级出站闸（须抛 BaseException 才不被 except Exception 吞）+ 8 处注入离线 agent，另收同类第四处 429 真等待 | §6-27 的 ① 与附项 |
| `2c681e17` | 真正取消跟踪那两个 .pyc（状态进索引 + 不带路径的 commit 只提交索引）；由守卫在提交后复跑时抓出上一次交付是假的 | §6-27 的 ③ 闭合 |
| `2c1008e6` | §6-27 三件收口登记 + 记一条「单元测试一直在花真实 API 配额」 | §6-27 |

上表未覆盖的序 1—11 仍按原序待点单。

## 10. 工作树状态

两轮审计全程只读。`git status` 复核：本轮未新增/未修改任何生产代码或测试，本文件为唯一新增产物（`git check-ignore` 确认未被忽略，可正常纳管）。

工作树另有三项**非本轮产生**的在途改动，属其他会话遗留，未作处置：
`models/tts/moss-nano/.gitattributes`（M）、`models/tts/moss-nano/configuration.json`（??）、`.zcodeignore`（??）。
提交本文件时须按 AGENTS.md §5 用 `git commit --only -- <paths>`，**严禁 `git add -A`** 把它们卷入。

执行事故与两次子代理失稳（返回无关内容 / 撞 maxTurns）已记于 §1；安全能力矩阵改由主会话自算，见 §3-B1。

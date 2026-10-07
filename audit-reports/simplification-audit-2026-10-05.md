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
- **闭环时的改判（`610b8a03`，实测与本条不同）**：按 §7"同一功能才合并"分两层比过——**密码学**这层选定 `providers/secret_store.py` 的 `enc:v2:` AES-256-GCM 并已接过去用（SimpleCipher 退役、`test_singleton_convergence.py` 清单一并摘掉）；**持久层**这层两份不是同一功能：`providers/secret_store.py` 是单文件全局表，本模块是**每用户一桶 + metadata + access_log**（三层隔离的凭据归属就靠这个分桶），删它等于把凭据归属压回 default 桶。故本文件保留为持久层、603→550 行，净 -52；`credentials.py` 不必迁走（它要的正是分桶）。三条附带产物：① 存量 XOR 只读解码 + **读到即升级**（活体用手工预置的历史桶证了读回与升级）；② "解不开→静默丢"这条更硬的根因一并堵（原文留档、失败不动盘、store 诚实回 False）；③ 零消费者且用随机临时密钥的 `get_secret_store()` 按断点退役。

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

**共性四判定：已收口（`14f0f164`，§9 序 8 同批）** ✅ —— 裁定与实测：影子文件搬进包内 `neurova/skill_system/core.py`（遮蔽这一根病灶随同名并存消失），门面转**纯静态 re-export**（`__getattr__` 8 段样板、幽灵名顶层 import、占位 `Skill`/`SkillResult`、重复 `SkillInfo`、零消费者的 `_get_skill_module` 全删；门面 304→26 行）。一进程内三份 `Skill` 收回一份，实测同一性判据常驻三个新守卫文件；`SkillStatus` 三份归一为 `str, Enum`（取长：保留 `status == "active"` 的裸串读法），成员只留被消费的 ACTIVE/INACTIVE。`SkillResult` 名实归一后带出两条下游事实：① `api/endpoints/skill.py:439` 降级分支读的 `output` 字段在真实对象上从不存在 → 恒 `{"status":"ok"}` 编造空载荷（已改读 `data`，活体对照见 §9.1）；② `skills/executor.py` 的 output 形状与运行层 data 形状是**两层职责**（桥接处显式转换），不是同一功能的二实现——故只收门面名，**不强改名 executor 层那份**（16 文件改名为后续项，理由见下）。生产净 **-306**（+51/-357），预估 -230 偏保守。
三条同族残留**登记不顺手改**（都不属"多条取用路径"本体）：① `skills/market_registry.py:108-109` `SkillDocSkill.add_event_handler` 转发给 `ExecutorBackedSkill`，而该方法在 `Skill` 基类与桥接类上都不存在（工单 017 退役事件桥后留下的一根空 shim，一旦被调即 AttributeError；本批前后同样红，属预存）；② `neurova/skills/executor.py:20 SkillResult`（output/metadata）与运行层同名类仍是两个名字一份含义，逐文件改名需先证"无第三方技能脚本按 `from neurova.skills.executor import SkillResult` 拿旧形状当注册表返回值"；③ `tests/unit/skills/test_skill.py:15` 整文件被 `pytestmark = skipif(...API changed...)` 永久挂起，理由串点名六个"已移除"符号——这是把红改写为跳的形态（AGENTS.md §2），处置应是按现行契约重写或删除，不是留着当覆盖。
另记一处**判据外**的落点旁路（活体取证时踩到）：见 §6-33。

**共性五 · 巨型文件与无谓间接层**：
`tool_executor.py`(6008) 内聚族可外迁（canvas `:2423-2704`、computer/SOM/SSH `:4348-5057`、browser `:5058-5315`；canvas 十法全是 `canvas_ops.get_canvas_op_service()` 薄包装）；`agent_core.py` 的 class Agent 起于 `:987`，此前 AgentLLMClient `:122`、AgentConfig `:209`、`_NullSystem`+`wire_memory_guards`、SubSystemContainer `:442` 均非类体成员（基线 2103 对 goal 900）；`post_chat_pipeline.py:2742-3147` 的 `_step_rsi_iteration` 406 行域属 `evolution/rsi/`；`session_manager.py:1528-1961` sidecar 块 + 本文件两份原子写（`core/atomic_io.py:16` 是第三份）。
**注意守卫**：`test_builtin_tools_expansion.py:113` 要求 `_builtin_dispatch` 的值是 ToolExecutor 真实方法名 → 必须走 mixin（经 MRO），拆独立函数即红。
样板类：provider 六件套逐字节复制 base 连接层（覆盖版丢掉 `base.py:86` 的 error_category/error_hint 归一）、`_estimate_context_window` 四份同构、`probe_model_multimodal` 四份只差一个字面量；`endpoints/provider.py`+`model.py` 里 provider_manager 取器 + 503 判断复制 16 次（但注意 `deps.py:199` 那份依赖自身也零消费者，见 A2）；响应信封 321 处手写字面量 vs 已存在的 `api_standard.py:157 success_response()`；`cognitive_layers/manager.py` 17 个形状相同的 `_ensure_*` 且都不在 `self._lock`（`:194` 是 RLock）内做 DCL；裸判 None 无锁单例 15+ 处（对照正例 `canvas_ops.py:568`、`seen_cursor.py:437`）；auth 侧 4 份 DCL 同构且用 Lock 非 RLock，还在已 import threading 的文件里用 `__import__('threading')`；4 个 `*_settings` 读写骨架逐字重复；8 份同形 workflow 模板构造块；external_clients 的 `__module__` 回写样板 85 行（11 个文件逐方法手写）。

## 6. 审计中发现的缺陷（不属简化，按教义第 1/2 条不得顺手改掉）

1. **memory 域身份旁路（已修 `63e8ae8e`）** ✅ —— `endpoints/memory/base.py:38-61` 手工剥 Bearer 头 + 直调 `verify_access_token`，except Exception: pass。**调用点 29 处**、横跨 5 个文件（crud 1 / metacognition 12 / profile 4 / tkg 4 / working_memory 8），初报"35 处"是原文出现数（29 调用 + 5 导入 + 1 定义），此处更正。回落面也比初报窄：带无效/过期 token 的请求早在 S-10 就被 `get_current_user_or_default` 挡成 401（`auth.py:541-556`），真问题是**与 `_user_identity()` 口径分叉**（存量 token 第二层键被写成 default）。无鉴权依赖的路由按结构扫描实测为 **16 条**（初报"14"来自一条不严谨的正则草稿）：其中 13 条同时走旁路（本批已补依赖并单源化），另 3 条（`/emotion/types`、`/{agent_id}/metacognition`、`/{agent_id}/metacognition/stats`）不取租户数据，判据外留档。**三条更硬的现行越权面（PUT 无归属校验、DELETE 传 `agent_wide=True` 关掉两层、GET 读零写入的存储且无依赖）已同批根修，图证、A/B 与一处守卫改判说明见 [`memory-isolation-2026-10-05.md`](memory-isolation-2026-10-05.md) §六。**
2. **`self._logger` 幻影引用破坏回滚（已修 `bf32ec98`）** ✅ —— `evolution/rsi/integration_manager.py:383/449` 用类内不存在的 `self._logger`（只有模块级 `logger:13`）。`:383` 位于 `:386` 回滚 setattr **之前**，抛出的 AttributeError 被 `:394` 吞掉 → "优化回执落盘失败时不回滚"，与注释承诺的安全语义相反。**按第 5 条全命中点扫荡**：AST 扫全仓 `self._logger` 取用点共 **151 处**，逐处判"所在类是否沿继承链定义过它"，幻影**只有本类这两处**（asr/、`core/base_module`、`context/injector` 等都有定义）。活体在真 RSI 管线上对照：修复前"回执写失败"分支 `{"applied": false, "decay_rate": 0.05}`（报失败却不撤效果），修复后 `decay_rate: 0.01`。**未顺手改的一处语义**：遗产分支（`debt_ledger=None`）写失败时仍返回 True——反向闸票面只针对带账本的场景，改成"任何写失败都走安全侧"会让配置错路径的优化整体失败，属口径变更。
3. **匿名可达的空转上报端点（已修 `f76677b5`）** ✅ —— `api/app.py:614 POST /api/v1/frontend/errors` 在 `global_auth.py:48` 白名单内，收 JSON 后只 `logger.warning` 便返回 `{"status": "logged"}`，**从不调 error_logger**；客户端被告知"已记录"而实际未存，体未见长度上限。**闭环时的实情比原判更完整**：sink 一直存在（`neurova/error_logger.py` 的 JSONL 读写 + 16 条自带测试），是**写了没人接**的断点；此外还有三处同源问题一并根修——解析失败回 200 且把 `str(e)` 回给匿名调用方（谎报状态 + 内部文本外泄）、载荷完全不限量（匿名可撑爆日志文件）、sink 侧把写失败吞成 `return 0` 且日志目录在**导入期**绑定数据根。现：坏体 400 / 超大 413 / 超条数 422 / 写失败 500 且不回显内部文本，只有真写进去才回 `logged` 带条数；载荷限 body 256KB·≤50 条·单字段 8000 字符（截断留 `"truncated": true` 痕）；归属只认服务端 `authenticateRequest`，丢弃载荷自带的 `user_id`/`timestamp`（否则等于允许日志投毒与嫁祸）。**额度没在此另造**：活体连打 140 发，前 120 发 200、第 **121** 发起 429，与 `rate_limit_per_minute=120` 吻合，证明 `RateLimitMiddleware` 已盖住这条白名单路由。A/B（core+api）基线 32 ⊃ 本树 31、零新增。教训一条：新判据自己也被常驻守卫逮住（探针字符串里写了开发机绝对路径，`TestNoHardcodedDevMachinePaths` 当场红），按守卫给的口径换成机器无关假路径，不改守卫不加豁免——见 `d319f4c3`。
4. **现役链读内存假存根（已修 `b3e44687`）** ✅ —— `notifications.py:83/117` 读 `enhanced_users_api.py:73` 的 `_users_store = {}`。**后果比"通知没送到"更硬**：那份字典从不播种，于是知识共享审批、市场提交、调度器失败这些**本应通知管理员**的事件每次都枚举到空集、全部兜底进 `default` 桶——既没送达真管理员，又把管理员可见内容放进 anonymous 共享可读面（与 §6-1 身份批同一张隔离面上的一格）。现枚举走身份链同一源 `UserModel.list_users(role=, status='active')` 并分页取（`limit=100` 默认值会把第 101 个账号静默丢掉）；"零账号才兜底 default"的单机语义原样保留并钉成判据。4 个测试文件共 10 条一并改判：它们原先靠注入那份字典"声明有个管理员"，等于在假契约上自证通过；现由共用夹具 `_realAccountFixture` 建/清空真账号。副产物一条：这些用例不隔离账号宇宙时会读到仓内 `data/users.db`（里面有真 admin），**通知是发给真人的**——§6-35 的落点隔离缺口因此多一格实证。活体：临时根两真账号 → 真后端 → alice 提交公库 → `notifications.json` 里 `kb_review` 的 user_id = 真管理员 id，落进 default 的条数 0。
5. **让位规则整条支路从未执行（已修 `49326f6d`）** ✅ —— `coordination_decorators.py:99` 调 `get_glance_yield_checker()` 漏 await，而工厂在 `glance_yield_rules.py:444` 确为 async def → 拿到协程对象，"操作碰撞即拒"实际空转。**本条原记两处，复扫实为四处**（同契约还有 `reset_glance_yield_checker`）：除 `:99`/`:271` 外，`coordination_api.py:111` 是**最危险的一副面孔**——协程被创建后丢弃、零异常，端点照常 200 `{"status":"reset"}` 而什么都没重置；活体对照（真 uvicorn + 生产挂载 `register_endpoint_routers` 89/89 + curl）修复前 register→`registered_agents:1` → reset→**仍 1** + 日志 `RuntimeWarning: coroutine was never awaited`，修复后 → **0**、警告 0 条。**第四处 `agent/turn_coordinator.py:52` 未修**：它的 `__init__` 是同步的（无从 await），紧接一行调 `GlanceYieldChecker` 全类不存在的 `initialize()`，且 `get_turn_coordinator` 生产侧零消费者（`tests/e2e/test_phase4_integration.py` 2 条预存失败即此）——补 await 只让它换个地方红，真正的处置是"接线 or 连同测试退役"，属产品裁决；判据里以"文件名→期望命中数 1"双向钉住（新增命中即红，修好了不摘表也红）。附带一条可达性事实：`coordination_decorators` 全模块**生产零导入**，所以 §6-5 说的"支路从未执行"比漏 await 更深一层——是被摘链的模块。
    **2026-10-07 两处事实更正 + 第一批落地（`78abaa2e`）**：① 「`test_phase4_integration.py` 2 条预存失败」已过期——本批复测 HEAD 上是 **7 条**，执行体收口并把用例改判到闸的真实契约上之后现 **17 passed**；② 第四处的处置形态不再是「接线 or 退役」二选一，用户已拍板**接真**，等待预算定为 ≤10 次、单次间隔 ≤20s（即总 ≤200s）、超时挂起等人工续跑。第一批只收**执行体**（教义第 7 条的四步序里前三步）：`agent/turn_coordinator.py` 重写为唯一让位闸（340→228 行，同步 `__init__` 不再无从 await、不再调不存在的 `initialize()`），被摘链的 `coordination_decorators.py`（304 行）连同其装饰器语义退役，漏 await 台账 `_UNWIRED_REGISTER` 随第四处消失**摘回空表**并另补一条 reset 端点行为判据（防"表空了但形态回流"）。**接线本体（闸进回合入口 + park/续跑闭环）为第二批，尚未落地**——所以本条的「支路从未执行」在第一批之后仍然成立，只是变了性质：不再是"两份实现各调各的"，而是"一份就绪但未接入"。接线前必须先修的记账根因见 §6-45，端点必 500 见 §6-44。
    **2026-10-07 第二批接线落地（`81fd6b56`）——本条"支路从未执行"至此才真闭环**：回合入口（`api/endpoints/console.py` 的 `/console/chat` 流式分支）现在真问一次闸；等不到额度就落 `parked`（`core/agent_run_store` 新增**非终态** + v2 迁移两列 `park_reason`/`resume_payload`）并以 `parked`+`done` 立即收尾；属主或管理员打 `POST /console/chat/resume` 复用**同一条回合入口**重跑（`resume_run_id` 通道 → 库里始终只有一行身份、`seq` 不变故仍排队头、载荷换手即清空），`GET /console/chat/runs` 是刷新/重启后的读面。活体量出并当场改掉一条判序缺陷：续跑原先先判状态再判身份，陌生账号会从**终态**行先拿到 409（等于确认这条 run 存在且已结束），现改为身份在前。**余下三条同根因入口已于第三批接上**（`d4c8b560`，台账执行体同时从 console 抽成四入口共用的唯一实现，见 §6-46 的闭环记录）。
6. **假委托 + API 签名断裂** ✅ —— `memory_layer/manager.py:2882/2889/2999/3005/3040/3045`（部分恒 return True）；`memory/profile.py:130/169` 传 user_id 位置参、`metacognition.py:329/412` 传 category=/top_k=，manager 形参不接受 → 必抛 TypeError，被 except Exception 折成 500；`models.py:133 UserProfile` 生产零引用。
7. **LM Studio 卡片恒灰** ✅ —— 见 B13：豁免分支不可达，无 key 时落到 `provider_manager.py:1326 return False`。
8. **依赖缺失仍返回成功** ◑ —— `channels/discord.py:255`、`qclaw.py:316`、`qclaw_service.py:77`；同形态在 `websocket.py:421` 已根修，按第 5 条应同批扫荡。**2026-10-06 复测三处仍是现行形态**：`REQUESTS_AVAILABLE` 为假时 discord 回一个 mock `message_id`、qclaw 回 `{"success": True, "message_id": "mock_media_…"}`、qclaw_service 回 `{"valid": True, "qclaw_user_id": "mock_user_…"}`——只 `logger.warning("模拟模式…")`，调用方无从分辨真假。**已于 `347bc581` 全族扫荡**：按第 5 条 AST 复扫实为 **26 处 / 10 文件**（不止三处），四类契约分别收成 False / None / None / 该文件已有的失败结构，并删掉同分支里的假状态写入（`_initialized = True`、mock token 进 `token_cache`、iLink 无操作却递增回复配额）。**判据按语义分类**：`telegram_api_client` / `wechat_auth` / `qqbot` 的 `_api_request` 返回的也是字典，但那是 `ok:False` / `errcode:-1` / `retcode:1` 的诚实失败，一个字都不动——第一版判据用 `ast.unparse(key)` 比键名，字符串键带引号回来，把 `{"success": True}` 也当失败放过（命中数 23 与人工 26 不符才暴露）。先例是 `test_b3_sip_honest_no_fakesuccess.py`（同口径）。活体最有说服力的一条不用构造：本机 venv 真没装 paho，`MQTT_AVAILABLE` 现值 False，修复前 `authenticate() -> True` 且 `_initialized -> True` 而 `_client` 从未存在，修复后 `-> False`。
9. **崩溃后无人接管** ✅ —— `recovery/` 的 sentinel 异常关机标记与按 agent_id 恢复记忆今日零承载；正常关停有人、崩掉没人管（`self.shutdown_guard` 全仓唯一出现处即 `app.py:62` 赋 None）。
10. **睡眠周期绕过装配点改私有字段且竞态未消** ◑ —— `manager.py:3908-3969` 靠"存旧值→改 `module._consolidation_threshold`→finally 还原"实现；`sleep_module.py:264/267` 读该字段时并不持锁（锁在 `:253-255` 已释放）。
11. **只写不读的配置面** ◑ —— `cognitive_layers/settings_config.py` 有 16 个 ParamSchema 自标"【预留】…修改暂不生效"，`activation.*`(7)、`auto_context.*`(2)、`graph.time_decay`、`vector_search.*`(3) 全域零读取方；同类还有 `AdaptiveToolWeights.lifecycle_state`（写盘但 load 从不回填）与 `total_latency`（只随 JSON 往返）。删须同步 i18n 11 语言 desc_key。
12. **EventBus 只 emit 不订阅** ✅ —— `cognitive_layers` 全域零 `_bus.on(` / `.subscribe(`，`manager.py` 5 处 emit，`get_stats()` 的 bus_handlers 恒为 0；`bus_event.MemoryModule` 从未被继承且其 init(bus, config) 签名与各模块实际 init() 不符。
    **2026-10-08 A 轮取证：本条原描述有三处要更正，且比原判更深**。① 全仓**不止一条总线**：`core/event_bus.py`（`publish/subscribe`，DCL 单例 `get_event_bus():324`，带优先级、事件日志、异步队列）与 `cognitive_layers/memory_layer/bus_event.py:125`（`on/off/emit/aemit`）是两份平行实现，而 `memory_layer/manager.py:185` 是 `self._bus = EventBus()` **每个 manager 自建私有总线**，外部唯一出口 `:832` 全仓零调用方（实测）；所以 MEMORY_* 不是"发了没人订"这么简单，是**发在一条别人拿不到的总线上**。② `bus_event.py:72` 那句"全仓无 emitter 也无 subscriber"指的是 P2-10 已删除的 `TOOL_INVOKED`/`METACOGNITION_EVALUATED` 两个常量，**不适用于 MEMORY_***——照原句读会误判成"连发都没发"。③ 第三份事件面在 `context/injector.py:36-69`：那是给 `BaseModule` 准备的 ImportError 降级替身，自带私有 `_event_handlers` 且 `emit_event` 里 `except Exception: pass` 吞 handler 异常；注释自述理由是"当 neurova.core 只有 .pyc 文件时"，属 `7835c367` pyc 骨架恢复时代的逃生门，而 `neurova.core.base_module` 恒可导入（实测 `_BASE_MODULE_AVAILABLE=True`）。
    **另扫出两条本条未记的硬形态（同批已修，见下）**：`core/base_module.py:83/:115` 调 `self._event_bus.emit(...)` 而那份总线只有 `publish`——一旦接线即 AttributeError；且全仓无一处给 `event_bus` 传非 None，`if self._event_bus:` 恒假，于是 `initialize/start/stop`(:141-174) 与 `idle_tracker.py:602` 的 `phase.changed` **一次都没发出过**，而 `api/endpoints/logs.py:72` 读的正是这条总线（写了没人读 + 读了恒为空，两头断点）。`injector` 的三个生命周期钩子是 `async def` 却体内零 await，被同步 `initialize()` 丢成协程对象（实测 `RuntimeWarning: coroutine ... was never awaited`），三条 `context.*` 订阅恒为 0——这是 §6-5 漏 await 同族的**类级**命中点，全仓 AST 扫同类形态只有这 3 处。
    **2026-10-08 缺陷①② 闭环（`b2a4cf55`）**：`_resolveEventBus()` 取"注入优先、未注入回落唯一全局入口"且每次现取（不在构造期冻结）；两处广播改指 `publish(..., source=MODULE_ID)`；`BaseModule.subscribe_event()` 新增为基类唯一订阅面；injector 的降级替身连同其私有事件面整体退役，三个钩子去掉误标 async；`orchestrator.init_context_system()`（唯一生产装配点）补调 `initialize()`。活体：真启动后 `context.build` 订阅数 0→2，`GET /api/v1/logs` 14 条事件里 12 条是 `module.state_changed`（此前恒空），再造一个 Agent 订阅数 +1。**未闭环的部分**：两份总线的合并与 MEMORY_* 的真实订阅者是 A3（下一批），本批只把"发得出、订得上"这条通道打通；`core/event_bus_enhanced`（重播/死信）仍零生产 import，属 §6-37 同族的"能力缺失还是预留"待裁。
    **2026-10-08 A3 落地（`e3cd82cc`）——本条到此才真闭环**：两份 EventBus 按教义第 7 条先比后合，选定 `core/event_bus.py`，`bus_event.py` 的 `EventBus`/`MemoryModule`/`ModuleHealth` 退役、只剩记忆域事件名常量表（改名 `MemoryEventName`，避开 `memory_stream.py:38` 那个同名不同义的 `MemoryEvent`）；`manager.py` 五处投递改走共享总线并带 `source`，私有总线实例与零调用方的 `bus` 出口一并删除，`get_stats()` 的两个读数从此读同一条总线。MEMORY_* 的"消费"落在**已存在的现役读面** `GET /api/v1/logs` 上（判据按这条钉，见 `test_memoryEventsReachLogsEndpoint.py`）——本批**主动撤回**了"接去清注入器上下文缓存"的形态，因为那张 LRU 的 `cache_entry`/`get_cached_entry` 全仓零调用方，接上去是假闭环（登记 §6-51 待人裁）。`event_bus_enhanced` 那一格不变，仍待裁。
13. **教义第 5 条"扫荡记账未落实"** ✅（已真闭环 `920dbfef`）—— `b84434cf` 提交说明自称扫荡了 `injector._truncate_text` 的 char/token 常数，但该 commit 对 `injector.py` 的 hunk 里没有 chinese_ratio / `_truncate_text` 任一行；实况 `injector.py:634` 仍按 `models.py:60 chinese_ratio` 就地折算。**2026-10-07 复测仍在位**（原判 ✅ 是空的，据此改回再闭环）：三处命中点同批收口——系数裁剪换成按统一估算器**整行二分**的 `_foldMemoryLineToBudget`（估算器不可加：实测 `est("- ")+est(正文) ≠ est(整行)`，按分量预留刚好越界），`TokenBudget.chinese_ratio`/`english_ratio` 两属性删除，零调用方的 `_truncate_text` 退役。同一入口的活体前后对照（`orchestrator.py:1759` → `builder.build_from_pool` → injector，记忆预算 4000）：中文 8400 tok 修前只填 58%（2341）、英文 4801 tok 修前只填 10%（403），且**两者裁出的字符数一模一样（2677）**——第二套固定系数的现场。**本条闭环顺带量出一条更大的**：生产默认 `enable_context_pool=True`（`agent_core.py:259`）时装配在编排器内联完成并于 `:1615` 返回，`_build_memory_context` **一次都不被调用**，`:1759` 那行只在池关闭/降级时走——见 §6-39，本批修的是池外分支。
14. **文档虚报集成完成** ◑ —— `docs/01-architecture/RSI_INTEGRATION_COMPLETE.md:24` 把从未接线的 EnhancedRatchetPruner 列为"集成完成"。同类：`skill_system_2.0.md:332` 承诺的 package 端点从未存在；`plugin-architecture-design.md:707` 按不存在的 `get_config_manager()` 写 import；`neurflow-dev-spec.md:68` 指定的 SkillChainExecutor 从未落地。
15. **守卫自身前提为假** ◑ —— `test_t09_selfloop_face_ruling.py:138/217` 断言的"MCPConnection 同名同源"不成立（详见 A7）；此类守卫必须先红灯修正，否则它会把错误前提固化成删除阻断。
16. **幽灵测试与空测试文件** ✅ —— `tests/unit/skills/test_skills_evolution_engine.py:10-17` 导入不存在的类名致整文件恒跳过；`test_skill_security.py` 共 17 行、def test 计数 0；`test_skill.py` 15 行、0 用例；`tests/execution_engine/test_tool_engine_v2.py:86` Mock 生产侧已不存在的 `engine._cognitive_security`。**"某模块有 N 个测试通过"在本仓不构成活证据，须先复算该测试是否真跑。**
17. **回退分支注册假实现（原判经复核改判，2026-10-07）** ✅ —— 原记：`skill_system.py:844-848` executor 注册失败即回退注册 `MemorySkill`/`FileOperationSkill`，而 `_store_memory` 什么都没存却回 `stored=True`。**复核结论：那段桩类不在生产路径上**——`neurova/skill_system.py` 被同名包 `neurova/skill_system/` 遮蔽，`import neurova.skill_system` 永不到达它；而它又不是死码：包 `__getattr__` 用 `spec_from_file_location` 有意把它按路径加载回来（ADR 0011 的规范实现载体，marketplace/skill/mcp_server/neurflow 四端点依赖，`test_skill_system_cleanup` 专锁此事）。**假成功的现场在真执行器里**：`skills/builtin/memory_executor.py` 在 `memory_manager is None` 时 store 回 `success=True, output={"stored": True, "degraded": True}`、search 回 `success=True, output=[]`——已于 **`f1a86796`** 收成诚实失败（点名缺什么），并改判三条把假成功当契约钉住的既有断言（`test_builtin_executors` 两条 + `test_default_skills_factory` 一条），影响面如实记下：三个走无参 `get_skill_registry()` 的端点从假成功变为点名失败，agent 侧传真管理器故不变。
    **连带登记一条比本条更值钱的结构性问题**：同一个 `neurova.skill_system` 名字下，包与影子文件**按符号名分头取实现**（registry/factory 从影子文件来，`SkillStatus` 一类在包内本地定义），`github_push/skill.py` 还另开一条 `spec_from_file_location` 后门自取基类——同一批符号三条取用路径。这正是 §9 序 8"skill_system 四体收口（-230）"的实体，但**先要裁定哪一份是规范**，不是能顺手合并的形状。**已按此裁定闭环（`14f0f164`）**：裁定过程证明"哪份是规范"要分符号答——`SkillRegistry` 是影子文件那份（ADR 0011 class A，包只是代理），`SkillResult` 则包导出的是 executor 层形状而运行时用 data 形状（名实分叉），而 `skills/models.py:Skill`（manifest dataclass）与影子文件 `:81 Skill`（行为基类）**根本是两层职责、不是同一功能的二实现**，所以不合并、只断多余取用路径。详见 §5 共性四判定与 §9.1 本批行。
    **取证纪律自纠**：我据原判一度 `git rm` 了 `skill_system.py` 与 `context.py`，被仓内守卫当场挡回后全部撤销——教训是"grep 到符号"不等于"这行代码在跑"，判死码前必须核导入解析结果（`hasattr(module, name)` / `module.__file__` / `__path__`），这条已写进 §8 的伪命中清单口径。
18. **安全实现里的假成功与弱加密** ✅ —— `emotion_adapter.py:46-82` ImportError 兜底成恒返 neutral/0.0 的 SimpleAnalyzer；`mcp_manager.py:248/259` 的 sse/http"连接"是自陈简化、`:213` Popen 绕开 shell 拒绝门；`secret_store_clean.py:79-103` 重复密钥流 XOR 且无 MAC。**逐条核现状（2026-10-07）**：第三条已闭环（`610b8a03`，见 A12 改判与 §6-34 附带两条）；前两条**原样在位**——`memory_layer/emotion_adapter.py:50/81` 的 SimpleAnalyzer 与 `execution_engine/mcp_manager.py:220` 的裸 Popen 均实测仍在，别把本条整体当已修引用。
19. **懒建单例缺 DCL+RLock（§3 违规面）** ✅（无锁那一格已闭环 `d63b3c66`，`Lock` 非 `RLock` 一格转棘轮） —— 原记：`collaboration` 侧 15+ 处裸判 None 无锁；auth 侧 4 份用 Lock 非 RLock；`get_flow_orchestrator:846` 无锁；`manager.py` 17 个 `_ensure_*` 不在锁内；`channels/manager.py:81` 懒建单例同样缺 DCL。**2026-10-07 按 AST 重测命中集，与原记差别很大**（原记是抽样描述，不是全量）：单例形态的懒建函数共 261 处，其中**完全无锁 79 处**（模块全局 74 + `cls._instance` 5）、**有锁但锁内单次判 7 处**（correct-but-slow，不是竞态）、**DCL 且用非可重入 `Lock`** 的落点按两种口径给出、别混用：按**函数**计数 150 处，按 **`with` 点**计数 165 处（一个函数里可能有多段锁），棘轮基线取后者并取的是 with 点口径 —— 因为要钉的是"每一段裸 `Lock` 的 DCL"。、**DCL+RLock 合规 25 处 → 收口后 31**。
    **已闭环的部分**：79 处无锁全部接上唯一实现 `neurova/core/lazy_singleton.py:lazySingleton`（DCL + `threading.RLock`，存储仍写回本模块全局名，故仓内既有 `mod._x = None` 复位路径一条不破）；缓存名写错在**装饰期** ValueError——收口时当场逮住一处真例（`tool_layers/capability_graph._META_RETRIEVAL_ROSTER` 只在函数里 `global` 过、模块字典没这个名字，照旧写下去＝每次调用重建名单）。红灯是并发探针（barrier 强制构造重叠，修前 8 线程 8 次构造、修后 1 次），不是形态断言。
    **本批明确不做的两格与代价**：① 165 处 `Lock` 逐处换 `RLock`——只有"构造期回落同一入口"才是真死锁，其余属形态不合，一次换 165 处是把判据面铺到无法归因的宽度，改为**只降不升棘轮**钉住（`test_lazySingletonDcl.py::testNonReentrantSingletonLocksDoNotGrow`，基线 165，新增即红，清到底时连基线一起删）；② 那 7 处锁内单次判保持原样。
    **扫荡带出的同族缺陷另立 §6-43**（`skill_service` 的 read-modify-write 不在 `self._lock` 内，判据已在位且常驻红）。
20. **`neurova/expected` 与同批的 `missing`** ✅ —— 均为 0 字节重定向残留，由 `98b5422a`「清理临时文件」引入（该提交还删了 471 行的 `missing_files.txt`）。
21. **后台任务句柄丢弃 → 关停无法收敛（已修 `b5f80e9c`）** ✅ —— `_schedule_mcp_bootstrap`(`api/app.py:765`) 起的 stdio 会话，`MCPToolClient.disconnect_all`(`tool_layers/mcp_client.py:240`) **生产侧零调用方**（同批还发现 `execution_engine/mcp_manager.py:395` 的第二份 `disconnect_all` 同样零调用方，属 §3-A7 面）；portal 只能取消，而 stdio reader 取消不收敛 → `thread.join()` 永久阻塞，真进程侧是 npx 子进程泄漏。同根因第二命中点：`bootstrap_mcp` 的 `_bootstrapped` 只写不读，重复 startup 顶掉活会话。**修法**：关停先收敛任务再关会话（注册表 + 进程单例两个发现口），`_bootstrapped` 转为被读。
22. **`POST /api/v1/health/recover` 假成功（已修 `212d855c`）** ✅ —— `endpoints/health.py:179-187` 写 `# TODO: 实现恢复逻辑` 却回 `success: true` + `"Recovery triggered"`；全仓除该测试文件外零消费者（NeurUI/NeurovaHarmony 零命中）。已收成显式 501 + 点名原因（路由保留），并同批删掉失去消费者的 `RecoveryResponse` 与本就零引用的 `RegisterCheckRequest`。
23. **响应模型不接受的字段被静默丢弃（已修 `d8f86dcd`）** ✅ —— `endpoints/health.py:88-92` 给无 `message` 字段的 `HealthStatusResponse` 传 `message="Health checker not available"`，pydantic v2 默认 `extra='ignore'` → 降级原因不可观测，调用方只见 `status:"unknown"`。字段已补进模型（与同文件 `CheckResultResponse.message` 同名同默认值，不另造口径）。
24. **进程级 agents 表是跨用例耦合面** ◑ —— `enhanced_memory_search_api.py:24` 自陈"唯一事实源是 `get_app_state()['agents']`"（`request.app.state.agents` 生产恒空），于是任何跑真实 startup 的用例都会把一个真 agent 写进该表，把同进程后续 18 条（nerf 11 + semantic-search 7）带倒。本轮在新用例内按原样回填所动全局以自证隔离；**表本身的单源化/用例隔离属预存脆弱面，未放宽**。
25. **时间边界抖动** ◑ —— `tests/integration/collaboration/test_phase3_intelligence.py::TestEdgeCases::test_outbox_expired_event` 以 `expiration_ttl=0` 撞墙钟，连跑 5 次 2 负，与本轮改动无关（A/B 逐行核过），登记备查。后续单跑三次全绿，目录跑时仍偶发翻转。
26. **落盘锚点接受非路径对象并在进程 CWD 静默建塔（已修 `a9170fa9`）** ✅ —— `MagicMock` 实现了 `__fspath__`，故 `Path(mock)` 能过类型检查、其 repr 被 Windows 拆成相对目录，随后 `mkdir(parents=True)` + 写盘**全部成功**，只在 `except OSError` 留一行 debug；仓库根实际长出过 `MagicMock/SkillService().skills_dir/<id>/.lifecycle_state.json`。同契约三命中点（`skill_lifecycle.run_sweep_if_due`、`ConsolidationPlanStore.__init__`、`SkillService.__init__`）现统一收到 `data_root.require_data_path`。**读码新发现**：判据必须落在**公开入口**——放在 `_state_file()` 那层会被 `_load_last_run` 的 `except ValueError` 吞成 "last=0"，非法路径照样落盘。**另记一条治理教训**：`.gitignore:380` 的 `/MagicMock/` 与 `git log` 表明该症状至少复发三次（`84260bb4` 2026-06-08 排除、`dd03d67c` 2026-09-02「根目录二次清理 — git rm … 垃圾 + gitignore 防再生」、2026-10-04 再现），三次都停在"清理 + 忽略"，从未查落点为何漂到 CWD——按教义第 2 条，"防再生"的 ignore 是把失败改写成静默，本条是首次根修；规则保留只为防误提交，不再充当止痛。
27. **跑测卫生三件（本批取证时发现，均预存）—— 三件已全部根修** ✅，逐件如下：
    ① `tests/unit/evolution/eval/` 挂死（`ea1da5ae`）：真因不在 runner 也不是死循环，而是三个文件传 `agent=None`，`service.py:209/327` 的 `agent or SimulatedAgent(...)` 回落成**真** LLM 客户端——**用例在发真实请求、花真实配额**，被判 `rate_limited` 后进入"≤10 次 × 间隔 10s"等待，远超 30s 用例预算被 thread 方法击杀，连累整目录。修法：目录级出站闸 + `offlineAgent`（8 处 `agent=None` 逐方法替换）。闸必须抛 **BaseException 子类**——`SimulatedAgent.run` 外层 `except Exception` 会把 AssertionError 吞成空回复，普通断言等于哑闸。
    ①附：同根因第四处 `tests/llm/test_instream_error_encoding.py`（故意喂 429 却没免等待）按 `_sleep_for_retry` docstring 预留的桩注入点收口；揭盖后 6 条全绿，说明挂死背后没藏别的缺陷。
    ② `tests/benchmarks/test_multi_agent_coordination.py` 收集期 ERROR（`ce74616b`）：模块顶层 `from neurova.agents.seen_boundary import ...`，该包本仓不存在 → `Interrupted: 1 error during collection` 使 `pytest tests/` **一条都不跑**。第 7 条比后判退役：全文 0 个 `def test`、三个基准方法**全都**依赖两个已退役模块、全仓零消费者、现役能力另有真用例在跑。修后全仓收集 `21292 tests collected` 零错误。**2026-10-06 复测：`21357 tests collected`、零错误、62.45s**（增量 65 条来自后续批次新增守卫，收集守卫 `tests/unit/core/test_whole_repo_collection_errors.py` 单跑 3 passed——它不进 CI 子集，因每次要 60s）。
    ③ `tests/unit/planning/__pycache__/*.pyc` 被跟踪（首次尝试 `5193a885` **未真正交付**，`2c681e17` 才收口）：**gitignore 规则对已跟踪文件不生效**——`dd5b00be`(08-30) 批量提交带入，`472a0180`(09-22) 才补 `tests/**/__pycache__/`，规则本身没错，这两个是规则之前的既成事实，于是每次跑测稳定产生一条无关 diff，污染 `git status` 与 A/B 判据。`git rm --cached` + 新增 `test_no_run_product_is_tracked`（取 `git ls-files` 而非磁盘形态：磁盘上的 pyc 是正常产物，仓库里的才是债）。**这一条我自己踩了命令坑**：`git commit --only -- <path>` 按**工作树内容**提交该路径，与 `--cached`（磁盘保留）叠加后，删除被在盘同名文件覆盖回去，那次 commit 实际是一次 `Bin 149 -> 149` 的内容更新；提交后复跑守卫转红才暴露——删除类改动的正确形态是"状态进索引 + 不带路径的 `git commit`（只提交索引）"，且绿灯必须在落库之后复取（教义第 4 条）。
    ④ 同批新增的全局收口（`9df526b9`）：`tests/conftest.py` 里 autouse 逐用例快照仓库根顶层条目，新增即红并点名肇事用例，与 §6-26 的具体根修互补。
    **仍存疑、未处理**：429 等待重试的最坏叠加时长（10 次 × 封顶 120s）在生产里没有全局 deadline，只有"重试次数"上界——是否要给整条请求加墙钟预算属产品口径，未擅动。
    **2026-10-08 闭环（`94f4eedc`，P3-11 B1；拍板"对比之前修过的 429：重试 10 次、每次间隔 20 秒"）**：这一格不再是"未擅动"。`security/llm_retry_settings.py` 的 DEFAULTS 新增 `wait_budget`（默认 200.0）并把 `interval` 默认由 10.0 改 20.0，与让位闸同口径；消费方 `multi_model_client.py` 把累计等待挂在**整条请求**上（不是每个候选一份），两个睡眠点 `:737`/`:1180` 都先问预算，不够这一发就**不再睡**、交回既有换模型/`exhausted`+流内错误路径——不新增错误形态，也不把失败降级成 warning。行为判据实测：`max_retries=50` + 两候选恒 429 时 `sum(sleeps) ≤ 200s` 且给出诚实终态（改前该值是 1000s 量级）。**留下的口径边界**：预算量的是"累计等待"，不含请求自身耗时（那由 read timeout 侧管，`tests/unit/llm/test_llm_read_timeout_split.py`），两处各扣一次等于把同一笔账算两遍；且 `wait_cap=120s` 未动——上游持续返回超大 Retry-After 时单发仍可吃满 120s，要不要把它也压到 20s 属另一拍板。
28. **会话与记忆按 user_id 隔离（政策拍板后的一轮，A/C/D 已修，B 判为产品口径）** —— 政策：匿名共享 default 桶可接受，但租户键必须是 user_id。
    **A 已修 `ed015dcb`**：`home.py` 的 `_real_conversation_count()` / `_aggregate_daily()` 不带 `user_id`，而 `/home/*` 是严格门 → 已登录用户在首页看到**全体用户**的会话数与按天趋势（核过不返回标题/正文，泄露面是跨租户聚合计数）；`GET /api/v1/stats/agents` 连门都没有，补的是 `get_current_user_or_default`（此前匿名可达，加硬门会打断既有调用方）。顺带挖出 `export_stats` 用 `await get_agents_stats(request)` **把端点当普通函数复用**——依赖不会被解析，一加身份参数就抛 AttributeError 并被自己的 `except` 吞成"agents 段空"，已抽 `_agentStatsRows(callerId)` 让两侧共用。
    **C 已修 `bcbb5f69`**：会话归属判据在 `console.py` 写了 5 份（helper 本体 + `_find_session_target` + delete/rename/auto-title 各一份），收口为一处。
    **B 更正我自己的判断**：我先前把"console 面校验会话属主、chat.py `/history` 只校验 agent 归属"记成现行越权面。新加的矩阵守卫实测**推翻**了它——bob 用真身份从 6 条会话端点碰 alice 的会话，修复前就已经全部 403；而 `chat.py` 那条要成立需要"同一 agent 的两个不同用户都能过 `can_access_agent`"，该判据是 admin 全量 / owner 匹配 / 无主仅 admin，普通用户不可达。所以它只是**口径不一致 + 纵深不足**，不是漏洞；是否让 agent 属主读到他人会话属产品语义，未擅动。（同 §七 教训：代码里有分叉 ≠ 请求能走到它。）
    **D 已修 `e040304d`**：`save_message()` 建新记录写死 `user_id=""` 且无入参，两个生产写方都无法声明归属——console 的 fork 只靠"先 create 再 save"的顺序侥幸，`room_store` 则恒产出共享会话。修法：加 `user_id` 关键字参数、既有属主只回填不覆盖、**生产调用点必须显式声明**由源码守卫钉。判据形态换过一次：先做"必填无默认"，实测要拉 24 个不建模归属的测试调用点填噪声，遂改为"带缺省 + 生产侧显式（源码守卫）"。
    **本轮新登记的债**（两笔，均已在同批后续闭合）：`auth.py:415` 与 `deps.py:38` 是**两份同名不同体的 `get_current_user`**（后者额外接受 `?access_token=` 查询参数），console 用 deps 那份——它让 `dependency_overrides` 打错对象时静默失效（本轮就这么红过一次），合并属全仓鉴权口径，需单开一批 → **已修 `b77d9b24`**（推导合一、两种凭证策略改叫两个名字、deps 收成带理由的再导出）。`tests/unit/test_session_round_ops.py` 单跑 7 failed（history 混入 98 条额外消息，疑跨用例共享会话目录），预存、与本批无关 → **已修 `fb7801be`**，真因是 chdir 隔离不了 `dataLanding` 落点，用例一直在读写仓库真实 `data/sessions/`；**同一根因的其余命中点转 §6-29**。
29. **`monkeypatch.chdir` 隔离不了 `dataLanding` 落点——同一根因的命中点全量清点（`fb7801be` 修一处，其余登记待点单）** ——
    根因不在用例，在两次收口的时间差：`session_manager.py:205-207` 的落点解析是「显式入参 > `NEUROVA_SESSIONS_DIR` > `dataLanding("sessions")`」，第三档**与进程 CWD 无关**（`c2cb809c` 2026-09-22「运行期落点全量锚定数据根」把原兜底裸相对名 `"sessions"` 收进数据根，方向正是 §6-26 的锚点纪律）。凡此前靠 chdir 隔离会话目录的用例，前提在同日即失效——它们读写的是**仓库真实 `data/sessions/`**。`tests/unit/test_session_archive.py:24` 的 docstring 还写着"SessionManager 的 sessions/ 是 CWD 相对"，该句现为假。
    **取证方法换过一次（这是本条最该记的）**：先用"跑前后 `find | sort` 集合差"，`test_session_archive` 报 `added=0 removed=0`，看着像干净；改用 mtime + 全树 md5 聚合复测，同一次运行**动了 15 个真实文件**（把 `kai/`、`default/` 下的会话移进移出 `archived/`）。集合差只能看见新增/消失，**看不见原地改写与等量搬移**——凡判据是"数据根有没有被写"，必须取内容指纹，不能取文件清单。
    实测（逐文件单跑，判据 = 跑前后 `data/sessions` 全树 md5 是否变化）：
    - `tests/unit/test_session_round_ops.py`：chdir 假前提 → 修前 6 passed / 7 failed 且每次 +1 真实文件；`fb7801be` 改 env 注入口后 **13 passed、md5 不变**。
    - `tests/unit/test_session_archive.py`：chdir 假前提 → **4 failed / 4 passed（预存）**，真实 store 被搬移 15 个文件。该文件最后一次改动是 `4a3c9380`(09-04)，早于 `c2cb809c`(09-22)，与本会话所有 commit 无关。
    - `tests/unit/agent/test_p3_p4_refactor.py:252`：**零隔离**直接 `SessionManager().create_session(agent_id="a1", user_id="u1")`，单跑 6 passed / 7 skipped——**全绿却在真实数据根建会话**，md5 变化。它同时证伪一件事：§6-27 ④ 的仓库根污染守卫只盯仓库顶层条目，`data/` 内部它看不见。
    - `core/test_session_manager.py`(31 passed)、`core/test_session_manager_json_safety.py`(6)、`core/test_session_assistant_metadata.py`(5)、`agent/test_history_write_fence.py`(16)：md5 不变，不污染真实盘，但隔离手段是 patch 私有方法 `_get_session_dir` / 直改私有字段 `_sessions_dir`——第 3 条明禁的"绕过生产装配点"，今天能过只因为那两个内部口恰好是唯一读路径，生产侧新增一条不经它们的解析就静默失效。
    - `memory/test_memory_loop_fixes.py`(8 passed)、`tools/test_shell_sessions.py`：不写真实盘（后者是 `ShellSessionManager`，与本契约无关——顺带记一次伪命中：`grep "SessionManager()"` 会把 `ShellSessionManager()` 一起捞进来，**"18 个文件未隔离"的最初估计就是这么来的，实测按精确类名 + 行为判据复算是 3 个真命中**）。
    **候选（未动，按此序性价比）**：① `test_session_archive` 4 条 + `test_p3_p4_refactor:252` 一处，同形改成 `NEUROVA_SESSIONS_DIR` + 单例复位（即 `fb7801be` 的形态）；② 上面四个 patch 内部口的改走同一 env 注入口；③ 一条守卫「跑测期间 `data/sessions` 内容指纹不得变化」，与仓库根守卫互补，成本同量级（现测 listdir 0.10 ms，md5 全树聚合每次约 0.2 s）。
    **已于 `abfe6d6b` 全数闭环，且实测命中面比本条估的 3 处大**：接守卫后按引用面跑 41 个文件，被点名的是 **8 个文件**——除上面列的，另发现 `api/test_session_summary_{cache,sidecar}.py` 与 `test_session_count_and_console_bound.py` 把 `NEUROVA_SESSIONS_DIR` 设成**相对值** `"sessions"` 并配 chdir（断言里还散布 `Path("sessions")` 字面量），其注释自称"相对路径才不毒化后续依赖 CWD 的测试"——那条依赖正是本条登记的假前提，`fb7801be` 之后它不再保护任何人。
    **收口形态是两层而不是一条守卫**（候选③按实测改了设计）：目录内容判据要么每用例取全树指纹（实测 4.71ms/次 → 每用例 2 次，全仓 2.1 万条 +200s），要么退化成清单集合差（看不见原地改写与等量搬移）。改为 ① `tests/conftest.py::_isolateSessionsLanding`——落点**默认**隔离（先只有守卫时，被点名的 16 条 ERROR 全是"起真 app"的用例：单例在每条用例里被重新构造，逐条补 env 属第 1 条禁的 consumer-side 打补丁；同手法仓内先例 `_isolate_agent_workspaces_root`）+ ② `_guardSessionLandingIsIsolated`——收尾守卫钉**装配点**，挡"显式改回真实库"。只留默认值一句 setenv 就能穿透，只留守卫每条用例都要自己补，故两条都要。
    取证中踩到两条通用坑（都进了 docstring）：**autouse 夹具按建立逆序拆除，不显式声明依赖时守卫会跑在隔离夹具的复位之后，`_instance` 已是 None，判据永远看不见肇事者**（本批哑火两次，靠临时 MARK 抛出 + 打印 `sys.modules` 才定位）；`tests/manual/*.py` 在**导入期**改 `os.environ`，它们不匹配 `test_*.py` 故默认不被收集，但被显式列进命令行时 env 会传给整个进程——实测掩盖过一次守卫（带上 manual 时 0 ERROR，摘掉后 16 ERROR）。
    复验：41 文件收口前 45 errors → **413 passed**；`test_session_archive` 4 failed/4 passed → **8 passed**；`tests/unit/api`+`core` A/B **32↔32 逐行一致**；整场跑测前后 `data/sessions` 全树 md5 不变。
31. **`tests/manual/*.py` 在导入期改写进程环境（已修 `4ef87e3d`）** ✅ —— 实测 **21 个文件 / 27 处**在模块顶层写 env（如 `os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp())`）。默认收集不到（名字不匹配 `pyproject` 的 `python_files`），但一旦被显式列进命令行就把变量带进**整个跑测进程**，此后所有依赖数据根/落点的判据被无声掩盖。不是推测：接 §6-29 落点守卫时同一条 41 文件选择集，带上 manual 时 0 ERROR，摘掉才露出 16 条真 ERROR——差点把“守卫不咬”当成“没有欠账”。
    修法拦在**收集之前**：`tests/manual/conftest.py::pytest_configure` 显式拒绝并给出正确调用方式（`python tests/manual/<name>.py`）。直觉方案 `collect_ignore_glob` / `pytest_ignore_collect` **实测对命令行直给的路径在 pytest 9 都不生效**，而收集即导入，钩子回来时 env 已改完。第二处坑：路径比较须用 `Path`，Windows 下 `str(path)` 带反斜杠，字符串 "tests/manual" 永不匹配（第一版就此静默失效）。
    三道判据（`tests/unit/test_manual_scripts_are_not_collectible.py`，红→绿实证：修复前探针 `LEAK= 1` 且退出码 0，修复后退出码 4 且读不到标记）：默认收集防线（口径**从 pyproject 现值读**，不另抄 glob）、显式点名被拒且同进程读不到污染（探针故意用**匹配收集口径**的文件名，证明拦截不靠“名字碰巧不被收集”）、整目录同样拒。
    **仍留的口子（须人裁）**：这 21 个脚本自身的导入期写 env 形态没动——作为脚本直跑它必须先于 `import neurova` 生效。彻底收口要么把它们移出测试树（`tests/runners/`？AGENTS.md §2 只规定“测试用例统一落 tests/”，脚本算不算用例未定），要么逐个改成 `__main__` 内的显式 setup（21 文件、回归风险高）。本批选择堵住被误用的通道，不重写脚本。
    **取证自证**：本条测量两次让 `a1` 下生成 `session_b6dab8cc_*`、`session_49ed4370_*`，均已即删，文件数回到 98；`_summary_index.json` 被运行重写过，留有这两条幽灵键——按 `session_manager.py:1870`「索引键集 ≠ 目录指纹键集即整份作废重建」，下次读取自愈（此为读码所见，未再实测触发自愈以免又写一次真实盘）。
30. **2026-10-06 对既有登记的复测更正（回答"还欠什么"时逐条重跑，不沿用旧值）** ——
    - **§6-5 命中点漏了一条**：`coordination_decorators.py` 调 `get_glance_yield_checker()` 漏 `await` 的实测有 **两处**（`:99` 与 `:271`），本条原先只记 `:99`——即第 5 条要求的"全命中点扫荡"当时没扫完，仍是欠账。
    - **§6-20 现状已变**：`neurova/expected`（0 字节）仍在（`Oct 4 01:04`），`neurova/missing` 已不在。所以序 1 的那句"`git rm neurova/expected`"仍待办，但"两件"的表述要按一件读。
    - **§6-16 四件命中里有一件正被在途改动删除**：`tests/unit/skills/test_skills_evolution_engine.py` 此刻是工作树 `D` 状态（同批还删了 `neurova/skills/evolution_engine.py`，并带来 `evolution/`、`skills/` 一大批 M/??），**未提交即未交付**，不计入已修；`test_skill_security.py` 仍在（17 行、0 用例）。
    - **仍现行确认未修**（逐条 grep 复算）：§6-2 `integration_manager.py:383/449` 的 `self._logger` 幻影引用（回滚路径仍被 `except` 吞）；§6-4 `notifications.py:85/119` 仍读 `enhanced_users_api._users_store = {}`（`:73` 空字典原样）；§6-8 三条"依赖缺失仍返回成功"（见该条新记的实测返回值）。
    - **本轮自己造成的台账缺陷已修**：§6-27 的 ①②③④ 曾被排到 §6-28 之后（排版串号，会让读者误归因），以纯行序置换修正并断言置换前后行多重集相等。

32. **env 重定位的落点直接喂 `Path`——空串键把审计流指到进程 CWD（已修 `98e07c70`）** ✅ ——
   `Path(os.environ.get(K, default))` 有个不显然的语义：**第二参只在键缺失时生效**，键被设成
   空串时它返回 `""`，`Path("")` 即进程 CWD。`rsi/result_summary.py:89` 就是这样：空串 env 让
   `attach_persistence` 去 `open('.')`，OSError 被自己的 `except` 吞成"保持内存模式"——运维以为挂了盘，
   其实一条没写。同文件另一副面孔是相对 env 值跟着启动目录漂。改走 `resolveDataPath`（绝对放行、
   相对归数据根）。第二处 `evolution/evolution_settings.py:29` 的默认值 `"config/evolution_settings.json"`
   也是相对字面量——**仓库根那个未跟踪的 `config/evolution_settings.json` 就是它写出来的**；默认值改锚
   `repoRoot()/config`（与同目录 `cors.json` 同一口径，位置零变动、不迁移既有配置），显式 env 值按
   `callerPath` 原样承载（与 `governance_settings` 同口径，测试隔离靠这条）。
   **判据自身的盲点一并补**：`test_runtime_landing_root` 认 `Path(config.get("NEUROVA_.._UPLOADS", "相对名"))`
   的前提是**键名带路径语义**；而 env 名不含 PATH/DIR、键又是变量间接引用时两个条件都不满足，静默漏过
   （第二处就是这么活下来的）。扩展为"外层是 Path/open/mkdir 这类路径语境时，兜底字面量本身即证据"，
   并加反向断言守住边界（`os.environ.get(_MODE_KEY, 'debug')` 这类非落点调用不得被误伤）；扩完全仓
   1000+ 文件只新增命中 1 处，正是 evolution_settings——不是撒网式误报。教训形态：**判据修的是代码，
   但判据自己也会漏**，每扩一次判据都要同时写一条"它必须抓到这个形状"的反证。
   附带一条口径统一：`_ENV_OVERRIDE_KEY` → `ENV_OVERRIDE_KEY`，对齐同职能的 `ENV_SUMMARIES_PATH`/`RECEIPTS_ENV`。
   **记账更正（我自己又犯过一次）**：`98e07c70` 提交说明写"生产净 +8（+13/-5）"，`git show --numstat`
   复算实为 **+17**（evolution_settings +11、result_summary +6）——错因是把两个文件的行数粗加成了净值。
   提交已入库不可改写，以复算值为准；这条与上一轮 "-38 应为 -17" 是同一个病：**净 LOC 只能逐文件 numstat 复算**。
33. **台账号引导脚本绕过数据根（已闭环 `f9f1b70b`）** ✅ —— 原判据与取证：`create_admin_user.py:17` 写死 `UserModel(db_path="data/users.db")`（**CWD 相对字面量**，`NEUROVA_DATA_DIR` 完全不生效），本会话活体取证时它把一个 admin 写进了**仓内真库**（临时数据根里反而没有），事后按 `id+username+role+created_at` 四条件精确删行（其余用户未动，`login_logs` 无关联）。处置按**下面那份**决策影响面走"改锚 + 口令注入**同批**"：脚本改用 `UserModel()`，与服务端 `_get_user_model()` 同一解析口径（`user_model.py:73` → `callerPath("", "users.db")` → 数据根），不另抄一条锚点调用；口令只认 `NEUROVA_ADMIN_PASSWORD`，强度沿用仓内 `PasswordHasher.is_password_strong`（不另造策略），不再回显；原 `except → print + traceback` 仍以 0 退出改为异常穿透非零退出。`docs/06-bugfix/login_fix_summary.md` 里那份把口令写公开的记录**不重写历史**，就地加"勿再照本节执行"的更新注记并提示已建过账号的部署改密。
    过程中我自己引入又当场消掉的一条：先加了"tty 上 `getpass` 交互输入"分支，实测 **Windows 的 `getpass` 直接读控制台、不看 `sys.stdin.isatty()`**，无人值守（stdin 重定向到 NUL）时把进程挂死在提示符上（`faulthandler` 栈定位到 `win_getpass`）。安装脚本有一条能阻塞的路径就是事故源，故只留注入，理由写进 docstring；判据常驻 `tests/unit/test_adminBootstrapLanding.py`（6 条，子进程探针且 cwd 故意不同于数据根，使两种落点一眼可分）。
    遗留的**同形态命中点 3 处**见 §6-38；"敏感记忆落盘加密从未接线"这条更大的发现见 §6-37。
    **按核心原则第 8 条补决策影响面**：
    - 接线后实现什么：脚本改走 `resolveDataPath()`/`get_data_root()` 锚点后，语义从"操作仓内 dev 库"变成"操作**当前数据根**"——桌面部署与 dev 部署各建各的账号，设了 `NEUROVA_DATA_DIR` 的部署首启就能拿到可用账号。
    - 数据从哪来到哪去：脚本 → `auth/user_model.UserModel(db_path=…)` → `<数据根>/users.db`（bcrypt 口令哈希）；读侧是 `api/endpoints/auth.py` 登录链（本批活体即凭此发 JWT）。
    - 影响面覆盖哪些模块：`create_admin_user.py` 本体、`docs/` 里指向它的初始化指引，以及**同形态的其它仓根脚本**——须先扫 `db_path="data/…"` 这类硬路径，命中点同批改（§5），否则修一条又留一片。
    - 不接线留下什么：重定位部署继续"脚本报成功、账号在别处"，并继续往仓内 dev 库写垃圾行。
    - 代价与不可逆点：改锚本身可逆（脚本无迁移语义）。真正的坑是它把弱口令 `"Admin23@"` 硬编码并打印到 stdout——**只改锚等于把一枚公开口令的 admin 从 dev 库搬进用户真实数据根**，是把问题搬大不是修好。所以"改锚"与"口令改为交互/环境注入"必须同批；后者改变调用方式（不再能无人值守一行跑），会影响 CI 与文档里的既有用法，这一层需产品拍板。

34. **同族降级门：`memory_layer/security.py:_FallbackCipher`（已闭环 `f9f1b70b`）** ✅ —— 原状：`:365-367` 在 cryptography 缺失时只 `logger.warning("…使用回退加密器")` 就换成 `_FallbackCipher`（`:243/261` 重复密钥流 XOR，与 §6-31 刚退役的凭据弱加密同族），且 `_FernetCipher.encrypt/decrypt` 把失败**改写成空串**——写侧落一条"加密成功的空记忆"，读侧让记忆看起来"没内容"。
    **处置形态是取证定的**：`encrypt_sensitive_content`/`decrypt_sensitive_content` 在 `7835c367`（pyc 骨架恢复）、`33b71a25`（桶层摘链）与 HEAD 三个版本上，`git grep -c` 命中文件**只有 `security.py` 自身**——这条链从未被任何调用方走过。既然写路径没被走过，盘上就不可能有 XOR 存量，于是可以直接 fail-fast（抛 RuntimeError 点名缺哪个依赖，口径对齐 `providers/secret_store.py:40-49`），不必先做 legacy 读回。同批收掉 `_load_or_create_encryption_key` 的 `except → return 随机临时密钥`：那是 M-12 的另一半，发一把"重启即失效"的钥匙等于亲手制造下一次"记忆消失"，现在记 ERROR 后抛出。判据常驻 `tests/unit/memory/test_memoryCipherFailFast.py`（5 条，含"零调用点"这一账的双向钉）。
    **本条闭环换来的、比它本身更大的一条**：既然这条链零调用方，那"敏感记忆落盘加密"这项能力就是**文档有、代码在、线上无人走**——另立 §6-37 按核心原则第 7 条记影响面，需人裁。
`:365-367` 在 `_FernetCipher` 抛 ImportError 时只 `logger.warning("cryptography 库未安装，使用回退加密器")` 就换用**重复密钥流 XOR**（`:243/261`，与 P0-3 刚退役的形态同族），且其 `decrypt()` 失败时 `return ""`（把解码失败改写成"这条记忆没内容"）。与 §6-8 渠道族是同一口径问题的密码学版：依赖缺失该 fail-fast 点名（`providers/secret_store.py:40-49` 已是本仓正确范例），不该降级成弱密文继续写盘。**未顺手改的原因是要先取证**：这一格的存量是**记忆库**（不是凭据桶），删降级门之前必须先答"有没有部署真在没装 cryptography 的机器上写过 XOR 记忆、今天还读不读得回"——`cryptography>=41.0` 在 `requirements.txt:88` 是声明依赖，实测本机可导入，所以降级支路今天不可达；但历史落库若存在，直接摘门会把那些记忆变成 `""`。处置需人裁：① 保留只读 legacy 解码再摘写路径（同 P0-3 形态，代价是要先找到存量库并证明可读回）；② 或确认全仓无 XOR 存量，直接 fail-fast。
    **按核心原则第 8 条补决策影响面**：
    - 接线后实现什么：依赖缺失时**拒绝初始化并点名**（照 `providers/secret_store.py:40-49` 的 HAS_CRYPTO 范例），不再产出"可被密钥流复用推懂"的伪加密记忆；同时把 `decrypt` 失败 `return ""` 改成抛出——今天那个空串正是把"解不开"改写成"这条记忆没内容"。
    - 数据从哪来到哪去：`MemorySecurity._init_cipher` → `encrypt/decrypt` → 记忆正文列（`neurova/memory/__init__.py:108` 是该模块唯一入口，读侧即敏感记忆的召回与展示）。
    - 影响面覆盖哪些模块：`cognitive_layers/memory_layer/security.py` 本体 + 其唯一调用方 `memory/__init__.py` + **所有已经用这条路径落库的记忆行**。
    - 选项①（留只读 legacy）代价：先要跨部署取证"这台机器的记忆库里有没有 XOR 存量"——探测法现成（无前缀 base64、XOR 后能 UTF-8 解开的行即为候选），成本是一次真实数据根的读扫描；好处是零断读风险。
    - 选项②（直接 fail-fast）代价：零代码成本、口径最干净；但若真存在 XOR 存量，那些记忆从"显示为空"变成"当场报错"。**不可逆点评估：没有**——密文仍在盘上、只是不再被静默当成空内容，改回①即可恢复；换来的是"坏数据第一次真正被看见"。
    - 不接线留下什么：任何一台没装 `cryptography` 的机器继续静默写入弱密文，且失败面被空串抹平，排查者拿不到任何信号。
35. **跑测会在仓内数据根创建 `data/web_reach_credentials/`（空目录）** 🔴 —— 实测发生于 A/B 期间（目录时间戳与跑测窗口一致，仓内 `data/` 未被 git 跟踪也无 ignore 规则覆盖该子目录名）。成因是 `web_reach/credentials.py:63` 的 `callerPath(base_dir, "web_reach_credentials")` 在构造时即 `mkdir`，而 `tests/conftest.py` 的落点隔离只覆盖了会话（`_isolateSessionsLanding`）与 `agent_workspaces`（`_isolate_agent_workspaces_root`）两格——凭据桶这格没进清单，于是每条起真 app 的用例都在真实数据根留一个空目录。属 §6-29 同一族的**隔离清单缺口**（那次补的是会话，这次是凭据），修法是在 conftest 补同款夹具；登记不顺手改：本轮改动面已含凭据存储，再叠一层共享测试基建改动会让 A/B 归因变浑。
    **按核心原则第 7 条补影响面（这不是"死码"，是隔离清单缺一格）**：接线后实现什么——每条用例的凭据桶落进该用例自己的 `tmp_path`，跑测不再往真实数据根留目录，且"凭据按用户分桶"的语义在测试里第一次真的被隔离（今天多个用例共用仓内 `default` 桶，互相可见）。数据从哪来到哪去——夹具写 `NEUROVA_DATA_DIR`/显式 `base_dir` → `web_reach/credentials.py:63` 的 `callerPath(...)` → `<数据根>/web_reach_credentials/<uid>/`；消费方是 `api/endpoints/settings.py` 六处 REST、`computer_use/{ssh_runner,rdp_provider}.py`、`web_reach/reach.py`。影响面覆盖哪些模块——`tests/conftest.py`（共享基建，全仓 2.1 万条用例都经过它）+ 现有那批凭据/SSH 用例。不接线留下什么——仓内数据根继续长空目录，且任何真去读写凭据桶的用例仍在共享状态上互串（形态与 §6-29 会话落点一致，那次的病灶也是"看着隔离、其实共用"）。改的代价与不可逆点——无不可逆；风险是若有用例**依赖**真实桶路径会当场红，因此须跑宽域（api+web_reach+computer_use）而非只跑本地那一个文件。
    **`b3e44687` 又添一格实证**：通知枚举改接真账号源之后，4 个测试文件共 10 条若不自隔离账号宇宙，就会读到仓内 `data/users.db` 里那个真 admin 并**把通知发给真人**；本轮以共用夹具（`seedAccounts` / `isolateNoAccounts`）逐套件钉住，全局 autouse 那一层仍是待裁项。
36. **敏感件防火墙会吞掉正当测试文件名（本批实测撞上一次）** 🔴 —— `.gitignore:483` 的 `tests/**/*_secret*`（同族 `*.pem`/`credentials*`/`api_keys*`/`.env`，由 `472a0180` 立）把新判据 `test_secretStoreCleanAuthenticated.py` 判成不可跟踪；把它登进 `scripts/ci/protected_tests.txt` 之后 `TestProtectedSubsetEntriesAreTracked` 立刻红，才暴露"文件名撞上防火墙"。改判方向是**给测试改名**（`test_credentialCipherDiscipline.py`）而不是放宽防火墙——豁免通道一旦按"这是个测试"开出，密钥文件也能顺着同一口径进来（AGENTS.md §6）。留给后续一条口径：新测试文件名带 `secret/credentials/api_key/env` 字样前，先 `git check-ignore -v` 一次；这条不是缺陷本身，是踩它的成本。

37. **"敏感记忆落盘加密"这项能力从未被任何调用方走过（需人裁，非死码可删）** 🔴 —— §6-34 闭环时的副产物，比那条本身要紧。取证形态：`encrypt_sensitive_content` / `decrypt_sensitive_content` 在三个版本（`7835c367` pyc 骨架恢复、`33b71a25` 桶层摘链、HEAD）上 `git grep -c` 命中文件都只有定义所在的 `security.py`；`encryption_method` 这个名字**全仓除该文件外零命中**（没有列、没有字段、没有读取方）；`MemorySecurity` 只在 `neurova/memory/__init__.py:108` 被 try-import 后再导出，无人实例化。
    **按核心原则第 7 条给影响面（这不是"删掉就好"）**：
    - 它本来要实现什么：写侧对敏感正文按 `EncryptionMethod`（FERNET/HASH/MASK/NONE）落库前变换，并把所用方法随内容一起记账；读侧按同一方法解回。`_BUILTIN_PATTERNS` 的敏感面覆盖手机号、身份证、邮箱、银行卡（模式表里明写"信用卡号码"）。
    - 数据从哪来到哪去：设计上是 `memory_layer/manager.py` 与 `cognitive_storage_engine.py` 的写入前 / 召回后两道缝，落点是记忆正文列；今天这两道缝直接把原文透传。
    - 影响的模块与端点：`neurova/memory/*`（含 `memory_enhancement` 那批 REST）、`api/endpoints/memory/{crud,working_memory,tkg}.py` 的读回面，以及三层隔离下的记忆归属——**今天敏感正文以明文落盘**，磁盘/备份可读即等同泄露，与 §6-1 身份批"租户隔离"是两回事（那批管的是"谁能看到"，这条管的是"落盘那一刻是不是明文"）。
    - 不接线留下什么：文档与本模块 docstring 继续宣称"加密存储（Fernet 对称加密）"，而线上没有一次加密发生；§6-34 刚修的 fail-fast 也只有在接线之后才真正护到人。
    - 处置选项与代价：① **接线**——要在写入与召回两道缝改，且必须同时把 `encryption_method` 落成一列（schema 变更走 `core/db_migration.py` 的 user_version 注册表，AGENTS.md §3），存量明文记忆需要一次"读-加密-回写"的迁移或惰性升级（同 P0-3 形态），代价是迁移期两种形态并存、判据要双向钉；② **显式放弃**——连同 `_FernetCipher`/`SecurityConfig.default_encryption` 一并退役，并把 docstring 与任何"加密存储"表述改掉，代价是承认该合规能力不存在（若涉及等保/GDPR 承诺，这条要走 `SECURITY.md` 口径而不是静默删除）。
    - 判据已经把这个事实钉成会红的账：`tests/unit/memory/test_memoryCipherFailFast.py::testCipherChainHasZeroCallersAndThatIsPinned` 期望零调用点，**接线或退役都必须来改它**，否则它就是"没人读的注释"。
38. **同形态硬路径落点还有 3 处命中（登记，未改）** 🔴 —— §6-33 修完 `create_admin_user.py` 后按 §5 复扫 `db_path="data/…"` 这类 CWD 相对字面量，仍剩：`scripts/demo_closed_loop.py:54`、`:215`、`scripts/demo_optimization.py:199`（三者都是 demo 落库路径）。同根因、同修法（走 `dataLanding`/`callerPath`），未顺手改的原因有两条且都写出来：① demo 脚本的落点语义本就模糊（演示数据该进数据根、还是该跟着脚本目录？），改了会让"清 demo"的既有操作扑空；② `test_runtime_landing_root` 的扫描面是 `neurova/`，把它扩到 `scripts/` 会一次牵出多批历史落点（§5 说的"命中点扫荡"应当是有判据支撑的整批，不是逐次凑数），这一步需要单独一轮。判据覆盖面的缺口本身已在 §6-33 定性登记。
39. **记忆预算在主链上不吃账：`TokenBudget.memories` 与 `_build_memory_context` 只服务池外分支（需人裁）** 🔴 —— P1-6 活体时撞出来的，比那条本身要紧。取证形态（一次真装配，`use_pool=True`、真 `ContextBuilder` + 真注入器、`init_context_system()` 走 `Agent.__init__` 同一入口）：给 `injector._build_memory_context` 挂探针，跑完 `memory-section calls: []`——**一次都没被调用**；那条 8400 token 的记忆原文整段出现在末条 user 消息（视图第 5 条，9968 字符），而 `TokenBudget.memories` 现值 4000。机理定位在编排器的返回点：池路径自己内联拼视图并在 `orchestrator.py:1615` 就 `return`，`context_builder.build_from_pool`（`:1759`，唯一会走到注入器记忆段的调用点）只在池关闭或降级时才执行；生产默认 `enable_context_pool=True`（`agent_core.py:259`），故**默认配置下这份预算不被消费**。主链的记忆文本改由 `:1444-1452 render_memory_line` 拼进 `blocks["memories"]`，再收进瞬态信封（`:1751`），受 `compress_envelope` 的**确定性淘汰**（整条丢弃）而非按预算裁剪。
    **按核心原则第 7 条给影响面**：
    - 接线（让主链也过这份预算）实现什么：`memories` 这一格从"配置里有、无人读"变成真上限——单条长记忆不再一口吃掉大半窗口（本次实测窗口预算 9600、单条记忆 8400），且淘汰形态从"整条丢"变为"按预算折行"，可注入内容更多而不是更少。
    - 数据从哪来到哪去：`ChatPipeline` 召回 → `build_context(relevant_memories=…)` → `:1340` 归档进池 + `:1444-1452` 渲染 → `blocks["memories"]` → `:1751` 信封 → 模型。注入器那份 `_build_memory_context` 排在同一张图的**另一条支流**上（`:1759`）。
    - 影响的模块与端点：`neurova/context/orchestrator.py`（视图装配）、`neurova/context/injector.py`（预算消费方）、`neurova/context/envelope.py`（淘汰策略）、`context_builder.compress_if_needed`；对外可感面是每轮发给模型的 prompt 长度与成本。
    - 不接线留下什么：`TokenBudget.memories` 继续是"只写不读"的配置（§6-11 同一形态），且 P1-6 刚收口的口径只在池外分支生效——真实部署几乎不跑那条分支。
    - 处置与代价：① **接线**——把记忆段裁剪从注入器提到主链（`blocks["memories"]` 落信封前统一裁），代价是要与 `compress_envelope` 的淘汰顺序重新定约，判据须覆盖两条路径；② **承认分工**——判定"池路径整条淘汰"就是设计，则应把 `memories` 预算与 `_build_memory_context` 显式限定为池外分支专用，并把口径写进 `models.py` 注释（否则下一个读代码的人仍会以为它是全局上限）。两种都要动，静置就是双口径。
40. **受保护子集里有一条常驻红，且它与代码里的设计口径互相矛盾（需人裁）** 🔴 —— `tests/unit/context/test_turn_identity_wiring.py::TestWindowCacheKeyReadsTurnIdentity::test_two_direct_sessions_do_not_share_fold_summary` 在 HEAD 上就红：逐文件单跑 `1 failed, 7 passed`；换干净数据根（`NEUROVA_DATA_DIR` 指向空目录）单跑仍红——**不是本机污染，也不是顺序耦合**。失败断言是"单聊 B 的视图不得出现 A 的内容"，而实际出现在 `<history>` 的 `[历史回忆]` 块（`orchestrator.py:1505`），是同 agent 池的**跨会话语义召回**；同一文件上方 `:1487-1489` 的注释把这件事写成设计："单聊/非协作仅见 direct（**仍跨普通会话召回**），排除任何房间归档"。同一批里"折叠摘要缓存分槽"那条断言（`keys ⊇ {sess-one, sess-two}`）是过的——即 `ecbd226a` 真正修的那件事仍在，红的是它对**召回面**多提的一格期望。
    该文件登在 `scripts/ci/protected_tests.txt:757`，而受保护子集的口径是"逐文件单跑确定全绿"，于是门禁在这一条上**声称跑过而实际是红的**（`ecbd226a` 之后的常驻红，非本批引入）。
    **待拍板（按核心原则第 8 条给决策影响面）**：
    - 选项 A：改判据——承认"普通单聊跨会话召回"是产品口径，把断言收成"折叠摘要与缓存键不得跨会话共用"（这一格已经真绿），删掉"内容不得出现"。代价：单聊之间的语义连续性正式成为承诺；只动测试，不可逆点低。
    - 选项 B：改代码——`filter_by_scope` 给 direct 再加 `session_id` 维度，单聊只见本会话归档。代价与影响面：`neurova/collaboration/memory_scope.py` 的共用规则要改（长期记忆与池召回同用它），"换个会话接着上次聊"的可见内容消失，用户可感；那批作用域用例（`test_pool_scope_wiring.py` 等）需同步改判。不可逆点在用户体验侧。
    - 无论选哪边，先把这条在受保护子集里**如实标注**（按第 3 条纪律：红灯文件不得留在"确定全绿"清单里），否则下一次 A/B 会把它当本批回归。
41. **跑测把测试文本写进仓内真上下文台账（§6-29/§6-35 同一族的隔离清单再缺一格）** 🔴 —— P1-6 的 A/B 之后实测：`data/context_ledger/a1.db` 的 `evicted_chunks` 表里 3 行含测试填充文本"量子计算第0条…"，文件 mtime 与跑测窗口一致，`agent_id`/`user_id` 正是用例里的 `a1`/`u1`。成因与 §6-35 同形：`tests/conftest.py` 的落点隔离覆盖了会话（`_isolateSessionsLanding`）与 `agent_workspaces`，凭据桶缺（§6-35），**上下文台账这格也缺**——台账按 agent_id 分库、启动即读（真启动日志就在打"本库已有 N 条归档（仅登记，不预载）"）。
    **按核心原则第 7 条给影响面**：接线后实现什么——每条用例的上下文台账落进自己的 `tmp_path`，跑测不再往真实数据根留测试内容，"按 agent 分库"的语义第一次在测试里真被隔离；今天多个用例与仓内真库共用，测试文本会像真实归档一样被后续轮次语义召回。数据从哪来到哪去——`orchestrator` 窗口/信封淘汰 → `context_ledger` 的 `evicted_chunks`（含 `session_id`/`turn_id`/`metadata` 列）→ 下次 `ContextPool` 启动读回 → `<history>` 召回块。影响范围——`tests/conftest.py`（全仓 2.1 万条用例都经过它）+ 所有走真编排器的上下文用例；真实侧后果是**用户提示里可能混进测试填充文本**，清理要手工删行（不是删目录了事，库文件本就该存在）。不接线留下什么——A/B 归因继续被"上一轮跑测留下的归档"污染，§6-29 那批判据看着齐了其实漏一格。代价与不可逆点——无不可逆；风险是个别用例若依赖仓内既有台账内容会当场红，故须跑宽域（context+agent+integration）。
42. **`skill_service` 的 read-modify-write 不在 `self._lock` 内（判据已在位，HEAD 上常驻红）** 🔴 —— §6-19 收口时顺带扫到的同族缺陷，形态不同：不是"懒建没锁"，而是**服务层被承诺了并发保护、关键段却没持锁**。判据 `tests/unit/api/test_skill_pool_api_rlock_protection.py::test_skill_service_critical_sections_hold_rlock[install_skill]` 与 `[register_auto_skill]` 在 HEAD 就红（仓外 HEAD worktree 与改动树**两侧同红**，非本批引入），断言原文：`register_auto_skill 必须在 self._lock 内做 read-modify-write（API 层已把并发保护责任交给服务层）`，实测 `assert 'with self._lock' in <函数体>` 落空——这两个函数体里根本没有那把锁。
    **按核心原则第 7 条给影响面**：接线后实现什么——技能池"读当前表→改→写回"这段在同一把锁内完成，两个并发安装/注册不再互相覆盖（今天的失败形态是后写的整表覆盖先写的，先写那条技能从池里无声消失；而 API 层已按"服务层负责加锁"的口径**去掉了自己的锁**，于是两侧都不保护）。数据从哪来到哪去——`api/endpoints/skill*` → `SkillService.install_skill / register_auto_skill` → 池索引与落盘库表 → 再被 `get_skill_registry` 召回消费。影响模块——`skills/skill_service.py` 与其端点面；也和 P2-7 直接接力：注册表收成单实例后，竞争面就从"多实例各写各的"变成"单实例内并发读写"，本条正是下一步。不接线留下什么——该判据长期挂两条常驻红，下一次 A/B 会把它当回归。代价与不可逆点——把关键段包进锁影响吞吐（安装/注册低频，可接受），真正的风险是**锁序**：技能池锁与注册表锁若互相嵌套会造死锁面，动手前要先画出取锁顺序。
43. **`tests/unit/computer_use/test_computer_param_no_phantom_knobs.py` 单跑即超全局 30s 墙钟，整个 `computer_use` 目录跑不完（§6-27 家族的墙钟成本）** 🔴 —— 实测：单文件、无并发负载下跑，第 3 条用例被 `pytest-timeout`（`timeout: 30.0s, method: thread`）击杀，栈停在 `pathlib.read_text`；同一文件在仓外 HEAD worktree 里同样超时，**与代码改动无关**。而手工复算同一份扫描（`neurova/**/*.py` 共 1031 个文件逐个 `read_text`）总耗时远低于 30s、没有单个文件超过 0.2s——卡点不在磁盘 IO，而在判据把"多组正则 × 全量生产源码"逐参数重复跑，累计成本越过墙钟。
    **按核心原则第 7 条给影响面**：修好之后实现什么——`tests/unit/computer_use` 能随全仓跑测跑完（今天只要带上这个目录整轮就被击杀，A/B 只能绕开它，等于这块回归无人守）。影响范围——该目录全部用例 + 任何 `pytest tests/unit` 全量入口。修法与代价：源码文本按目录读一次并在同批用例间复用（或一次遍历跑多模式），代价是判据语义要重述清楚；另一条路是给该文件单独 `@pytest.mark.timeout(120)`，但那只把墙钟抬高、成本仍在。登记不顺手改：与本批锁改造无关，混批会让归因变浑。
44. **已挂载端点每次必 500：手抄响应字段时抄出一个不存在的属性（P2-8 第一批活体踩出，已修 `78abaa2e`）** 🔴✅ —— `POST /api/coordination/yield-checker/check` 在 HEAD 上**任何一次调用都 500**。根因不在业务逻辑而在**响应装配形态**：`api/endpoints/coordination_api.py` 没有用 `YieldDecision` 自带的 `to_dict()`，而是手工逐字段抄了一遍字典，其中一行写 `decision.backoff_round`——这个属性在 `YieldDecision` 全类**从未定义**，全仓也只有这一行提到它（AST 复算过属性集，不是 grep 到了就当存在）。红灯原文：`AttributeError: 'YieldDecision' object has no attribute 'backoff_round'`；活体基线树 5 发全 500，修后同 5 发全 200 且载荷与真实裁决一致。处置形态是 `return decision.to_dict()`（单一事实源，教义第 6 条：响应形状只由数据类自己定义一次），不是给它加 `getattr(..., None)` 兜底。
    **为什么这条比看起来严重**：它是 §6-5 那条链上唯一**对外可见**的格子——规则引擎、注册表、stats 端点全都活着，只有"问一次该不该让位"这条必崩，而崩的形状是 500 而非降级。此前所有轮次都没发现，是因为没有任何用例真打过这个端点（原有测试直接调 `checker.check_operation()` 绕开了 HTTP 面）；这同 §6-27 家族的"绿灯不等于在路上"是一个病灶的两副面孔。登记意义：**"手工抄一遍已有 `to_dict()` 的字段"是全仓可回流形态**，本批只在协作域扫到一处，未做全域扫荡（全域扫需先定义"数据类有 to_dict 而调用点逐字段抄"的判据形态，属另一批）。
45. **并发额度"判一次加一次、只有注册没有注销"——让位闸一旦接线就会把自己锁死（同一批的前置根因，已修 `78abaa2e`）** 🔴✅ —— 接真之前必须先修的账。`GlanceYieldChecker` 的 Layer 2（模型并发上限）在**查询路径**上递增 `_active_operations`，而全类唯一的递减点是 `unregister_agent`，**生产侧零调用方**（`register_agent` 侧也只有被摘链的装饰器调过）。于是同一个 Agent 问 6 次就把该模型的 6 格永久占满，此后同模型的每一发都恒判"让位"——不是限流生效，是账本漏还。实测红灯原文 `active_per_model={'gpt-x': 6}`；活体在 HEAD worktree 上更直接：5 发 check 之后 stats 里 `active_per_model={"gpt-live": 5}`，**且这 5 发全是 500**（§6-44），即一次都没真执行过操作，额度却已耗尽。这条若不先修，P2-8 的接真形态就成了"回合入口装一道闸，第一次重试就把自己的模型锁死"——错误会被读成限流策略在起作用，属最难归因的一类。
    **收口形态（三条，都在 `glance_yield_rules.py`）**：① 查询路径改**纯读**，占位只在 `record_operation_start`、还位在 `record_operation_complete`，同一 agent 重复 start 幂等不重复占；② 加 `ACTIVE_OP_LEASE_SECONDS = 600.0` 租约回收，进程内崩溃/漏还不会永久吃格子（回收在读取前跑，不另起后台任务，避免再造一条无人管的循环）；③ **归因不到模型就不占槽**——被退役的装饰器用 `kwargs.get("agent_id", "unknown")` 取身份，实测注册进 `['unknown','unknown']`，所有 Agent 挤同一个公共桶（那既是限流失真也是隔离面缺失），故闸侧改为按 `session_id + user_input` 派生稳定操作身份（`turnOperationIdentity()`，sha256 前 32 位），拿不到模型归属时明确记日志"本次不占并发槽"而不是塞进公共桶。**判据落点**：`tests/unit/collaboration/test_yieldConcurrencySlots.py`（4 条）已入受保护子集。
46. **让位闸与 run 台账只覆盖 `/console/chat` 这一条回合入口——另三条未接（教义第 5 条命中点，需人裁）** 🔴 —— 接真时按拍板"闸放回合入口一次"落到了 console 的流式分支，但"回合入口"在仓内**不止一个**：`channels/channel_router.py:154`（飞书/钉钉/Telegram 等渠道消息真跑一轮）、`api/endpoints/chat.py:183`（`/v1/chat` 非流式）、`api/endpoints/chat.py:291`（`/v1/chat/stream` 遗留流式面）三处都直接 `agent.chat(...)`，既不问让位闸、也不在 run 台账留行。另有一格如实记录：`/console/chat` 在 `get_agent_instance` 拿不到实例时落到 echo 分支（`console.py:737`），那条分支不调 LLM，接不接闸代价为零——活体第一版就是打在 echo 上才暴露出"types=['chunk','done'] 却没有 parked"。
    **按核心原则第 7 条给影响面**：接上之后实现什么——渠道侧与遗留 API 面的每一轮同样受并发/间距/限流/冷却约束，且超限后同样有一条可审计、可人工续跑的 run；数据从哪来到哪去——三条入口 → `agent.chat` → `ChatPipeline`（这条已共用）→ 会话落盘；影响范围——`channels/`（全部适配器）、`/v1/chat*` 两条公开 API、以及它们各自的测试面。不接留下什么——限流规则对网页面生效、对渠道面恒不生效（同一份额度被两条路各花各的），且渠道侧超载时没有任何"挂起等人"的形态，只有静默排队或直接失败。**为什么本批不动**：渠道面没有 SSE，park 的"立即收尾 + 人工续跑"需要先定一份渠道侧的挂起话术与续跑触发口（谁点、在哪个界面/命令点），属产品裁决而非缺陷修复；`/v1/chat` 那条还与 §6-6 的签名断裂同族（形参不接受即抛 TypeError 折成 500）。代价与不可逆点——把闸接进渠道会把"等待最多 200s"变成用户可感知的延迟（渠道消息回复慢会被当成掉线），接之前要先把等待期的用户反馈设计好。
    **2026-10-07 第三批闭环（`d4c8b560`，用户拍板"全量接：接闸 + park 复用台账"）**：三入口都接上了，且做法是先收口再接线——台账执行体与"问闸→挂起→落库→构造回包"从 `console.py` 抽成唯一实现 `neurova/core/agent_run_ledger.py`（`AgentRunLedger` / `requestTurnAdmission` / `reportAdmissionOutcome` / `resumeTurnIdentity`），四入口全部改指它；结构守卫钉住"闸口调用点全仓只许一处""台账类不得住回 console""三入口必须 import 那份实现"。挂起按各面本来的样子回：网页发 `parked` SSE、渠道回一条**带 run_id 的诚实回执**、非流式 API 回 `message:"parked"`（它原先回 `{"code":0,"message":"success","data":{"reply":…}}`——没跑的一轮被报成答完了，本批最硬的一条就是它）。载荷带 `entry`，续跑按 entry 回**原入口**重建请求。活体三证：`/api/v1/chat` 超限 `status=200 message='parked'`；渠道行 `parked` 且 `user_id` 是 agent 属主、回执文本含该 run_id；拿这个 run_id 打网页那条 `/console/chat/resume` 得 `status=200`（渠道挂起的回合确实能在网页续）。**留下的两处边界（如实，不算已闭环的部分）**：① 渠道续跑后的回复只写进会话，**不会再推回渠道**——回执文本按这个事实写，要做渠道回投需给 run 行加投递坐标，属另一小批；② 不带 `session_id` 的 API 调用**不记账**（凭空造一条共享泳道会让这些请求互相排队，那是接线造出的新阻塞面）——闸**照样问**，但挂起时无处落库，只能如实回 503 / 发 `error` 事件，绝不回一个"已挂起"糊弄过去。
47. **`evolution/eval/miner.py` 的模块注释声称源 A 是 `agent_runs`，实测全文件对该表零读取** 🔴 —— `miner.py:3` 写着"源 A:`core/agent_run_store` 的 agent_runs(真实任务 + 状态)"，而该文件里除这一行外没有任何 `agent_runs` / `agent_run_store` 引用（AST 与 grep 双查，`SELECT` 面也没有）。于是"评估挖矿吃真 run 台账"这句话在代码里没有对应实现——本批新增的 `parked` 状态自然也不会被任何评估面读到。属 §6-14（文档虚报集成完成）同族：口径写在 docstring 里、实现从未跟上，读的人却会按它判断"挂起的回合进不进指标"。**处置建议**：要么把源 A 真接进 miner，要么把该行改成"计划中/未接线"——二者都由该模块 owner 裁，本批不动（改注释不解决问题，改实现属另一批）。
48. **前端两条 HEAD 常驻红（本批 A/B 中归因，非本批引入）** 🔴 —— ① `NeurUI/src/tests/duplicate-function-inventory.guard.test.ts` 以 **0 test 失败**形态红：vitest 导入 `scripts-qa/duplicate-function-audit.mjs` 即抛 `SyntaxError: Invalid or unexpected token`，而 `node --check` 与该脚本直接调用（`auditDuplicateFunctions()` 实跑打印 `tierAGroups:0, variantBodyGroups:96, scannedFiles:326`）都正常；归因用"只含一行 import"的探针文件复现——与被扫源码内容无关，故不是本批新增的 `sseJsonEvents`/`parkedNotice` 造成。② `NeurUI/src/modules/collaboration/__tests__/canvasEdgesStyle.test.ts::悬浮层（提示行/缩放栏/小地图）位于 transform 容器之外` 同样在 HEAD 红，本批未碰 canvas CSS。两条都按基线既有失败处置：不摘文件、不改判据、在本报告如实标注；①修法是让该守卫别在 vitest 里直接 import `.mjs`（改走子进程调用或把口径函数落进 `.ts`），属独立一小批。
49. **`EventBus.publish` 对 async 订阅者是"无队列即静默丢弃"，且不留痕（A 轮接线后才成为承重路径，需人裁）** 🔴 —— `core/event_bus.py:189-201`：订阅者若为协程函数，只有 `self._async_queue` 存在时才入队，队列由 `start()`(:78-91) 在**有运行中事件循环时**才创建；否则直接 `continue`——不执行、不计数、不打日志。`_async_queue_full_dropped` 那个计数器只在"队列满"时递增，"根本没有队列"这种形态连计数都不进。为什么现在才咬人：A 轮之前没有任何生产订阅者（恒空所以恒对），而本批接上的 injector 三条 handler 全是 `async def`（`_handle_build_request`:1169 等），于是"订上了"与"收得到"之间新多出这一格。实测影响面：`publish()` 在无 loop 的上下文（同步脚本、启动早期、单测直调）发出的事件，对 async 订阅者**必然静默消失**；在请求循环内则正常。可选处置三档——① `publish` 遇无队列时改为 `logger.warning` + 计数（诚实暴露，不改语义，最小）；② 让 `start()` 在无 loop 时也置一个"异步不可用"标记，`publish` 据此显式抛错或降级为 `asyncio.run`（改语义，风险大）；③ 把订阅端 handler 改同步（回到 A2 的判据形态"async 声明必须有 await"）。**本批不动**：①③都可接受但需要产品口径（这类事件到底是尽力投递还是必须投递），且 A3 的 MEMORY_*→缓存失效会直接踩到它——A3 开工时必须一并处置，不能只测"在 loop 内"的那条路径。
    **2026-10-08 闭环（`e3cd82cc`，取 ①+② 之间的最小诚实形态）**：`publish()` 无队列分支不再静默 `continue`，改为 `self._async_no_queue_dropped += 1` + 节流告警（1/100/1000/10000），新增读口 `droppedAsyncCount()`（无队列 + 队列满两种丢弃都计）与 `publishedCount()`。**语义没改**（仍是尽力投递、不抛错、不降级为成功），改的是"丢得看得见"。同批把 `self._published += 1` 挪进锁内——`+=` 是读-改-写三步，GIL 不保证跨字节码原子；这条不是我推出来的，是改判过来的并发判据 `test_concurrent_emit_count_accurate`（20 线程 × 200 发）在改前把计数精确性抓红的（"计数守卫逮住自己人"的又一例）。判据 `testAsyncSubscriberLeavesATraceEitherWay` 写成不变量"要么被执行、要么记为丢弃"，不写环境依赖分支（否则无 loop 时静默空转、有 loop 时恒过）。
50. **两处"只写不读"的总线取用面（与 §6-12 同族，登记未改）** 🔴 —— ① `api/deps.py:175 get_event_bus()` 是 FastAPI 依赖形态的总线取用器，全仓**零 `Depends(get_event_bus)` 消费者**（实测），且它把取用失败 `except Exception` 折成 503 并 `logger.error`——一个无人走的入口还自带降级语义；② `shared_core/infrastructure.py:190 get_event_bus()` 返回 `self._event_bus`，该字段是否有装配来源未取证（若恒 None 则同样是空转门面）。二者与 `memory_layer/manager.py:832` 那个零调用方的私有总线出口同形：写出无人读的取用面。按 AGENTS §2「写出无人读的字段、注册无消费者的模块均属断点，必须接线或删除」——**处置需人裁**（接进真消费者 vs 连同其 503 语义一并退役），本批不动，避免与 A3 的总线合并搅在同一次改动里让 A/B 无法归因。
51. **注入器"上下文缓存"与记忆流水账都是零写零读的面（A3b 接线时当场验出，需人裁）** 🔴 —— 本批原计划把 MEMORY_UPDATED/DELETED 接去"清 `UnifiedContextInjector` 的上下文缓存"，读码后发现接无可接：`cache_entry`(:1103) 与 `get_cached_entry`(:1115) **全仓零调用方**（`neurova/` 与 `tests/` 都无人调，实测 grep），那张 LRU `_cache`(:135) 既不写也不读，`on_stop` 里 `_flush_cache()` 清的是一张恒空的表。接上去**判据会绿、闭环并不存在**（教义第 2 条禁止的表面抹除），故撤回该形态，改为钉"记忆写入须能在现役 HTTP 读面 `/api/v1/logs` 上看到"（`logs.py:72/106` 走 `get_event_log()`，前端 `NeurUI/src/api/modules/system-logs.ts:29` + `config/navigation.ts:73` 真在用）。同族第二格：`memory_layer/memory_stream.py` 的 `record_event/record/get_stream/get_recent/get_stats/export_json` 一整套"事件→账本"面，除模块内自己的单例工厂 `:227` 外**零生产实例化、零读取方**。两条都是"模块是对的、缺的是消费方"（§3-C 档形态），要则接线（缓存须真被 `build_context` 使用、账本须有读面）、不要则连同其测试与 i18n 一并退役——**删即失去"上下文装配可缓存"这项能力**（本仓唯一实装），按 dead-code 流程一律走人裁，不在简化批次里当可删项。
52. **惰性导出判据的前提符号已被退役（HEAD 常驻红，改判需人裁）** 🔴 —— `tests/unit/cognitive_layers/memory_layer/test_torch_lazy_import.py::test_lazy_attribute_access_still_works` 在 HEAD 就红（基线仓外 worktree 与本树**两侧同红**，非本批引入）：断言 `from neurova.cognitive_layers.memory_layer import MemoryFieldConfig` 可用，而 `class MemoryFieldConfig` 在 `0c333a76`（温度衰减双实现收敛 + 清退 5 组死码）里已整体不存在，包 `__init__` 也不导出。这不是产品缺陷，是**判据陈旧**——但"惰性导出契约还该不该覆盖 memory_field 那组符号"等于替该能力做存续裁决（同文件另两条 `test_import_submodule_does_not_load_torch`、`test_missing_torch_fail_soft` 是真在防 torch 白拉 +176MB 的活判据，必须留）。故不擅自改判到别的符号：按 §6-40 的既有处置形态，就地当基线既有失败对待、A/B 时不计回归，改判方向由人裁（改判到现役符号 / 连同那一条断言一起退役）。
53. **跑测会在仓内真会话落点改写真实用户文件（§6-29/§6-35/§6-41 同族的又一格）** 🔴 —— A/B 期间实测：`data/sessions/kai/session_kai-dialog-20260509_2026-10-08.json` 与同目录 `_summary_index.json` 的 mtime 落在跑测窗口内（01:28-01:30），`data/sessions` 文件数 207 → 208。**不是我本批的判据写的**：单跑本批新增的 `test_memoryEventsReachLogsEndpoint.py`（启真 `create_app()`）前后，`data/sessions/kai/_summary_index.json` md5 仍 `60f9e0ae94983eb9f68e24aa0f51cbc9`、文件数仍 208、`data/` 近 3 分钟无改动，故锁定来源是大选择集里既有套件。根因与 §6-41 同形：`tests/conftest.py:38` 的 `setdefault("NEUROVA_DATA_DIR", DATA_ROOT_SESSION_DIR)` 把默认数据根就设在**仓内**，`_isolateSessionsLanding`(:160) 只覆盖 SessionManager 构造期这一条路径，真实 agent 目录（`kai`/`yi_ling`）被启动链按别的取数口写入。后果比"脏仓库"更硬：**改写了真实用户的会话文件**（`kai` 是本仓在用的人）。修法是把这类落点也收进 conftest 隔离夹具（同 §6-29 已成立的两层形态：默认隔离 + 收尾守卫），或在装配期钉死"测试进程不得写仓内真会话根"；本轮只登记（改共享夹具会让本批 A/B 归因变浑，与 §6-35/§6-41 同一取舍）。
    **2026-10-08 实测更正（本条的根因判断不成立，D1 的删除前提随之作废）**：上面那句
    "`tests/conftest.py:38` 把默认数据根就设在**仓内**"是**读错代码**——现值
    `DATA_ROOT_SESSION_DIR = Path(tempfile.mkdtemp(prefix="neurovaDataRoot-"))`（:37），
    `setdefault` 注入的是**系统临时目录**，生产默认仍是仓库 `data/` 但测试进程拿不到它。
    落点实验复算：对 `data/` 全树取 (mtime_ns, md5) 指纹（3054 个文件）→ 跑
    `tests/unit/session + tests/unit/core/test_session_manager.py + tests/integration`
    （628 条，含会话落点那一族）→ 复取指纹，**changed = 0**。
    即：现行套件不写仓内 `data/`；本条原先描述的"跑测改写真实用户会话文件"这一机制
    **没有复现**，那条 01:28-01:30 的 mtime 变动因此是**未归因**事件（同一窗口内并发会话
    在跑真 app 与其活体探针，`agent_workspaces/kai/...` 同时被改动是旁证），
    不能记在跑测头上。**登记的教训**：一条"根因"如果只在 mtime 窗口上成立、
    没有做过 before/after 内容指纹复算，就必须标成未证实——本条正是这么补的，
    而它原本的写法（"根因与 §6-41 同形"）把猜测当成了结论。
    **由此 D1 的处置改向**：见 §6-65（那些文件绝大多数是**未跟踪且 gitignore** 的真实
    用户数据与历史存档，删除不可恢复；分类不能靠文件名，须逐族取证后由人裁定）。
54. **角色门与严格门共用两份身份解析（C1 想顺手收口时当场撞红，需人裁）** 🔴 —— C1 要把"记忆面只留两个门"坐实，`memory_settings_api.py` 的读侧门从 `api/deps.get_current_user` 换成 `api/auth.get_current_user` 后，同一文件三条写端点全塌：`require_admin()` → `deps.py:280 require_role()` 内部 `Depends(get_current_user)` 指的就是 **`deps` 那份**（`WithQueryToken` 的再导出），`dependency_overrides` 按对象生效，于是 6 条既有判据当场 401。也就是说"只留两个门"要真成立，必须把**角色门的身份源一起收口**。代价实测：`require_admin`/`require_role` 全仓 **73 处命中**、约 **20 个测试文件** override 的是 `deps` 路径（`grep -rln "from neurova.api.deps import.*get_current_user" tests/`），且收口后这些端点不再接受 `?access_token=`（浏览器下载类链路要先清点）。两条处置各自成立的条件：**A** 收口 `require_role` 到严格门（安全面收窄：token 不再进 URL 与访问日志；一次改动 73 处，A/B 面极宽）；**B** 维持双源并把"记忆面允许的门"闭集判据的作用域写死在 `endpoints/memory/` 包内（现判据就是这个口径，`memory-share-groups`/`memory-timeline` 那两个零调用方入口不受影响）。本批按 B 落地并**回退了那一次 swap**，不静默遗留故登记于此；A 何时做需人裁（它与 §9 序 11「鉴权 7 定义单源化」是同一条链，不宜拆着做）。
55. **HEAD 自带两条红：`_FakeMemoryManager` 落后于被测端点契约** 🔴 —— `tests/test_api/test_memory_route_shadowing.py::test_get_memory_detail_returns_200` 与 `::test_get_unknown_memory_returns_structured_404` 在 HEAD 即红（仓外基线 worktree 与本树**两侧同红**，非 C1 引入）：`crud.py:259` 走 `manager.get_memory(...)`，而该文件的替身 `_FakeMemoryManager`(:61) 只实现了 `storage.get()`，报 `'_FakeMemoryManager' object has no attribute 'get_memory'`。形态与 §6-52 同族但成因不同——那条是**前提符号被退役**（判据陈旧），这条是**替身没跟着生产契约走**（判据仍有效、夹具过期）。修法很小（替身补一个 `get_memory()`），但它是别人批次的遗留且与本批根因无关，按教义第 5 条"同根因扫荡"的边界不混入 C1，登记待处置。
56. **常驻守卫 HEAD 红：`tests/manual` 新脚本写死开发机绝对路径** 🔴 —— `test_dev_path_and_runtime_dep_guards.py::TestNoHardcodedDevMachinePaths::test_no_dev_repo_path_in_tests` 现红，命中两条：`tests/manual/pending_hints_session_fence_live.py:19` 与 `tests/manual/tool_round_replay_limit_exit.py:15`，均在 docstring 的"一条命令复现"里写了 `PYTHONPATH="E:/项目/Neurova"`。来源不是本审计会话（`git log` 归到并发会话的 `8d9a459e`/`1cc26b47`）。守卫要防的正是这件事：脚本换机器/换 checkout 路径即不可复现。修法是把复现行改成相对写法或走 `tests/repo_paths.py` 的 `REPO_ROOT` 派生；本批未代改他人判据，登记以免无人认领。
57. **`/api/v1/chat/history` 两条端点从来没工作过（✅ 已闭环 `d9224d52`）** 🔴 —— 本会话开工时把它记成"跨租户可读"，复核实状后**该描述作废**：两条 handler 调的是 `agent.get_conversation_history()` / `agent.clear_conversation_history()`，而这两个名字全仓只出现在那四行里、**没有任何实现**（`git log --all -S "def get_conversation_history"` 零命中，来源 `7835c367` 的 pyc 骨架恢复）。`hasattr` 恒 False ⇒ GET 对任何人恒回 `{"history": []}`、DELETE 恒回 `{"code": 0, "message": "History cleared"}` 却什么都没清。真实缺陷是"门挂着、数据恒空的空转端点 + §6-8 族的假成功"，不是越权（读不出东西也就读不走东西）。修法与处置形态见 §9.1 的 `d9224d52` 行；留下的边界：`DELETE` 现为显式 501，因为 `session_repository` 只有 `delete_session`/`delete_round`，**没有**"清空一个会话的持久消息"这一格，补它等于新增一条不可逆写路径且当前零调用方（→ §6-60 人裁）。
58. **`/api/v1/sync` 会话面六格身份/归属缺失，其中三条原本匿名可达（✅ 已闭环 `2ca1bfc1`）** 🔴 —— C2 的同根因扫荡扫出（AST 复扫"取 `session_id` 却不做归属比对"：全仓 25 条带 `session_id` 的路由中 11 条无归属校验，逐条读码分类）。本文件 6 格：`GET /sessions/{id}`（外人读 `user_id`/`agent_id`/`conversation_id`/渠道清单）、`GET .../history`（**他人消息正文全量返回**）、`POST .../messages`（把消息写进他人会话并经 `broadcast_event` 推送到其**活动通道**）、`DELETE /sessions/{id}`（**无身份依赖** ⇒ 匿名可结束任意会话）、`GET /sessions`（**无身份依赖** + `user_id` 是调用方可指定的查询参数 ⇒ 匿名按用户名拉整张会话表）、`GET /connections`（**无身份依赖** ⇒ 匿名枚举所有在线 `session_id`，等于把其余四条的 id 来源也送出去）。"匿名"不是理论风险：`NEUROVA_GLOBAL_AUTH` 未设时 `get_global_auth_mode()` 回落 `MODE_OFF`（`global_auth.py:61-63`），兜底中间件不在路上。该 store 与 chat 会话**共用 id 命名空间**（`chat_pipeline.py:558-563` 用 `ctx.session_id` 调 `register_or_create_session`），所以不是隔离的内部面。修法：归属比对**转交** `console.py:_check_session_ownership` 那份唯一实现（`/connections` 走 `manager.list_sessions(user_id=...)` 那道已有过滤，均不在本文件写比较式），身份口径与本文件已修的 S-03 两处（`create_session:286`、WS:133-143）同形——**那一条口径本来就存在，本批只是把它接到自己漏掉的半张面上**。
59. **`SessionSyncPage.vue` 调两条后端从未注册的路径** 🔴 —— `NeurUI/src/pages/SessionSyncPage.vue:150` 打 `POST /sync/sessions/{id}/message`、`:157` 打 `POST /sync/sessions/{id}/close`，而 router 里的真实形态是 `POST /sessions/{session_id}/messages`（复数）与 `DELETE /sessions/{session_id}`——**两条路径都命中不了**，实测恒 404。与 §6-12 那族 `system-logs.ts:39`「原写 `POST /logs/clear` 从未注册过路由，LogPage 的「清空日志」实测恒 404」同形。另有形态错配：`:119` 按 `SyncSession[] | {data: SyncSession[]}` 解，而服务端回 `{total, sessions}`。该页在路由表里有（`router/index.ts:299` `collaboration/session-sync`）但**不在导航里**（`config/navigation.ts` 无入口），所以只有直连 URL 才会撞上。不在 §6-58 同批改的原因：那是前端契约根因，与本批的身份/归属根因不同链，混做会让 A/B 无法归因。**待点单**：接线（前端改指真实两条）或显式退役该页。
60. **sync 列表与在线连接面「管理员全量可见」被删，需人裁** 🟡 —— §6-58 修法把 `GET /sessions` 的过滤器改为**只取 token 主体**，`user_id` 查询参数被删除而非"保留但校验"。理由：判断"你能不能看别人的"需要角色口径，而仓内角色口径只有一处定义（`agent_access.py:30` 的 `if role == "admin"`，且它包在 `can_access_agent` 里、不是可独立调用的谓词），在 sync 面写 `current_user.get("role") == "admin"` 就是新造第二份——正是 §5 共性二/§6-54 反复收口的形态。**代价如实写明**：管理员/运维此后从这个面看不到全量会话与在线连接了。两条后续处置：A 把 `agent_access` 抽出一个共享的 admin 谓词再接进这两条面（与 §9 序 11「鉴权 7 定义单源化」同链，宜并批）；B 给该页配一个 admin-only 的运维视图。§6-59 那条前端形态问题会在 A/B 之前先暴露给使用者，两条建议同批裁。
61. **`GET /api/v1/context/{agent}/composition` 同类但低危** 🟡 —— `context.py:365` 取 `session_id` 不做归属比对，读的是 `context/composition.py:349 get_last_composition`，兜底路径才走 `get_session_repository().get_history`（`:363-366`）。泄露面是"按角色计数的 token 和"与会话存在性（404 vs 200），**不含消息正文**，且结果会被缓存。同根因、同修法（转交唯一归属谓词），但属另一条读面链；本批未动以免把"正文泄露"与"计数泄露"两种风险混成一次改动。待点单。
62. **`POST /api/v1/phase3/hooks/session-started` 的 `user_id` 来自查询串而非 token** 🟡 —— `phase3_api.py:331` 把 `user_id` 做成 query 参数直接喂给 `cost_ledger_integration.on_session_started`（`:48-63`），于是任何人可以**替任意用户**记一笔 `session_started` 花费。这与 §6-58 不同根：那不是"没比对会话属主"，而是"归属声明可被伪造 + 该走 admin 门却没走"（同文件 `:42` 有 `_requireAdmin` 先例）。同族的还有 `publish_event`(:134) 的 `session_id` 只是 outbox 事件上的标签字段（**不构成**越权读，不在 §6-58 清单内）。待点单，建议与 §9 序 11 一并裁。
63. **记账更正三条（并发会话重写历史所致，非缺陷但会误导下一轮）** 🟡 —— ① 本会话 C2/C3 的两格子集登记（`tests/unit/api/test_chatHistorySingleSource.py`、`tests/unit/sync/test_sessionSyncRestOwnershipGate.py`）一度随并发会话的 E 批登记 commit 一起进了 HEAD，随后**并发会话重写历史**（那笔 E 批登记 commit 的号在十几分钟内换过一次，新版只含它自己的 +3 行），于是我的两格从 HEAD 里消失、只留在工作树，`git log -S` 对这两个文件名**零命中**。台账守卫 `test_auditLedger_hasNoUnreachableReference` 恰好把那个已被替换的旧号判红，才把这件事暴露出来——**只查"对象是否存在"发现不了重写，必须查可达性**（`a31851e2` 那条守卫的老教训复现一次；本条刻意**不写那个旧号**，写了就是一条悬空引用）。处置：两格由本会话**单独重新入库**（`2df0d958`），不再借他人 commit——子集登记各批自己带路径单落一笔，才是可归因的形态。② A/B 基线一度取的是**过期** worktree（`@ 750395e2`，早于 C1 三笔）；那一轮"26↔26 差集为空"因此不作数，已重建到当时 HEAD（`d636e366`/`6ca9b4e5`）复跑。判据是：仓外基线 worktree 必须**每次开工现建**，留着复用到下一批就会拿到旧 HEAD 的红绿。③ **台账格号与已入库 commit 正文差一格**：`2ca1bfc1` 正文写"前端从未注册那条另登 §6-58""管理员全量可见已登记 §6-59"，而落账时因 §6-57/§6-58 先占位，实际编号是 **§6-59（前端从未注册的路径）** 与 **§6-60（管理员全量可见）**。commit 已入库改不了，且其上已有并发会话的在途 commit——为两格号去 rebase 他人历史不值当，故勘误写在这里，不默默留错。**读 commit 正文里的 §N 时以本台账现号为准。**

64. **子进程文本捕获不显式指定 encoding：全仓 61 处命中，其中一处使守卫从未运行（✅ 第 2 格已闭环 `aff4ec6b`，余 60 处需人裁）** 🔴 —— `subprocess.run(..., capture_output=True, text=True)` 不给 `encoding` 时，父进程按 `locale.getpreferredencoding()`（本机 **cp936**）解子进程写的 UTF-8 字节。实测三种形态，危险度递增：① 输出全 ASCII → 侥幸没事；② 全仓收集那一发 1.65MB 输出 → `proc.stdout` 被**静默置成 None**，`proc.stdout + proc.stderr` 当场 `TypeError`（同一调用改回 bytes 模式立刻拿到 1648378 字节的正常输出——坏在解码层，不在子进程）；③ 非 ASCII 恰好能凑成合法 cp936 序列 → **不报错，内容被替换**，断言照跑、读的是脏文本。
    第 ② 态把 `tests/unit/core/test_whole_repo_collection_errors.py` 的两条主断言变成 **2 ERROR at setup**，也就是「全仓收集零错误」这条守卫**从来没咬过**；文件里唯一真跑起来的是最便宜的那条反证（造死导入文件必须被点名），于是它一直维持着「这个文件是活的」的假象。修法与新增的运行性前置判据见 `aff4ec6b`；修后实测 `4 passed in 63.76s`，全仓 **21690 条、零 ERROR collecting、rc=0**——收集卫生本身是好的，坏的只是看门那双眼睛。
    同根因第 1 格是今天早些时候的 `test_pip_audit_gate`（Windows 上红，同样是子进程 stdout=None、GBK 解码失败）。AST 复扫谓词取「`Call(func=Attribute(subprocess.run / check_output / Popen))` 且带 `text` 或 `universal_newlines` 且有捕获、但关键字里没有 `encoding`」，全仓 **61 处**：`tests/` 35、`scripts/` 21、`neurova/` 5。**本批只修被证明「判据从未运行」的那一格**，余 60 处不盲扫的原因：逐处补上 encoding 后，凡断言里比中文/绝对路径的都可能从「假绿」翻成「真红」，那是另一轮改动面与另一轮 A/B 归因，混进来会让本批说不清「红是哪一条带来的」。**待裁的两种处置**：A 按目录分批扫净（建议先 `scripts/ci/` 与 `neurova/`——那两处是产品与 CI 路径，脏文本会直接进判定）；B 加一条只降不升的形状棘轮（新落点必须带 encoding，基线 60 条冻结），先止住增长再逐批消化。两者不冲突，B 的成本低得多。

65. **`data/sessions` 历史件清理（D1）——删除前提已随 §6-53 更正而作废，改为人裁** 🔴 —— 原计划"只删探针族 ≈25 个 + 同批处理索引/时间线指向 + 加防再生判据"，三件事逐一复算后都不成立或已成立：
    ① **不可恢复**：`git ls-files data/sessions` 为 **0**，且 `.gitignore:284` 的 `/data/` 整目录豁免——这些文件既不在版本控制里也没有暂存副本，删掉就是真没了。本仓第一条纪律（不可逆动作先取证再确认）在这里直接适用。
    ② **动它们的理由没了**：登记时的依据是 §6-53"跑测改写真实用户会话文件"，而该条根因已被实测否证（conftest 注的是系统临时目录；628 条用例前后 `data/` 全树 3054 个文件 (mtime_ns, md5) 指纹 **changed=0**）。也就是说这些是**历史存量**，不是持续在生成的垃圾。
    ③ **防再生判据早已在场**：`tests/conftest.py::_guardSessionLandingIsIsolated` + `tests/unit/test_session_landing_guard.py` 钉的是**装配点**（单例 `_sessions_dir == <repo>/data/sessions` 即红），取向正是"目录内容判据不可用，要么太贵、要么退化成看不见原地改写的清单差集"。②的那次指纹实验等于给这把锁做了一回来复验，无需再造第二条。
    现存 208 个文件的分布（按文件名形态，只读统计，未处置；计数取自本轮目录实测）：
    - **形态可判定为探针/夹具残留：共 31 件**。① agent 目录名就是探针名的五个目录
      `elapsed-probe-01/`(4)、`loop-probe-01/`(4)、`loop-probe-cli/`(4)、`test-agent/`(1)、
      `test_agent/`(1) 合计 **14 件**，会话 id 直接写着 `elapsed-probe`/`probe-session`/
      `probe-cli`；② `default/` 里非影子的 **8 件**（`shared-sid`、`sess-bob`、`sess-d2`
      各 1 + `led-c{1,2,3,5,6}.jsonl` 5）；③ `kai/` 里像夹具字面量的 **9 件**
      （`sess-<单字母>` 7 + `test-kai-model` 1 + `shared-sid` 1）。
    - **不可由文件名判定，须逐族取证**：`kai/session_kai-dialog-*` 47 件（真人长期对话，
      跨 2026-05→10）、`kai/session_kai-legacy-*` 约 40 件、`kai/session_kai-history-*`
      11 件（像是导入的历史）、`yi_ling/session_auto-<hex>` 50 件（`auto-` 前缀既可能是
      渠道自动建会话的正常产物，也可能是某批探针）、`a1/session_<uuid8>` 10 件。
    - **易被漏掉的一处连带**：每个 agent 目录下还有 `_summary_index.json` 与
      `_timeline/*.jsonl` 两类影子文件，按 id 指回主文件。删主文件不删影子，就是 §6-29
      记过的"FTS 影子行与主表脱节"同形问题——真要清理必须同批处理指向，
      不能只删 `session_*.json`。
    **建议**：① 若要清，先只动那 **31 件**（且先复制到仓外归档再删，给一次反悔窗口），
    `kai-dialog`/`kai-legacy`/`kai-history`/`yi_ling auto-*` 一律不动；② 或者就地不动，
    只把这条标成"已知存量、不再生成"。两种都比"按名字猜着删 208 件"好。
    **这一条不执行，等人裁**——理由见上面 ①②③：不可恢复、动它的依据已被否证、
    防再生另有在着的装配点判据。
66. **`tests/manual/` 收集拦截层不该退役（E1 的前提被推翻）** 🟡 —— 原计划把约 21 份活体脚本改成"不在模块顶层改 `os.environ`"，然后**退役** `tests/manual/conftest.py` 的两道拦截。读码与复算后前提不成立，三条：
    ① 拦截层不是 consumer-side guard，而是**收集期根修**。这些脚本的正确形态是"直跑"（`python tests/manual/<name>.py`），必须在 `import neurova` **之前**改环境；被 pytest 导入就是事故——变量带进整个跑测进程，无声掩盖一切依赖数据根的判据（本仓实测掩盖过一次会话落点守卫）。把"事故"的成因归到脚本、然后去掉拦截，等于把防护换成运气。
    ② 两道拦截各堵一条路径，且第二道是被实测逼出来的：默认收集靠 `python_files = ["test_*"]` 挡；**显式点名**时 `pytest_ignore_collect` 在 pytest 9 对命令行直接给出的路径**不生效**（实测仍被收集，而收集即导入，钩子回来已太晚），所以必须在 `pytest_configure`（收集之前）`UsageError` 拒绝。退役它，`pytest tests/manual/x.py` 就重新变成污染全进程的入口。
    ③ 就算脚本全部改造完，仍要靠"导入顺序"这件事本身——顺序错了照样污染，而拦截层是唯一**不依赖脚本自觉**的那道。文件里还留着一条已踩的坑："比较一律用 `Path`，Windows 下 `str(path)` 带反斜杠，字符串 `tests/manual` 永不匹配"。
    **改判后的 E 档实际待办**只剩一件，且与退役无关：**止住增长**。AST 复算"模块顶层
    （含顶层 `if`/`try` 体内）改 `os.environ` 或调 `setdefault/update`"的现值是
    **22 份文件 / 32 处**——比 `tests/manual/conftest.py` docstring 自记的"21 个文件 27 处"
    **多 1 份 5 处**，即那条口径本身已经漂了（这正是本仓反复要求的"计数型描述落库前本轮
    自己量一遍"）。要加的是对**新增**脚本的只降不升棘轮（新脚本出现顶层 env 改写即判红，
    并提示走 `_liveVerifyIsolation` 的单点），而不是回头改老脚本。
    另外 E2 那一格（其余导入期 env 族 + 棘轮）与 §6-64 的 60 处 encoding 命中是**同一次机械改动面**，建议并批处理，见该条的 A/B 两种处置。

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
| 3 | **缺陷批**：§6-1 memory 越权面 ✅、§6-2 回滚幻影 ✅、§6-5 缺 await ✅、§6-4 假存根 ✅(`b3e44687`)、§6-3 空转上报端点 ✅(`f76677b5`)、§6-6 假委托+签名断裂（部分） | ≈0 | 五条已逐条先立红灯再修（跨用户隔离、落盘失败须回滚、碰撞须拒）；§6-1 的图证与五条红灯见 [`memory-isolation-2026-10-05.md`](memory-isolation-2026-10-05.md)，余下按 §6 清单续排 |
| 4 | A 档"骨架恢复引入且从未接线"批：`llm/client.py`、`config_resolver`、`config_console`、`context_cache`、`context_persistence`、`voice_adapter`、顶层 `context.py`、`collaborate/{models,template}` | ≈2400 | 同批改 `test_refactor_imports.py` 兼容钉与两处 docs 悬空指向 |
| 5 | A 档"换代残留"批（cognitive_layers 八件 + 三套 plan_orchestrator + 三套 ConfigManager） | ≈4200 | 逐条核 `protected_tests.txt`；**先裁睡眠三套归属**（A9 与 B5 有耦合） |
| 6 | A 档"消费方被摘后残留"批：`plugins`、`media`、`language`、`cognitive` | ≈2700 | pyyaml 守卫须**改指**而非删 |
| 7 | 安全实现批：`mcp_manager`+`schemas`（含 shell 门闭环）、`emotion_adapter` 假成功、~~`secret_store_clean` 迁 AES-GCM~~（**已闭环 `610b8a03`**，同族降级门 `_FallbackCipher` 另登 §6-34） | ≈1100 → 余 ≈950 | **先修守卫假前提**；只收判据不放宽校验 |
| 8 | ~~`skill_system` 四体收口（§5 共性四）~~ **已闭环 `14f0f164`** | 实测 **-306**（预估 -230） | 契约快照 + 测试改引用**实测 12 个文件**（初估 4 处偏少：幽灵模块名 6 处、影子路径 6 处、替身字段 5 处重叠分布）；技能执行链活体已跑（真后端 + 真 JWT + 5 技能列表 + 真载荷透出） |
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
| `ed015dcb` | 首页会话数/按天趋势与 `/stats/agents` 按调用者分桶（生产净 **+50**）；`/export` 不再把端点当普通函数 `await`，两侧共用 `_agentStatsRows(callerId)` | §6-28 的 A |
| `bcbb5f69` | 会话归属判据在 `console.py` 的 5 份写法收口为 `_check_session_ownership` 一处（生产净 **-8**） | §6-28 的 C |
| `e040304d` | `save_message()` 加 `user_id` 关键字参数、既有属主只回填不覆盖，生产调用点须显式声明归属由源码守卫钉（生产净 **+23**）；`room_store` 显式声明共享 | §6-28 的 D |
| `a9126ce5` `dd9c4ffa` | 上述两批守卫进受保护子集（逐文件单跑确定全绿后才登记） | §6-28 判据接线 |
| `b77d9b24` | 身份门收成一份推导（`_identityFromCredentialsOr401` / `_identityFromCredentialsOrNone`），两种凭证策略**改叫两个名字**（`get_current_user` 严格 / `...WithQueryToken` 可查询参数），`deps.py` 收成带理由的再导出（生产净 **-17**：`auth +54 / deps -71`）。**记账更正**：该 commit 正文写的是"生产净 -38"，按 `git show --numstat` 复算实为 **-17**——错在把 `deps` 的删除行数当成了净数 | §6-28 登记的债 ① |
| `fb7801be` | `test_session_round_ops` 的隔离从 chdir 改为 `NEUROVA_SESSIONS_DIR` + 单例复位，并在 fixture 内断言落点确为 tmp 目录（生产净 0，测试净 +10）；6 passed/7 failed → **13 passed**，真实 `data/sessions` 内容指纹不再变化 | §6-28 登记的债 ②，命中点清点转 §6-29 |
| `bf32ec98` | RSI 回执落盘失败终于真回滚：`self._logger` 幻影引用（全仓 151 处取用中仅这 2 处是幻影）把 `:386` 的 `setattr` 撤回短路成死码，调用方收 `False` 而系统留着新值；判据含全仓 AST 扫防同形回流（生产净 **0**） | §6-2 闭环，附一条未顺手改的遗产分支口径 |
| `49326f6d` | 让位规则的协程工厂处处 await（生产净 **0**）。第四命中点在**已挂载端点**上：`POST /coordination/yield-checker/reset` 零异常零效果地回 `{"status":"reset"}`——最安静的一类假成功；`agent/turn_coordinator.py` 那处按"文件名→期望命中数"双向钉入台账（零生产消费者 + 调不存在的 `initialize()`，属接线/退役待裁） | §6-5 闭环（命中点由 2 复扫为 4） |
| `347bc581` | 渠道域"依赖缺失却报成功"全族扫荡：**26 处 / 10 文件**（原报告记 3 处），四类契约分别收成 False / None / None / 该文件已有的失败结构，并删假状态写入与 2 处随之失去用处的 `import time`（生产净 **-9**）。三处本就是诚实失败结构的（`ok:False`/`errcode:-1`/`retcode:1`）按语义放行未动 | §6-8 闭环 |
| `abfe6d6b` | 会话落点两层判据收口：conftest 默认隔离（`_isolateSessionsLanding`，同 `_isolate_agent_workspaces_root` 手法）+ 收尾守卫挡显式改回真实库；8 个测试文件的 chdir/patch 私有方法/相对 env 全部改走单一通道，重复定义收回一处（生产净 0，测试/CI +202）。41 文件 45 errors → **413 passed**，`test_session_archive` 4 failed → 8 passed，api+core A/B 32↔32 逐行一致 | §6-29 闭环，并新增 §6-31 一条环境掩盖面 |
| `a31851e2` | 台账 commit 号可达性守卫：`scripts/ci/audit_ledger_commit_guard.py`（判据 `merge-base --is-ancestor`，替代号须"标题唯一 + numstat 逐行一致"才给）+ 三判据测试，其中用 `git commit-tree` 现造悬空 commit 自证扫描器咬得住；常驻判定红→绿端到端演过一遍（塞入失效号即红、还原即绿）（生产 0，脚本+测试 +229） | 本报告"号会再次静默失效"的口子闭环（见 §10 回写记录） |
| `4ef87e3d` | `tests/manual/` 脚本拒在收集之前（`pytest_configure`；`collect_ignore*` 对显式路径实测无效）+ 三道判据，默认收集口径从 pyproject 现值读（生产 0，+155）。全仓收集 **21440、零错误** | §6-31 闭环，脚本自身形态未动（留人裁） |
| `98e07c70` | env 重定位落点走锚点：空串 env 曾让 RSI 审计流指到进程 CWD（`Path("")`==CWD，OSError 又被吞成"内存模式"），管理配置默认值不再按 CWD 解析（改锚 `repoRoot()/config`，位置零变动）；**并补判据盲点**——键名不带路径语义时 `Path(os.environ.get(变量, "相对名"))` 静默漏过，扩展后加反向断言守住不误伤（生产净 **+17**：evolution_settings +11 / result_summary +6；测试 +102）。HEAD 上的常驻守卫红已消 | §6-32 新增并闭环；§6-26 锚点契约第四、五命中点 |
| `f1a86796` | 记忆技能未装配管理器时诚实失败（store 曾回 `stored=True`、search 回空集且 `success=True`，`degraded` 只是附注）；三条把假成功当契约钉住的既有断言改判成"缺席必须点名失败／挂上管理器必须真被 `recall`/`remember` 调用"两两可证伪形态。A/B：受影响面既有 2 条失败两侧一致、零新增（`neuHebb` 一次偶发，单跑 3/3 与合跑第二次均不复现，不当结论）。**净 LOC 复算：生产 +4**（memory_executor 10-6），测试 +146/-10——提交说明里写的 +2 与 +86/-14 都是手工加总之误 | §6-17 改判并闭环 |
| `14f0f164` | `skill_system` 四体收口：影子文件 `neurova/skill_system.py` 搬入包内 `core.py`（同名包遮蔽这一根病灶随之消失），门面 304→26 行转**纯静态 re-export**（8 段逐字相同的反射样板、幽灵名顶层 import、占位 `Skill`/`SkillResult`、重复 `SkillInfo`、零消费者的 `_get_skill_module` 全删）；一进程内三份 `Skill` 收回一份，`SkillStatus` 三份归一为 `str, Enum`（保 `status=="active"` 裸串读法）并删五个零读取成员；github_push 的第二条反射后门（另一个 cache key）删除；`ExecutorBackedSkill` 改为继承运行时基类并退役重复 `get_info`、私造 `_SkillInfo`/`_SkillResult` 改指单源；名实归一带出端点降级分支读错字段的真缺陷（恒回 `{"status":"ok"}` 编造空载荷）一并根修。红灯四条实测原文（`isinstance(...) → False`、门面类≠运行时类、`SkillStatus` 两次取值 `is False`、期望 `{'computed': 42}` 实得 `{'status': 'ok'}`）；绿灯 3+6+1；**A/B 用 HEAD 只读 worktree 逐条比**：skills+evolution 基线 2 failed/2482 passed/2 收集 ERROR → 本批 2 failed/2491 passed/**0 ERROR**；活体：真后端 8123 + 真 JWT 登录 → 5 条技能（含 github_push）+ `file_operation` 真目录列表透出 + `/metrics` 200。净 LOC 按前两笔教训**先 numstat 后写说明**：生产 **-306**（+51/-357），测试/文档 +357/-146 | §5 共性四、§9 序 8 闭环；新增 §6-33（活体踩出的脚本落点旁路） |
| `610b8a03` | 凭据存储改走认证加密（P0-3）：`secret_store_clean.SimpleCipher` 重复密钥流 XOR 退役，写侧接仓内唯一 `enc:v2:` AES-256-GCM 口径；**更硬的一条根因在失败语义**——解不开只 warning 后丢条目，而保存按内存重写整份 `secrets.json`，换一次 keyfile 就静默丢掉存量 SSH 私钥与社交凭据，`store_secret()` 却照样回 True。一并做的：存量 XOR 只读解码 + **读到即升级**、升级失败不动盘、读一条凭据不再重算整桶 KDF（实测 ≈40ms/条，读一次放大成 N×KDF）、零消费者且用随机临时密钥的 `get_secret_store()` 按断点退役。红灯 6 条原文（含篡改一位后 `get_secret` 返回 `'value-to-taFper'`）；绿灯 8；A/B（llm+api+collaboration+core）33↔33 逐行一致，两处差异各自归因（基线独有 1 条顺序偶发 ERROR；本树 1 条棘轮红证实是仓内 worktree 被全仓扫描双计，摘掉即绿）；活体：真端点写入 → 盘上 `enc:v2:` 且全桶零明文 → **换进程**读回一致 → 手工预置历史桶读回并当场升级。生产净 **-52**（+114/-166），测试/CI +8/-1。撞上一次敏感件防火墙吞测试文件名，改判为改名不放宽（§6-36） | §6-18 第三条闭环（前两条实测在位）；A12 判定按实测改判；新增 §6-34（同族降级门，需存量取证与产品裁）、§6-35（凭据桶落点隔离缺口） |
| `f9f1b70b` | P0-3 同族两条诚实性收口（生产净 **-24**，+98/-122）：① 记忆层 `_FallbackCipher` 降级门改为 fail-fast（口径对齐 `providers/secret_store.py:40-49`），`_FernetCipher` 不再把失败改写成空串，`_load_or_create_encryption_key` 不再发"重启即失效"的临时钥匙（M-12 的另一半）；② `create_admin_user.py` 改走服务端同一解析（`UserModel()` → 数据根）+ 口令只认 `NEUROVA_ADMIN_PASSWORD`（强度沿用 `PasswordHasher.is_password_strong`）、不回显、失败非零退出，`docs/06-bugfix/login_fix_summary.md` 就地加"勿再照本节执行"注记。取证决定形态：三版 `git grep -c` 证这条加密链从未被调用方走过 → 盘上无 XOR 存量，可直接 fail-fast 而不必先做 legacy 读回。红灯 3+5、绿灯 5+6；A/B（memory+core）本树 8 ⊂ 基线 10，零新增；活体：从 /tmp 作 CWD 跑脚本 → 账号落进指定数据根（仓内 `data/users.db` 复查为空）→ 同一数据根起真后端 → 用该口令登录拿到 token。**我自己引入又消掉的一条**：`getpass` 交互分支在 Windows 不看 `sys.stdin.isatty()`，无人值守时挂死在提示符（faulthandler 栈定位），安装脚本不能留能阻塞的路径 | §6-33、§6-34 闭环；新增 §6-37（能力从未接线，需人裁）、§6-38（同形态硬路径 3 处命中） |
| `b3e44687` | P1-4 通知枚举改接真账号源（生产净 **+11**，逐处列明：分页循环 8 / 降级点名 5 / 口径注释 5，减两处旁路读 21）：`_users_store` 从不播种 → `notify_admins` 每次枚举空集、审批与市场通知全体落进 `default` 共享桶（没送达真管理员 + 管理员可见内容跨租户可读）。现走 `UserModel.list_users(role=, status='active')` 并分页（默认 limit=100 会静默丢掉第 101 个账号）；"零账号才兜底 default"保留并钉成判据。4 个测试文件 10 条改判为建/清空真账号（共用夹具 `_realAccountFixture`），并暴露"不隔离就读到仓内真 admin、通知发给真人"这一格。A/B（仓外 worktree，api+collaboration+skills）基线 28 ⊃ 本树 26，唯一本树独有条目早前基线复跑同样红（顺序偶发，不下结论）。活体：临时根建 admin id=1 / alice id=2 → 真后端 → alice 提交公库 200 → `kb_review` 通知 user_id=1、落 default 0 条，服务端日志同行对得上；仓内 store 零污染 | §6-4 闭环；§6-35 落点隔离缺口再添一格实证 |
| `f76677b5` + `d319f4c3` | P1-5 前端错误上报真落盘并限量（生产净 **+58**，逐处列明并说明 numstat 被反缩进放大的部分）：端点接进既有 JSONL sink（该 sink 生产零调用方＝"写了没接"的断点）；状态与事实一致（坏体 400、超大 413、超条数 422、写失败/少写 500 且不回显内部异常文本，只有真写入才回 `logged`+count）；免鉴权面加载荷上限（256KB·≤50 条·单字段 8000，截断留痕）；归属只认服务端身份并丢弃客户端 `user_id`/`timestamp`；sink 侧两处同根因一并修（目录不再导入期绑定、写失败不再吞成 return 0）。额度**没**在此另造——活体连打 140 发，第 121 发即 429 与 `rate_limit_per_minute=120` 吻合，证全局 `RateLimitMiddleware` 已盖住这条白名单路由。红灯 5 → 绿灯 5（含 sink 自带 16 条同跑全绿）；A/B（core+api）基线 32 ⊃ 本树 31 零新增。**自查出一条自己的违规**：新判据探针里写了开发机绝对路径，被 `TestNoHardcodedDevMachinePaths` 当场逮住（`d319f4c3` 按守卫口径换机器无关假路径，未改守卫未加豁免） | §6-3 闭环（原记"从不调 error_logger"，实为 sink 存在但零调用方 + 另有三处同源问题） |
| `920dbfef` | P1-6 记忆段 token↔字符换算收口（生产净 **+18**，`injector +21 / models -3`，去向已在提交说明逐条列明）：`TokenBudget.chinese_ratio`/`english_ratio` 两属性与零调用方的 `_truncate_text` 退役，系数裁剪换成按统一估算器**整行二分**的 `_foldMemoryLineToBudget`（估算器不可加，量的是整行而非分量相加）。红灯 3 failed（66/100、17/100、AST 仍在用第二套比例）→ 绿灯 4 passed 并入受保护子集。活体同一句生产调用 `:1759` 前后对照：中文 58%→100%、英文 10%→100%，修前两条裁出的字符数一模一样（2677）。A/B（`tests/unit/context`，排除本批新判据）基线与本树失败集**逐行一致**（同为 §6-40 那条常驻红）。**两处自我更正**：① 提交说明写"新判据文件 87 行"，`git show --numstat` 实测 **86**；② 本批修的这条折叠路径在生产默认（池开启）下**不被消费**——这是活体挂探针量出来的，不是事后找的说法 | §6-13 真闭环（原 ✅ 是空判）；新增 §6-39（主链不吃记忆预算，需人裁）、§6-40（受保护子集里的常驻红 + 判据与设计口径冲突，需人裁）、§6-41（跑测污染仓内上下文台账，§6-29/§6-35 同族漏格） |
| `d63b3c66` | P2-7 懒建单例收口成双检锁唯一实现（生产净 **+24**，去向逐条列明：新模块 `core/lazy_singleton.py` +57，改动的 67 个生产文件净 **-33**）。原记 §6-19 是抽样描述、不是全量——AST 重测得 261 处单例形态懒建：**79 处完全无锁**（模块全局 74 + `cls._instance` 5）、7 处锁内单次判（correct-but-slow，不动）、**165 处 DCL 用非可重入 `Lock`**（原判"auth 侧 4 份"偏小两个数量级）。79 处全部接唯一实现；`lazySingleton` 在**装饰期**校验缓存名，收口时当场逮住一处真写错（`capability_graph._META_RETRIEVAL_ROSTER` 只在函数里 `global`、模块字典没这个名字——照旧写下去就是"每次调用重建名单"）。红灯是并发探针（barrier 强制构造重叠：修前 8 线程构造 8 次、修后 1 次），不是形态断言；活体走真 ASGI + 真 JWT：24 线程 × 4 路径 = 96 发全 200、零 5xx，整段并发里 `UserModel`/`_Metrics` 各构造 1 次，并如实记下"这条端点是 async、循环内本就串行，活体没复现双建，双建证据在探针那一层"。A/B（HEAD 只读 worktree 在仓外）：core 9↔9 逐行一致；agent+api 基线 28 ⊃ 本树 26；channels/collaboration/security/execution/skills/llm/memory 基线 22 ⊃ 本树 19 且 passed 两侧同为 5061 —— **本树独有失败 0 条**。基线独有 3 条单跑皆绿（顺序偶发，不下结论）。**自己的两条违规当场自纠**：① 棘轮判据里"锁内二次判空"那格，我把 `is None` 的比较取在 `If` 节点本身（`noneCompare(n)` 而非 `n.test`），DCL 永远判不出来 → 计数恒 0、断言 `0 <= 150` **假绿**；是我另跑一遍独立计数拿到 165 才发现判据在骗人（同一文件里还另有一处把 `ast` 写成模块内没导入的别名，那条直接 NameError 红出来——假绿的这条更危险，因为它不报任何错）；② `protected_tests.txt` 被我重复登记两次同一文件（第二遍追加时没先查已有条目），已删重、复跑跟踪守卫 34 passed | §6-19 无锁那一格闭环、`Lock`/`RLock` 一格转只降不升棘轮；新增 §6-42（`skill_service` 关键段不持锁，判据常驻红）、§6-43（`test_computer_param_no_phantom_knobs` 超全局墙钟，整目录跑不完） |
| `78abaa2e` | P2-8 第一批：让位**执行体**收成一份并先修好额度账（生产净 **-372**：`turn_coordinator -112`、被摘链的 `coordination_decorators` 整包退役 **-304**、`coordination_api -3`、`glance_yield_rules +47` 为占位/还位/租约）。裁决形态由用户拍板为**接真**，预算 ≤10 次重试、单次 ≤20s、超时挂起等人工续跑；本批只做教义第 7 条的前三步（对比→取长补短→退役），**接线本体留第二批**，故 §6-5 的"支路从未执行"此刻仍成立，只是从"两份实现各调各的"变成"一份就绪未接入"。三条打在现状行为上的红灯原文：① `AttributeError: 'YieldDecision' object has no attribute 'backoff_round'`（已挂载端点每次必 500，见 §6-44）；② 等待 1s 期间其它协程**只走 0 拍**（装饰器在协程里 `time.sleep`，一个 Agent 让位睡掉整条事件循环）；③ `['unknown','unknown']`（`kwargs.get("agent_id","unknown")` 让所有 Agent 挤同一个公共桶）。前置根因见 §6-45：Layer 2 **判一次加一次、只有注册没有注销**，接真后第一轮重试就会把自己的模型锁死。活体对照（真 uvicorn + 真 HTTP 栈）：基线树 5 发 `check` 全 500 且 `active_per_model={"gpt-live": 5}`；本树 5 发全 200 且回落 `{}`，闸占 1 格、操作完成后归零。A/B（仓外 HEAD worktree；collaboration+e2e）**本树独有失败 0 条**，新 44↔基线 66，红自证确认基线独有那 22 条正是本批新判据；合跑 551 passed。**一处判据形态联动**：漏 await 台账 `_UNWIRED_REGISTER` 随第四处消失摘回**空表**（原"文件名→期望命中数 1"的双向钉不再有无的放矢的钉子），另补 reset 端点的**行为**判据顶住"表空了但形态回流"。受保护子集登记与台账回写另笔提交 | §6-5 第一批落地（两处事实更正：e2e 预存失败 2→7→现 17 passed；第四处由"接线 or 退役待裁"改为已拍板接真）；新增 §6-44（端点每次必 500：手抄字段抄出不存在的属性）、§6-45（额度判一次加一次，接线前必须先把账修对） |
| `81fd6b56` | P2-8 第二批：闸**接进回合入口** + `parked` 非终态 + 人工续跑（后端生产净 **+413**、前端生产净 **+183**，去向逐文件列明；测试与契约生成物 +787）。红灯原文四条打在现状行为上：回合入口根本没问闸（间谍计数 `assert 0 == 1 where 0 = len([])`）；没有挂起形态 `assert 'parked' in ['chunk','item_started','item_completed','done']`；**未归因回合把 pin 钉成空串** `get_stats()['registered_agents'] == 1`——前端默认不传 model（`ChatPage.vue:1340` 的 `selectedModel.value || undefined`），用户一选手动模型就撞上 `MODEL_PIN_VIOLATION` 这格"等多久都不自愈"的原因，第一次判定即挂起（这条只有接真才会露出来）；`stats()` 把 parked 折进 terminal。绿灯：新判据 9+8+3 条合跑 20 passed，前端契约 10 passed、locale-consistency 22 passed、`vue-tsc --noEmit` 零输出。活体（真 uvicorn + 真 JWT + 隔离数据根，探针即用即删）：`types=['parked','done']`、行落 `parked/owner=''/finished_at=None` 且载荷入库；换新 store 实例（等价重启）后仍 parked，`stats={'running':0,'queued':0,'parked':1,'terminal':0}`；续跑 200 且**库里仍只有 1 行**、`attempt` 递增、终态写回后载荷清空；陌生 403/匿名 401；仓内 `data/agent_runs.db` md5 前后一致。如实记一条活体边界：本机模型密钥是占位值（真服务端回 401 `sk-test`），故续跑那一腿活体走的是"真入口 + 真失败"，"续跑后拿到回复内容"由单元层桩 agent 那 8 条钉。**活体自纠一条自己刚写出的缺陷**：续跑端点原先先判状态再判身份，陌生账号会从终态行先拿到 409（等于确认这条 run 存在且已结束）——改为身份在前并钉成判据。三处既有判据按实测改判（非放宽）：`test_stats_and_wal` 三键→四键；`console_split_routes.json` 重生成（逐字段核对：仅 `/chat` 多一个 `resume_run_id`、新增两条路由、无移除）；前端 F-10 从"全文件恰好一个 AbortController"改成"每条流式取数各建各的且同处消费自己的 signal"（续跑是第二条独立流，数总数会把正确形态判成违规）。A/B（仓外 HEAD worktree；api+core+collaboration+e2e，按 §6-43 绕开 computer_use）：本树 24 failed/8 errors ↔ 基线 24 failed/9 errors，**本树独有失败 0 条**；基线独有 1 条回基线单跑 3 passed 属顺序偶发。红自证：单独 stash 本批 4 个生产文件后复跑同一选择集 20 failed/1 passed，失败集恰为本批新判据（唯一绿的是防"把 pin 判据一并删掉"的反向守卫）。受保护子集新增三份（逐文件单跑确定全绿后才登记），跟踪守卫复跑 34 passed | §6-5 真闭环（"支路从未执行"结束）；新增 §6-46（三条同根因入口未接闸未记账，需人裁）、§6-47（miner 注释虚报 agent_runs 为数据源）、§6-48（前端两条 HEAD 常驻红） |
| `d4c8b560` | P2-8 第三批：§6-46 三条入口接上闸与台账（生产净 **+475**，逐处列明：新模块 `core/agent_run_ledger.py +307`，其中约 159 行是从 `console.py` **搬过去**的既有实现（console 侧净额 **-128** 即它）、`chat.py +231`、`channel_router.py +65`；测试 +422）。做法是**先收口再接线**：台账执行体与"问闸→挂起→落库→构造回包"抽成唯一实现，四入口（`/console/chat`、`/v1/chat`、`/v1/chat/stream`、渠道入站）全部改指它，并钉三条结构守卫（闸口调用点全仓只一处、台账类不得住回 console、三入口必须 import 那份实现）。最硬的一条红是**假成功**：`/v1/chat` 超限那一轮回 `{'code': 0, 'message': 'success', 'data': {'reply': …}}`（§6-8 那族形态的另一副面孔），现按各面本来的样子回 parked。载荷带 `entry` 使续跑回到**原入口**重建请求（按网页请求体重建会静默丢掉 `temperature`/`max_tokens`，那是另一轮对话不是重跑）。活体：`status=200 message='parked'`；渠道行 `parked` 且属主是 agent 属主、回执文本含该 run_id、拿它打网页续跑口得 200；陌生账号 403；仓内 `data/agent_runs.db` md5 未变。A/B（仓外 HEAD worktree；api+core+channels+collaboration+e2e）本树 24 failed/8 errors ↔ 基线 24 failed/9 errors，**本树独有失败 0 条**；红自证 10 failed/1 passed 且失败集恰为本批新判据（唯一绿的渠道 fail-open 那条在接线前当然绿，如实记）。两处既有判据按 seam 移动改判（行为主张不变）：间谍从 `console.requestYieldGate` 改打 `core.agent_run_ledger.requestYieldGate`、`HEARTBEAT_SECONDS` 的 import 随类搬家 | §6-46 闭环（留两处如实边界：渠道续跑后不再推回渠道、无 `session_id` 的调用不记账但仍问闸）；两份新判据入受保护子集（逐文件单跑 4 / 7 passed 后登记），跟踪守卫 34 passed |
| `b2a4cf55` | A 轮第一批（§6-12 缺陷①②）：事件面两处契约错配根修，**生产净 -3**（`base_module +48/-18`、`injector +11/-48`（删降级替身）、`orchestrator +4/-0`），测试 +306。取证推翻三条旧表述：全仓实为**两份 EventBus 平行实现**且 `memory_layer/manager.py:185` 自建私有总线（出口 `:832` 零调用方）、`bus_event.py:72` 的"无 emitter 无 subscriber"只指 P2-10 已删常量、`base_module._event_bus` 生产恒 None 致生命周期广播一次都没发出（`/api/v1/logs` 读的就是这条总线）。修法四处一并收：`_resolveEventBus()` 注入优先/未注入回落唯一全局入口且每次现取、两处广播改指 `publish`、`BaseModule.subscribe_event()` 成为基类唯一订阅面、injector 降级替身整体退役 + 三个 `async` 误标钩子改同步 + 唯一装配点 `init_context_system()` 补调 `initialize()`。红自证失败集恰好 12 条（新判据 10 + 改判的既有 2），既有判据 `test_emit_event_with_bus` 原用 `MagicMock` 断言 `bus.emit`——**生产与测试同时错所以一直绿**，现改真 `EventBus()` 行为判据。活体：真启动后 `context.build` 订阅 0→2、`GET /api/v1/logs` 14 条里 12 条 `module.state_changed`、再造一个 Agent 订阅 +1；`data/agent_runs.db` md5 与 `data/sessions` 207 文件均未变。A/B（仓外 HEAD worktree，core+context）基线 10 failed/3002 passed，本树独有失败仅那条假契约判据（改判后全绿） | §6-12 缺陷①② 闭环（总线合并与 MEMORY_* 真实订阅者留 A3）；新增 §6-49（`publish` 对 async 订阅者无队列即静默丢弃，A3 必须一并处置）、§6-50（`deps.py:175` 与 `infrastructure.py:190` 两处只写不读的取用面）；两份新判据入受保护子集（单跑 4 / 6 passed），跟踪守卫 15 passed、条目 405 无重复 |
| `9d4befb9` | 前置守卫修复（开工拦路虎）：`tests/ast_scan.py:filesUnder()` 用 `rglob` + 只排 `__pycache__`，于是把开发机放在仓根内的第三方一起算进扫描面——实测 **35965 个 .py 里 32711 个来自 `.venv`/`node_modules`**，文本预筛须先读每个文件，全量读 **49.68s** 越过 pyproject 全局 `timeout = 30`，导致整个 `tests/unit/cognitive_layers/` 在开发机上不可跑（同一判据在仓外精简 worktree 只 5.87s 通过：**绿灯取决于本机装了什么**，与 §6-43 同族）。改在单点：`os.walk` 遍历时就剪掉第三方/产物目录（`rglob` 是"先下钻再筛"，实测光遍历 11376 个目录要 1.82s）。剪枝后扫描面 3255 文件、全量读 0.43s（↓约 115 倍）。红→绿：2 failed/2 passed → 4 passed；四条判据含反向两格（仓内 `neurova/ tests/ scripts/` 必须仍全覆盖且 >1000、往 `neurova/` 种探针必须仍被扫到），防"排除"写成"什么都不扫"。测试基建 +85/-7，生产零改动 | 本批 A/B 与后续所有跨文件判据的前置；无台账格新增（属判据基础设施缺陷，非产品缺陷） |
| `e3cd82cc` | A 轮第二批（§6-12 总线合一）：两份 EventBus 按教义第 7 条**先比后合**，选定 `core/event_bus.py`（有 DCL 单例、优先级/once/模块归属、事件日志且日志有现役读面 `logs.py:72/106`、publish 返回 handler 结果；调用方 3 处 vs 1 处）。`manager.py` 五处 `self._bus.emit(MemoryEvent(...))` → 唯一投递口 `_publishMemoryEvent()` 走 `get_event_bus().publish(..., source="memory_manager")`；**删掉每 manager 自建的私有总线实例与零调用方的 `bus` 出口**——这才是"MEMORY_* 没人读"的真成因（发到一条外部拿不到的总线上），也才是 `get_stats()` :2115-2116 恒 0 的成因。`bus_event.py` 退役 `EventBus`/`MemoryModule`/`ModuleHealth`（后两者全仓零引用）收成常量表，持有者改名 `MemoryEventName` 以避开 `memory_stream.py:38` 同名不同义的 `MemoryEvent`；顺手删六个零发射零订阅的僵尸常量（与 P2-10 已删那两个同族）。`event_bus.py` 取长补短 + §6-49：发布计数**移进锁内**（`+=` 非原子，被改判过来的 20 线程×200 发并发判据当场抓红）、async 订阅者无队列时改留痕不再静默 `continue`、新增 `publishedCount()`/`droppedAsyncCount()`。**主动撤回一格假接线**：原计划把 MEMORY_UPDATED/DELETED 接去清注入器上下文缓存，实测 `cache_entry`/`get_cached_entry` 全仓零调用方（那张 LRU 既不写也不读），接上去绿灯会亮、闭环不存在 → 改判据为"记忆写入须出现在现役 HTTP 读面 `/api/v1/logs`"。既有判据改判 8 条（Bug 6 六条锁纪律**逐条机械改写到幸存 API、一条不删**；`test_import_safety` 导入落点改指唯一实现）。红→绿 5 条全红 → 5 passed + 2 passed；活体见 §6-12；A/B（仓外 HEAD worktree，cognitive_layers+core+context+api）基线 27 failed/9 errors、本树 28 failed/8 errors，"仅本树红"1 条是随后 B1 批默认值变更在 A/B 运行期间的串扰（已在 B1 内改判），"仅基线红"1 条 ERROR 回基线单跑即绿属顺序偶发 | §6-12 总线合一闭环、§6-49 闭环；新增 §6-51（缓存与流水账两个零写零读面，需人裁）、§6-52（惰性导出判据前提符号已退役，HEAD 常驻红）、§6-53（跑测改写仓内真实用户会话文件，含对本行上方 207 文件数的更正：现测 208） |
| `94f4eedc` | P3-11（B1）：429 等待加**累计预算**并按拍板改 10×20s。单源 `llm_retry_settings.py` 新增 `wait_budget=200.0`（+ `MIN/MAX_BUDGET`、env `NEUROVA_LLM_429_WAIT_BUDGET`）、`interval` 默认 10.0→20.0；治理面 PUT 收这一格且区间**直接取单源常量**（不重抄数字）；消费方把 `waitedSeconds` 挂在**整条请求**上（原状每个候选各带一份 10×interval，流式还 `while True` + 换模型归零 `retry_no` → 最坏 10×120s×5 ≈ 2 小时，全文件 grep 不到 deadline），两个睡眠点都先问预算，不够就**不再睡**、交回既有换模型/`exhausted`+流内错误路径（不新增错误形态、不把失败降级成 warning）；前端类型 + SettingPage 旋钮 + **i18n 11 语言**各两键（`locale-consistency` 22 passed、`vue-tsc` 退出 0）。行为判据：`max_retries=50` + 两候选恒 429 → `sum(sleeps) ≤ 200` 且必须给诚实终态。红→绿 5 条红 → 6 passed；既有判据改判 8 条（`test_chat_stream_429_retry` 的 cfg/sleeps/interval 七处取值随拍板走 + `test_governance_llm_retry::test_get_defaults` 逐字对照）。活体（真 app + 真登录端点签 JWT + 生产取数函数）：GET 默认含 `wait_budget:200.0` → PUT 7.5 → 消费方读到 7.5 → env 覆盖 3.0 → 越界 PUT 0 得 422；探针即用即删，`data/agent_runs.db` md5 未变、探针账号未落进仓内 `data/users.db`。生产 +68/-20、前端 +24/-1、测试 +153/-2 | §6-5 附格的 429 待办闭环（留下 `wait_cap=120` 未压到 20 的口径边界，已在格内如实写明） |
| `42447e8e` | **补交 `94f4eedc` 漏扫的同根因判据**：`tests/unit/llm/test_chat_stream_429_retry.py` 仍按旧口径钉 `interval=10.0` 且不含 `wait_budget`，于是 B1 一入库，HEAD 自己带着 **9 条红**（`9 failed, 8 passed`，在仓外基线 worktree 复算原文见 commit 正文）。CI 没拦住的原因值得记：**该文件不在 `protected_tests.txt` 子集里**——"不在子集"不等于"没坏"。改法是让值层期望跟上单源 `DEFAULTS`（补 `wait_budget`、回落值与睡眠断言 10.0→20.0），不是放宽判据。测试 +12/-10，生产零改动 | `94f4eedc` 的教义第 5 条补面（同根因命中点扫荡未做完那一半） |
| `d2ee8d96` | P3-12（C1）：记忆面**写侧**收口到路由级身份门（生产净 **+63**：`api/auth.py +46` 新增 `requireIdentityForWrites` 与 `MEMORY_IDENTITY_GATES` 闭集、`memory/base.py +8/-2` 在唯一的 `APIRouter(dependencies=[...])` 上挂一次门覆盖 11 个子模块、`cli.py +15/-4` 补 401 自救提示）。根因是"匿名回落 default 桶"这条**读侧**政策被写侧沿用——共享桶被当成无人看守的桶，任何访客可增删改且事后无从对账；§6-1 修的是跨租户越权，这一格是同一条链的另一半。门**不重解凭证**，直接调严格门本体用的同一份 `_identityFromCredentialsOr401`（教义第 6 条）。红灯原文：30 条写路由 30 条放行匿名（`POST /markdown → 422`、`PUT /eki/enable → 500`，都是"进到 handler 却没人看守"）。连锁改判 15 个测试文件（新增 `tests/auth_headers.py::bearerHeaders` 签**生产同一个函数**产出的真 JWT；`dependency_overrides` 替不掉路由级门这一格在 `test_memory_route_authorization.py` 上实测撞出，并顺带把匿名写期望从 404 改钉 401——两道门各自可核实，覆盖面更强）。活体（真 uvicorn + 真 JWT，不用 TestClient 因为门挂在路由级依赖上）：匿名四类写全 401 且带 `WWW-Authenticate`、带凭证同批写进到 handler 回业务码、匿名读仍 200、合法写 markdown 200、`data/` 逐文件 md5 指纹前后相等。A/B（仓外 HEAD worktree）`tests/unit/api` 24↔24 差集为空、`tests/integration` 全量仅本树红 0 条、`tests/test_api`+`tests/test_memory` 差集为空；**中途 A/B 真抓出 6 条回归**（`test_memory_settings_api_auth`），归因即 §6-54 那格门源冲突，按"回第 3 段修根因"处置为**回退该文件**而非放宽门。两份新判据入子集（单跑 4 / 4 passed），跟踪守卫 21 passed、条目 412 | 新增 §6-54（角色门与严格门双身份源，73 处命中，需人裁）、§6-55（HEAD 自带 2 条夹具过期红）、§6-56（并发会话脚本写死开发机路径使常驻守卫红） |
| `d9224d52` | C2：`/api/v1/chat/history` 两条端点**接上真数据**，归属与 console 面同解（生产净 **−42**：两条 handler 各删掉一整套"取 agent→判可达→try/except 折 500"的空转骨架，换成归属校验 + 唯一仓储取数；测试 +199）。复核实状推翻本批开工时的描述——缺陷不是"跨租户可读"而是**端点从来没工作过**（调的 `agent.get_conversation_history`/`clear_conversation_history` 全仓无实现，来源 `7835c367` 的 pyc 骨架恢复），于是 GET 恒空表、DELETE 恒 `code:0` 假成功。按教义第 7 条选定 console 那份实现，chat 面改指同一条链，归属比较式仍只在 `console.py` 出现一次；归属键从"agent 可达"换成"会话属主"（旧门同时留下两个错：非 default agent 的**属主自己**先撞 403，而 agent 可达时 `session_id` 从不比对属主）；`session_id` 由 Optional 收成必填（缺键回空表＝把"没给键"伪装成"没有历史"）；DELETE 收成**显式 501** 并沿用 `212d855c` 的处置形态，**身份判定排在能力判定之前**（陌生人拿 403 而非 501，否则 501 替他确认会话存在）。红自证 7 failed/4 passed 且失败集恰为本批新判据（**如实记 4 条基线也绿**：旧形态靠 agent 可达那道门恰好也挡住了 bob，所以那几条不是本批的红，是不许放宽的反证——也正说明旧门挡的理由是错的）。顺带补上 `test_session_ownership_single_source.py` docstring 早已主张、矩阵里却没落进 chat 面的那一半。活体（真 uvicorn + 真 JWT + 生产写入路径造真会话）：属主读到真消息、外人两面同码 403、外人 DELETE 403、属主 DELETE 501 且消息一条没少、共享会话仍可读、缺键 422、匿名 401、`data/` md5 未变——ALL PASS。A/B（仓外 worktree @ d636e366）`tests/unit/api+tests/test_api+test_chat_dead_endpoints+test_session_manager` 26↔26 双向差集为空 | §6-57 新增并闭环；§6-58 由本批的同根因 AST 扫荡扫出（见下行）；该文件入子集的登记历经并发重写，最终由本会话单独入库（§6-63 记账更正①） |
| `2ca1bfc1` | C3：`/api/v1/sync` 会话面补齐身份与归属，六格里三条原本**连身份依赖都没有**（生产净 **+80**：两个转交口 `_callerUserId`/`_requireSessionOwnership` +26、四条已有门的 handler 各加一行比对、三条补 `Depends(get_current_user)`、`end_session` 改"先查存在→比归属→再删"、`list_sessions` 过滤器改取 token 主体并**删除**外部 `user_id` 形参、`get_connections` 按已有过滤收敛；余量为逐格约束说明）。匿名可达不是理论风险：`NEUROVA_GLOBAL_AUTH` 未设即 `MODE_OFF`，兜底中间件不在路上。该 store 与 chat **共用 session_id 命名空间**（`chat_pipeline.py:558`），故非隔离内部面。归属比对**转交** `console.py` 唯一实现，本文件零内联比较式；`/connections` 一度写成 `session.user_id != caller`——那正是"复制同样逻辑换个变量名"能绕过只数 `!= user_id` 的守卫的形态，已改走 `manager.list_sessions(user_id=...)` 那道已有过滤。判据钉两层（四 handler 各须调转交口 + 转交口须交给 console）。**两条差点假绿**：AST 谓词第一版把 `router.get` 当 `Call(func=Name)` 数出 **0 条命中**（独立复算才发现数错）；`/connections` 那条在 `_ws_connections` 为空时恒真（改为先往生产表挂真连接 + 加正主仍可见的正证）。红自证 11 failed/4 passed 且失败集恰为新判据（外人四条的实测值是 **200** 而非码数不对；匿名 DELETE 用**真实存在的会话 id** 打，否则红会被洗成"像路由没命中"）。活体（真 `create_app()` + 真 uvicorn + 生产注册口播种；不用 TestClient 因为一半缺陷是"根本没有身份依赖"，只有真装配点能证明兜底中间件确实不在路上）：匿名三条 401 且未伤及会话、外人四条 403、alice 未被塞入 bob 的消息、属主四条 200、`?user_id=alice` 拉不到、`data/` md5 未变——ALL PASS。A/B（仓外 @ 6ca9b4e5）sync+channels+api+test_api 28↔28 双向差集为空；另跑 sync+channels 全量 576 passed 零连锁破坏 | §6-58 新增并闭环；新增 §6-59（前端调两条从未注册的路径，另根因）、§6-60（管理员全量可见被删，需人裁）、§6-61（context composition 同类低危）、§6-62（phase3 `user_id` 来自查询串，另一条链）；`test_sessionSyncRestOwnershipGate.py` 入子集同样经历并发重写导致的丢登记，最终由本会话单独入库（§6-63 记账更正①） |
| `2df0d958` | C2/C3 两份判据入受保护子集（**重落一次**）：第一次登记随并发会话的 E 批 commit 进过 HEAD，随后该会话**重写那笔历史**（新版只含它自己的 +3 行），两格从 HEAD 消失、只剩工作树，`git log -S` 对这两个文件名零命中才查出。触发点是台账可达性守卫把那个已失效的旧号判红——**只查对象存在与否发现不了重写**（`a31851e2` 的老教训今日复现，且这次连"曾经在 HEAD 里"都不保证）。纪律产出：**子集登记各批自己带路径单落一笔，不借他人 commit**。逐文件单跑 11 / 15 passed 后登记；跟踪守卫 21 passed；`uniq -d` 零重复；`git check-ignore -v` 两个文件名零命中。基建池 +15/-0 | §6-63 记账更正① 的落点 |
| `aff4ec6b` | D2 改判后的实际产出：`test_whole_repo_collection_errors.py` 的两条主断言**此前从未运行**——`_collect` 用 `text=True` 而不显式给 `encoding`，父进程按 cp936 解子进程的 UTF-8 字节，全仓那一发把 `proc.stdout` 静默置成 None ⇒ `proc.stdout + proc.stderr` 抛 `TypeError` ⇒ 2 ERROR at setup；而文件里唯一真跑起来的是最便宜的那条反证，于是长期顶着"这个守卫在守着"的假象。修法两侧钉死（`encoding="utf-8", errors="replace"`——replace 是刻意的：宁可看见 U+FFFD 也不要整条流换回 None 或让守卫炸）。新增一条**运行性前置判据**先证"捕获层本身可信"；走法上避开了一个坑：最初用"模块顶层 print 中文"做证据，实测**不行**——收集期 print 被子 pytest 的捕获层吞掉，与编码口径无关也会缺席，那样判据分不出"解码坏了"和"根本没打出来"；改为让子进程取一个**路径含中文**的目标，pytest 会把该路径原样打进它自己的 stdout。去掉 encoding 参数后这条复现的正是生产那条错的原文。修后 `4 passed in 63.76s`，全仓 **21690 条、零 ERROR collecting、rc=0**（收集卫生本身是好的，坏的只是看门那双眼睛）。A/B（仓外只读 worktree @ 6ca9b4e5，`tests/unit/core`）本树 9 ↔ 基线 11，**仅本树红 0 条**；基线独有 2 条即本文件那两条（修后转绿），即本批产出本身。测试基建 +47/−2，生产零改动 | D2 结论**改判**：本文件**不入 CI 子集**。理由不是"超 30s 全局 timeout"（每条断言带 `@pytest.mark.timeout(480+)`，单文件跑不被杀），而是 60s+ 的 CI 时长成本——`ce74616b` 当初写的就是这个，本轮复算（63.63s / 21690 条）后维持原处置，只把实测数与"它此前根本没在跑"补进文件说明与本台账；新增 §6-64（同根因全仓 **61 处**命中：`tests/` 35、`scripts/` 21、`neurova/` 5；余 60 处待裁 A 分批扫净 / B 只降不升棘轮） |


上表未覆盖的序 1—11 仍按原序待点单。队列进度：**P0-1/P0-2/P0-3、P1-4/P1-5/P1-6、P2-7 已全部落地**（P2-7 见 `d63b3c66`，只收了"无锁"那一格，`Lock`→`RLock` 的 165 处转棘轮）；**P2-8 三批全部落地**（第一批 `78abaa2e` 执行体归一 + 额度记账，第二批 `81fd6b56` 接进网页回合入口 + `parked` 非终态 + 人工续跑，第三批 `d4c8b560` 渠道与两条 `/v1/chat` 入口接上同一份实现），§6-5 与 §6-46 均已真闭环——闸现在覆盖仓内四条真回合入口，台账执行体与准入口只剩 `core/agent_run_ledger` 一处实现。`agent/turn_coordinator.py` 因此**从"需人裁"移出**——裁决已给并实现完毕（≤10 次、单次 ≤20s、超时挂起等人工续跑；闸放回合入口一次；park 落库后立即收尾；续跑权限＝会话属主 + 管理员）。**2026-10-08 追加：P2-9（§6-12 事件面）A 轮三批落地**（`b2a4cf55` 缺陷①② 契约错配、`9d4befb9` 判据扫描面剪第三方、`e3cd82cc` 两份总线合一 + §6-49 留痕）；**P3-11（429 墙钟预算）落地**（`94f4eedc`，10×20s=200s 累计预算，同让位闸口径；其同根因判据补交见 `42447e8e`）；**P3-12（记忆面写侧匿名可改）落地**（`d2ee8d96`，路由级门一处覆盖 31 条写路由，读侧 default 桶语义未动）——这三项从"需人裁"移出。**P3-12 的"只留两个门"没做完**：角色门 `require_role` 仍指 `deps` 那份解析，收口它要动 73 处命中，已登记 §6-54 待裁（与 §9 序 11 同一条链，不宜拆着做）。**2026-10-08 追加 P3-13（C2/C3 会话面归属）落地**：`d9224d52` 把 `/api/v1/chat/history` 两条空转端点接上唯一实现并同解归属（复核实状后原"跨租户可读"描述作废——真缺陷是从未工作过 + 假成功）；`2ca1bfc1` 把 C2 同根因 AST 扫荡扫出的 `/api/v1/sync` 六格补齐，其中三条**原本连身份依赖都没有**（匿名可结束任意会话、可按 `?user_id=` 拉整张会话表、可枚举在线 session_id），且该 store 与 chat 共用 session_id 命名空间。往后只剩两类：① **需人裁**——§6-37（敏感记忆加密从未接线）、§6-39（主链不吃记忆预算）、§6-40（受保护子集常驻红 + 判据与设计口径冲突）、§6-41（跑测污染上下文台账）、§6-42（技能池关键段两侧都不持锁）、§6-43（`computer_use` 目录超墙钟跑不完）、§6-47（miner 注释虚报数据源）、§6-48（前端两条 HEAD 常驻红）、§6-38（demo 脚本 CWD 落点）、§6-50（两处只写不读的总线取用面）、§6-51（上下文缓存与记忆流水账两个零写零读面）、§6-52（惰性导出判据前提符号已退役）、§6-53（跑测改写仓内真实用户会话文件）、**§6-54（角色门与严格门双身份源，73 处命中）**、§6-55（`test_memory_route_shadowing` 夹具落后于生产契约，HEAD 常驻红）、§6-56（`tests/manual` 新脚本写死开发机绝对路径使常驻守卫红）、**§6-59（`SessionSyncPage.vue` 调两条从未注册的路径：接线 or 显式退役该页）**、**§6-60（sync 列表/在线连接的"管理员全量可见"被删，代价已写明）**、**§6-61（context composition 同类低危）**、**§6-62（phase3 `session-started` 的 `user_id` 来自查询串，可冒充他人记账）**、**§6-64 余 60 处（子进程文本捕获未显式 encoding；A 分批扫净 / B 只降不升棘轮，两者不冲突且 B 便宜得多）**、RSI 遗产分支成功语义、属主读会话、**§6-65（`data/sessions` 历史件删除——依据已否证、文件不可恢复，只列清单不动手）**、**§6-66（`tests/manual` 收集拦截层：E1 原计划"退役它"的前提被推翻，实际待办只剩对新增脚本的只降不升棘轮）**；② **可按序推**——§9 序 1—11 与 B 档 14 组（≈1.3 万行）。「+60s 收集守卫是否进 CI 子集」这一格**已裁毕并维持原处置**（`aff4ec6b` 复算：单文件 63.63s，成本口径不变则不进；真正的产出是查出该守卫此前从未运行）。

## 10. 工作树状态

两轮审计全程只读。`git status` 复核：本轮未新增/未修改任何生产代码或测试，本文件为唯一新增产物（`git check-ignore` 确认未被忽略，可正常纳管）。

工作树另有三项**非本轮产生**的在途改动，属其他会话遗留，未作处置：
`models/tts/moss-nano/.gitattributes`（M）、`models/tts/moss-nano/configuration.json`（??）、`.zcodeignore`（??）。
提交本文件时须按 AGENTS.md §5 用 `git commit --only -- <paths>`，**严禁 `git add -A`** 把它们卷入。

执行事故与两次子代理失稳（返回无关内容 / 撞 maxTurns）已记于 §1；安全能力矩阵改由主会话自算，见 §3-B1。

**§9.1 各落地批次的当下工作树复测（2026-10-06，本轮登记结束时取）**：`git status` 仅本报告为 modified；工作树另有五项**非本会话产生**的在途改动——`docs/INDEX.md`(M) + `docs/08-research/rsiagent_vs_neurova_rsi_comparison_2026-10-06.md`(??)（同一次外部对标登记）、`config/evolution_settings.json`(??)、`.zcodeignore`(??)、`models/tts/moss-nano/{.gitattributes(M),configuration.json(??)}`，一律未处置、未卷入提交。
**2026-10-07 台账 commit 号失效与回写（并发会话重写历史所致）**：本文件原引 73 个 commit 号，
用 `git merge-base --is-ancestor <h> HEAD` 复核发现 **4 个已不可达**——对象仍在 `.git` 里，
所以 `git cat-file -e` 依旧成功，**只查"对象是否存在"发现不了重写，必须查可达性**。
`9495f1db→fb7801be`、`0fb8fed2→bf32ec98`、`942150e9→49326f6d`、`b1e18dfc→b77d9b24`，
成因是另一会话在并发提交之后做了 rebase/merge（`7285c66d` 已在历史中）。回写前两件事逐条验过：
标题映射**唯一**（无歧义），且 `git show --numstat` 两侧**逐行一致**——只凭标题相同就替换，
遇到"同题重做"会张冠李戴。教训入档：并发会话会改写历史，**commit 号不是稳定标识**，
每批落地后应复跑一次可达性检查；引用优先
这条已接成常驻守卫（`a31851e2`）：`scripts/ci/audit_ledger_commit_guard.py` +
`tests/unit/test_audit_ledger_commit_guard.py`，台账里任何号一旦不可达即红；替代号仍须
标题唯一且 numstat 逐行一致才给，不给则留空要求人工判定。
"标题 + 文件集"，号只作辅助。
（同批另记：本会话后续三批的号在写入时已按重写后的历史核对可达性。）

**推送状态更正**：本节原写"本会话各 commit 尚未推送"——现已不成立。并发会话在 rebase/merge
之后把它们推上了 `origin/main`（`git branch -r --contains` 逐一验过：`b77d9b24`/`fb7801be`/
`bf32ec98`/`49326f6d`/`347bc581` 均已在远端），当前 `origin/main..HEAD` 只剩 `abfe6d6b` 一条。
本会话自身**未执行过任何 push**；远端前进是并发会话所为。

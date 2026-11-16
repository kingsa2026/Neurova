# R3 收尾修复台账（P2 清偿·core/llm/context/知识/记忆/认知）

会话：R3 · 日期：2026-11-17 · 依据：`audit-reports/fullrepo-code-audit-2026-11-16.md` §3.2/§3.3/§11

---

## 3.2-1 check_connection 对死服务报成功 ✅

**根因**：ollama/lm_studio 的 `get_available_models()` 在 API 探测失败时回落静态默认清单，
`_fetch_models_from_api` 把非 200/网络异常吞成空列表；anthropic 的 `get_available_models`
直接返回静态已知清单。三条路都让 `check_connection` 不发真实探测就 `success=True`。

**修复点**（对齐 gemini/openai 已修口径）：
- `neurova/llm/providers/ollama_provider.py`：`get_available_models` 直透 `_fetch_models_from_api`；
  `_fetch_models_from_api` 非 200 抛带 `status_code` 的异常、网络异常上抛，不再吞成空列表。
- `neurova/llm/providers/lm_studio_provider.py`：同形态。
- `neurova/llm/providers/anthropic_provider.py`：新增 `_fetch_models_from_api`（真实 GET
  `{base_url}/v1/models`，非 200 抛错；无 key 返回空——管理器预检已拦截该场景）＋
  `_parse_api_model`（静态素材按 id 丰富元信息）；`get_available_models` 改走真实 API。

**红灯**：`tests/unit/llm/test_check_connection_dead_service_honest.py` 新建 8 格；
修前实跑 `1 failed`——`test_dead_service_check_connection_fails` 实测
`success=True, models_available=10`（静态清单判活），其余 6 格在 `-x` 下未跑、
anthropic 两格因 fixture 笔误后修（非实现问题）。

**绿灯**：同文件 8/8 passed（12.61s）；`tests/unit/llm/` 全量 881 passed 无回归。

**live-verify**：见批次末尾统一节（真实后端 + provider 连接测试端点）。

**命中点扫荡**（教义第 5 条）：同契约静态判活残余已查——openai/openrouter/gemini
先前已修（`get_available_models` 均 API 直透）；`fetch_models` 缓存路径失败回落
`_extra_models`（用户自配模型，非伪造内置清单，口径诚实）保留；base.py:86 通用实现
本就经 error_mapping 上抛。anthropic 的 `check_model_connection` 为同根因命中点
（本地构造 `create_chat_model` 不触网恒成功），已同批扫平：改对真实 `/v1/models`
清单做 found 判定（provider_only 形态），补 3 格红→绿
（`test_model_connection_dead_service_fails` 修前红：`success=True`）。

**遗留移交**：ollama/lm_studio 的 `_get_default_models` 现仅测试引用（"素材"约定，
与 openai 同形态）；anthropic 的 `_get_known_pydantic_models` 修前即零调用（预存死码，
未动）；ollama/lm_studio 的 `check_model_connection` 走 `create_chat_model` 本地构造
（同形态但属本地服务语义：构造成功＝运行时可用，未在本条口径内）。

---

## 3.2-2 DCL 单例守卫锁 Lock→RLock 收口 ✅

**根因**：AGENTS.md §3 明文要求懒创建型单例走 DCL + `threading.RLock`（构造过程可能
回调到同一入口，`Lock` 重入自死锁）；仓内单源是 `core/lazy_singleton.py`（DCL+RLock），
但一批手写 DCL 单例仍用 `threading.Lock`，偏离规格。

**修复点**（13 处机械替换 `threading.Lock()`→`threading.RLock()`，全为单例创建/复位守卫锁）：
`llm/provider_manager.py:2095`、`llm/providers/capability_detector.py:515,516`、
`llm/providers/multimodal_prober.py:279`、`core/aigc_usage.py:139`、`core/usage_history.py:534`、
`core/annotation_store.py:176`、`knowledge/storage.py:296`、
`cognitive_layers/memory_layer/security.py:710`、`cognitive_layers/memory_layer/manager.py:107`、
`context/env_delta.py:63`、`memory/pending_memory.py:510`、`tool_executor.py:5096`（类级）。

**红灯**：`tests/unit/core/test_dcl_singleton_rlock.py` 新建 13 格（12 参数化模块锁 +
tool_executor 类属性锁），修前实跑 **13 failed**。

**绿灯**：修后同文件 13/13 passed；`test_capability_detector.py` +
`test_capability_cache_single_source.py` 51 格无回归（合计 64 passed）。

**命中点扫荡**：全仓残余 `threading.Lock()` 逐一核对——`secret_store_clean.py:1088`
`_singleton_lock`（文件域外→移交）；其余为实例级方法互斥/字典分桶锁
（`auth/verification_code.py:106`、`auth/invitation_code.py:111`、`channels/attention_budget.py:57`、
`core/agent_run_store.py:536`、`knowledge/datasource_sync.py:42,53`），不是懒建单例创建守卫，
不在本条规格内，未动。

**遗留移交**：`neurova/llm/providers/secret_store_clean.py:1088` Lock→RLock（一行，域外）；
全仓 200+ 手写 DCL 收敛到 `core/lazy_singleton.py` 装饰器形态为独立批次（涉及各模块
复位路径语义，未在本条机械替换口径内）。

---

## 3.2-2 DCL 单例守卫锁 Lock→RLock 收口 ✅（提交 7531e33f3）

**根因**：AGENTS.md §3 要求懒创建型单例走 DCL + `threading.RLock`；13 处手写 DCL
单例守卫锁仍是 `threading.Lock`（重入路径自死锁风险）。单源 `core/lazy_singleton.py`
本就是 DCL+RLock。

**修复点**：13 处机械替换（provider_manager:2095、capability_detector:515,516、
multimodal_prober:279、aigc_usage:139、usage_history:534、annotation_store:176、
knowledge/storage:296、memory_layer/security:710、memory_layer/manager:107、
env_delta:63、pending_memory:510、tool_executor:5096）。

**红灯**：`tests/unit/core/test_dcl_singleton_rlock.py` 新建 13 格，修前 13 failed。
**绿灯**：13/13 passed；capability_detector/capability_cache 套件 64 passed。

**命中点扫荡**：全仓残余逐一核对——`secret_store_clean.py:1088`（域外→移交）；
其余为实例级方法互斥/字典分桶锁，非懒建单例创建守卫，未动。

**遗留移交**：`neurova/llm/providers/secret_store_clean.py:1088` Lock→RLock（一行）；
全仓 200+ 手写 DCL 收敛到 lazySingleton 装饰器形态为独立批次。

---

## 3.2-5 usage_history 建库失败吞异常 ✅ + 3.2-9/3.3-2/3.4-10 db_migration 注册批 ✅
（提交 7531e33f3 前四域 + 708c2c675 后四域）

**根因**：8 个自建表域（usage_history/aigc_usage/annotations/pending_memories/
channel_identity/channel_outbound/approval/evolution_jobs）schema 演进停留在裸
IF NOT EXISTS + 启动期手拼，未登记版本注册表；usage_history 的 `_init_db` 还
`except Exception: pass`——写入持续失败且启动无读数。

**修复点**：8 域全部登记 `core/db_migration`（PRAGMA user_version，对照
`context/eviction_ledger_db.py` 合规范本）并在建库点接 `apply_migrations`：
- usage_history：v1 建表/索引 + v2 旧库补列（原启动期 ALTER 搬进版本链）；
  失败改 ERROR 级诚实暴露（fail-soft 语义保持）
- pending_memory：原 __init__ 六步手拼转 v1 建表废弃旧索引→v2 补列→v3
  堆积收敛+隔离唯一索引；`_migrate_columns` 吞异常 rollback 退役
- approval_manager：`_create_schema` 静态方法退役（SQL 单源迁入注册块）
- 其余四域 v1（outbound 两表同库同域 v1+v2）

**红灯**：`tests/unit/core/test_db_migration_registration_batch.py` 新建 11 格
（8 域注册断言 + 旧库补列 + 建库失败 ERROR 留痕），修前 10 failed
（1 格域未注册时 latest=0 空转，注册后转真判据）。
**绿灯**：11/11 passed；受影响域既有套件 161 passed 无回归。

**live-verify**：见批次末尾统一节。

**命中点扫荡**：审计点名的 6 域 + §3.2-9 三处 + §11 新增命中点 11 全量覆盖；
已注册域（memory/agent_runs/channel_ingress/channel_archive/knowledge_*/
mobile_push/ekb 等）不在本条范围。

**遗留移交**：无。

---

## 3.2-6 dead_letter_queue _is_processed 恒 False ✅（提交 c0ba22d08）

**根因**：`_is_processed` 两段条件嵌套的归并分支全部落 False。重试次数达
`max_retries` 的死信在每次退避窗口到期后都重回 `get_retryable()` 重放面——
重放循环对同一消息反复投递（acp_runtime 复用本队列，活伤）。

**修复点**：`_is_processed` 改与 `retry()` 同源判定（`_retry_count >= max_retries`，
单一事实源两处不漂移）；mark_processed/discard 移出队列的消息天然不进遍历
队列的两个调用方。

**红灯**：`tests/unit/agent/protocols/test_dead_letter_queue_replay.py` 新建 4 格，
修前 2 failed（可控时钟实测：耗尽后窗口再到期 get_retryable 仍含该消息；
get_pending 同样包含）。
**绿灯**：4/4 passed；test_acp_runtime 15 格无回归。

**命中点扫荡**：acp_runtime 仅 dlq.add（重放面消费方是 get_retryable/get_pending
与未来重试循环）；`get_dead_letter_queue` 本就是 lazySingleton 单例（核实非每调新建）。

**遗留移交**：同一 message_id 重复 add 会产生双队列条目（审计未点名，未动）。

---

## 3.2-7 turn_context clear_turn_state 漏清两变量 ✅（提交 c6885763e）

**根因**：teardown 清空清单漏 `_subagent_tool_allowlist_var`（蜂群子代理工具面
白名单跨回合残留→面外工具被结构化拒绝）与 `_tool_call_id_var`（审批回投地址
串轮）。

**修复点**：两变量入 clear_turn_state 清空循环（单一清单，单点收口）。

**红灯**：`tests/unit/core/test_clear_turn_state_full_sweep.py` 新建 2 格，
修前 2 failed。**绿灯**：2/2 passed；test_agent_state_api +
test_agent_turn_session_contract 13 格无回归。

---

## 3.2-8 retriever_adapters _simple_cache 只写不淘汰 ✅（提交 9991e2d12）

**根因**：无界 dict、只写不淘汰——长驻进程随查询多样性单向增长。

**修复点**（教义第 7 条先比后合）：收口到 `core/cache.MemoryCache` 单源
（LRU+TTL+容量+线程安全），capacity=256 / TTL 600s / cleanup_interval=0
（适配器按管线实例构造，不起每实例后台清理线程，TTL 读路径判定）。
既有 BUG#4 三格测试同步改到新 API（同批收口不双跑）。

**红灯**：`tests/unit/agent/test_cache_retriever_adapter_bounded.py` 新建 4 格，
修前 4 failed。**绿灯**：4/4 passed；test_memory_retrieval_bugfix 17 格无回归。

---

## 3.2-13 context 三处死重复/弃用取值 ✅（提交 d36bf6e95，refactor）

semantic_drawer 第二份逐字相同的 `_setReadout`（遮蔽前者）、orchestrator
会话身份回落链重复判定块（第二遍不可达）、builder.py:390 裸
`session.get("agent_id")` 弃用取值——三处纯删除，行为零变化。
验证：tests/unit/context/ 全量 1144 passed 无回归。

---

## 3.2-14 第三方措辞红线 + 未用导入 ✅（提交 22dc7cafa）

**根因**：四文件注释/docstring 以「对照/对齐 ZCode」措辞描述设计来源，
触碰 AGENTS §2 原创性红线；tool_executor.py:19 lazySingleton 导入零使用。

**修复点**：turn_phase.py 模块 docstring（3 处）、resilience.py（1）、
hooks_engine.py（3）、swarm.py（1）全部改本项目自述措辞；删未用导入。
新增全仓扫描守卫 `tests/unit/core/test_originality_wording_guard.py`
（大小写不敏感命中即红；白名单只许缩小不许扩大）。

**红灯**：守卫主格修前 failed（四域内文件全部命中）。**绿灯**：3/3 passed；
turn_phase/hooks/swarm/resilience 相关 96 格无回归。

**命中点扫荡**：全仓 `zcode` 大小写不敏感盘点 8 文件——域内 4 文件全清；
域外 3 文件（security/command_syntax.py、telemetry/__init__.py、
workflow/scripted/__init__.py 同款措辞）+ models/computer.py（`ZCODE` 为
集成后端功能性枚举值，如同 openai/anthropic，非设计引用）登记守卫白名单移交。

**遗留移交**：域外 3 文件措辞清偿（守卫白名单等它们清偿后缩小）。

---

## 3.2-15 voice_pipeline 装配失败仅 debug 吞 ✅（提交 d8eb5d806）

**修复点**：fail-soft 保持；四处装配失败 debug→WARNING 并点名失能后果
（上下文注入/记忆记录/识别/合成），装配结束对失能清单补汇总 WARNING。

**红灯**：`tests/unit/test_voice_pipeline_assembly_honest.py` 新建 2 格，
修前 1 failed。**绿灯**：2/2 passed；邻座 16 passed
（test_process_multimodal 1 失败经 A/B 自证预存）。

---

## 3.3-3 /activation/{id} 恒 200 空壳 ✅（提交 2a5302bb7）

**根因**：读全仓零写入方的全局字典 `_activations`，任意 id 恒 200 返回伪造
零激活。同文件 /decay 已有 P2-6 先例：无生产实现 → 诚实 501。

**修复点**：端点改 501（同口径）；`_activations` 死字典随批退役（只读假源不留）。

**红灯**：`tests/unit/api/test_activation_endpoint_honest.py` 新建 4 格，
修前 4 failed。**绿灯**：4/4 passed；EMS 域邻座 30 格无回归。

**遗留移交**：NeurUI/src/api/modules/memory.ts:1052 getMemoryActivation 前端
调用方（文件域外）应随 501 语义退役或改读真实激活源。

---

## 3.3-4 knowledge/storage API Key 固定盐 ✅（提交 dcfdb0738）

**根因**：`_hash_api_key` 固定盐 "neurova-knowledge-salt"——同一 Key 全库
哈希一致，可离线建彩虹表反查。

**修复点**：改 `<salt>$<digest>` 每条目独立随机盐（secrets.token_hex(16) 随
哈希落盘）；verify 解析盐后 hmac.compare_digest 恒时比较；固定盐时代存量
哈希（无盐前缀）验证一律 False——宁可重配一次 Key，不留可离线比对的旧指纹。
选随机盐而非 Fernet 通道：Fernet（api_key_encrypted）已是凭证主通道（R-7），
哈希面仅剩 has_api_key 存在性旗标消费方，随机盐改动面最小且域内闭合。

**红灯**：`tests/unit/knowledge/test_kb_api_key_salt.py` 新建 5 格，
修前 4 failed。**绿灯**：5/5 passed；knowledge 定向回归 18 passed。

**遗留移交**：verify_api_key 生产零调用（预存观察）；knowledge 全目录跑
超时为预存重测问题（scandir，与本条无关）。

---

## 3.3-5 MemorySecurity 接线进主链 ✅（提交 e437738d1，用户拍板）

**根因**：memory_layer/security.py（731 行）主链零消费——加密/敏感检测零生产
调用、遗忘链被 memory_enhancement 直调 manager.forget 绕过（无访问审计）。

**接线形态**（与认知安全门同姿态：fail-open、默认零内容漂移）：
- `security.py` 新增 `screenForStorage`：检测证据必记；处置按
  `SecurityConfig.sensitive_write_action` 三态——log_only（默认零漂移，
  与认知安全门 observe 同姿态）/ mask（敏感段掩码，正文其余保留，指纹在
  掩码文本上计算保持 dedup 一致）/ encrypt（Fernet 全文，运维显式开启）；
  env `NEUROVA_MEMORY_SECURITY_WRITE_ACTION` 逃生门（非法值回落 log_only）
- `manager.remember` 咽喉接线（remember_with_trace 委托 remember，全部生产方
  一轮覆盖）；证据落 `metadata._security`；安全面故障放行原文
- `memory_enhancement` forget 端点改走 `MemorySecurity.forget_memory` 统一
  入口（带访问审计），直调 manager.forget 旧路退役

**规则单源事实**：MemorySecurity 与认知安全门共用 security/sensitive_info.py
的 SENSITIVE_RULES 同一张表（教义第 6 条无第二张表）。encrypt 态为何默认不开：
整条加密会把嵌入向量/全文索引建在密文上（检索面退化），mask 只掩敏感段——
设计权衡非缺陷。

**红灯**：`tests/unit/memory/test_memory_security_wiring.py` 新建 7 格，
修前 7 failed。**绿灯**：7/7 passed；回归充分性：tests/unit/memory/ 全量
**1211 passed** + API 记忆端点与 agent 邻座 **87 passed**（含 forget 端点
ownership/real_manager 两套），无回归。

**live-verify**：见下节（遗忘链审计留痕由单测覆盖：forget 后 get_access_log
含 FORGET 记录）。

**遗留移交**：encrypt 态的读侧透明解密未接（get_memory/recall 读面 9+ 处
SELECT 直读，接入属每读点解密大手术）——encrypt 显式开启后读面见 Fernet
令牌，需读侧解密批配套。
（勘误：本条提交信息净 LOC 写 +92/−12，numstat 实测生产池 +76/−5
（security +47/−2、manager +19、memory_enhancement +10/−3），以本台账为准。）

---

## 3.3-6 旁路存储隔离面 None 放行 ✅（提交 84e9c0e5d）

**根因**：`_passesIsolation` 对 `isolation_context=None` 直接放行——三层隔离
在"调用方忘传上下文"时整个失效。

**修复点**：None → fail-closed（无身份不给看）。影响面按复核注：主检索不经
本类，query/list_by_tags 无生产调用方，改动限于旁路存储与测试。

**红灯**：`tests/unit/cognitive_layers/memory_layer/test_isolation_fail_closed.py`
新建 4 格，修前 2 failed。**绿灯**：4/4 passed；cognitive_layers/memory_layer
全域 612 passed（1 失败 test_futureNotRecalled 经 A/B 自证预存）。

---

## live-verify 统一节（教义第 4 条）

真实后端（隔离端口 9528，9527 被其他会话常驻进程占用；代理变量已按 AGENTS §0
清理）：

1. **启动读数**（AGENTS §0 复算判据）：`grep -c "\[ERROR\]"` = **0**；
   `Registered router: /v1/providers (Provider API)` 在位（日志 :17）；
   无「端点注册表未全量装载」；`Application startup complete` + health 200。
2. **3.2-1 端到端**：真实创建 ollama provider（base_url=127.0.0.1:9 死端口）→
   `POST /api/v1/providers/r3probe-dead-1/check-connection` → 实测响应
   `{"success":false, "error":"Cannot connect to host 127.0.0.1:9 ...",
   "models_available":0, "metadata":{"provider":"ollama","base_url":"http://127.0.0.1:9"}}`
   ——修复前同链路 success:true + models_available:10（静态清单判活）。探针
   provider 已清理（delete 200）。
3. **3.3-3 端到端**：`GET /api/v1/enhanced-memory-search/activation/test-id`
   （data/.jwt_secret 同口签 access token）→ 实测 **501**
   `{"detail":"记忆激活状态账本未实现（无生产写入方）"}`；`/api/v1/providers`
   → 200（鉴权与路由面健康）。
4. 遗忘链统一入口（3.3-5）：端点级探针需先造记忆再删，由单测覆盖
   （forget ownership/real_manager 两套 + 审计留痕断言，87 格绿）。

探针数据已清理；9528 实例已关停（9527 常驻进程未触碰）。

---

## 预存失败观察（非本批回归，A/B 自证）

- `tests/unit/test_process_multimodal.py::test_process_multimodal_video_maps_to_video_understanding`
  （stash voice_pipeline 改动后仍红）
- `tests/unit/cognitive_layers/memory_layer/test_memory_validity_window.py::TestManagerValidity::test_futureNotRecalled`
  （stash storage.py 改动后仍红）
- tests/unit/knowledge/ 全目录跑超时（scandir 扫描问题，定向套件全绿）

## 会话纪要

15 条认领条目全部修复入库（13 个 fix/feat commit + 1 个 refactor commit +
台账本条）；预存失败 3 处 A/B 自证与本批无关；域外移交 5 项见各条遗留段。

# TODO/Stub 文件清理计划

**日期**: 2026-06-04
**状态**: 执行中

---

## 一、分类统计

| 分类 | 数量 | 处理方式 |
|------|------|----------|
| ORPHAN（无人导入） | ~40 | 直接删除 |
| STUB_CHAIN（仅 stub 互引） | ~80 | 删除 |
| CRITICAL（被真实代码导入） | ~30 | 实现或最小化 |
| 认知图谱将替代 | ~10 | 最小化实现 |

## 二、直接删除清单（ORPHAN + STUB_CHAIN）

### 2.1 记忆层 - ORPHAN 文件
- `memory_layer/emotion_adapter.py` — 无人导入
- `memory_layer/memory_layer.py` — 无人导入

### 2.2 记忆层 - STUB_CHAIN 文件（仅被其他 stub 引用）
- ~~`memory_layer/cache.py`~~ — **已删除**（缓存三本账收成一处 `neurova/core/cache.py`，连同 `neurova/core/cache.py` 旧门面与 `neurova/memory/core/` 包一并退役；判据 `tests/unit/core/test_cacheAccountsMergedIntoOneModule.py`）
- `memory_layer/working_memory.py` — 设计文档明确要删除
- `memory_layer/agent_self.py`
- `memory_layer/bus_event.py`
- `memory_layer/conflict_detector.py`
- `memory_layer/conflict.py`
- `memory_layer/dream_mixin.py`
- `memory_layer/proactive_question.py`
- `memory_layer/auto_classifier.py`
- `memory_layer/auto_context_updater.py`
- `memory_layer/forgetting_recovery.py`
- `memory_layer/explainability_storage_mixin.py`
- `memory_layer/vector_index_manager.py`
- `memory_layer/temporal_knowledge_graph.py`
- `memory_layer/proactive_recall.py`
- `memory_layer/memory_bus.py`
- `memory_layer/memory_stream.py`
- `memory_layer/relation_mixin.py`
- `memory_layer/result_processor.py`
- `memory_layer/search_mixin.py`
- `memory_layer/security.py`
- `memory_layer/version_control.py`
- `memory_layer/compression.py`
- `memory_layer/enhanced_retrieval.py`
- `memory_layer/explainability.py`
- `memory_layer/forgetting_recovery_storage_mixin.py`

### 2.3 记忆层 modules/ 子目录（全 stub）
- `memory_layer/modules/` 下所有 19 个 .py 文件

### 2.4 进化层 - STUB_CHAIN
- `evolution/experience_feedback.py`
- `evolution/skill_improver.py`
- `evolution/skill_encapsulation.py`
- `evolution/tool_weights.py`
- `evolution/tool_lifecycle.py`

### 2.5 执行引擎 - STUB_CHAIN
- `execution_engine/workflow_engine.py`
- `execution_engine/tool_engine.py`
- ~~`execution_engine/plan_orchestrator.py`~~（2026-10-12 退役，台账 §6-166：执行表零注册方 ⇒
  每步必 raise；其唯二真缺的格子已并入 `neurflow/execution_engine.py`，见 §6-157）
- `execution_engine/mcp_manager.py`
- `execution_engine/mcp_client_manager.py`
- `execution_engine/execution_monitor.py`
- `execution_engine/agent_colab.py`

### 2.6 工具层 - STUB_CHAIN
- `tool_layers/tool_logger.py`
- `tool_layers/tool_cache.py`
- `tool_layers/schemas.py`
- `tool_layers/openai_schema.py`
- `tool_layers/mcp_client.py`
- `tool_layers/capability_graph.py`
- `tool_layers/browser_capability.py`

### 2.7 核心层 - STUB_CHAIN / ORPHAN
- ~~`core/cognition_orchestrator.py`~~（2026-10-12 退役，台账 §6-166：零消费者，"周期"按字符串长度
  编内容并把 `success` 写 True；现役对应物见 `docs/09-dev-progress/module_designs/cognition_orchestrator.md`
  顶部的更正说明）
- `core/flow_orchestrator.py`
- ~~`core/plan_orchestrator.py`~~（2026-10-12 退役，台账 §6-166：`set_executor` 零调用 ⇒
  `_execute_single_task` 无条件走 `_simulate_task_execution`；`adjust_plan` 无写入方 ⇒ 死格）
- `core/state_manager.py`
- `core/task_tracker.py`
- `core/firewall.py`
- `core/intrinsic_motivation.py`
- `core/multi_agent_manager.py`
- `core/service_manager.py`
- `core/timezone_manager.py`
- `core/user_workspace.py`
- `core/settings_manager.py`

### 2.8 安全层 - STUB_CHAIN
- `security/tool_guard.py`
- `security/skill_scanner.py`
- `security/compliance_reporter.py`
- `security/cognitive_security.py`
- `security/api_keys.py`

### 2.9 LLM 层 - STUB_CHAIN
- `llm/providers/litellm_provider.py`
- `llm/providers/rate_limiter.py`
- `llm/config_console.py`

### 2.10 技能系统 - STUB_CHAIN
- `skills/task_decomposer.py`
- `skills/skill_need_analyzer.py`
- ~~`skills/security_scanner.py`~~ —— 已删除（2026-10-13 批 38，台账 §6-194）：与
  `security/skill_scanner.py` 同功能的第二套实装且零生产消费者；名称级凭据/可执行产物检查
  两项能力已重造进那一处，其 `SkillSandbox` 经查是假沙箱（内存上限取了从不使用、无 rlimit
  与网络隔离、每次留一个未回收的临时目录），不接生产
- `skills/market_searcher.py`
- `skills/market_adapt.py`
- ~~`skill/skill_packer.py`~~ —— 已删除（2026-09-17 P2 收口，Issue #46）：零生产调用，
  且产物不经过证据闸；专用测试 `tests/skill/*` 同步移除

### 2.11 其他 STUB_CHAIN
- ~~`shared_core/plan_orchestrator.py`~~ —— 已删除（2026-10-09 序 5 批 D，台账 §6-115）：四个
  handler 只回名字字典、一次 LLM/工具调用都不发，生产与测试两侧 import 复算均为 0
- `shared_core/infrastructure.py`
- `shared_core/execution_engine.py`
- ~~`plugins/plugin_manifest.py`~~、~~`plugins/plugin_manager.py`~~、
  ~~`plugins/plugin_lifecycle.py`~~、~~`plugins/base_plugin.py`~~、
  ~~`plugins/plugin_api_registry.py`~~ —— **本条已作废**：2026-10-10 裁「不做插件体系」并落地
  `e95d3a76`（包 2206 行整批删除），同日 2026-10-11 用户改裁「做插件体系并接线」，
  包体连同其专用测试按历史版本取回、`/v1/plugins` 端点改走真动态装载（落地 `fed108a0`，台账 §6-150）。
  因此这里不再是"已删除"，而是一段**被推翻的裁定**：留原文与划线的意义在于它记着
  "删掉的是能力不是残留"这个判断本身没错——错的是那次裁定，不是那次取证。
  当时那句"唯一实装在 `plugin_manager.py:377-384`"经复算成立，但取回后实测又发现该实现
  自己也跑不通（`plugin_class()` 无参构造 vs `BasePlugin.__init__(self, manifest)`），
  已随接线的同一批改掉。防再生判据 `tests/unit/plugins/test_pluginSystemRetired.py`
  随裁定撤销一并删除，换成钉"装载是真的、边界是真的"的 `test_pluginLoadIsReal.py`
- `performance.py`
- `error_logger.py`
- `shared_config.py`
- `memory_rw_manager.py`
- `agent_config.py`
- ~~`context_compressor.py`~~（已于 B6-10 批次 C 整模块退役）
- `context_cache.py`
- `tts/moss_nano.py`
- `tts/mock_tts_simple.py`
- `media/manager.py`
- `media/config.py`
- `language/models.py`
- `language/manager.py`
- `knowledge/storage.py`
- ~~`knowledge/rag/enhanced_retrieval.py`~~ ✅ 已清理
- `analytics/models.py`
- `analytics/collector.py`
- `computer_use/vision_lite.py`
- `computer_use/vision_basic.py`
- `computer_use/vision.py`
- ~~`api/communication_protocol.py`~~ ✅ 已退役（2026-10-05）：版本协商/载荷上限/在线态派生
  抽为 `api/external_agent_protocol.py`，限流改接 `core/firewall` 的 externalAgent 档，
  由 `endpoints/agent_communication_api.py` 消费；专用测试两份随文件一并退。
- `api/api_key_manager.py`
- `benchmark/__init__.py`
- `auth.py` (根级)
- `auth/verification_code.py`
- `auth/user_group_model.py`
- `auth/password_hasher.py`
- `auth/invitation_code.py`

## 三、CRITICAL 文件 — 需实现或最小化

### 3.1 认知图谱将替代 → 最小化实现
| 文件 | 导入者 | 最小化策略 |
|------|--------|-----------|
| `tool_memory_integration.py` | agent_core.py, mem_core.py | 实现 check_tool_memory/record_tool_usage 核心逻辑 |
| `experience_caller.py` (evolution) | agent_core.py | 实现 record_experience/find_similar 核心逻辑 |
| `pattern_miner.py` | closed_loop.py | 实现占位（返回空） |
| `genetic_engine.py` | closed_loop.py | 实现占位（返回空） |
| `nl_synthesizer.py` | closed_loop.py | 实现占位（返回空） |

### 3.2 不受认知图谱影响 → 需完整实现
| 文件 | 导入者 | 实现复杂度 |
|------|--------|-----------|
| `core/logger.py` | 全项目 | 低 |
| `core/config_manager.py` | 多处 | 低 |
| `core/file_utils.py` | 多处 | 中 |
| `core/attachment_manager.py` | memory API | 中 |
| `core/error_handler.py` | 多处 | 低 |
| `core/api_standard.py` | API | 低 |
| `core/api_router.py` | API | 低 |
| `core/module_lib.py` | module system | 低 |
| `core/module_tracker.py` | module system | 低 |
| `security/auth_system.py` | auth API | 中 |
| `security/audit_logger.py` | auth | 中 |
| `security/rbac.py` | auth | 中 |
| `security/data_masking.py` | auth | 低 |
| `security/approval_manager.py` | auth | 中 |
| `llm/providers/base.py` | LLM system | 中 |
| `llm/providers/secret_store.py` | LLM providers | 中 |
| `llm/providers/multimodal_prober.py` | provider API | 低 |
| `llm/providers/capability_detector.py` | provider API | 低 |
| `llm/providers/capability_cache.py` | provider API | 低 |
| `llm/presets.py` | LLM config | 低 |
| `llm/model_route_config.py` | LLM router | 低 |
| `llm/generators/base.py` | generators | 低 |
| `emotion.py` | emotion API | 中 |
| `vector_search_advanced.py` | synonym API | 中 |
| `muscle_memory.py` | agent_core | 中 |
| `working_memory.py` | mem_core | 低 |

## 四、执行顺序

1. **Phase 1**: 删除 ORPHAN + STUB_CHAIN 文件（~120 个）
2. **Phase 2**: 修复 __init__.py 导出（删除对已删文件的引用）
3. **Phase 3**: 最小化实现 CRITICAL 文件（认知图谱将替代的）
4. **Phase 4**: 完整实现 CRITICAL 文件（不受影响的）
5. **Phase 5**: 验证 — 运行导入测试确保系统可启动

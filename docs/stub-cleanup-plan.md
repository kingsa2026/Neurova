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
- `memory_layer/cache.py` — 设计文档明确要删除
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
- `execution_engine/plan_orchestrator.py`
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
- `core/cognition_orchestrator.py`
- `core/flow_orchestrator.py`
- `core/plan_orchestrator.py`
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
- `skills/security_scanner.py`
- `skills/market_searcher.py`
- `skills/market_adapt.py`
- `skill/skill_packer.py`

### 2.11 其他 STUB_CHAIN
- `shared_core/plan_orchestrator.py`
- `shared_core/infrastructure.py`
- `shared_core/execution_engine.py`
- `plugins/plugin_manifest.py`
- `plugins/plugin_manager.py`
- `plugins/plugin_lifecycle.py`
- `performance.py`
- `error_logger.py`
- `shared_config.py`
- `memory_rw_manager.py`
- `agent_config.py`
- `context_compressor.py`
- `context_cache.py`
- `tts/moss_nano.py`
- `tts/mock_tts_simple.py`
- `media/manager.py`
- `media/config.py`
- `language/models.py`
- `language/manager.py`
- `knowledge/storage.py`
- `knowledge/rag/enhanced_retrieval.py`
- `analytics/models.py`
- `analytics/collector.py`
- `computer_use/vision_lite.py`
- `computer_use/vision_basic.py`
- `computer_use/vision.py`
- `api/communication_protocol.py`
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

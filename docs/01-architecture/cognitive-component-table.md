# 认知层 · 现役组件表（机器生成）

> **状态**: **[权威] 认知层现役组件表**（`docs/INDEX.md` 认知层）。**由代码生成，不手维护**：
> 生成器 `scripts/ci/cognitive_component_table.py`，判据
> `tests/unit/ci/test_cognitiveComponentTable.py` 逐字比对本文件的机读区，并抽样与
> `tests/ast_scan.importersOfModule`（单目标取数口）交叉验证。**最后生成**: 2026-10-20。
>
> 为什么有它：`NEUROVA_CogArch_2.0.md` §8.2 是 2026-05-12 的手工映射表，2026-10-20 复算
> 70 条路径里 **44 条已不存在**（台账 §6-362）。CogArch 已降为沿革档，认知层"今天有什么、
> 谁在读它"以本表为准。本表**只回答现状**，不代替设计文档。

## 口径

- **组件**＝`neurova/cognitive_layers/` 下跟踪态的 `.py`（不含 `__init__.py`）。
- **层外读者**＝`neurova/` 内、但在 `neurova/cognitive_layers/` 之外的导入者文件数；
  **层内读者**＝同层内、该模块自身之外的导入者文件数；**测试读者**＝`tests/` 内的导入者文件数。
  读者按**文件**去重，认四种导入形（含相对形与父包取名形），由 `tests/ast_scan` 的解析入口给出。
- **状态**：`在役`（层外读者 ≥1）／`仅层内`（只被同层读）／`仅测试`／`零读者`。
  把"层外"单列，是因为**被同层读只证明内部接线，不证明在服**（台账 §6-359／§6-360 的教训）。
- 本文件是聚合索引（单趟建边）；**单目标判定请用 `ast_scan.importersOfModule`**，不要拿本表当判据取数口。

## 摘要

<!-- COGNITIVE:SUMMARY:BEGIN -->
共 **106** 个模块 / **45375** 行。按状态：**在役 55** · **仅层内 39** · **仅测试 6** · **零读者 6**。

| 子层 | 模块数 | 行数 |
|---|---|---|
| `emotion_context_layer` | 4 | 2300 |
| `growth_layer` | 1 | 813 |
| `knowledge_graph` | 1 | 1259 |
| `memory_layer` | 95 | 38731 |
| `meta_cognition_layer` | 5 | 2272 |
<!-- COGNITIVE:SUMMARY:END -->

## 组件表

<!-- COGNITIVE:TABLE:BEGIN -->

### `emotion_context_layer`

| 模块 | 行数 | 层外读者 | 层内读者 | 测试读者 | 状态 |
|---|---|---|---|---|---|
| `neurova/cognitive_layers/emotion_context_layer/emotion.py` | 359 | 1 | 0 | 2 | 在役 |
| `neurova/cognitive_layers/emotion_context_layer/emotion_conduction.py` | 342 | 1 | 0 | 2 | 在役 |
| `neurova/cognitive_layers/emotion_context_layer/emotion_hub_engine.py` | 647 | 0 | 2 | 2 | 仅层内 |
| `neurova/cognitive_layers/emotion_context_layer/time_awareness.py` | 952 | 1 | 0 | 1 | 在役 |

### `growth_layer`

| 模块 | 行数 | 层外读者 | 层内读者 | 测试读者 | 状态 |
|---|---|---|---|---|---|
| `neurova/cognitive_layers/growth_layer/analyzer.py` | 813 | 2 | 0 | 4 | 在役 |

### `knowledge_graph`

| 模块 | 行数 | 层外读者 | 层内读者 | 测试读者 | 状态 |
|---|---|---|---|---|---|
| `neurova/cognitive_layers/knowledge_graph/manager.py` | 1259 | 5 | 1 | 16 | 在役 |

### `memory_layer`

| 模块 | 行数 | 层外读者 | 层内读者 | 测试读者 | 状态 |
|---|---|---|---|---|---|
| `neurova/cognitive_layers/memory_layer/absence_reasoner.py` | 145 | 1 | 1 | 5 | 在役 |
| `neurova/cognitive_layers/memory_layer/agent_self.py` | 524 | 1 | 0 | 0 | 在役 |
| `neurova/cognitive_layers/memory_layer/attachment_manager.py` | 978 | 1 | 0 | 1 | 在役 |
| `neurova/cognitive_layers/memory_layer/auto_classifier.py` | 596 | 0 | 2 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/bayesian_eki/cognitive_optimizer.py` | 479 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/bus_event.py` | 44 | 0 | 1 | 0 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/cascade_engine.py` | 226 | 1 | 1 | 4 | 在役 |
| `neurova/cognitive_layers/memory_layer/causal_reasoning.py` | 349 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/base.py` | 79 | 0 | 12 | 8 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/builtin/category.py` | 54 | 0 | 1 | 0 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/builtin/emotion.py` | 76 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/builtin/graph.py` | 259 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/builtin/temperature.py` | 53 | 0 | 1 | 0 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/builtin/text.py` | 61 | 0 | 1 | 0 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/builtin/voice.py` | 66 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/centroid.py` | 53 | 0 | 1 | 2 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/conflict.py` | 100 | 0 | 2 | 3 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/moe_router.py` | 178 | 0 | 0 | 3 | 仅测试 |
| `neurova/cognitive_layers/memory_layer/channels/processor.py` | 107 | 0 | 1 | 3 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/registry.py` | 91 | 0 | 4 | 5 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/temporal.py` | 68 | 0 | 2 | 3 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/threshold.py` | 46 | 0 | 1 | 3 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/channels/weight.py` | 62 | 0 | 1 | 3 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py` | 532 | 2 | 4 | 23 | 在役 |
| `neurova/cognitive_layers/memory_layer/compression.py` | 1039 | 1 | 1 | 2 | 在役 |
| `neurova/cognitive_layers/memory_layer/conflict.py` | 260 | 1 | 1 | 4 | 在役 |
| `neurova/cognitive_layers/memory_layer/conflict_detector_v2.py` | 265 | 0 | 1 | 2 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/conversation_buffer.py` | 434 | 2 | 2 | 13 | 在役 |
| `neurova/cognitive_layers/memory_layer/conversation_rule_extractor.py` | 184 | 1 | 0 | 1 | 在役 |
| `neurova/cognitive_layers/memory_layer/dependency_graph.py` | 495 | 2 | 3 | 5 | 在役 |
| `neurova/cognitive_layers/memory_layer/emotion.py` | 452 | 3 | 1 | 1 | 在役 |
| `neurova/cognitive_layers/memory_layer/emotion_adapter.py` | 241 | 0 | 0 | 0 | 零读者 |
| `neurova/cognitive_layers/memory_layer/experience_memory_fusion.py` | 188 | 1 | 0 | 2 | 在役 |
| `neurova/cognitive_layers/memory_layer/explainability.py` | 646 | 0 | 0 | 0 | 零读者 |
| `neurova/cognitive_layers/memory_layer/forgetting_recovery_storage_mixin.py` | 347 | 0 | 0 | 0 | 零读者 |
| `neurova/cognitive_layers/memory_layer/graph_traversal.py` | 587 | 1 | 2 | 6 | 在役 |
| `neurova/cognitive_layers/memory_layer/isolation.py` | 204 | 0 | 5 | 10 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/manager.py` | 4622 | 14 | 0 | 90 | 在役 |
| `neurova/cognitive_layers/memory_layer/memory_exporter.py` | 271 | 1 | 0 | 1 | 在役 |
| `neurova/cognitive_layers/memory_layer/memory_index.py` | 277 | 0 | 0 | 2 | 仅测试 |
| `neurova/cognitive_layers/memory_layer/memory_record_store.py` | 196 | 0 | 0 | 1 | 仅测试 |
| `neurova/cognitive_layers/memory_layer/memory_stream.py` | 235 | 1 | 0 | 1 | 在役 |
| `neurova/cognitive_layers/memory_layer/meta_cognition.py` | 633 | 1 | 0 | 2 | 在役 |
| `neurova/cognitive_layers/memory_layer/models.py` | 522 | 6 | 10 | 38 | 在役 |
| `neurova/cognitive_layers/memory_layer/modules/auto_context_module.py` | 255 | 0 | 1 | 0 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/modules/buffer_module.py` | 329 | 1 | 1 | 3 | 在役 |
| `neurova/cognitive_layers/memory_layer/modules/classifier_module.py` | 231 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/modules/conflict_module.py` | 327 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/modules/eki_module.py` | 304 | 0 | 1 | 0 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/modules/emotion_conduction_module.py` | 233 | 0 | 0 | 0 | 零读者 |
| `neurova/cognitive_layers/memory_layer/modules/emotion_module.py` | 451 | 4 | 1 | 13 | 在役 |
| `neurova/cognitive_layers/memory_layer/modules/explainability_module.py` | 269 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/modules/forgetting_recovery_module.py` | 237 | 0 | 1 | 0 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/modules/meta_cognition_module.py` | 301 | 0 | 1 | 2 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/modules/relation_module.py` | 321 | 0 | 1 | 0 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/modules/self_manager_module.py` | 251 | 0 | 1 | 0 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/modules/self_model_module.py` | 183 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/modules/sleep_module.py` | 310 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/modules/tkg_module.py` | 284 | 0 | 1 | 4 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/modules/working_memory_module.py` | 249 | 0 | 1 | 0 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/moe_dependency_extractor.py` | 287 | 1 | 2 | 5 | 在役 |
| `neurova/cognitive_layers/memory_layer/moe_router.py` | 432 | 1 | 2 | 6 | 在役 |
| `neurova/cognitive_layers/memory_layer/muscle_memory.py` | 815 | 1 | 0 | 11 | 在役 |
| `neurova/cognitive_layers/memory_layer/neuHebb_curator.py` | 156 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/neuHebb_forge.py` | 288 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/neuHebb_manager.py` | 242 | 1 | 0 | 3 | 在役 |
| `neurova/cognitive_layers/memory_layer/neurova_hebb.py` | 228 | 1 | 3 | 6 | 在役 |
| `neurova/cognitive_layers/memory_layer/neurova_recall.py` | 1888 | 1 | 1 | 12 | 在役 |
| `neurova/cognitive_layers/memory_layer/pattern_crystallizer.py` | 670 | 3 | 1 | 16 | 在役 |
| `neurova/cognitive_layers/memory_layer/persist_landing.py` | 28 | 1 | 1 | 3 | 在役 |
| `neurova/cognitive_layers/memory_layer/pollution_purge.py` | 349 | 0 | 0 | 2 | 仅测试 |
| `neurova/cognitive_layers/memory_layer/positional_encoding.py` | 291 | 0 | 1 | 3 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/proactive_question.py` | 940 | 0 | 0 | 0 | 零读者 |
| `neurova/cognitive_layers/memory_layer/question_decomposer.py` | 311 | 0 | 1 | 1 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/reasoning_trace_manager.py` | 208 | 1 | 1 | 5 | 在役 |
| `neurova/cognitive_layers/memory_layer/relation_mixin.py` | 400 | 0 | 0 | 0 | 零读者 |
| `neurova/cognitive_layers/memory_layer/security.py` | 809 | 1 | 0 | 2 | 在役 |
| `neurova/cognitive_layers/memory_layer/semantic_emotion.py` | 121 | 1 | 0 | 2 | 在役 |
| `neurova/cognitive_layers/memory_layer/semantic_search.py` | 314 | 1 | 3 | 10 | 在役 |
| `neurova/cognitive_layers/memory_layer/settings_config.py` | 347 | 4 | 3 | 8 | 在役 |
| `neurova/cognitive_layers/memory_layer/share_group.py` | 314 | 1 | 1 | 2 | 在役 |
| `neurova/cognitive_layers/memory_layer/sleep.py` | 1137 | 6 | 0 | 39 | 在役 |
| `neurova/cognitive_layers/memory_layer/sleep_writeback.py` | 121 | 2 | 1 | 10 | 在役 |
| `neurova/cognitive_layers/memory_layer/storage.py` | 717 | 1 | 3 | 19 | 在役 |
| `neurova/cognitive_layers/memory_layer/temperature.py` | 564 | 3 | 4 | 12 | 在役 |
| `neurova/cognitive_layers/memory_layer/temporal_knowledge_graph.py` | 449 | 1 | 0 | 4 | 在役 |
| `neurova/cognitive_layers/memory_layer/temporal_reasoner.py` | 636 | 0 | 0 | 1 | 仅测试 |
| `neurova/cognitive_layers/memory_layer/tool_memory_integration.py` | 536 | 2 | 0 | 13 | 在役 |
| `neurova/cognitive_layers/memory_layer/unified_retriever.py` | 161 | 1 | 1 | 3 | 在役 |
| `neurova/cognitive_layers/memory_layer/unified_vector_store.py` | 941 | 3 | 4 | 17 | 在役 |
| `neurova/cognitive_layers/memory_layer/vector_index_manager.py` | 431 | 0 | 0 | 1 | 仅测试 |
| `neurova/cognitive_layers/memory_layer/vector_search.py` | 726 | 1 | 0 | 2 | 在役 |
| `neurova/cognitive_layers/memory_layer/version_control.py` | 618 | 1 | 0 | 0 | 在役 |
| `neurova/cognitive_layers/memory_layer/volume_renderer.py` | 282 | 0 | 2 | 2 | 仅层内 |
| `neurova/cognitive_layers/memory_layer/working_memory.py` | 115 | 2 | 0 | 2 | 在役 |

### `meta_cognition_layer`

| 模块 | 行数 | 层外读者 | 层内读者 | 测试读者 | 状态 |
|---|---|---|---|---|---|
| `neurova/cognitive_layers/meta_cognition_layer/growth_log.py` | 595 | 6 | 1 | 8 | 在役 |
| `neurova/cognitive_layers/meta_cognition_layer/ledger.py` | 415 | 4 | 4 | 12 | 在役 |
| `neurova/cognitive_layers/meta_cognition_layer/proactive_behavior.py` | 105 | 1 | 0 | 2 | 在役 |
| `neurova/cognitive_layers/meta_cognition_layer/question_queue.py` | 577 | 4 | 1 | 5 | 在役 |
| `neurova/cognitive_layers/meta_cognition_layer/self_model.py` | 580 | 4 | 1 | 11 | 在役 |

<!-- COGNITIVE:TABLE:END -->

## 复算

```bash
python scripts/ci/cognitive_component_table.py            # 打印两个机读区
python scripts/ci/cognitive_component_table.py --write    # 写回本文件
.venv/Scripts/python.exe -m pytest -p no:cacheprovider \
    tests/unit/ci/test_cognitiveComponentTable.py          # 判据（含抽样交叉验证）
```

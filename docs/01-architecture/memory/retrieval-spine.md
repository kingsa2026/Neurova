# 记忆检索脊柱（现役架构）

> **状态**: **[权威] 检索脊柱**（`docs/INDEX.md` 记忆层）。**只写在服的那条链**；
> 计划与未接线另列第 5 节。**最后复核**: 2026-10-20（行号按当日代码；复算方式见第 7 节）。
>
> 为什么单独立这一份：INDEX 原先标为「[权威] 记忆升级」的
> `docs/04-plans/memory-system-upgrade-plan-final.md` 全文不含 `MoE`／`通道插件`／`Phase`
> （289 行 0 命中），今天真正在跑的检索脊柱在那份文档里没有设计描述（台账 §6-362）。

## 1. 入口与装配

| 环节 | 落点 | 说明 |
|---|---|---|
| 检索引擎 | `cognitive_layers/memory_layer/neurova_recall.py:567` `NeurovaRecallEngine` | 记忆读取的总入口 |
| 主入口 | `:703` `recall()` ／ `:777` `recall_flat()` | 两条返回形状不同，共用同一套通道与打分 |
| 意图检测 | `:119` `QueryIntentDetector`、`:370` `IntentAwareRecallStrategy` | `recall()` 在 `:733-734` 取通道权重与检索参数 |

## 2. 通道插件（live）

- **注册表**：`channels/registry.py:16` `ChannelRegistry`（进程内单例）。
- **装配**：`neurova_recall.py:615-626`——`use_plugins` 打开且注册表为空时，把
  `channels/builtin/__init__.py` 的 `BUILTIN_CHANNELS` 逐个实例化并注册。
- **六个内置通道**：`TemperatureChannel` / `TextChannel` / `CategoryChannel` /
  `GraphChannel` / `EmotionChannel` / `VoiceChannel`（`channels/builtin/`）。
- **取用**：`neurova_recall.py:954-955` 按 `ch.metadata.name ∈ enabled_names` 选出启用通道，
  并发跑各自的 `retrieve()`。
- **激活**：`NeurovaRecallEngine._ensurePluginChannelsReady()`——生产没有启动钩子调用
  `ChannelRegistry.initialize_all()`，注册后的通道长期 INACTIVE、`get_active()` 恒空
  ⇒ 插件召回恒空。首次召回时补一次幂等初始化（§6-377 活体取证并根修）。

## 3. 合并、打分、排序（live）

- **去重**：`neurova_recall.py:921`（`recall_flat` 在 `:1019`）调 `_deduplicate_results():1586`
  （按 `memory_id` 保留高分）。
- **融合打分**：`:928`（`recall_flat` 在 `:1021`）调 `_fusion_score():1439`，
  入参含通道权重与查询；具体因子以该函数为准（不在此复制实现，避免第二份口径）。

## 4. expert MoE（live）

- **构造与挂载**：`neurova/mem_core.py:824` 构造 `MoEMemoryRouter`，`:925` 挂到 agent 的
  `_moe_router`。
- **检索路上**：`neurova/agent/chat_pipeline.py:252-254` 取该 router 包成
  `retriever_adapters.MoERetrieverAdapter` 使用。
- **质心**：`cognitive_layers/memory_layer/moe_router.py:350` 调
  `unified_vector_store.initialize_centroids(experts)`——这是该方法的**唯一生产者**。
- **门控阈值**：全局 `threshold.default`（`memory_layer/settings_config.py:105`）经
  `mem_core.py:818` 喂进 expert 门控。

## 5. 已处置的旋钮（不再列在脊柱上）

四件曾未接线的旋钮已有结论：

| 旋钮 | 结论 | 现役承担者 / 放弃点 |
|---|---|---|
| 反馈驱动的通道权重 | **已接线**（§6-377） | `IntentAwareRecallStrategy.applyFeedback` 写回意图权重并落盘；读侧仍是 `get_channel_weights` |
| per-channel 阈值覆盖 | **显式放弃**（§6-378） | 保留全局 `threshold.default`（expert 门控）；per-channel 表无消费者 |
| 插件通道质心自动生成 | **显式放弃**（§6-378） | expert 质心仍由 `unified_vector_store.initialize_centroids` 生成；通道描述质心无消费者 |
| 统一结果管道 | **显式放弃**（§6-378） | 去重/加权/时间衰减已由 live 的 `_deduplicate_results`/`_fusion_score`/`_recency_score` 承担；内联冲突判据已并入 `judgeClauseConflict`（§6-374），`activations` 乘子无生产者 |

> `channels/weight.py` 的动态能力由 §6-377 的写侧接管；`channels/temporal.py` 的可配置曲线
> 与 `channels/moe_router.py` 的按查询门控随同族一并显式放弃——它们从未有生产消费者。
> 端点 `/channel-weights` 的第三份硬编码表已改读 live `intent_strategy`（§6-378）。
> **2026-10-21（§6-373）**：§6-371 的退役已撤回，四旋钮恢复在位；去留按教义 7 重做
> （先取长补短再退役），本表重新生效。
> **2026-10-21（§6-374）**：`channels/conflict.py` 的否定检测已并入单源
> `judgeClauseConflict`（含英文词级否定），随后退役；`channels/processor.py` 的冲突段改调单源。

## 6. 一处同名不同物（别当双源）

`neurova/channels/plugin_channels.py` 的 `PluginChannelRegistry` 是**消息渠道**（微信/Telegram/QQ 等）
插件面，服务于 `api/endpoints/channel_config.py`；与本节第 2 条的**记忆检索** `ChannelRegistry`
同名不同物，不是第二份注册表。

## 7. 复算方式

本文所有行号都可用一条命令复算（不复制实现，避免文档成为第二事实源）：

```bash
grep -n "^class NeurovaRecallEngine\|def recall(\|def _fusion_score\|def _deduplicate_results\|BUILTIN_CHANNELS\|enabled_names" \
  neurova/cognitive_layers/memory_layer/neurova_recall.py
grep -n "MoEMemoryRouter\|initialize_centroids\|threshold.default" -r neurova/mem_core.py neurova/cognitive_layers/memory_layer/
```

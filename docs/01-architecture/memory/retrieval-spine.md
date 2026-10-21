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

## 5. 未接线的旋钮（**不是**脊柱的一部分）

这四件在同一包内、结构完整，但**没有插进上面那条链**（§6-360 逐档档案）：

| 旋钮 | 文件 | 今天缺的那半边 |
|---|---|---|
| per-channel 阈值覆盖 | `channels/threshold.py` | 只有全局 `threshold.default`，且只作用于 expert 门控 |
| 反馈驱动的通道权重 | `channels/weight.py` | 权重是两份手抄静态表；无人写回 |
| 插件通道质心自动生成 | `channels/centroid.py` | 质心只按 Expert 定义表建 |
| 统一结果管道 | `channels/processor.py` | 内联语义冲突检测未进 live 链；`activations` 乘子无生产者 |

它们的去留见台账 §6-361 的"四旋钮接不接"（等裁）。
> **2026-10-21（§6-373）**：§6-371 的退役已撤回，四旋钮恢复在位；去留按教义 7 重做
> （先取长补短再退役），本表重新生效。

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

# ADR 0018: 记忆分类词汇表唯一事实源（分类引擎只有一套枚举）

- **Status**: Accepted
- **Date**: 2026-09-21
- **Decision Maker**: Issue #68 分类闭环收口

## Context

Issue #68 的三个现象指向同一个病根：**记忆分类的值域有三份，且没有一份是权威的。**

1. **文档口径与实现不符**。仓库 25 处文档（`CONTEXT.md`、`0-index/README.md`、
   `01-architecture/01-core-architecture.md`、`data-flow-analysis.md`、ADR 0003 等）
   把"17 维记忆分类"当既定事实陈述。实测（`architecture-findings.md` u1）：
   「17」只能凑自 `auto_classifier.py:27/39/50` 三个**私有枚举**的
   7+6+4，且 `01-core-architecture.md` 里那 17 个"短期/长期/社交/空间/创造性/
   元认知/集体/进化记忆"在代码中**一个都没有对应枚举值**。
2. **唯一分类器是死码**。`MemoryAutoClassifier`（带上面三个私有枚举 + 一整套
   正则规则）全仓**零消费者**：`manager._auto_classifier` 建了没人读。生产真正
   被调用的只有 `modules/classifier_module.py` 的 **6 个硬编码关键词桶**
   （personal / work / knowledge / conversation / emotion / technical）——它与
   落库的 `MemoryCategory`（general / conversation / knowledge / experience /
   tool_usage / reflection / user_preference）**既不同名也不同集**：
   `general` 只在兜底分支里被 append，`experience`/`reflection`/`user_preference`/
   `tool_usage` 四个真实枚举值**永远认不出来**，而 personal/work/technical 三个
   桶**没有对应的枚举值可落**。
3. **`remember()` 不自动分类**。`auto_classify` 只出现在 `manager.py` 的注释
   （"控制参数(留 kwargs)"）里，没有任何分支消费它；`AddMemoryRequest.auto_classify`
   默认 True 一路传到 `remember` 的 kwargs 黑洞后消失。于是库里 99% 的行是 general。
4. **声称能分类的 API 恒 500**。`api/endpoints/memory/eki.py:102` 以
   `classify_memory(content, context)` 两参调用一参签名的方法，并按
   `result["category"][0]` 取值（真实返回是 `{"memory_id","categories","tags"}`）。
   TypeError 与 KeyError 叠加 ⇒ `POST /memory/classify` 必 500，因为**没有任何
   测试覆盖它**，坏了一整个版本周期无人发现。

## Decision

**分类值域只有一处：`memory_layer/models.py` 的枚举。**

```
MemoryType (7)          semantic / episodic / procedural / pattern /
                        emotional / working / workflow_experience
MemoryCategory (7)      general / conversation / knowledge / experience /
                        tool_usage / reflection / user_preference
MemoryPerspective (4)   first_person / second_person / third_person / system
```

关键设计：

1. **枚举身份唯一**。`auto_classifier.py` 不再定义 `CategoryType` /
   `MemoryTypeEnum` / `PerspectiveType`，改为**别名导入** models.py 的枚举
   （`CategoryType is MemoryCategory` 由测试用 `is` 断言锁死，不只是"值相同"）。
   任何重新定义第二套值域的做法都会变红。
2. **引擎唯一**。`MemoryAutoClassifier` 是唯一分类引擎，`manager._ensure_auto_classifier()`
   与 `ClassifierModule.classify` 都走它。`ClassifierModule` 收敛为**有状态面**
   （memory_id → categories/tags 缓存 + 检索 + 标签抽取），它那 6 个硬编码桶删除；
   `add_category_rule` 仍可用，但值域锁在 MemoryCategory 内（非法分类名显式
   `ValueError`，不再允许建无对应枚举的桶）。
3. **`remember()` 真接线自动分类**。`auto_classify` / `classification_context`
   从 kwargs 黑洞升为显式形参；`category` / `memory_type` 默认值由
   `"general"/"semantic"` 改为 `None`（= 未声明）。**只补未声明项**：显式声明的
   维度不覆盖，推断项落 `metadata["_auto_classified"]`（inferred 清单 + 置信度 + 依据）。
   默认 False：管线/睡眠写回等既自行标好类型的调用方行为不变；API 侧默认 True。
4. **分类可观测**。`get_stats()` 增 `by_category` / `by_memory_type` /
   `auto_classified_count` / `unknown_category_count`（与工单 012 的
   `unknown_memory_type_count` 同纪律）。"库里 99% 是 general"从此有读数可查。
5. **API 契约与实现对齐**。`MemoryManager.classify_memory(content, context)` 的返回
   与 `ClassifyMemoryResponse` 逐字段对齐（值为字符串 + 独立置信度列），端点只透传。

**文档口径裁决**：「17 维」不存在于代码，也不在本 ADR 采纳。分类维度以
`models.py` 枚举为准（7 类型 + 7 分类 + 4 视角，另有 LifecycleStage 5 / EmotionType 9
属状态与情感维度，不是"分类"）。引用该数字的文档按本 ADR 逐个修正。

## Consequences

**正向**
- 新增分类值只需改 models.py 一处，引擎/缓存/API/前端页签自动对齐；
- `remember(auto_classify=True)` 的分类结果可复现、可审计（证据落 metadata）；
- 坏端点恢复（`/memory/classify` 与 `/memory/classify-and-remember` 都 200 且真落分类）；
- 分类分布进入 stats，为后续"分类质量"指标留了读数入口。

**负向 / 代价**
- `remember()` 的 `category`/`memory_type` 默认值语义变化（None = 未声明）。
  已核对：`auto_classify=False` 时仍回落 general/semantic，与历史默认值逐字节等价，
  故对既有调用方是零行为变化；只有显式开 `auto_classify` 的路径会得到非 general 值。
- `ClassifierModule.classify` 的返回值从"6 桶之一/多个"变为 MemoryCategory 值域，
  历史上依赖 personal/work/technical 字面量的消费方需改（本仓无此类消费方，
  由 `test_classification_closed_loop.py::TestClassifierModuleVocabulary` 锁死）。

**验证**
- `tests/unit/cognitive_layers/memory_layer/test_classification_closed_loop.py`（24 条）
  与 `tests/unit/api/test_memory_classify_endpoint.py`（8 条）：修复前 26 红，
  修复后 32 绿（stash A/B 实测）。
- `tests/unit/memory` + `tests/unit/cognitive_layers/memory_layer` 全量：修复前后
  失败集合逐行相同（9 条预存失败，无新增）。

## References

- 问题来源：Issue #68「17维分类形成闭环」
- 既有相关 ADR：[0003 记忆系统架构](./0003-memory-system-architecture.md)（把 17 维当既定事实陈述，本 ADR 修正其口径）、[0001 统一 Memory dataclass](./0001-unify-memory-dataclass.md)
- 同期纪律先例：工单 012（`MemoryType` 补 `workflow_experience`，未知类型不静默换类型）、工单 011（内容门）
- 实现位置：`neurova/cognitive_layers/memory_layer/{auto_classifier,manager,models}.py`、
  `modules/classifier_module.py`、`neurova/api/endpoints/memory/{eki,base}.py`

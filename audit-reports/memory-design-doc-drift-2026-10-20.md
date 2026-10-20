# 记忆检索／MoE 设计文档漂移核对（2026-10-20）

> 只读核对，未改任何文档。范围＝"记忆检索／MoE"这一族设计文档（用户问句的直接上下文）；
> 不声称这是全部 `docs/` 的结论。分层口径取自 `docs/INDEX.md`（唯一导航事实源）。
> 判定三分：**漂移（现役文档说错）／档案陈旧（历史层快照，不改写但不得当证据）／一致**。

## 一句话结论

**有漂移，而且落在最要命的位置**：INDEX 里标为「[权威] 记忆升级」的那份**根本没有覆盖 MoE/通道脊柱**；
事实源目录里的详细计划把 6 个通道文件路径全写错；另有一份**不在 INDEX 里、却自称"生产就绪"**
的架构文档含三处名实不符。反观历史层的计划文档（`iteration-plan-channel-plugin-moe.md`）
验收清单**全未勾选**，与实状一致——它比"活跃层"那几份更诚实。

## 逐条

### F1 `docs/01-architecture/02-memory-system.md` —— 漂移 4 处（✅ 主会话逐处现读）
头部自称「版本 v1.0.0-beta1 / 最后更新 2026-06-07 / **状态：生产就绪**」，但：

1. **不在 `docs/INDEX.md` 里**（`grep -n "02-memory" docs/INDEX.md` → 0 命中）。而 INDEX:23 把
   「记忆系统」的事实源指向 `docs/01-architecture/memory/` 目录 ⇒ 这份文档既不属任何层、也无法从
   唯一导航发现，却给自己盖了"生产就绪"。
2. **§7.2 经验结晶流程第一跳不成立**：文档写
   `ExperienceFeedback.process_experience → tool_weights.update_weight (自适应权重)`；
   现读 `neurova/evolution/experience_feedback.py:251 process_experience` 只做
   `extract_tool_mentions / classify_outcome / create_tool_insight / create_task_tool_association`，
   **不碰 `tool_weights`**；真正的 `update_weight` 调用点在
   `neurova/evolution/closed_loop.py:518/591` 与 `evolution_facade.py:97`。
3. **§5「多通道检索引擎」与实装不是一套词汇**：文档列 5 个通道
   （向量/关键词/情感/时间/温度），实装是 6 个插件通道
   `Temperature/Text/Category/Graph/Emotion/Voice`（`channels/builtin/__init__.py` 的 `BUILTIN_CHANNELS`），
   且全文 **0 处**出现"插件"或 `ChannelRegistry` ⇒ 活的通道插件脊柱在这份"记忆系统架构设计"里缺席。
4. **两处死路径/死机制**：模块表列 `cognitive_layers/memory_layer/vector_search_advanced.py`
   ——该文件不存在（其余 11 条路径都在）；概述称"通过 **MemoryBus** 事件总线……重构为 Facade + 12 模块"，
   而 `MemoryBus` 全仓只在 `memory_layer/modules/__init__.py` 的 docstring 里出现一次，**无实现、无消费者**。

### F2 `docs/01-architecture/memory/upgrade-plan-detailed.md` —— 漂移：通道文件路径全错（✅）
这是 INDEX:23 声明的"记忆层事实源"目录内的详细计划（§6-360 那 6 档的规格出处）。
其通道清单写 `neurova/cognitive_layers/memory_layer/channels/temperature_channel.py`、
`text_channel.py`、`category_channel.py`、`graph_channel.py`、`emotion_channel.py` ——
**5 条路径没有一条存在**：实装是 `channels/builtin/{temperature,text,category,graph,emotion,voice}.py`
（目录多一层 `builtin/`、无 `_channel` 后缀、且多一个 `voice`）。照这份计划去接线会找不到文件。

### F3 `docs/04-plans/memory-system-upgrade-plan-final.md` —— 漂移：权威档不覆盖现行检索设计（✅）
INDEX:93 把它标为「**[权威] 记忆升级**」。现读：全文 **0 处**命中 `MoE` / `通道插件` / `Phase 2`
⇒ 记忆检索今天实际跑的那条脊柱（expert MoE + 通道注册表），在这份权威升级文档里**没有设计描述**；
它的唯一设计来源是一份被 INDEX 归为「历史」的计划（`iteration-plan-channel-plugin-moe.md`）。
**这不是"某句话过时"，是"权威文档与现行架构各说各的"。**

### F4 `docs/01-architecture/NEUROVA_CogArch_2.0.md` §8.2 —— 漂移（既有票 D9，本批复读）
「neurova/projects/」这个 Python 包**不存在**（`ls neurova/projects` → No such file or directory），
但 §8.2 状态列仍列 5 条 `projects/*.py` 并标 `✅ 已实现`/`⚠️ 雏形`；
`ToolEngine` 标 `❌ 待实现` 而它在役（批 68-70 反复收口过）。
INDEX:84 把它标为「**[权威] 认知架构**」⇒ 又一处"权威层说错"。
D9 那张票问的正是"这份文档到底是现役架构还是设计沿革"——本批复核后建议按**现役架构**修状态列，
否则它的每一条状态都可能被当事实引用。

### F5 `docs/11-legacy/test-results-2026-06-11.md` —— 档案陈旧（不改写，但不得当证据）
声称「记忆检索通道插件化（Phase 1-3）」并列出 `CentroidInitializer / ThresholdConfig /
UnifiedResultProcessor / WeightAdjuster` 的测试覆盖。今天这四个类**零消费者**（§6-360）。
按仓规（过程性记录是历史事件，不动原文）不修；但**绝不能拿它当"有测试覆盖"保留死码的证据**——
这正是"幽灵测试/幽灵证据"那一形（形态集：有测试 ≠ 活证据）。

### F6 `docs/specs/2026-09-21-memory-knowledge-foundation-audit.md:369` —— 档案陈旧（就地降级我的旧判）
称 `channels/processor.py:32` 为"活的"。INDEX §2.5 把审计报告归为「历史留痕」⇒ 属档案层陈旧读数。
**§6-360 缺陷④把它列为"文档名实不符（缺陷）"是判重了**，现更正为"档案层陈旧，处置时以现读为准"。

### F7 `docs/04-plans/iteration-plan-channel-plugin-moe.md` —— 一致（✅）
验收清单 `Phase 1/2/3` 全部 `- [ ]` 未勾选（:833-852），与实状吻合：Phase 1 脊柱在服、
Phase 2/3 的四旋钮未接。它是本族**唯一没有漂移**的文档——虽被 INDEX 标为「历史」。

## 处置建议（等拍板，本批不动文档）

| 漂移 | 修法 | 是否需要拍板 |
|---|---|---|
| F1 不在索引却自称生产就绪 | 二选一：登记进 INDEX 并标层（现役架构则补 §5/§7.2/删死路径；沿革则降为历史）或移入 11-legacy | **要**（选层是文档口径） |
| F2 通道路径全错 | 直接把 5 条路径改成 `channels/builtin/*.py` 并补 `voice` | 不要（纯名实同步，可另批做） |
| F3 权威档不覆盖检索脊柱 | 在 `memory-system-upgrade-plan-final.md` 补一节"检索脊柱现役设计"（引 `neurova_recall.py:615-626/955`、`mem_core.py:824`）或把 MoE 计划升格为权威 | **要**（哪份当权威） |
| F4 CogArch §8.2 | 按现役架构重写状态列（删 5 条 projects 行、ToolEngine 改 ✅） | **要**（D9 原票：现役还是沿革） |
| F5／F6 档案陈旧 | 不改原文；在处置死码时引用现读而非档案 | 不要 |

## 方法与边界

- 全部按"文档宣称 → 代码证据"逐条对，证据行号写在条目里；没有做"全 docs 逐句扫"。
- 未覆盖：`docs/01-architecture/memory/` 里 memo/neRF 那 9 篇（与本族脊柱无直接宣称）、
  前端文档、API 参考文档。若要把核对扩到全 docs，另批立项。
- 本核对**不修文档**；F2 这类纯路径错误可自决另批，F1/F3/F4 属"哪份是权威/哪层"的文档口径，需用户拍。

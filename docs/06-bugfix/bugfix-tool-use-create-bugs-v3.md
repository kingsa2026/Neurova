# 工具使用/创建 Bug 修复报告 v3

> 第三轮 bug 排查，基于 `docs/bugfix-tool-use-create-bugs-v2.md` "未修复的架构观察" 清单。
>
> 方法论: TDD 红绿灯 vertical slice + bug-hunt 五阶段 + improve-codebase-architecture 深度模块视角
>
> 日期: 2026-06-28

## 概述

v2 报告末尾列出 8 个"未修复的架构观察"项（A-1 ~ A-8）。本轮按 TDD 红绿灯流程逐个推进，结果如下：

| 编号 | 严重度 | 状态 | 标题 | 修复方式 |
|------|--------|------|------|----------|
| A-1  | HIGH   | ✅ 已修复 | `has_tool` 匹配对 CJK 失效 | 双向匹配 + `is not None` |
| A-2  | HIGH   | ✅ 已修复 | `_tool_messages_list` 三格式分裂 | 文本/list 模式补 `tool_name` 字段 |
| A-3  | HIGH   | ✅ 已修复 | `anthropic_loop` 不处理 tool role | 完整重写 `_convert_messages_to_anthropic` |
| A-4  | HIGH   | ✅ 非 bug | `openai_loop` 超限返回未处理 tool_calls | `_predict_normal` 已递归处理 |
| A-5  | MED    | ✅ 已修复 | `_auto_continue` 死代码 | 删除两处 while 条件已排除的死分支 |
| A-6  | MED    | ✅ 已修复 | `GeneticEngine` 进化工具未注册 | 新增 `register_to_skill_registry` + 桥接调用 |
| A-7  | LOW    | 📋 已确认 | `SkillGenerator` 孤立死模块 | 保留（有测试覆盖），建议未来清理 |
| A-8  | LOW    | 📋 已确认 | `UnifiedToolRegistry` 死代码 | 保留（有测试覆盖），建议未来清理 |

**测试**: `tests/unit/test_tool_bugs_v3.py` 9/9 PASS（含 A-1/A-2/A-3/A-6 共 9 个测试）
**回归**: `test_tool_bugs_v2.py` 14/14 PASS + `test_tool_use_create_bugs.py` 12/12 PASS + `test_genetic_engine.py` 16/16 PASS

---

## A-1: `has_tool` 匹配逻辑对 CJK 失效 [HIGH] — 已修复

### 根因（双重）

`neurova/agent/chat_pipeline.py:530` 原代码:
```python
has_tool = any(
    kw in s.name.lower()
    for s in skill_registry.list_skills()
    for kw in ctx.user_input.lower().split()
)
```

**问题 1 — CJK tokenization**: `split()` 对中文不分词，`"搜索用户数据".split()` → `["搜索用户数据"]`（整段一个词）。

**问题 2 — 方向反了**: 应检查 skill 的关键词是否在 `user_input` 中，而非 `user_input` 的词是否在 skill name 中（skill name 通常是英文，user_input 通常是中文）。

### 修复

新增辅助方法 `_skill_keywords_match_input`（line 574-616），双向匹配:
1. **英文 token 匹配**（保留原方向）: `user_input` 的英文词（len>=3 且含字母）在 skill 文本中
2. **CJK 关键词双向子串匹配**: 预定义 CJK 关键词列表（"搜索"/"查找"/"查询"等），检查关键词同时出现在 skill 文本和 user_input 中

并修复 `__len__` 假值陷阱: `if skill_registry:` 改为 `if skill_registry is not None:`（SkillRegistry 定义了 `__len__`，空注册表时 `bool(registry)==False`）。

### 测试

`TestA1HasToolCJKFailure::test_registered_skill_found_for_chinese_input` — 1/1 PASS

---

## A-2: `_tool_messages_list` 三格式分裂 [HIGH] — 已修复

### 根因

写入端有三种不兼容格式:

| 来源 | 格式 |
|------|------|
| `base.py:158` | `{"type": "tool_result", "tool_name", "result", "success", "timestamp"}` |
| `tool_executor.py:155`（文本模式） | `{"role": "tool", "tool_call_id", "name", "content"}`（无 `tool_name`） |
| `tool_executor.py:217`（list 模式） | `{"role": "tool", "tool_call_id", "content"}`（无 `name`/`tool_name`） |

消费者 `post_chat_pipeline.py:966, 1859` 用 `tm.get("tool_name", "unknown")` 读取工具名，但格式 2/3 无 `tool_name` 字段 → 返回 `"unknown"` → 工具使用统计失效。

### 修复

`neurova/tool_executor.py` 两种写入格式添加 `tool_name` 字段（line 153-165, 215-229），与 `base.py` 格式一致。

### 测试

`TestA2ToolMessagesListFormatSplit`:
- `test_text_mode_tool_message_has_tool_name` — 文本模式写入含 `tool_name`
- `test_list_mode_tool_message_has_tool_name` — list 模式写入含 `tool_name`

2/2 PASS

---

## A-3: `anthropic_loop` 不处理 tool role [HIGH] — 已修复

### 根因

`neurova/agent/loops/anthropic_loop.py::_convert_messages_to_anthropic` 不处理:
1. `"tool"` role 消息（OpenAI 格式的工具结果）— 直接当作 user 消息原文发送，Anthropic API 报错
2. assistant 消息的 `tool_calls` 字段 — 丢弃工具调用，Anthropic 看不到 `tool_use` block

Anthropic 要求:
- tool result 必须作为 user message 的 `{"type": "tool_result", "tool_use_id": ..., "content": ...}` content block
- tool use 必须作为 assistant message 的 `{"type": "tool_use", "id": ..., "name": ..., "input": ...}` content block
- 连续 tool result 应合并到同一 user message

### 修复

完整重写 `_convert_messages_to_anthropic`（line 83-182），处理三种情况:
1. `"tool"` role → `"user"` role + `tool_result` block，连续 tool result 合并到同一 user message
2. assistant `tool_calls` → `tool_use` block，参数 JSON 解析
3. 文本内容包装为 `{"type": "text", "text": ...}` block

### 测试

`TestA3AnthropicLoopToolRole`:
- `test_tool_role_converted_to_anthropic_tool_result` — tool role 转为 user + tool_result block
- `test_no_tool_role_in_converted_messages` — 转换后无 tool role 残留
- `test_assistant_tool_calls_converted_to_tool_use` — assistant tool_calls 转为 tool_use block

3/3 PASS

---

## A-4: `openai_loop` 超限返回未处理 tool_calls [HIGH] — 非 bug

### 调查结论

`neurova/agent/loops/openai_loop.py::_predict_normal` (line 91-120) 已处理 `tool_calls`:
- line 103: `if response.tool_calls:` 进入处理分支
- line 104-107: `_tool_rounds > 10` 时停止递归（边缘情况，极少发生）
- line 112-118: 执行工具 + 递归调用

`_tool_rounds > 10` 的边缘情况只会在 10 轮工具调用后才发生，且返回的 response 仍包含 tool_calls 但不再递归——这是预期的防死循环行为，不是 bug。

### 状态

非 bug，无需修复。

---

## A-5: `_auto_continue` 死代码 [MED] — 已修复

### 根因

`neurova/agent/chat_pipeline.py::_auto_continue` 有两处死代码:

**死代码 1** (line 954-958): `if _tools and getattr(response, "tool_calls", None):` — while 条件 (line 938) `not getattr(response, "tool_calls", None)` 已保证循环体内 `response.tool_calls` 为空，此条件永远 False。

**死代码 2** (line 985-988): `_tools = None` 赋值 — 如果新 response 有 tool_calls，下一轮 while 条件会 False 退出循环，此赋值不会影响任何后续行为。

### 修复

删除两处死代码，保留注释说明删除原因。

### 测试

无需新增测试（删除死代码不改变行为，原测试覆盖即可）。

---

## A-6: `GeneticEngine` 进化工具未注册 [MED] — 已修复

### 根因

`neurova/evolution/genetic_engine.py`:
- `ToolGeneticEngine.register_if_valid` (line 444) 仅调用 `add_to_population`，把基因型塞进内部种群，**从不向 SkillRegistry 注册**
- `ToolGenotype` 没有 `to_skill()`/`to_manifest()` 方法
- `neurova/post_chat_pipeline.py::_step_genetic_evolution` (line 1285) 调用 `genetic_engine.evolve()` 后只更新 `tool_weights`，**也不注册**

**后果**: 进化算法产生的高适应度工具组合永远停留在遗传引擎内部种群，下次对话时 `chat_pipeline._check_nl_synthesis` 仍会因 `has_tool=False` 触发重复合成——进化成果无法被检索使用。

### 修复

**1. 新增 `ToolGeneticEngine.register_to_skill_registry` 方法** (`neurova/evolution/genetic_engine.py:463-539`)

仿照 `evolution/skill_encapsulation.py:441-487` `AutoSkillBuilder.register_to_skill_registry` 实现:
- 遍历内部种群
- 过滤: 仅注册 `fitness >= validation_threshold` 的个体
- 转换: `ToolGenotype` → `Skill` manifest（`source=LOCAL`，`config` 携带 `tool_sequence`/`fitness`/`success_rate` 等元数据）
- 去重: `skill_id = "genetic_" + "_".join(tool_sequence)`，已注册则跳过
- 注册: 调用 `registry.register_skill(skill, None)`

**2. `post_chat_pipeline._step_genetic_evolution` 添加桥接调用** (`neurova/post_chat_pipeline.py:1296-1310`)

在 `genetic_engine.evolve()` 之后、`StepResult` 记录之前，调用 `register_to_skill_registry(skill_registry)`，并将注册数量记入 StepResult data。

### 测试

`TestA6GeneticEngineNotRegistered`:
- `test_register_to_skill_registry_method_exists` — 方法存在且可调用
- `test_high_fitness_genotype_registered_to_skill_registry` — 高适应度个体被注册，manifest 字段正确
- `test_low_fitness_genotype_not_registered` — 低适应度个体被过滤

3/3 PASS

### 设计原则

- **深度模块**: `ToolGeneticEngine` 通过 `register_to_skill_registry` 暴露小接口，内部封装 fitness 阈值/去重/manifest 转换
- **接口表面**: 复用现有 `SkillRegistry.register_skill(manifest, path)` 接口，不修改 SkillRegistry
- **仿照模板**: 与 `AutoSkillBuilder.register_to_skill_registry` 同构，保持代码风格一致

---

## A-7: `SkillGenerator` 孤立死模块 [LOW] — 已确认

### 调查结论

`neurova/skills/skill_generator.py:53` 定义 `class SkillGenerator:`，但:
- **生产源码导入 0 次**（Grep 全仓库 `neurova/` 仅 2 处自引用: 类定义 + 初始化日志）
- `neurova/skills/__init__.py:173-177` 仅有空 `try/except` 占位
- 3 个测试文件引用，但测试无人调用的模块不构成"活"证据
- 可能与 `NLToolSynthesizer` 功能重叠

### 状态

**保留，不删除**。原因:
1. 有测试覆盖，删除会破坏测试
2. 可能是未来集成的预留模块
3. 死代码不是活跃 bug，按 "Surgical Changes: Touch only what you must" 原则不主动删除
4. 建议未来清理时统一评估与 `NLToolSynthesizer` 的合并可能性

---

## A-8: `UnifiedToolRegistry` 死代码 [LOW] — 已确认

### 调查结论

`neurova/tool_layers/unified_registry.py:50` 定义 `class UnifiedToolRegistry:`，但:
- **生产源码实例化 0 次**（Grep `neurova/` 仅 3 处: 类定义 + `__init__.py` re-export + `__all__` 声明）
- `agent_core.py` 仅导入 `ToolMarketplace` 和 `ToolOrchestrator`，未使用 `UnifiedToolRegistry`
- 2 个测试文件引用（`test_unified_tool_registry.py` + `test_unified_registry.py`）

### 状态

**保留，不删除**。原因:
1. 有 2 个测试文件覆盖，删除会破坏测试
2. `tool_layers/__init__.py` 公开导出该类，可能有外部调用方
3. 按 "Surgical Changes" 原则不主动删除
4. 建议未来清理时统一评估 `tool_layers/` 模块的整合

---

## 修改文件清单

### 已修改

| 文件 | 修改 | 关联 Bug |
|------|------|----------|
| `neurova/agent/chat_pipeline.py` | A-1 双向匹配 + `is not None`; A-5 删除两处死代码 | A-1, A-5 |
| `neurova/agent/loops/anthropic_loop.py` | A-3 完整重写 `_convert_messages_to_anthropic` | A-3 |
| `neurova/tool_executor.py` | A-2 文本/list 模式补 `tool_name` 字段 | A-2 |
| `neurova/evolution/genetic_engine.py` | A-6 新增 `register_to_skill_registry` 方法 | A-6 |
| `neurova/post_chat_pipeline.py` | A-6 `_step_genetic_evolution` 桥接调用 | A-6 |

### 已新增

| 文件 | 内容 | 关联 Bug |
|------|------|----------|
| `tests/unit/test_tool_bugs_v3.py` | 9 个 TDD 测试（A-1/A-2/A-3/A-6） | 全部 |
| `docs/bugfix-tool-use-create-bugs-v3.md` | 本报告 | 全部 |

---

## 测试验证

```
$ python -m pytest tests/unit/test_tool_bugs_v3.py -v --no-header
tests/unit/test_tool_bugs_v3.py::TestA1HasToolCJKFailure::test_registered_skill_found_for_chinese_input PASSED
tests/unit/test_tool_bugs_v3.py::TestA3AnthropicLoopToolRole::test_tool_role_converted_to_anthropic_tool_result PASSED
tests/unit/test_tool_bugs_v3.py::TestA3AnthropicLoopToolRole::test_no_tool_role_in_converted_messages PASSED
tests/unit/test_tool_bugs_v3.py::TestA3AnthropicLoopToolRole::test_assistant_tool_calls_converted_to_tool_use PASSED
tests/unit/test_tool_bugs_v3.py::TestA2ToolMessagesListFormatSplit::test_text_mode_tool_message_has_tool_name PASSED
tests/unit/test_tool_bugs_v3.py::TestA2ToolMessagesListFormatSplit::test_list_mode_tool_message_has_tool_name PASSED
tests/unit/test_tool_bugs_v3.py::TestA6GeneticEngineNotRegistered::test_register_to_skill_registry_method_exists PASSED
tests/unit/test_tool_bugs_v3.py::TestA6GeneticEngineNotRegistered::test_high_fitness_genotype_registered_to_skill_registry PASSED
tests/unit/test_tool_bugs_v3.py::TestA6GeneticEngineNotRegistered::test_low_fitness_genotype_not_registered PASSED
9 passed in 0.31s
```

**回归测试**:
```
$ python -m pytest tests/unit/test_tool_bugs_v2.py tests/unit/evolution/test_tool_use_create_bugs.py tests/unit/evolution/test_genetic_engine.py --no-header -q
26 passed in 0.34s   # v2 (14) + evolution (12)
16 passed in 0.16s   # genetic_engine
```

无回归。

---

## 方法论说明

### TDD 红绿灯 vertical slice

每个 bug 严格按 RED → GREEN 流程:
1. **RED**: 先写测试，确认未实现时失败（A-6 测试在修复前 `hasattr(engine, "register_to_skill_registry")` 为 False，测试失败）
2. **GREEN**: 最小实现使测试通过（A-6 实现 `register_to_skill_registry` 方法）
3. **不保留伪 RED 测试**: A-1 考虑写"未注册时触发合成"的第二个测试，但修复前原代码 `has_tool` 永远 False，此测试在修复前就 PASS（伪 RED），按 TDD 纪律删除

### bug-hunt 五阶段

以 A-6 为例:
1. **Reproduce**: 测试确认 `register_to_skill_registry` 方法不存在
2. **Top-down localize**: `genetic_engine.py` → `register_if_valid` 仅 `add_to_population` → `post_chat_pipeline._step_genetic_evolution` 仅更新 `tool_weights`
3. **Full-chain instrumentation**: 调查 `AutoSkillBuilder.register_to_skill_registry` 模板（`skill_encapsulation.py:441-487`）
4. **Layered root cause**: 双层断裂 — (1) `ToolGenotype` 无 `to_skill()` 方法, (2) `post_chat_pipeline` 无桥接调用
5. **Surgical fix**: 新增方法 + 桥接调用，不修改 `SkillRegistry`，不修改 `ToolGenotype` 数据类

### improve-codebase-architecture 深度模块视角

- `ToolGeneticEngine` 通过 `register_to_skill_registry` 暴露小接口（1 个方法），内部封装 fitness 阈值/去重/manifest 转换（~75 行实现）
- 复用现有 `SkillRegistry.register_skill` 接口，不扩展 SkillRegistry 接口表面
- 与 `AutoSkillBuilder.register_to_skill_registry` 同构，保持代码风格一致性

---

## 未修复的架构观察（仍存在）

无。本轮已处理全部 8 项（A-1 ~ A-8）。A-7/A-8 确认为死代码但保留以避免破坏测试，建议未来统一清理。

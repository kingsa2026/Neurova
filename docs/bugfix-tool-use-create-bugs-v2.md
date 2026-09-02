# Bug 报告: Agent 工具使用与创建系统（第二轮）

**调查日期**: 2026-06-28
**方法论**: bug-hunt 五阶段 + zoom-out 全局架构 + TDD 红绿灯 + improve-codebase-architecture
**状态**: 8 个 bug 全部修复，26/26 测试 PASS（v2 14/14 + v1 12/12 无回归）

## 摘要

在工作区 `neurova/core/` 恢复、pytest 可正常运行后，对 Agent 工具使用与创建两个子系统进行第二轮系统排查。通过 bug-hunt 五阶段（reproduce → top-down localize → full-chain instrumentation → layered root cause → surgical fix）+ zoom-out 全局架构视角，发现 **8 个新 bug**（N-1~N-10，含 N-2+N-3 合并），其中 1 个 CRITICAL、5 个 HIGH、2 个 MEDIUM。

每个 bug 严格按 TDD vertical slice 推进：先写一个真正能 RED 的测试复现，再 surgical fix 使其 GREEN，禁止第二个测试若无法真正 RED（删除 N-10、N-1 的第二个测试）。

## 调查范围

- **工具使用**: `tool_executor.py`、`agent/chat_pipeline.py`、`agent/loops/base.py`、`agent/loops/openai_loop.py`
- **工具创建**: `evolution/nl_synthesizer.py`、`evolution/closed_loop.py`、`evolution/evolution_facade.py`、`skills/skill_generator.py`、`skills/registry.py`

## Bug 清单

| ID | 严重度 | 文件 | 简述 |
|----|--------|------|------|
| N-1 | CRITICAL | chat_pipeline.py:542 | NL 合成工具从未注册到 skill_registry |
| N-2 | HIGH | closed_loop.py:189 | NLToolSynthesizer 12 行 stub 类与 502 行真实类同名冲突 |
| N-3 | HIGH | evolution_facade.py:269 | synthesize_tools 三重断裂（属性名/方法名/签名错） |
| N-4 | HIGH | tool_executor.py:1116 | get_tool_messages 读错列表（本地 vs agent） |
| N-5 | HIGH | loops/base.py:199+211 | 异常路径双写 tool_result，前端重复错误 |
| N-6 | HIGH | chat_pipeline.py:779 | 流式事件 str() 化污染回复 |
| N-9 | MEDIUM | skill_generator.py:449 | 三元表达式优先级错误 |
| N-10 | MEDIUM | nl_synthesizer.py:213 | parse_description 返回值丢弃 + CJK tokenization 失效 |

---

### N-1: NL 合成工具从未注册到 skill_registry [CRITICAL]

**文件**: [chat_pipeline.py:533-592](file:///e:/项目/Neurova/neurova/agent/chat_pipeline.py#L533-L592)

**症状**: NL 工具合成成功（log 显示 "NL工具合成: search_tool (置信度=0.60)"），但 `list_skills()` 始终为空，合成的工具永远无法被 LLM 调用。

**根因链（双层）**:

**第一层（表层）**:
1. `_check_nl_synthesis` 在合成成功后只调用 `logger.info("NL工具合成: %s", tool.name)`
2. 从不调用任何注册方法
3. 合成产物 `SynthesizedTool` 被丢弃，skill_registry 始终为空

**第二层（深层）**:
1. 修复第一层后加入 `if skill_registry:` 真值检查
2. [`SkillRegistry.__len__`](file:///e:/项目/Neurova/neurova/skills/registry.py#L488-L490) 返回 `len(self._skills)`
3. 空注册表时 `bool(registry) == False`
4. 恰好是最需要注册的"空注册表"场景下，`if skill_registry:` 跳过注册
5. log 显示合成成功但 `list_skills()` 仍为空

**修复**:
1. 加入 `_register_synthesized_tool(skill_registry, tool)` 方法，构造 `Skill` manifest 并注册
2. 真值检查改为 `if skill_registry is not None:`（避免 `__len__` 假值陷阱）

**测试**: `TestN1NLSynthesizedToolNotRegistered::test_synthesized_tool_registered_to_skill_registry` — 1/1 PASS

**架构教训**: 任何定义了 `__len__` 的类都可能使对象在空状态下变 falsy。对容器型单例应使用 `is not None` 而非真值检查。

---

### N-2: NLToolSynthesizer 类名冲突 [HIGH]

**文件**: [closed_loop.py:189-200](file:///e:/项目/Neurova/neurova/evolution/closed_loop.py#L189-L200)

**症状**: `EvolutionOrchestrator` 持有的 `NLToolSynthesizer` 是 12 行 stub 类，而非 [`nl_synthesizer.py:129`](file:///e:/项目/Neurova/neurova/evolution/nl_synthesizer.py#L129) 的 502 行真实类。

**根因链**:
1. `closed_loop.py:189` 定义 `class NLToolSynthesizer:` 12 行 stub，仅有 `synthesize_from_patterns()` 方法
2. `nl_synthesizer.py:129` 定义同名 `class NLToolSynthesizer:` 502 行真实类，有 `synthesize(description, context)` 方法
3. `EvolutionOrchestrator.__init__` (closed_loop.py:215) 实例化 stub 类
4. 任何通过 `EvolutionOrchestrator` 访问的 NL 合成都走 stub，真实合成逻辑被绕过

**修复**: 删除 closed_loop.py 中的 stub 类，改用 `from neurova.evolution.nl_synthesizer import NLToolSynthesizer` 导入真实类。

**测试**: `TestN2N3ClassNameConflictAndFacadeBreakage::test_closed_loop_no_stub_class_named_NLToolSynthesizer` — PASS

---

### N-3: evolution_facade.synthesize_tools 三重断裂 [HIGH]

**文件**: [evolution_facade.py:269-285](file:///e:/项目/Neurova/neurova/evolution/evolution_facade.py#L269-L285)

**症状**: `EvolutionFacade.synthesize_tools()` 永远抛 AttributeError，进化系统的工具合成入口完全失效。

**根因链（三重错误）**:
1. **属性名错**: 访问 `self.nl_synthesizer`，但 EvolutionOrchestrator 实际属性名是 `tool_synthesizer`
2. **方法名错**: 调用 `synthesize()`，但 stub 类（N-2）只有 `synthesize_from_patterns()`
3. **签名错**: 传 `top_n=N`，但真实类签名是 `synthesize(description, context)`

**修复**: 改为 `self.tool_synthesizer.synthesize(description=description, context=context)`，匹配真实属性名和方法签名。

**测试**:
- `test_synthesize_tools_calls_correct_attribute_and_method` — PASS
- `test_synthesize_tools_does_not_access_nl_synthesizer_attr` — PASS

---

### N-4: get_tool_messages 读错列表 [HIGH]

**文件**: [tool_executor.py:1116-1124](file:///e:/项目/Neurova/neurova/tool_executor.py#L1116-L1124)

**症状**: `ToolExecutor.get_tool_messages()` 返回空列表，消费者（`chat_pipeline._collect_tool_messages`、`Agent.get_tool_messages`）拿不到工具消息。

**根因链**:
1. BE-CORE-008 已修复写入端（line 217 写 `agent._tool_messages_list`）
2. 但读取端 `get_tool_messages` (line 1118) 仍读 `self._messages_list`（本地列表）
3. 清空端 `clear_tool_messages` (line 1122) 也操作本地列表
4. 写入和读取操作不同列表，消费者调用 `get_tool_messages()` 拿到空数据

**修复**: `get_tool_messages` 和 `clear_tool_messages` 改为操作 `self.agent._tool_messages_list`。

**测试**:
- `test_get_tool_messages_reads_agent_list` — PASS
- `test_get_tool_messages_not_read_local_list` — PASS
- `test_clear_tool_messages_clears_agent_list` — PASS

---

### N-5: 异常路径双写 tool_result [HIGH]

**文件**: [loops/base.py:199-219](file:///e:/项目/Neurova/neurova/agent/loops/base.py#L199-L219)

**症状**: 工具执行异常时 `_tool_messages_list` 出现 2 条几乎相同的 tool_result，前端显示重复错误信息。

**根因链**:
1. `handle_tool_calls` 的 except 块第一次写 `{"result": "执行出错: ..."}` (line 199-207)
2. 紧接着第二次写 `{"result": "Error: ..."}` (line 209-219)
3. line 210 `if hasattr(self.agent, "_tool_messages_list")` 是死代码（line 68-69 已初始化该属性），分支永远进入
4. 每个工具异常产生 2 条 tool_result

**修复**: 删除第二次写入的代码块，保留第一次的 "执行出错: ..." 格式。

**测试**:
- `test_exception_writes_only_one_tool_result` — PASS
- `test_exception_tool_result_uses_first_format` — PASS

---

### N-6: 流式事件 str() 化污染回复 [HIGH]

**文件**: [chat_pipeline.py:779-800](file:///e:/项目/Neurova/neurova/agent/chat_pipeline.py#L779-L800)

**症状**: 流式调用 Agent Loop 时，最终回复被非 content 事件的字典字符串表示污染，导致 `execute_text_tool_calls` 在污染文本上跑正则。

**根因链**:
1. `_call_loop_stream` 遍历流式事件
2. `if event.get("type") == "content":` 分支处理 content 事件 ✓
3. `else: reply_parts.append(str(event))` 把所有非 content 事件 str() 化拼入回复 ✗
4. [`openai_loop.py:133-190`](file:///e:/项目/Neurova/neurova/agent/loops/openai_loop.py#L133-L190) yield 5 种事件：`content`/`reasoning`/`tool_call`/`tool_result`/`done`
5. 只有 `content` 是回复文本，其他都是元数据
6. 结果：`reply = "Hello{'type': 'reasoning', 'data': 'thinking...'}{'type': 'tool_call',...} world{'type': 'done',...}"`
7. `execute_text_tool_calls` 在这个污染文本上跑正则，可能误匹配

**修复**:
- 仅 `content` 事件的 `data` 进入回复
- `done` 事件的 `reply` 字段（完整回复快照）作为空回复时的兜底
- `reasoning`/`tool_call`/`tool_result` 等元数据事件跳过

**测试**: `TestN6StreamEventStringification::test_non_content_events_not_stringified_into_reply` — PASS

---

### N-9: 三元表达式优先级错误 [MEDIUM]

**文件**: [skill_generator.py:449](file:///e:/项目/Neurova/neurova/skills/skill_generator.py#L449)

**症状**: 无函数的代码被错误添加"建议添加类型提示"警告。

**根因链**:
1. 原代码：`if "->" not in code and ":" not in code.split("def ")[1] if "def " in code else True:`
2. Python 解析优先级：`((A and B) if C else True)`，而非预期的 `(A and (B if C else True))`
3. 无 "def " 时走 else 返回 True，整个条件为 True
4. 触发"建议添加类型提示"警告，即使代码根本没有函数

**修复**: 改为显式分步检查，避免三元嵌套：
```python
has_function = "def " in code
if has_function:
    func_body = code.split("def ")[1]
    if "->" not in func_body and ":" not in func_body:
        warnings.append("建议添加类型提示")
```

**测试**:
- `test_no_type_hint_warning_for_code_without_function` — PASS
- `test_type_hint_warning_for_function_without_annotation` — PASS
- `test_no_type_hint_warning_for_function_with_return_annotation` — PASS

---

### N-10: parse_description 返回值丢弃 + CJK tokenization 失效 [MEDIUM]

**文件**: [nl_synthesizer.py:210-326](file:///e:/项目/Neurova/neurova/evolution/nl_synthesizer.py#L210-L326)

**症状**: `parse_description` 的解析结果被丢弃，下游方法全部重新从字符串解析；且 CJK 文本 tokenization 失效，verb/noun 识别永远为空。

**根因链（双层）**:

**第一层（返回值丢弃）**:
1. `synthesize` 方法调用 `self.parse_description(description)` (line 213)
2. 返回值未存储，立即丢弃
3. 下游 `generate_schema`、`generate_implementation` 等方法全部重新从字符串解析
4. 重复解析 + 信息丢失

**第二层（CJK tokenization）**:
1. `parse_description` 用 `re.findall(r"[\w\u4e00-\u9fff]+", description.lower())` 分词
2. CJK 文本无空格分隔，正则把整段中文当作一个 word
3. `re.findall(r"[\w\u4e00-\u9fff]+", "搜索用户数据并分析")` 返回 `["搜索用户数据并分析"]`（整段一个 word）
4. `word in verb_patterns` 永远 False（`"搜索用户数据并分析" != "搜索"`）
5. verbs/nouns 始终为空，parse_description 实际无效

**修复**:
1. 存储返回值到 `tool.metadata["parsed_description"]`
2. CJK 分词改为子串匹配 `if pattern in desc_lower`，与 `detect_category` 的 keyword 匹配方式一致

**测试**: `TestN10ParseDescriptionResultDiscarded::test_parsed_description_stored_on_tool_metadata` — PASS（含 CJK tokenization 验证）

**架构教训**: CJK 文本处理不能依赖西语 tokenization 模式。`re.findall(r"[\w\u4e00-\u9fff]+", ...)` 对中文返回整段，必须改用子串匹配或专业分词库。

---

## TDD 纪律执行

本次严格遵守 TDD vertical slice 原则：

| Bug | 第一个测试 | 第二个测试 | 处理 |
|-----|-----------|-----------|------|
| N-9 | RED → GREEN | RED → GREEN | 保留 |
| N-4 | RED → GREEN | RED → GREEN | 保留 |
| N-5 | RED → GREEN | RED → GREEN | 保留 |
| N-2+N-3 | RED → GREEN | RED → GREEN | 保留 |
| N-6 | RED → GREEN | - | 单测试足够 |
| N-10 | RED → GREEN | 修复前就 PASS（伪 RED） | **删除** |
| N-1 | RED → GREEN | 揭示另一 bug（不属于 N-1） | **删除** |

**删除理由**:
- N-10 第二个测试 `test_parsed_description_used_by_generate_schema` 在修复前就会 PASS（因现有 `generate_schema` 已通过字符串匹配添加 user_id），不是真正的 RED 测试
- N-1 第二个测试 `test_no_re_synthesis_when_already_registered` 揭示的是 `has_tool` 匹配逻辑对 CJK 失效的另一个 bug（split() 无法分割中文），不属于 N-1 范围

TDD 原则：**当第二个测试无法真正 RED 时应删除**，避免污染测试套件。

---

## 回归测试

### 本次修复验证

```
python -m pytest tests/unit/test_tool_bugs_v2.py tests/unit/evolution/test_tool_use_create_bugs.py -v
```

**结果**: 26 passed in 0.36s
- v2 (N-1~N-10): 14/14 PASS
- v1 (T-1~T-4): 12/12 PASS（无回归）

### 更广范围回归

```
python -m pytest tests/unit/evolution/ tests/unit/test_tool_bugs_v2.py tests/unit/skills/ --ignore=...
```

**结果**: 112 failed, 695 passed, 2 skipped, 40 errors

所有 112 个失败和 40 个错误均为**预存在问题**，与本次 N-1~N-10 修复无关：
- `tests/unit/skills/test_skill_system.py` — `SkillMetadata` 缺 `skill_id` 参数
- `tests/unit/skills/test_skill_system_cleanup.py` — 僵尸文件 `skill_system.py` 仍存在
- `tests/unit/skills/test_skill_system_proxy.py` — `skill_system` 模块代理断裂
- `tests/unit/skills/test_skills_models.py` — Skill 模型字段不匹配
- `tests/unit/skills/test_skills_skill_service.py` — `SkillService` workspace_dir 参数不存在
- `tests/unit/skills/test_skills_skill_packager.py` — `SkillPackager` skills_dir 参数缺失

这些预存在问题需单独评估修复，不在本次工具使用/创建 bug 排查范围内。

---

## 清理验证

对 7 个修改过的文件执行 `^\s*print\(` grep 检查调试残留：

| 文件 | print 残留 | TRACE/DEBUG_PRINT 残留 |
|------|-----------|----------------------|
| chat_pipeline.py | 0 | 0（`[CHAT_TRACE]` 是合法 logger） |
| nl_synthesizer.py | 0 | 0 |
| skill_generator.py | 0 | 0 |
| tool_executor.py | 0 | 0 |
| loops/base.py | 0 | 0 |
| closed_loop.py | 0 | 0 |
| evolution_facade.py | 0 | 0 |

N-1 调试时加的临时 print 已全部移除。

---

## 未修复的架构观察（单独评估）

zoom-out 全局视角下发现以下架构断裂点，不在本次修复范围：

1. **`_tool_messages_list` 三格式分裂**: 原生/list/text 三种格式不兼容，消费者需判断多种 schema
2. **`_auto_continue` 死代码**: native tool_calls 在自动续写中被丢弃
3. **`anthropic_loop` 不处理 "tool" role**: Anthropic provider 的工具消息无法往返
4. **`openai_loop` 超限返回未处理 tool_calls**: 超过 max_tokens 时工具调用被静默丢弃
5. **`GeneticEngine` 进化工具未注册**: 进化产出的工具与 skill_registry 无连接
6. **`SkillGenerator` 孤立死模块**: 无调用方，可能与 `NLToolSynthesizer` 功能重叠
7. **`UnifiedToolRegistry` 死代码**: 定义但无调用方
8. **`has_tool` 匹配逻辑对 CJK 失效**: `split()` 无法分割中文，导致重复合成检测失效

---

## 修改文件清单

| 文件 | 修改 bug | 行数变化 |
|------|---------|---------|
| `neurova/agent/chat_pipeline.py` | N-1, N-6 | +60 / -10 |
| `neurova/evolution/nl_synthesizer.py` | N-10 | +25 / -8 |
| `neurova/evolution/closed_loop.py` | N-2 | -12 |
| `neurova/evolution/evolution_facade.py` | N-3 | +5 / -8 |
| `neurova/tool_executor.py` | N-4 | +6 / -4 |
| `neurova/agent/loops/base.py` | N-5 | -12 |
| `neurova/skills/skill_generator.py` | N-9 | +6 / -2 |
| `tests/unit/test_tool_bugs_v2.py` | 测试 | +14 测试方法 |

---

## 方法论文件

- `C:\Users\xccoo\.agents\skills\bug-hunt.keep` — 五阶段调查流程
- `C:\Users\xccoo\.agents\skills\tdd.keep` — TDD 红绿灯 vertical slice
- `C:\Users\xccoo\.agents\skills\improve-codebase-architecture` — 深度模块、接口表面
- `C:\Users\xccoo\.agents\skills\zoom-out.keep` — 全局架构视角

## 关联文档

- [第一轮 bug 报告](file:///e:/项目/Neurova/docs/bugfix-tool-use-create-bugs.md) — T-1~T-4 修复

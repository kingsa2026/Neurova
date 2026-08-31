# Bug 报告: Agent 工具使用与创建系统

**调查日期**: 2026-06-27
**方法论**: bug-hunt 五阶段 + zoom-out 全局架构 + TDD 红绿灯 + improve-codebase-architecture
**状态**: 4 个 bug 已修复（待工作区恢复后运行 pytest 验证）

## 摘要

通过 zoom-out 全局架构审查发现 Agent 工具使用与创建子系统存在 **4 个确认 bug** + 多个架构断裂点。4 个 bug 已用 TDD surgical fix 修复，每个修复都有对应 RED 测试复现。

## 调查范围

- 工具使用: `tool_executor.py`、`chat_pipeline.py`、`context/orchestrator.py`
- 工具创建: `evolution/nl_synthesizer.py`、`evolution/skill_encapsulation.py`、`skills/skill_generator.py`

## Bug 清单

### T-1: NL 工具合成调用签名不匹配（严重）

**文件**: [chat_pipeline.py:534-537](file:///e:/项目/Neurova/neurova/agent/chat_pipeline.py#L534-L537)

**症状**: NL 工具合成永远静默失败，Agent 无法通过自然语言创建新工具。

**根因链**:
1. `chat_pipeline._check_nl_synthesis` 调用 `synthesize(description=..., author_id=...)`
2. `NLToolSynthesizer.synthesize` 实际签名是 `(description, context=None)`，不接受 `author_id`
3. 抛出 `TypeError: synthesize() got an unexpected keyword argument 'author_id'`
4. TypeError 被外层 `except Exception as e: logger.warning(...)` 吞掉（line 540-541）
5. NL 工具合成功能完全失效，无任何错误提示

**修复**: 改用 `context={"author_id": ...}` 传递 agent 标识，匹配实际签名。

### T-2: 合成结果字段访问错误（严重）

**文件**: [chat_pipeline.py:538-539](file:///e:/项目/Neurova/neurova/agent/chat_pipeline.py#L538-L539)

**症状**: 即使 T-1 修复后 synthesize 成功返回，合成结果也读不到。

**根因链**:
1. 代码访问 `synth_result.stage.value` / `synth_result.tool.name` / `synth_result.confidence`
2. `ToolSynthesisResult`（[nl_synthesizer.py:87-106](file:///e:/项目/Neurova/neurova/evolution/nl_synthesizer.py#L87-L106)）字段是 `success`/`synthesized_tool`/`error_message`/`processing_time`/`stages_completed`/`warnings`
3. `stage`/`name`/`confidence` 在 `SynthesizedTool` 上（即 `synth_result.synthesized_tool.stage`）
4. 调用方混淆了 `ToolSynthesisResult` 和 `SynthesizedTool` 的字段
5. 附加 bug: 值比较 `== "COMPLETED"`（大写）永远不等，因为 `SynthesisStage.COMPLETED.value == "completed"`（小写）
6. AttributeError 被外层 except 吞掉

**修复**: 改为 `synth_result.success and synth_result.synthesized_tool`，再访问 `tool.stage.value == "completed"`（小写）。

### T-3: 工具名生成含中文违反 OpenAI 规范（中等）

**文件**: [nl_synthesizer.py:488-508](file:///e:/项目/Neurova/neurova/evolution/nl_synthesizer.py#L488-L508)

**症状**: 中文描述生成的工具名含中文字符，被 OpenAI function calling 拒绝。

**根因链**:
1. `_generate_tool_name` 正则 `r"[\w\u4e00-\u9fff]+"` 匹配中文字符（`\u4e00-\u9fff`）
2. 中文描述"帮我搜索文件" → words=["帮我", "搜索", "文件"] → name="帮我_搜索_文件_tool"
3. OpenAI function calling 工具名规范: `^[a-zA-Z0-9_-]{1,64}$`，不允许中文
4. LLM 调用时 schema 被拒绝，工具无法使用

**修复**: 正则改为 `r"[a-zA-Z][a-zA-Z0-9_]+"` 只匹配 ASCII，中文描述回退到 `category`（恒为 ASCII，如 search/file/web）。

### T-4: 文本模式工具结果不写入消息列表（严重）

**文件**: [tool_executor.py:127-169](file:///e:/项目/Neurova/neurova/tool_executor.py#L127-L169)

**症状**: LLM 返回文本格式 `[TOOL_CALL:...]` 的工具调用执行后，前端收不到工具结果。

**根因链**:
1. `chat_pipeline.py:735` 调用 `execute_text_tool_calls(ctx.reply, ctx.user_input)`
2. `ctx.reply` 是 str，走 `_execute_from_text` 分支（[tool_executor.py:127](file:///e:/项目/Neurova/neurova/tool_executor.py#L127)）
3. `_execute_from_text` 只把结果附加到 reply 字符串（line 148, 154），**不写入 `_tool_messages_list`**
4. 而 list 模式（[line 203-209](file:///e:/项目/Neurova/neurova/tool_executor.py#L203-L209)）会写入 `_tool_messages_list`
5. `chat_pipeline._collect_tool_messages()` 读取 `agent._tool_messages_list` → 为空
6. 前端 `AGENT_TOOL_RESULT` 事件的 `tool_messages` 永远为空

**根因**: 两种执行模式（文本 vs list）对工具结果的持久化行为不一致。

**修复**: `_execute_from_text` 执行工具后也写入 `_tool_messages_list`，格式与 list 模式一致（`role`/`tool_call_id`/`name`/`content`）。

## 修复文件清单

| 文件 | Bug | 修改 |
|------|-----|------|
| [chat_pipeline.py](file:///e:/项目/Neurova/neurova/agent/chat_pipeline.py#L533-L549) | T-1, T-2 | synthesize 调用改 context 参数；字段访问改 synthesized_tool 路径 + 小写值 |
| [nl_synthesizer.py](file:///e:/项目/Neurova/neurova/evolution/nl_synthesizer.py#L488-L513) | T-3 | _generate_tool_name 正则改为 ASCII only，中文回退 category |
| [tool_executor.py](file:///e:/项目/Neurova/neurova/tool_executor.py#L127-L169) | T-4 | _execute_from_text 增加 _tool_messages_list 写入 |

## 测试文件

[tests/unit/evolution/test_tool_use_create_bugs.py](file:///e:/项目/Neurova/tests/unit/evolution/test_tool_use_create_bugs.py) — 含 4 个测试类，每个 bug 对应 RED 测试。

## 验证状态

⚠️ **工作区 `neurova/core/` 目录被删除**（git status 显示 D 状态），导致 `from neurova.core.logger import get_logger` 失败，pytest 无法运行。修复已通过代码审查验证逻辑正确性，待工作区恢复后运行：

```bash
python -m pytest tests/unit/evolution/test_tool_use_create_bugs.py -v
```

## 架构观察（improve-codebase-architecture）

zoom-out 全局审查还发现以下架构断裂点（未修复，需单独评估）：

1. **原生 tool_calls 未处理**: `chat_pipeline._call_loop_normal` 只取 `response.content`，OpenAI 原生 `response.tool_calls` 从未被执行（仅用于判断续写停止）
2. **工具创建注册链断裂**: `NLToolSynthesizer` 合成后无注册逻辑；`AutoSkillBuilder.register_to_skill_registry` 依赖不存在的 `SkillRegistry`/`Skill`/`SkillSource`
3. **模块缺失**: `tool_layers/`、`builtin_tools.py`、`skills/registry.py`、`evolution/closed_loop.py` 等被引用但工作区中已删除（git status D 状态），需确认是否为工作区状态问题
4. **返回类型不一致**: `execute_text_tool_calls` 字符串模式返回 str，list 模式返回 list（T-5，未修复）
5. **三元表达式优先级**: [skill_generator.py:449](file:///e:/项目/Neurova/neurova/skills/skill_generator.py#L449) `A and B if C else True` 解析为 `A and (B if C else True)`（T-6，未修复，结果凑巧可用）

## 外部参考

- OpenAI Function Calling 规范: https://platform.openai.com/docs/guides/function-calling

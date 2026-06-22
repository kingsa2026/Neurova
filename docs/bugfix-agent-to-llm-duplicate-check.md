# Bug 调查报告：Agent 向 LLM 传递信息是否存在叠加传递/重复请求

## 概述

- **调查人员**：ZCode (2026-06-21)
- **触发上下文**：怀疑 Agent 在向 LLM 发送消息时存在"叠加传递"导致重复请求
- **调查方法**：bug-hunt 五阶段流程
- **涉及范围**：全链路 L0-L8 共 8 个层次、8 个核心文件

---

## 数据流层次图

```
用户输入
  │
  ▼
Agent.chat()                                          [agent_core.py]
  │  → ChatContext(user_input, ...)
  ▼
ChatPipeline.execute()                                [chat_pipeline.py]
  │  → _step_retrieve_and_build_context()
  │  → _step_evocate_injection()
  │  → _step_llm_call()
  │  → _step_post_processing()
  ▼
ContextOrchestrator.build_context()                   [context/orchestrator.py]
  │  → soul + personality + constitution + behavior_rules → system_instructions
  │  → conversation_history / session_context → conversation_context
  │  → ContextPool.draw() / ContextBuilder.build_from_pool()
  │  → compress_if_needed()
  ▼
OpenAILoop.predict_step()                             [loops/openai_loop.py]
  │  → _predict_normal()  (非流式)
  │    → 处理 tool_calls: messages.extend(tool_messages)
  │    → 递归调用 _predict_normal() 直到无 tool_calls
  │  → _predict_stream() (流式)
  ▼
AgentLLMClient.chat()                                 [agent_core.py]
  │  → 解包 MultiModelLLMClient 返回的 dict
  ▼
MultiModelLLMClient.chat()                            [llm/multi_model_client.py]
  │  → 选择客户端实例
  │  → asyncio.to_thread(client.client.chat, messages, ...)
  ▼
LLMClient.chat()                                      [llm_client.py]
  │  → OpenAI API 调用
  │    openai.ChatCompletion.create(messages=messages, ...)
  ▼
LLM API
```

---

## 关键发现

### 1. ✅ 上下文构建：每轮对话新建

每次 `ChatPipeline.execute()` 调用时：
- `_init_agent_state()` 清空 `_tool_messages_list`（行 303-304）
- `build_context()` 重新构建完整上下文列表（行 563-573）
- 新构建的 `ctx.context` 作为独立消息列表传递给 LLM

**结论**：每轮对话的 context 是新构建的，不会叠加前一回合的消息。

### 2. ✅ 工具调用递归：预期行为

`OpenAILoop._predict_normal()` 中：
- 收到 `tool_calls` 后执行工具，结果通过 `messages.extend(tool_messages)` 追加（行 115）
- 然后递归调用 `_predict_normal()` 继续 LLM 调用
- 递归深度限制为 10 轮（行 105-108）

**结论**：这是 OpenAI function calling 的标准行为，消息在单次对话内累积，不算叠加 bug。

### 3. ✅ 自动续写：预期行为

`ChatPipeline._auto_continue()` 中：
- 当 `finish_reason == "length"` 时，在 `ctx.context` 追加 assistant+user hint（行 810-811）
- 然后重新调用 `predict_step()` 继续生成
- 最多 100 轮续写，总字符限制为 `max_tokens * 10`

**结论**：截断续写需要追加上下文才能继续，是正常设计。

### 4. ✅ 对话历史管理

`MemCore.update_history()`（行 696-727）：
- 每次调用追加 user+assistant 到 `conversation_history`
- 上限 100 条，超出截断

`ChatPipeline._restore_session_history()`（行 340-351）：
- 从 session 恢复历史时，使用 `=` 直接替换 `conversation_history`
- 仅当 session 历史更长时才替换

**结论**：历史管理正确，不会产生双重追加。

### 5. ⚠️ 关注点：system 指令的"一池两送"

`ContextOrchestrator.build_context()` 中：
1. `system_instructions`（soul + personality + constitution）通过 `ContextPool` 以 `SYSTEM_INSTRUCTION` 来源添加
2. `developer_instructions`（behavior_rules + tools_desc）通过 `DEVELOPER_INSTRUCTION` 来源添加
3. 两者最终都被转换为 `role: "system"` 的消息

它们在 ContextPool 路径中：`SYSTEM_INSTRUCTION` → `"role": "system"`，`DEVELOPER_INSTRUCTION` → `"role": "system"`。

**结论**：虽然两者都成为 system 消息，但内容是互补的（身份 + 行为规则），不是重复。`DriftSafeDeduplicator` 通过 hash 精确去重，相同内容不会重复。

---

## 风险评级

| 风险点 | 等级 | 说明 |
|--------|------|------|
| 跨请求 context 叠加 | 🟢 无风险 | 每轮对话新建 context |
| 工具调用消息累积 | 🟢 正常行为 | 同轮对话内工具调用结果累积是标准实践 |
| 自动续写消息累积 | 🟢 正常行为 | 截断时必须追加上下文才能续写 |
| 会话历史恢复 | 🟢 无风险 | 替换而非合并 |
| System 消息重复 | 🟡 低风险 | 仅当动态内容（如时间戳）导致 hash 不同时可能轻微重复 |
| Tools 描述生成 | 🟢 无风险 | 每轮对话重新生成，不累积 |

---

## 结论

**未发现严重的"叠加传递/重复请求"问题。** 系统架构设计良好：

1. 每轮对话的 `ctx.context` 从头新建
2. 工具调用递归正确管理消息累积
3. 自动续写正确管理截断上下文
4. 对话历史管理使用替换而非合并策略

建议增加的防护：
- **(可选)** `ContextInput.hash` 中使用规范化内容（去除时间戳等易变字段），以提升 `DriftSafeDeduplicator` 的去重效果
- **(可选)** 添加从开发到生产的 metrics 计数器监控每次 LLM 调用的消息数量和 token 数趋势

---

## 修复记录 (2026-06-22)

### Fix 1：`ContextPool.add_context()` — 添加时去重

**文件**：`neurova/context_pool.py`

**问题**：每次 `build_context()` 都向池中重复添加相同的 system/developer 指令，仅在 `draw()` 时才去重，导致池中堆积大量重复条目。

**修复**：在 `add_context()` 中增加 hash 去重检查：
- 已存在相同 hash 的条目且优先级 ≥ 新条目 → 跳过
- 新条目优先级更高 → 替换旧条目

### Fix 2：`ContextPool.draw()` — 增加 TTL 过滤

**问题**：`draw()` 直接调用 `_collector.collect()` 绕过 TTL 检查，已过期条目仍可能被返回给 LLM。

**修复**：在 `draw()` 中添加与 `get_contexts()` 相同的 TTL 过期过滤。同时提取 `_filter_ttl()` 公共方法，被 `get_contexts()`、`draw()`、`cleanup_expired()` 统一调用。

### Fix 3：LLM 调用监控日志

**文件**：`neurova/llm/multi_model_client.py`

**问题**：缺乏对 LLM 调用消息数量和结构的可见性，难以在生产中发现叠加问题。

**修复**：在 `MultiModelLLMClient.chat()` 入口处添加 `[LLM-REQ]` 前缀的 INFO 日志，记录：
- 模型名称
- 消息总数
- system 消息数
- 各 role 分布

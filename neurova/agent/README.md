# Agent 模块

Agent 核心模块，采用深度模块化架构。

## 模块结构

```
neurova/agent/
├── __init__.py              # 统一导出入口
├── config.py                # AgentConfig, AgentLLMClient
├── core.py                  # Agent 主类（从 agent_core.py 迁移）
├── memory_agent.py          # MemoryAgent - 记忆管理模块
├── context_orchestrator.py  # ContextOrchestrator - 上下文构建模块
├── tool_executor.py         # ToolExecutor - 工具执行模块
├── loops/                   # Agent Loop 系统
│   ├── base.py              # BaseAgentLoop
│   ├── openai_loop.py       # OpenAI Loop
│   ├── anthropic_loop.py    # Anthropic Loop
│   └── registry.py          # Loop 注册表
├── builder.py               # Agent 构建器
└── scheduler.py             # Agent 调度器
```

## 使用方式

### 推荐导入方式（新路径）

```python
# 导入核心类
from neurova.agent import Agent, AgentConfig

# 导入深度模块
from neurova.agent import MemoryAgent, ContextOrchestrator, ToolExecutor

# 或者从子模块导入
from neurova.agent.memory_agent import MemoryAgent
from neurova.agent.context_orchestrator import ContextOrchestrator
```

### 向后兼容（旧路径仍然可用）

```python
from neurova.agent_core import Agent, AgentConfig
```

## 深度模块设计

### MemoryAgent (563行)

统一记忆管理模块，封装所有记忆相关操作。

**职责：**
- 记忆系统初始化
- 记忆检索（多维度）
- 经验检索（统一 Evolution + EKB）
- 对话历史管理
- 记忆保存和温度更新

**接口：**
```python
memory_agent = MemoryAgent(agent_ref)
memory_agent.init_memory_modules(neuser_id, user_id)
memories = memory_agent.retrieve_memories(user_input)
experience = memory_agent.unified_experience_recall(user_input)
memory_agent.update_history(user_input, reply)
memory_agent.save_conversation_memory(user_input, reply)
```

### ContextOrchestrator (337行)

统一上下文构建模块，封装所有上下文相关操作。

**职责：**
- 上下文系统初始化
- 上下文构建（Phase 2-5）
- 系统提示构建
- 工具描述和列表构建

**接口：**
```python
context_orchestrator = ContextOrchestrator(agent_ref)
context_orchestrator.init_context_system()
context = await context_orchestrator.build_context(
    user_input, tool_memory_result, experience_items, relevant_memories
)
system_prompt = context_orchestrator.build_system_prompt(tools_desc)
tools = await context_orchestrator.build_tools_for_llm()
```

### ToolExecutor (485行)

统一工具执行器，封装所有工具执行相关操作。

**职责：**
- 文本工具调用解析与执行
- 肌肉记忆工具执行
- Skill/CLI/MCP 工具分派
- 内置工具参数信息

**接口：**
```python
tool_executor = ToolExecutor(agent_ref)
result = await tool_executor.execute_text_tool_calls(reply, user_input)
```

## 设计原则

1. **深度模块**：小接口，深实现
2. **依赖注入**：通过 `agent_ref` 访问 Agent 实例属性
3. **可独立测试**：不依赖 Agent 类的完整初始化
4. **向后兼容**：保留旧导入路径

## 测试

```bash
# 运行 tracer bullet 测试
python -m pytest tests/unit/test_agent_chat_tracer_bullet.py -v

# 验证导入
python -c "from neurova.agent import Agent, AgentConfig, MemoryAgent, ContextOrchestrator, ToolExecutor; print('OK')"
```

## 重构效果

- **agent_core.py**: 2,180 → 1,621 行 (-25.6%)
- **测试覆盖**: 13/13 tracer bullet 测试全部通过
- **Linter**: 0 错误

# Bug Fix: ToolRouter Skill/MCP 路由阻断

## 问题描述

**报告时间**: 2026-06-10  
**严重程度**: 高  
**影响范围**: 所有通过 ToolRouter 执行的 Skill 和 MCP 工具  

### 问题现象

ToolRouter 的 `execute()` 方法中存在路由阻断问题，导致 Skill 和 MCP 工具无法通过 ToolRouter 正常调用。具体表现为：

1. **Skill 工具不可用**: 通过 ToolRouter 调用 Skill 工具时，总是返回 "Tool not found" 错误
2. **MCP 工具不可用**: 通过 ToolRouter 调用 MCP 工具时，同样返回 "Tool not found" 错误  
3. **路由逻辑失效**: `_execute_skill` 和 `_execute_mcp` 分支永远不会被触达，成为死代码

### 影响范围

- Agent 系统无法通过 ToolRouter 执行 Skill 工具
- Agent 系统无法通过 ToolRouter 执行 MCP 工具
- ContextOrchestrator 获取工具列表时参数不匹配
- 向后兼容性受损（`route()` 方法缺失）

## 根因分析

### 核心问题：门控检查逻辑错误

`neurova/tool_layers/tool_router.py:152-158` 中的 `execute()` 方法存在逻辑缺陷：

```python
# 原始错误代码（第152-158行）
tool = None
source = None

# 检查内置工具
if tool_name in self._builtin_tools:
    tool = self._builtin_tools[tool_name]
    source = "builtin"

# 如果工具未找到，直接返回错误（跳过了 Skill 和 MCP 检查）
if tool is None:
    return ToolResult(
        success=False,
        error=f"Tool not found: {tool_name}",
        ...
    )
```

### 问题分析

1. **门控检查过早**: 在检查 Skill 和 MCP 工具之前就进行了"工具未找到"的返回
2. **工具注册不完整**: Skill 工具由 `_skill_manager` 管理，MCP 工具由 `_mcp_clients` 管理，但它们都不在 `_builtin_tools` 字典中
3. **类型检查缺失**: 原始代码没有检查工具的 `is_mcp` 或 `is_skill` 属性
4. **向后兼容性缺失**: `tool_executor.py:400` 调用 `route()` 方法但不存在

### 技术细节

- **Skill 工具**: 由 `SkillManager` 动态管理，通过 `skill_manager.get_skill_tools()` 获取
- **MCP 工具**: 由多个 `MCPToolClient` 实例管理，通过 `client.list_tools()` 获取
- **内置工具**: 注册在 `_builtin_tools` 字典中，静态定义

## 修复方案

### 1. 添加工具代理数据类

引入 `_SkillToolProxy` 和 `_MCPToolProxy` 数据类，用于类型分发：

```python
@dataclass
class _SkillToolProxy:
    name: str
    skill_name: str
    is_skill: bool = True
    is_mcp: bool = False
    source: str = "skill"
    description: str = ""
    parameters: typing.Dict[str, typing.Any] = field(default_factory=dict)

@dataclass
class _MCPToolProxy:
    name: str
    server_id: str
    is_mcp: bool = True
    is_skill: bool = False
    source: str = "mcp"
    description: str = ""
    parameters: typing.Dict[str, typing.Any] = field(default_factory=dict)
```

### 2. 重写 execute() 方法

实现三源解析逻辑：

```python
async def execute(self, tool_name: str, params: typing.Dict[str, typing.Any], 
                  agent_id: typing.Optional[str] = None, 
                  user_id: typing.Optional[str] = None) -> ToolResult:
    tool = None
    source = None
    
    # 1. 内置工具
    if tool_name in self._builtin_tools:
        tool = self._builtin_tools[tool_name]
        source = "builtin"
    
    # 2. Skill 工具
    if tool is None and self._skill_manager:
        tool = await self._resolve_skill_tool(tool_name)
        if tool:
            source = "skill"
    
    # 3. MCP 工具
    if tool is None and self._mcp_clients:
        tool = await self._resolve_mcp_tool(tool_name)
        if tool:
            source = "mcp"
    
    # 门控检查（现在正确）
    if tool is None:
        return ToolResult(
            success=False,
            error=f"Tool not found: {tool_name}",
            ...
        )
    
    # ... 执行逻辑
```

### 3. 添加动态解析方法

- `_resolve_skill_tool()`: 从 SkillManager 动态解析 Skill 工具
- `_resolve_mcp_tool()`: 从所有 MCP 客户端动态解析 MCP 工具

### 4. 添加向后兼容别名

添加 `route()` 方法作为 `execute()` 的别名，修复 `tool_executor.py:400` 的调用问题。

### 5. 修复 get_all_tools() 方法

修改 `get_all_tools()` 以聚合三个来源的工具，并支持 `agent_id`/`user_id` 参数，修复 `context/orchestrator.py:548` 的参数不匹配问题。

### 6. 修复 _execute_mcp() 方法

修改 `_execute_mcp()` 以正确使用 `server_id` 而不是 `source`：

```python
# 修复前
server_id = tool.source  # 返回 "mcp"，不是实际的 server_id

# 修复后
server_id = getattr(tool, 'server_id', None) or getattr(tool, 'source', None)
```

## 修改文件

### 主要修改文件

1. **neurova/tool_layers/tool_router.py** (核心修复)
   - 添加 `_SkillToolProxy` 和 `_MCPToolProxy` 数据类
   - 重写 `execute()` 方法实现三源解析
   - 添加 `_resolve_skill_tool()` 和 `_resolve_mcp_tool()` 方法
   - 添加 `route()` 向后兼容别名
   - 修复 `get_all_tools()` 方法签名和实现
   - 修复 `_execute_mcp()` 使用 `server_id`

### 测试文件

2. **tests/unit/test_tool_router_routing.py** (新增，23个测试)
   - 内置工具路由测试 (3个)
   - Skill 工具路由测试 (5个)
   - MCP 工具路由测试 (5个)
   - 工具优先级测试 (2个)
   - get_all_tools 聚合测试 (3个)
   - route() 别名测试 (3个)
   - MCP 执行源测试 (2个)

## 测试结果

### 单元测试

```
============================= test session starts =============================
collected 23 items

tests/unit/test_tool_router_routing.py::TestBuiltinToolRouting::test_builtin_tool_found PASSED [  4%]
tests/unit/test_tool_router_routing.py::TestBuiltinToolRouting::test_builtin_tool_not_found PASSED [  8%]
tests/unit/test_tool_router_routing.py::TestBuiltinToolRouting::test_isolation_context_injected PASSED [ 13%]
tests/unit/test_tool_router_routing.py::TestSkillToolRouting::test_skill_tool_resolved_from_manager PASSED [ 17%]
tests/unit/test_tool_router_routing.py::TestSkillToolRouting::test_skill_tool_has_skill_attribute PASSED [ 21%]
tests/unit/test_tool_router_routing.py::TestSkillToolRouting::test_skill_tool_not_found PASSED [ 26%]
tests/unit/test_tool_router_routing.py::TestSkillToolRouting::test_skill_manager_has_skill_false PASSED [ 30%]
tests/unit/test_tool_router_routing.py::TestSkillToolRouting::test_skill_manager_no_skills_dict PASSED [ 34%]
tests/unit/test_tool_router_routing.py::TestMCPToolRouting::test_mcp_tool_resolved_from_client PASSED [ 39%]
tests/unit/test_tool_router_routing.py::TestMCPToolRouting::test_mcp_tool_has_mcp_attribute PASSED [ 43%]
tests/unit/test_tool_router_routing.py::TestMCPToolRouting::test_mcp_tool_not_found PASSED [ 47%]
tests/unit/test_tool_router_routing.py::TestMCPToolRouting::test_mcp_client_list_tools_exception PASSED [ 52%]
tests/unit/test_tool_router_routing.py::TestMCPToolRouting::test_mcp_client_no_list_tools PASSED [ 56%]
tests/unit/test_tool_router_routing.py::TestToolPriority::test_builtin_over_skill PASSED [ 60%]
tests/unit/test_tool_router_routing.py::TestToolPriority::test_skill_over_mcp PASSED [ 65%]
tests/unit/test_tool_router_routing.py::TestGetAllTools::test_aggregates_all_sources PASSED [ 69%]
tests/unit/test_tool_router_routing.py::TestGetAllTools::test_get_all_tools_with_params PASSED [ 73%]
tests/unit/test_tool_router_routing.py::TestGetAllTools::test_empty_when_no_sources PASSED [ 78%]
tests/unit/test_tool_router_routing.py::TestRouteAlias::test_route_returns_result_directly PASSED [ 82%]
tests/unit/test_tool_router_routing.py::TestRouteAlias::test_route_raises_on_failure PASSED [ 86%]
tests/unit/test_tool_router_routing.py::TestRouteAlias::test_route_with_skill PASSED [ 91%]
tests/unit/test_tool_router_routing.py::TestMCPExecuteSource::test_mcp_execute_uses_server_id PASSED [ 95%]
tests/unit/test_tool_router_routing.py::TestMCPExecuteSource::test_mcp_execute_server_not_found PASSED [100%]

============================== 23 passed, 4 warnings in 0.11s ==============================
```

### Linter 检查

```
neurova/tool_layers/tool_router.py: 0 errors
```

## 验证结果

1. **功能验证**: 所有 23 个测试通过，覆盖三个工具来源的路由逻辑
2. **向后兼容性**: `route()` 方法别名修复了现有调用
3. **参数兼容性**: `get_all_tools()` 支持 `agent_id`/`user_id` 参数
4. **类型安全**: 代理数据类确保正确的类型分发
5. **错误处理**: 改进的错误消息和异常处理

## 架构改进

### 修复前的问题

```
ToolRouter.execute()
  ↓
检查 _builtin_tools（仅内置工具）
  ↓
工具未找到？→ 返回错误（跳过 Skill/MCP）
  ↓
永远无法执行 Skill/MCP 工具
```

### 修复后的流程

```
ToolRouter.execute()
  ↓
1. 检查 _builtin_tools（内置工具）
  ↓
2. 检查 _skill_manager（Skill 工具）
  ↓
3. 检查 _mcp_clients（MCP 工具）
  ↓
工具未找到？→ 返回错误（已检查所有来源）
  ↓
根据 is_mcp/is_skill 属性选择执行方式
  ↓
成功执行工具
```

## 后续建议

1. **性能优化**: 考虑添加工具缓存，避免每次执行都重新解析
2. **工具注册**: 实现统一的工具注册表，简化三源管理
3. **监控增强**: 添加工具路由的性能监控和统计
4. **文档更新**: 更新 ToolRouter 的 API 文档和使用示例

## 相关文件

- `neurova/tool_layers/tool_router.py` - 核心修复
- `neurova/agent/tool_executor.py:400` - 调用 route() 方法
- `neurova/context/orchestrator.py:548` - 调用 get_all_tools() 方法
- `neurova/agent/skill_manager.py` - Skill 工具管理
- `neurova/tool_layers/mcp_client.py` - MCP 工具管理
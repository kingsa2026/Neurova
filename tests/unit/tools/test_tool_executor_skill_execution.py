"""
P0.1-P0.2 测试：修复 tool_executor.execute_skill_tool 调用正典路径

P0 Bug 根因（双重 Bug）：
1. SkillRegistry.get_skill() 返回 Optional[Tuple[Skill, Path]]（元组），
   但 line 348 把元组当 Skill 对象调用 .execute()
2. Skill dataclass 无 execute() 方法（只有 manifest 字段）

正确做法：调用 SkillRegistry.execute_skill(skill_name, params, context)（registry.py:150-203）
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.skills.executor import SkillResult


@pytest.fixture
def mock_agent_with_registry():
    """创建 mock agent，其 _skill_registry 是 AsyncMock"""
    mock_registry = AsyncMock()
    mock_agent = MagicMock()
    mock_agent._skill_registry = mock_registry
    return mock_agent, mock_registry


@pytest.mark.asyncio
async def test_execute_skill_tool_calls_registry_execute_skill(mock_agent_with_registry):
    """P0.1: execute_skill_tool 应调用 registry.execute_skill() 而非 get_skill().execute()"""
    from neurova.tool_executor import ToolExecutor

    mock_agent, mock_registry = mock_agent_with_registry
    mock_registry.execute_skill.return_value = SkillResult(success=True, output="ok")

    executor = ToolExecutor(mock_agent)
    result = await executor.execute_skill_tool("memory_search", {"query": "test"})

    # 验证调用了 execute_skill（正典路径），而非 get_skill + .execute()
    mock_registry.execute_skill.assert_awaited_once()
    call_args = mock_registry.execute_skill.await_args
    assert call_args.args[0] == "memory_search", "应传入 skill_name 作为第一参数"

    # 验证返回结果格式
    assert result["success"] is True
    assert result["output"] == "ok"


@pytest.mark.asyncio
async def test_execute_skill_tool_nonexistent_returns_error(mock_agent_with_registry):
    """P0.2: 不存在的 skill 应返回错误（捕获 ValueError）"""
    from neurova.tool_executor import ToolExecutor

    mock_agent, mock_registry = mock_agent_with_registry
    mock_registry.execute_skill.side_effect = ValueError("技能 nonexistent 未注册")

    executor = ToolExecutor(mock_agent)
    result = await executor.execute_skill_tool("nonexistent", {})

    # 应返回错误，不应抛出异常
    assert result.get("success") is False or "error" in result
    assert "未注册" in str(result) or "不存在" in str(result)


@pytest.mark.asyncio
async def test_execute_skill_tool_no_registry_returns_error():
    """P0 补充: _skill_registry 为 None 时应返回错误"""
    from neurova.tool_executor import ToolExecutor

    mock_agent = MagicMock()
    mock_agent._skill_registry = None

    executor = ToolExecutor(mock_agent)
    result = await executor.execute_skill_tool("any", {})

    assert "error" in result
    assert "未初始化" in result["error"] or "not" in result["error"].lower()

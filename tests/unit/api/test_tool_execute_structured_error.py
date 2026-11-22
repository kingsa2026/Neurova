"""TDD：/tools/execute 失败面结构化错误信封透传（批四移交项）。

U3（远程失联相位）/U12（TOOL_UNSUPPORTED）/U1（主机密钥）在咽喉层产出
结构化失败载荷（error_code/phase/retryable/executed/needs_credential...），
此前被端点压扁成裸 error 字符串——前端/模型拿不到可判读语义。
本卡钉约：失败时原始载荷原样进 data.result（不丢任何结构化字段），
顶层 error 串保留兼容既有消费方。
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch


STRUCTURED_FAILURE = {
    "error": "SSH 连接失败: [Errno 111] Connection refused",
    "error_code": "REMOTE_NOT_EXECUTED",
    "phase": "connect",
    "retryable": True,
    "executed": False,
    "host": "127.0.0.1",
    "command": "echo probe",
}


def _mockAgentWithStructuredFailure():
    executor = Mock()
    executor.execute = AsyncMock(return_value=dict(STRUCTURED_FAILURE))
    executor._result_is_success = Mock(return_value=False)
    agent = Mock()
    agent.tool_executor = executor
    return agent


def _emptyEngine():
    """对齐既有端点测试的空引擎形态（属主门查无注册 → 放行进咽喉支）。"""
    engine = Mock()
    engine.execute_with_safeguards = AsyncMock(
        side_effect=ValueError("工具未注册（测试不走到这一支）"))
    engine.list_tools = Mock(return_value=[])
    engine.get_tool = Mock(return_value=None)
    return engine


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["error_code", "phase", "retryable", "executed"])
async def test_execute_failure_carries_structured_envelope(field):
    from neurova.api.endpoints import tool_layers
    from neurova.api.endpoints.tool_layers import (
        execute_tool,
        ToolExecuteRequest,
    )

    agent = _mockAgentWithStructuredFailure()
    with patch.object(tool_layers, "get_tool_engine", return_value=_emptyEngine()), \
         patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
        body = ToolExecuteRequest(
            tool_name="computer_ssh_exec",
            arguments={"host": "127.0.0.1", "command": "echo probe"},
            timeout=5,
        )
        response = await execute_tool(
            body, current_user={"user_id": "u_test", "username": "tester",
                                "role": "user", "neuser_id": "ne_test"}
        )

    assert response["code"] == 1, "结构化失败载荷应仍判失败（code=1）"
    carried = (response.get("data") or {}).get("result") or {}
    assert carried.get(field) == STRUCTURED_FAILURE[field], (
        f"失败面丢了结构化字段 {field!r}——被压扁成裸 error 串: {response}"
    )
    # 顶层 error 串保留（既有消费方按 error 判读的契约不破坏）
    assert "SSH 连接失败" in (response.get("error") or "")

"""agent_reach 内置工具三元组（schema 单源 / 分派表 / 执行体）测试。

schema/dispatch 全量对账由既有守卫（test_builtin_tools_expansion、
test_tool_schema_contract）承担；本文件钉 agent_reach 自己的行为面：
三种 mode 的路由、参数校验、失败诚实透传。
"""

from unittest.mock import Mock

import pytest

from neurova.builtin_tools import _BUILTIN_SCHEMAS, get_builtin_tool_params
from neurova.web_reach import agent_reach_cli as cli


def _make_executor():
    from neurova.tool_executor import ToolExecutor

    agent = Mock()
    agent._skill_registry = Mock()
    agent.tool_router = Mock()
    agent.tool_memory = Mock()
    agent.tool_lifecycle = Mock()
    agent.skill_packer = Mock()
    agent.config = Mock()
    agent.memory_manager = Mock()
    agent.asr_manager = None
    agent.tts_manager = None
    return ToolExecutor(agent)


class TestSchemaAndDispatch:
    def test_schemaRegistered(self):
        entry = get_builtin_tool_params("agent_reach")
        assert entry is not None, "agent_reach 必须进 schema 单源"
        assert entry["parameters"]["required"] == ["mode"]
        modeEnum = entry["parameters"]["properties"]["mode"]["enum"]
        assert modeEnum == ["channels", "read", "action"]

    def test_dispatchRowPointsToRealMethod(self):
        dispatch = type(_make_executor())._builtin_dispatch
        assert dispatch.get("agent_reach") == "_execute_agent_reach"
        assert callable(getattr(type(_make_executor()), "_execute_agent_reach", None))

    def test_capabilitySharedScopeSerial(self):
        """共享 ~/.agent-reach 状态目录 → shared 作用域，合取判据自动串行。"""
        cap = _BUILTIN_SCHEMAS["agent_reach"]["capability"]
        assert cap["readOnly"] is True
        assert cap["writeScopes"] == ("shared",)


class TestExecutorModes:
    @pytest.mark.asyncio
    async def test_channelsModeDelegatesToBridge(self, monkeypatch):
        sentinel = {"success": True, "channels": []}
        monkeypatch.setattr(cli, "runChannels", lambda: sentinel)
        result = await _make_executor()._execute_agent_reach({"mode": "channels"})
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_readModeRequiresUrl(self):
        result = await _make_executor()._execute_agent_reach({"mode": "read"})
        assert result["success"] is False
        assert "url" in result["error"]

    @pytest.mark.asyncio
    async def test_readModeDelegatesToBridge(self, monkeypatch):
        sentinel = {"success": True, "items": []}
        seen = {}
        monkeypatch.setattr(cli, "runRead", lambda url: seen.update(url=url) or sentinel)
        result = await _make_executor()._execute_agent_reach(
            {"mode": "read", "url": "https://example.com"}
        )
        assert result is sentinel
        assert seen["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_actionModeRequiresChannelAndAction(self):
        result = await _make_executor()._execute_agent_reach({"mode": "action"})
        assert result["success"] is False
        assert "channel" in result["error"]

    @pytest.mark.asyncio
    async def test_actionModeDelegatesWithNormalizedParams(self, monkeypatch):
        sentinel = {"success": True, "items": []}
        seen = {}

        def fakeAction(channel, action, target=None, limit=None, extraArgs=None):
            seen.update(channel=channel, action=action, target=target, limit=limit, extraArgs=extraArgs)
            return sentinel

        monkeypatch.setattr(cli, "runChannelAction", fakeAction)
        result = await _make_executor()._execute_agent_reach(
            {
                "mode": "action",
                "channel": "github",
                "action": "search",
                "target": "fastapi",
                "limit": "5",
                "extra_args": ["--timeout", "30"],
            }
        )
        assert result is sentinel
        assert seen == {
            "channel": "github", "action": "search", "target": "fastapi",
            "limit": 5, "extraArgs": ["--timeout", "30"],
        }

    @pytest.mark.asyncio
    async def test_actionModeRejectsNonIntLimit(self):
        result = await _make_executor()._execute_agent_reach(
            {"mode": "action", "channel": "github", "action": "search", "limit": "abc"}
        )
        assert result["success"] is False
        assert "limit" in result["error"]

    @pytest.mark.asyncio
    async def test_unknownModeRejectedHonestly(self):
        result = await _make_executor()._execute_agent_reach({"mode": "shell"})
        assert result["success"] is False
        assert "channels/read/action" in result["error"]

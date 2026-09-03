"""
TDD 红绿灯测试 — ToolMarketplace 自动发布断点修复

问题（Bug A，预存断点）:
  _step_marketplace_publish 用
      MarketplaceTool(name=..., description=..., schema=..., agent_id=...)
  构造市场工具。但真实 tool_layers/tool_marketplace.py 的 MarketplaceTool
  dataclass 需要必填 `tool_id`（位置参数首参，无默认值），且**没有**
  schema / agent_id 字段。于是 `MarketplaceTool(...)` 抛出 TypeError，
  被 `except (ImportError, Exception)` 吞掉 —— 导致「使用过的工具自动发布
  到市场」静默失败，published_tools 恒为空，市场永远不会获得自动工具。
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from neurova.post_chat_pipeline import PostChatPipeline, StepStatus
from neurova.tool_layers.tool_marketplace import MarketplaceTool


@pytest.fixture
def marketplace():
    """假工具市场，记录 add_tool 调用"""
    m = MagicMock()
    m.add_tool = MagicMock()
    m.has_tool = MagicMock(return_value=False)
    return m


def _make_agent():
    agent = MagicMock()
    agent.config.agent_id = "agent_kai"
    agent._collect_tool_messages.return_value = [
        {
            "tool_name": "web_search",
            "type": "tool_result",
            "success": True,
            "result": {"content": "ok"},
        }
    ]
    skill = MagicMock()
    skill.description = "网页搜索工具"
    skill.to_schema.return_value = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
    }
    agent._skill_registry.get_skill.return_value = skill
    return agent


@pytest.fixture
def pipeline(marketplace):
    """注入 tool_marketplace 的 PostChatPipeline"""
    p = PostChatPipeline(agent_ref=_make_agent())
    p.configure(tool_marketplace=marketplace)
    return p


class TestMarketplaceAutoPublish:
    @pytest.mark.asyncio
    async def test_publish_constructs_valid_marketplace_tool(self, pipeline, marketplace):
        """应构造带必填 tool_id/name 的合法 MarketplaceTool 并成功发布"""
        await pipeline._step_marketplace_publish()
        assert marketplace.add_tool.called, "add_tool 应被调用（当前 TypeError 被吞导致未调用）"
        published = marketplace.add_tool.call_args[0][0]
        assert isinstance(published, MarketplaceTool)
        assert published.tool_id
        assert published.name == "web_search"

    @pytest.mark.asyncio
    async def test_publish_records_step_success(self, pipeline, marketplace):
        """步骤结果应标记 EXECUTED 且 published_tools 非空"""
        await pipeline._step_marketplace_publish()
        result = pipeline._step_results[-1]
        assert result.status == StepStatus.EXECUTED
        assert result.data.get("published_tools") == ["web_search"]

    @pytest.mark.asyncio
    async def test_publish_keeps_schema_and_agent_in_metadata(self, pipeline, marketplace):
        """schema 与 agent_id 应保留在 MarketplaceTool.metadata 中（不应丢失）"""
        await pipeline._step_marketplace_publish()
        published = marketplace.add_tool.call_args[0][0]
        assert published.metadata.get("schema") == {
            "type": "object",
            "properties": {"q": {"type": "string"}},
        }
        assert published.metadata.get("agent_id") == "agent_kai"

    @pytest.mark.asyncio
    async def test_publish_skips_failed_tool(self, pipeline):
        """发布失败的工具（success=False）不应进入市场"""
        agent = _make_agent()
        agent._collect_tool_messages.return_value = [
            {"tool_name": "bad_tool", "type": "tool_result", "success": False}
        ]
        p = PostChatPipeline(agent_ref=agent)
        mkt = MagicMock()
        mkt.add_tool = MagicMock()
        p.configure(tool_marketplace=mkt)
        await p._step_marketplace_publish()
        assert not mkt.add_tool.called

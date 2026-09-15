# -*- coding: utf-8 -*-
"""P1-5 Tool Search 默认激活（inert-but-ready → live）。

原 A6 机制（neurova/context/tool_search.py）已完整交付但 env 门控默认关
（NEUROVA_TOOL_SEARCH=1 才激活）。P1-5：
翻转为默认激活——未设置 env 时按规模阈值自动启用；NEUROVA_TOOL_SEARCH=0
保留显式关闭开关（只提升不下降约束的退路）。
"""
import pytest


def _fake_tools(n: int) -> list:
    return [
        {
            "type": "function",
            "function": {"name": f"longtail_tool_{i}", "description": f"长尾工具 {i}", "parameters": {"type": "object", "properties": {}}},
        }
        for i in range(n)
    ]


def _orchestrator():
    from unittest.mock import MagicMock

    from neurova.context.orchestrator import ContextOrchestrator

    agent = MagicMock()
    orch = ContextOrchestrator.__new__(ContextOrchestrator)
    orch._agent = agent
    return orch


class TestToolSearchDefaultOn:
    def test_default_activates_when_catalog_large(self, monkeypatch):
        """无 env 设置：隐藏候选 ≥ 阈值 → 压缩生效（直连+控制工具可见）。"""
        monkeypatch.delenv("NEUROVA_TOOL_SEARCH", raising=False)
        orch = _orchestrator()
        tools = _fake_tools(60)  # 60-13=47 隐藏 ≥ 40
        out = orch._apply_tool_search_compaction(tools)
        assert out is not tools
        names = {t["function"]["name"] for t in out}
        assert "longtail_tool_0" not in names       # 长尾被隐藏
        assert "tool_search_directory" in names     # 目录入口存在
        assert any("隐藏工具目录" in t["function"]["description"] for t in out)

    def test_env_zero_disables(self, monkeypatch):
        """NEUROVA_TOOL_SEARCH=0：显式关闭，清单原样。"""
        monkeypatch.setenv("NEUROVA_TOOL_SEARCH", "0")
        orch = _orchestrator()
        tools = _fake_tools(60)
        assert orch._apply_tool_search_compaction(tools) is tools

    def test_small_catalog_untouched(self, monkeypatch):
        """隐藏候选 < 阈值：不压缩（零行为变化）。"""
        monkeypatch.delenv("NEUROVA_TOOL_SEARCH", raising=False)
        orch = _orchestrator()
        tools = _fake_tools(20)
        assert orch._apply_tool_search_compaction(tools) is tools

    def test_empty_tools_untouched(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_TOOL_SEARCH", raising=False)
        orch = _orchestrator()
        assert orch._apply_tool_search_compaction([]) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

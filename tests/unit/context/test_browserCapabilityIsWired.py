# -*- coding: utf-8 -*-
"""P2-10（审计 2026-11-04）：浏览器后端能力描述接进 system prompt。

工具面出现 browser_/computer_ 工具时，get_tools_description 追加真后端能力段；
没有已知后端或没有相关工具时返回空串，不注入编造能力。
"""
import asyncio

from neurova.context.orchestrator import ContextOrchestrator
from neurova.tool_layers.browser_capability import buildBrowserCapabilityContext


def test_contextOnlyListsRealBackends():
    text = buildBrowserCapabilityContext(["playwright", "scrapling"])
    assert "playwright" in text
    assert "scrapling" in text
    assert "camofox" not in text, "未实装的后端不得出现在能力描述里"
    assert "不执行 JavaScript" in text, "scrapling 的限制必须如实告知模型"


def test_unknownBackendsProduceEmptyContext():
    assert buildBrowserCapabilityContext(["not-a-real-backend"]) == ""
    assert buildBrowserCapabilityContext([]) == ""


def test_getToolsDescriptionAppendsSectionOnlyWhenBrowserToolsPresent(monkeypatch):
    from neurova.context import orchestrator as orchestrator_module

    async def _browserTools():
        return [{"type": "function", "function": {"name": "browser_navigate", "description": "go"}}]

    instance = ContextOrchestrator.__new__(ContextOrchestrator)
    instance.build_tools_for_llm = _browserTools
    monkeypatch.setattr(orchestrator_module, "render_tools_description", lambda tools: "## 可用工具\n- browser_navigate")
    monkeypatch.setattr(
        "neurova.tool_layers.browser_capability.buildBrowserCapabilityContext",
        lambda: "## 浏览器后端能力\nBrowser Backend: playwright",
    )
    text = asyncio.run(instance.get_tools_description())
    assert "## 可用工具" in text
    assert "## 浏览器后端能力" in text


def test_getToolsDescriptionSkipsSectionWithoutBrowserTools(monkeypatch):
    from neurova.context import orchestrator as orchestrator_module

    async def _weatherTools():
        return [{"type": "function", "function": {"name": "weather", "description": "forecast"}}]

    def _mustNotCall():
        raise AssertionError("没有浏览器工具时不该读取浏览器能力")

    instance = ContextOrchestrator.__new__(ContextOrchestrator)
    instance.build_tools_for_llm = _weatherTools
    monkeypatch.setattr(orchestrator_module, "render_tools_description", lambda tools: "## 可用工具\n- weather")
    monkeypatch.setattr(
        "neurova.tool_layers.browser_capability.buildBrowserCapabilityContext", _mustNotCall,
    )
    text = asyncio.run(instance.get_tools_description())
    assert "## 浏览器后端能力" not in text

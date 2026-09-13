"""
P1-2 searxng 自托管搜索 provider（TDD）。

实测修正（对计划文档 P1-2）：web_search 并无 provider 管理子系统（计划假设
"llm/搜索 provider 管理已有"不成立——那是 LLM 服务商侧），现状为硬编码 Bing
HTML 抓取。本项按实际架构落为：settings.searxng_url 配置一个自托管后端时
优先走 searxng /search?format=json，失败/未配置回退 Bing 原路径（只提升不
下降），结果带 backend 字段诚实标注来源。
"""

import io
import json
from unittest.mock import Mock, patch

import pytest


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
    return ToolExecutor(agent)


BING_HTML = '<html><div class="b_caption"><p> Bing 摘要内容 </p></div></html>'
SEARXNG_JSON = json.dumps({
    "query": "t",
    "results": [
        {"title": "结果一", "url": "https://a.example/1", "content": "摘要一"},
        {"title": "结果二", "url": "https://a.example/2", "content": "摘要二"},
    ],
})


def _settings_with(value):
    """返回 patch get_shared_config_manager 的 side_effect 工厂。"""
    mgr = Mock()
    mgr.get_settings = Mock(return_value={"searxng_url": value} if value is not None else {})
    return patch("neurova.shared_config.get_shared_config_manager", return_value=mgr)


class TestSearxngBackend:
    @pytest.mark.asyncio
    async def test_not_configured_uses_bing(self):
        exe = _make_executor()
        with _settings_with(None), patch.object(exe, "_blocking_fetch", return_value=BING_HTML) as fb:
            result = await exe._execute_builtin_tool("web_search", {"query": "x"})
        assert result.get("backend") == "bing"
        assert "Bing 摘要内容" in result["results"]

    @pytest.mark.asyncio
    async def test_configured_uses_searxng_json(self):
        exe = _make_executor()
        with _settings_with("http://127.0.0.1:8888"), patch.object(
            exe, "_blocking_fetch", return_value=SEARXNG_JSON
        ) as fb:
            result = await exe._execute_builtin_tool("web_search", {"query": "x"})
        assert result.get("backend") == "searxng"
        assert "结果一" in result["results"] and "https://a.example/1" in result["results"]
        # 请求打到配置的实例且 format=json
        called_url = fb.call_args[0][0]
        assert called_url.startswith("http://127.0.0.1:8888/search")
        assert "format=json" in called_url and "q=x" in called_url

    @pytest.mark.asyncio
    async def test_searxng_failure_falls_back_to_bing(self):
        """诚实降级：searxng 不可达不得吞错——回退 Bing 且 backend 标注 fallback。"""
        import urllib.error

        exe = _make_executor()

        def fake_fetch(url, ua, timeout=10):
            if "127.0.0.1:8888" in url:
                raise urllib.error.URLError("connection refused")
            return BING_HTML

        with _settings_with("http://127.0.0.1:8888"), patch.object(exe, "_blocking_fetch", side_effect=fake_fetch):
            result = await exe._execute_builtin_tool("web_search", {"query": "x"})
        assert result.get("backend") == "searxng_fallback_bing"
        assert "Bing 摘要内容" in result["results"]

    @pytest.mark.asyncio
    async def test_searxng_invalid_json_falls_back(self):
        exe = _make_executor()

        def fake_fetch(url, ua, timeout=10):
            if "127.0.0.1:8888" in url:
                return "<html>not json (format=json 未开启)"
            return BING_HTML

        with _settings_with("http://127.0.0.1:8888"), patch.object(exe, "_blocking_fetch", side_effect=fake_fetch):
            result = await exe._execute_builtin_tool("web_search", {"query": "x"})
        assert result.get("backend") == "searxng_fallback_bing"

    @pytest.mark.asyncio
    async def test_searxng_empty_results_honest(self):
        exe = _make_executor()
        with _settings_with("http://127.0.0.1:8888"), patch.object(
            exe, "_blocking_fetch", return_value=json.dumps({"results": []})
        ):
            result = await exe._execute_builtin_tool("web_search", {"query": "x"})
        assert result.get("backend") == "searxng"
        # 空结果不得伪装成有内容，也不得回退 Bing 掩盖
        assert result["results"].strip() == "" or "未返回结果" in result["results"]

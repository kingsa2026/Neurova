"""
P1-1 deep_research 工具（TDD）。

设计（对计划 P1-1 的收敛）：不做阻塞整轮的重型 LLM 编排引擎（那会重复
spawn_subagent 能力、违背 Simplicity/不镀金，且长耗时阻塞对话）。落为**有界
多源采集器**：对 query(+子查询) 批量检索 → 抽取候选 URL 去重 → web_fetch 取
正文摘录 → 返回带 [n] 编号引用的源料包；报告综合交回主 LLM（本就在环内）。
价值：省去 agent 多轮 search+fetch 往返，引用真实可溯源；无工具内 LLM 调用，
不阻塞、可离线测（mock _blocking_fetch）。
"""

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


SEARXNG_RESULTS = json.dumps({
    "results": [
        {"title": "文章一", "url": "https://ex.com/a", "content": "摘要一"},
        {"title": "文章二", "url": "https://ex.com/b", "content": "摘要二"},
        {"title": "文章三", "url": "https://ex.com/c", "content": "摘要三"},
    ]
})


def _settings_searxng():
    mgr = Mock()
    mgr.get_settings = Mock(return_value={"searxng_url": "http://127.0.0.1:8888"})
    return patch("neurova.shared_config.get_shared_config_manager", return_value=mgr)


def _fake_fetch(url, ua, timeout=10):
    """searxng /search → JSON 结果；其余 URL → 网页正文。"""
    if "127.0.0.1:8888" in url:
        return SEARXNG_RESULTS
    return "<html><body><p>正文内容 for " + url + "</p>" + "填充" * 50 + "</body></html>"


class TestDeepResearchRegistration:
    def test_schema_and_dispatch(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS
        from neurova.tool_executor import ToolExecutor

        assert "deep_research" in _BUILTIN_SCHEMAS
        assert "query" in _BUILTIN_SCHEMAS["deep_research"]["parameters"]["properties"]
        assert "deep_research" in ToolExecutor._builtin_dispatch


class TestDeepResearchCollection:
    @pytest.mark.asyncio
    async def test_returns_numbered_cited_source_pack(self):
        exe = _make_executor()
        with _settings_searxng(), patch.object(exe, "_blocking_fetch", side_effect=_fake_fetch):
            result = await exe._execute_builtin_tool(
                "deep_research", {"query": "量子计算", "max_sources": 3}
            )
        assert "error" not in result, result
        assert result["sources"], "应至少采到一条源"
        # 编号引用：每条带 1-based index + url + excerpt
        for i, s in enumerate(result["sources"], start=1):
            assert s["index"] == i
            assert s["url"].startswith("http")
            assert "excerpt" in s
        # 引用块可直接注入报告
        assert "[1]" in result["citation_block"]

    @pytest.mark.asyncio
    async def test_max_sources_caps_fanout(self):
        exe = _make_executor()
        with _settings_searxng(), patch.object(exe, "_blocking_fetch", side_effect=_fake_fetch) as fb:
            result = await exe._execute_builtin_tool(
                "deep_research", {"query": "x", "max_sources": 2}
            )
        assert len(result["sources"]) <= 2

    @pytest.mark.asyncio
    async def test_dedupes_urls_across_subqueries(self):
        """子查询命中同一 URL 只采一次（去重）。"""
        exe = _make_executor()
        seen = {}

        def fake(url, ua, timeout=10):
            if "127.0.0.1:8888" in url:
                # 每次搜索都返回相同的两条 URL → 两个子查询应去重为 2 条源
                return json.dumps({"results": [
                    {"title": "T1", "url": "https://ex.com/dup", "content": "c"},
                    {"title": "T2", "url": "https://ex.com/other", "content": "c"},
                ]})
            return "<html><p>body</p></html>"

        with _settings_searxng(), patch.object(exe, "_blocking_fetch", side_effect=fake):
            result = await exe._execute_builtin_tool(
                "deep_research", {"query": "x", "sub_queries": ["a", "b"]}
            )
        urls = [s["url"] for s in result["sources"]]
        assert len(urls) == len(set(urls))

    @pytest.mark.asyncio
    async def test_failed_fetch_dropped_not_fatal(self):
        """单源抓取失败不得让整轮失败——诚实跳过该源（不吞整体）。"""
        exe = _make_executor()

        def fake(url, ua, timeout=10):
            if "127.0.0.1:8888" in url:
                return json.dumps({"results": [
                    {"title": "OK", "url": "https://ex.com/good", "content": "c"},
                    {"title": "Bad", "url": "https://ex.com/bad", "content": "c"},
                ]})
            if "bad" in url:
                raise OSError("403 forbidden")
            return "<html><p>good body</p></html>"

        with _settings_searxng(), patch.object(exe, "_blocking_fetch", side_effect=fake):
            result = await exe._execute_builtin_tool("deep_research", {"query": "x"})
        assert "error" not in result
        assert any("good" in s["url"] for s in result["sources"])
        assert all("bad" not in s["url"] for s in result["sources"])  # 失败源被剔除

    @pytest.mark.asyncio
    async def test_empty_results_honest(self):
        """完全搜不到 → 诚实返回空源，不编造。"""
        exe = _make_executor()
        with _settings_searxng(), patch.object(
            exe, "_blocking_fetch", return_value=json.dumps({"results": []})
        ):
            result = await exe._execute_builtin_tool("deep_research", {"query": "x"})
        assert result.get("sources") == []
        assert "未采集到" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_requires_query(self):
        exe = _make_executor()
        result = await exe._execute_builtin_tool("deep_research", {})
        assert "error" in result


class TestToolTimeouts:
    """复核修正闭环：新工具扇出/慢 IO 不得撞 60s 默认超时中途转后台。"""

    def test_registered_timeouts(self):
        from neurova.agent.tool_coordinator import TOOL_DEFAULT_TIMEOUT_S, get_tool_timeout

        assert get_tool_timeout("deep_research") > TOOL_DEFAULT_TIMEOUT_S
        assert get_tool_timeout("file_parse") > TOOL_DEFAULT_TIMEOUT_S
        assert get_tool_timeout("git") > TOOL_DEFAULT_TIMEOUT_S

    def test_file_parse_concurrency_safe(self):
        """file_parse 只读无共享态 → 并行安全名单；git/deep_research 保守留外。"""
        from neurova.agent.tool_coordinator import is_concurrency_safe

        assert is_concurrency_safe("file_parse")
        assert not is_concurrency_safe("git")

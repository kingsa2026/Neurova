# -*- coding: utf-8 -*-
"""T1 工具运行时自发现目录（reference_af 拆解卡）红灯测试。

契约（拆解评测 §5 卡 T1）：
- 新增只读工具 `tool_catalog_search` / `tool_doc`，让 agent 主动检索内置工具
  （对方的 capabilities/doc 范式）——工具面大（146 个），长尾工具靠猜名不可行；
- 数据单源：`neurova.tools.catalog`（builtin_tools 声明位的投影层），不另造
  第二份工具定义；
- 检索：keyword 大小写不敏感匹配名称+描述；tag 过滤（read_only/external_write/
  main_only）；limit 有界（默认 20、上限 100）；空命中如实空表；
- `tool_doc`：单工具全量档案（描述+参数 schema+能力声明+使用范围）；
  未知名 → 结构化 tool_not_found（不抛裸异常）。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.tool_executor import ToolExecutor


def _makeExecutor() -> ToolExecutor:
    agent = SimpleNamespace(
        config=SimpleNamespace(user_id="u1", agent_id="a1"),
        tool_memory=MagicMock(),
        tool_lifecycle=None,
        _skill_registry=None,
        tool_router=None,
        _current_user_input="x",
        _tool_messages_list=[],
        append_tool_messages=lambda records: None,
    )
    return ToolExecutor(agent)


class TestToolCatalogWiring:
    def test_schemas_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        assert "tool_catalog_search" in _BUILTIN_SCHEMAS
        assert "tool_doc" in _BUILTIN_SCHEMAS
        for name in ("tool_catalog_search", "tool_doc"):
            cap = _BUILTIN_SCHEMAS[name]["capability"]
            assert cap["readOnly"] is True, "目录是纯只读面"
            assert cap["concurrentSafe"] is True

    def test_dispatch_entries_present(self):
        executor = _makeExecutor()
        assert "tool_catalog_search" in executor._builtin_dispatch
        assert "tool_doc" in executor._builtin_dispatch


class TestToolCatalogSearch:
    @pytest.mark.asyncio
    async def test_keyword_finds_computer_screenshot(self):
        executor = _makeExecutor()
        res = await executor._execute_tool_catalog_search({"keyword": "screenshot"})
        assert res["success"] is True
        names = [row["name"] for row in res["tools"]]
        assert "computer_screenshot" in names
        row = next(r for r in res["tools"] if r["name"] == "computer_screenshot")
        assert row["description"]
        assert {"name", "description", "read_only", "agent_scope", "param_count"} <= set(row)

    @pytest.mark.asyncio
    async def test_keyword_matches_description_not_only_name(self):
        executor = _makeExecutor()
        res = await executor._execute_tool_catalog_search({"keyword": "剪贴板"})
        names = [row["name"] for row in res["tools"]]
        assert "computer_paste" in names, "中文描述关键字必须命中（描述匹配面）"

    @pytest.mark.asyncio
    async def test_empty_hit_is_honest_empty(self):
        executor = _makeExecutor()
        res = await executor._execute_tool_catalog_search(
            {"keyword": "zzz-no-such-tool-zzz"})
        assert res["success"] is True
        assert res["tools"] == [] and res["total"] == 0

    @pytest.mark.asyncio
    async def test_limit_bounds_result(self):
        executor = _makeExecutor()
        res = await executor._execute_tool_catalog_search({"limit": 5})
        assert res["success"] is True
        assert len(res["tools"]) <= 5
        assert res["total"] >= len(res["tools"])

    @pytest.mark.asyncio
    async def test_tag_filter_read_only(self):
        executor = _makeExecutor()
        res = await executor._execute_tool_catalog_search({"tag": "read_only", "limit": 100})
        assert res["success"] is True
        assert res["tools"], "只读工具族非空"
        assert all(row["read_only"] for row in res["tools"])

    @pytest.mark.asyncio
    async def test_unknown_tag_rejected(self):
        executor = _makeExecutor()
        res = await executor._execute_tool_catalog_search({"tag": "nope"})
        assert res["success"] is False and "tag" in res["error"]


class TestToolDoc:
    @pytest.mark.asyncio
    async def test_doc_returns_full_schema(self):
        executor = _makeExecutor()
        res = await executor._execute_tool_doc({"tool_name": "computer_click"})
        assert res["success"] is True
        tool = res["tool"]
        assert tool["name"] == "computer_click"
        assert tool["description"]
        assert "properties" in (tool["args_schema"] or {})

    @pytest.mark.asyncio
    async def test_doc_unknown_structured_not_found(self):
        executor = _makeExecutor()
        res = await executor._execute_tool_doc({"tool_name": "no-such-tool"})
        assert res["success"] is False
        assert res["error"] == "tool_not_found"
        assert res["tool_name"] == "no-such-tool"

    @pytest.mark.asyncio
    async def test_doc_missing_param_rejected(self):
        executor = _makeExecutor()
        res = await executor._execute_tool_doc({})
        assert res["success"] is False

"""P1-4 多知识库路由（TDD — Dify `multi_dataset_function_call_router` 对标）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §2.6/§4 P1-4）：
- 多库场景（>1 个 KB）先选库再检索：LLM FunctionCall 选库（提供每个库
  的 name/description 供模型选择），直连 multi_model_client
- MultiKBRouter.route(query, kbs)：
  - 0/1 个库 → 不调 LLM，直接全部/单库返回（零成本路径）
  - ≥2 个库 → LLM 选库（返回选中的 kb_id 列表），按选择过滤
  - LLM 不可用/失败 → 兜底全库检索（可用性优先，不因路由故障丢检索）
- schema 驱动：tools 参数从 KB 元数据生成（Dify FunctionCall 选库同型）
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.knowledge.multi_kb_router import MultiKBRouter, kb_catalog_tool


def _kb(kb_id, name, description, hits=None):
    kb = MagicMock()
    kb.kb_id = kb_id
    kb.name = name
    kb.description = description
    kb.search = AsyncMock(return_value={"success": True, "results": hits or [{"text": f"hit-{kb_id}"}]})
    return kb


class TestCatalogSchema:
    def test_tool_schema_from_kb_metadata(self):
        kbs = [
            _kb("kb1", "产品手册", "产品功能说明"),
            _kb("kb2", "API 文档", "接口说明"),
        ]
        tool = kb_catalog_tool(kbs)
        assert tool["name"] == "select_knowledge_bases"
        props = tool["parameters"]["properties"]
        assert set(props["kb_ids"]["items"]["enum"]) == {"kb1", "kb2"}
        # 库元数据在工具级 description（OpenAI function 规范位置）供模型选择
        assert "产品手册" in tool["description"]


class TestRouting:
    @pytest.mark.asyncio
    async def test_single_kb_skips_llm(self):
        """0/1 个库零成本直通（不调 LLM）"""
        router = MultiKBRouter(llm_call=AsyncMock())
        selected = await router.route("q", [_kb("kb1", "a", "b")])
        assert [k.kb_id for k in selected] == ["kb1"]
        router._llm_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_kb_llm_selects_subset(self):
        """≥2 库 → LLM FunctionCall 选库，仅检索被选中的库"""
        kbs = [_kb("kb1", "产品手册", "产品"), _kb("kb2", "API 文档", "接口"), _kb("kb3", "闲聊库", "杂")]
        router = MultiKBRouter(llm_call=AsyncMock(return_value={"kb_ids": ["kb2"]}))
        selected = await router.route("Python SDK 怎么调", kbs)
        assert [k.kb_id for k in selected] == ["kb2"]
        router._llm_call.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_all(self):
        """LLM 不可用/异常 → 兜底全库（可用性优先）"""
        kbs = [_kb("kb1", "a", "a"), _kb("kb2", "b", "b")]
        router = MultiKBRouter(llm_call=AsyncMock(side_effect=RuntimeError("no llm")))
        selected = await router.route("q", kbs)
        assert [k.kb_id for k in selected] == ["kb1", "kb2"]

    @pytest.mark.asyncio
    async def test_llm_invalid_selection_ignored(self):
        """LLM 返回未知 kb_id → 过滤掉幻觉 id，有效选择仍生效"""
        kbs = [_kb("kb1", "a", "a"), _kb("kb2", "b", "b")]
        router = MultiKBRouter(llm_call=AsyncMock(return_value={"kb_ids": ["kb2", "kb_hallucinated"]}))
        selected = await router.route("q", kbs)
        assert [k.kb_id for k in selected] == ["kb2"]

    @pytest.mark.asyncio
    async def test_empty_selection_returns_all(self):
        """LLM 返回空选择 → 兜底全库（拒绝空结果检索）"""
        kbs = [_kb("kb1", "a", "a"), _kb("kb2", "b", "b")]
        router = MultiKBRouter(llm_call=AsyncMock(return_value={"kb_ids": []}))
        selected = await router.route("q", kbs)
        assert [k.kb_id for k in selected] == ["kb1", "kb2"]


class TestSearchAcross:
    @pytest.mark.asyncio
    async def test_search_fans_out_and_merges(self):
        """route 后逐库检索并合并结果（带 kb_id 溯源）"""
        kbs = [_kb("kb1", "a", "a", [{"text": "r1"}]), _kb("kb2", "b", "b", [{"text": "r2"}])]
        router = MultiKBRouter(llm_call=AsyncMock(return_value={"kb_ids": ["kb1", "kb2"]}))
        merged = await router.search("q", kbs, limit=5)
        texts = [r["text"] for r in merged["results"]]
        assert texts == ["r1", "r2"]
        assert merged["results"][0]["kb_id"] == "kb1"
        kbs[0].search.assert_awaited_once()

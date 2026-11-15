# -*- coding: utf-8 -*-
"""MCP 工具面 curated 守卫（P2-1）。

- 广告出的工具名与 curated 名册**集合相等**——新工具注册而未登记 curated
  即红（catch-all exclude 语义：模型面不因顺手注册而静默变宽）；
- curated 每项都有「何时该用」的行为指引（prompt 语言，非空且非复述名字）；
- 每个广告工具的 docstring 非空（描述是 prompt 的一部分）。
"""

from __future__ import annotations

import asyncio

from neurova.knowledge.ontology.mcp_surface import CURATED_TOOLS, curatedNames
from neurova.mcp_ontology_server import create_ontology_mcp_server


def _advertisedTools():
    server = create_ontology_mcp_server()
    return asyncio.run(server.list_tools())


class TestMcpCuratedSurface:
    def testAdvertisedToolsExactlyMatchCuratedAllowlist(self):
        advertised = {t.name for t in _advertisedTools()}
        curated = curatedNames()
        assert advertised == curated, (
            "MCP 工具面漂移：多出 %s，缺 %s——新工具必须先登记 "
            "mcp_surface.CURATED_TOOLS 再暴露给模型" % (
                sorted(advertised - curated), sorted(curated - advertised)))

    def testCuratedEntriesCarryWhenToUseGuidance(self):
        for entry in CURATED_TOOLS:
            guidance = str(entry.get("when_to_use") or "").strip()
            assert len(guidance) >= 12, "curated 条目 %s 缺 when_to_use 指引" % entry
            assert guidance != entry["name"], "when_to_use 不得只是复述工具名"

    def testAdvertisedDescriptionsAreNonEmpty(self):
        for tool in _advertisedTools():
            assert str(tool.description or "").strip(), \
                "工具 %s 的 docstring 为空——工具描述是 prompt 的一部分" % tool.name

    def testCuratedHasNoPhantomTool(self):
        """名册里的名字必须真实注册（防 curated 侧单向漂移）。"""
        advertised = {t.name for t in _advertisedTools()}
        phantom = curatedNames() - advertised
        assert not phantom, "curated 名册含未注册工具: %s" % sorted(phantom)

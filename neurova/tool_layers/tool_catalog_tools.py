# -*- coding: utf-8 -*-
"""tool_catalog_search / tool_doc 工具族——从 neurova.tool_executor 拆出。

数据单源=neurova.tools.catalog（builtin_tools 声明位投影）；本处理器只过滤、
有界输出、返回单工具档案，不定义任何工具。`_builtin_dispatch` 目标
`_execute_tool_catalog_search` / `_execute_tool_doc` 不变。不顶层 import
`neurova.tool_executor`。
"""
from typing import Dict

__all__ = ["ToolCatalogToolsMixin"]


class ToolCatalogToolsMixin:
    """tool_catalog_search + tool_doc built-ins."""

    async def _execute_tool_catalog_search(self, params: Dict) -> Dict:
        """T1 工具自发现目录：按关键字/标记检索内置工具（只读投影）。

        数据单源=neurova.tools.catalog（builtin_tools 声明位投影），本处理器
        只做过滤与有界输出，不定义任何工具。空命中如实空表。
        """
        from neurova.tools.catalog import all_tool_defs

        keyword = str(params.get("keyword") or "").strip().lower()
        tag = str(params.get("tag") or "").strip().lower()
        if tag and tag not in ("read_only", "external_write", "main_only"):
            return {
                "success": False,
                "error": f"非法 tag: {tag}（可选 read_only / external_write / main_only）",
            }
        try:
            limit = min(100, max(1, int(params.get("limit") or 20)))
        except (TypeError, ValueError):
            limit = 20

        matched = []
        for defn in all_tool_defs():
            if keyword and (
                keyword not in defn.name.lower()
                and keyword not in defn.description.lower()
            ):
                continue
            if tag == "read_only" and not defn.read_only:
                continue
            if tag == "external_write" and not defn.external_write:
                continue
            if tag == "main_only" and defn.agent_scope != "main_only":
                continue
            matched.append(defn)

        tools = [
            {
                "name": defn.name,
                "description": defn.description[:200],
                "read_only": defn.read_only,
                "external_write": defn.external_write,
                "agent_scope": defn.agent_scope,
                "param_count": len(defn.args_schema.get("properties") or {}),
            }
            for defn in matched[:limit]
        ]
        return {"success": True, "tools": tools, "count": len(tools), "total": len(matched)}

    async def _execute_tool_doc(self, params: Dict) -> Dict:
        """T1 工具文档：单工具全量档案（描述+参数 schema+能力声明+使用范围）。

        未知名走结构化 tool_not_found（不抛裸异常），并指引回目录检索。
        """
        from neurova.tools.catalog import get_tool_def

        tool_name = str(params.get("tool_name") or "").strip()
        if not tool_name:
            return {"success": False, "error": "缺少 tool_name"}
        defn = get_tool_def(tool_name)
        if defn is None:
            return {
                "success": False,
                "error": "tool_not_found",
                "tool_name": tool_name,
                "hint": "用 tool_catalog_search 检索可用工具",
            }
        return {
            "success": True,
            "tool": {
                "name": defn.name,
                "description": defn.description,
                "args_schema": defn.args_schema,
                "read_only": defn.read_only,
                "external_write": defn.external_write,
                "agent_scope": defn.agent_scope,
            },
        }

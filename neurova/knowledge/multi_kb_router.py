"""多知识库路由（P1-4 — Dify `multi_dataset_function_call_router` 对标）。

多库场景「先选库再检索」：LLM FunctionCall 按库元数据（name/description）
选择目标库，再逐库检索合并。检索策略（semantic/hybrid/...）与选库是
分开的两层（P0-3 已落 RetrievalMethod 层），本模块只管「选库」。

可用性优先：LLM 不可用/选库失败/选择为空 → 兜底全库检索，路由故障
绝不丢检索能力（fail-open 到全库，隔离仍由各库自身可见性保证）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_SELECTOR_TOOL_NAME = "select_knowledge_bases"


def kb_catalog_tool(kbs: List[Any]) -> Dict[str, Any]:
    """库清单 → FunctionCall 选库工具 schema（enum 限定可选集，description
    携带各库说明供模型判断）"""
    catalog = "\n".join(
        f"- {getattr(kb, 'kb_id', '')}: {getattr(kb, 'name', '')} — {getattr(kb, 'description', '')}"
        for kb in kbs
    )
    return {
        "name": _SELECTOR_TOOL_NAME,
        "description": f"根据用户查询选择最相关的知识库（可多选）。可选库：\n{catalog}",
        "parameters": {
            "type": "object",
            "properties": {
                "kb_ids": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [str(getattr(kb, "kb_id", "")) for kb in kbs],
                    },
                    "description": "与查询相关的知识库 id 列表",
                },
            },
            "required": ["kb_ids"],
        },
    }


class MultiKBRouter:
    """LLM FunctionCall 选库路由器（llm_call 注入式——测试用桩，生产接
    multi_model_client 的 tool_calls 形态）。"""

    def __init__(self, llm_call=None):
        # llm_call(query, tool_schema) -> {"kb_ids": [...]}（或抛异常）
        self._llm_call = llm_call

    async def route(self, query: str, kbs: List[Any]) -> List[Any]:
        """选库：0/1 库直通；≥2 库 LLM 选择（失败/空选 → 兜底全库）"""
        if len(kbs) <= 1:
            return list(kbs)

        by_id = {str(getattr(kb, "kb_id", "")): kb for kb in kbs}
        try:
            if self._llm_call is None:
                raise RuntimeError("llm_call 未装配")
            outcome = await self._llm_call(query, kb_catalog_tool(kbs))
            selected_ids = [
                str(x) for x in (outcome or {}).get("kb_ids") or []
            ]
        except Exception as e:  # noqa: BLE001 — 路由故障兜底全库
            logger.warning("多库路由选库失败（兜底全库）: %s", e)
            return list(kbs)

        # 幻觉 id 过滤；空有效选择 → 兜底全库
        valid = [by_id[i] for i in selected_ids if i in by_id]
        return valid or list(kbs)

    async def search(
        self,
        query: str,
        kbs: List[Any],
        limit: int = 5,
        llm_call: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """先选库后检索，结果合并并附 kb_id 溯源（Dify 多库检索信封）"""
        chosen = await self.route(query, kbs)
        results: List[Dict[str, Any]] = []
        for kb in chosen:
            kb_id = str(getattr(kb, "kb_id", ""))
            try:
                outcome = await kb.search(query, limit=limit)
                hits = (outcome or {}).get("results") or []
            except Exception as e:  # noqa: BLE001 — 单库故障不影响其余库
                logger.warning("知识库 %s 检索失败: %s", kb_id, e)
                continue
            for hit in hits:
                if isinstance(hit, dict):
                    hit.setdefault("kb_id", kb_id)
                    results.append(hit)
                else:
                    results.append({"text": str(hit), "kb_id": kb_id})
        return {
            "query": query,
            "selected_kb_ids": [str(getattr(kb, "kb_id", "")) for kb in chosen],
            "results": results,
            "total": len(results),
        }


__all__ = ["MultiKBRouter", "kb_catalog_tool"]

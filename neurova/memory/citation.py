# -*- coding: utf-8 -*-
"""记忆 citation 溯源标记（P2-2 遗留收口，Codex <memory_citation> 对齐）。

- 检索产物注入 prompt 时携带溯源标记：模型可引用/归因记忆条目，
  后处理可从回复中抽取被引用的 memory_id 做审计与温度联动
- 无标识字段（memory_id/id/knowledge_id 均缺）→ 不加标记（格式不变）
- marker 是可选后缀：既有 "[记忆] content" 格式与召回去重 hash（按 content
  计算）均不受影响
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

_CITATION_RE = re.compile(r'<memory_citation\s+([^/>]*?)/>')


def render_citation(memory: Any) -> str:
    """从记忆条目渲染 citation 后缀（无标识返回空串）。"""
    if not isinstance(memory, dict):
        return ""
    mid = memory.get("memory_id") or memory.get("id") or memory.get("knowledge_id")
    if not mid:
        return ""
    parts = [f'memory_id="{mid}"']
    for key in ("category", "score", "temperature"):
        value = memory.get(key)
        if value is not None:
            parts.append(f'{key}="{value}"')
    return " <memory_citation " + " ".join(parts) + "/>"


def render_memory_line(memory: Any, prefix: str = "[记忆]") -> str:
    """组装注入行：'[前缀] content' + citation 后缀（无标识格式与旧版一致）。"""
    content = memory.get("content", str(memory)) if isinstance(memory, dict) else str(memory)
    return f"{prefix} {content}{render_citation(memory)}"


def extract_citations(text: str) -> List[Dict[str, str]]:
    """从模型回复抽取被引用的记忆标识（审计/温度联动用）。"""
    out: List[Dict[str, str]] = []
    for m in _CITATION_RE.finditer(str(text or "")):
        attrs: Dict[str, str] = {}
        for pair in m.group(1).split():
            if "=" in pair:
                k, _, v = pair.partition("=")
                attrs[k] = v.strip('"')
        if attrs.get("memory_id"):
            out.append(attrs)
    return out

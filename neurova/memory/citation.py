# -*- coding: utf-8 -*-
"""记忆 citation 溯源标记。

- 检索产物注入 prompt 时携带溯源标记：模型可引用/归因记忆条目，
  后处理可从回复中抽取被引用的 memory_id 做审计与温度联动
- 无标识字段（memory_id/id/knowledge_id 均缺）→ 不加标记（格式不变）
- marker 是可选后缀：既有 "[记忆] content" 格式与召回去重 hash（按 content
  计算）均不受影响

P0#5两件核心机制：
1. **句柄压缩**：CitationRegistry 本轮作用域把长 UUID 换成 m1/k1 短句柄
   （省 token；长 UUID 被模型改写损坏的概率也归零）。记忆 m 前缀、
   知识条目 k 前缀（P0#4 归一化载荷带 knowledge_id）。
2. **资格分离**：只有本轮注册过（=本轮检索证据）的句柄才允许成为引用。
   抽取/解码时未注册句柄、本轮外 memory_id 的回放引用一律丢弃——
   模型从历史消息里复制上一轮的 citation 不再被当作真实溯源。
registry=None 的一切调用保持旧行为（向后兼容）。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_CITATION_RE = re.compile(r'<memory_citation\s+([^/>]*?)/>')
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def _identify(memory: Any) -> Optional[Tuple[str, str]]:
    """(kind, real_id)：knowledge_id → k；memory_id/id → m；无标识 → None。"""
    if not isinstance(memory, dict):
        return None
    kid = memory.get("knowledge_id")
    if kid:
        return ("k", str(kid))
    mid = memory.get("memory_id") or memory.get("id")
    if mid:
        return ("m", str(mid))
    return None


class CitationRegistry:
    """本轮检索证据的句柄 ↔ 真实 id 双向表（管线每轮新建，非线程共享）。"""

    def __init__(self) -> None:
        self._id_to_handle: Dict[Tuple[str, str], str] = {}
        self._handle_to_id: Dict[str, str] = {}
        self._ids: set = set()
        self._counters: Dict[str, int] = {"m": 0, "k": 0}

    def register(self, memory: Any) -> Optional[str]:
        """注册条目并返回句柄；无标识返回 None；同 id 幂等复用。"""
        ident = _identify(memory)
        if ident is None:
            return None
        if ident in self._id_to_handle:
            return self._id_to_handle[ident]
        kind, real = ident
        self._counters[kind] += 1
        handle = f"{kind}{self._counters[kind]}"
        self._id_to_handle[ident] = handle
        self._handle_to_id[handle] = real
        self._ids.add(real)
        return handle

    def handle_for(self, memory: Any) -> Optional[str]:
        ident = _identify(memory)
        return self._id_to_handle.get(ident) if ident else None

    def resolve(self, handle: str) -> Optional[str]:
        return self._handle_to_id.get(str(handle))

    def is_empty(self) -> bool:
        """本轮没有任何注册句柄（流式缓冲门控：无句柄=无需缓冲，逐字节旧行为）。"""
        return not self._handle_to_id

    def recognizes_id(self, real_id: str) -> bool:
        """legacy 全 id 引用的资格判定（本轮注册过才算）。"""
        return str(real_id) in self._ids


def render_citation(memory: Any, registry: Optional[CitationRegistry] = None) -> str:
    """渲染 citation 后缀：registry 在场用句柄 ref="m1"，否则旧全 id 格式。"""
    if registry is not None:
        handle = registry.register(memory)  # 注入即本轮证据，幂等自注册
        if not handle:
            return ""
        return f' <memory_citation ref="{handle}"/>'
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


def render_memory_line(
    memory: Any, prefix: str = "[记忆]", registry: Optional[CitationRegistry] = None
) -> str:
    """组装注入行：'[前缀] content' + citation 后缀（无标识格式与旧版一致）。"""
    content = memory.get("content", str(memory)) if isinstance(memory, dict) else str(memory)
    return f"{prefix} {content}{render_citation(memory, registry)}"


def _parse_attrs(chunk: str) -> Dict[str, str]:
    return {k: v for k, v in _ATTR_RE.findall(chunk)}


def extract_citations(
    text: str, registry: Optional[CitationRegistry] = None
) -> List[Dict[str, str]]:
    """从模型回复抽取被引用的记忆标识（审计/温度联动用）。

    registry 在场执行资格分离：句柄解析回真实 id；本轮未注册的句柄与
    本轮外的 memory_id（历史回放/模型幻觉）一律丢弃。
    """
    out: List[Dict[str, str]] = []
    for m in _CITATION_RE.finditer(str(text or "")):
        attrs = _parse_attrs(m.group(1))
        if registry is not None:
            ref = attrs.get("ref")
            if ref:
                real = registry.resolve(ref)
                if real is None:
                    continue  # 本轮无此证据 → 引用不成立
                entry = {k: v for k, v in attrs.items() if k != "ref"}
                entry["memory_id"] = real
                out.append(entry)
                continue
            mid = attrs.get("memory_id")
            if mid and not registry.recognizes_id(mid):
                continue  # 上一轮残留引用：丢弃
        if attrs.get("memory_id"):
            out.append(attrs)
    return out


def decode_citation_handles(
    text: str, registry: Optional[CitationRegistry]
) -> str:
    """落库/展示前把句柄引用还原为真实 memory_id；无资格标记整体删除。

    流式出口本轮维持句柄原文（报告 §7 #5：SSE 逐字缓冲后置），此函数覆盖
    持久化与会话重放路径——下一轮窗口里出现的只会是真实 id 的 legacy 格式。
    """
    if registry is None or not text or "<memory_citation" not in text:
        return str(text or "")

    def _repl(m: "re.Match[str]") -> str:
        attrs = _parse_attrs(m.group(1))
        ref = attrs.get("ref")
        if not ref:
            return m.group(0)  # legacy 全 id 格式原样
        real = registry.resolve(ref)
        if real is None:
            return ""  # 伪造/越权引用：整个标记删除
        rest = " ".join(f'{k}="{v}"' for k, v in attrs.items() if k != "ref")
        marker_attrs = f'memory_id="{real}"' + (f" {rest}" if rest else "")
        return f"<memory_citation {marker_attrs}/>"

    return _CITATION_RE.sub(_repl, text)


_MARKER = "<memory_citation"


class StreamCitationBuffer:
    """④ 流式 citation 后缀缓冲。

    SSE 分片会把 `<memory_citation .../>` 切断——裸半截 tag 会闪进用户可见流。
    feed() 只返回安全前缀（完整标记按 registry 解码/丢弃，与持久化解码同口径），
    尾部若疑似标记开头（严格前缀 / 开而未闭的 tag）挂起等下一片；flush() 结清。
    registry=None 时纯透传（legacy 全 id 格式行为不变）。
    """

    def __init__(self, registry: Optional[CitationRegistry] = None) -> None:
        self._registry = registry
        self._held = ""

    def feed(self, text: str) -> str:
        if not text:
            return ""
        buf = self._held + str(text)
        decoded = (
            decode_citation_handles(buf, self._registry)
            if self._registry is not None
            else buf
        )
        hold = self._hold_len(decoded)
        self._held = decoded[len(decoded) - hold:] if hold else ""
        return decoded[: len(decoded) - hold] if hold else decoded

    @staticmethod
    def _hold_len(s: str) -> int:
        # 尾部是标记的严格前缀（下一分片可能补全成标记）
        for k in range(min(len(s), len(_MARKER) - 1), 0, -1):
            if _MARKER.startswith(s[-k:]):
                return k
        # 尾部含已开未闭的标记（decode 只处理闭合形态）
        start = s.rfind(_MARKER)
        if start != -1 and "/>" not in s[start:]:
            return len(s) - start
        return 0

    def flush(self) -> str:
        tail, self._held = self._held, ""
        # 已出现完整 `<memory_citation` 却未闭合 → 丢弃半截 tag（非用户内容）；
        # 仅是严格前缀（<m/<mem…）→ 可能是真文本，结清时原样吐出不丢字。
        if tail.startswith(_MARKER):
            return ""
        return tail

# -*- coding: utf-8 -*-
"""渠道出站消息分片器（统一防截断，对齐各平台官方单条长度上限）。

背景：各渠道单条消息有长度上限（Telegram 4096、QQ 群/C2C ~4096、企微 text 2048、
钉钉/飞书亦有），此前全渠道单条整发、发送失败被吞 → 长回复"截断终止/整条消失"。
本模块在 manager.send_message 统一按渠道上限分片、逐条发送、失败告警不静默。
"""

from __future__ import annotations

from typing import List

# 各渠道单条安全上限（保守值，留出格式余量；以各平台官方文档为准）
CHANNEL_TEXT_LIMITS = {
    "telegram": 4000,
    "qq": 4000,
    "qqbot": 4000,
    "wecom": 1800,       # 企微 text 2048 字节，中文按字符保守
    "dingtalk": 3500,
    "feishu": 4000,
    "wechat": 4000,
    "console": 8000,
}
DEFAULT_TEXT_LIMIT = 4000


def text_limit_for(channel_type: str) -> int:
    return CHANNEL_TEXT_LIMITS.get(channel_type, DEFAULT_TEXT_LIMIT)


def split_message(text: str, limit: int) -> List[str]:
    """把长文本按段落/句子边界切成 <=limit 的多段；短文本原样单段。

    优先级：空行段 → 句子边界 → 硬切。保证不丢字符、不产生空段。
    """
    if not text:
        return [text]
    if limit <= 0 or len(text) <= limit:
        return [text]

    chunks: List[str] = []
    buf = ""
    for unit in _split_units(text):
        # 单元本身超长 → 先冲缓冲，再硬切
        while len(unit) > limit:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(unit[:limit])
            unit = unit[limit:]
        if not unit:
            continue
        joined = unit if not buf else buf + "\n\n" + unit
        if len(joined) <= limit:
            buf = joined
        else:
            if buf:
                chunks.append(buf)
            buf = unit
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c]


def _split_units(text: str) -> List[str]:
    """按空行分段，段内再按句子边界细分，保证单元素尽量 <= 常见上限。"""
    paras = text.split("\n\n")
    units: List[str] = []
    for p in paras:
        if len(p) <= 1000:
            units.append(p)
            continue
        units.extend(_split_sentences(p))
    return units


_SENT_END = "。！？!?；;\n"


def _split_sentences(s: str) -> List[str]:
    parts: List[str] = []
    cur = ""
    for ch in s:
        cur += ch
        if ch in _SENT_END and len(cur) >= 300:
            parts.append(cur)
            cur = ""
    if cur:
        parts.append(cur)
    return parts or [s]

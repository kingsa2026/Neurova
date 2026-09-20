"""内容身份归一化 —— 写入侧内容门的唯一事实源。

用途：给"同一件事的又一次表述"算出一个确定性键，让记忆/经验写入面能判定
"这条是不是已经有了"。EKB `add_experience_record` 与 `MemoryManager.remember`
都走这里，两处的折叠口径必须一致，否则同一个缺陷会在另一面复活。

折叠口径刻意保守：NFKC 全半角 + 小写 + 去说话人前缀 + 剔除标点/空白。
键相同 ≈ "同一事实的新说法"；语义级判断（话题归并/矛盾检测）不做——那是
LLM 的职责，写路径保持零模型调用、确定性可复现。

空键语义：归一后为空（纯空白/纯标点/无字符串叶子）表示**没有内容身份**，
调用方必须跳过去重而不是把它们并进同一个桶——否则所有空写入互相吞没。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, List

_SPEAKER_PREFIXES = (
    "助手：", "助手:", "用户：", "用户:", "assistant:", "user:",
    "助手", "用户",
)


def normalized_key(content: Any) -> str:
    """确定性归一化键：NFKC + 小写 + 去说话人前缀 + 剔除标点/空白。"""
    text = unicodedata.normalize("NFKC", str(content or "")).strip().casefold()
    for p in _SPEAKER_PREFIXES:
        if text.startswith(p):
            text = text[len(p):].strip()
            break
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def _string_leaves(payload: Any, out: List[str]) -> None:
    if isinstance(payload, str):
        if payload:
            out.append(payload)
    elif isinstance(payload, dict):
        for value in payload.values():
            _string_leaves(value, out)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            _string_leaves(value, out)
    # 其余标量（int/float/bool/None）不携带文本身份，不参与建键


def normalized_payload_key(payload: Any) -> str:
    """结构化载荷的内容身份：收集全部字符串叶子（排序后拼接）再归一化。

    只取字符串叶子、丢弃字段名，让 `{"user_input": "你好"}` 与
    `{"user_input": " 你好！"}` 同键；标量元数据（页码、计数）不建身份。
    """
    leaves: List[str] = []
    _string_leaves(payload, leaves)
    return normalized_key("".join(sorted(leaves)))

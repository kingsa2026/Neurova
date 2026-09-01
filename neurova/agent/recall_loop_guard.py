# -*- coding: utf-8 -*-
"""
召回循环防护（P1-a，对标 QP beta.5 RecallLoopGuard）

问题：模型可在同一轮内反复调用 recall_history 同查询——每次拿到相同
结果（甚至相同空结果），陷入无效重试循环并浪费 token。

语义（双指纹）：
- 请求指纹 = sha256(query|limit)
- 结果快照指纹 = 召回条目内容的 sha256
- 判定：请求指纹首次出现 → 放行；复现时**结果快照相同** → DENY
  （数据没变，重查无意义）；**结果快照漂移** → 放行并更新（台账确有更新）
- 轮次边界：reset() 由 chat_pipeline Step0 调用（一次对话一轮）
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Tuple


def compute_digest(recalled_items: List[Dict]) -> str:
    """结果快照指纹：条目 content+turn_id 的稳定哈希（顺序敏感）。"""
    canonical = "\x1f".join(
        f"{item.get('turn_id', '')}\x1e{item.get('content', '')}"
        for item in recalled_items or []
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class RecallLoopGuard:
    """同轮召回死循环防护（进程内状态，agent 级单实例）。"""

    def __init__(self, max_tracked: int = 64):
        self._seen: Dict[str, str] = {}  # 请求指纹 -> 结果快照指纹
        self._max_tracked = max_tracked

    def record_and_check(self, query: Optional[str], limit: int, digest: str) -> Tuple[bool, Optional[str]]:
        """记录本次召回并判定是否放行。

        Returns:
            (allowed, deny_reason)
        """
        fp = hashlib.sha256(f"{query or ''}|{limit}".encode("utf-8")).hexdigest()[:16]

        prev = self._seen.get(fp)
        if prev is not None:
            if prev == digest:
                return (
                    False,
                    f"该查询本轮已召回过且结果未变化（快照 {digest}）——"
                    "请改写查询、提高 limit、或继续其他工作；重复召回只会得到相同结果",
                )
            # 结果漂移：台账确有更新，放行并刷新快照
            self._seen[fp] = digest
            return True, None

        # 新查询：LRU 上限保护（长轮次防dict膨胀）
        if len(self._seen) >= self._max_tracked:
            oldest = next(iter(self._seen))
            self._seen.pop(oldest, None)
        self._seen[fp] = digest
        return True, None

    def reset(self) -> None:
        """新轮次：清空全部指纹状态。"""
        self._seen.clear()

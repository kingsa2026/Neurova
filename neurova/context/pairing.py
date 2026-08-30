"""
上下文视图配对完整性校验（P1-1 期①）

活水上下文池的视图层（Drawer 选取结果）按相关性/预算整条选取，可能出现
配对残缺：TOOL_CALL chunk 被选入视图，而其所属轮次（pairs_with 指向的
turn/conversation chunk）未被选入——残缺视图会让 LLM 看到"无上下文的
工具结果"（孤儿），诱发幻觉或协议错误。

本模块提供纯函数校验：
- validate_pairing(chunks) → PairingReport(kept, orphans)
  孤儿判定：source=TOOL_CALL 且 metadata.pairs_with 指向的 turn_id 不在
  视图内 → 移出 kept、进入 orphans（留在池中，不破坏归档无损语义）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

from neurova.context.pool_models import ContextInput, ContextSource


@dataclass
class PairingReport:
    """配对校验结果：kept 为过滤后的视图（保持原顺序），orphans 为被剔除的孤儿。"""

    kept: List[ContextInput] = field(default_factory=list)
    orphans: List[ContextInput] = field(default_factory=list)

    @property
    def orphan_count(self) -> int:
        return len(self.orphans)


def _pairs_with_target(chunk: ContextInput) -> Any:
    metadata = chunk.metadata or {}
    return metadata.get("pairs_with")


def _collected_turn_ids(chunks: List[ContextInput]) -> set:
    """视图内所有可被配对的 id：turn_id 与 chunk 自身 hash（pairs_with 的两种合法目标）。"""
    ids = set()
    for c in chunks:
        metadata = c.metadata or {}
        if metadata.get("turn_id"):
            ids.add(metadata["turn_id"])
        if c.hash:
            ids.add(c.hash)
    return ids


def validate_pairing(chunks: List[ContextInput]) -> PairingReport:
    """校验视图配对完整性：剔除孤儿 TOOL_CALL chunk。

    规则：
    - 仅 TOOL_CALL 源参与孤儿判定（conversation 等源天然自洽）
    - TOOL_CALL 的 metadata.pairs_with 指向 turn_id 或目标 chunk 的 hash；
      指向目标不在视图内 → 孤儿
    - 未设置 pairs_with 的 TOOL_CALL 视为自包含（如工具主动记录），不剔除
    - 非视图成员的引用关系不校验（池内归档完整性由归档层保证）
    """
    turn_ids = _collected_turn_ids(chunks)
    kept: List[ContextInput] = []
    orphans: List[ContextInput] = []

    for chunk in chunks:
        if chunk.source == ContextSource.TOOL_CALL:
            target = _pairs_with_target(chunk)
            if target is not None and target not in turn_ids:
                orphans.append(chunk)
                continue
        kept.append(chunk)

    return PairingReport(kept=kept, orphans=orphans)

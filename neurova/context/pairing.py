"""
上下文视图配对完整性校验与残留清扫（P1-1 期① / P2-9）

活水上下文池的视图层（Drawer 选取结果）按相关性/预算整条选取，可能出现
配对残缺：TOOL_CALL chunk 被选入视图，而其所属轮次（pairs_with 指向的
turn/conversation chunk）未被选入——残缺视图会让 LLM 看到"无上下文的
工具结果"（孤儿），诱发幻觉或协议错误。

本模块是视图出口洁净度的**判定单源**（教义第 6 条），提供纯函数：
- validate_pairing(chunks) → PairingReport(kept, orphans)
  第一遍·孤儿判定：source=TOOL_CALL 且 metadata.pairs_with 指向的 turn_id
  不在视图内 → 移出 kept、进入 orphans（留在池中，不破坏归档无损语义）。
- sweepResidues(chunks) → PairingReport(kept, orphans, residues)
  两遍扫描：第一遍复用 validate_pairing 剔孤儿；第二遍对 kept 再剔
  "空壳 assistant 残留"（content 空/白 且 无 tool_calls 且 无
  tool_call_id——中断/失败轮的占位残留，发给模型是纯噪声）。
  被剔者统一进 orphans（调用方读数不细分），residues 单列空壳供诊断。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from neurova.context.pool_models import ContextInput, ContextSource


@dataclass
class PairingReport:
    """配对校验结果：kept 为过滤后的视图（保持原顺序），orphans 为被剔除的孤儿。

    P2-9 起 orphans 含两遍扫描的全部被剔者（孤儿 TOOL_CALL + 空壳 assistant）；
    residues 单列其中的空壳残留，供调用方按需细分（缺省空表，既有构造点不受影响）。
    """

    kept: List[ContextInput] = field(default_factory=list)
    orphans: List[ContextInput] = field(default_factory=list)
    residues: List[ContextInput] = field(default_factory=list)

    @property
    def orphan_count(self) -> int:
        return len(self.orphans)


def _chunkMetadata(chunk: Any) -> Dict[str, Any]:
    """鸭子取 metadata：ContextInput 读属性，dict 读键（同 validate_pairing 的取法）。"""
    if isinstance(chunk, dict):
        metadata = chunk.get("metadata")
        return metadata if isinstance(metadata, dict) else {}
    return getattr(chunk, "metadata", None) or {}


def _chunkField(chunk: Any, name: str, default: Any = None) -> Any:
    """鸭子取顶层字段：ContextInput 读属性，dict 消息读键。"""
    if isinstance(chunk, dict):
        return chunk.get(name, default)
    return getattr(chunk, name, default)


def _pairs_with_target(chunk: ContextInput) -> Any:
    metadata = _chunkMetadata(chunk)
    return metadata.get("pairs_with")


def _collected_turn_ids(chunks: List[ContextInput]) -> set:
    """视图内所有可被配对的 id：turn_id 与 chunk 自身 hash（pairs_with 的两种合法目标）。"""
    ids = set()
    for c in chunks:
        metadata = _chunkMetadata(c)
        if metadata.get("turn_id"):
            ids.add(metadata["turn_id"])
        chunkHash = _chunkField(c, "hash")
        if chunkHash:
            ids.add(chunkHash)
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
        # 鸭子取 source（ContextInput 为枚举，dict 消息可能给枚举或其 value）
        source = _chunkField(chunk, "source")
        sourceValue = getattr(source, "value", source)
        if sourceValue == ContextSource.TOOL_CALL.value:
            target = _pairs_with_target(chunk)
            if target is not None and target not in turn_ids:
                orphans.append(chunk)
                continue
        kept.append(chunk)

    return PairingReport(kept=kept, orphans=orphans)


def isEmptyAssistantResidue(chunk: Any) -> bool:
    """空壳 assistant 残留判定（P2-9 第二遍）。

    空壳形态：role=assistant 且 content 去空白后为空 且 无 tool_calls 且
    无 tool_call_id——中断/失败轮的占位残留，发给模型是纯噪声。

    鸭子类型：ContextInput（role 等在 metadata）与 dict 消息（role 等在
    顶层字段）都支持。source=TOOL_CALL 的条目不归本判定管（那是第一遍
    validate_pairing 孤儿扫描的事）。
    """
    source = _chunkField(chunk, "source")
    sourceValue = getattr(source, "value", source)
    if sourceValue == ContextSource.TOOL_CALL.value:
        return False

    metadata = _chunkMetadata(chunk)
    role = metadata.get("role") or _chunkField(chunk, "role")
    if role != "assistant":
        return False

    content = _chunkField(chunk, "content")
    if str(content or "").strip():
        return False

    toolCalls = _chunkField(chunk, "tool_calls") or metadata.get("tool_calls")
    if toolCalls:
        return False

    toolCallId = _chunkField(chunk, "tool_call_id") or metadata.get("tool_call_id")
    if toolCallId:
        return False

    return True


def sweepResidues(chunks: List[ContextInput]) -> PairingReport:
    """残留清理两遍扫描（P2-9）：第一遍孤儿 TOOL_CALL，第二遍空壳 assistant。

    复用 validate_pairing 做第一遍（孤儿判定单源，不复制其逻辑）；第二遍
    对第一遍的 kept 再剔空壳 assistant 残留。返回同一 PairingReport 形态：
    kept=两遍都存活（保持原顺序）；orphans=全部被剔者（孤儿+空壳，调用方
    读数不细分）；residues=其中第二遍剔出的空壳，供诊断细分。
    """
    firstPass = validate_pairing(chunks)
    kept: List[ContextInput] = []
    residues: List[ContextInput] = []
    for chunk in firstPass.kept:
        if isEmptyAssistantResidue(chunk):
            residues.append(chunk)
        else:
            kept.append(chunk)
    return PairingReport(kept=kept, orphans=firstPass.orphans + residues, residues=residues)

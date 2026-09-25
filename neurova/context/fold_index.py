# -*- coding: utf-8 -*-
"""折叠层索引：SUMMARY 层节点的 covers 派生、解析与档号派生（Issue #90 · T-11b）。

## 为什么单独一个模块

T-11a 让折叠**分代**了，但代际栈只活在 `_window_compaction_cache`（进程内易失）
里：池内 `ContextSource.SUMMARY` 节点数实测 **0**。于是工单 §12.1 的
**C4 层即索引**在数据上不成立：

- 没有 `covers`，下钻（T-11d）无从知道一个摘要覆盖了哪些原文条目；
- 没有档号，视图装配器（T-11c）无法按分辨率档装配。

本模块是 covers 的**唯一派生与解析处**——写入侧派一次（`buildCovers`），
读取侧解一次（`parseCovers`）。两处各写一份字段名与区间算法，就是第二份索引
格式（修复教义第 6 条）。

## 引用（covers_ref）为什么必须可解析

索引存在 ≠ 取回的到。层节点的 `covers` 只活在池里，视图里那行摘要是一段纯文本
——模型读到摘要却没有任何确定性寻址手段，只能退回 `recall_history(query=…)` 的
相关性门槛碰运气（工单 §12.5 第 3 条明列为假实现）。

故引用（`covers_ref`）由本模块**单点**派生（`renderCoversRef`）与解析
（`parseCoversRef`），视图只在摘要行尾部内联它的渲染结果。两处各写一遍引用语法，
就是第二份寻址口径 —— 与 `_tool_placeholder` 的 `call=` 指针同纪律：地址由生产
它的那一处给，消费方只解析，不猜。

## 为什么 metadata 存层序而不是档号

工单 §12.4 的原话是"SUMMARY metadata 增 `level` + `covers`"。实现存的键是
`fold_seq`（该次折叠的层序，1 = 该会话的第一次），**档号由 `layerLevel` 派生**：
最新一档恒为 1，越早越大。

理由是档号**随新代产生而整体下移**：把它写进归档实体，每次折叠都要就地改写
已归档节点（与 T-04 "归档实体永不原地改写"的纪律正面冲突），而且改一处必漏
一处。层序是**不可变事实**，档号是它的确定性函数——一份事实，一处派生。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

#: SUMMARY 层节点 metadata 里的两个键。写入与读取都取这里，不各写一份字面串。
COVERS_KEY = "covers"
FOLD_SEQ_KEY = "fold_seq"

#: covers 内的两个子键。
TURN_RANGE_KEY = "turn_range"
HASHES_KEY = "hashes"

#: 无法进索引 / 无法下钻的点名（读数与日志共用同一串，避免两处各写一份措辞）。
REASON_NO_COVERS = "NoCovers"
REASON_NO_FOLD_ORDINAL = "NoFoldOrdinal"
REASON_POOL_ABSENT = "PoolAbsent"
REASON_COVERAGE_GAP = "CoverageGap"
#: 下钻侧的失败点名（与上四条同域，一处定义）。
REASON_REF_UNPARSABLE = "RefUnparsable"
REASON_LAYER_ABSENT = "LayerAbsent"
REASON_SOURCE_MISSING = "SourceMissing"
REASON_SCOPE_FILTERED = "ScopeFiltered"

#: 引用语法：`covers_ref=fold:<层序>@<会话身份>`。档号（level）不入引用——
#: 它随新代产生整体下移（见本模块顶部），写进引用会在下一次折叠后指向别的档。
REF_PREFIX = "covers_ref="
_REF_RE = re.compile(
    r"covers_ref=fold:(?P<seq>\d+)@(?P<session>[^\s\]\[()（），、;；]+)"
)


def renderCoversRef(foldSeq: int, sessionId: Optional[str]) -> str:
    """派生一个层节点的引用串（**唯一**派生处）。

    会话身份取写入那一刻的**同一份**身份（`_advanceFoldGeneration` 的折叠槽键，
    即 T-03b 的身份单源），不在这里另算一次 —— 引用里的会话与索引里的会话若来自
    两份口径，下钻就会在"引用指 A、索引只有 B"之间静默落空。
    """
    return f"{REF_PREFIX}fold:{int(foldSeq)}@{sessionId or ''}"


def parseCoversRef(text: str) -> Optional[Tuple[int, str]]:
    """从任意文本（视图摘要行 / 模型复述的引用）解析出 `(层序, 会话身份)`。

    解析不出返回 None，不猜默认值 —— 调用方据此点名 `RefUnparsable`，
    给个兜底引用只会把"没有引用"伪装成"指向某处"。
    """
    match = _REF_RE.search(str(text or ""))
    if match is None:
        return None
    try:
        foldSeq = int(match.group("seq"))
    except (TypeError, ValueError):
        return None
    if foldSeq <= 0:
        return None
    return foldSeq, match.group("session")


def buildCovers(turnIds: Iterable[str], hashes: Iterable[str]) -> Dict[str, Any]:
    """派生一个层节点的 covers：turn 区间 + 被覆盖条目 hash 列表（唯一派生处）。

    - `turn_range` 取被覆盖轮次 id 的 min/max；轮次 id 形如 `turn_7`，按数值比较，
      非该形态的 id 不计入区间（但条目仍在 hash 列表里，覆盖闭合不受影响）。
    - `hashes` 保序去重：同一条内容在一轮折叠里只算一次。
    """
    ordered: List[str] = []
    seen: set = set()
    for value in hashes or ():
        key = str(value or "")
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)

    numbers: List[int] = []
    for turn in turnIds or ():
        text = str(turn or "")
        if text.startswith("turn_"):
            tail = text[5:]
            if tail.isdigit():
                numbers.append(int(tail))
    turn_range: List[int] = [min(numbers), max(numbers)] if numbers else []
    return {TURN_RANGE_KEY: turn_range, HASHES_KEY: ordered}


def parseCovers(metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """解析一个层节点的 covers；解析不出（缺键 / 形态不对）返回 None。

    不抛异常、不猜默认值：解析失败必须可被计数（`unparsable`），
    给个空 covers 兜底只会把"索引没写"伪装成"索引为空"。
    """
    raw = (metadata or {}).get(COVERS_KEY)
    if not isinstance(raw, dict):
        return None
    hashes = raw.get(HASHES_KEY)
    if not isinstance(hashes, (list, tuple)) or not hashes:
        return None
    turn_range = raw.get(TURN_RANGE_KEY)
    if not isinstance(turn_range, (list, tuple)):
        return None
    parsed_turns: List[int] = []
    for value in turn_range:
        try:
            parsed_turns.append(int(value))
        except (TypeError, ValueError):
            return None
    if len(parsed_turns) != 2 or parsed_turns[0] > parsed_turns[1]:
        return None
    return {
        TURN_RANGE_KEY: parsed_turns,
        HASHES_KEY: [str(h) for h in hashes if h],
    }


def isIndexNode(metadata: Optional[Dict[str, Any]]) -> bool:
    """该 SUMMARY 节点是否**声明**参加层索引（判据 = 带层序键）。

    声明与内容分离：`FOLD_SEQ_KEY` 在场即"我是层节点"（折叠路径写的），
    不在场的是普通摘要（溢出恢复路径 `archive_summary` 写的，用途是"视图可调取"）。
    两者混为一谈会让"解析失败率"把合法的非层摘要也算成失败。

    这条谓词是**召回面与索引面的分工判据的唯一出处**：层节点由确定性索引
    （`summaryLayers()`）寻址，不参加概率性相关性召回——工单 §12.5 第 3 条把
    "下钻靠相关性门槛碰运气"列为假实现。两处各写一遍谓词必然漂移。
    """
    return FOLD_SEQ_KEY in (metadata or {})


def foldSeqOf(metadata: Optional[Dict[str, Any]]) -> Optional[int]:
    """解出层序（不可变事实）；缺失或非正整数返回 None（读数据此点名）。"""
    raw = (metadata or {}).get(FOLD_SEQ_KEY)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def layerLevel(foldSeq: Optional[int], newestSeq: Optional[int]) -> Optional[int]:
    """档号：最新一档恒为 1，越早越大（档号 = 最新层序 - 本节点层序 + 1）。

    层序或最新层序缺失时返回 None —— 派生不出来就如实为空，不猜 1。
    """
    if not foldSeq or not newestSeq or foldSeq > newestSeq:
        return None
    return int(newestSeq) - int(foldSeq) + 1


def newestFoldSeq(rows: Iterable[Tuple[Optional[int], Any]]) -> Optional[int]:
    """索引内最大的层序（档号的派生基准；无层序节点不参与）。"""
    seqs = [seq for seq, _ in rows if seq]
    return max(seqs) if seqs else None

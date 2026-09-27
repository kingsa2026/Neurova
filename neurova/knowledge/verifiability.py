"""逐字可核闸（共享位）：模型说的话，凡引用精确标识符，必须在证据里逐字存在。

为什么要有这一位：本仓对"模型说的话能不能信"曾有两套强度不同的门——摘要走逐字闸
（生成 → 脱敏 → 逐字校验 → 单次 repair → 不过就保留旧摘要），而经验 / 知识 /
教训三条入库口只有分数闸或干脆没有门。偏偏后三条才是会被回灌进后续决策的：
经验进检索排序、知识当事实注入、教训直接拦工具。同一类风险不许有两套门，
而被绕过的那套更弱——所以判定实现收口到这里一份，四条调用点共用。

本模块只做**判定**，不做处置：违规的代价三条口各不相同（经验是概率性资产，
阻塞会让它大面积失声；知识会被当事实读；教训会停用工具），处置强度因此留给
各调用点，理由与差异见各入库口自己的说明。
"""

from __future__ import annotations

import re
from typing import List

# 高风险标识符提取域：URL / 绝对路径 / 版本号 / hex-hash。
# 域是按"模型最容易在这些地方编造、且编造后最难被发现"选的，不是按自然语言断言选的
# ——扩到自然语言断言要另立项（先得定义"什么算一条可核断言"）。
_IDENTIFIER_PATTERNS = (
    re.compile(r"https?://[^\s<>\"')\]\uFF0C\u3002\uFF1B\uFF01\uFF1F\uFF08\uFF09\u3010\u3011\u300A\u300B]+", re.IGNORECASE),
    re.compile(r"(?<![\w\-/])(/[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+)"),  # 多段路径
    re.compile(r"\b\d+\.\d+\.\d+(?:\.\d+)?(?:-[0-9A-Za-z.\-]+)?\b"),  # semver 形
    re.compile(r"\b[0-9a-f]{12,64}\b", re.IGNORECASE),  # hex hash/sha 片段
)

# 每笔写入的逐字可核结论（三态，与 `evidence_state` 正交）。
# `unchecked` 必须自成一态：调用方没提供可核原料时，既不是"核过没问题"，
# 也不是"核过有问题"——把前两者合起来读，违规率就永远被稀释成好看的数字。
VERIFIABILITY_STATES: tuple = ("unchecked", "verified", "violated")

# 违规处置名册：三种代价各有名字，不许把三者折叠成同一个布尔——
# 折叠之后"经验被降权"与"工具被停用"在读面上长得一样，读数就再也分不出轻重。
VIOLATION_OUTCOMES: tuple = (
    "demoted",   # 记违规标记 + 降权，仍写入（经验是概率性资产）
    "rejected",  # 拒该条断言，走既有诚实路径暴露（知识会被当事实注入）
    "refused",   # 拒绝生成（教训会拦工具，代价最高）
)


def extract_identifiers(text: str) -> List[str]:
    """从文本提取高风险精确标识符（URL/路径/版本号/hash）——反幻觉校验域。"""
    found: List[str] = []
    seen = set()
    for pattern in _IDENTIFIER_PATTERNS:
        for m in pattern.finditer(text or ""):
            value = m.group(0).rstrip(".,;:，。；）)…")
            if value and value.lower() not in seen and len(value) >= 5:
                seen.add(value.lower())
                found.append(value)
    return found


def find_violations(summary: str, evidence: str) -> List[str]:
    """`summary` 中存在但 `evidence` 中逐字缺失的标识符。"""
    evidence_lower = (evidence or "").lower()
    return [
        ident
        for ident in extract_identifiers(summary)
        if ident.lower() not in evidence_lower
    ]


def verifiabilityState(text: str, evidence: str) -> str:
    """一笔写入的逐字可核结论（三态）。

    没有可核原料时返回 `unchecked`，**不返回 `verified`**——把"没提供证据"
    读成"核过了没问题"，正是这一批要灭的那种把没测到演成好结果的病。
    """
    if not str(evidence or "").strip():
        return "unchecked"
    if not str(text or "").strip():
        return "unchecked"
    return "violated" if find_violations(str(text), str(evidence)) else "verified"

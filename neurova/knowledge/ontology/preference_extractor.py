"""反馈→偏好约束提取（B-L-F F-1/F-2，升级计划 §3.5 L-F）。

从客户反馈文本中提取结构化偏好约束——差评不是噪声，是偏好信号。
模式匹配覆盖常见场景（过敏/预算/口味/忌口），复杂场景靠 LLM 抽取管道（另批）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .recommender import Constraint


#: 模式库：每条 (pattern, attribute, operator, value, priority)
#: pattern 是正则，匹配反馈文本中的偏好信号词。
_PATTERNS: List[Dict[str, Any]] = [
    # 饮食限制（硬约束：健康/安全）
    {"pattern": r"海鲜过敏|对海鲜.*过敏|不能吃海鲜",
     "attribute": "has_seafood", "operator": "==", "value": "false",
     "priority": "hard", "rationale": "海鲜过敏"},
    {"pattern": r"花生过敏|对花生.*过敏",
     "attribute": "has_peanut", "operator": "!=", "value": "true",
     "priority": "hard", "rationale": "花生过敏"},
    {"pattern": r"素食|不吃肉",
     "attribute": "has_meat", "operator": "!=", "value": "true",
     "priority": "hard", "rationale": "素食"},
    {"pattern": r"忌辣|不能吃辣|不吃辣",
     "attribute": "is_spicy", "operator": "!=", "value": "true",
     "priority": "hard", "rationale": "忌辣"},
    # 价格敏感（软偏好）
    {"pattern": r"价格偏[高]|太贵|价格太高|贵了",
     "attribute": "price", "operator": "<", "value": "400",
     "priority": "soft", "rationale": "价格敏感"},
    {"pattern": r"预算[不足有限]|便宜.*好",
     "attribute": "price", "operator": "<", "value": "300",
     "priority": "soft", "rationale": "预算有限"},
]


def extractPreferences(feedbackText: str) -> List[Constraint]:
    """从反馈文本中提取偏好约束。返回 Constraint 列表（可能为空）。"""
    text = str(feedbackText or "").strip()
    if not text:
        return []
    constraints: List[Constraint] = []
    seen: set = set()
    for pattern in _PATTERNS:
        if re.search(pattern["pattern"], text, re.IGNORECASE):
            key = (pattern["attribute"], pattern["operator"], pattern["value"])
            if key not in seen:
                seen.add(key)
                constraints.append(Constraint(
                    attribute=pattern["attribute"],
                    operator=pattern["operator"],
                    value=pattern["value"],
                    priority=pattern["priority"],
                ))
    return constraints

"""宪法规则独立持久源（data/constitution/{agent_id}.json）。

2026-09-12 P1 台账清剿引入：原读写 agent.constitution 内存属性（构造默认 ""，
add 时 setattr 成 list）→ 无落盘重启即丢，且 FE growth.ts 路径 /constitution[/{id}]
与 BE /constitution/rules[/{id}] 错位增删改恒 404。规则独立落盘。

2026-09-16 模块化：自 growth.py 拆出（原私有名经 growth 聚合器 re-export
保持兼容：_load_constitution_rules / _save_constitution_rules / _rule_to_model /
_CONSTITUTION_DIR）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

CONSTITUTION_DIR = "data/constitution"


def constitution_path(agent_id: str) -> pathlib.Path:
    safe = str(agent_id).replace("/", "_").replace("\\", "_")
    return pathlib.Path(CONSTITUTION_DIR) / f"{safe}.json"


def load_constitution_rules(agent_id: str) -> List[Dict[str, Any]]:
    try:
        with open(constitution_path(agent_id), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_constitution_rules(agent_id: str, rules: List[Dict[str, Any]]) -> None:
    p = constitution_path(agent_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
    tmp.replace(p)


class ConstitutionRule(BaseModel):
    """宪法规则"""

    rule_id: str
    agent_id: str
    timestamp: float
    rule_type: str = "behavior"
    content: str = ""
    priority: int = 0
    enabled: bool = True


class ConstitutionRuleCreate(BaseModel):
    """创建宪法规则请求"""

    rule_type: str = Field(default="behavior", description="规则类型")
    content: str = Field(..., description="规则内容")
    priority: int = Field(default=0, ge=0, le=100, description="优先级")
    # FE 启用/禁用开关（toggle）：None = 不改，缺省新建为 enabled True
    enabled: Optional[bool] = Field(default=None, description="是否启用")


class ConstitutionRuleUpdate(BaseModel):
    """局部更新宪法规则请求（toggle 只传 enabled，不得覆写 content）"""

    rule_type: Optional[str] = None
    content: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=0, le=100)
    enabled: Optional[bool] = None


def rule_to_model(agent_id: str, rule: Dict[str, Any]) -> ConstitutionRule:
    return ConstitutionRule(
        rule_id=rule.get("rule_id", ""),
        agent_id=agent_id,
        timestamp=rule.get("timestamp", 0.0),
        rule_type=rule.get("rule_type", "behavior"),
        content=rule.get("content", ""),
        priority=rule.get("priority", 0),
        enabled=rule.get("enabled", True),
    )

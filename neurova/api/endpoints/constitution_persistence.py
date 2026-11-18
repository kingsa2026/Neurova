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
from neurova.core.data_root import dataPath


CONSTITUTION_DIR = dataPath("constitution")


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


# ── E2 宪法规则接行为注入（四域审计 2026-11-18）──────────────────────────
# 规则编译进 system prompt 宪法段的渲染上界（具名常量，超限诚实截断）。
# 条数 × 单条长度共同界定 token 预算（修复计划 E2 卡：规则条数×长度设具名上限）。
CONSTITUTION_RULES_MAX_COUNT = 20  # 单次注入 system prompt 的启用规则条数上限
CONSTITUTION_RULES_MAX_CHARS = 500  # 单条规则文本的字符数上限


def _rule_priority(rule: Dict[str, Any]) -> int:
    """规则优先级安全读数（脏数据按 0 计，不在注入面抛异常）。"""
    try:
        return int(rule.get("priority", 0) or 0)
    except (TypeError, ValueError):
        return 0


def compileConstitutionRulesSection(agent_id: str) -> str:
    """把该 agent 的 **enabled** 宪法规则编译为一段可注入 system prompt 的文本。

    - 只读：不写任何状态；产物与 `config.constitution` 字符串轨在 orchestrator
      `build_context` 的 system_instructions 组装点合流（同一注入点，不造第二个）。
    - 有界：条数 ≤ `CONSTITUTION_RULES_MAX_COUNT`、单条 ≤ `CONSTITUTION_RULES_MAX_CHARS`；
      超限在段内诚实标注（总数、未注入数与去向），不静默丢弃。
    - 排序：priority 降序（高优先级在前），同优先级保持落盘顺序（稳定排序）。
    - 无启用规则返回 ""，调用方据此不注入空段。
    - 会话冻结语义：本函数在会话首轮经 `session_snapshot._read_live` 取值并随
      快照冻结——同会话中途增删改规则不漂移当前 prompt，下次会话生效。
    """
    if not agent_id:
        return ""
    rules = load_constitution_rules(agent_id)
    if not isinstance(rules, list):
        return ""
    enabled: List[tuple] = []
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get("enabled", True):
            continue
        content = str(rule.get("content", "") or "").strip()
        if not content:
            continue
        enabled.append((_rule_priority(rule), content))
    if not enabled:
        return ""
    enabled.sort(key=lambda pair: -pair[0])
    total = len(enabled)
    lines = [f"宪法规则（启用 {total} 条，按优先级降序）："]
    for index, (_priority, content) in enumerate(
        enabled[:CONSTITUTION_RULES_MAX_COUNT], start=1
    ):
        if len(content) > CONSTITUTION_RULES_MAX_CHARS:
            content = (
                content[:CONSTITUTION_RULES_MAX_CHARS].rstrip()
                + f"…[单条超长，已截断至{CONSTITUTION_RULES_MAX_CHARS}字符]"
            )
        lines.append(f"{index}. {content}")
    if total > CONSTITUTION_RULES_MAX_COUNT:
        lines.append(
            f"（已截断：启用规则共 {total} 条，超出注入上限 {CONSTITUTION_RULES_MAX_COUNT} 条，"
            f"另有 {total - CONSTITUTION_RULES_MAX_COUNT} 条未注入；完整清单见宪法规则管理页）"
        )
    return "\n".join(lines)

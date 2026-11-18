"""人格特质独立持久源（`data/<agent_id>/personality.json`）。

2026-09-12 空数据页面修复引入：Agent.personality 实为 personality.md 身份文本
字符串，此前端点要求 isinstance(agent.personality, dict)（永假）→ traits 恒空、
PUT 静默 no-op 谎报成功、/growth 主页在非空 md 上 .get() 抛 AttributeError。
特质/价值观/风格与身份 md 正交，独立落盘。

2026-09-16 模块化：自 growth.py 拆出（原私有名经 growth 聚合器 re-export
保持兼容：_load_personality_data / _save_personality_data）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


def personality_path(agent_id: str) -> pathlib.Path:
    from neurova.core.agent_workspaces import get_agent_personality_path

    return get_agent_personality_path(agent_id)


def load_personality_data(agent_id: str) -> Dict[str, Any]:
    try:
        with open(personality_path(agent_id), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_personality_data(agent_id: str, data: Dict[str, Any]) -> None:
    p = personality_path(agent_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(p)


class PersonalityUpdate(BaseModel):
    """更新人格请求"""

    traits: Optional[Dict[str, float]] = None
    values: Optional[List[str]] = None
    communication_style: Optional[str] = None
    decision_style: Optional[str] = None


# ── E4 人格特质接行为注入（四域审计 2026-11-18）──────────────────────────
# 特质编译进 system prompt 人格段的渲染上界（具名常量，超限诚实截断）。
PERSONALITY_TRAITS_MAX_COUNT = 12  # 价值观/特质摘要最多列出的条目数
PERSONALITY_TRAITS_MAX_CHARS = 2000  # 人格特质段总字符上限


def compilePersonalityTraitsSection(agent_id: str) -> str:
    """把 personality.json 的沟通/决策风格、价值观与特质摘要编译为人格段文本。

    - 只读：不写任何状态；产物与 `personality.md` 文本轨（agent.personality）
      在 orchestrator `build_context` 的 system_instructions 组装点同点合流
      （紧邻文本轨之后，不造第二入口）。
    - 有界：条目 ≤ `PERSONALITY_TRAITS_MAX_COUNT`、段总长 ≤ `PERSONALITY_TRAITS_MAX_CHARS`，
      超限在段尾诚实标注，不静默丢弃。
    - 无任何特质内容返回 ""，调用方据此不注入空段。
    - 会话冻结语义：本函数在会话首轮经 `session_snapshot._read_live` 取值并随
      快照冻结——同会话中途改特质不漂移当前 prompt，下次会话生效。
    """
    if not agent_id:
        return ""
    data = load_personality_data(agent_id)
    if not isinstance(data, dict):
        return ""
    lines: List[str] = []
    communication_style = str(data.get("communication_style", "") or "").strip()
    if communication_style:
        lines.append(f"- 沟通风格：{communication_style}")
    decision_style = str(data.get("decision_style", "") or "").strip()
    if decision_style:
        lines.append(f"- 决策风格：{decision_style}")
    values = data.get("values")
    if isinstance(values, list):
        value_texts = [
            str(v).strip() for v in values if str(v).strip()
        ][:PERSONALITY_TRAITS_MAX_COUNT]
        if value_texts:
            lines.append("- 价值观：" + "、".join(value_texts))
    traits = data.get("traits")
    if isinstance(traits, dict):
        trait_items: List[tuple] = []
        for name, score in traits.items():
            name_text = str(name).strip()
            if not name_text:
                continue
            try:
                trait_items.append((name_text, float(score)))
            except (TypeError, ValueError):
                continue
        trait_items = trait_items[:PERSONALITY_TRAITS_MAX_COUNT]
        if trait_items:
            lines.append("- 特质：" + "、".join(f"{n} {s:.2f}" for n, s in trait_items))
    if not lines:
        return ""
    section = "人格特质档案：\n" + "\n".join(lines)
    if len(section) > PERSONALITY_TRAITS_MAX_CHARS:
        section = (
            section[:PERSONALITY_TRAITS_MAX_CHARS].rstrip()
            + f"…[人格特质段超长，已截断至{PERSONALITY_TRAITS_MAX_CHARS}字符]"
        )
    return section

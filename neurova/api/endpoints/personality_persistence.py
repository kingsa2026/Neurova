"""人格特质独立持久源（data/personality/{agent_id}.json）。

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

PERSONALITY_DIR = "data/personality"


def personality_path(agent_id: str) -> pathlib.Path:
    safe = str(agent_id).replace("/", "_").replace("\\", "_")
    return pathlib.Path(PERSONALITY_DIR) / f"{safe}.json"


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

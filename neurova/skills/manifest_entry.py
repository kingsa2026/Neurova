"""
Skill 清单条目数据类

清单中的单条 Skill 元数据——纯数据，不含执行逻辑（与
Skill 实例区分：manifest 没有 execute / run 方法）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SkillManifestEntry:
    """清单中的单条 Skill 元数据"""

    id: str
    name: str
    version: str = "1.0.0"
    source: str = "local"
    description: str = ""
    author: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

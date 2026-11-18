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
    # 对照批 B11：治理性披露字段（全部可选，缺省=行为与既往一致）
    #: 渠道限定：非空时仅这些渠道的轮次注入该技能（读侧信号=turn_context 渠道）
    channels: List[str] = field(default_factory=list)
    #: 环境依赖：声明的环境变量缺失时本轮不注入（点名记录，不静默）
    require_envs: List[str] = field(default_factory=list)
    #: 预载标记：True 时跳过按需选择直接进目录（保留位，消费面随批次接）
    preload: bool = False

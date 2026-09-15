"""技能库巩固(umbrella)— 识别窄技能簇,产出合并**计划**(纯计划,零变更)。

哲学收窄为两段:
  - **本模块是确定性计划段**(零 LLM):按前缀/领域词聚类,选出 umbrella,
    产出 ConsolidationPlan 列表;**绝不直接改技能库**;
  - 执行段走既有审批面(skill_review_gate / skill_pool_api pending 审批),
    由人/审批流拍板后才真正合并归档。

  - 只归档不删除,可恢复;
  - "一个宽 umbrella + 标注小节"优于"N 个窄兄弟";
  - 包完整性:吸收 references/ 必须重新编目(执行段责任,计划里标注)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_MIN_CLUSTER = 2


@dataclass
class ConsolidationPlan:
    """一次合并计划(未执行)。"""

    umbrella: str
    absorbed: list[str] = field(default_factory=list)
    reason: str = ""
    # 包完整性提示:被吸收技能的支撑文件须在执行段重新编目
    needs_reference_rehoming: bool = False

    def to_dict(self) -> dict:
        return {
            "umbrella": self.umbrella,
            "absorbed": list(self.absorbed),
            "reason": self.reason,
            "needs_reference_rehoming": self.needs_reference_rehoming,
        }


def find_prefix_clusters(names: list[str], min_size: int = _DEFAULT_MIN_CLUSTER) -> list[list[str]]:
    """按首个域词(或首段)聚类;窄前缀簇是 umbrella 的首要信号。

    """
    groups: dict[str, list[str]] = {}
    for name in names:
        parts = re.split(r"[-_.]", name.lower())
        if not parts or not parts[0]:
            continue
        # 单段名无簇信号;两段名取首段,三段以上取前两段(域词更准)
        key = "-".join(parts[:2]) if len(parts) >= 3 else parts[0]
        groups.setdefault(key, []).append(name)
    clusters = [sorted(v) for v in groups.values() if len(v) >= min_size]
    clusters.sort(key=lambda c: (-len(c), c[0]))
    return clusters


def _pick_umbrella(members: list[str], descriptions: dict[str, str]) -> str:
    """选 umbrella:正文最长的既有成员(内容最多者最可能承载类级规则)。

    确定性、可解释;不引入 LLM 判断。
    """
    return max(members, key=lambda m: (len(descriptions.get(m, "")), m))


class SkillConsolidator:
    """技能库巩固计划器(plan-only)。"""

    def __init__(self, min_cluster_size: int = _DEFAULT_MIN_CLUSTER):
        self.min_cluster_size = min_cluster_size

    def plan(self, skills: dict[str, str]) -> list[ConsolidationPlan]:
        """skills: {skill_name: description/正文};返回合并计划列表。

        纯计划产出——调用方拿到计划后走审批面执行,本模块零副作用。
        """
        if not skills:
            return []
        plans: list[ConsolidationPlan] = []
        claimed: set[str] = set()
        for cluster in find_prefix_clusters(list(skills), self.min_cluster_size):
            members = [m for m in cluster if m not in claimed]
            if len(members) < self.min_cluster_size:
                continue
            umbrella = _pick_umbrella(members, skills)
            absorbed = [m for m in members if m != umbrella]
            if not absorbed:
                continue
            claimed.update(members)
            plans.append(
                ConsolidationPlan(
                    umbrella=umbrella,
                    absorbed=absorbed,
                    reason=(
                        f"前缀簇 {len(members)} 个成员共享域词,合并为类级技能"
                        f"「{umbrella}」提升可发现性(系统提示技能索引按描述路由,"
                        f"窄技能越多路由越稀)"
                    ),
                    needs_reference_rehoming=True,
                )
            )
        return plans

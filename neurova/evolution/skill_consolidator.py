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
    # P1-2：成员质量证据（成功观测/复用数/描述长度），决策可审计
    quality: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "umbrella": self.umbrella,
            "absorbed": list(self.absorbed),
            "reason": self.reason,
            "needs_reference_rehoming": self.needs_reference_rehoming,
            "quality": dict(self.quality),
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


# ── P1-2 接线（2026-09-17）：从 plan-only 升级为"计划 + 审批面 + 落盘执行" ──


def _quality_of(stats: Optional[dict]) -> tuple:
    """成员质量排序键：成功观测数优先，其次回收次数，再退回描述长度。

    旧实现只按"描述最长"选 umbrella——那是"内容最多"的代理，与"质量最高"
    无关（一个被反复失败、从未成功的宽描述照样当选）。这里把真实使用账本
    纳入：成功数 → 复用数 → 描述长度，全部缺失时退化为确定性名字序。
    """
    if not isinstance(stats, dict):
        return (0.0, 0.0, 0)
    usage = stats.get("usage") or {}
    funnel = stats.get("funnel") or {}
    # usage/funnel 两个面都可能是"计数对象本身"或"外层容器"，逐个下钻一层。
    inner = usage.get("usage") if isinstance(usage.get("usage"), dict) else {}
    successes = float(inner.get("successes") or inner.get("success_count")
                      or inner.get("completions")
                      or usage.get("successes") or usage.get("success_count")
                      or usage.get("completions") or funnel.get("completions") or 0)
    reuse = float(stats.get("reuse_count") or inner.get("applications")
                  or usage.get("applications") or funnel.get("applications") or 0)
    return (successes, reuse, len(str(stats.get("description") or "")))


def plan_from_service(service, min_cluster_size: int = _DEFAULT_MIN_CLUSTER) -> list[ConsolidationPlan]:
    """从 SkillService 读真实技能库与账本，产出合并计划。

    与 `plan({name: description})` 的差别：umbrella 用**质量账本**选，而不是
    描述长度；聚簇仍在名字前缀上（确定性），但成员质量来自 usage/funnel。
    """
    stats: dict[str, dict] = {}
    descriptions: dict[str, str] = {}
    try:
        entries = service.list_skills()
    except Exception as e:  # noqa: BLE001 - 库不可读即无计划（绝不猜）
        logger.debug("技能库读取失败，合并计划为空: %s", e)
        return []
    for entry in entries:
        skill_id = str(entry.get("id") or "")
        if not skill_id:
            continue
        descriptions[skill_id] = str(entry.get("description") or "")
        detail = {}
        try:
            detail = service.get_skill_info(skill_id) or {}
        except Exception as e:  # noqa: BLE001
            logger.debug("技能 %s 详情读取失败: %s", skill_id, e)
        merged = {**entry, **detail}
        usage = {}
        try:
            usage = service.get_skill_usage(skill_id) or {}
        except Exception as e:  # noqa: BLE001
            logger.debug("技能 %s 用量读取失败: %s", skill_id, e)
        # funnel/usage 两个面都收：get_skill_usage 既可能返回完整用量对象，
        # 也可能直接返回漏斗计数（历史两种形态并存），并集后再取质量键。
        funnel = {}
        if isinstance(usage, dict):
            funnel = usage.get("funnel") if isinstance(usage.get("funnel"), dict) else usage
        stats[skill_id] = {**merged, "usage": merged.get("usage") or {},
                           "funnel": funnel or {}}

    plans: list[ConsolidationPlan] = []
    claimed: set[str] = set()
    for cluster in find_prefix_clusters(list(stats), min_cluster_size):
        members = [m for m in cluster if m not in claimed]
        if len(members) < min_cluster_size:
            continue
        # 质量优先选 umbrella；同分时按名字确定性兜底（可解释、可复现）
        umbrella = max(members, key=lambda m: (_quality_of(stats.get(m)), m))
        absorbed = [m for m in members if m != umbrella]
        if not absorbed:
            continue
        claimed.update(members)
        plans.append(
            ConsolidationPlan(
                umbrella=umbrella,
                absorbed=absorbed,
                reason=(
                    f"前缀簇 {len(members)} 个成员共享域词，合并为类级技能"
                    f"「{umbrella}」（按成功观测/复用数选优，非描述长度）"
                ),
                needs_reference_rehoming=True,
                quality={m: _quality_of(stats.get(m)) for m in members},
            )
        )
    return plans


class ConsolidationPlanStore:
    """合并计划落盘仓：待审批件（非技能库改动），有界 + 原子写。"""

    def __init__(self, skills_dir, filename: str = ".consolidation_plans.json"):
        from pathlib import Path

        self.path = Path(skills_dir) / filename

    def load(self) -> list[dict]:
        import json

        try:
            items = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return items if isinstance(items, list) else []

    def upsert(self, plans: list[dict], limit: int = 50) -> list[dict]:
        """按 umbrella 覆盖式登记（同一簇重复规划不叠加），有界保留。"""
        import json
        import os

        by_umbrella = {p.get("umbrella"): p for p in self.load() if isinstance(p, dict)}
        for plan in plans:
            if isinstance(plan, dict) and plan.get("umbrella"):
                by_umbrella[plan["umbrella"]] = {**plan, "status": plan.get("status", "pending")}
        items = list(by_umbrella.values())[-limit:]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            logger.debug("合并计划落盘失败: %s", e)
        return items

    def decide(self, umbrella: str, approve: bool) -> bool:
        items = self.load()
        hit = False
        for item in items:
            if item.get("umbrella") == umbrella and item.get("status") == "pending":
                item["status"] = "approved" if approve else "rejected"
                hit = True
        if hit:
            self.upsert(items)
        return hit


class ConsolidationApproval:
    """合并审批执行器（审批面调用；计划 → 归档被吸收技能 + 留痕）。

    语义选择：**归档不删除**（本模块设计契约"只归档不删除，可恢复"），
    被吸收成员转 archived 并由生命周期摘除，umbrella 保留可命中。绝不在此
    生成新技能正文——正文级改写走文本进化通道（有标尺）。
    """

    def __init__(self, service, store: Optional[ConsolidationPlanStore] = None):
        self.service = service
        self.store = store

    def approve(self, umbrella: str, absorbed: list) -> dict:
        archived, failed = [], []
        for skill_id in absorbed:
            try:
                result = self.service.archive_skill(skill_id)
            except Exception as e:  # noqa: BLE001 - 单个失败不阻断其余（可重试）
                result = {"success": False, "error": str(e)}
            (archived if result.get("success") else failed).append(skill_id)
        if self.store is not None and not failed:
            self.store.decide(umbrella, approve=True)
        return {"umbrella": umbrella, "archived": archived, "failed": failed}

    def reject(self, umbrella: str, absorbed: list) -> dict:
        if self.store is not None:
            self.store.decide(umbrella, approve=False)
        return {"umbrella": umbrella, "rejected": list(absorbed)}

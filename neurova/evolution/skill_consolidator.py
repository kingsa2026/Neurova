"""技能库巩固(umbrella)— 识别可合并技能簇,产出合并**计划**(纯计划,零变更)。

哲学收窄为两段:
  - **本模块是确定性计划段**(零 LLM):按**结构身份**聚类(工具序列/参数/
    业务意图,见 `find_structural_clusters`),选出 umbrella,产出
    ConsolidationPlan 列表;**绝不直接改技能库**;
  - 执行段走既有审批面(skill_review_gate / skill_pool_api consolidation 审批),
    由人/审批流拍板后才真正合并归档。

  - 只归档不删除,可恢复;
  - "一个宽 umbrella + 标注小节"优于"N 个窄兄弟";
  - 包完整性:吸收 references/ 必须重新编目(执行段责任,计划里标注)。

P1 收口(2026-09-17):**聚类口径从"名字前缀"换成"结构身份"**。
旧实现只按名字前缀聚簇,于是"同一工具序列、名字形态不同"的一批
(`skill_<fp16>` vs `genetic_<tools>` vs 裸参臂)——正是 P1-1 判定的
"同一技能被封装成多条"——聚不到一起,合并能力天花板停在名字层。
现在按身份聚类,basis 记录本簇依据哪一级身份(可审计),名字前缀只作为
**无工具序列条目**(手工/用户技能)的兜底信号。
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
    # P1 收口（2026-09-17）：本簇依据哪一级身份聚出来的——审批人据此判断
    # 合并的激进程度。见 `find_structural_clusters`：
    #   "identity"    同一业务身份（工具序列+参数+意图全同）= 真重复，可直接合
    #   "structure"   同一工具序列但意图不同 = 同族不同业务，合并即"跨意图收编"
    #   "name_prefix" 无工具序列的存量条目兜底（名字前缀），旧口径
    basis: str = "name_prefix"
    # 结构身份（工具序列+参数，不含意图）；name_prefix 兜底簇为空串
    structure: str = ""
    # 簇内业务身份分布：{skill_id: 业务身份指纹}，供审批面看"收编了几个意图"
    intents: dict = field(default_factory=dict)

    @property
    def cross_intent(self) -> bool:
        """本簇是否跨业务意图（basis=="structure" 且含多个不同意图）。"""
        return self.basis == "structure" and len(set(self.intents.values())) > 1

    def to_dict(self) -> dict:
        return {
            "umbrella": self.umbrella,
            "absorbed": list(self.absorbed),
            "reason": self.reason,
            "needs_reference_rehoming": self.needs_reference_rehoming,
            "quality": dict(self.quality),
            "basis": self.basis,
            "structure": self.structure,
            "intents": dict(self.intents),
        }


def find_prefix_clusters(names: list[str], min_size: int = _DEFAULT_MIN_CLUSTER) -> list[list[str]]:
    """按首个域词(或首段)聚类——**仅作无结构身份条目的兜底信号**。

    P1 收口(2026-09-17):本函数不再是首要聚簇口径。名字是**展示层**属性,
    三条写入臂各有命名形态(`skill_<fp16>` / `genetic_<tools>` / `synth_*`),
    同一工具序列换个名字就聚不到一起——合并能力天花板卡在名字层。首要口径
    改为 `find_structural_clusters`(工具序列族);本函数只处理**没有工具
    序列的存量条目**(手工创建/用户导入),那些条目本来就没有结构可依。
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


@dataclass
class _Cluster:
    """一个候选簇（结构身份聚合的中间产物，不外泄）。

    basis/structure/intents 会原样带进 ConsolidationPlan——审批人需要知道
    "这一簇是真重复，还是同序列不同业务"，两者的合并风险不同。
    """

    members: list[str] = field(default_factory=list)
    basis: str = "name_prefix"
    structure: str = ""
    intents: dict = field(default_factory=dict)


def sequence_family(steps) -> str:
    """结构族键 = **工具名序列**(按顺序，忽略参数与意图)。

    为什么族键忽略参数:`{"tool":"read","params":{"i":0}}` 与
    `{"tool":"read","params":{"i":1}}` 是"同一序列的两个实例"——参数是调用
    时的绑定，不是身份；把它们拆到两个簇，正是旧实现"同一技能堆成多条"
    却合并不了的同一层失效。参数差异在业务身份里仍被吸收(见下方的
    `intents`)，审批面据此看到"这一簇里绑了几个身份"。
    """
    from neurova.skills.creation_governance import normalize_steps

    normalized = normalize_steps(steps)
    if not normalized:
        return ""
    return " → ".join(step["tool"] for step in normalized)


def find_structural_clusters(
    facts: dict[str, dict], min_size: int = _DEFAULT_MIN_CLUSTER
) -> list["_Cluster"]:
    """按**结构身份**聚簇:先工具序列族，余下无序列条目走名字前缀兜底。

    facts: {skill_id: {"tool_sequence": [...], "purpose": "...", "description": "..."}}

    返回的每个簇记录 `basis`(本簇依据哪一级身份聚出)与 `intents`(成员业务
    身份指纹)，两者随计划落库——审批人需要知道"这一簇是真重复，还是同族
    不同业务"，两者的合并风险完全不同。
    """
    from neurova.skills.creation_governance import fingerprint

    families: dict[str, list[str]] = {}
    structural: set[str] = set()
    for skill_id, fact in facts.items():
        family = sequence_family(fact.get("tool_sequence"))
        if not family:
            continue
        families.setdefault(family, []).append(skill_id)
        structural.add(skill_id)

    clusters: list[_Cluster] = []
    for family, members in families.items():
        if len(members) < min_size:
            continue
        members = sorted(members)
        intents = {
            sid: fingerprint(facts[sid].get("tool_sequence"),
                             facts[sid].get("purpose") or facts[sid].get("description") or "")
            or ""
            for sid in members
        }
        basis = "identity" if len(set(intents.values())) == 1 else "structure"
        clusters.append(_Cluster(members=members, basis=basis, structure=family, intents=intents))

    # 兜底:无工具序列的存量条目(手工/用户导入)按名字前缀聚——它们没有
    # 结构可依，前缀是唯一可用信号；basis 如实标 "name_prefix"。
    leftovers = {sid: fact for sid, fact in facts.items() if sid not in structural}
    for prefix_cluster in find_prefix_clusters(list(leftovers), min_size):
        members = sorted(prefix_cluster)
        clusters.append(
            _Cluster(
                members=members,
                basis="name_prefix",
                structure="",
                intents={
                    sid: fingerprint(leftovers[sid].get("tool_sequence"),
                                     leftovers[sid].get("purpose")
                                     or leftovers[sid].get("description") or "")
                    or ""
                    for sid in members
                },
            )
        )
    # 确定性排序：簇越大越靠前，同大小按首成员名——计划可复现
    clusters.sort(key=lambda c: (-len(c.members), c.members[0]))
    return clusters


def _pick_umbrella(members: list[str], descriptions: dict[str, str]) -> str:
    """选 umbrella:正文最长的既有成员(内容最多者最可能承载类级规则)。

    确定性、可解释;不引入 LLM 判断。
    """
    return max(members, key=lambda m: (len(descriptions.get(m, "")), m))


class SkillConsolidator:
    """技能库巩固计划器(plan-only)。

    P1 收口(2026-09-17):**聚簇口径只有一个——结构身份**。
    生产入口是 `plan_from_service`(读真实库 + 质量账本);本类的 `plan`
    保留旧的 `{名字: 描述}` 入参,但它只能走名字前缀兜底(入参里没有工具
    序列,结构身份无从算起)——故 `plan` 与 `plan_from_service` **不是两套
    口径**,是同一套口径在"有/无结构信息"两种输入下的两级信号:

      - 有工具序列(生产真实条目,三条写入臂产物都带) → `plan_from_structure`
        按序列族聚,能认出"同序列、异名形态"的重复;
      - 无工具序列(手工/用户条目) → 名字前缀兜底,plan 结果里 basis 如实
        标 "name_prefix",不冒充结构判据。
    """

    def __init__(self, min_cluster_size: int = _DEFAULT_MIN_CLUSTER):
        self.min_cluster_size = min_cluster_size

    def plan(self, skills: dict[str, str]) -> list[ConsolidationPlan]:
        """skills: {skill_name: description/正文};返回合并计划列表。

        纯计划产出——调用方拿到计划后走审批面执行,本模块零副作用。
        入参无工具序列 → 只能名字前缀兜底(见类 docstring);
        需要结构身份聚类请走 `plan_from_service` / `plan_from_structure`。
        """
        return self.plan_from_structure({sid: {"description": desc} for sid, desc in skills.items()})

    def plan_from_structure(self, facts: dict[str, dict]) -> list[ConsolidationPlan]:
        """按结构身份聚簇产计划。

        facts: {skill_id: {"tool_sequence": [...], "purpose": "...", "description": "..."}}
        有工具序列的走序列族;没有的自动落到名字前缀兜底——两条路径都带
        basis 标注,审批面能分辨本簇是真重复还是兜底聚簇。
        """
        if not facts:
            return []
        descriptions = {
            sid: str(fact.get("description") or fact.get("purpose") or "")
            for sid, fact in facts.items()
        }
        plans: list[ConsolidationPlan] = []
        claimed: set[str] = set()
        for cluster in find_structural_clusters(facts, self.min_cluster_size):
            members = [m for m in cluster.members if m not in claimed]
            if len(members) < self.min_cluster_size:
                continue
            umbrella = _pick_umbrella(members, descriptions)
            absorbed = [m for m in members if m != umbrella]
            if not absorbed:
                continue
            claimed.update(members)
            plans.append(
                ConsolidationPlan(
                    umbrella=umbrella,
                    absorbed=absorbed,
                    reason=_cluster_reason(cluster.basis, members, umbrella, cluster.structure),
                    needs_reference_rehoming=True,
                    quality={m: _quality_of({"description": descriptions.get(m, "")}) for m in members},
                    basis=cluster.basis,
                    structure=cluster.structure,
                    intents={m: cluster.intents.get(m, "") for m in members},
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


def _entry_fact(entry: dict, detail: dict) -> dict:
    """从库条目抽结构身份三件套：工具序列 / 业务意图 / 描述。

    工具序列藏在 manifest.config（三臂统一写这里）；意图优先取显式
    task_purpose / context_template，缺省退回描述——与
    `creation_governance.manifest_purpose` 同一口径，否则同一技能在
    "封装署名"与"合并计身份"两处会算出不同身份。
    """
    manifest = (detail.get("manifest") or entry.get("manifest") or {})
    config = manifest.get("config") if isinstance(manifest, dict) else None
    config = config if isinstance(config, dict) else {}
    return {
        "tool_sequence": config.get("tool_sequence") or [],
        "purpose": (config.get("task_purpose") or config.get("context_template")
                    or detail.get("description") or entry.get("description") or ""),
        "description": str(detail.get("description") or entry.get("description") or ""),
    }


def plan_from_service(service, min_cluster_size: int = _DEFAULT_MIN_CLUSTER) -> list[ConsolidationPlan]:
    """从 SkillService 读真实技能库与账本，产出合并计划。

    P1 收口（2026-09-17）：**聚簇口径换成结构身份**（`find_structural_clusters`）。

    旧实现的失效不在"选谁当 umbrella"，而在**聚谁**：只按名字前缀聚，于是
    P1-1 已判定的"同一技能被封装成多条"（同序列、异名形态：
    `skill_<fp16>` / `genetic_<tools>` / `synth_*`）**聚不到同一簇**——重复被
    判出来了、却合并不了，能力天花板停在名字层。现在按工具序列族聚类，
    并如实标注本簇是"同一业务身份的真重复"还是"同序列不同业务的跨意图收编"。

    与 `plan({name: description})` 的差别：umbrella 用**质量账本**选，而不是
    描述长度；成员质量来自 usage/funnel。
    """
    stats: dict[str, dict] = {}
    facts: dict[str, dict] = {}
    try:
        entries = service.list_skills()
    except Exception as e:  # noqa: BLE001 - 库不可读即无计划（绝不猜）
        logger.debug("技能库读取失败，合并计划为空: %s", e)
        return []
    for entry in entries:
        skill_id = str(entry.get("id") or "")
        if not skill_id:
            continue
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
        facts[skill_id] = _entry_fact(entry, detail)

    plans: list[ConsolidationPlan] = []
    claimed: set[str] = set()
    for cluster in find_structural_clusters(facts, min_cluster_size):
        members = [m for m in cluster.members if m not in claimed]
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
                reason=_cluster_reason(cluster.basis, members, umbrella, cluster.structure),
                needs_reference_rehoming=True,
                quality={m: _quality_of(stats.get(m)) for m in members},
                basis=cluster.basis,
                structure=cluster.structure,
                intents={m: cluster.intents.get(m, "") for m in members},
            )
        )
    return plans


def _cluster_reason(basis: str, members: list[str], umbrella: str, structure: str) -> str:
    """计划理由：先说清**依据哪一级身份**聚的——审批人据此判风险。"""
    if basis == "identity":
        return (
            f"业务身份重复：{len(members)} 个条目工具序列+意图全同，"
            f"收敛为「{umbrella}」（真重复，可直接合并；按成功观测/复用数选优）"
        )
    if basis == "structure":
        return (
            f"结构同族：{len(members)} 个条目共享工具序列「{structure}」但业务意图不同，"
            f"合并为「{umbrella}」= 跨意图收编（窄技能越多路由越稀；审批需确认"
            f"「一个宽 umbrella 覆盖多意图」是否可接受）"
        )
    return (
        f"名字前缀簇：{len(members)} 个成员无工具序列（手工/用户技能），"
        f"按域词聚合并为「{umbrella}」（无结构身份可依，前缀是唯一可用信号）"
    )


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

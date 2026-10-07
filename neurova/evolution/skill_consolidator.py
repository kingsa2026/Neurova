"""技能库巩固(umbrella)— 识别可合并技能簇,产出合并计划并按治理模式执行。

治理模式(2026-10-07 规则修订,登记于
docs/08-research/skillglow_vs_neurova_skill_consolidation_2026-10-07.md §0):
  - 默认(consolidation_auto_commit_enabled=false):**纯计划段**——本模块
    零 LLM 产出计划,执行走审批面(skill_pool_api /consolidation/*),由人拍板;
  - 全自动(开关=true,2026-10-07 用户指令):计划过**确定性 commit gate**
    (`auto_commit_gate_issues`——召回预检 + 结构身份门槛,fail-closed:任一检
    不过仍留人工)即自动执行 `ConsolidationApproval.approve`,decided_by=
    "auto_commit_gate" 全程留痕。此为对"绝不自动合并"旧哲学的显式修订:
    整合动作=归档可逆+预检确定性+账本迁移,风险量级低于新技能生成
    (后者维持评审闸不变)。

共同语义:
  - 只归档不删除,可恢复;
  - "一个宽 umbrella + 标注小节"优于"N 个窄兄弟";
  - 包完整性:吸收 references/ 须重新编目(执行段责任,计划里标注);
  - 吸收时被吸收技能的 applied 经验重键到 umbrella(P1-1,教训不冷启动)。

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

from neurova.core.data_root import require_data_path
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


def _collect_service_facts(service) -> tuple:
    """从 SkillService 读真实技能库与账本（结构/语义两源共用）：返回 (stats, facts)。

    库不可读 → ({}, {})——调用方按"无计划"处理，绝不猜。
    """
    stats: dict = {}
    facts: dict = {}
    try:
        entries = service.list_skills()
    except Exception as e:  # noqa: BLE001 - 库不可读即无计划（绝不猜）
        logger.debug("技能库读取失败，合并计划为空: %s", e)
        return stats, facts
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
    return stats, facts


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
    stats, facts = _collect_service_facts(service)
    if not facts:
        return []

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


# ── P3 语义族第二计划源（2026-10-07，SkillGLoW 对比）──────────────────

_DEFAULT_SEMANTIC_THRESHOLD = 0.82


def semantic_family_clusters(
    vectors: dict, threshold: float, exclude: Optional[set] = None
) -> list:
    """按名述嵌入余弦聚"同目的、异序列"族(种子中心贪心,防单链漂移)。

    确定性:成员按名排序后依次作种子,吸收与种子相似 ≥threshold 的未认领
    成员——不做对链式合并(那会把"相似链"两端拉进同族)。
    """
    from neurova.skills.skill_semantics import _cosine

    names = sorted(n for n in vectors if n not in (exclude or set()))
    claimed: set = set()
    clusters: list = []
    for seed in names:
        if seed in claimed:
            continue
        members = [seed]
        for other in names:
            if other == seed or other in claimed:
                continue
            if _cosine(vectors[seed], vectors[other]) >= threshold:
                members.append(other)
        if len(members) >= 2:
            claimed.update(members)
            clusters.append(sorted(members))
    return clusters


def plan_from_semantics(
    service,
    exclude: Optional[set] = None,
    *,
    vector_cache: Optional[Any] = None,
    threshold: float = _DEFAULT_SEMANTIC_THRESHOLD,
) -> list[ConsolidationPlan]:
    """语义族第二计划源(P3,SkillGLoW 对比):聚"同目的、异序列"的语义同义族。

    - 结构族(工具序列)仍是主判据且先产先占成员:调用方把结构计划已认领的
      成员传进 `exclude`,本源只聚剩余技能——两源不抢同一成员;
    - 零 LLM:嵌入来自本地 bge ONNX(skill_semantics,带缓存);引擎不可用
      → 空列表诚实降级(结构源是常备路径);
    - basis="semantic" 的计划**永不自动提交**(auto_commit_gate_issues 拦):
      跨序列收编风险高于结构族,只进人工审批面。
    """
    from types import SimpleNamespace

    from neurova.skills.creation_governance import fingerprint
    from neurova.skills.skill_semantics import SkillVectorCache

    exclude = set(exclude or ())
    stats, facts = _collect_service_facts(service)
    candidates = {sid: fact for sid, fact in facts.items() if sid not in exclude}
    if len(candidates) < 2:
        return []

    cache = vector_cache or SkillVectorCache()
    skill_objs = {
        sid: SimpleNamespace(
            name=sid,
            description=str(fact.get("description") or fact.get("purpose") or ""),
        )
        for sid, fact in candidates.items()
    }
    vectors = cache.vectors_for(skill_objs)
    if not vectors:
        logger.debug("语义族计划:嵌入向量不可用,诚实降级(结构源是常备路径)")
        return []

    plans: list[ConsolidationPlan] = []
    for members in semantic_family_clusters(vectors, threshold, exclude):
        umbrella = max(members, key=lambda m: (_quality_of(stats.get(m)), m))
        absorbed = [m for m in members if m != umbrella]
        if not absorbed:
            continue
        plans.append(
            ConsolidationPlan(
                umbrella=umbrella,
                absorbed=absorbed,
                reason=(
                    f"语义同族:{len(members)} 个条目名述嵌入高度相似(≥{threshold:.2f})"
                    f"但工具序列不同——可能是\"同一目的、不同实现路径\"的语义同义重复,"
                    f"收敛为「{umbrella}」;跨序列收编风险高于结构族,留人工确认后合并"
                ),
                needs_reference_rehoming=True,
                quality={m: _quality_of(stats.get(m)) for m in members},
                basis="semantic",
                structure="",
                intents={
                    m: fingerprint(
                        facts[m].get("tool_sequence"),
                        facts[m].get("purpose") or facts[m].get("description") or "")
                    or ""
                    for m in members
                },
            )
        )
    plans.sort(key=lambda p: (-len(p.absorbed) - 1, p.umbrella))
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
        """锚点在构造处收口：`skills_dir` 必须是绝对路径。

        本仓有 6 个生产调用点把 `service.skills_dir` 直接递进来。真 `SkillService`
        取 `get_data_root()`（恒绝对），所以非绝对值只可能是外部注入（mock / 手传相对
        串）——那种情况下原先是 `upsert` 里 `mkdir(parents=True)` 在进程 CWD 静默建塔
        写盘，只在 `except OSError` 留一行 debug。判据与 `run_sweep_if_due` 同一处
        （`data_root.require_data_path`），不在本模块另抄一份。
        """
        self.path = require_data_path(skills_dir, "skills_dir（合并计划落盘锚点）") / filename
        # 工单 016 口径：溢出必须留痕计数，不许静默丢（2026-10-07 对齐）
        self.overflow_dropped = 0

    def load(self) -> list[dict]:
        import json

        try:
            items = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return items if isinstance(items, list) else []

    def upsert(self, plans: list[dict], limit: int = 50) -> list[dict]:
        """按 umbrella 覆盖式登记（同一簇重复规划不叠加），有界保留。

        有界截断的溢出计数进 `overflow_dropped` 并告警——静默丢计划等于
        观察面失明（对齐 skill_experience/结晶器的工单 016 口径）。
        """
        import json
        import os

        by_umbrella = {p.get("umbrella"): p for p in self.load() if isinstance(p, dict)}
        for plan in plans:
            if isinstance(plan, dict) and plan.get("umbrella"):
                by_umbrella[plan["umbrella"]] = {**plan, "status": plan.get("status", "pending")}
        items = list(by_umbrella.values())
        overflow = len(items) - limit
        if overflow > 0:
            self.overflow_dropped += overflow
            dropped = [p.get("umbrella") for p in items[:overflow]]
            logger.warning(
                "合并计划仓超上界 %d，丢弃最旧 %d 条（累计 %d）: %s",
                limit, overflow, self.overflow_dropped, dropped,
            )
            items = items[-limit:]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            logger.debug("合并计划落盘失败: %s", e)
        return items

    def decide(self, umbrella: str, approve: bool,
               decided_by: str = "", gate_issues: Optional[list] = None) -> bool:
        from datetime import datetime, timezone

        items = self.load()
        hit = False
        for item in items:
            if item.get("umbrella") == umbrella and item.get("status") == "pending":
                item["status"] = "approved" if approve else "rejected"
                if decided_by:
                    item["decided_by"] = str(decided_by)
                item["decided_at"] = datetime.now(timezone.utc).isoformat()
                # 审计面统一形态：过闸=空表，留人工=预检读数
                item["gate_issues"] = list(gate_issues or [])
                hit = True
        if hit:
            self.upsert(items)
        return hit


class ConsolidationApproval:
    """合并审批执行器（审批面调用；计划 → 归档被吸收技能 + 账本迁移 + 留痕）。

    语义选择：**归档不删除**（本模块设计契约"只归档不删除，可恢复"），
    被吸收成员转 archived 并由生命周期摘除，umbrella 保留可命中。绝不在此
    生成新技能正文——正文级改写走文本进化通道（有标尺）。
    吸收时被吸收技能的 applied 经验重键到 umbrella（P1-1，2026-10-07）：
    教训随家族走，umbrella 不冷启动重新学习。
    """

    def __init__(self, service, store: Optional[ConsolidationPlanStore] = None):
        self.service = service
        self.store = store

    def approve(self, umbrella: str, absorbed: list,
                decided_by: str = "human") -> dict:
        archived, failed, migrated = [], [], {}
        for skill_id in absorbed:
            try:
                result = self.service.archive_skill(skill_id)
            except Exception as e:  # noqa: BLE001 - 单个失败不阻断其余（可重试）
                result = {"success": False, "error": str(e)}
            (archived if result.get("success") else failed).append(skill_id)
            if result.get("success"):
                try:
                    from neurova.evolution.skill_experience import (
                        get_skill_experience_store,
                    )

                    moved = get_skill_experience_store().migrate_records(
                        skill_id, umbrella)
                    if moved:
                        migrated[skill_id] = moved
                except Exception as e:  # noqa: BLE001 - 账本迁移失败不阻断归档（可重试）
                    logger.warning("经验账本迁移失败 %s → %s: %s", skill_id, umbrella, e)
        if self.store is not None and not failed:
            self.store.decide(umbrella, approve=True, decided_by=decided_by)
        return {"umbrella": umbrella, "archived": archived, "failed": failed,
                "migrated_experiences": migrated, "decided_by": decided_by}

    def reject(self, umbrella: str, absorbed: list,
               decided_by: str = "human") -> dict:
        if self.store is not None:
            self.store.decide(umbrella, approve=False, decided_by=decided_by)
        return {"umbrella": umbrella, "rejected": list(absorbed),
                "decided_by": decided_by}


def auto_commit_gate_issues(service, plan: dict) -> list:
    """全自动 commit gate 的确定性预检(P1-2/SkillGLoW 对比落地,零 LLM)。

    fail-closed 多检——任一不过即留人工:
    1. basis=="name_prefix"(无结构身份的兜底簇)永不自动提交;
    2. umbrella 必须真实存在且描述非空(死种子不吞并别人);
    3. 召回预检:umbrella 的名述必须能召回每个被吸收成员的技能名
       (复用 routing_sanity_check 的正例召回判据,单一事实源)——
       这正是 SkillGLoW 自认"修好一个弄坏另一个"失败模式的审批前拦截。
    """
    issues: list = []
    umbrella = str(plan.get("umbrella") or "")
    absorbed = [str(a) for a in (plan.get("absorbed") or [])]
    if plan.get("basis") == "name_prefix":
        issues.append("name_prefix 兜底簇无结构身份可依,留人工裁决")
    if plan.get("basis") == "semantic":
        issues.append("语义族计划是跨序列收编(工具序列不同),风险高于结构族,留人工裁决")
    detail = {}
    try:
        detail = service.get_skill_info(umbrella) or {}
    except Exception as e:  # noqa: BLE001
        issues.append(f"umbrella 详情读取失败: {e}")
        detail = {}
    if not detail:
        issues.append(f"umbrella 不存在: {umbrella}")
        return issues

    from neurova.skills.skill_injection import routing_sanity_check

    positives = []
    for sid in absorbed:
        info = {}
        try:
            info = service.get_skill_info(sid) or {}
        except Exception as e:  # noqa: BLE001
            issues.append(f"被吸收成员 {sid} 详情读取失败: {e}")
        positives.append(str(info.get("name") or sid))
    issues.extend(routing_sanity_check(
        str(detail.get("name") or umbrella),
        str(detail.get("description") or ""),
        positive_queries=positives,
    ))
    return issues


def consolidation_auto_commit_enabled() -> bool:
    """全自动 commit gate 开关(治理设置;env NEUROVA_CONSOLIDATION_AUTO_COMMIT
    逃生门)。默认开 = 2026-10-07 用户指令"全自动 commit gate 替代人工审批"
    的规则修订;关 = 回退人工审批面。"""
    from neurova.security.governance_settings import resolve_flag

    return resolve_flag(
        "consolidation_auto_commit_enabled", "NEUROVA_CONSOLIDATION_AUTO_COMMIT")


def consolidation_semantic_plans_enabled() -> bool:
    """语义族第二计划源开关(治理设置;env NEUROVA_CONSOLIDATION_SEMANTIC_PLANS
    逃生门)。默认开:计划只进人工审批面、永不自动提交,成本为本地嵌入
    (带缓存)。关 = 只跑结构族计划源。"""
    from neurova.security.governance_settings import resolve_flag

    return resolve_flag(
        "consolidation_semantic_plans_enabled", "NEUROVA_CONSOLIDATION_SEMANTIC_PLANS")


def maybe_auto_commit(service, store: ConsolidationPlanStore,
                      plans: list) -> list:
    """对 pending 计划跑全自动 commit gate:过闸即执行,不过留人工。

    Returns: 审计列表 [{umbrella, decision, gate_issues|result}]。
    """
    audits: list = []
    if not consolidation_auto_commit_enabled():
        return audits
    for plan in plans:
        if not isinstance(plan, dict) or plan.get("status") != "pending":
            continue
        umbrella = str(plan.get("umbrella") or "")
        if not umbrella:
            continue
        issues = auto_commit_gate_issues(service, plan)
        if issues:
            # 不过闸不改状态（留人工），但把预检读数挂回计划留痕
            items = store.load()
            for item in items:
                if item.get("umbrella") == umbrella:
                    item["gate_issues"] = issues
            store.upsert(items)
            audits.append({"umbrella": umbrella, "decision": "held_for_human",
                           "gate_issues": issues})
            logger.info("整合计划 %s 未过自动 commit gate,留人工: %s", umbrella, issues)
            continue
        result = ConsolidationApproval(service, store).approve(
            umbrella, list(plan.get("absorbed") or []),
            decided_by="auto_commit_gate")
        audits.append({"umbrella": umbrella, "decision": "auto_committed",
                       "gate_issues": [], "result": result})
        logger.info(
            "整合计划 %s 过自动 commit gate,已执行(archived=%s, migrated=%s)",
            umbrella, result.get("archived"), result.get("migrated_experiences"),
        )
    return audits

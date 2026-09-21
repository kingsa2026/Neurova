# -*- coding: utf-8 -*-
"""轮级技能可见视图（Wave H-W2，三层技能库的装配内核）

需求模型（用户拍板）：
- 技能库三层：agent 私库 / 用户私库 / 公共库（所有用户可见）；
- agent 对话可见集 = 自己私库 + **当前会话用户**私库 + 公共库；别的 agent、
  别的用户的私库不可见不可调；
- 同名就近优先：agent > user > public（越私有越具体
  多源发现"首见者胜"相反方向——我们按层覆盖，agent 层最后写入即遮蔽）。

纪律：
- 视图缺席（后台任务/评测/旧调用链）→ 一切行为与现状一致（增量红线）；
- 用户键规范 `u:{jwt_sub}` / `ch:{channel}:{sender_id}`（library_service 白名单
  校验，防孤岛教训的路径注入）；系统身份（default/system/空）不建用户库视图；
- 账本 provenance 由视图供给：执行采集点记录命中副本的 (pool, owner_key)，
  flush 按库回写（W1 路由已就位）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.skills import library_service as lib
from neurova.skills.skill_injection import QualityInfo

logger = get_logger(__name__)

__all__ = ["VisibleSkill", "SkillView", "resolve_user_key", "build_turn_view"]

_SYSTEM_IDENTITIES = frozenset({"", "default", "system", "anonymous", "unknown"})

# registry 运行时的停用态（`SkillStatus` 的取值 + 库条目里出现过的同义写法）。
# 判停采白名单：新状态默认可见，改状态机时不会被静默拦掉。
_DISABLED_RUNTIME_STATUS = frozenset({"inactive", "disabled", "disabled_pending_review"})

# 生命周期终态（`SkillService.archive_skill` 写 `usage["state"]`）。
# `stale` 只是闲置标记，调得动，故不入表 —— 判停只认真归档。
_ARCHIVED_LIFECYCLE_STATES = frozenset({"archived"})


@dataclass
class VisibleSkill:
    """一条可见技能（manifest 条目 + 归属坐标）。"""

    name: str
    skill_id: str
    pool: str
    owner_key: str
    entry: dict = field(default_factory=dict)

    # ── duck-type 面：render_skill_catalog / schema 装配按 Skill 形状消费 ──
    @property
    def description(self) -> str:
        return str(self.entry.get("description") or "")

    @property
    def config(self) -> dict:
        return dict((self.entry.get("manifest") or {}).get("config") or {})

    @property
    def enabled(self) -> bool:
        """可调性 = manifest `enabled` 且运行时 `status` 不停用、生命周期未归档。

        三处判停落点各管一件事，任一判停即不可调：

        - `enabled`：运营面/评审闸的停用（`SkillService.enable_skill` 写它）；
        - `status`：`SkillRegistry` 运行时状态机（`set_skill_enabled` 写它）——
          此前 schema 段只看得到①条目的硬编码 True，这条判据形同虚设；
        - `usage.state`：生命周期扫描的归档态（`SkillService.archive_skill` 写它）。
          归档是最大破坏动作，工具面还留着它等于给 LLM 一个必然失败的工具。
        """
        if not bool(self.entry.get("enabled", True)):
            return False
        status = str(self.entry.get("status") or "").strip().lower()
        if status in _DISABLED_RUNTIME_STATUS:
            return False
        lifecycle = str((self.entry.get("usage") or {}).get("state") or "").strip().lower()
        return lifecycle not in _ARCHIVED_LIFECYCLE_STATES


class SkillView:
    """轮级可见集：name → VisibleSkill（已按就近优先合并）。"""

    def __init__(self, agent_id: str = ""):
        self.agent_id = str(agent_id or "")
        self.skills: Dict[str, VisibleSkill] = {}

    def invocable(self, name: str) -> bool:
        """该技能本轮是否可调（停用/待审的条目**在表里但不可调**）。

        判据落在**同一份 entry**上：`build_turn_view` 已按 identity 反查把 manifest
        的 `enabled`/`status` 合进来，此处不再各自查一遍（三个取数口统一到同一次
        反查，禁止各查各的）。
        """
        visible = self.skills.get(str(name or ""))
        if visible is None:
            return False
        return visible.enabled

    def provenance_for(self, name: str) -> Tuple[str, str]:
        v = self.skills.get(str(name or ""))
        if v is None:
            return ("agent", self.agent_id)
        return (v.pool, v.owner_key)

    def quality_for(self, name: str) -> Optional[QualityInfo]:
        v = self.skills.get(str(name or ""))
        if v is None:
            return None
        usage = v.entry.get("usage") or {}
        apps = int(usage.get("applications", 0) or 0)
        if apps <= 0:
            return None
        return QualityInfo(
            applications=apps,
            completions=int(usage.get("completions", 0) or 0),
            fallbacks=int(usage.get("fallbacks", 0) or 0),
        )

    def trust_for(self, name: str) -> Optional[str]:
        v = self.skills.get(str(name or ""))
        if v is None:
            return None
        return str(((v.entry.get("identity") or {}).get("trust") or {}).get("state") or "") or None

    def registry_view(self):
        """给 render_skill_catalog 等按 `.skills` dict 消费的函数用的替身。"""
        return types_namespace(self.skills)


def types_namespace(skills: Dict[str, VisibleSkill]):
    import types as _t

    return _t.SimpleNamespace(skills=skills)


def resolve_user_key(
    user_id: Optional[str] = None,
    channel_user_id: Optional[str] = None,
    channel: Optional[str] = None,
) -> Optional[str]:
    """请求身份 → 用户库键。渠道外部身份优先（ch: 命名空间），内部账号 u:；
    系统/匿名身份 → None（无用户库视图，agent+public）。非法字符由
    library_service 白名单兜底（抛错按 None 处理，不炸装配）。"""
    cu = str(channel_user_id or "").strip()
    ch = str(channel or "").strip()
    if cu and ch:
        try:
            return lib.normalize_user_key(f"ch:{ch}:{cu}")
        except ValueError:
            logger.warning("渠道用户键非法，降级无用户库视图: %r", cu)
            return None
    uid = str(user_id or "").strip()
    if uid.lower() in _SYSTEM_IDENTITIES:
        return None
    try:
        return lib.normalize_user_key(f"u:{uid}")
    except ValueError:
        logger.warning("内部用户键非法，降级无用户库视图: %r", uid)
        return None


def _runtime_status(skill: Any) -> str:
    """registry 运行时状态 → 视图判据用的字符串（枚举取 `value`）。

    `SkillRegistry.set_skill_enabled` 写的是 `skill.status`
    （`SkillStatus.ACTIVE/INACTIVE`），不经 manifest。底座条目必须把这份状态
    带上，否则"运行时停用一条手工技能"在工具面上看不出任何变化。
    """
    status = getattr(skill, "status", None)
    if status is None:
        return ""
    return str(getattr(status, "value", status) or "")


def build_turn_view(agent_id: str, user_key: Optional[str], registry_skills: Optional[dict] = None) -> SkillView:
    """三库合并视图（public → user → agent 逐层写入，同名后层遮蔽前层）。

    内置技能（create_default_skills 产物）**不落 manifest**——视图必须并入
    registry 运行时技能名，否则按视图过滤会把内置面误伤成不可见（装配
    红线）。registry 来源条目以 agent 层入表，同名 manifest 条目后写覆盖
    （账本/描述以 manifest 为准）。

    manifest 条目 enabled=False / 无 skill 键的脏行不进视图；公共库目录不存
    在时 get_library 首建空清单（首次装配可容忍一次 mkdir）。
    """
    view = SkillView(agent_id=agent_id)
    registry_entries: Dict[str, dict] = {}
    # ① registry 内置/运行时技能（agent 层底座）
    for name, raw in (registry_skills or {}).items():
        skill = raw[0] if isinstance(raw, tuple) and raw else raw
        key = str(name)
        entry = {
            "id": key,
            "name": key,
            "description": str(getattr(skill, "description", "") or ""),
            "status": _runtime_status(skill),
            "manifest": {"config": getattr(skill, "config", {}) if isinstance(getattr(skill, "config", None), dict) else {}},
        }
        registry_entries[key] = entry
        view.skills[key] = VisibleSkill(
            name=key, skill_id=key, pool=lib.POOL_AGENT,
            owner_key=agent_id, entry=entry,
        )
    # ② 三库 manifest（agent 库最后写入，同名覆盖 registry 底座条目）
    layers = [(lib.POOL_PUBLIC, "")]
    if user_key:
        layers.append((lib.POOL_USER, user_key))
    if agent_id:
        layers.append((lib.POOL_AGENT, agent_id))
    manifest_entries: Dict[str, dict] = {}
    disabled_names: set = set()
    for pool, owner in layers:
        try:
            service = lib.get_library(pool, owner)
        except ValueError as bad_key:
            logger.warning("库路由非法（pool=%s owner=%s）：%s", pool, owner, bad_key)
            continue
        except Exception:  # noqa: BLE001 - 单库故障不拖垮装配（其余层照常可见）
            logger.warning("技能库加载失败（pool=%s owner=%s）", pool, owner, exc_info=True)
            continue
        for _skill_id, entry in service.iter_skills():
            if not isinstance(entry, dict):
                continue
            # 查询键域是 **name**（schema 装配拿 name 问视图，见
            # `context/orchestrator.py` 的 `_view.invocable(n)`），而库条目按
            # `skill_id` 建键。此前的写法把两套键域混在一张表里：以 registry 键
            # （= name）建的①条目**硬编码 enabled=True**，于是自动技能
            # （`name ≠ skill_id`）停用后仍走①条目，质量熔断/信任过滤三闸同时
            # 恒开绿灯。收口方式：name 与 identity **同时登记**到同一份反查表，
            # 不新建第三份映射。
            entry = dict(entry)
            entry.setdefault("name", str(entry.get("name") or _skill_id))
            manifest_entries[str(entry["name"])] = entry
            if not bool(entry.get("enabled", True)):
                disabled_names.add(str(entry["name"]))

    for name, entry in manifest_entries.items():
        visible_entry = dict(registry_entries.get(str(name), {}))
        visible_entry.update(entry)
        view.skills[str(name)] = VisibleSkill(
            name=str(name),
            skill_id=str(entry.get("id") or name),
            pool=str(entry.get("pool_type") or lib.POOL_AGENT),
            owner_key=str(entry.get("owner_user_id") or "") or (agent_id if
                       str(entry.get("pool_type") or lib.POOL_AGENT) == lib.POOL_AGENT else ""),
            entry=visible_entry,
        )
    # 被 manifest 停用的名字：连 registry 底座条目一并从视图摘除——否则
    # ①那条硬编码 `enabled=True` 的底座会把停用又"救回来"（三闸恒开绿灯的根因）。
    for name in disabled_names:
        view.skills.pop(str(name), None)
    return view

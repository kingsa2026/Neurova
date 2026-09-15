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
from typing import Dict, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.skills import library_service as lib
from neurova.skills.skill_injection import QualityInfo

logger = get_logger(__name__)

__all__ = ["VisibleSkill", "SkillView", "resolve_user_key", "build_turn_view"]

_SYSTEM_IDENTITIES = frozenset({"", "default", "system", "anonymous", "unknown"})


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
        return bool(self.entry.get("enabled", True))


class SkillView:
    """轮级可见集：name → VisibleSkill（已按就近优先合并）。"""

    def __init__(self, agent_id: str = ""):
        self.agent_id = str(agent_id or "")
        self.skills: Dict[str, VisibleSkill] = {}

    def invocable(self, name: str) -> bool:
        return str(name or "") in self.skills

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
    # ① registry 内置/运行时技能（agent 层底座）
    for name, raw in (registry_skills or {}).items():
        skill = raw[0] if isinstance(raw, tuple) and raw else raw
        view.skills[str(name)] = VisibleSkill(
            name=str(name),
            skill_id=str(name),
            pool=lib.POOL_AGENT,
            owner_key=agent_id,
            entry={
                "id": str(name),
                "enabled": True,
                "description": str(getattr(skill, "description", "") or ""),
                "manifest": {"config": getattr(skill, "config", {}) if isinstance(getattr(skill, "config", None), dict) else {}},
            },
        )
    # ② 三库 manifest（agent 库最后写入，同名覆盖 registry 底座条目）
    layers = [(lib.POOL_PUBLIC, "")]
    if user_key:
        layers.append((lib.POOL_USER, user_key))
    if agent_id:
        layers.append((lib.POOL_AGENT, agent_id))
    for pool, owner in layers:
        try:
            service = lib.get_library(pool, owner)
        except ValueError as bad_key:
            logger.warning("库路由非法（pool=%s owner=%s）：%s", pool, owner, bad_key)
            continue
        except Exception:  # noqa: BLE001 - 单库故障不拖垮装配（其余层照常可见）
            logger.warning("技能库加载失败（pool=%s owner=%s）", pool, owner, exc_info=True)
            continue
        for key, entry in service.iter_skills():
            if not entry.get("enabled", True):
                continue
            view.skills[str(key)] = VisibleSkill(
                name=str(key),
                skill_id=str(entry.get("id") or key),
                pool=pool,
                owner_key=owner or (agent_id if pool == lib.POOL_AGENT else ""),
                entry=dict(entry),
            )
    return view

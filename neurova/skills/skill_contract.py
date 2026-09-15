# -*- coding: utf-8 -*-
"""技能契约层。

背景：三套技能模型并存——
- ``neurova.skill_system.Skill`` 运行时基类（身份字段 ``name``，子类可带 skill_id）
- ``neurova.skills.models.Skill`` dataclass（身份字段 ``id``）
- ``neurova.skill_system.skill_pool_manager.SkillMetadata``（身份字段 ``skill_id``；
  该孤岛 2026-09-15 已退役，第三形态以 pool 条目 dict 为兼容样本——解析器仍覆盖）
历史上消费方各写三跳 getattr 链，且链序在两处互相矛盾（agent_core/tool_executor
取 skill_id 优先；api/skill.py 取 id 优先）——同一对象可被记成两个身份，
是漏斗/trust 记账与 API 展示对不上的潜在活雷。

本模块是身份解析的**唯一权威**（静态纪律由
tests/unit/skills/test_skill_contract_wave_g.py 守卫）：

- 规范次序 ``skill_id → id → name → fallback``：与记账面（post_execute 的
  record_usage、execute_skill_tool 的漏斗 _funnel_id）对齐——账本是事实源，
  API 展示向账本看齐；
- 兼容 tuple/list 包装（class B ``(Skill, Path)`` 历史形态，解包委托
  compat.unpack_skill 既有单源）与 dict（manifest 行、pool metadata 行）；
- ``canonicalize_skill_identity`` 供注册边界调用：无身份的运行时对象补写
  ``skill_id``，已有身份**永不覆写**（注册键=工具名可能与账本 id 不同，
  覆写会撕裂血缘）。

刻意不做的事（对齐立项判断"收敛身份内核，保留执行外延"）：不合并三个类、
不新建 god-dataclass——执行语义（async execute/ToolSequenceSkill/SkillDocSkill）
留在 skill_system，字段漂移由本层吸收。
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable

__all__ = ["SkillCore", "resolve_skill_identity", "canonicalize_skill_identity"]


@runtime_checkable
class SkillCore(Protocol):
    """技能共同身份内核（结构化协议，三套模型天然成员满足，无需显式继承）。

    声明的是"可被安全读取的最小面"；新代码按此协议写消费逻辑，即与具体
    模型解耦。version/config 等仅部分模型具备的字段不进协议——读取仍走
    getattr 默认值（单跳不算漂移面）。
    """

    @property
    def name(self) -> str:  # pragma: no cover - 协议声明
        ...

    @property
    def description(self) -> str:  # pragma: no cover - 协议声明
        ...


def _field_str(obj: Any, key: str) -> str:
    """安全取字符串字段：非 str 值（脏数据/数字 id）视同缺失。"""
    try:
        value = getattr(obj, key, None)
    except Exception:  # noqa: BLE001 - property 抛错按缺失处理
        return ""
    if isinstance(value, str):
        return value.strip()
    return ""


def _dict_field(data: Dict[str, Any], key: str) -> str:
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ""


def resolve_skill_identity(skill: Any, fallback: str = "") -> str:
    """三套模型/元组包装/dict 的统一身份解析（唯一权威实现）。

    规范次序 skill_id → id → name → fallback。永不抛异常：None/标量/
    无字段对象一律落到 fallback（空则返回 ""，调用方自行决定丢弃或报错）。
    """
    if skill is None:
        return (fallback or "").strip()
    if isinstance(skill, (tuple, list)):
        from neurova.skill_system.compat import unpack_skill

        return resolve_skill_identity(unpack_skill(skill), fallback=fallback)
    if isinstance(skill, dict):
        for key in ("skill_id", "id", "name"):
            got = _dict_field(skill, key)
            if got:
                return got
        return (fallback or "").strip()
    for attr in ("skill_id", "id", "name"):
        got = _field_str(skill, attr)
        if got:
            return got
    return (fallback or "").strip()


def canonicalize_skill_identity(skill: Any, fallback: str = "") -> str:
    """注册边界归一化：保证对象携带显式 ``skill_id``，返回最终身份。

    - 已有非空 skill_id：原样返回（永不覆写）；
    - 仅有 id/name：补写 skill_id 实例属性（models.Skill 与运行时 Skill 均
      无 __slots__；dataclass 额外赋值安全）；setattr 失败（冻结对象）静默
      降级——身份仍可由 resolve 单跳取到，不阻断注册。
    """
    ident = resolve_skill_identity(skill, fallback=fallback)
    if not ident:
        return ""
    try:
        if _field_str(skill, "skill_id") == "" and not isinstance(skill, (dict, tuple, list)):
            setattr(skill, "skill_id", ident)
    except Exception:  # noqa: BLE001 - 只读对象降级，不炸注册
        pass
    return ident

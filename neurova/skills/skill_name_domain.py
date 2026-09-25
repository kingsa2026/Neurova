# -*- coding: utf-8 -*-
"""技能**名字域**的唯一判据（Issue #189 残留 · ADR 0019 留的口）。

## 为什么有这一层

ADR 0017 定的键域是：注册表按 `skill.name` 建键（`name` 是执行与展示域，模型
看到的工具名就是它），身份域是 `skill_id`。ADR 0019 把这条纪律钉在视图域，并
写明同名覆盖「出声不硬拒」——**存量库的迁移留给另单**，因为当场硬拒会让存量
装配失败。

存量库的形状是：`ai_tool` / `general_tool` 这类名字被多条不同身份的自动技能
（历史生成器遗留的 `synth_*`）共用。注册表只留得住先到者，其余**静默**消失，
工具面上少了几条却无从察觉（Issue #189 启动实测累计 10 次）。

## 口径：名字域 = 身份的函数

同一份 manifest 里，**同一 name 下身份不同的额外条目**必须拿到一个携带身份的
派生名——这样"注册表按 name 建键"与"每条身份都在工具面上"同时成立，不必翻转
主键（ADR 0017 已否掉"主键改成 identity"：那会让模型侧工具面漂移）。

判据只写这一份，三处消费同一份：

1. 存量库迁移：`migrateManifestNames` 就地收敛（幂等，不丢条目、不动血缘）；
2. 装配：`restore_market_skills_from_service` 装机前收敛，工具面不再丢技能；
3. 新写入：`SkillService` 写入口按本层取名，名字域不再退化。

命名风格按本项目约定（变量/函数 camelCase）；报告字典的键沿用既有可观测读数
的口径（`collision_count` 已被 `tests/unit/skills/test_skill_name_collision_recount.py`
钉住），不在此处另立一套。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set

__all__ = [
    "TOOL_NAME_MAX_LEN",
    "ALIASES_KEY",
    "isLegalToolName",
    "sanitizeName",
    "claimUniqueName",
    "migrateManifestNames",
    "recountManifestCollisions",
]

#: 工具名契约（OpenAI function calling：`^[a-zA-Z0-9_-]{1,64}$`）。派生名必须
#: 满足它，否则迁移把条目改成模型看不见的名字，等于换一种方式丢技能。
TOOL_NAME_MAX_LEN = 64
_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,%d}$" % TOOL_NAME_MAX_LEN)

#: 别名表键是索引而不是技能条目（`SkillService._ALIASES_KEY`），迁移必须跳过它，
#: 否则会把映射表当技能改名。
ALIASES_KEY = "_skill_aliases"

#: 派生名的兜底词干：原名字与身份都不可用时用它，保证结果仍是合法工具名。
_FALLBACK_STEM = "skill"


def isLegalToolName(name: Any) -> bool:
    """名字是否满足工具名契约（长度 + 字符集）。"""
    return bool(_TOOL_NAME_RE.match(str(name or "")))


def sanitizeName(raw: Any) -> str:
    """把任意存量名字归一成合法工具名的词干（可空——空即"原名字不可用"）。

    只做字符集与空白归一，不擅自截断到上限：截断归 `claimUniqueName` 管，
    因为那里才知道要给身份后缀留多少预算。
    """
    text = re.sub(r"[^a-zA-Z0-9_-]", "_", str(raw or "").strip())
    return re.sub(r"_+", "_", text).strip("_")


def claimUniqueName(base: str, identity: str, taken: Iterable[str]) -> str:
    """在 `taken` 之外为 `identity` 取一个名字：空闲则原样，被占则派生。

    返回值的三条不变量：

    - 未被占用的 `base` 原样返回（迁移对无关条目零 churn，也不改字形）；
    - 被占用时派生名**携带身份**（否则下次装配还会撞回同一个 name）；
    - 返回的派生名恒满足工具名契约（存量里的中文名/超长名也照样派生出合法名）。

    `identity` 缺席时**不伪造身份**（与 NL 合成臂同纪律）：原样返回，由调用方
    出声——静默改名与静默覆盖一样不可发现。

    **只判"占没占用"，不判字符集**：`本地版` / `Web Search` 这类名字是本仓既有
    的技能名（手工/市场技能），唯一就原样保留——顺手把它们改成 ASCII 是超出
    "键域唯一"范围的改动（教义第 5 条讲放大视角，但改名字形属于另一件事）。
    字符集约束只作用在**派生名**上：派生名要进工具清单，必须合法。
    """
    occupied: Set[str] = {str(x) for x in (taken or ())}
    text = str(base or "")
    if text.strip() and text not in occupied:
        return text

    ident = sanitizeName(identity)
    if not ident:
        return text

    stem = sanitizeName(base) or _FALLBACK_STEM
    suffix = "_%s" % ident
    budget = TOOL_NAME_MAX_LEN - len(suffix)
    if budget < 1:
        # 身份本身就很长：优先保住身份（名字是身份的派生物，反过来保不住身份
        # 的派生名没有意义），截到上限以内。
        return ident[:TOOL_NAME_MAX_LEN]

    candidate = "%s%s" % (stem[:budget], suffix)
    ordinal = 1
    while candidate in occupied:
        tag = "_%d" % ordinal
        keep = TOOL_NAME_MAX_LEN - len(suffix) - len(tag)
        if keep < 1:
            candidate = ("%s%s" % (ident, tag))[:TOOL_NAME_MAX_LEN]
        else:
            candidate = "%s%s%s" % (stem[:keep], suffix, tag)
        ordinal += 1
        if ordinal > len(occupied) + 2:  # 有界：占用集有限，正常数轮即收敛
            return ("%s_%d" % (ident, ordinal))[:TOOL_NAME_MAX_LEN]
    return candidate


def _iterEntries(payload: Dict[str, Any]):
    """按 manifest 原始顺序遍历技能条目（别名表与非法行不算条目）。"""
    for key, entry in (payload or {}).items():
        if key == ALIASES_KEY or not isinstance(entry, dict):
            continue
        yield key, entry


def migrateManifestNames(payload: Dict[str, Any]) -> Dict[str, Any]:
    """就地收敛一份 manifest 的名字域，返回迁移报告（幂等）。

    顺序即口径：先到者留住原名字，其后同 name 不同身份的条目依次派生携带身份
    的名字。身份（`id`/`skill_id`）、血缘（`identity`/`version_history`）、
    别名表与其余字段一概不动——迁移只改"名字"这一处键值域的取值。
    """
    renamed: List[Dict[str, Any]] = []
    taken: Set[str] = set()
    for key, entry in _iterEntries(payload):
        identity = str(entry.get("id") or entry.get("skill_id") or key or "")
        base = str(entry.get("name") or identity)
        claimed = claimUniqueName(base, identity, taken)
        if claimed != base:
            entry["name"] = claimed
            renamed.append({"id": identity, "from": base, "to": claimed})
        taken.add(str(claimed))
    return {"renamed_count": len(renamed), "renamed": renamed}


def recountManifestCollisions(payload: Dict[str, Any]) -> Dict[str, Any]:
    """复算一份 manifest 上的同名覆盖（同 name 不同身份的额外条目数）。

    口径与 `SkillRegistry._warn_on_name_collision` 一致：同一 name 下先到者
    留得住，其余每个记一次覆盖——这正是"工具面上少了几条"的可观测读数。
    """
    by_name: Dict[str, List[str]] = {}
    for key, entry in _iterEntries(payload):
        identity = str(entry.get("id") or key)
        by_name.setdefault(str(entry.get("name") or identity), []).append(identity)

    collisions: List[Dict[str, Any]] = []
    total = 0
    for name, identities in sorted(by_name.items()):
        unique = sorted(set(identities))
        if len(unique) <= 1:
            continue
        total += len(unique) - 1
        collisions.append({"name": name, "resident": unique[0], "shadowed": unique[1:]})
    return {"collision_count": total, "collisions": collisions}


def applyToManifestFile(path: Any) -> Optional[Dict[str, Any]]:
    """把迁移落到磁盘上的一份 manifest（原子替换），返回报告；无改动返回 None。

    供运维复算/迁移入口（`scripts/diagnostics/skill_name_collisions.py --apply`）
    使用。落盘走"临时文件 + `os.replace`"：写一半崩溃不得让技能库清零。
    """
    import json
    import os
    import tempfile
    from pathlib import Path

    manifest = Path(path)
    if not manifest.exists():
        return None
    payload = json.loads(manifest.read_text(encoding="utf-8") or "{}")
    if not isinstance(payload, dict):
        return None
    report = migrateManifestNames(payload)
    if not report["renamed_count"]:
        return report
    fd, tmp_path = tempfile.mkstemp(dir=str(manifest.parent), prefix="manifest_", suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, manifest)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return report

"""本体语义版本（B12 L8，升级计划 §12.9）：semver 判定/比较/推进。

规则：破坏性变更＝major、增术语＝minor、修标签＝patch；
存量 `vN` 形状不是 semver（只读兼容），新登记走 semver。
"""

from __future__ import annotations

import re

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def isSemver(version: str) -> bool:
    return bool(_SEMVER.match(str(version or "").strip()))


def _parts(version: str) -> tuple:
    match = _SEMVER.match(str(version or "").strip())
    if not match:
        raise ValueError("版本 %r 不是 semver 形状（X.Y.Z）" % version)
    return tuple(int(g) for g in match.groups())


def compareVersions(left: str, right: str) -> int:
    """left < right ⇒ 负数；相等 ⇒ 0；大于 ⇒ 正数。"""
    lp, rp = _parts(left), _parts(right)
    return (lp > rp) - (lp < rp)


def bumpVersion(version: str, kind: str) -> str:
    """按变更种类推进：major（破坏性）/ minor（增术语）/ patch（修标签）。"""
    major, minor, patch = _parts(version)
    if kind == "major":
        return "%d.0.0" % (major + 1)
    if kind == "minor":
        return "%d.%d.0" % (major, minor + 1)
    if kind == "patch":
        return "%d.%d.%d" % (major, minor, patch + 1)
    raise ValueError("未知版本推进种类 %r（有效值: major / minor / patch）" % kind)

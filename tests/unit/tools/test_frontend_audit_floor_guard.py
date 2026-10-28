# -*- coding: utf-8 -*-
"""前端依赖树（`NeurUI`）的修复下界守卫——`npm audit` 之前先把「顶不顶得到」钉住。

背景（PR #369 构建 `cnb-9jl-1k5lkat1o#005`）：`frontend` 腿第一步
`cd NeurUI && npm audit --audit-level=high` 红在 `undici 7.0.0 - 7.30.0`。
锁里是 7.29.1，而 `overrides` 写的是 `"undici": "^7.29.1"`——**区间下界恰好等于
锁里的值**，重跑 `npm install` 只会原地复刻 7.29.1，永远落不到 7.30.1。
与 `tools/npx-runtime` 侧已被咬住的那条同一根因（父包 `undici ^7.0.0` 顶不到修复版、
只能由 `overrides` 顶替），只是那侧的顶替写法用了精确版本，这侧用了 `^`。

故本守卫不吃「npm audit 红了再改」那一套，而是把两件可由本仓复算的事变成判据：

1. 每个登记的包 → 修复下界，锁里**全部**载体条目都 ≥ 下界（含嵌套形态）；
2. `overrides` 那条必须是**精确版本**：用 `^`/`~` 之类的区间时，下界一旦等于锁内现值，
   顶替就自我失效（本单的形态）——区间不报错的唯一写法是让下界高于现值，
   而那是「把锁里的值抄进 overrides」，下次公告一来又原地不动。

新公告仍由 `npm audit` 实扫发现，发现后在 `_KNOWN_FLOORS` 与 `_OVERRIDE_FLOORS`
各追加一条；本类只防回退（与 `test_npx_runtime_pinning` 的同名类同口径）。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

RULE_ROOT = Path(__file__).resolve().parents[3]
FRONTEND = RULE_ROOT / "NeurUI"


def _read_json(path: Path) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def releaseTuple(version: str) -> tuple:
    """把版本串归一成可比元组：`2.0.0-1` 是"2.0.0 之后的第一个预发布"。"""
    core, _, tail = version.partition("-")
    nums = tuple(int(p) for p in core.split("."))
    return nums + (0 if not tail else 1,)


#: 包名 → (修复下界, CVE/公告, 说明)。前端树里每条登记都必须是**已修**的下界。
_KNOWN_FLOORS = {
    "undici": (
        "7.30.1",
        "GHSA-4qv8-2p9j-2685 / GHSA-f72v-6w45-q472 / GHSA-xjj6-f33q-929c",
        "EventSource 解析器无界内存 DoS / 非小写算法 token 绕过 SRI / "
        "过量 content-encoding 未捕获异常 DoS",
    ),
}

#: 必须在 `overrides` 里被顶替的包（父包声明区间顶不到修复版，靠 install 抬不动）。
_REQUIRED_OVERRIDES = set(_KNOWN_FLOORS)


def _carriers(packages: dict, name: str) -> dict:
    """同名包在前端树里的**全部**落点（`node_modules/<包>` 与 `<父>/node_modules/<包>`）。"""
    suffix = f"/node_modules/{name}"
    return {
        key: entry
        for key, entry in packages.items()
        if key == f"node_modules/{name}" or key.endswith(suffix)
    }


class TestFrontendLockIsAtOrAboveCveFloors:
    def test_lock_carries_every_registered_floor(self):
        lock = _read_json(FRONTEND / "package-lock.json")
        packages = lock.get("packages") or {}
        assert len(packages) > 100, (
            f"前端锁解析出 {len(packages)} 条目——锁文件被换掉或结构变了，本判据的域不成立")
        problems = []
        for name, (floor, advisory, note) in _KNOWN_FLOORS.items():
            carriers = _carriers(packages, name)
            if not carriers:
                # 承载者被整体摘除是合格形态（不再受该公告影响），不报红。
                continue
            for key, entry in carriers.items():
                version = entry.get("version", "")
                if releaseTuple(version) >= releaseTuple(floor):
                    continue
                problems.append(
                    f"{key}@{version} 低于 {advisory} 的修复下界 {floor}——{note}。\n"
                    "    处置：在 NeurUI 改 overrides 为精确版本后重跑 "
                    "`npm install --package-lock-only --ignore-scripts`，不要手改锁里的版本号。"
                )
        assert not problems, "\n  ".join(["前端依赖树里出现已登记公告的未修版本:"] + problems)

    def test_registered_floors_are_the_ones_npm_audit_sees(self):
        """登记的每个包都必须在树里真的存在——空账就等于「绿了，判据却空了」。"""
        lock = _read_json(FRONTEND / "package-lock.json")
        packages = lock.get("packages") or {}
        missing = [name for name in _KNOWN_FLOORS if not _carriers(packages, name)]
        assert not missing, (
            f"登记的包在锁里一条落点都找不到: {', '.join(missing)}\n"
            "  确属上游把承载者摘掉了，须同步删掉 _KNOWN_FLOORS 与 _REQUIRED_OVERRIDES 的条目并写明理由；\n"
            "  只想让它变绿而把登记行删掉，正是本判据要拦的形态。"
        )


class TestFrontendOverridesAreExactVersions:
    def test_required_overrides_exist(self):
        pkg = _read_json(FRONTEND / "package.json")
        overrides = pkg.get("overrides") or {}
        missing = sorted(_REQUIRED_OVERRIDES - set(overrides))
        assert not missing, (
            f"overrides 缺 {', '.join(missing)}——父包声明区间顶不到修复版，"
            "缺这条顶替就只能停在有公告的版本上（前端 audit 第一步即红）"
        )

    def test_override_values_are_exact_and_reach_the_floor(self):
        """顶替值必须是精确版本号，且 ≥ 登记下界。

        用 `^`/`~` 的写法在本单里曾经"看着像已经顶了"：`^7.29.1` 的下界正好等于锁里
        的 7.29.1，重跑 install 原地不动。区间写法要么自我失效（下界 == 现值），
        要么把锁里的值抄进清单（下界 > 现值），两种都把「顶替」变成一句空话。
        """
        pkg = _read_json(FRONTEND / "package.json")
        overrides = pkg.get("overrides") or {}
        problems = []
        for name in sorted(_REQUIRED_OVERRIDES):
            value = overrides.get(name)
            if not isinstance(value, str):
                continue
            if not value[:1].isdigit():
                problems.append(
                    f"overrides.{name} = {value!r} 是区间而非精确版本——"
                    "区间下界若等于锁内现值，顶替不产生任何解析变化（npm install 原地复刻）"
                )
                continue
            floor = _KNOWN_FLOORS[name][0]
            if releaseTuple(value) < releaseTuple(floor):
                problems.append(f"overrides.{name} = {value!r} 低于登记下界 {floor}")
        assert not problems, "\n  ".join(["前端 overrides 顶不住已登记公告:"] + problems)

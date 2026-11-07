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

新公告仍由 `npm audit` 实扫发现，发现后在 `_KNOWN_FLOORS` 追加一条下界，
重解析落不到位时再进 `_REQUIRED_OVERRIDES`；本类只防回退（与 `test_npx_runtime_pinning` 的同名类同口径）。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

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
    # axios `^1.16.0` 的真实解析点（唯一载体，无嵌套副本）。
    # 1.16.1 用 `value instanceof Array` 校验 `sensitiveHeaders`：跨 realm 的数组
    # 该式为假，选项被静默换成空列表，调用方声明的自定义凭证头（API key 之类）
    # 因此会在跨域 302 上被带到攻击者目标。1.16.2 改回 `Array.isArray` 即根修。
    "follow-redirects": (
        "1.16.2",
        "CVE-2026-116689 / GHSA-mrwp-f3q8-3g9p",
        "跨 realm 的 sensitiveHeaders 被当成非法值丢弃，自定义凭证头随跨域重定向外泄",
    ),
}

#: 必须在 `overrides` 里被顶替的包（父包声明区间顶不到修复版，靠 install 抬不动）。
#: 刻意**不**取 `_KNOWN_FLOORS` 全集：`follow-redirects` 由 axios 的 `^1.16.0` 引入，
#: 该区间本身就含修复版 1.16.2，重解析即可落位，多加一条顶替只是把「能升级」变成
#: 「被钉死」。哪些包真的顶不到，由 `TestFloorsAreReachableFromDeclaredRanges` 复算——
#: 没被 overrides 覆盖的登记项，其引入区间必须真的容得下修复版，否则判红。
_REQUIRED_OVERRIDES = {"undici"}


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
                    "    处置：重跑 `npm install --package-lock-only --ignore-scripts` 让锁重解析；"
                    "重解析仍落不到位（引入区间容不下修复版）时才在 NeurUI 的 overrides 写精确版本。"
                    "不要手改锁里的版本号。"
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


def _declaredRanges(packages: dict, name: str) -> dict:
    """谁按什么区间引入了这个包 —— 取锁里 `dependencies` 等四个字段的声明原文。

    这是本档唯一不靠外部公告、也不靠 `overrides` 就能复算的事实：
    区间容不容得下修复版。容不下却又不写 `overrides`，`npm install` 只会原样留着旧版，
    而锁里那条「版本低于下界」的红要等到下次才有人看见。
    """
    fields = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
    found = {}
    for key, entry in packages.items():
        for field in fields:
            spec = (entry.get(field) or {}).get(name)
            if isinstance(spec, str):
                found[f"{key or '.'}.{field}"] = spec
    return found


def rangeAdmitsVersion(spec: str, version: str) -> bool:
    """区间是否容得下该版本。只认锁里实际出现的几种写法，其余一律判「容不下」。

    宁可判红：认不出的区间若默认放行，本判据就成了恒真断言。
    """
    spec = spec.strip()
    if spec in ("*", "latest", ""):
        return True
    target = releaseTuple(version)
    if spec[0].isdigit():
        return target == releaseTuple(spec)
    for prefix in ("^", "~", ">="):
        if spec.startswith(prefix):
            body = spec[len(prefix):]
            if not body[:1].isdigit():
                return False
            base = body.split(" ")[0]
            floorTuple = releaseTuple(base)
            if prefix == ">=":
                return target >= floorTuple
            if prefix == "~":
                return target >= floorTuple and target[:2] == floorTuple[:2]
            # `^`：主版本相同且不低于下界；0.x 线里 `^0.a.b` 的次版本也算边界。
            if floorTuple[0] != 0:
                return target >= floorTuple and target[0] == floorTuple[0]
            return target >= floorTuple and target[:2] == floorTuple[:2]
    return False


class TestFloorsAreReachableFromDeclaredRanges:
    """没写 `overrides` 的登记项，必须真的能被引入区间解析到修复版。

    `follow-redirects` 就是这一形态：axios 声明 `^1.16.0`，1.16.2 落在区间内，
    故本档处置是「锁内重解析」而不是「加一条 overrides 顶死」。
    哪天 axios 改成 `~1.16.0`，重解析就落不到 1.16.2，这条会红——那时才该进
    `_REQUIRED_OVERRIDES`，而不是让锁停在旧版、由 `npm audit` 事后发现。
    """

    def test_unoverridden_floors_are_inside_their_declared_ranges(self):
        packages = _read_json(FRONTEND / "package-lock.json").get("packages") or {}
        problems = []
        for name, (floor, advisory, _note) in _KNOWN_FLOORS.items():
            if name in _REQUIRED_OVERRIDES:
                continue
            ranges = _declaredRanges(packages, name)
            if not ranges:
                continue
            bad = {
                who: spec for who, spec in ranges.items()
                if not rangeAdmitsVersion(spec, floor)
            }
            if bad:
                problems.append(
                    f"{name} 的修复版 {floor}（{advisory}）不在引入区间内: {bad}——"
                    "重解析落不到位，须加进 _REQUIRED_OVERRIDES 用精确版本顶替"
                )
        assert not problems, "\n  ".join(["登记了下界却顶不到:"] + problems)

    def test_required_overrides_are_registered_floors(self):
        """顶替名单必须是登记项的子集——否则 `_KNOWN_FLOORS[name][0]` 取不到。"""
        stray = sorted(_REQUIRED_OVERRIDES - set(_KNOWN_FLOORS))
        assert not stray, f"_REQUIRED_OVERRIDES 里的 {stray} 没有对应的修复下界登记"

    @pytest.mark.parametrize(
        "spec, version, expected",
        [
            ("^1.16.0", "1.16.2", True),
            ("^1.16.0", "2.0.0", False),
            ("~1.16.0", "1.16.2", True),
            ("~1.16.0", "1.17.0", False),
            ("^7.25.0", "7.30.1", True),
            ("^0.3.0", "0.4.0", False),
            ("1.16.2", "1.16.2", True),
            (">=1.16.0", "1.16.2", True),
            ("latest", "1.16.2", True),
            ("workspace:*", "1.16.2", False),
        ],
    )
    def test_rangeMatcherIsNotVacuous(self, spec, version, expected):
        """反空转：认不出的写法必须判「容不下」，否则上面那条恒绿。"""
        assert rangeAdmitsVersion(spec, version) is expected

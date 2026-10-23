# -*- coding: utf-8 -*-
"""运行时 npx 包钉版本守卫（Issue #56 残留边界：供应链）。

问题（实跑确认）：

    npx -y @askjo/camofox-browser      # 不带版本号 = 每次解析最新版

这类调用在仓库里有多处（camofox 常驻服务、MCP 目录的 context7/dbhub、
共享配置默认模板的 filesystem server）。它们的共性风险：

1. **不可复现**：同一个 Neurova 版本在不同日期跑的是不同的第三方代码；
2. **无审计覆盖**：npx 现拉的包不进任何清单，pip-audit / npm audit /
   OSV 都看不到，而这些代码在生产路径上执行；
3. **无评审窗口**：上游发版（含回归/投毒）在用户机器上即时生效。

本守卫锁定"三处同源"契约：
    npx_runtime_registry.PINNED  ==  tools/npx-runtime/package.json
                                 ==  tools/npx-runtime/package-lock.json
以及"全库不得再出现裸包名 npx 调用"（防回潮）。

改一处漏改另一处会红——这正是升级流程要防的。
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
#: 扫描根单点（必须是模块级：函数内的局部名会被面自证棘轮解成动态值，那档就静默掉出它的面）。
NEUROVA = PROJECT_ROOT / "neurova"

from neurova.tool_layers.npx_runtime_registry import (  # noqa: E402
    PINNED,
    pinned_npx_args,
    pinned_spec,
    to_package_json_dependencies,
)


def _read_json(rel: str) -> dict:
    return json.loads(io.open(PROJECT_ROOT / rel, encoding="utf-8").read())


class TestRegistryIsSingleSourceOfTruth:
    def test_pinned_entries_are_exact_versions(self):
        """登记值必须是精确版本，不得是 ^ / ~ / latest 这类区间或浮动值。"""
        for pkg, ver in PINNED.items():
            assert re.fullmatch(r"\d+\.\d+\.\d+[\w.\-+]*", ver), (
                f"{pkg} 的登记版本 {ver!r} 不是精确版本——"
                "浮动范围会让锁文件失去意义（npx 仍会跑更新版）。"
            )

    def test_pinned_nonempty(self):
        assert PINNED, "登记表为空——运行时 npx 调用将失去版本来源"

    def test_pinned_spec_shape(self):
        for pkg, ver in PINNED.items():
            assert pinned_spec(pkg) == f"{pkg}@{ver}"

    def test_unregistered_package_raises(self):
        """未登记包必须炸——否则新增运行时拉包会悄悄绕过审计覆盖面。"""
        with pytest.raises(KeyError) as ei:
            pinned_spec("@evil/never-registered")
        assert "未登记" in str(ei.value)

    def test_pinned_npx_args_passes_through_rest(self):
        args = pinned_npx_args("@bytebase/dbhub", "--dsn", "postgres://x")
        assert args[0] == "-y"
        assert args[1] == pinned_spec("@bytebase/dbhub")
        assert args[2:] == ["--dsn", "postgres://x"]


class TestManifestMatchesLockfiles:
    """PINNED ↔ package.json ↔ package-lock.json 三者同源。"""

    def test_package_json_matches_registry(self):
        pkg = _read_json("tools/npx-runtime/package.json")
        assert pkg["dependencies"] == to_package_json_dependencies(), (
            "tools/npx-runtime/package.json 与 npx_runtime_registry.PINNED 不一致。\n"
            "升级流程见 npx_runtime_registry 模块 docstring：改 PINNED → 重生成锁。"
        )

    def test_lockfile_resolves_each_pinned_package(self):
        lock = _read_json("tools/npx-runtime/package-lock.json")
        packages = lock.get("packages") or {}
        for pkg, ver in PINNED.items():
            entry = packages.get(f"node_modules/{pkg}")
            assert entry is not None, (
                f"锁文件缺 {pkg}（运行时 npx 包不在审计覆盖面内）——"
                "在 tools/npx-runtime 重跑 npm install --package-lock-only --ignore-scripts"
            )
            assert entry.get("version") == ver, (
                f"{pkg} 锁里是 {entry.get('version')}，登记是 {ver}——"
                "改了 PINNED 但没重生成锁，npx 实际跑的还是旧版本。"
            )

    def test_lockfile_is_committed_not_ignored(self):
        """锁文件必须可入库：被 .gitignore 吞掉 = 门禁输入缺失。"""
        import subprocess

        r = subprocess.run(
            ["git", "check-ignore", "-q", "tools/npx-runtime/package-lock.json"],
            cwd=str(PROJECT_ROOT),
        )
        assert r.returncode != 0, (
            "tools/npx-runtime/package-lock.json 被 .gitignore 忽略——"
            "OSV 审计没有输入，运行时 npx 包又回到无人可见状态。\n"
            "需在 .gitignore 加 `!tools/npx-runtime/package-lock.json`。"
        )


class TestNoBareNpxCallsRemain:
    """全库不得再有 `npx -y <裸包名>`（防回潮到未钉版本形态）。"""

    # 允许出现裸包名的例外：文档/注释/测试夹具（它们是"描述"而非"调用"）
    _SKIP_DIRS = ("tests", "docs", ".git", "node_modules", "__pycache__")
    _PATTERN = re.compile(
        r'"-y"\s*,\s*"((?:@[\w.\-]+/)?[\w.\-]+)"\s*\]'
    )

    def test_no_unversioned_package_specs_in_source(self):
        offenders = []
        sources = [p for p in NEUROVA.rglob("*.py") if "__pycache__" not in p.parts]
        assert len(sources) > 500, (
            f"扫描面现读 {len(sources)} 档（根＝{NEUROVA}，本判据的域＝生产源码）——"
            "根被改窄时「没有裸包名」只是没在看代码")
        for py in sources:
            text = io.open(py, encoding="utf-8", errors="replace").read()
            for m in self._PATTERN.finditer(text):
                spec = m.group(1)
                if spec.startswith("-") or "@" in spec.lstrip("@"):
                    continue
                # 命中形如 ["-y", "pkg"] 的裸包名
                if "/" in spec or re.match(r"^[a-z]", spec):
                    offenders.append(f"{py.relative_to(PROJECT_ROOT)}: npx args 裸包名 {spec!r}")
        assert not offenders, (
            "发现未钉版本的 npx 调用（每次解析 latest = 不可复现 + 无审计覆盖）:\n  "
            + "\n  ".join(offenders)
            + "\n改用 npx_runtime_registry.pinned_npx_args(pkg, ...)。"
        )


class TestNoKnownVulnerableRuntimePackages:
    """运行时审计树里不得有已知 CVE 载体（Issues #56 残留边界 / #160 起为常驻守卫）。

    为什么单列一类、不塞进上面的"三者同源"：同源只锁"改一处漏改另一处"，
    对"三处一致地停在一个有漏洞的版本"完全无感——CVE-2026-33532（`yaml` 栈溢出，
    CVSS 4.3）正是这个形态：`PINNED` 里没有 `yaml`（它不属"运行时 npx 现拉"面），
    `package.json` 里也没有，只有锁文件深处那条 **传递依赖** 停在 2.0.0-1。
    故判据落在锁文件上，逐条登记「包 → 修复下界 → 引入链」，真跑断言。

    口径说明（刻意不写成"不许出现任何漏洞"）：本仓无法在此复算 OSV 公告，
    能机器验证的是「**已登记 CVE 的修复下界**没有被回退」。新增 CVE 仍由
    `scripts/ci/osv_audit.py` 实扫发现，发现后在此追加一条——即本类是防回退闸门。
    """

    # 包名 → (修复下界, 允许的引入链, CVE, 说明)
    _KNOWN_FLOORS = {
        "yaml": ("2.8.3", ("node_modules/swagger-jsdoc",), "CVE-2026-33532", "CVE-2026-33532"),
    }

    def _release_tuple(self, version: str) -> tuple:
        """把版本串归一成可比元组：`2.0.0-1` 是"2.0.0 之后的第一个预发布"。"""
        core, _, tail = version.partition("-")
        nums = tuple(int(p) for p in core.split("."))
        return nums + (0 if not tail else 1,)

    def test_locked_yaml_is_at_or_above_cve_floors(self):
        lock = _read_json("tools/npx-runtime/package-lock.json")
        packages = lock.get("packages") or {}
        problems = []
        for name, (floor, chains, cve, note) in self._KNOWN_FLOORS.items():
            entry = packages.get(f"node_modules/{name}")
            if entry is None:
                # 承载者被整体摘除（依赖被上游换掉）也是合格形态，不报红。
                continue
            version = entry.get("version")
            if self._release_tuple(version) < self._release_tuple(floor):
                problems.append(
                    f"{name}@{version} 低于 {cve} 的修复下界 {floor}——{note}。\n"
                    f"    引入链: {' → '.join(chains)}\n"
                    "    处置：不要手改锁文件里的版本号（父包用的是精确版本声明，"
                    "真实解析仍是旧版），改为在 tools/npx-runtime 重跑 "
                    "`npm install --package-lock-only --ignore-scripts` 让解析结果自然抬升。"
                )
        assert not problems, "\n  ".join(["运行时审计树里出现已登记 CVE 的未修版本:"] + problems)

    def test_no_cve_has_been_regressed_by_downgrade(self):
        """CVE 修复不得被"降级"悄悄回退（本单硬要求）。"""
        lock = _read_json("tools/npx-runtime/package-lock.json")
        entry = (lock.get("packages") or {}).get("node_modules/yaml")
        if entry is None:
            pytest.skip("yaml 已不在这棵依赖树里——回退问题不适用")
        assert self._release_tuple(entry["version"]) >= self._release_tuple("2.8.3"), (
            f"yaml@{entry['version']} 相对修复版本 2.8.3 属降级——"
            "本仓只接受抬升到修复版或整体摘除，不接受回退到有漏洞的版本。"
        )


class TestUndiciDecompressCarrierIsAtTheCveFloor:
    """`undici` decompress 拦截器**受影响区间**的版本门禁（CVE-2026-87029）。

    为什么单列一类、不并进上面的 `_KNOWN_FLOORS`：那些钉的是「修复下界」，而本条
    的修复版**不在本仓可走的那条线上**——7.x 线唯一的补丁版 7.30.1 恰好仍是公告
    区间的上界（`7.15.0–7.30.1`，后果是解压输出经 zlib 回调异步逃逸的异常终止 Node
    进程）；再往上的修复只存在于 8.x 大版本，而引入方 `@upstash/context7-mcp`
    精确声明 `undici ^7.0.0`，越线的锁是拼出来的绿。故门禁钉的不是「到了某个下界」
    （那会在锁停在 7.29.1 时照样绿），而是**锁里的版本离开了受影响区间的下沿**，
    即把「不得降级回 7.15.0 以下」这件事机器化。

    `undici` 还是 **`PINNED` 之外的传递依赖**，版本由上游声明 + 锁共同决定，谁都不在
    `PINNED` 里看着它。故第二条判据钉「声明与锁在同一条主版本线上」——防「锁被手抬到
    8.x、而声明区间其实仍是 ^7」（那种锁装不出来）。
    """

    #: CVE-2026-87029 公告区间的**下沿**：低于它即已躲开本条。
    _AFFECTED_FLOOR = "7.15.0"

    def _releaseTuple(self, version: str) -> tuple:
        """与 `TestNoKnownVulnerableRuntimePackages._release_tuple` 同口径的版本比较。"""
        core, _, tail = version.partition("-")
        nums = tuple(int(p) for p in core.split(".")[:3])
        return nums + (0 if not tail else 1,)

    def _undiciEntry(self) -> dict:
        lock = _read_json("tools/npx-runtime/package-lock.json")
        entry = (lock.get("packages") or {}).get("node_modules/undici")
        if entry is None:
            pytest.skip("undici 已不在这棵依赖树里——压缩面不适用")
        return entry

    def test_locked_undici_left_the_cve_affected_range(self):
        version = self._undiciEntry()["version"]
        assert self._releaseTuple(version) >= self._releaseTuple(self._AFFECTED_FLOOR), (
            f"undici@{version} 落在 CVE-2026-87029 的受影响区间下沿 "
            f"{self._AFFECTED_FLOOR} 之下——decompress 拦截器里异步逃逸的未捕获异常"
            "会终止 Node 进程。\n"
            "   引入链: node_modules/@upstash/context7-mcp → undici ^7.0.0\n"
            "   处置：在 tools/npx-runtime 重生成锁抬回 7.x 补丁版，不接受降级。"
        )

    def test_context7_declared_range_is_consistent_with_the_lock(self):
        """锁里的人为抬版必须仍落在引入方声明的同一条主版本线上（否则装不出来）。"""
        lock = _read_json("tools/npx-runtime/package-lock.json")
        declared = ((lock.get("packages") or {})
                    .get("node_modules/@upstash/context7-mcp", {})
                    .get("dependencies", {})
                    .get("undici"))
        assert declared, (
            "@upstash/context7-mcp 不再声明 undici——本判据的引入链前提没了，"
            "请先复核 undici 是否仍在这棵审计树里，再决定删判据还是改链。"
        )
        # 只认 `^7.0.0` / `~7.0.0` / 精确版这类单区间声明：取声明下界与锁里的版本比对
        # 主版本号，并确认下界不高于锁里的版本。
        lower = declared.lstrip("^~>=< ").strip()
        locked = self._undiciEntry()["version"]
        assert self._releaseTuple(lower)[0] == self._releaseTuple(locked)[0], (
            f"引入方声明 {declared!r} 与锁里 {locked} 不在同一条主版本线上——"
            "锁是越线拼出来的（大版本越线须先改声明，不能只改锁）。"
        )
        assert self._releaseTuple(lower) <= self._releaseTuple(locked), (
            f"引入方声明 {declared!r} 的下界高于锁里 {locked}——"
            "锁里的版本与声明区间不自洽。"
        )

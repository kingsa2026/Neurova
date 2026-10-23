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
    """`undici` decompress 拦截器的版本下界门禁（CVE-2026-87029）。

    为什么单列一类、不并进上面的 `_KNOWN_FLOORS`：这里要钉的不只是「不比某版低」。
    `undici` 是 **`PINNED` 之外的传递依赖**（`@upstash/context7-mcp` → `undici ^7.0.0`），
    它的版本由上游声明区间 + 锁文件共同决定，谁都不在 `PINNED` 里看着它。而这条 CVE
    的载体恰好是「运行起来才生效」的压缩面：7.15.0–7.30.0 / 8.0.0–8.12.1 的
    decompress 把解压后的数据经 zlib 流回调交给下游，下游按设计抛出（例：dump 拦截器
    响应超过 maxSize）时异常从回调里**异步**逃逸，成为未捕获异常并终止 Node 进程。

    故判据两件事：① 锁里的版本在修复下界之上；② 引入方的声明区间仍然允许它——
    后者防的是「锁被手改成高版、而声明区间其实已经变窄」这种拼出来的绿。
    """

    #: OSV 公告给出的首个修复版；7.x 线之上还有 8.x 线，本仓只走 7.x。
    _FIXED_FLOOR = "7.30.1"

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

    def test_locked_undici_is_at_or_above_the_cve_floor(self):
        version = self._undiciEntry()["version"]
        assert self._releaseTuple(version) >= self._releaseTuple(self._FIXED_FLOOR), (
            f"undici@{version} 低于 CVE-2026-87029 的修复下界 {self._FIXED_FLOOR}——"
            "decompress 拦截器里异步逃逸的未捕获异常会终止 Node 进程。\n"
            "   引入链: node_modules/@upstash/context7-mcp → undici ^7.0.0\n"
            "   处置：在 tools/npx-runtime 重生成锁把它抬到修复版，不接受降级。"
        )

    def test_context7_declared_range_still_admits_the_fix(self):
        """抬版不得靠越界：引入方声明的区间必须允许修复版（否则锁是拼出来的）。"""
        lock = _read_json("tools/npx-runtime/package-lock.json")
        declared = ((lock.get("packages") or {})
                    .get("node_modules/@upstash/context7-mcp", {})
                    .get("dependencies", {})
                    .get("undici"))
        assert declared, (
            "@upstash/context7-mcp 不再声明 undici——本判据的引入链前提没了，"
            "请先复核 undici 是否仍在这棵审计树里，再决定删判据还是改链。"
        )
        # 只认 `^7.0.0` / `~7.0.0` / 精确版这类单区间声明；取区间下界判定即可
        # （`^7.0.0` 的下界 7.0.0 只要不高于修复版，修复版就在区间内）。
        lower = declared.lstrip("^~>=< ").strip()
        assert self._releaseTuple(lower) <= self._releaseTuple(self._FIXED_FLOOR), (
            f"引入方声明 {declared!r} 的下界已高于修复版 {self._FIXED_FLOOR}——"
            "锁里的版本与声明区间不自洽。"
        )


class TestNonPipAuditTreesStayAtTheAdvisoryFloors:
    """非 pip 两片审计树的版本下界门禁（Rust 桌面壳 + npx 运行时树）。

    为什么单列一类：`TestNoKnownVulnerableRuntimePackages` 只登记**子依赖被父包精确
    声明卡住**的那一类载体（yaml），`TestUndiciDecompressCarrierIsAtTheCveFloor` 只钉
    undici 一支。两片树里其余的包没有任何"抬版不许回退"的判据——本类补上。

    判据刻意只钉**修复下界**，不钉具体版本：公告入库后 `scripts/ci/osv_audit.py` 会
    先报红发现，发现者在此登记一条下界；此后谁把锁改回有漏洞的版本就立刻红。
    这与 `docs/05-reports/dependency-cve-ledger.md` 的 allowlist 纪律同形：
    能升级修掉的一律升级，不登记豁免。
    """

    #: 包名 → (修复下界, 公告 id 串, 载体说明)
    npm_floors = {
        "@modelcontextprotocol/server": (
            "2.3.0",
            "GHSA-46jr-4wx8-v453 / GHSA-jm63-cq47-j5jp / GHSA-rvq5-wwqv-78pq",
            "MCP server SDK：单请求内存耗尽、跨客户端串话、bearer 未校验受众",
        ),
        "hono": (
            "4.13.11",
            "GHSA-5r4p-p66f-jhc7",
            "serveStatic 二次解码绕过路由中间件",
        ),
        "ip-address": (
            "10.7.4",
            "GHSA-rxp7-6hxx-x8q5",
            "Address6 区段标识二次扫描（O(N²)）",
        ),
    }

    #: crate 名 → 同上
    cargo_floors = {
        "rustls": (
            "0.23.46",
            "RUSTSEC-2026-0346/0347/0348/0349",
            "会话密钥经 Debug 泄漏、ECH 拒后外发缓冲数据、Brotli 证书 1 GiB 预分配、未认证降级",
        ),
        "rustls-webpki": (
            "0.103.16",
            "RUSTSEC-2026-0382",
            "接受含被吊销 emSign 中间人的证书路径",
        ),
        # 0.26.x 是"兼容包"：不含独立信任库，只 re-export 1.x 的根，故判据落在 1.x 线上
        # （两条都钉会把 0.26.11 这条 re-export 当成漏洞载体）。
        "webpki-roots 1": (
            "1.0.10",
            "RUSTSEC-2026-0381",
            "内置根证书集含被吊销的 emSign 根",
        ),
    }

    def _parseVersion(self, version: str) -> tuple:
        core, _, tail = version.partition("-")
        parts = tuple(int(p) for p in core.split(".")[:3])
        return parts + (0 if not tail else 1,)

    def test_lockedNpmPackagesAreAtOrAboveTheAdvisoryFloors(self):
        packages = _read_json("tools/npx-runtime/package-lock.json").get("packages") or {}
        problems = []
        for name, (floor, advisories, note) in self.npm_floors.items():
            entry = packages.get(f"node_modules/{name}")
            if entry is None:
                # 承载者被整体摘除（依赖被上游换掉）也是合格形态，不报红。
                continue
            version = entry.get("version")
            if self._parseVersion(version) < self._parseVersion(floor):
                problems.append(
                    f"{name}@{version} 低于 {advisories} 的修复下界 {floor}——{note}。\n"
                    "    处置：抬协议方包（PINNED）或重生成锁，不要手改版本号后不回写声明。"
                )
        assert not problems, "\n  ".join(["运行时审计树里出现已登记公告的未修版本:"] + problems)

    def test_lockedCratesAreAtOrAboveTheAdvisoryFloors(self):
        text = io.open(PROJECT_ROOT / "NeurUI/src-tauri/Cargo.lock", encoding="utf-8").read()
        problems = []
        for name, (floor, advisories, note) in self.cargo_floors.items():
            # 键可带版本线后缀（`webpki-roots 1` → crate `webpki-roots`，只认 1.x 线）。
            crate, _, line = name.partition(" ")
            found = re.findall(
                r'\[\[package\]\]\nname = "%s"\nversion = "([^"]+)"' % re.escape(crate), text
            )
            if line:
                found = [v for v in found if v.split(".")[0] == line]
            if not found:
                continue
            for version in found:
                if self._parseVersion(version) < self._parseVersion(floor):
                    problems.append(
                        f"{name}@{version} 低于 {advisories} 的修复下界 {floor}——{note}。"
                    )
        assert not problems, "\n  ".join(["桌面壳 crate 树里出现已登记公告的未修版本:"] + problems)

    def test_cargoLockChecksumsMatchTheRegistry(self):
        """锁里手改的 version 必须与 checksum 同源——否则 `cargo build` 直接校验失败。"""
        #: crate → (版本, crates.io 公布的 sha256)。版本被抬而 checksum 没跟着改，
        #: 就是"锁看着修了、实际装不上"的形态；这条钉住两者同源。
        expected = {
            "rustls": ("0.23.46", "48e13bd8c0e9365c43cfa5c9e8f9ad49d3c8444926c9aac819e0e4dc503c8fdf"),
            "rustls-webpki": ("0.103.16", "4443b1b6d39d7c663139942cc4558262562d2c84123bb6282ef177009ca8b281"),
            "webpki-roots": ("1.0.10", "1c1c8e20c8a38fc7d65abfe74eb7280e4aa667e8eec8bc84996d2874810748d9"),
        }
        text = io.open(PROJECT_ROOT / "NeurUI/src-tauri/Cargo.lock", encoding="utf-8").read()
        problems = []
        for name, (version, checksum) in expected.items():
            # 精确到版本：同名的 0.26.x 兼容包不算本判据的载体（它 re-export 1.x 的根）。
            pattern = (
                r'\[\[package\]\]\nname = "%s"\nversion = "%s"\nsource = "[^"]+"\n'
                r'checksum = "([^"]+)"' % (re.escape(name), re.escape(version))
            )
            match = re.search(pattern, text)
            if match is None:
                problems.append(f"{name}@{version} 不在 Cargo.lock 里——已登记的修复版被摘掉了")
                continue
            lockedSum = match.group(1)
            if lockedSum != checksum:
                problems.append(
                    f"{name}@{version} 的 checksum 与 registry 公布值不一致（{lockedSum[:16]}… != "
                    f"{checksum[:16]}…）——版本抬了、校验和没跟着改，构建会直接失败"
                )
        assert not problems, "\n  ".join(["Cargo.lock 与 registry 不同源:"] + problems)

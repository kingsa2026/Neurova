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
        # PR #369 构建 cnb-p98-1k5la1aci#008 实扫命中（osv_audit.py 退出 1）：
        # 一个压缩帧 + 尾随字节即可让进程未捕获异常退出（HIGH，7.5），无鉴权、无路由要求。
        # 树里有两份载体：express@5.2.1 → ^2.2.1 解析到 2.3.0；
        # @bytebase/dbhub → express@4.22.3 → ~1.20.5 解析到 1.20.8。两条都要抬。
        "body-parser": (
            "1.20.9",
            ("node_modules/express", "node_modules/@bytebase/dbhub/node_modules/express"),
            "GHSA-27r3-jxmh-p828",
            "两条声明线各有修复版：2.x 线 2.4.0，1.x 线 1.20.9",
        ),
        # 2026-10-23 一组四条（low/low/medium/medium，上游同日发布）：scheme 注入、
        # 百分号编码的 scheme 伪造、WHATWG host 归一化导致的 host 混淆、相对引用
        # 路径等价。开的是区间，不是单条 id——只销一条等于换个 id 重报。
        # 载体是 ajv 8.20.0 声明 `fast-uri ^3.0.1` 解析到的 3.1.8，修复版 3.1.9。
        "fast-uri": (
            "3.1.9",
            ("node_modules/ajv",),
            "GHSA-333x-w4r6-6crp / GHSA-w74x-v6f9-j3xg / "
            "GHSA-wjr9-j795-jxcr / GHSA-xhq7-xmqj-769h",
            "fast-uri 四条（scheme 注入 / scheme 伪造 / host 混淆 / 路径等价）",
        ),
        # 2026-10-24 实扫命中的另一组（undici 三条修复版同日同一处：7.30.1）：
        # EventSource 解析器无界内存 DoS、非小写算法 token 绕过 SRI、
        # 过量 content-encoding 未捕获异常 DoS。载体是 context7-mcp 声明
        # `undici ^7.0.0` 解析到的 7.29.1；^7 区间顶得到 7.30.1，故按 7.x 线钉。
        "undici": (
            "7.30.1",
            ("node_modules/@upstash/context7-mcp",),
            "GHSA-4qv8-2p9j-2685 / GHSA-f72v-6w45-q472 / GHSA-xjj6-f33q-929c",
            "undici 三条（EventSource DoS / SRI 绕过 / content-encoding DoS）",
        ),
        # @azure/msal-node 6.0.1：授权码流把参数泄露给攻击者可控端点。
        # 修复版 7.1.0（6.x 线无修复——上游只发 7.x），故钉 7.1.1。
        # 载体是 @azure/identity 4.13.3 声明 `@azure/msal-node ^6.0.0`，
        # ^6 顶不到 7.x，只能由 overrides 顶替。
        "@azure/msal-node": (
            "7.1.0",
            ("node_modules/@azure/identity",),
            "GHSA-xcx6-jx8p-x3h5",
            "msal-node 授权码流参数泄露（6.x 线无修复版，须顶到 7.x）",
        ),
    }

    #: 每条包的**全部载体条目**：同名包在树里可能以嵌套形态并存（`<父>/node_modules/<包>`），
    #: 只核根条目等于给嵌套那份放行。键为包名，值为承载条目的 lock 键元组。
    _KNOWN_FLOOR_CARRIERS = {
        "body-parser": (
            "node_modules/body-parser",
            "node_modules/@bytebase/dbhub/node_modules/body-parser",
        ),
    }

    #: 载体键 → 该载体所在声明线的修复下界。只有分段修复的包需要它：
    #: 拿 1.20.9 去卡 2.x 那份等于把「已修」判成「未修」，两条声明线各有自己的下界。
    #: 未登记的载体一律按 `_KNOWN_FLOORS` 的取值卡。
    _FLOOR_BY_CARRIER = {
        "node_modules/body-parser": "2.4.0",
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
            carriers = self._KNOWN_FLOOR_CARRIERS.get(name, (f"node_modules/{name}",))
            present = [key for key in carriers if key in packages]
            if not present:
                # 只有**全部**载体都消失才算「承载者被整体摘除」（合格形态，不报红）；
                # 少一份而另一份还在，就是本类要拦的形态——缺失的落点由
                # `test_everyRegisteredCarrierSurvives` 报红，这里不重复。
                continue
            for key in present:
                version = packages[key].get("version")
                carrier_floor = self._FLOOR_BY_CARRIER.get(key, floor)
                if self._release_tuple(version) >= self._release_tuple(carrier_floor):
                    continue
                problems.append(
                    f"{key}@{version} 低于 {cve} 的修复下界 {carrier_floor}——{note}。\n"
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


class TestNestedCarrierSubtreeIsKeptWhole:
    """body-parser 的两条声明线各落一份，抬版**不许**把嵌套子树并掉。

    背景（PR #369 构建 `cnb-p98-1k5la1aci#008` 的红）：GHSA-27r3-jxmh-p828 的两份载体
    `node_modules/body-parser`（express 5.2.1 → `^2.2.1`）与
    `node_modules/@bytebase/dbhub/node_modules/body-parser`（dbhub → express 4.22.3 →
    `~1.20.5`）各自要走自己的声明线。

    把嵌套落点并到顶层、只留一份的写法（`overrides: {"body-parser": "2.4.0"}` 这种
    平铺覆盖）能让 OSV 变绿，代价是**审计面不再与真实解析同形**：
    `@bytebase/dbhub/node_modules/express@4.22.3` 仍声明 `body-parser ~1.20.5`，
    而 2.x 是 ESM + 命名导出，两者并不通用。故本仓的处置按父包分段钉：
    `{"@bytebase/dbhub": {"body-parser": "1.20.9"}}`——子树保留、版本升到修复版。

    三类断言合起来才有意义：下界（上一类）、**在场**（本类）、**销账与清单咬合**
    （本类的最后一条）。少任何一类，「审计面绿了、判据却空了」都能通过。
    """

    #: 本类钉住的包 → 它在本树里的**全部**落点（缺一即报红）。
    _CARRIERS = {
        "body-parser": (
            "node_modules/body-parser",
            "node_modules/@bytebase/dbhub/node_modules/body-parser",
        ),
    }

    def test_everyRegisteredCarrierSurvives(self):
        lock = _read_json("tools/npx-runtime/package-lock.json")
        packages = lock.get("packages") or {}
        missing = [
            f"{name} → {key}"
            for name, keys in self._CARRIERS.items()
            for key in keys
            if key not in packages
        ]
        assert not missing, (
            "登记的载体落点消失了:\n  " + "\n  ".join(missing) + "\n"
            "  上一类此时会静默退化为空转（看着绿、其实那一份没人查）。\n"
            "  确属上游换掉了承载者，须同步改 _KNOWN_FLOOR_CARRIERS 与 _CARRIERS 并写明理由；\n"
            "  只想让它变绿而把落点从登记里删掉，正是本判据要拦的形态。"
        )

    def test_nested_carrier_sits_under_its_own_parent(self):
        """嵌套那份必须仍落在 dbhub 子树下——落在顶层就说明子树被并掉了。"""
        lock = _read_json("tools/npx-runtime/package-lock.json")
        packages = lock.get("packages") or {}
        nested = "node_modules/@bytebase/dbhub/node_modules/body-parser"
        express = "node_modules/@bytebase/dbhub/node_modules/express"
        assert nested in packages, f"{nested} 不在锁里——dbhub 的 express 4 子树被并掉了"
        declared = (packages[express].get("dependencies") or {}).get("body-parser")
        assert declared, (
            f"{express} 不再声明 body-parser——引入链变了，本类的分段下界需重核"
        )
        root_version = (packages.get("node_modules/body-parser") or {}).get("version", "")
        nested_version = packages[nested].get("version", "")
        assert root_version.split(".")[0] != nested_version.split(".")[0], (
            f"两条声明线解析到同一个大版本（{root_version} / {nested_version}）——"
            "子树已被并成一份，审计树不再与真实解析同形"
        )

    def test_overrides_pin_each_line_by_its_parent(self):
        """按父包分段钉版的 overrides 必须在清单里，否则 1.x 线按 semver 顶不到修复版。"""
        pkg = _read_json("tools/npx-runtime/package.json")
        overrides = pkg.get("overrides") or {}
        assert "body-parser" in overrides, (
            "overrides 缺顶层 body-parser 钉版——express 5 那条线会重新解析到 2.3.0"
        )
        dbhub = overrides.get("@bytebase/dbhub")
        assert isinstance(dbhub, dict) and dbhub.get("body-parser"), (
            "overrides 缺 `@bytebase/dbhub → body-parser` 分段钉版——\n"
            "  express@4.22.3 声明 `body-parser ~1.20.5`，按 semver 顶不到 1.20.9，\n"
            "  只有按父包钉才能保住子树并把那一份抬到修复版。"
        )

# -*- coding: utf-8 -*-
"""前端 API 清单守卫（Issue #112 销账 / Issue #68 归档层导航影响筛选·乙类）。

背景（根因，不是形状）：`docs/09-dev-progress/api_inventory.md` 是一份**专职指路文档**——
它被 `docs/0-index/README.md` 列为 `09-dev-progress` 领域入口，读者顺着它去找前端 API
模块。但它自 2026-06-06 起就没再对齐代码树：声明的模块里近半已改名或合并，另有一批
现行模块根本没进清单。

它坏掉的方式值得点明：**不是没人维护，是它压根没有生成入口**。清单正文是手写的，
代码树一变，它只能漂移。所以本单的落点不是「逐条改路径」（那只能得到一份半对半错的
表，而清单的全部价值在于可信），而是**重生成 + 常驻守卫**：

1. **机器区必须有生成器，且与生成器逐字一致**。清单正文由
   `scripts/generate_api_inventory.py` 产出，守卫重算比对；人在清单里手改一行即红。
2. **模块双向差集为空**。清单声明的模块 ←→ `NeurUI/src/api/modules/*.ts`，
   任一方向有差即红——这是 Issue #112 的验收判据 1。
3. **差异项以显式列表暴露，不得删条目掩盖**。「前端调用未命中后端注册」
   「后端已注册无前端消费」两组差异逐条登记，与生成器输出一致。
4. **快照纪律可核**。清单头部须含生成命令与快照日期；日期不可缺、不可未来、
   不得超过约定周期——过期而不标注，就是让读者把旧表当现行事实源。

反向控制（门禁不空转）：live 路由表与模块清单都设下界；注入漏模块、篡改差异表、
改掉日期，都必须转红。
"""
import io
import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

generator = pytest.importorskip("scripts.generate_api_inventory")

INVENTORY = generator.INVENTORY_PATH


def _inventory_text() -> str:
    assert INVENTORY.is_file(), (
        f"前端 API 清单不存在: {INVENTORY.relative_to(PROJECT_ROOT)}\n"
        "它是 `docs/0-index/README.md` 里的领域入口，缺了读者就找不到前端 API 面。"
    )
    return io.open(INVENTORY, encoding="utf-8").read()


def _machine_block() -> str:
    text = _inventory_text()
    start = text.find(generator.INVENTORY_BEGIN)
    assert start != -1, (
        f"清单缺少机器区起始标记 {generator.INVENTORY_BEGIN}——"
        "没有机器区就无法判断哪些内容是生成物。"
    )
    stop = text.find(generator.INVENTORY_END, start)
    assert stop != -1, f"清单缺少机器区结束标记 {generator.INVENTORY_END}"
    return text[start:stop + len(generator.INVENTORY_END)]


class TestGeneratorIsTheSingleSource:
    """判据必须由生成器提供，守卫不另写一套解析。"""

    def test_generator_exposes_the_inventory_surface(self):
        for name in ("frontModules", "registeredRoutes", "moduleNameDiff",
                     "unmatchedFrontCalls", "unconsumedBackendPrefixes",
                     "renderInventoryTables", "declaredModuleNames"):
            assert hasattr(generator, name), (
                f"生成器未提供 {name}()：清单的事实源缺位，本守卫会退化成一条空规则。"
            )

    def test_declares_generate_command(self):
        assert "generate_api_inventory.py" in generator.GENERATE_COMMAND, (
            "生成命令必须指向本仓实际的生成器脚本；写错命令等于把修复责任推给手改。"
        )


class TestScreeningDoesNotRunVacuous:
    """反向控制：范围与判据都不得退化成空集。"""

    def test_live_route_table_is_not_empty(self):
        routes = generator.registeredRoutes()
        assert len(routes) > 600, (
            f"后端实测路由只解析到 {len(routes)} 条，疑似路由表解析失效——"
            "下面的「对照后端注册」会全部白通过。"
        )

    def test_front_module_surface_is_not_empty(self):
        modules = generator.frontModules()
        assert len(modules) > 40, f"前端模块只解析到 {len(modules)} 个，疑似扫描范围失效。"
        assert sum(module["callCount"] for module in modules) > 300, (
            "前端调用总数过低，疑似调用解析失效（模板串/泛型参数未被识别）。"
        )

    def test_known_live_routes_are_recognized(self):
        """抽样自证：几条确定存在的路由必须在实测表里，否则解析器认错了形态。"""
        paths = {path for path, _ in generator.registeredRoutes()}
        for probe in ("/api/v1/health", "/api/v1/agents", "/api/v1/memory"):
            assert probe in paths, f"实测路由表缺 {probe}——路由表解析口径有误。"
        methods = dict(generator.registeredRoutes())["/api/v1/agents"]
        assert "GET" in methods and "POST" in methods, (
            "实测路由表未带出 HTTP 方法——「方法不匹配」与「路径未注册」会被混作一种差异。"
        )

    def test_injected_missing_module_is_detected(self, tmp_path, monkeypatch):
        """负向控制：磁盘上多出一个未登记的模块，双向差集必须报出来。"""
        monkeypatch.setattr(generator, "MODULES_DIR", tmp_path)
        (tmp_path / "zzz-probe.ts").write_text("export const x = 1\n", encoding="utf-8")
        diff = generator.moduleNameDiff()
        assert "zzz-probe.ts" in diff["undeclared"], (
            "磁盘上多出的模块未被检出——「双向差集为空」这条断言会白通过。\n"
            "（若两侧取数同源，这条断言恒真：清单声明侧必须从清单正文解析。）"
        )


class TestMachineBlockMatchesGenerator:
    """清单是生成物：机器区必须与生成器输出逐字一致，人不得手改。"""

    def test_tables_match_generator_output(self):
        block = _machine_block()
        expected = generator.renderInventoryTables()
        assert block.strip() == expected.strip(), (
            "清单机器区与生成器输出不一致。清单是生成物，不要手改；\n"
            f"重跑：{generator.GENERATE_COMMAND}"
        )

    def test_module_diff_is_empty(self):
        diff = generator.moduleNameDiff()
        assert not diff["missingOnDisk"] and not diff["undeclared"], (
            "清单声明的模块与 `NeurUI/src/api/modules/*.ts` 双向差集不为空："
            f"{diff}\n验收判据 1 要求双向差集为空——清单漏模块或写了不存在的模块。"
        )


class TestDifferencesAreListedExplicitly:
    """差异不是问题，**被藏起来的差异**才是。两组差异都须逐条登记。"""

    def test_every_front_call_gap_is_registered(self):
        gaps = generator.unmatchedFrontCalls()
        if not gaps:
            pytest.skip("本轮前端调用全部命中后端注册（无差异）")
        block = _machine_block()
        missing = [row for row in gaps
                   if f"`{row['path']}`" not in block]
        assert not missing, (
            "有「前端调用未命中后端注册」的条目未登记进清单："
            f"{[(row['module'], row['path']) for row in missing][:5]}\n"
            "删条目不等于修好——差异必须逐条暴露（显式列表，不得用「大致一致」带过）。"
        )

    def test_every_unconsumed_backend_prefix_is_registered(self):
        roots = generator.unconsumedBackendPrefixes()
        if not roots:
            pytest.skip("本轮后端前缀全部有前端消费方")
        block = _machine_block()
        missing = [root for root in roots if f"`{root}`" not in block]
        assert not missing, (
            f"有后端已注册却无前端消费的前缀未登记: {missing[:8]}\n"
            "这是「前端还需补消费方」的显式清单，不许静默。"
        )


class TestQueryStringIsNotARouteSegment:
    """查询串是请求参数，不是路由段——它不得参与路径比对。

    根因（把报错恢复原状就会复现）：`resolveCallPath()` 把实参模板原样当路径，
    于是 `getConsoleChatHistory()` 的 `` `${BASE}/chat/history?session_id=…` ``
    被归一成 `/api/v1/console/chat/history?session_id=*`，而真实路由表里的键是
    `/api/v1/console/chat/history` —— 尾段不等、永不匹配。后果不是「少报一条」，
    而是**假阳性**：真实存在的端点被报成「路径未注册」，连带把有活跃消费者的
    `getConsoleChatHistory` 判成幻影契约、要求删净。假阳性比漏报更坏——它会
    训练人整体忽略那张差异表。

    路由表的键从不含 `?`（参数在 `Query(...)` 里，不在路径里），故判据是
    「带查询串的调用按**路径段**比对」，而不是「把这条差异从表里删掉」。
    """

    CLIENT = "NeurUI/src/api/modules/console.ts"

    def test_query_string_is_not_part_of_the_call_path(self):
        calls = generator.frontendModuleCalls(self.CLIENT)
        assert calls, f"{self.CLIENT} 解析不出任何调用——取数口径失效"
        offenders = [f"{method} {path}" for method, path, _raw in calls if "?" in path]
        assert not offenders, (
            "调用路径里带着查询串，按路由段比对必然失配（真实端点被报成断链）：\n  "
            + "\n  ".join(offenders)
        )

    def test_registered_endpoint_with_query_is_not_reported_as_a_gap(self):
        """真存在、只是调用时带了查询串的端点，不得进差异表。"""
        assert "/api/v1/console/chat/history" in generator.registeredRoutePaths(), (
            "实测路由表缺 `/api/v1/console/chat/history`——本条的反向控制失去意义"
        )
        gaps = [(row["module"], row["method"], row["path"])
                for row in generator.unmatchedFrontCallRows()
                if row["module"] == "console" and "history" in row["path"]]
        assert not gaps, (
            "真实存在的 history 端点被判成「后端未注册」——假阳性会训练人忽略差异表：\n  "
            + "\n  ".join(f"{m} {me} {p}" for m, me, p in gaps)
        )

    def test_genuinely_unregistered_path_with_query_is_still_reported(
        self, tmp_path, monkeypatch
    ):
        """反向控制：真不在路由表里、且带查询串的路径，仍须被判为「路径未注册」。

        没有这一条，上面的修法就可能被做成「凡带 `?` 就跳过」——那是**规避报错**
        （教义第 2 条），差异就此静默。本条的期望值同时钉住「查询串被剥掉」这个
        归一化事实：报出的路径必须是纯路径段。
        """
        probe = tmp_path / "NeurUI" / "src" / "api" / "modules"
        probe.mkdir(parents=True)
        (probe / "zzz-probe.ts").write_text(
            "const BASE = '/console'\n"
            "export function probeMissing() {\n"
            "  return api.get(`${BASE}/zzz-nope?session_id=${id}`)\n"
            "}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(generator, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(generator, "MODULES_DIR", probe)
        monkeypatch.setattr(generator, "FRONTEND_CLIENT_FILES", ())
        rows = generator.unmatchedFrontCallRows()
        assert [(row["module"], row["method"], row["path"]) for row in rows] == [
            ("zzz-probe", "GET", "/api/v1/console/zzz-nope")
        ], f"注入的带查询串断链未被如实报出（或路径未归一）：{rows}"


class TestSnapshotDiscipline:
    """快照纪律：命令与日期必须可核，过期必须显式标注。

    头部是**人的叙述区**（生成命令 + 快照日期写在区块标记之外），机器区的日期由
    `--write` 写回时读回（保证幂等）。故取数一律从**整篇**取：这不是放宽判据，
    而是承认「快照纪律落在头部」这一既定形态。
    """

    def test_header_publishes_command_and_date(self):
        text = _inventory_text()
        assert generator.GENERATE_COMMAND in text, (
            "清单头部未写明生成命令——读者无法自行复算，快照纪律形同虚设。"
        )
        assert generator.extractSnapshotDate(text) is not None, (
            "清单头部未写明快照日期（或日期不可解析）。"
            "没有日期，读者无法判断这份表是否已过期。"
        )

    def test_snapshot_date_is_not_in_the_future(self):
        snapshot = generator.extractSnapshotDate(_inventory_text())
        assert snapshot <= date.today(), (
            f"快照日期 {snapshot} 在未来——日期不可信，快照纪律失效。"
        )

    def test_snapshot_is_within_the_agreed_age(self):
        snapshot = generator.extractSnapshotDate(_inventory_text())
        age = (date.today() - snapshot).days
        assert age <= generator.SNAPSHOT_MAX_AGE_DAYS, (
            f"清单快照已 {age} 天未重生成（上限 {generator.SNAPSHOT_MAX_AGE_DAYS} 天）。\n"
            f"重跑：{generator.GENERATE_COMMAND}\n"
            "过期而不重新生成，就是让读者把旧表当现行事实源。"
        )

    def test_injected_stale_block_is_detected(self):
        """负向控制：机器区被手改成陈旧内容，比对必须转红。"""
        text = _inventory_text()
        drifted = text[:text.find(generator.INVENTORY_END)] + \
            "手改出来的陈旧行\n" + text[text.find(generator.INVENTORY_END):]
        assert drifted != _inventory_text(), "注入漂移失败"
        restored = generator.applyInventoryBlocks(drifted)
        assert generator.INVENTORY_END in restored
        assert generator.renderInventoryTables().strip() == restored[
            restored.find(generator.INVENTORY_BEGIN):
            restored.find(generator.INVENTORY_END) + len(generator.INVENTORY_END)
        ].strip(), "生成器未能把漂移的机器区拉回生成器输出"
        assert "陈旧行" not in restored, "生成器留下了旧内容（替换不彻底）"

    def test_injected_missing_module_in_inventory_is_detected(self, tmp_path, monkeypatch):
        """负向控制：清单漏写一个现行模块，双向差集必须报出来。"""
        text = _inventory_text()
        line = next(l for l in text.splitlines()
                    if "`NeurUI/src/api/modules/memory.ts`" in l)
        drifted = tmp_path / "api_inventory.md"
        drifted.write_text(text.replace(line, ""), encoding="utf-8")
        monkeypatch.setattr(generator, "INVENTORY_PATH", drifted)
        assert "memory.ts" in generator.moduleNameDiff()["undeclared"], (
            "清单里被拿掉一个模块却没被检出——「双向差集为空」会白通过。\n"
            "（declared 侧若不从清单正文取数、而是直接读磁盘，这条恒不触发。）"
        )

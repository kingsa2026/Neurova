# -*- coding: utf-8 -*-
"""路由挂载契约守卫（Issue #68 收口：挂载事实必须只有一处定义）。

根因（把报错恢复原状就会复现）：路由的真实路径由**两处**共同决定——`endpoints/__init__.py`
的 `endpoint_modules` 挂载表（表内 prefix）与各模块 `APIRouter(prefix=...)` 自述前缀；
`app.py` 另有旁路直接挂载。两处各写一半、无一致性校验，于是同一份注册表长出三类矛盾：

1. **零路由挂载**：`router` / `evolution_router` / `rag_router` 是模块级空 `APIRouter()`
   （全仓没有任何语句往里加路由），却被挂成 `/api`、`/api/evolution`、`/api/rag`
   ——对外声称三个前缀可用，实际 404。
2. **前缀重复**：`neuron` 自述前缀 `/neuron` 被表内 prefix 与 `app.py` 各叠一次
   → 真实路径 `/api/neuron/neuron/*`；`coordination_api` 同理 →
   `/api/coordination/coordination/*`。前端按 `/api/neuron/*` 请求，落 404。
3. **挂载层错位**：`budget_api` / `cost_rollup_api` 被旁路挂在 `/api` 下，
   而前端 axios `baseURL=/api/v1`。`CostDashboardPage.vue`（路由表内真实页面）
   请求 `/api/v1/budgets/*`、`/api/v1/cost-rollup/*` → 必 404，且被
   `.catch(() => null)` 静默吞成「页面正常渲染、数据全空」。

判据单源在 `scripts/generate_api_inventory.py`（守卫只做「取数 + 断言 + 反向控制」，
不在测试里另写一套解析）——那正是本次要收口的那件事：挂载事实只能有一处定义。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi import APIRouter, FastAPI

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

GENERATOR_NAME = "scripts.generate_api_inventory"


def _generator():
    """生成器模块。缺失即红灯——不许用 importorskip 把它变成静默跳过。"""
    return importlib.import_module(GENERATOR_NAME)


class TestJudgementLivesInTheGenerator:
    """判据必须由生成器提供，守卫不另写一套挂载解析。"""

    def test_generator_exposes_mount_audit_surface(self):
        generator = _generator()
        for name in ("mountedRouterAudit", "auditMountsFor", "unmountedEndpointModules"):
            assert hasattr(generator, name), (
                f"生成器未提供 {name}()：挂载契约的事实源缺位，本守卫会退化成一条空规则。"
            )


class TestNoZeroRouteMount:
    def test_no_mounted_router_serves_nothing(self):
        audit = _generator().mountedRouterAudit()
        assert not audit["零路由挂载"], (
            "有挂载动作却一条路由也没有——对外声称该前缀可用，实际全 404：\n  "
            + "\n  ".join(f"挂载点 {point}（自述前缀 {own!r}）"
                          for point, own, _operation in audit["零路由挂载"])
        )


class TestNoRepeatedPrefixSegment:
    def test_mount_prefix_does_not_repeat_router_own_prefix(self):
        audit = _generator().mountedRouterAudit()
        assert not audit["前缀重复"], (
            "挂载前缀与 router 自述前缀重复，真实路径多出一段"
            "（前端按单段路径请求 → 全 404）：\n  "
            + "\n  ".join(f"{point} + 自述 {own}" for point, own, _operation in audit["前缀重复"])
        )


class TestNoRouterIsMountedTwice:
    def test_same_router_is_not_mounted_twice(self):
        audit = _generator().mountedRouterAudit()
        assert not audit["重复挂载"], (
            "同一个 router 被挂到两个前缀——同一件事两个写入点，改一处漏一处：\n  "
            + "\n  ".join(f"{point}（自述前缀 {own!r}，首挂 {first}）"
                          for point, own, first in audit["重复挂载"])
        )


def _wiringKey(modulePath: str) -> str:
    """处置台账的键：端点包内的模块收成末段短名，包外保留完整点分路径。

    「短名还是全路径」这条口径只写在这里一处，并且与台账现状对齐——
    包外两个模块（`routes` / `acp_server`）末段不保证唯一，台账因此按全路径记；
    混用两种键会让台账与名单互相掩盖（同名不同物直接对上号）。
    """
    return modulePath.rsplit(".", 1)[-1]


class TestUnmountedModulesAreExplicit:
    def test_unmounted_route_defining_modules_are_named(self):
        """定义了路由却从未挂载的模块必须被点名（不许静默遗留）。

        本条**不要求当场接线**——接线要动运行时行为，须各自评估适配面。
        它要求的是「以显式名单暴露」：名单进清单（`api_inventory.md`）供人排期，
        而不是像现在这样只活在架构评审文档里。
        """
        names = _generator().unmountedEndpointModules()
        assert isinstance(names, list)
        for name in names:
            assert name.startswith(("neurova.", "scripts.", "tools.", "examples.")), (
                f"未挂载模块名单出现仓外模块名：{name}（取数口径错了）"
            )

    def test_unmounted_set_matches_the_baseline(self):
        """未挂载名单与台账逐项咬合，双向——只降不升。

        新出现一个未挂载模块即红（不许静默新增无服务面的模块）；
        台账里的条目已被修复/删除却未下调基线亦红（台账失真等于没有台账）。
        """
        generator = _generator()
        current = set(generator.unmountedEndpointModules())
        dispositions = generator.readWiringDispositions()
        # 台账用短名、名单用完整点分路径，两边都归一到末段再比；
        # 台账若登记同一个末段名的两条不同模块，按「末段命中即算登记」判，
        # 宁可漏一份台账缺行，也不把已被登记过的模块再报一次「新增」。
        recordedKeys = {_wiringKey(name) for name in dispositions}
        added = sorted(path for path in current
                       if _wiringKey(path) not in recordedKeys)
        assert not added, (
            "出现新的未挂载路由模块（全仓定义了路由、装配后一条都不可达）：\n  "
            + "\n  ".join(added)
            + "\n修法：接入注册表，或删除该模块；两者都不是时在 "
            + generator.WIRING_BASELINE.name
            + " 里登记处置与依据"
        )
        # 反向：台账不再「只列名字」——每一行都必须落到磁盘事实
        # （已接线 ⇒ 真在路由表；已删除 ⇒ 文件真没了；待实现 ⇒ 仍在名单里）。
        stale = sorted(
            name for name, verdict in dispositions.items()
            if verdict == "待实现"
            and not any(_wiringKey(path) == _wiringKey(name) for path in current)
        )
        assert not stale, (
            "台账标记「待实现」的模块其实已经不在未挂载名单里——"
            "处置写「待实现」而事实已收口，等于把已办事项继续挂在待办区（台账失真）：\n  "
            + "\n  ".join(stale)
        )


class TestNegativeControls:
    """反向控制：门禁不得空转。"""

    def test_injected_empty_router_is_detected(self):
        """注入一个零路由 router（自述前缀写进挂载前缀）→ 必须报零路由。"""
        app = FastAPI()
        app.include_router(APIRouter(prefix="/zzz-probe"), prefix="/api/zzz-probe")
        audit = _generator().auditMountsFor(app)
        assert ("/api/zzz-probe/zzz-probe", "/zzz-probe") in {
            (point, own) for point, own, _operation in audit["零路由挂载"]
        }, "注入的零路由 router 未被检出——「无零路由挂载」这条断言会白通过。"

    def test_injected_duplicate_prefix_is_detected(self):
        """注入「挂载前缀重复自述前缀」（自述已含该段、挂载点又写一遍）→ 必须报重复段。"""
        app = FastAPI()
        router = APIRouter(prefix="/dup")
        router.get("/x")(_noop)
        app.include_router(router, prefix="/api/dup")
        audit = _generator().auditMountsFor(app)
        assert any(point == "/api/dup/dup" for point, _own, _op in audit["前缀重复"]), (
            "注入的「挂载前缀重复自述前缀」未被检出——重复段这条断言会白通过。"
        )

    def test_injected_double_mount_is_detected(self):
        """同一个 router 挂两次 → 必须报重复挂载，且不把正常挂载误判成问题。"""
        app = FastAPI()
        router = APIRouter(prefix="/once")
        router.get("/x")(_noop)
        app.include_router(router, prefix="/api/once")
        app.include_router(router, prefix="/api/twice")
        audit = _generator().auditMountsFor(app)
        assert any(point == "/api/twice/once" for point, _own, _first in audit["重复挂载"]), (
            "注入的重复挂载未被检出——「无重复挂载」这条断言会白通过。"
        )

    def test_unmounted_detector_marks_injected_orphan_and_clears_known_wired(
        self, tmp_path, monkeypatch
    ):
        """未挂载判据必须咬住孤儿、且不把已接入模块误报（假阳性比漏报更坏）。

        孤儿侧用**注入**而非依赖仓库里的某个具体残留：本批已把实测的六个孤儿
        各自收口（接线 / 删除），拿其中一个当锚点会让这条反向控制反过来
        **要求那个孤儿继续存在**——门禁锚在可变事实上的典型失效。
        """
        generator = _generator()
        probe = tmp_path / "neurova" / "api" / "endpoints"
        probe.mkdir(parents=True)
        (probe / "zzz_orphan.py").write_text(
            "from fastapi import APIRouter\n"
            "router = APIRouter(prefix='/zzz')\n\n"
            "@router.get('/x')\n"
            "def _x():\n"
            "    return {}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(generator, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(generator, "SOURCE_ROOTS", ("neurova",))
        assert generator.unmountedEndpointModules() == ["neurova.api.endpoints.zzz_orphan"], (
            "注入的孤儿端点模块未被检出——判据认错了接线形态。"
        )

        monkeypatch.undo()
        unwired = {name.rsplit(".", 1)[-1]
                   for name in generator.unmountedEndpointModules()}
        assert "computer" not in unwired, (
            "已接入注册表的 computer 模块被误报为未接线——假阳性会训练人忽略这份名单。"
        )


async def _noop():
    return None

class TestFrontendBaseUrlIsReadFromEveryDeclaredForm:
    """前端客户端的基地址有三类写法，判据必须全认——漏认就是**假阳性**。

    `neuron.ts` 用的是 `axios.create({ baseURL: '/api/neuron' })`。漏认这一形态时，
    它的 8 个调用会被拼成 `/api/v1/<资源段>` 并被报成「后端未注册」——而
    `/api/neuron/stats` 这类路由其实好好地挂在 `/api/neuron` 下。
    假阳性比漏报更坏：它会训练人忽略这张差异表（教义第 2 条的同型反面）。
    """

    def test_object_literal_base_url_is_recognized(self):
        generator = _generator()
        calls = generator.frontendModuleCalls("NeurUI/src/api/neuron.ts")
        assert calls, "neuron.ts 解析不出任何调用——取数口径失效"
        for _method, fullPath, _raw in calls:
            assert fullPath.startswith("/api/neuron/"), (
                f"`neuron.ts` 的调用被拼成 {fullPath}：其 `axios.create({{baseURL:"
                " '/api/neuron'}})` 声明未被识别，会产生成批假阳性。"
            )

    def test_neuron_calls_match_the_registered_routes(self):
        generator = _generator()
        gaps = [row for row in generator.unmatchedFrontCallRows()
                if row["module"] == "neuron"]
        assert not gaps, (
            "`neuron.ts` 的调用被报成未命中，但后端确实挂在 /api/neuron 下：\n  "
            + "\n  ".join(f"{row['method']} {row['path']}" for row in gaps)
        )


class TestWiringDispositionsAreRecordedAndExecuted:
    """未挂载名单的每一行都必须带「处置 + 依据」，且处置必须落到磁盘事实。

    根因（把报错恢复原状就会复现）：台账头部把收录口径写成「模块定义了路由，
    但装配后的应用里一条都不可达」，`docs/architecture-model/architecture-findings.md`
    也按「全仓」表述；而 `unmountedEndpointModules()` 的实现曾只 `rglob`
    `neurova/api/endpoints/` 一个包。判据比自己声明的契约窄一层，同一形态在包外
    就静默存活——包外的 `neurova.api.openplatform.routes`（19 条）与
    `neurova.core.acp_server`（5 条）正是因此长期不在册的两条命中点。

    两条命中点已在后续批次**按根因退役**（第二份平行实现，见
    `tests/unit/api/test_orphan_faces_retired_guard.py`）：包外当前无孤儿，
    故「扫全仓」这一口径由**注入探针**自证（把 `SOURCE_ROOTS` 换成一个只有
    孤儿模块的临时根，必须检出）——判据不读该常量就会静默返回空。

    本文件（上一轮：接线断点处置批）：台账升级为**三态处置表**——只列名字的台账
    答得出「现在有哪些没接线」，答不出「每一条的结论是什么、执行了没有」，
    于是同一份名单可以被反复登记、永不收敛；处置是有限枚举后，「已办/待办」
    才可机器判定，且每一行都必须落到磁盘事实（已接线 ⇒ 真在路由表；
    已删除 ⇒ 文件真没了；待实现 ⇒ 仍在名单里且写了依据）。

    两条口径合并后仅存一种台账写法：**全仓 + 三态处置**。删除批若另立一份
    只列名字的名单，就是同一件事的第二份事实源（教义第 6 条）。
    """

    def test_retired_out_of_package_orphans_are_not_named(self):
        """已退役的两条包外命中点不得再出现在名单里（名单是「尚未处置」的集合）。"""
        names = set(_generator().unmountedEndpointModules())
        relisted = sorted({"neurova.api.openplatform.routes", "neurova.core.acp_server"} & names)
        assert not relisted, (
            "已退役的包外孤儿面又被报进未挂载名单：\n  " + "\n  ".join(relisted)
            + "\n它们已按根因删除；再次出现说明删除被回退了。"
        )

    def test_wired_rows_are_really_mounted(self):
        """处置写「已接线」的模块必须真在装配后的路由表里（不许只改台账）。"""
        generator = _generator()
        unwired = set(generator.unmountedEndpointModules())
        for module, verdict in generator.readWiringDispositions().items():
            if verdict == "已接线":
                assert module not in unwired, (
                    f"{module} 的处置写成「已接线」，但它仍不在装配后的路由表里"
                    "——台账与事实不符（改台账不代替改事实）。"
                )

    def test_deleted_rows_are_really_gone(self):
        """处置写「已删除」的模块文件必须真的不在盘上。"""
        generator = _generator()
        for module, verdict in generator.readWiringDispositions().items():
            if verdict == "已删除":
                assert not (PROJECT_ROOT / generator.moduleFile(module)).is_file(), (
                    f"{module} 的处置写成「已删除」，但文件仍在盘上——台账失真。"
                )

    def test_pending_rows_carry_a_reason(self):
        """仍待办的每一行必须写明依据——「待实现」不能是一句空话。"""
        generator = _generator()
        reasons = generator.readWiringReasons()
        for module, verdict in generator.readWiringDispositions().items():
            if verdict == "待实现":
                assert reasons.get(module), (
                    f"{module} 仍标记「待实现」却没有写依据——排期者拿不到任何判据。"
                )


class TestRegistrationFailuresAreVisibleAtStartup:
    """注册表导入失败必须在启动期可见（`architecture-findings.md` 6.1 的另一半）。

    根因（把报错恢复原状就会复现）：`register_endpoint_routers` 对导入失败只
    `logger.debug("Skipping %s")` ——DEBUG 在默认级别下不输出，于是「某个注册表
    模块炸了、该前缀整体 404」这件事在启动期**完全不可见**，只在用户点开页面时
    表现为空白。这正是教义第 2 条点名的「把失败改写成看不见」。
    """

    def test_failing_registry_module_is_logged_at_error(self, caplog, monkeypatch):
        import logging

        from neurova.api import endpoints as endpoints_package
        from fastapi import FastAPI

        monkeypatch.setattr(
            endpoints_package,
            "ENDPOINT_MODULES",
            [("neurova.api.endpoints.__nonexistent_probe__", "/v1/probe", "Probe API")],
        )
        endpoints_package.resetRegistrationFailures()
        with caplog.at_level(logging.DEBUG):
            endpoints_package.register_endpoint_routers(FastAPI())

        records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert records, (
            "注册表模块导入失败只留下了 DEBUG 级日志——启动期不可见。"
        )
        assert any("__nonexistent_probe__" in r.getMessage() for r in records), (
            "ERROR 日志没有点出失败的模块名，排障者仍不知道是谁炸了。"
        )

    def test_failing_module_is_reported_by_the_failure_surface(self, monkeypatch):
        from neurova.api import endpoints as endpoints_package
        from fastapi import FastAPI

        monkeypatch.setattr(
            endpoints_package,
            "ENDPOINT_MODULES",
            [("neurova.api.endpoints.__nonexistent_probe__", "/v1/probe", "Probe API")],
        )
        endpoints_package.resetRegistrationFailures()
        endpoints_package.register_endpoint_routers(FastAPI())
        failures = endpoints_package.registrationFailures()
        assert failures and failures[0][0] == "neurova.api.endpoints.__nonexistent_probe__", (
            "导入失败没有被记进可读取的失败面——健康检查与启动自检都拿不到它。"
        )

    def test_real_application_registers_all_rows(self):
        """live：真应用的注册表全量可导入（失败面为空）。

        这条同时是「失败面不得恒空」的反向控制：若判据失效，
        上面的注入用例会转绿，而这条会暴露真实注册表本身有模块进不来。
        """
        from neurova.api import endpoints as endpoints_package

        endpoints_package.resetRegistrationFailures()
        records = endpoints_package.register_endpoint_routers(
            __import__("fastapi").FastAPI()
        )
        assert endpoints_package.registrationFailures() == [], (
            "真实注册表有模块导入失败："
            + repr(endpoints_package.registrationFailures())
        )
        assert records > 0


class TestFrameworkClientsUseTheSharedInstance:
    """`NeurUI/src/api/computer.ts` 必须走唯一 axios 实例（鉴权/信封解包只在那一处）。

    根因（把报错恢复原状就会复现）：该客户端 `import axios from 'axios'` 自建裸调用
    并硬编码 `const API_BASE = '/api'`。于是它拿不到 Bearer token、不做响应解包、
    指向未挂载的 `/api/computers`——**「无 token + 无信封 + 必 404」**三件事叠在
    一个文件里，而它恰恰是清单第四节 17 条「路径未注册」的来源。
    """

    CLIENT = "NeurUI/src/api/computer.ts"

    def test_client_does_not_bare_import_axios(self):
        text = (PROJECT_ROOT / self.CLIENT).read_text(encoding="utf-8")
        assert "from 'axios'" not in text, (
            "该客户端仍直接 import axios——绕开唯一实例即绕开鉴权拦截器与信封解包。"
        )

    def test_client_uses_the_shared_api_entry(self):
        text = (PROJECT_ROOT / self.CLIENT).read_text(encoding="utf-8")
        assert "@/api'" in text, (
            "该客户端未使用 `@/api` 的共享实例——全库唯一 axios 实例在 `src/api/index.ts`。"
        )

    def test_client_calls_resolve_against_registered_routes(self):
        generator = _generator()
        rows = [row for row in generator.unmatchedFrontCallRows()
                if row["module"] == "computer"]
        assert not rows, (
            "`computer.ts` 的调用仍未命中后端注册表：\n  "
            + "\n  ".join(f"{row['method']} {row['path']}（{row['verdict']}）" for row in rows)
        )


class TestUnmountedScanCoversTheWholeRepository:
    """未挂载名单的收录口径是**全仓**，不是只扫端点包。

    根因（把报错恢复原状就会复现）：台账声明「模块定义了路由，但装配后的应用里
    一条都不可达」，`docs/architecture-model/architecture-findings.md` 也按「全仓」
    表述；口径若只 `rglob` `neurova/api/endpoints/` 一个包，同一形态在包外就永远
    看不见。早前实测 `neurova.api.openplatform.routes`（19 条路由）与
    `neurova.core.acp_server`（5 条）都不在主应用路由表里，却从不进名单——
    「登记不代替修复」的前提是先被看见。口径收口到 `SOURCE_ROOTS` 后这两条在册，
    与 `computer_api` / `phase3_api` 两条接线项并列处置（见处置台账）。

    本类只钉**口径**：名单归零由 `TestWiringDispositionsAreRecordedAndExecuted`
    的硬零断言负责，两者不重复要求「名单非空」——那会把已办事项又要求成未办。
    """

    def test_scan_roots_are_the_whole_repository(self):
        generator = _generator()
        assert tuple(generator.SOURCE_ROOTS) == ("neurova", "scripts", "tools", "examples"), (
            "收录口径的源码根集合变了：口径只写一份（`SOURCE_ROOTS`），"
            "改口径须连同台账声明与守卫一起收口。"
        )

    def test_injected_orphan_outside_the_endpoints_package_is_detected(
        self, tmp_path, monkeypatch
    ):
        """反向控制：仓内任一源码根下注入的孤儿模块都必须被检出（门禁不得空转）。

        判据若不读 `SOURCE_ROOTS`，把根换成一个只有孤儿模块的临时目录就会静默返回空
        ——「扫全仓」这句声明便成了空话。
        """
        generator = _generator()
        probe = tmp_path / "probe"
        probe.mkdir()
        (probe / "orphan_face.py").write_text(
            "from fastapi import APIRouter\n"
            "router = APIRouter(prefix='/orphan')\n\n"
            "@router.get('/x')\n"
            "def _x():\n"
            "    return {}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(generator, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(generator, "SOURCE_ROOTS", ("probe",))
        assert generator.unmountedEndpointModules() == ["probe.orphan_face"], (
            "临时源码根下的孤儿模块未被检出——「扫全仓」这条口径在空转。"
        )

    def test_self_serving_asgi_app_is_not_reported(self):
        """反向控制：自带 `FastAPI()` 应用、由自己的进程提供服务的模块不是孤儿。

        `neurova/guest_agent/server.py` 自建 ASGI 应用、由独立启动器跑起来，
        它不依赖被 include 进主应用——把它报成「未接线」是假阳性，
        而假阳性会训练人忽略这份名单（教义第 2 条的同型反面）。
        """
        names = set(_generator().unmountedEndpointModules())
        assert "neurova.guest_agent.server" not in names, (
            "自带 FastAPI 应用的模块被误报为未接线——判据认错了「接线」形态。"
        )

    def test_injected_orphan_inside_the_endpoints_package_is_detected(
        self, tmp_path, monkeypatch
    ):
        """反向控制：端点包内的孤儿模块同样必须被检出（口径扩到全仓不得丢掉原包）。"""
        generator = _generator()
        probe = tmp_path / "neurova" / "api" / "endpoints"
        probe.mkdir(parents=True)
        (probe / "zzz_orphan.py").write_text(
            "from fastapi import APIRouter\n"
            "router = APIRouter(prefix='/zzz')\n\n"
            "@router.get('/x')\n"
            "def _x():\n"
            "    return {}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(generator, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(generator, "SOURCE_ROOTS", ("neurova",))
        assert generator.unmountedEndpointModules() == ["neurova.api.endpoints.zzz_orphan"], (
            "注入的孤儿端点模块未被检出——名单归零这条断言会白通过。"
        )

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
        current = set(generator.unwiredEndpointModuleNames())
        baseline = generator.readWiringBaseline()
        added = sorted(current - baseline)
        assert not added, (
            "出现新的未挂载路由模块（全仓定义了路由、装配后一条都不可达）：\n  "
            + "\n  ".join(added)
            + "\n修法：接入注册表，或删除该模块；两者都不是时登记进 "
            + generator.WIRING_BASELINE.name
        )
        removed = sorted(baseline - current)
        assert not removed, (
            "台账里的未挂载模块已被修复/删除，请同步下调基线（只降不升）：\n  "
            + "\n  ".join(removed)
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

    def test_unmounted_detector_marks_known_orphan_and_clears_known_wired(self):
        """未挂载判据必须咬住已知孤儿、且不把已接入模块误报（假阳性比漏报更坏）。"""
        generator = _generator()
        unwired = set(generator.unwiredEndpointModuleNames())
        assert "neurova.api.endpoints.computer_api" in unwired, (
            "已实现但全仓无挂载点的 computer_api 未被检出——判据认错了接线形态。"
        )
        assert "neurova.api.endpoints.computer" not in unwired, (
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


class TestUnwiredScanCoversTheWholeRepository:
    """收录口径必须与台账声明的契约一致：**全仓**无挂载点。

    根因（把报错恢复原状就会复现）：台账头部把收录口径写成「模块定义了路由，
    但装配后的应用里一条都不可达」，`docs/architecture-model/architecture-findings.md`
    也按「全仓」表述；而 `unmountedEndpointModules()` 的实现只 `rglob`
    `neurova/api/endpoints/` 一个包。判据比自己声明的契约窄一层，于是同一形态在
    包外静默存活——实测 `neurova.api.openplatform.routes`（19 条路由）与
    `neurova.core.acp_server`（5 条）都不在主应用路由表里，却从不进名单。
    「登记不代替修复」的前提是先被看见；看不见的条目连登记的机会都没有。
    """

    def test_orphans_outside_the_endpoints_package_are_named(self):
        names = set(_generator().unmountedEndpointModules())
        for orphan in ("neurova.api.openplatform.routes", "neurova.core.acp_server"):
            assert orphan in names, (
                f"{orphan} 定义了路由、装配后一条都不可达，却不在名单里——"
                "收录口径只扫 `neurova/api/endpoints/`，比台账声明的「全仓」窄一个包。"
            )

    def test_injected_orphan_outside_the_endpoints_package_is_detected(self, tmp_path, monkeypatch):
        """反向控制：仓内任一源码根下注入的孤儿模块都必须被检出（门禁不得空转）。

        判据若不读 `SOURCE_ROOTS`，把根换成一个只有孤儿模块的临时目录就会静默返回空
        ——「扫全仓」这句声明便成了空话。
        """
        generator = _generator()
        probe = tmp_path / "probe"
        probe.mkdir()
        (probe / "orphan_face.py").write_text(
            "from fastapi import APIRouter\n"
            "router = APIRouter(prefix='/zzz')\n\n"
            "@router.get('/x')\n"
            "def _x():\n"
            "    return {}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(generator, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(generator, "SOURCE_ROOTS", ("probe",))
        names = generator.unmountedEndpointModules()
        assert names == ["probe.orphan_face"], (
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

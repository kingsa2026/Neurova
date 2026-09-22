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
            assert name.startswith("neurova.api.endpoints."), (
                f"未挂载模块名单出现非端点模块名：{name}（取数口径错了）"
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

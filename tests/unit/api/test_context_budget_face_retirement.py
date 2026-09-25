# -*- coding: utf-8 -*-
"""T-09：假预算面下架——端点 + 前端包装 + 锁 URL 的测试同删（Issue #90 §10 第 2 项）。

## 为什么这是「下架」而不是「修读数」

审计 P2-2 的原始形态是**假读数**：GET 恒返回硬编码 `16000/0/16000`、PUT 恒返回
成功而零效果，两个分支都挂在 `agent.unified_injector` 上——该属性全仓零赋值点。
B6-2 把读数接回了真源（`ContextOrchestrator` 的窗口预算，取不到即 503 点名），
**假读数这一面已消**，剩下的判定是「这个 HTTP 面还要不要」。

判定依据（工单 §10 第 2 项已给，2026-09-21 核过前端消费面）：

- `NeurUI/src/api/modules/context.ts` 的两个包装函数**无任何 .vue / store 调用**；
- 唯一的「引用」是 `api-modules.test.ts` 里锁 URL 的两条用例——那是**锁自己**，
  不构成消费方。

于是它是一个「无消费者却有对外契约」的面。按修复教义第 5 条（放大视角），下架
必须**整条契约一次扫净**，否则会在别处长出新的孤儿：端点删了而编排器上的读写方法
留着，就是新鲜的「零生产消费点」。

## 契约搬到哪面（不是凭空删）

两个事实都有**有真实消费者的面**在serving：

| 事实 | 下架面（无消费者） | 真面（有消费者） |
|---|---|---|
| 本轮 prompt 实测规模 | `get_token_budget()["used_tokens"]` | `GET /context/composition` 的 `total_tokens` |
| 模型上下文窗口 | `get_token_budget()["max_tokens"]` | 同响应的 `context_window` |

`/context/composition` 的消费者是聊天页环图（`ContextUsageIndicator.vue`），
且它读的就是同一份 compose 侧实测快照。故本下架**不移除任何事实**，只移除
第二份对外契约——这正是「单一事实源」要求的形态。

## 本守卫钉什么

1. 路由表里不再有 `/token-budget`（GET / PUT）；
2. 前端模块不再导出这两个包装（含类型声明）；
3. 仓内（前端 + 测试）不再有任何锁该 URL 的字符串——「同删」是机器可验的；
4. 编排器上不在保留只服务该端点的读写方法（否则是新的零消费点）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
GUARD_REL = "tests/unit/api/test_context_budget_face_retirement.py"

CONTEXT_ENDPOINT = PROJECT_ROOT / "neurova" / "api" / "endpoints" / "context.py"
FRONTEND_MODULE = PROJECT_ROOT / "NeurUI" / "src" / "api" / "modules" / "context.ts"

#: 下架面的 URL 形态：后端字面量 `/context/token-budget`，前端模板 `${BASE}/token-budget`。
#: 负向断言 `(?![-\w/{])` 把 `/context-pool/pool-settings/token-budget/{model}` 排除——
#: 那是**另一个面**的路径（`ContextPool.get_token_budget_for_model`，有真实消费者），
#: 不在本单范围内，误伤它就是把两个面当成一个面。
RETIRED_URL_PATTERN = re.compile(r"(?:/context/token-budget|\$\{BASE\}/token-budget)(?![-\w/{])")

#: 锁该 URL 的字符串可能出现的两个根（前端源码 + 测试根）。
SCAN_ROOTS = ("NeurUI/src", "tests")
SCAN_SUFFIXES = (".ts", ".vue", ".py", ".js")
#: 本守卫自身要写这个 URL 才能做负向断言，故显式豁免（不靠"它能读到自己"这条巧合）。
SELF_EXEMPT = {GUARD_REL}
#: 下架前的历史记录（工单/审计/台账）是**证据**不是引用，故只扫代码与测试。
HISTORY_SUFFIXES_KEPT = ()


class TestRetiredRouteIsGone:
    """路由表里不再有该面——「删了函数但装饰器还在」这类半删会被抓到。"""

    def test_router_serves_no_token_budget_route(self):
        from neurova.api.endpoints import context as endpoint

        paths = {
            (getattr(route, "path", ""), method)
            for route in endpoint.router.routes
            for method in (getattr(route, "methods", None) or ())
        }
        offenders = sorted(p for p in paths if p[0] == "/token-budget")
        assert not offenders, (
            f"上下文端点仍挂着假预算路由 {offenders} —— 该面无任何非测试消费者"
            "（工单 §10 第 2 项），下架必须连端点一起去掉。"
        )

    def test_no_budget_holder_resolver_left_behind(self):
        """`_resolve_budget_holder` 只服务那两个路由，路由没了它就该没了。"""
        source = CONTEXT_ENDPOINT.read_text(encoding="utf-8")
        assert "_resolve_budget_holder" not in source, (
            "`_resolve_budget_holder` 仍留在端点模块里 —— 只服务已下架路由的解析函数"
            "留着就是新的零消费点（修复教义第 5 条：同一契约整条扫净）。"
        )


class TestRetiredFrontendWrapperIsGone:
    """前端包装同删——留着就是「调用一个后端已不存在的路径」的幻影契约。"""

    def test_frontend_module_exposes_no_budget_wrapper(self):
        source = FRONTEND_MODULE.read_text(encoding="utf-8")
        offenders = [
            name
            for name in ("getTokenBudget", "setTokenBudget", "interface TokenBudget")
            if name in source
        ]
        assert not offenders, (
            f"前端 context 模块仍导出已下架面的包装：{offenders}\n"
            "后端路由已删，留着的包装一调就 404（幻影契约）。"
        )


class TestRetiredUrlIsNotLockedAnywhere:
    """锁 URL 的测试必须同删：它是唯一「消费」该面的东西，留着等于锁一个空契约。"""

    def test_no_source_or_test_locks_the_retired_url(self):
        offenders = []
        for root_name in SCAN_ROOTS:
            root = PROJECT_ROOT / root_name
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                    continue
                relative = path.relative_to(PROJECT_ROOT).as_posix()
                if relative in SELF_EXEMPT:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if RETIRED_URL_PATTERN.search(line):
                        offenders.append(f"{relative}:{lineno}")
        assert not offenders, (
            "仓内仍有代码/测试锁着已下架的预算 URL：\n  "
            + "\n  ".join(offenders[:12])
            + "\n修法：端点、前端包装、锁 URL 的测试三处同删（工单 §10 第 2 项）。"
        )


class TestOrchestratorBudgetFaceIsGone:
    """编排器上只服务该端点的读写方法一并退役——否则是新鲜的零消费点。"""

    def test_orchestrator_has_no_budget_read_write_face(self):
        from neurova.context.orchestrator import ContextOrchestrator

        offenders = [
            name
            for name in ("get_token_budget", "set_token_budget")
            if hasattr(ContextOrchestrator, name)
        ]
        assert not offenders, (
            f"`ContextOrchestrator` 仍保留 {offenders} —— 它们的唯一消费方是已下架的"
            "端点（B6-2 为接真读数而加）。留着就是「写了没人读」的断点，"
            "且与 `/context/composition` 的实测快照构成第二份对外读数。"
        )


class TestLiveFactsStillHaveTheirRealFace:
    """契约搬到真面：下架不得移除任何事实（否则就是"删干净"式的能力净损失）。"""

    def test_composition_endpoint_still_serves_both_facts(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.auth import get_current_user
        from neurova.api.endpoints import context as endpoint
        from neurova.context.composition import measure_composition, reset_composition

        reset_composition()
        measure_composition(
            "agent-budget-retire",
            [{"role": "user", "content": "本轮 prompt 正文" * 20}],
            None,
            context_window=128000,
        )
        app = FastAPI()
        app.include_router(endpoint.router, prefix="/context")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        try:
            resp = TestClient(app).get(
                "/context/composition", params={"agent_id": "agent-budget-retire"}
            )
        finally:
            app.dependency_overrides.clear()
            reset_composition()

        assert resp.status_code == 200, resp.text[:300]
        data = resp.json()
        assert data["total_tokens"] > 0, (
            "「本轮 prompt 实测规模」这一事实在下架后取不到了 —— "
            "它必须由有真实消费者的 `/context/composition` 承担（total_tokens）。"
        )
        assert data["context_window"] == 128000, (
            "「模型上下文窗口」这一事实在下架后取不到了 —— "
            "同响应应以 context_window 提供。"
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = {
            line.split("#", 1)[0].strip()
            for line in PROTECTED.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        assert GUARD_REL in listed, (
            f"{GUARD_REL} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行"
            "（B5 收口时正是这个形态：文件在仓、单跑全绿、清单里没有）。"
        )

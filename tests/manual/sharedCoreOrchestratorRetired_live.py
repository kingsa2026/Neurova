# -*- coding: utf-8 -*-
"""活体自证（§6-115 · 序 5 批 D）：删掉桩编排器后，真启动路径与规划面照旧。

不跑单元测试的形状检查，走 `create_app()` + `TestClient` 的真栈：

1. 应用真启动（lifespan 跑完），`/api/v1/health` 返 200；
2. 真发请求打 `/api/v1/plans/documents` 与 `/api/v1/monitor/status`：**404 才算面被删坏**，
   401 说明前缀在位、只是鉴权没过。挂载前缀是 `/api` + 注册表前缀，不是裸 `/v1/*`；
   路由表形状读数在这里不可信（include_router 存成 `_IncludedRouter`，顶层项无 `.path`，
   摊平只读得到 5 条），故本脚本一律用行为读数。404 校准格再打一条不存在的路径，
   要求它**必须** 404——否则上面那句"≠404"永远无从失败；
3. **启动全过程中 `neurova.shared_core.plan_orchestrator` 一次都没进过 `sys.modules`**
   ——这是"它从来不在生产路上"的运行时证据（grep 只证明文本，不证明执行）；同一格要求
   在役的 `shared_core.execution_engine` **在**，否则第 3 条只是空集假绿；
4. 反向对照：现在去 import 它必须 `ModuleNotFoundError`，且门面 docstring 不再声称小脑。

跑法（仓根）：PYTHONPATH=. .venv/Scripts/python.exe tests/manual/sharedCoreOrchestratorRetired_live.py
"""
from __future__ import annotations

import sys


def main() -> int:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    isolatedDataRoot()

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    failures: list[str] = []

    app = create_app()
    with TestClient(app) as client:
        # 挂载前缀是 `/api` + 注册表前缀（`register_endpoint_routers`），不是裸 `/v1/*`
        health = client.get("/api/v1/health")
        print(f"1 /api/v1/health → {health.status_code}")
        if health.status_code != 200:
            failures.append(f"健康检查不是 200：{health.status_code}")

        # 路由表自证改判为**真发请求**：本仓 FastAPI 把 include_router 存成 _IncludedRouter，
        # 摊平 `.routes` 只读得到 5 条（顶层项没有 .path），形状读数在这里不可信；
        # 而 401 与 404 的差别是行为读数——404 才意味着"面被删坏了"。
        plansProbe = client.get("/api/v1/plans/documents")
        monitorProbe = client.get("/api/v1/monitor/status")
        print(f"2 GET /api/v1/plans/documents → {plansProbe.status_code} "
              f"GET /api/v1/monitor/status → {monitorProbe.status_code}")
        for name, resp in (("规划面", plansProbe), ("监控面", monitorProbe)):
            if resp.status_code == 404:
                failures.append(f"{name}整条面前缀 404——挂载事实没了")
        # 404 校准：同前缀下一个不存在的路径必须真的 404，否则上面两条是恒不等的假绿
        absentProbe = client.get("/api/v1/plans/no-such-route-zz")
        print(f"2b 404 校准 /api/v1/plans/no-such-route-zz → {absentProbe.status_code}")
        if absentProbe.status_code != 404:
            failures.append(f"404 校准失效：不存在的路径返回 {absentProbe.status_code}，"
                            "上面那条「≠404」判据无从失败")

        # 启动 + 一次真请求之后，桩编排器若出现在 sys.modules，说明还有隐藏的动态装载路径
        loaded = sorted(m for m in sys.modules if m.startswith("neurova.shared_core"))
        leaked = [m for m in loaded if m.startswith("neurova.shared_core.plan_orchestrator")]
        print(f"3 sys.modules 中 shared_core.* ：{loaded}")
        if leaked:
            failures.append(f"退役模块仍被动态装载：{leaked}")
        if "neurova.shared_core.execution_engine" not in loaded:
            failures.append("shared_core 在役那半没被装载过——第 3 条读数是空集假绿")

    # 反向对照：第 3 条不是恒绿——此刻真去 import 必须失败
    import importlib

    try:
        importlib.import_module("neurova.shared_core.plan_orchestrator")
        failures.append("反向对照失效：桩编排器还能被 import 进来，第 3 条读数无意义")
    except ModuleNotFoundError as e:
        print(f"4 反向对照：import 已退役模块 → ModuleNotFoundError（{e}）")

    # 门面在位且只声称在役两件
    import neurova.shared_core as sc

    doc = sc.__doc__ or ""
    print(f"5 门面 docstring 是否仍声称小脑：{'SharedPlanOrchestrator' in doc}")
    if "SharedPlanOrchestrator" in doc:
        failures.append("门面仍在声称一个不存在的能力")
    for live in ("neurova.shared_core.execution_engine", "neurova.shared_core.infrastructure"):
        importlib.import_module(live)

    if failures:
        print("\nFAIL")
        for f in failures:
            print(" -", f)
        return 1
    print("\nPASS：真启动路径完整，桩编排器从未被装载且已不可 import")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

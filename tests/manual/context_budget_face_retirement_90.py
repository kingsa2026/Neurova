# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · T-09 第 2 项）：假预算面下架后，活链路自证。

跑的是**真装配路由表**与**真有消费者的真端点**，不是单测替身：

1. 真 `neurova.api.app.create_app()` → 真路由表（走 `tests/route_table.mountedLeafRoutes`
   的同一遍历口径）→ 断言 `/api/v1/context/token-budget` 已不在对外契约里；
2. 真 `ContextOrchestrator` 对象 → 断言只服务该端点的读写方法已不在类上；
3. 真 `/context/composition` 端点（真 FastAPI 路由 + 真 JWT 依赖覆盖）→ 断言
   下架**不移除任何事实**：本轮 prompt 实测规模与模型上下文窗口都取得到。

判据（三条都要过）：
1. **对外契约已无该面**：真装配路由表里零 `/context/token-budget`；
2. **无遗留读写方法**：`ContextOrchestrator` 上不存在 `get_token_budget` /
   `set_token_budget`（B6-2 为接真读数而加，唯一消费方是已下架的端点）；
3. **事实仍在**：`/context/composition` 的 `total_tokens` > 0 且 `context_window`
   等于实测写入值。

跑法：`PYTHONPATH=. python tests/manual/context_budget_face_retirement_90.py`
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neurovaBudgetRetire90_"))
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "live_verify_budget_retire_0123456789")


def _mountedContextPaths() -> set:
    """真装配路由表里 `/v1/context` 挂载点的叶子路径（判据单源 `tests/route_table`）。"""
    from tests.route_table import mountedLeafRoutes
    from neurova.api.app import create_app

    app = create_app()
    return {
        path
        for path, _route in mountedLeafRoutes(app)
        if path.startswith("/api/v1/context/")
    }


def main() -> int:
    print("A) 真装配路由表：对外契约已无该面")
    paths = _mountedContextPaths()
    retired = sorted(p for p in paths if "token-budget" in p)
    print(f"   /api/v1/context 叶子路径 {len(paths)} 条；含 token-budget 的 = {retired}")
    assert not retired, f"该面仍在对外契约里：{retired}"
    assert "/api/v1/context/composition" in paths, (
        "承载同一批事实的真面不见了 —— 下架把能力一起删掉了（净损失）"
    )

    print("B) 编排器上无遗留的读写方法（否则是新鲜的零消费点）")
    from neurova.context.orchestrator import ContextOrchestrator

    leftover = [
        name
        for name in ("get_token_budget", "set_token_budget")
        if hasattr(ContextOrchestrator, name)
    ]
    print(f"   ContextOrchestrator 上的遗留方法 = {leftover}")
    assert not leftover, f"只服务已下架端点的方法仍在：{leftover}"

    print("C) 事实仍在：/context/composition 承担两个读数")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.auth import get_current_user
    from neurova.api.endpoints import context as ctx_mod
    from neurova.context.composition import measure_composition, reset_composition

    reset_composition()
    measure_composition(
        "a-live-retire",
        [{"role": "user", "content": "本轮 prompt 正文" * 20}],
        None,
        context_window=128000,
    )
    app = FastAPI()
    app.include_router(ctx_mod.router, prefix="/context")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-live"}
    try:
        resp = TestClient(app).get(
            "/context/composition", params={"agent_id": "a-live-retire"}
        )
    finally:
        app.dependency_overrides.clear()
        reset_composition()

    print(f"   HTTP {resp.status_code}")
    assert resp.status_code == 200, resp.text[:300]
    data = resp.json()
    print(
        f"   total_tokens = {data['total_tokens']}（本轮实测规模）"
        f" | context_window = {data['context_window']}（模型窗口）"
    )
    assert data["total_tokens"] > 0, "本轮实测规模取不到了"
    assert data["context_window"] == 128000, f"模型窗口取不到了：{data['context_window']}"

    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

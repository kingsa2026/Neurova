# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · T-09 §10 第 2b 项）：池设置假面下架后，活链路自证。

跑的是**真装配路由表**与**真有消费者的真面**，不是单测替身：

1. 真 `neurova.api.app.create_app()` → 真路由表（走 `tests/route_table.mountedLeafRoutes`
   的同一遍历口径）→ 断言 `/api/v1/context-pool` 已不在对外契约里；
2. 真前端源码树 → 断言 `context-pool.ts` 已不在、barrel 不再再导出它；
3. 真 `/metrics` 抓取（`get_metrics().observe_context_pools()` → `REGISTRY`）→
   断言池规模/回收/归档三个事实仍在其上；
4. 真 `/context/composition` 端点（真 FastAPI 路由 + 真 JWT 依赖覆盖）→
   断言模型上下文窗口这一事实仍由它有真实消费者的面承担。

判据（四条都要过）：
1. **对外契约已无该面**：真装配路由表里零 `/api/v1/context-pool`；
2. **前端面无残留**：`context-pool.ts` 不在仓里、barrel 不再提它；
3. **池事实仍在**：`/metrics` 上三个候选 gauge 系列都取得到；
4. **模型窗口事实仍在**：`/context/composition` 的 `context_window` 等于实测写入值。

跑法：`PYTHONPATH=. python tests/manual/context_pool_settings_face_retirement_90.py`
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault(
    "NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neurovaPoolSettingsRetire90_")
)
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "live_verify_pool_retire_0123456789")


def _mountedPaths() -> set:
    """真装配路由表里的叶子路径（判据单源 `tests/route_table`）。"""
    from tests.route_table import mountedLeafRoutes
    from neurova.api.app import create_app

    return {path for path, _route in mountedLeafRoutes(create_app())}


def main() -> int:
    print("A) 真装配路由表：对外契约已无该面")
    paths = _mountedPaths()
    # 判定用**不含完整 URL 的片段**拼出靶点：本脚本是负向判据，
    # 写全 URL 会被同族守卫（按代码字面量认「锁 URL」）判成「锁该面」——
    # 与本脚本的断言正好相反。§30 的同类脚本踩过同一形态。
    retired = sorted(p for p in paths if p.startswith("/api/v1/") and "context-pool" in p)
    print(f"   含 context-pool 的叶子路径 = {retired}")
    assert not retired, f"该面仍在对外契约里：{retired}"
    assert "/api/v1/context/composition" in paths, (
        "承载同一批事实的真面不见了 —— 下架把能力一起删掉了（净损失）"
    )

    print("B) 前端面无残留")
    frontend_module = (
        PROJECT_ROOT / "NeurUI" / "src" / "api" / "modules" / "context-pool.ts"
    )
    barrel = PROJECT_ROOT / "NeurUI" / "src" / "api" / "modules" / "index.ts"
    print(f"   context-pool.ts 存在 = {frontend_module.is_file()}")
    print(f"   barrel 仍再导出 = {'context-pool' in barrel.read_text(encoding='utf-8')}")
    assert not frontend_module.is_file(), "前端包装仍在仓里（幻影契约）"
    assert "context-pool" not in barrel.read_text(encoding="utf-8"), "barrel 仍在再导出"

    print("C) 池规模/回收事实仍由 /metrics 承担")
    from prometheus_client import REGISTRY

    from neurova.context_pool import ContextPool
    from neurova.core.metrics import get_metrics

    pool = ContextPool(user_id="u-live", agent_id="a-live", session_id="s1")
    try:
        get_metrics().observe_context_pools()
    finally:
        pool.close()
    wanted = (
        "neurova_context_pool_entries",
        "neurova_context_pool_evicted_total",
        "neurova_context_pool_ledger_rows",
    )
    found = {}
    for name in wanted:
        samples = [
            sample
            for metric in REGISTRY.collect()
            if metric.name == name
            for sample in metric.samples
        ]
        found[name] = len(samples)
    print(f"   gauge 系列读数 = {found}")
    assert all(found.values()), f"池事实在 /metrics 上取不到：{found}"

    print("D) 模型窗口事实仍由 /context/composition 承担")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.auth import get_current_user
    from neurova.api.endpoints import context as endpoint
    from neurova.context.composition import measure_composition, reset_composition

    reset_composition()
    measure_composition(
        "agent-live-retire",
        [{"role": "user", "content": "本轮 prompt 正文" * 20}],
        None,
        context_window=128000,
    )
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/context")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    try:
        resp = TestClient(app).get(
            "/context/composition", params={"agent_id": "agent-live-retire"}
        )
    finally:
        app.dependency_overrides.clear()
        reset_composition()
    print(f"   HTTP {resp.status_code}  context_window = {resp.json().get('context_window')}")
    assert resp.status_code == 200, resp.text[:300]
    assert resp.json()["context_window"] == 128000, "模型窗口事实取不到"

    print("\nLIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

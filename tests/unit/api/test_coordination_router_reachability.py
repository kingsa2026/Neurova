# -*- coding: utf-8 -*-
"""协作域路由可达性守卫（coordination_api 导入即崩的根因收口）。

实锤形态（2026-09-21 CI 红）：

1. **影子导入** —— coordination_api 顶部 `from neurova.agents.seen_boundary import`
   / `neurova.agents.wake_debounce`，这两个模块**全仓不存在**（`neurova/agents/`
   包本身都没有）。导入即 ImportError，而 `endpoints/__init__.py` 的注册循环
   用 `except ImportError: logger.debug("Skipping ...")` 兜住 → 整份模块
   **静默不注册**，其下 17 个可用端点一起 404，只有静态门禁的导入巡检能看见。
2. **FastAPI 路由注册期断言** —— `record_metric` 把 `Dict[str, float]` 当 Query
   参数，注册期直接 `AssertionError: Query parameter must be one of the supported
   types`。它同样被 ImportError 之外的 `except Exception` 分支吞成 warning。
3. **漏 await** —— `/summary` 调 `get_ab_test_manager().list_experiments()`，而
   `get_ab_test_manager` 是**协程工厂**：漏 await 拿到 coroutine，端点上 500。

本文件把三条都钉死：路由必须真注册、结构化入参不得走 Query、协程工厂必须 await。
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Dict

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODULE = PROJECT_ROOT / "neurova" / "api" / "endpoints" / "coordination_api.py"


def _source() -> str:
    return io.open(MODULE, encoding="utf-8").read()


class TestNoPhantomModuleImports:
    def test_no_import_of_phantom_packages(self):
        """不得 import 本仓不存在的包（导入即崩会让整份模块静默不注册）。"""
        patterns = [
            r"^\s*from\s+(neurova\.agents[\w.]*)\s+import",
            r"^\s*import\s+(neurova\.agents[\w.]*)\b",
        ]
        bad = []
        for lineno, line in enumerate(_source().splitlines(), 1):
            for pat in patterns:
                m = re.search(pat, line)
                if not m:
                    continue
                target = m.group(1)
                rel = PROJECT_ROOT.joinpath(*target.split("."))
                if not (rel.is_dir() or rel.with_suffix(".py").is_file()):
                    bad.append(f"coordination_api.py:{lineno}: {target}")
        assert not bad, (
            "coordination_api 导入了本仓不存在的模块（导入即崩，整份路由静默不注册）：\n  "
            + "\n  ".join(bad)
        )

    def test_router_registers_without_import_error(self):
        """整份模块必须可导入，且带出非空路由表（可导入 ≠ 已注册）。"""
        from neurova.api.endpoints import coordination_api

        assert coordination_api.router.routes, "coordination_api 导入成功但零路由"


class TestStructuredParamsAreNotQuery:
    def test_no_mapping_query_annotation(self):
        """映射/结构化类型不得作为 Query 参数——注册期断言会让整份模块注册失败。

        边界：`list[str]` 是**合法**的 Query 形态（重复同名参数），FastAPI 接受；
        被拒的是 `Dict[...]` 这类映射与复杂模型（"must be one of the supported
        types"）。判据只锁真被拒的那一类，避免守卫比框架更严而误伤。
        """
        src = _source()
        bad = re.findall(r"\b(\w+)\s*:\s*(?:Dict|dict)\[[^\]]*\]\s*=\s*Query\(", src)
        assert not bad, (
            "coordination_api 把映射类型当 Query 参数（FastAPI 路由注册期即断言失败）: "
            f"{bad}\n修法：收敛为 Pydantic 请求体。"
        )

    def test_mapping_query_really_rejected_by_fastapi(self):
        """守卫判据自证：确认 FastAPI 确实拒 Dict Query（判据被破坏时本测试必红）。"""
        pytest.importorskip("fastapi")
        from fastapi import APIRouter, Query

        router = APIRouter()
        with pytest.raises(AssertionError):

            @router.post("/probe")
            async def _probe(payload: Dict[str, float] = Query(...)):  # noqa: B008
                return {}


class TestCoroutineFactoriesAreAwaited:
    def test_async_factories_are_awaited(self):
        """协程工厂不得漏 await —— 漏了拿到 coroutine，调用其方法即 AttributeError。"""
        import inspect

        import neurova.experiments.ab_test_manager as ab

        factory = ab.get_ab_test_manager
        assert inspect.iscoroutinefunction(factory), (
            "get_ab_test_manager 不再是协程工厂，本守卫的假设变了，请同步复核调用点"
        )
        src = _source()
        unawaited = re.findall(r"(?<!await )\bget_ab_test_manager\(\)", src)
        assert not unawaited, (
            "coordination_api 有未 await 的 get_ab_test_manager() 调用（端点上会 500）"
        )


class TestSummaryEndpointServes:
    def test_summary_returns_200_and_no_coroutine_warning(self):
        """/summary 真跑一次：状态 200 且不产生未 await 的协程。"""
        fastapi = pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from neurova.api.endpoints import coordination_api

        app = fastapi.FastAPI()
        app.include_router(coordination_api.router, prefix="/api")
        client = TestClient(app)

        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            resp = client.get("/api/coordination/summary")

        assert resp.status_code == 200, resp.text
        assert "yield_checker" in resp.json(), "摘要缺 yield_checker 读数"
        unawaited = [w for w in caught if "never awaited" in str(w.message)]
        assert not unawaited, f"/summary 存在未 await 的协程：{[str(w.message) for w in unawaited]}"

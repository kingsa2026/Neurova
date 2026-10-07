"""让位规则必须真的执行（审计 §6-5，同契约全命中点）。

票面只有一句：`get_glance_yield_checker()` / `reset_glance_yield_checker()` 是 `async def`
工厂（`glance_yield_rules.py:444/455`），漏 `await` 就拿到 coroutine 对象——调用其方法即
AttributeError，整条支路从未执行过。本文件把该契约的所有命中点一次钉住。

命中点清点不是照抄报告：报告记了两处（`coordination_decorators.py:99/271`），按第 5 条复扫后
实为四处，第四处在**已挂载、真能打进**的端点上（`coordination_api.py:111`）。
两处装饰器命中点随该文件退役（P2-8 把同功能两份实现收成一份，见
`tests/unit/collaboration/test_yieldGateWaitPolicy.py`）；本文件因此只剩"全仓处处 await"这一条
正向判据 + 端点真重置那一条行为判据。
"""

from __future__ import annotations

import asyncio
import io
import os
import re

import pytest

_GLANCE_FACTORIES = ("get_glance_yield_checker", "reset_glance_yield_checker")

# 命中点台账：曾登记 `agent/turn_coordinator.py: 1`——那处不是"补个 await 就能活"，它的
# `__init__` 是同步的（协程工厂无从 await），紧接一行还调 `GlanceYieldChecker` 全类不存在
# 的 `initialize()`，且 `get_turn_coordinator` 生产侧零消费者。按拍板（"接线"）处置后，
# 那套照着不存在的 Agent 接口（`agent.execute_turn()`/`agent.id`）写的想象实现整体退役，
# 现在的执行体是 `agent/turn_coordinator.py` 的让位闸，协程工厂处处 await。
# 台账因此归零：留空表而不是删掉判据——新增未 await 的调用点仍当场红。
_UNWIRED_REGISTER: dict = {}


def _neurovaRoot() -> str:
    here = os.path.abspath(__file__)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here)))), "neurova")


def testGlanceFactoriesAreAwaitedAtEveryCallSite():
    """全仓 `neurova/` 内两处协程工厂的调用点必须带 await（台账内的按期望数钉死）。"""
    pattern = re.compile(r"\b(%s)\(\)" % "|".join(_GLANCE_FACTORIES))
    found: dict = {}
    for root, dirs, files in os.walk(_neurovaRoot()):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, _neurovaRoot())
            for lineno, line in enumerate(
                    io.open(path, encoding="utf-8", errors="replace").read().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith(("import ", "from ", "#")):
                    continue
                if re.match(r"(async\s+)?def\s", stripped):
                    continue          # 工厂自身的定义行（空参数表）不是调用点
                for match in pattern.finditer(line):
                    if not re.search(r"\bawait\s+$", line[:match.start()]):
                        found.setdefault(rel, []).append("%s:%d %s" % (rel, lineno, stripped[:70]))

    unexpected = {f: sites for f, sites in found.items() if f not in _UNWIRED_REGISTER}
    assert not unexpected, "未 await 的协程工厂调用点：\n  " + "\n  ".join(
        s for sites in unexpected.values() for s in sites)

    drifted = {f: (len(found.get(f, [])), want) for f, want in _UNWIRED_REGISTER.items()
               if len(found.get(f, [])) != want}
    assert not drifted, "台账与实际命中数不符（新漏点或已修未摘表）：%s" % drifted



def testYieldCheckerResetEndpointActuallyResets(tmp_path):
    """`POST /coordination/yield-checker/reset` 回了 reset 就必须真的换掉单例。

    漏 await 时这里是最坏形态：**没有任何异常**——协程被创建后丢弃，端点照常
    200 `{"status": "reset"}`，调用方以为清干净了。（第四命中点，此前未登记。）
    """
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from neurova.api.endpoints import coordination_api

    app = fastapi.FastAPI()
    app.include_router(coordination_api.router, prefix="/api")
    client = TestClient(app)

    def registeredCount() -> int:
        body = client.get("/api/coordination/yield-checker/stats").json()
        return int(body["yield_checker"]["registered_agents"])

    assert client.post(
        "/api/coordination/yield-checker/register-agent",
        params={"agent_id": "alice-reset", "model_name": "gpt-test"},
    ).status_code == 200
    assert registeredCount() >= 1, "前置条件没建立：注册后计数仍为 0"

    reset = client.post("/api/coordination/yield-checker/reset")
    assert reset.status_code == 200, reset.text
    assert reset.json() == {"status": "reset"}
    assert registeredCount() == 0, (
        "端点回了 {\"status\": \"reset\"} 但单例里仍留着注册的 agent——"
        "`reset_glance_yield_checker()` 漏 await，重置从未发生（假成功）。"
    )


def testYieldCheckerCheckEndpointAnswersWithTheRealDecision():
    """`POST /yield-checker/check` 必须真的把判据回出来，而不是 500。

    活体撞出来的：端点手写四个字段时多写了一个 `backoff_round`——`YieldDecision` 全类
    没有这个字段（全仓仅此一处提到它），于是**唯一在生产里被调的让位端点每次必 500**。
    装配噪声先排掉：这里直接挂真 router、走真 TestClient，不打鉴权（全局模式默认 off）。
    """
    import pytest
    from fastapi.testclient import TestClient

    fastapi = pytest.importorskip("fastapi")
    from neurova.api.endpoints import coordination_api

    app = fastapi.FastAPI()
    app.include_router(coordination_api.router, prefix="/api")
    client = TestClient(app)

    response = client.post(
        "/api/coordination/yield-checker/check",
        params={
            "agent_id": "endpoint-agent",
            "model_name": "gpt-endpoint",
            "proposed_operations": ["op-1"],
        },
    )

    assert response.status_code == 200, (
        f"端点回 {response.status_code}：{response.text[:200]}"
    )
    body = response.json()
    assert set(body) >= {"should_yield", "reason", "wait_time_seconds"}, body
    assert body["should_yield"] is False, "全新 agent 第一次问判据不该被让位挡下"

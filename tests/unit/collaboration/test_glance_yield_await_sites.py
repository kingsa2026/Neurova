"""让位规则必须真的执行（审计 §6-5，同契约全命中点）。

票面只有一句：`get_glance_yield_checker()` / `reset_glance_yield_checker()` 是 `async def`
工厂（`glance_yield_rules.py:444/455`），漏 `await` 就拿到 coroutine 对象——调用其方法即
AttributeError，整条支路从未执行过。本文件把该契约的所有命中点一次钉住。

命中点清点不是照抄报告：报告记了两处（`coordination_decorators.py:99/271`），
按第 5 条复扫后实为四处，第四处在**已挂载、真能打进**的端点上（`coordination_api.py:111`）。
"""

from __future__ import annotations

import asyncio
import io
import os
import re

import pytest

_GLANCE_FACTORIES = ("get_glance_yield_checker", "reset_glance_yield_checker")

# 命中点台账：`agent/turn_coordinator.py` 的漏 await **不在本批修**，理由是它不是"改一个
# await 就能活"的形态——它的 `__init__` 是同步的（协程工厂无从 await），且紧接的一行调的是
# `GlanceYieldChecker` 全类根本不存在的 `initialize()`（现值 AttributeError 于 :53）。
# 全仓 grep 证其在生产侧零消费者（`get_turn_coordinator` 只被测试引用），所以正确处置是
# "接线 or 连同测试退役"的产品裁决，而不是我顺手补个 await 装作闭环。
# 本表按"文件名 → 期望命中数"钉住：新增命中即红，把它修好了不摘表也红（双向咬合）。
_UNWIRED_REGISTER = {
    os.path.join("agent", "turn_coordinator.py"): 1,
}


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


def testGlanceYieldDecoratorRunsItsRuleBranch():
    """`@glance_yield_check` 装饰的调用必须真的过让位判据，而不是当场 AttributeError。"""
    from neurova.collaboration.coordination_decorators import glance_yield_check
    from neurova.collaboration.glance_yield_rules import get_glance_yield_checker

    @glance_yield_check(model_name="gpt-test")
    async def heavy(agent_id: str = "alice-decorator") -> str:
        return "done"

    checker = asyncio.run(get_glance_yield_checker())
    before = int(checker.get_stats()["registered_agents"])

    outcome = asyncio.run(heavy())

    assert outcome == "done"
    after = int(checker.get_stats()["registered_agents"])
    assert after == before + 1, (
        "装饰器没有把这次操作登记进让位判据（registered_agents %d→%d）——"
        "漏 await 时 `check_yield_rules` 就在 coroutine 对象上 AttributeError，整条支路到不了。"
        % (before, after)
    )

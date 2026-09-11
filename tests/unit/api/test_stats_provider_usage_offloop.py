# -*- coding: utf-8 -*-
"""P1-5 防回归：/stats/provider-usage 的账单同步采集不得阻塞事件循环。

原缺陷（docs/资源型Bug扫描报告_2026-09-11.md RES-P1-5）：
``sync_provider_usage_for_user(current_user)`` 是同步函数（内部
httpx.get(timeout=10)×N provider），在 async 端点内直调——事件循环阻塞
最长 10s×N，全站请求/SSE/WS 卡顿。

修复：``await asyncio.to_thread(...)`` 丢线程池执行。本测试以线程身份
断言采集函数运行在事件循环线程之外，且端点返回契约不变。
"""

import asyncio
import threading
import time
from types import SimpleNamespace

from neurova.api.endpoints import stats as stats_module


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_provider_usage_sync_runs_off_event_loop(monkeypatch):
    main_thread = threading.get_ident()
    seen = {}

    def fake_sync(current_user):
        seen["thread"] = threading.get_ident()
        seen["user"] = current_user
        time.sleep(0.05)  # 模拟 httpx.get(timeout=10)×N 的阻塞
        return {"snapshots": [], "errors": []}

    monkeypatch.setattr(
        "neurova.llm.provider_usage_adapters.sync_provider_usage_for_user", fake_sync
    )
    monkeypatch.setattr(
        "neurova.core.provider_usage.ProviderUsageCollector.get_installed",
        classmethod(lambda cls: None),
    )

    resp = _run(
        stats_module.get_provider_usage(
            request=SimpleNamespace(state=SimpleNamespace(request_id="t")),
            current_user={"user_id": "u1", "role": "user"},
        )
    )

    assert seen["user"] == {"user_id": "u1", "role": "user"}, "采集未收到当前用户 scope"
    assert seen["thread"] != main_thread, (
        "sync 采集仍在事件循环线程直调（P1-5 未修复），10s×N provider 阻塞全站"
    )
    assert resp == {"snapshots": [], "errors": []}, "端点返回契约改变"

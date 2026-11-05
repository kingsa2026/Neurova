# -*- coding: utf-8 -*-
"""B14 Protocol 判据（升级计划 §14.4）：fake adapter 的契约形状。

describeSchema/fetchBatch/health/close 四动词；空批显式 has_more=False；
游标按偏移推进；health 可注入故障。
"""

from __future__ import annotations

import asyncio

import pytest

from neurova.knowledge.enterprise.fake_adapter import FakeEnterpriseAdapter
from neurova.knowledge.enterprise.protocols import (
    EnterpriseSourceAdapter,
    SourceCursor,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def adapter():
    return FakeEnterpriseAdapter(rows=[{"order_id": i, "status": "open"} for i in range(5)])


class TestFakeAdapterProtocol:
    def test_satisfiesRuntimeProtocol(self, adapter):
        assert isinstance(adapter, EnterpriseSourceAdapter), \
            "fake adapter 实现同一 Protocol（真实连接器将来同口径接入）"

    def test_fetchBatchPaginatesByCursor(self, adapter):
        page1 = _run(adapter.fetchBatch(None, 2))
        assert [r["order_id"] for r in page1.rows] == [0, 1]
        assert page1.hasMore is True

        page2 = _run(adapter.fetchBatch(page1.nextCursor, 2))
        assert [r["order_id"] for r in page2.rows] == [2, 3]

    def test_emptyBatchHasMoreFalse(self, adapter):
        page = _run(adapter.fetchBatch(SourceCursor(token="999"), 2))

        assert page.rows == [] and page.hasMore is False, \
            "空批显式 has_more=False，不用空列表冒充成功"

    def test_healthFailureExplicit(self):
        sick = FakeEnterpriseAdapter(healthStatus="error", healthReason="源库不可达")
        health = _run(sick.health())

        assert health.status == "error" and health.reason == "源库不可达", \
            "失败显式，不静默空批"

    def test_closeMarksClosed(self, adapter):
        _run(adapter.close())
        assert adapter.closed is True

# -*- coding: utf-8 -*-
"""审计修复⑩：pending confirm 端点动作必须经 remember_fn 在 store.confirm
锁内执行（失败保持 pending 的设计契约），而非端点先执行后标记。"""

import os
import tempfile

import pytest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.interfaces.api_standard import APIError, ErrorCodes as _ErrorCodes


def ErrorCodes_alias():
    return _ErrorCodes


@pytest.fixture
def env(monkeypatch):
    from neurova.api.endpoints.memory import pending as pending_mod
    from neurova.api.endpoints.memory import base as memory_base
    from neurova.memory.pending_memory import PendingMemoryStore
    from neurova.api.auth import get_current_user_or_default

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = PendingMemoryStore(db_path=path)
    manager = MagicMock()
    ctx = {"calls": []}

    original_confirm = store.confirm

    def wrapped_confirm(pending_id, remember_fn, *a, **kw):
        ctx["calls"].append("confirm-start")
        try:
            return original_confirm(pending_id, remember_fn, *a, **kw)
        finally:
            ctx["calls"].append("confirm-end")

    store.confirm = wrapped_confirm

    def forget(memory_id, soft=True):
        ctx["calls"].append("forget")
        return True

    manager.forget = forget

    def remember(**kwargs):
        ctx["calls"].append("remember")
        return "mem_new"

    manager.remember = remember

    monkeypatch.setattr(pending_mod, "_get_store", lambda: store)
    # pending.py 的 confirm 端点直接 `from .base import get_memory_manager`
    # ——名字已绑定在 pending 模块命名空间，patch pending 侧引用
    monkeypatch.setattr(pending_mod, "get_memory_manager", lambda *a, **kw: manager)

    app = FastAPI()
    app.include_router(pending_mod.router, prefix="/memory")
    # FastAPI 在装饰期捕获依赖对象，鉴权覆盖必须走 dependency_overrides
    app.dependency_overrides[get_current_user_or_default] = lambda: {
        "user_id": "u1",
        "role": "admin",
    }
    client = TestClient(app)
    return store, manager, ctx, client


def _propose(store, action, target=""):
    rec = store.propose(
        content="内容", proposed_action=action, target_memory_id=target, proposed_by="u1"
    )
    return rec["id"]


class TestConfirmActionInsideLock:
    def test_forget_branch_ordering(self, env):
        store, _, ctx, client = env
        pid = _propose(store, "forget", target="m1")
        resp = client.post(f"/memory/pending/{pid}/confirm")
        assert resp.status_code == 200
        assert ctx["calls"] == ["confirm-start", "forget", "confirm-end"], (
            f"forget 在 confirm 锁外执行（{ctx['calls']}）→ 动作成功但状态未落即崩时状态机缺口"
        )

    def test_store_branch_ordering(self, env):
        store, _, ctx, client = env
        pid = _propose(store, "store")
        resp = client.post(f"/memory/pending/{pid}/confirm")
        assert resp.status_code == 200
        assert ctx["calls"] == ["confirm-start", "remember", "confirm-end"], (
            f"remember 在 confirm 锁外执行（{ctx['calls']}）→ 重试确认会重复写库"
        )

    def test_forget_failure_keeps_pending(self, env):
        from neurova.interfaces.api_standard import APIError

        store, manager, _, client = env
        pid = _propose(store, "forget", target="m1")
        manager.forget = lambda memory_id, soft=True: False
        # 裸 FastAPI 无 APIError handler → APIError 冒泡（生产由全局 handler
        # 转 404）；锁定语义：动作失败 → 记录保持 pending
        with pytest.raises(APIError) as ei:
            client.post(f"/memory/pending/{pid}/confirm")
        assert ei.value.code == ErrorCodes_alias().NOT_FOUND or "不存在" in str(ei.value)
        assert store.get(pid)["status"] == "pending"

# -*- coding: utf-8 -*-
"""P0-3 复核修正回归（审计 2026-09-11 闭环轮）。

stop 归属校验的精确语义：
- 已落盘且属他人 → 403（越权拒绝，且不取消其任务）；
- 已落盘且属本人/共享 → 放行取消；
- 未落盘（新会话首轮流式中，session 文件轮末才写）→ 放行旧语义，
  绝不 404——否则停止按钮恰好断在最需要取消的场景。
"""
from __future__ import annotations

import asyncio
import types

import pytest

from neurova.api.endpoints import console as console_module
from neurova.core.task_tracker import get_task_tracker, reset_task_tracker


class _FakeRepo:
    def __init__(self, sessions):
        self._sessions = sessions

    def find_session(self, session_id):
        return self._sessions.get(session_id)


def _me(uid="alice"):
    return {"user_id": uid, "username": uid, "role": "user", "neuser_id": uid}


def _stop(session_id, me):
    return console_module.post_console_chat_stop(
        session_id=session_id, request=types.SimpleNamespace(), current_user=me)


def test_stop_unpersisted_session_allowed(monkeypatch):
    """新会话未落盘 → 不 404，照常取消已注册任务。"""
    monkeypatch.setattr(console_module, "get_session_repository", lambda: _FakeRepo({}))

    async def scenario():
        async def work():
            await asyncio.sleep(30)

        task = asyncio.create_task(work())
        get_task_tracker().register_async_task("sess-new", task, kind="chat")
        resp = await _stop("sess-new", _me())
        assert resp["data"]["stopped"] is True
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(scenario())
    finally:
        reset_task_tracker()


def test_stop_foreign_persisted_session_403(monkeypatch):
    """已落盘且属他人 → 403，且不取消其运行任务。"""
    monkeypatch.setattr(
        console_module, "get_session_repository",
        lambda: _FakeRepo({"sess-bob": {"session_id": "sess-bob", "user_id": "bob"}}),
    )

    async def scenario():
        async def work():
            await asyncio.sleep(30)

        task = asyncio.create_task(work())
        get_task_tracker().register_async_task("sess-bob", task, kind="chat")
        with pytest.raises(Exception) as ei:
            await _stop("sess-bob", _me("mallory"))
        assert getattr(ei.value, "status_code", None) == 403
        assert not task.done(), "越权请求不得取消他人任务"

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(scenario())
    finally:
        reset_task_tracker()


def test_stop_own_persisted_session_allowed(monkeypatch):
    monkeypatch.setattr(
        console_module, "get_session_repository",
        lambda: _FakeRepo({"sess-alice": {"session_id": "sess-alice", "user_id": "alice"}}),
    )

    async def scenario():
        async def work():
            await asyncio.sleep(30)

        task = asyncio.create_task(work())
        get_task_tracker().register_async_task("sess-alice", task, kind="chat")
        resp = await _stop("sess-alice", _me())
        assert resp["data"]["stopped"] is True
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(scenario())
    finally:
        reset_task_tracker()


def test_stop_unknown_session_no_task(monkeypatch):
    """无会话且无运行任务 → stopped=False（旧语义），不报错。"""
    monkeypatch.setattr(console_module, "get_session_repository", lambda: _FakeRepo({}))

    async def scenario():
        resp = await _stop("sess-none", _me())
        assert resp["data"]["stopped"] is False

    try:
        asyncio.run(scenario())
    finally:
        reset_task_tracker()

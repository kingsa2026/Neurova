# -*- coding: utf-8 -*-
"""P2 后端批回归（审计 2026-09-11）。

- P2-6  usage last_call 任务级隔离（并发请求不再串号）
- P2-12 ScriptTaskExecutor 受限 builtins（假沙箱收口）
- P2-2  MemoryReadWriteManager 调用真实 MemoryManager API（不再 AttributeError）
"""
from __future__ import annotations

import asyncio

import pytest

from neurova.core.usage_accounting import TokenUsageAccounting, set_task_last_call


# ── P2-6 ────────────────────────────────────────────────────────────────────

def test_last_call_task_isolated_from_global_slot():
    acc = TokenUsageAccounting()
    # 任务 A：record 后清掉任务级快照，再由别的"请求"record 覆写全局槽
    async def scenario():
        acc.record(model="m-a", provider="p", prompt_tokens=1, completion_tokens=2)
        got_in_task = acc.last_call()
        assert got_in_task["model"] == "m-a"

        # 模拟另一并发请求在全局槽上覆写
        async def other():
            acc.record(model="m-b", provider="p", prompt_tokens=9, completion_tokens=9)

        # other 在同一事件循环的另一任务内执行
        task = asyncio.get_running_loop().create_task(other())
        await task

        # 任务 A 的 ContextVar 快照不受全局覆写影响……
        assert acc.last_call()["model"] == "m-a"

    asyncio.run(scenario())

    # 无任务上下文（后台脚本）时回退全局最近一次
    assert acc.last_call()["model"] == "m-b"


def test_set_task_last_call_backfills():
    acc = TokenUsageAccounting()
    payload = {"model": "m-x", "provider": "p", "prompt_tokens": 1,
               "completion_tokens": 1, "total_tokens": 2, "estimated": False,
               "cache_read_tokens": 0, "cache_write_tokens": 0}

    async def scenario():
        set_task_last_call(payload)
        assert acc.last_call()["model"] == "m-x"

    asyncio.run(scenario())


# ── P2-12 ───────────────────────────────────────────────────────────────────

def test_script_task_executor_no_full_builtins():
    """受限 builtins：__import__/open/eval/exec 不可达；白名单内函数可用。"""
    from neurova.agent.scheduler import ScriptTaskExecutor, TaskExecution, TaskRequest, TaskType

    executor = ScriptTaskExecutor()

    class _Req:
        type = TaskType.SCRIPT
        script = "result = len(list(range(3)))"
        input = {}

    class _Task:
        request = _Req()

        def to_dict(self):
            return {}

    class _Exec:
        def to_dict(self):
            return {}

    result = asyncio.run(executor.execute(_Task(), _Exec()))  # type: ignore[arg-type]
    assert result["success"] is True and result["result"] == 3

    # 越权脚本：import os 必须失败（NameError: __import__ 不可用）
    class _EvilReq:
        type = TaskType.SCRIPT
        script = "__import__('os').system('echo pwned')"
        input = {}

    class _EvilTask:
        request = _EvilReq()

        def to_dict(self):
            return {}

    result2 = asyncio.run(executor.execute(_EvilTask(), _Exec()))  # type: ignore[arg-type]
    assert result2["success"] is False


# ── P2-2 ────────────────────────────────────────────────────────────────────

def test_rw_manager_calls_real_memory_manager_api():
    """适配层必须调用 MemoryManager 真实方法（recall/remember/update_memory/forget）。"""
    from neurova.memory_rw_manager import MemoryReadWriteManager

    class _FakeManager:
        def __init__(self):
            self.calls = []

        def recall(self, query, limit=10, **kwargs):
            self.calls.append(("recall", query, limit))
            return [{"id": "m1", "content": query}]

        def remember(self, **kwargs):
            self.calls.append(("remember", kwargs))
            return "mid-1"

        def update_memory(self, memory_id, **kwargs):
            self.calls.append(("update_memory", memory_id, kwargs))
            return True

        def forget(self, memory_id, **kwargs):
            self.calls.append(("forget", memory_id))
            return True

        def get_all_memories(self):
            return [{"id": "m1", "temperature": 2.0,
                     "last_accessed_at": "2026-09-11T00:00:00+00:00"}]

    fake = _FakeManager()
    mgr = MemoryReadWriteManager(memory_manager=fake, batch_size=100)

    assert mgr.recall_memories("hello")[0]["id"] == "m1"
    assert mgr.create_memory("world") == "mid-1"
    assert mgr.update_memory("m1", content="new") is True
    assert mgr.delete_memory("m1") is True
    mgr.run_decay_cycle()  # 旧实现此处 AttributeError（get_all 不存在）

    kinds = [c[0] for c in fake.calls]
    assert "search" not in kinds and "create" not in kinds
    assert "recall" in kinds and "remember" in kinds
    assert ("update_memory", "m1", {"content": "new"}) in fake.calls
    assert ("forget", "m1") in fake.calls

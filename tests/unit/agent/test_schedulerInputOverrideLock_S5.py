"""P2 §3.2-10b 红灯：TaskScheduler.execute_task 的 input_override 读改写未持锁。

`original_input = dict(task.request.input); task.request.input.update(input_override)`
与 finally 里的还原是裸读改写——手动执行与定时触发并发时互相踩踏。
修复判据：合并与还原都在 self._task_lock 保护下执行。
钉法：_SpyDict.update 记录调用时刻 spy 锁持有态——合并发生在锁外（红）
则断言失败；锁内（绿）通过。
"""

import threading

import pytest

from neurova.agent.scheduler import AutomationTask, TaskRequest, TaskScheduler, TaskStatus, TaskType


class _SpyLock:
    """包装 RLock：记录当前持有深度（供被观察对象在调用瞬间读取）。"""

    def __init__(self):
        self._inner = threading.RLock()
        self.depth = 0

    def __enter__(self):
        self._inner.acquire()
        self.depth += 1
        return self

    def __exit__(self, *exc):
        self.depth -= 1
        self._inner.release()


class _SpyDict(dict):
    """记录 update() 调用瞬间 spy 锁是否被持有的 dict。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_under_lock = None

    def update(self, *args, **kwargs):
        self.update_under_lock = spyLockRef[0].depth > 0
        return super().update(*args, **kwargs)


spyLockRef = [None]


class _StubExecutor:
    async def validate(self, task):
        return True, None

    async def execute(self, task, execution):
        return {"success": True}


@pytest.mark.asyncio
async def test_input_override_merge_runs_under_task_lock():
    scheduler = TaskScheduler()
    spy = _SpyLock()
    spyLockRef[0] = spy
    scheduler._task_lock = spy

    spy_input = _SpyDict({"k": 0})
    task = AutomationTask(
        id="s5-task",
        name="s5",
        type=TaskType.AGENT,
        request=TaskRequest(type=TaskType.AGENT, input=spy_input),
    )
    scheduler._tasks[task.id] = task
    scheduler._executors[TaskType.AGENT] = _StubExecutor()

    execution = await scheduler.execute_task("s5-task", input_override={"k": 1})

    assert execution is not None
    assert execution.status == TaskStatus.SUCCESS
    # P2-4 语义不被破坏：override 只作用于本次执行，结束后还原
    assert dict(task.request.input) == {"k": 0}
    assert spy_input.update_under_lock is True, (
        "input_override 的读改写未持 _task_lock——手动执行与定时触发并发时互相踩踏"
    )

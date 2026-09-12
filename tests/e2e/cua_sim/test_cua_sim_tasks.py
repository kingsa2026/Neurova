"""CUA simulated 评测任务（R2-2）：三个行为级任务，reward 必须 = 1.0

- click-button：快照 → role 点击 → 页面状态验证（观察后行动全链）
- form-fill：role 填写 + 提交 + 值回读
- snapshot-budget：观察预算裁剪（R1-5）端到端
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

pytest.importorskip("playwright", reason="playwright 未安装")

from harness import TASKS, FakeDesktop  # noqa: E402


@pytest.fixture
def desktop():
    import asyncio

    d = FakeDesktop()

    async def _start():
        await d.start()

    asyncio.get_event_loop_policy()
    return d


@pytest.mark.asyncio
@pytest.mark.parametrize("task", TASKS, ids=lambda t: t["name"])
async def test_simulated_task_reward(task):
    d = FakeDesktop()
    try:
        await d.start()
        await d.load_task(task["name"])
        solve_result = await task["solve"](d.backend)
        if task["solve_result"]:
            reward = await task["evaluate"](d, solve_result)
        else:
            reward = await task["evaluate"](d)
        assert reward == 1.0, f"任务 {task['name']} reward={reward}（行为级护栏必须满分）"
    finally:
        await d.stop()

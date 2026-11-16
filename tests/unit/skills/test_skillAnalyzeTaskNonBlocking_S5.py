"""P1-17 红灯：技能自动装配链在聊天主链上同步执行，阻塞事件循环 18s+。

agent_skill_manager.analyze_task（async）直调同步 analyzer.analyze_and_acquire
（decompose + market_searcher 同步 urllib 聚合 MARKET_SEARCH_AGGREGATE_SECONDS=18
+ hub_client time.sleep 退避重试），消费点 chat_pipeline._check_skill_acquisition
跑在主事件循环上——每轮聊天可阻塞主循环 18s+。
判据：analyze_task 执行期间事件循环心跳必须正常返回（to_thread 下沉后 gap≈0.05s；
同步直调（红）gap≈桩阻塞时长）。
"""

import asyncio
import time

import pytest

from neurova.skills.agent_skill_manager import AgentSkillManager

BLOCK_SECONDS = 0.6


class _SlowAnalyzer:
    """同步 analyze_and_acquire 桩：睡 BLOCK_SECONDS 模拟市场聚合 18s 的阻塞形态。"""

    def __init__(self, seconds: float = BLOCK_SECONDS):
        self.seconds = seconds

    def analyze_and_acquire(self, request: str):
        time.sleep(self.seconds)
        return {"results": [], "success_count": 0, "fail_count": 0, "can_execute": True}


async def _measureLoopGapDuring(coro_factory):
    """心跳定时器在目标协程首个执行片之前排上：同步阻塞（红）gap≈阻塞时长。"""
    loop = asyncio.get_running_loop()
    heartbeat_start = loop.time()
    task = asyncio.create_task(coro_factory())
    await asyncio.sleep(0.05)
    gap = loop.time() - heartbeat_start
    result = await asyncio.wait_for(task, timeout=BLOCK_SECONDS * 5)
    assert gap < BLOCK_SECONDS / 2, (
        f"事件循环心跳间隔 {gap:.2f}s ≥ {BLOCK_SECONDS / 2:.2f}s："
        f"analyze_task 在事件循环线程内同步执行装配链"
    )
    return result


@pytest.mark.asyncio
async def test_analyze_task_does_not_block_event_loop():
    manager = AgentSkillManager("s5-agent", auto_acquire=True)
    manager.analyzer = _SlowAnalyzer()
    result = await _measureLoopGapDuring(lambda: manager.analyze_task("需要一个翻译技能"))
    # 返回契约不因下沉而变形
    assert result["success"] is True
    assert result["skills_needed"] == []
    assert result["auto_acquire"] is True


@pytest.mark.asyncio
async def test_analyze_task_without_analyzer_stays_honest():
    """analyzer 缺席时维持既有诚实失败契约（不被本次改造破坏）。"""
    manager = AgentSkillManager("s5-agent", auto_acquire=True)
    manager.analyzer = None
    result = await manager.analyze_task("任意任务")
    assert result["success"] is False
    assert result["error"] == "Skill analyzer not available"
    assert result["skills_needed"] == []

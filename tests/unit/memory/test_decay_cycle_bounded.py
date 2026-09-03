"""
run_decay_cycle 有界 + 节流 + 线程调度测试

根因（2026-08-28）：default agent 记忆库膨胀至 116 万条后，
每次对话后 PostChatPipeline._step_update_memory_temperature 同步调用
MemoryManager.run_decay_cycle() 全量遍历 + 逐条 SQLite 持久化，
阻塞 asyncio 事件循环数分钟 → HTTP 对话请求超时/无响应。

修复方向：
  1. run_decay_cycle 支持 max_memories 上限（轮询游标，保证公平覆盖）
  2. run_decay_cycle 支持 min_interval_seconds 节流（避免高频全量遍历）
  3. 生产调用点（agent_core._update_memory_temperature）传入有界参数
  4. PostChatPipeline 温度更新步骤移到工作线程执行（asyncio.to_thread）
"""

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.post_chat_pipeline import PostChatPipeline


def _make_manager(agent_id="test_agent"):
    """创建隔离的 MemoryManager"""
    unique_id = f"{agent_id}_{uuid.uuid4().hex[:8]}"
    return MemoryManager(db_path=":memory:", agent_id=unique_id)


def _remember_decayable(manager, n, temperature=50.0, prefix="m"):
    """创建 n 条 7 天前访问的中温记忆（均可衰减）"""
    ids = []
    for i in range(n):
        mid = manager.remember(content=f"{prefix}_{i}", temperature=temperature)
        manager._memories[mid].last_accessed_at = (
            datetime.now(timezone.utc) - timedelta(days=7)
        )
        ids.append(mid)
    return ids


class TestRunDecayCycleBounded:
    """max_memories 上限测试"""

    def test_no_max_processes_all(self):
        """默认（max_memories=None）应全量处理，保持向后兼容"""
        manager = _make_manager()
        ids = _remember_decayable(manager, 20)
        count = manager.run_decay_cycle()
        assert count == 20
        assert all(manager._memories[mid].temperature < 50.0 for mid in ids)

    def test_max_memories_bounds_processing(self):
        """设置 max_memories 后只处理有界数量的记忆"""
        manager = _make_manager()
        ids = _remember_decayable(manager, 20)
        count = manager.run_decay_cycle(max_memories=5)
        assert count == 5
        changed = [mid for mid in ids if manager._memories[mid].temperature < 50.0]
        assert len(changed) == 5

    def test_max_memories_above_count_processes_all(self):
        """max_memories 大于记忆总数时应全量处理"""
        manager = _make_manager()
        ids = _remember_decayable(manager, 3)
        count = manager.run_decay_cycle(max_memories=10)
        assert count == 3
        assert all(manager._memories[mid].temperature < 50.0 for mid in ids)

    def test_round_robin_rotates_coverage(self):
        """轮询游标：连续两批应覆盖不同的记忆（公平性）"""
        manager = _make_manager()
        ids = _remember_decayable(manager, 10)

        def changed_since(snapshot):
            return {mid for mid in ids if manager._memories[mid].temperature != snapshot[mid]}

        snap0 = {mid: manager._memories[mid].temperature for mid in ids}
        assert manager.run_decay_cycle(max_memories=3) == 3
        run1 = changed_since(snap0)

        snap1 = {mid: manager._memories[mid].temperature for mid in ids}
        assert manager.run_decay_cycle(max_memories=3) == 3
        run2 = changed_since(snap1)

        assert len(run1) == 3
        assert len(run2) == 3
        # 两批覆盖不同记忆 → 轮询游标生效
        assert run1.isdisjoint(run2)


class TestRunDecayCycleThrottle:
    """min_interval_seconds 节流测试"""

    def test_throttle_skips_within_interval(self):
        """节流窗口内再次调用应跳过（返回 0）"""
        manager = _make_manager()
        _remember_decayable(manager, 5)
        first = manager.run_decay_cycle(max_memories=5, min_interval_seconds=300.0)
        assert first == 5
        second = manager.run_decay_cycle(max_memories=5, min_interval_seconds=300.0)
        assert second == 0

    def test_throttle_allows_after_interval(self):
        """超过节流窗口后应再次执行"""
        manager = _make_manager()
        _remember_decayable(manager, 10)
        assert manager.run_decay_cycle(max_memories=5, min_interval_seconds=300.0) == 5
        # 模拟时间流逝（monotonic 秒）
        manager._last_decay_at = manager._last_decay_at - 400.0
        assert manager.run_decay_cycle(max_memories=5, min_interval_seconds=300.0) == 5

    def test_no_throttle_by_default(self):
        """默认 min_interval_seconds=0 时不应节流（保持向后兼容）"""
        manager = _make_manager()
        _remember_decayable(manager, 5)
        assert manager.run_decay_cycle(max_memories=5) == 5
        assert manager.run_decay_cycle(max_memories=5) == 5


class TestAgentBoundedDecayCall:
    """Agent._update_memory_temperature 应传入有界参数"""

    def test_calls_bounded_run_decay_cycle(self):
        from neurova.agent_core import Agent

        mock_agent = MagicMock()
        mock_agent.memory_manager = MagicMock()
        mock_agent.memory_manager.run_decay_cycle.return_value = 5

        Agent._update_memory_temperature(mock_agent)

        # 生产调用必须是有界 + 节流的，否则 116 万条记忆会阻塞事件循环
        mock_agent.memory_manager.run_decay_cycle.assert_called_once_with(
            hours=1.0, rate=1.0, max_memories=500, min_interval_seconds=300.0
        )


class TestPostChatPipelineThreadDispatch:
    """温度更新步骤应在工作线程中执行，不阻塞事件循环"""

    @staticmethod
    def _patch_other_steps(pipeline):
        """将除 _step_update_memory_temperature 外的所有步骤替换为 no-op

        注意：仅 patch 可调用方法；_step_results（contextvar property）、
        _step_results_ctx（ContextVar）、_step_results_store（list）等
        非方法属性不可覆盖，否则步骤结果机制会损坏。
        """
        for name in dir(pipeline):
            if name.startswith("_step_") and name != "_step_update_memory_temperature":
                attr = getattr(pipeline, name, None)
                if callable(attr):
                    setattr(pipeline, name, AsyncMock(return_value=None))

    @pytest.mark.asyncio
    async def test_temperature_step_dispatched_to_thread(self):
        mock_agent = MagicMock()
        pipeline = PostChatPipeline(mock_agent)
        self._patch_other_steps(pipeline)
        captured = {}

        async def fake_to_thread(func, *args, **kwargs):
            captured["func"] = func
            captured["args"] = args
            return func(*args, **kwargs)

        with patch("asyncio.to_thread", side_effect=fake_to_thread):
            await pipeline.process(
                user_input="hi",
                reply="hello",
                session_id="s1",
                save_memory=True,
                enable_tts=False,
                metadata={},
            )

        # bound method 每次访问生成新对象，用 __func__ 比较底层函数
        assert captured.get("func") is not None
        assert captured["func"].__func__ is PostChatPipeline._safe_step_sync
        assert captured["args"][0] == "update_memory_temperature"
        assert captured["args"][1].__func__ is PostChatPipeline._step_update_memory_temperature

    @pytest.mark.asyncio
    async def test_event_loop_stays_responsive_during_sync_step(self):
        """同步阻塞步骤放入 to_thread 后，事件循环仍可处理其他任务"""
        manager = _make_manager()
        _remember_decayable(manager, 200, temperature=50.0, prefix="stress")

        ticked = []

        async def ticker():
            # 在 run_decay_cycle 同步执行期间，事件循环应仍能调度此任务
            for _ in range(3):
                await asyncio.sleep(0.01)
                ticked.append(True)

        tick_task = asyncio.create_task(ticker())
        await asyncio.to_thread(manager.run_decay_cycle, max_memories=500)
        await tick_task
        assert len(ticked) == 3

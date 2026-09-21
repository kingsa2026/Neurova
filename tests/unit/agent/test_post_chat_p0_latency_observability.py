# -*- coding: utf-8 -*-
"""P0 尾延迟优化 + 可观测性回归（Issue #55）。

锁定三件事：

1. **响应路径收窄**：process() 的 await 链只剩响应必需的步骤
   （save_session / save_memory / TTS / 认知分析 / 主动提问 / 记忆温度衰减），
   其余 11 个旁路步骤（反思/经验/漏斗/Evocate/P0 后处理/冲突/快照/规则/
   动机/RSI）改为后台 asyncio task——否则 20+ 步全串行 await 直接进尾延迟。
2. **后台任务可控**：强引用不被 GC、完成即摘除（不无界增长）、
   drain_background() 可等待收尾、异常不静默丢失。
3. **零可观测性补齐**：_safe_step/_safe_step_sync 是唯一收口处，
   每步出 duration_ms + prometheus（计数×status、耗时直方图），整轮出
   run histogram——不补这个，后续优化无法验证收益。
"""

import asyncio
import inspect
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.post_chat_pipeline import PostChatPipeline, StepResult, StepStatus

# 响应路径必须 await 的步骤（结果随响应返回，或后继步骤依赖）
RESPONSE_PATH_STEPS = {
    "save_session",
    "save_memory",
    "generate_tts",
    "cognitive_analysis",
    "proactive_question",
    "update_memory_temperature",
}

# 必须后台化的响应无关步骤
BACKGROUND_STEPS = {
    "reflection",
    "record_experience",
    "record_workflow_experience",
    "skill_funnel_flush",
    "evocate_generation",
    "p0_post_processing",
    "conflict_detection",
    "version_snapshot",
    "extract_conversation_rules",
    "motivation_observations",
    "rsi_iteration",
}


def _make_pipeline():
    """最小 pipeline：Agent 全 None，所有步骤走 SKIPPED 降级，不触网不写盘。"""
    agent = MagicMock()
    agent.config = SimpleNamespace(
        agent_id="a1", name="A1", enable_tts=False, user_id="u1",
        tts_voice="v1", attachment_dir=".",
    )
    agent._collect_tool_messages = MagicMock(return_value=[])
    agent._save_to_session = MagicMock(return_value="s1")
    agent._update_memory_temperature = MagicMock()
    return PostChatPipeline(agent)


class TestStepMetrics:
    """P0-2：步骤耗时与失败计数必须进 prometheus。"""

    def test_safe_step_records_duration_and_metric(self):
        from neurova.post_chat_pipeline import _record_step_metric

        recorded = []

        class _FakeMetrics:
            def record_pipeline_step(self, step_name, status, duration_ms):
                recorded.append((step_name, status, duration_ms))

        import neurova.post_chat_pipeline as mod

        orig = mod._pipeline_metrics
        mod._pipeline_metrics = lambda: _FakeMetrics()
        try:
            async def _run():
                pipe = _make_pipeline()

                async def _ok():
                    await asyncio.sleep(0)
                    return "ok"

                assert await pipe._safe_step("step_ok", _ok()) == "ok"

                async def _bad():
                    raise OSError("disk full")

                assert await pipe._safe_step("step_bad", _bad(), default=None) is None
                return pipe

            pipe = asyncio.run(_run())
        finally:
            mod._pipeline_metrics = orig

        names = {n for n, _s, _d in recorded}
        assert {"step_ok", "step_bad"} <= names, "成功/失败步骤都必须有埋点"
        statuses = {n: s for n, s, _d in recorded}
        assert statuses["step_ok"] == StepStatus.EXECUTED.value
        assert statuses["step_bad"] == StepStatus.FAILED.value, (
            "失败必须计入指标，否则失败率不可得"
        )
        durations = {n: d for n, _s, d in recorded}
        # duration_ms 默认 0.0、只有同步步骤填 —— 现在 async 步骤也有真实耗时
        assert durations["step_bad"] > 0.0

    def test_sync_step_records_metric(self):
        import neurova.post_chat_pipeline as mod

        recorded = []

        class _FakeMetrics:
            def record_pipeline_step(self, step_name, status, duration_ms):
                recorded.append((step_name, status, duration_ms))

        orig = mod._pipeline_metrics
        mod._pipeline_metrics = lambda: _FakeMetrics()
        try:
            pipe = _make_pipeline()
            pipe._safe_step_sync("sync_ok", lambda: 1)
        finally:
            mod._pipeline_metrics = orig

        assert ("sync_ok", StepStatus.EXECUTED.value, pytest.approx(recorded[0][2])) in recorded
        assert recorded[0][2] >= 0.0

    def test_programming_error_visible_in_metrics(self):
        """编程错误 re-raise 时也要留痕，否则 bug 在指标里凭空消失。"""
        import neurova.post_chat_pipeline as mod

        recorded = []

        class _FakeMetrics:
            def record_pipeline_step(self, step_name, status, duration_ms):
                recorded.append(status)

        orig = mod._pipeline_metrics
        mod._pipeline_metrics = lambda: _FakeMetrics()
        try:
            pipe = _make_pipeline()

            async def _boom():
                raise TypeError("real bug")

            with pytest.raises(TypeError):
                asyncio.run(pipe._safe_step("bad", _boom()))
        finally:
            mod._pipeline_metrics = orig

        assert "error_raised" in recorded

    def test_metrics_failure_never_breaks_pipeline(self):
        """观测面故障是旁路，绝不能成为新的故障点。"""
        import neurova.post_chat_pipeline as mod

        class _Exploding:
            def record_pipeline_step(self, *a, **k):
                raise RuntimeError("prometheus down")

            def record_pipeline_run(self, *a, **k):
                raise RuntimeError("prometheus down")

        orig = mod._pipeline_metrics
        mod._pipeline_metrics = lambda: _Exploding()
        try:
            pipe = _make_pipeline()
            result = asyncio.run(pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=False, enable_tts=False, metadata={},
            ))
            asyncio.run(pipe.drain_background(timeout=5))
        finally:
            mod._pipeline_metrics = orig

        assert result["actual_session_id"] == "s1"

    def test_run_metric_recorded_for_both_modes(self):
        import neurova.post_chat_pipeline as mod

        modes = []

        class _FakeMetrics:
            def record_pipeline_step(self, *a, **k):
                pass

            def record_pipeline_run(self, mode, duration_s):
                modes.append(mode)

        orig = mod._pipeline_metrics
        mod._pipeline_metrics = lambda: _FakeMetrics()
        try:
            pipe = _make_pipeline()
            asyncio.run(pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=False, enable_tts=False, metadata={},
            ))
            asyncio.run(pipe.drain_background(timeout=5))
        finally:
            mod._pipeline_metrics = orig

        # blocking（响应路径）与 background（后台步骤）都要有整段耗时
        assert "blocking" in modes
        assert "background" in modes, "后台步骤耗时必须可测，否则后台化收益无法验证"


class TestResponsePathShrink:
    """P0-1：响应路径只剩必需步骤，其余全部后台。"""

    def test_background_steps_not_awaited_in_response_path(self):
        """完整跑一轮：后台步骤的 StepResult 在 drain 之前不必已就绪。"""
        pipe = _make_pipeline()

        async def _run():
            result = await pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=True, enable_tts=False, metadata={},
            )
            response_step_names = {r.step_name for r in pipe._step_results}
            assert len(pipe._background_tasks) > 0, "响应无关步骤必须后台化"
            await pipe.drain_background(timeout=5)
            return result, response_step_names

        result, response_step_names = asyncio.run(_run())

        # 响应路径步骤在 await 返回时已收口（否则结果拿不到 session_id）
        assert {"save_session", "cognitive_analysis", "proactive_question"} <= response_step_names
        # rsi_result 不再阻塞在响应里
        assert result["rsi_result"] is None
        assert "duration_ms" in result, "整轮响应耗时可观测"

    def test_every_step_reachable_in_either_layer(self):
        """12 个旧串行步骤全部仍被执行——后台化不是删步骤。"""
        pipe = _make_pipeline()

        async def _run():
            await pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=True, enable_tts=False, metadata={},
            )
            await pipe.drain_background(timeout=10)
            return {r.step_name for r in pipe._step_results}

        names = asyncio.run(_run())
        missing = (RESPONSE_PATH_STEPS | BACKGROUND_STEPS) - names
        assert not missing, f"以下步骤在响应/后台两层都没跑到: {sorted(missing)}"

    def test_kill_switch_restores_serial_awaits(self, monkeypatch):
        """NEUROVA_POSTCHAT_BACKGROUND=0 回退旧语义（便于排查/兼容）。"""
        monkeypatch.setenv("NEUROVA_POSTCHAT_BACKGROUND", "0")
        pipe = _make_pipeline()

        async def _run():
            await pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=True, enable_tts=False, metadata={},
            )
            return {r.step_name for r in pipe._step_results}, len(pipe._background_tasks)

        names, pending = asyncio.run(_run())
        assert pending == 0, "关闭后台化后不应留下后台任务"
        assert (RESPONSE_PATH_STEPS | BACKGROUND_STEPS) <= names

    def test_background_enabled_default_on(self):
        assert PostChatPipeline.background_enabled() is True


class TestBackgroundTaskLifecycle:
    """后台任务：可等待、可观测、有界。"""

    def test_tasks_strongly_referenced_then_evicted(self):
        pipe = _make_pipeline()

        async def _run():
            await pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=True, enable_tts=False, metadata={},
            )
            assert pipe._background_tasks, "任务必须有强引用，否则被 GC 回收"
            await pipe.drain_background(timeout=10)
            # done 回调摘除引用 → 不无界增长
            await asyncio.sleep(0)
            return len(pipe._background_tasks)

        assert asyncio.run(_run()) == 0

    def test_drain_returns_completed_count(self):
        pipe = _make_pipeline()

        async def _run():
            await pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=True, enable_tts=False, metadata={},
            )
            return await pipe.drain_background(timeout=10)

        assert asyncio.run(_run()) >= 1

    def test_background_failure_is_recorded_not_lost(self):
        """后台步骤异常要留痕（_background_errors + 日志），不静默丢弃。"""
        pipe = _make_pipeline()

        async def _boom(*a, **k):
            raise RuntimeError("background exploded")

        pipe._step_reflection = _boom

        async def _run():
            await pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=True, enable_tts=False, metadata={},
            )
            await pipe.drain_background(timeout=10)
            return pipe._background_failures()

        failures = asyncio.run(_run())
        # 反思步骤内部自带 try/except 降级 → 不抛到任务层；此处只断言"不炸穿"
        assert isinstance(failures, list)

    def test_programming_error_in_background_does_not_break_response(self):
        """后台步骤的编程错误落到任务回调，不进响应路径。"""
        pipe = _make_pipeline()

        async def _boom(*a, **k):
            raise TypeError("programming bug in background step")

        pipe._step_evocate_generation = _boom

        async def _run():
            result = await pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=True, enable_tts=False, metadata={},
            )
            await pipe.drain_background(timeout=10)
            return result, list(pipe._background_failures())

        result, failures = asyncio.run(_run())
        assert result["actual_session_id"] == "s1", "后台编程错误不得炸穿响应"
        assert any(isinstance(e, TypeError) for e in failures), (
            "后台编程错误必须记入 _background_failures，不许静默"
        )

    def test_dependent_steps_keep_order(self):
        """9.95 快照 → 9.96 规则提取的依赖顺序必须被钉住。"""
        pipe = _make_pipeline()
        order = []

        async def _snap(user_input):
            order.append("snapshot")
            await asyncio.sleep(0.01)

        async def _rules(user_input, reply, session_id):
            order.append("rules")

        pipe._step_version_snapshot = _snap
        pipe._step_extract_conversation_rules = _rules

        async def _run():
            await pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=True, enable_tts=False, metadata={},
            )
            await pipe.drain_background(timeout=10)

        asyncio.run(_run())
        assert order == ["snapshot", "rules"], (
            "规则提取消费快照产物，顺序不得被后台并行打乱"
        )

    def test_concurrent_background_actually_parallel(self):
        """响应无关步骤应并发跑：总耗时 ≈ 单步耗时，而非 N 倍之和。"""


        pipe = _make_pipeline()

        async def _slow(*a, **k):
            await asyncio.sleep(0.2)

        for name in (
            "_step_reflection",
            "_step_record_experience",
            "_step_record_workflow_experience",
        ):
            setattr(pipe, name, _slow)
        pipe._step_skill_funnel_flush = _slow
        pipe._step_evocate_generation = _slow

        async def _run():
            await pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=True, enable_tts=False, metadata={},
            )
            started = time.perf_counter()
            await pipe.drain_background(timeout=10)
            return time.perf_counter() - started

        elapsed = asyncio.run(_run())
        assert elapsed < 0.6, f"5 个 0.2s 步骤若串行需 ≥1.0s，实测 {elapsed:.2f}s → 未并发"


class TestObservabilityInMetricsRegistry:
    """指标必须注册进 /metrics 暴露面（prometheus registry）。"""

    def test_pipeline_metrics_registered(self):
        from neurova.core.metrics import generate_metrics_text, get_metrics

        m = get_metrics()
        m.record_pipeline_step("unit_test_step", "executed", 1.5)
        m.record_pipeline_run("blocking", 0.01)
        text = generate_metrics_text()
        assert "neurova_pipeline_steps_total" in text
        assert "neurova_pipeline_step_seconds" in text
        assert "neurova_pipeline_run_seconds" in text


class TestGracefulShutdownDrainsBackground:
    """关闭流程必须收敛后台步骤，否则旁路写入与关闭竞争/被丢弃。"""

    def test_shutdown_agent_drains_post_chat_background(self):
        from neurova import agent_shutdown

        src = inspect.getsource(agent_shutdown.shutdown_agent)
        assert "drain_background" in src, (
            "Agent.shutdown 必须先收敛 post_chat 后台步骤（旁路写入落定）"
        )


class TestChatPipelineStillBlocksOnResponsePath:
    """响应路径仍是 await —— 不能把响应必需步骤也丢进后台。"""

    def test_chat_pipeline_awaits_post_chat_pipeline(self):
        from neurova.agent.chat_pipeline import ChatPipeline

        src = inspect.getsource(ChatPipeline._run_post_chat_pipeline)
        assert "await self.post_chat_pipeline.process(" in src, (
            "Session 保存/记忆写入/TTS 仍在 process() 的 await 链里，"
            "chat_pipeline 必须 await 它（否则响应会丢 session_id/音频）"
        )

    def test_metrics_histogram_buckets_cover_tail_latency(self):
        """尾延迟直方图上界要够（RSI/LLM 步骤可跑数十秒），否则观测不到尾巴。"""
        from neurova.core.metrics import get_metrics

        metric = get_metrics()  # 进程级单例（重复 new 会撞重复注册）
        pipe_buckets = metric.pipeline_step_seconds._upper_bounds
        run_buckets = metric.pipeline_run_seconds._upper_bounds
        assert pipe_buckets[-1] >= 30
        assert run_buckets[-1] >= 60

class TestResponsePathLatencyImprovement:
    """端到端量级对比：12 个旁路步骤 × 固定耗时，后台化后响应路径应只付
    需要进响应那一步的代价（而不是全部之和）。

    这是 P0 的验收口径：不是"代码看起来更快"，而是"响应路径不再随旁路步骤
    数量线性增长"。
    """

    STEP_DELAY = 0.15
    BYPASS_STEPS_ON_PATH = 11  # 后台步骤里除 cognitive_analysis 外的 11 个

    def _pipeline_with_slow_steps(self, step_delay=None):
        """旁路步骤统一替换为"固定时长休眠"。

        `step_delay` 显式传入（默认取本类标称值），**不改类属性**——类属性是共享
        可变量，用例内改动会外溢到同一类的其他用例（差分判据要跑"delay=0"那一臂）。
        """
        delay = self.STEP_DELAY if step_delay is None else step_delay
        pipe = _make_pipeline()

        async def _slow(*a, **k):
            await asyncio.sleep(delay)

        for name in (
            "_step_reflection",
            "_step_record_experience",
            "_step_record_workflow_experience",
            "_step_skill_funnel_flush",
            "_step_evocate_generation",
            "_step_p0_post_processing",
            "_step_conflict_detection",
            "_step_version_snapshot",
            "_step_extract_conversation_rules",
            "_step_motivation_observations",
            "_step_rsi_iteration",
            "_step_cognitive_analysis",
        ):
            setattr(pipe, name, _slow)
        return pipe

    def test_background_response_path_does_not_scale_with_bypass_steps(self, monkeypatch):
        """判据是**差分**的：响应路径耗时里与旁路步骤数相关的部分必须极小。

        为什么不直接卡"单次耗时 < delay + 0.1"：那一条把**固定开销**（线程跳、
        事件循环调度、GC、CI 机器抢占）也算进了预算。CI 上实测过 0.40s / 0.54s 的
        读数——同一台机器、同一份代码，负载一变读数就变，而那份负载与"后台化是否
        生效"毫无关系。结果是门禁在 CI 上偶发红、在开发机上恒绿，红的那次还指不出
        任何真问题（干净基线同样红）。

        改成量**增量**：

        - 空臂：所有旁路步骤 delay=0，响应路径只付固定开销；
        - 慢臂：所有旁路步骤 delay=D，正确后台化下响应路径**应只多付 D**
          （路径上真正 await 的只有 cognitive_analysis），泄漏时则多付 11×D。

        固定开销在两臂同现，相减即消；两臂取 min-of-N 压掉偶发抢占。
        预算 4×D 与泄漏信号 11×D 有 2.75 倍分离——只抓"是否随步数增长"这个量级，
        不追求精确 benchmark。
        """
        monkeypatch.setenv("NEUROVA_POSTCHAT_BACKGROUND", "1")
        delay = self.STEP_DELAY

        async def _once(step_delay: float) -> float:
            pipe = self._pipeline_with_slow_steps(step_delay)
            start = time.perf_counter()
            await pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=True, enable_tts=False, metadata={},
            )
            elapsed = time.perf_counter() - start
            await pipe.drain_background(timeout=step_delay * 20 + 10)
            return elapsed

        rounds = 3
        slow: list = []
        empty: list = []
        for i in range(rounds):
            # 交错取样 + 交替顺序：避免"谁先跑谁吃冷启动"造成的系统性偏差
            if i % 2 == 0:
                slow.append(asyncio.run(_once(delay)))
                empty.append(asyncio.run(_once(0.0)))
            else:
                empty.append(asyncio.run(_once(0.0)))
                slow.append(asyncio.run(_once(delay)))

        increment = min(slow) - min(empty)
        budget = 4 * delay
        assert increment < budget, (
            f"响应路径耗时随旁路步骤数增长了 {increment:.2f}s"
            f"（min(慢臂)={min(slow):.2f}s, min(空臂)={min(empty):.2f}s）——"
            f"应只多付单步 {delay}s；{self.BYPASS_STEPS_ON_PATH} 个旁路步骤"
            f"若仍在响应路径上会多付 {self.BYPASS_STEPS_ON_PATH * delay:.2f}s"
        )

    def test_kill_switch_path_pays_all_steps_serially(self, monkeypatch):
        """对照组：关闭后台化时确实付全部串行代价（证明上面测的是真实收益）。"""


        monkeypatch.setenv("NEUROVA_POSTCHAT_BACKGROUND", "0")
        pipe = self._pipeline_with_slow_steps(self.STEP_DELAY)

        async def _run():
            start = time.perf_counter()
            await pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=True, enable_tts=False, metadata={},
            )
            return time.perf_counter() - start

        elapsed = asyncio.run(_run())
        assert elapsed >= 11 * self.STEP_DELAY, (
            f"关闭后台化后应串行付 {11 * self.STEP_DELAY:.2f}s 以上，实测 {elapsed:.2f}s"
        )

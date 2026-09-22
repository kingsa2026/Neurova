# -*- coding: utf-8 -*-
"""RSI 结果真接线回归（Issue #55 后续）。

背景：PR #60 把 RSI 迭代后台化后，``process()["rsi_result"]`` 恒为 None——
字段还在，但"本轮 RSI 到底做了什么"没有任何出口；而唯一想读它的
``NegativeScreenPusher.push_rsi_result`` 读的是
``iteration/improvements/convergence_score/status``，与
``RSIOrchestrator.run_iteration`` 真实输出（``convergence``（dict）/
``applied_count``/``gain``/``phase_advanced``）名字全不匹配，且
``convergence_score * 100`` 拿到真实结果就 TypeError。

本套件钉住真接线的四件事：

1. **摘要字段名对齐真实输出**——单一事实源
   ``neurova.evolution.rsi.result_summary``；``convergence`` 是 dict 时取
   ``status``，不得把 dict 当数字。
2. **响应面**——``PostChatPipeline.process()`` 返回 ``rsi`` 摘要（取该会话
   最近一次已完成迭代，``stale`` 标明非本轮），且**不把 RSI 拉回响应路径**。
3. **对话返回值**——``ChatPipeline`` 组装 ``ctx.result`` 时不再丢该字段
   （executor 与 post_chat fallback 两条路径都要带上）。
4. **推送面**——`push_rsi_result` 吃真实 `run_iteration` 返回不报错
   （对照组：旧字段口径必崩），字段按摘要模块统一解释。

工单 012 变更记录：第 4 组 `TestNegativeScreenPushFields`（8 条）随
``NegativeScreenPusher.push_rsi_result`` 一并删除——该方法生产零调用方
（``manager.py`` 只调 ``push_task``），属工单 012「接电或拆除」二选一里选的拆除。
它原先锁的三件事没有失效：字段口径仍由本文件第 1 组锁、响应面仍由第 2/3 组锁，
而「晋升结论 + 落盘状态必须人可读」迁到 ``orchestrator.get_status()`` 与
``GET /v1/governance/rsi/status``（见 ``tests/unit/evolution/rsi/test_rsi_observation_surface.py``）。
"""

import ast
import asyncio
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.evolution.rsi.result_summary import (
    RSI_SUMMARY_FIELDS,
    clear_rsi_summaries,
    convergence_status,
    get_latest_rsi_summary,
    record_rsi_summary,
    summarize_rsi_result,
)
from neurova.evolution.rsi.orchestrator import IterationCadence
from neurova.post_chat_pipeline import PostChatPipeline

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# RSIOrchestrator.run_iteration 的真实返回形态（原样取自 orchestrator.py 尾部）
REAL_ITERATION_RESULT = {
    "feedback_signals": {"signals": []},
    "convergence": {"status": "converging", "metrics": {"roi": 0.2}},
    "optimizations": [{"param": "temperature"}],
    "applied_results": [{"applied": True}, {"applied": True}],
    "applied_count": 2,
    "gain": 0.125,
    "eval": {"before": None, "after": None},
    "escalation": {"verdict": {}, "proposals": [], "skipped": []},
    "phase_advanced": True,
    "phase_persisted": False,
    "metrics": {"metrics": {"iteration_count": 3}},
}


@pytest.fixture(autouse=True)
def _clean_summaries():
    clear_rsi_summaries()
    yield
    clear_rsi_summaries()


# ─── 1. 摘要单一事实源 ────────────────────────────────────────────────────────


class TestSummarizeRsiResult:
    def test_fields_match_orchestrator_output(self):
        """摘要字段必须对齐 run_iteration 真实输出，不是历史臆造名。

        工单 016 改写本用例的理由：契约的字段集合从 7 项增到 8 项（新增
        `phase_verdict`——"没晋升"的成因必须与布尔值一起送达，否则三态里的
        `unevidenced` 只活在日志里）。这里的期望值随之多一条，而
        `REAL_ITERATION_RESULT` 是历史形态、没带判据 ⇒ 期望值为 None，
        **不是** "passed"（未知不得读成判据通过）。断言一条未减。

        工单 005 再改写一次：字段集合增到 9 项（新增 `phase_persisted`）。
        本样本已带上该键，值为 False —— 即"内存已晋升、盘上没晋升"这一态
        必须原样抵达响应面，不得被 `phase_advanced` 一个布尔压掉。
        """
        summary = summarize_rsi_result(REAL_ITERATION_RESULT)
        assert set(summary) == set(RSI_SUMMARY_FIELDS)
        assert summary == {
            "status": "converging",
            "applied_count": 2,
            "gain": 0.125,
            "phase_advanced": True,
            "phase_persisted": False,
            # eval.after 为 None = 本轮没做前后测量（不是"测了 0 例"）
            "measure_state": "not_attempted",
            "evidenced_cases": None,
            # 快照没带缺席信息 ≠ "一个都没缺席"（未知不得读成正常）
            "placeholder_systems": None,
            # 快照没带晋升判据 ≠ "判据通过"（同上，工单 016）
            "phase_verdict": None,
        }

    def test_convergence_is_dict_not_number(self):
        """convergence 是 dict：不得当数字用（旧推送实现 *100 会 TypeError）。"""
        status = convergence_status(REAL_ITERATION_RESULT)
        assert status == "converging"
        assert isinstance(status, str)

    def test_convergence_missing_status_degrades(self):
        assert convergence_status({"convergence": {}}) == "unknown"
        assert convergence_status({"convergence": None}) == "unknown"
        # 扁平/历史形态兼容，不炸
        assert convergence_status({"convergence_score": 0.85, "status": "completed"}) == "completed"
        assert convergence_status({"convergence_status": "diverging"}) == "diverging"

    @pytest.mark.parametrize("bad", [None, {}, [], "x", 0, {"raw": 1} if False else None])
    def test_non_iteration_shapes_return_none(self, bad):
        """形态不符不造默认值——不存在的迭代不冒充"跑了一轮没优化"。"""
        assert summarize_rsi_result(bad) is None

    def test_never_multiplies_unvalidated_value(self):
        """convergence 为 dict 时摘要仍可算（对照旧实现必崩）。"""
        summary = summarize_rsi_result({"convergence": {"status": "converged"}, "gain": 0.0})
        assert summary["status"] == "converged"
        # 对照组：旧实现的算法在这份输入上必崩
        with pytest.raises(TypeError):
            _ = REAL_ITERATION_RESULT["convergence"] * 100


class TestPackageExports:
    """摘要 API 必须从 neurova.evolution.rsi 包级别可达（可发现性）。"""

    def test_exported_from_package(self):
        import neurova.evolution.rsi as rsi_pkg

        for name in ("RSI_SUMMARY_FIELDS", "summarize_rsi_result",
                     "get_latest_rsi_summary", "record_rsi_summary"):
            assert hasattr(rsi_pkg, name), f"{name} 未从 rsi 包导出"
            assert name in rsi_pkg.__all__

    def test_import_is_stdlib_only_no_heavy_pull(self):
        """摘要模块只依赖标准库——import 期不得拉起 evolution 重链。"""
        import subprocess
        import sys

        code = (
            "import sys, neurova.evolution.rsi.result_summary as m;"
            "assert not any(k.startswith('torch') or k.startswith('numpy') for k in sys.modules);"
            "print('ok')"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, cwd=str(PROJECT_ROOT), timeout=180)
        assert proc.returncode == 0, proc.stderr[-800:]


class TestSummaryStore:
    def test_none_until_first_iteration(self):
        assert get_latest_rsi_summary("a1", "s1") is None

    def test_session_and_agent_isolated(self):
        record_rsi_summary("a1", "s1", REAL_ITERATION_RESULT, turn=1)
        assert get_latest_rsi_summary("a2", "s1") is None
        assert get_latest_rsi_summary("a1", "s2") is None
        assert get_latest_rsi_summary("a1", "s1")["status"] == "converging"

    def test_stale_flag_marks_non_current_turn(self):
        record_rsi_summary("a1", "s1", REAL_ITERATION_RESULT, turn=3)
        assert get_latest_rsi_summary("a1", "s1", current_turn=3)["stale"] is False
        assert get_latest_rsi_summary("a1", "s1", current_turn=4)["stale"] is True
        # 不知道当前轮次时不虚报
        assert get_latest_rsi_summary("a1", "s1")["stale"] is False

    def test_record_rejects_bad_shape(self):
        assert record_rsi_summary("a1", "s1", None, turn=1) is None
        assert get_latest_rsi_summary("a1", "s1") is None

    def test_store_bounded(self):
        """长进程不得无界增长（有界淘汰，只留最近若干会话）。"""
        from neurova.evolution.rsi import result_summary as mod

        for i in range(mod._MAX_TRACKED_SESSIONS + 50):
            record_rsi_summary("a1", f"s{i}", REAL_ITERATION_RESULT, turn=1)
        assert len(mod._summaries) <= mod._MAX_TRACKED_SESSIONS


# ─── 2/3. 响应面接线 ──────────────────────────────────────────────────────────


def _stub_pipeline():
    """最小 pipeline：依赖全缺，步骤走 SKIPPED；只验 RSI 摘要出口。"""
    agent = MagicMock()
    agent.config = SimpleNamespace(
        agent_id="a1", name="A1", enable_tts=False, user_id="u1",
        tts_voice="v1", attachment_dir=".",
    )
    agent.session_id = "s1"
    agent._collect_tool_messages = MagicMock(return_value=[])
    agent._save_to_session = MagicMock(return_value="s1")
    agent._update_memory_temperature = MagicMock()
    return PostChatPipeline(agent)


def _process(pipe, **kw):
    params = dict(user_input="hi", reply="yo", session_id="s1",
                  save_memory=False, enable_tts=False, metadata={})
    params.update(kw)
    return asyncio.run(pipe.process(**params))


class TestProcessExposesSummary:
    def test_rsi_key_present_and_none_without_iteration(self):
        result = _process(_stub_pipeline())
        assert "rsi" in result, "响应必须带 RSI 摘要出口（真接线）"
        assert result["rsi"] is None, "从未跑过 RSI 时不得编造摘要"

    def test_rsi_result_legacy_field_kept(self):
        """旧字段保留（恒 None）——真接线不是破坏性变更。"""
        result = _process(_stub_pipeline())
        assert result["rsi_result"] is None

    def test_summary_returned_after_completed_iteration(self):
        pipe = _stub_pipeline()
        record_rsi_summary("a1", "s1", REAL_ITERATION_RESULT, turn=1)

        result = _process(pipe)
        summary = result["rsi"]
        assert set(RSI_SUMMARY_FIELDS) <= set(summary)
        assert summary["status"] == "converging"
        assert summary["applied_count"] == 2
        assert summary["gain"] == 0.125
        assert summary["phase_advanced"] is True

    def test_summary_never_awaits_rsi_on_response_path(self):
        """摘要出口不得把 RSI 拉回响应路径（P0 尾延迟不可回退）。

        判据是结构性的（与机器速度无关）：把 RSI 步骤闸住不放，若它仍挂在响应
        路径上，``process()`` 会等它而返回不了（``wait_for`` 超时判红）。原写法
        断言墙钟 ``elapsed < 0.35``（RSI 睡眠 0.4s），在 CI 共享机的负载下会把
        正确实现误判为回归；误判方向还会诱导"放宽阈值换绿"，那是教义第 2 条
        禁止的降级断言。见 ``tests/unit/test_ci_wallclock_assertion_ledger.py``。
        """
        pipe = _stub_pipeline()
        rsi_entered = asyncio.Event()

        async def _gated_rsi():
            rsi_entered.set()
            await asyncio.Event().wait()  # 永不自行结束：只有被取消才会退出
            return REAL_ITERATION_RESULT

        pipe._step_rsi_iteration = _gated_rsi

        async def _run():
            result = await asyncio.wait_for(
                pipe.process(
                    user_input="hi", reply="yo", session_id="s1",
                    save_memory=False, enable_tts=False, metadata={},
                ),
                timeout=10,
            )
            at_return = {r.step_name for r in pipe._step_results}
            return result, at_return

        result, at_return = asyncio.run(_run())
        assert "rsi" in result
        assert "rsi_iteration" not in at_return, (
            "process() 返回时 RSI 步骤已收口 ⇒ 它被 await 在响应路径上（P0 尾延迟回退）"
        )

    def test_step_rsi_iteration_records_summary_with_real_field_names(self, monkeypatch):
        """步骤真跑一次 → 摘要落库，且字段取自真实输出（不是 iteration/improvements）。"""
        class FakeRSI:
            def should_continue(self):
                return True

            def iteration_cadence(self):  # 工单 008：派发层改读节奏，不再读二态开关
                return IterationCadence(mode="run", basis="converging",
                                        evidence="窗口 20 轮内有效测量 1 轮")

            def run_iteration(self):
                return REAL_ITERATION_RESULT

        async def _no_proposals(_loader):
            return []

        monkeypatch.setattr(
            "neurova.evolution.skill_improver.get_skill_improver",
            lambda: SimpleNamespace(
                propose_pending_improvements_async=_no_proposals,
                apply_improvement=lambda *a, **k: False,
            ),
        )

        pipe = _stub_pipeline()
        pipe._get_dependency = lambda name: FakeRSI() if name == "rsi_orchestrator" else None

        from neurova.core.turn_context import set_turn_identity

        set_turn_identity("hi", "s1", "u1")
        step_result = asyncio.run(pipe._step_rsi_iteration())
        assert step_result["applied_count"] == 2

        summary = get_latest_rsi_summary("a1", "s1")
        assert summary is not None, "RSI 步骤执行后必须落摘要（否则接线是空的）"
        assert summary["applied_count"] == 2
        assert summary["gain"] == 0.125
        assert summary["phase_advanced"] is True
        assert summary["status"] == "converging"


class TestChatPipelineCarriesSummary:
    def _chat_pipeline(self, post_result):
        from neurova.agent.chat_pipeline import ChatPipeline

        agent = MagicMock()
        agent.config = SimpleNamespace(
            agent_id="a1", llm_config=SimpleNamespace(model="m"), name="A1",
            tts_enabled=False,
        )
        agent.post_chat_pipeline = MagicMock()
        agent.post_chat_pipeline.process = AsyncMock(return_value=post_result)
        agent._trajectory_recorder = None
        agent.session_manager = MagicMock()
        agent.trace_manager = None
        return ChatPipeline(agent)

    def test_fallback_path_passes_rsi_through(self):
        summary = {"status": "converging", "applied_count": 2, "gain": 0.125,
                   "phase_advanced": True, "turn": 1, "stale": True}
        pipe = self._chat_pipeline({
            "actual_session_id": "s1",
            "cognitive_score": 0.1,
            "rsi": summary,
        })
        result = asyncio.run(pipe._run_post_chat_pipeline(MagicMock(
            user_input="u", reply="r", session_id="s1", save_memory=False,
            enable_tts=False, metadata={}, writer_claim=None,
        )))
        assert result["rsi"] == summary

    def test_ctx_result_includes_rsi(self):
        """组装 ctx.result 时 rsi 必须随行（历史断点：字段被丢弃）。"""
        from neurova.agent.chat_pipeline import ChatContext

        pipe = self._chat_pipeline({})
        summary = {"status": "converging", "applied_count": 1, "gain": 0.5,
                   "phase_advanced": False}
        pipe._run_post_chat_pipeline = AsyncMock(return_value={"rsi": summary})

        ctx = ChatContext(user_input="u", session_id="s1")
        ctx.reply = "r"
        result = asyncio.run(pipe._step_post_processing(ctx))
        assert ctx.result["rsi"] == summary


# ─── 4. 推送面字段名对齐 ──────────────────────────────────────────────────────

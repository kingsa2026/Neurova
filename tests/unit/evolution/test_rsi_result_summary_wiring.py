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
4. **推送面**——``push_rsi_result`` 吃真实 ``run_iteration`` 返回不报错
   （对照组：旧字段口径必崩），字段按摘要模块统一解释。
"""

import ast
import asyncio
import io
import threading
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
    "escalation_proposals": [],
    "phase_advanced": True,
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
        """摘要字段必须对齐 run_iteration 真实输出，不是历史臆造名。"""
        summary = summarize_rsi_result(REAL_ITERATION_RESULT)
        assert set(summary) == set(RSI_SUMMARY_FIELDS)
        assert summary == {
            "status": "converging",
            "applied_count": 2,
            "gain": 0.125,
            "phase_advanced": True,
            # eval.after 为 None = 本轮没做前后测量（不是"测了 0 例"）
            "measure_state": "not_attempted",
            "evidenced_cases": None,
            # 快照没带缺席信息 ≠ "一个都没缺席"（未知不得读成正常）
            "placeholder_systems": None,
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
        """摘要出口不得把 RSI 拉回响应路径（P0 尾延迟不可回退）。"""
        pipe = _stub_pipeline()
        started = []

        async def _slow_rsi():
            started.append(threading.get_ident())
            await asyncio.sleep(0.4)
            return REAL_ITERATION_RESULT

        pipe._step_rsi_iteration = _slow_rsi

        async def _run():
            import time

            t0 = time.perf_counter()
            result = await pipe.process(
                user_input="hi", reply="yo", session_id="s1",
                save_memory=False, enable_tts=False, metadata={},
            )
            elapsed = time.perf_counter() - t0
            await pipe.drain_background(timeout=5)
            return result, elapsed

        result, elapsed = asyncio.run(_run())
        assert elapsed < 0.35, f"RSI 后台步骤阻塞了响应路径（{elapsed:.2f}s）"
        assert "rsi" in result

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


class TestNegativeScreenPushFields:
    def _pusher(self):
        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenPusher,
        )

        return (
            NegativeScreenPusher(),
            NegativeScreenConfig(user_id="u1", auth_code="code", enabled=True),
        )

    def test_real_run_iteration_result_does_not_crash(self):
        """对照组修复：真实 run_iteration 返回喂进来必须能推送（旧字段口径必崩）。"""
        pusher, config = self._pusher()
        with patch.object(pusher, "push_task", new=AsyncMock(return_value=MagicMock(success=True))) as mp:
            asyncio.run(pusher.push_rsi_result(config, REAL_ITERATION_RESULT))

        content = mp.call_args.kwargs["task_content"]
        assert "converging" in content, "状态要显示真实 convergence.status"
        assert "2" in content, "应用优化数要来自 applied_count"
        assert "部署阶段推进" in content and "是" in content

    def test_summary_input_supported(self):
        """摘要（ctx.result["rsi"]）直接喂进来也要工作。"""
        pusher, config = self._pusher()
        summary = dict(summarize_rsi_result(REAL_ITERATION_RESULT), turn=7, stale=False)
        with patch.object(pusher, "push_task", new=AsyncMock(return_value=MagicMock(success=True))) as mp:
            asyncio.run(pusher.push_rsi_result(config, summary))

        assert "RSI 迭代#7" in mp.call_args.kwargs["task_name"]

    def test_push_surfaces_stall_cause(self):
        """停滞原因要上推送面：光有 gain=0 分不清"没改善空间"和"量不出来"（工单 008 项 5）。

        两者处置相反（前者降频巡检、后者去修测量），所以度量证据状态必须有出口，
        否则摘要里加了字段而用户侧仍看不见 —— 那就是断点。
        """
        pusher, config = self._pusher()
        blind = dict(
            REAL_ITERATION_RESULT,
            gain=0.0,
            applied_count=0,
            eval={"before": None, "after": {
                "score": None, "state": "measurement_blind",
                "evidenced_cases": 0, "blind_cases": 9, "cases": [],
            }},
        )
        with patch.object(pusher, "push_task", new=AsyncMock(return_value=MagicMock(success=True))) as mp:
            asyncio.run(pusher.push_rsi_result(config, blind))

        content = mp.call_args.kwargs["task_content"]
        assert "measurement_blind" in content, "度量证据状态未进推送面"
        assert "0/9" in content or "有证据用例" in content, "证据分母未进推送面"

    def test_legacy_shape_does_not_crash(self):
        """历史字段形态（iteration/improvements/convergence_score）不炸。"""
        pusher, config = self._pusher()
        legacy = {"iteration": 1, "improvements": 3, "convergence_score": 0.85, "status": "completed"}
        with patch.object(pusher, "push_task", new=AsyncMock(return_value=MagicMock(success=True))) as mp:
            asyncio.run(pusher.push_rsi_result(config, legacy))
        assert "completed" in mp.call_args.kwargs["task_content"]

    def test_push_names_absent_closed_loop_systems(self):
        """缺席的闭环系统要在推送面点名列出（工单 018 第 4 项的出口）。

        只显示"应用优化数 0"会被读成"进化跑过了但没找到改进空间"，
        而真实原因是那套系统根本没装配 —— 两者的处置完全不同。
        """
        pusher, config = self._pusher()
        absent = dict(REAL_ITERATION_RESULT, applied_count=0, gain=0.0,
                      placeholder_systems=["sleep", "emotion"])
        with patch.object(pusher, "push_task", new=AsyncMock(return_value=MagicMock(success=True))) as mp:
            asyncio.run(pusher.push_rsi_result(config, absent))

        content = mp.call_args.kwargs["task_content"]
        # 只断言标签：名字本身在末尾的 raw JSON 里必然出现，断它等于没断
        assert "缺席闭环系统" in content, "缺席名单未成行展示"
        assert content.index("缺席闭环系统") < content.index("### 迭代结果"), (
            "缺席名单要进「迭代信息」区，不是只躺在 raw JSON 里")

    def test_empty_input_does_not_crash(self):
        pusher, config = self._pusher()
        with patch.object(pusher, "push_task", new=AsyncMock(return_value=MagicMock(success=True))) as mp:
            asyncio.run(pusher.push_rsi_result(config, {}))
        assert "unknown" in mp.call_args.kwargs["task_content"]

    def test_push_consumes_summary_module_not_second_field_map(self):
        """推断面必须复用摘要模块的口径，不得自带第二套字段解释。"""
        src = io.open(
            PROJECT_ROOT / "neurova" / "notifications" / "negative_screen.py", encoding="utf-8"
        ).read()
        tree = ast.parse(src)

        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "neurova.evolution.rsi.result_summary":
                imported |= {a.name for a in node.names}
        assert "summarize_rsi_result" in imported, (
            "push_rsi_result 必须用摘要模块统一裁剪字段，否则又出现第二套字段名"
        )

        # 历史臆造字段名不得再被当键读取（docstring 里作历史说明提及是允许的，
        # 只拦可执行代码里的取值：xxx.get("convergence_score") 之类）
        ghosts = {"convergence_score", "improvements"}
        read_keys = {
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "pop", "setdefault")
            and node.args
            and isinstance(node.args[0], ast.Constant)
        }
        assert not (ghosts & read_keys), (
            f"幽灵字段 {sorted(ghosts & read_keys)} 又被当键读取——字段口径已收口到摘要模块"
        )

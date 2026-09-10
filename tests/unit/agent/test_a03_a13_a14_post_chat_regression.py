"""A-03 / A-13 / A-14 回归测试（post_chat_pipeline.py）。

红绿说明（修复缺位时为红）：
- A-03: `_collect_round_artifacts`/`_step_record_experience` 原用
  `getattr(agent, "agent_id", ...)`——Agent 无该顶层属性（在
  config.agent_id），恒空/None → 断言拿到 config.agent_id 失败（红）。
- A-13: `_step_rsi_iteration` 原在事件循环线程内同步调 `rsi.run_iteration()`
  （含 SQLite 读写/参数寻优）→ 线程断言失败（红）。
- A-14: 原 `_PROGRAMMING_ERRORS` 含 ImportError，可选依赖缺失
  （ModuleNotFoundError）炸穿整轮 chat() → pytest.raises 捕获（红）；
  修复后降级为步骤失败 + warning + default（绿）。
"""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from neurova.post_chat_pipeline import PostChatPipeline, StepStatus


def _make_pipe(agent) -> PostChatPipeline:
    pipe = PostChatPipeline.__new__(PostChatPipeline)
    pipe._agent = agent
    return pipe


@pytest.fixture(autouse=True)
def _isolated_step_results_ctx():
    """每个用例独立 _step_results 上下文，测试结束复位 ContextVar token。

    此前 helper 用 `pipe._step_results = []`（property setter）隔离——
    ContextVar.set 落在线程基础上下文且永不复位，泄漏给同 worker 所有
    后续测试（test_agent_neurflow_integration 共享同一列表 2→3→4 递增）。
    set/reset 必须成对，泄漏归零。
    """
    token = PostChatPipeline._step_results_ctx.set([])
    yield
    PostChatPipeline._step_results_ctx.reset(token)


# ═══════════════════════════════════════════════════════════════
# A-03: agent_id 恒空
# ═══════════════════════════════════════════════════════════════


def test_a03_collect_round_artifacts_uses_config_agent_id(monkeypatch):
    """产物收集必须携带 config.agent_id（原 getattr(agent,'agent_id') 恒空）。"""
    import neurova.api.endpoints.artifacts_api as artifacts_api

    captured = {}

    def fake_extract(tool_name, result_text, agent_id=None, user_id=None):
        captured["agent_id"] = agent_id
        captured["user_id"] = user_id
        return []

    monkeypatch.setattr(artifacts_api, "extract_tool_artifacts", fake_extract)

    agent = SimpleNamespace(
        # 真 Agent 形态：只有 config.agent_id，无顶层 agent_id 属性
        config=SimpleNamespace(agent_id="agent-x"),
        current_user_id="u1",
    )
    pipe = _make_pipe(agent)
    pipe._collect_round_artifacts(
        [{"type": "tool_result", "tool_name": "t", "result": "产出文本"}]
    )

    assert captured.get("agent_id") == "agent-x", (
        "A-03: 产物提取的 agent_id 必须取 config.agent_id，不得恒为空串"
    )


def test_a03_record_experience_passes_config_agent_id(monkeypatch):
    """EKB 沉淀必须携带 config.agent_id（:1208 同根因命中点）。"""
    from neurova.skills.experience_knowledge_base import ExperienceRecord

    captured = {}

    class FakeEKB:
        def add_experience_record(self, **kw):
            captured.update(kw)

    import neurova.skills.experience_knowledge_base as ekb_mod

    monkeypatch.setattr(ekb_mod, "get_experience_knowledge_base", lambda: FakeEKB())

    evolution = type("Evo", (), {"on_experience_recorded": lambda self, *a, **k: None})()
    monkeypatch.setattr(
        PostChatPipeline,
        "_get_dependency",
        lambda self, name: evolution if name == "evolution" else None,
    )
    import neurova.evolution.evolution_facade as facade_mod

    monkeypatch.setattr(facade_mod.EvolutionFacade, "record_experience", lambda self, *a, **k: None)

    agent = SimpleNamespace(
        config=SimpleNamespace(agent_id="agent-y"),
        session_id="sess-1",
        _collect_tool_messages=lambda: [],
        crystallizer=None,
    )
    pipe = _make_pipe(agent)
    asyncio.run(pipe._step_record_experience("hello", "world", True))

    assert captured.get("agent_id") == "agent-y", (
        "A-03: EKB 写入必须携带 config.agent_id（原恒 None，归属不了 agent）"
    )
    assert isinstance(captured.get("exp"), ExperienceRecord)


# ═══════════════════════════════════════════════════════════════
# A-13: RSI 迭代阻塞事件循环
# ═══════════════════════════════════════════════════════════════


def _patch_improver(monkeypatch):
    """隔离 _step_rsi_iteration 前置的技能改进扫描（与本缺陷无关）。"""
    improver = SimpleNamespace(
        propose_pending_improvements=lambda: [],
        apply_improvement=lambda *a, **k: False,
    )
    monkeypatch.setattr(
        "neurova.evolution.skill_improver.get_skill_improver", lambda: improver
    )


def test_a13_rsi_run_iteration_runs_off_event_loop(monkeypatch):
    """run_iteration（SQLite/寻优重活）必须离开事件循环线程执行，返回值透传。"""
    loop_thread = threading.get_ident()
    used_threads = []

    class FakeRSI:
        def should_continue(self):
            return True

        def run_iteration(self):
            used_threads.append(threading.get_ident())
            return {"convergence": {"status": "converged"}}

    _patch_improver(monkeypatch)

    agent = SimpleNamespace(config=SimpleNamespace(agent_id="a"), turn_count=1)
    pipe = _make_pipe(agent)
    pipe._get_dependency = lambda name: FakeRSI() if name == "rsi_orchestrator" else None

    result = asyncio.run(pipe._step_rsi_iteration())

    assert result == {"convergence": {"status": "converged"}}, "返回值必须原样透传"
    assert used_threads and used_threads[0] != loop_thread, (
        "A-13: run_iteration 含同步重活，不得在事件循环线程内执行"
    )


def test_a13_rsi_iteration_exception_semantics_preserved(monkeypatch):
    """run_iteration 抛错仍按原语义：步骤 FAILED + 返回 None，不炸穿。"""

    class BrokenRSI:
        def should_continue(self):
            return True

        def run_iteration(self):
            raise ValueError("iteration exploded")

    _patch_improver(monkeypatch)

    agent = SimpleNamespace(config=SimpleNamespace(agent_id="a"), turn_count=1)
    pipe = _make_pipe(agent)
    pipe._get_dependency = lambda name: BrokenRSI() if name == "rsi_orchestrator" else None

    result = asyncio.run(pipe._step_rsi_iteration())

    assert result is None
    failed = [r for r in pipe._step_results if r.status == StepStatus.FAILED]
    assert any(r.step_name == "rsi_iteration" for r in failed)


# ═══════════════════════════════════════════════════════════════
# A-14: ImportError 移出编程错误集合
# ═══════════════════════════════════════════════════════════════


def test_a14_import_error_removed_from_programming_errors():
    from neurova.post_chat_pipeline import PostChatPipeline as P

    assert ImportError not in P._PROGRAMMING_ERRORS, (
        "A-14: ImportError（含 ModuleNotFoundError）不得再 re-raise 炸穿整轮"
    )
    assert ModuleNotFoundError not in P._PROGRAMMING_ERRORS
    # 其余编程错误保留 re-raise
    assert TypeError in P._PROGRAMMING_ERRORS
    assert AttributeError in P._PROGRAMMING_ERRORS
    assert NameError in P._PROGRAMMING_ERRORS
    assert SyntaxError in P._PROGRAMMING_ERRORS


def test_a14_module_not_found_degrades_to_failed_step():
    """可选依赖缺失按步骤失败跳过（返回 default），不炸穿。"""

    async def boom():
        raise ModuleNotFoundError("No module named 'some_optional_dep'")

    pipe = _make_pipe(SimpleNamespace())
    result = asyncio.run(pipe._safe_step("opt_step", boom(), default="fallback"))

    assert result == "fallback"
    assert pipe._step_results[-1].status == StepStatus.FAILED
    assert pipe._step_results[-1].step_name == "opt_step"


def test_a14_plain_import_error_degrades_to_failed_step():
    def boom():
        raise ImportError("legacy import failure")

    pipe = _make_pipe(SimpleNamespace())
    result = pipe._safe_step_sync("sync_step", boom, default=None)

    assert result is None
    assert pipe._step_results[-1].status == StepStatus.FAILED


def test_a14_type_error_still_reraises():
    async def boom():
        raise TypeError("real programming bug")

    pipe = _make_pipe(SimpleNamespace())
    with pytest.raises(TypeError):
        asyncio.run(pipe._safe_step("bad", boom(), default="x"))


def test_a14_syntax_error_still_reraises_sync():
    def boom():
        raise SyntaxError("real programming bug")

    pipe = _make_pipe(SimpleNamespace())
    with pytest.raises(SyntaxError):
        pipe._safe_step_sync("bad", boom, default="x")

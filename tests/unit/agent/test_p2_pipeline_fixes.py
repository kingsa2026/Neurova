"""
P2 修复测试（2026-08 代码审计）— 管线/身份/蜂群

覆盖 bug:
1. chat_pipeline.py:1230 `len(user_input) + len(reply) if reply else len(user_input)`
   审计时疑似运算符优先级 bug，经 AST 语义验证为误报（条件表达式优先级低于 +，
   reply 为空时只计输入一次）。保留 AST 语义测试作为回归护栏。
2. post_chat_pipeline._step_generate_tts:
   `use_tts = enable_tts and config.enable_tts`; Agent.chat(enable_tts=None) 契约是
   "None 表示使用配置"，但 API 从不传 enable_tts → None and ... 恒 falsy →
   配置了 enable_tts=True 的 Agent 永远不生成 TTS
3. agent_core._load_identity 从 workspace_path/"workspace"/"memory" 加载 soul.md,
   但标准目录是 workspace_path/"memory"（db/attachments 均在此）→ 自定义身份永不加载
4. post_chat_pipeline._step_proactive_question:
   `should_ask, reason = manager.should_ask_question(context)` 但真实签名返回 bool
   且要求 Dict 上下文 → TypeError 被 except 吞掉，步骤恒 FAILED
5. post_chat_pipeline._step_conflict_detection 调用不存在的 check_conflict()
   并假设 result.has_conflict 结构; 真实 API 是
   detect_conflict(new_memory: Memory, existing_memories: List[Memory]) -> List[Dict]
   → 依赖注入后必然 AttributeError，步骤恒 FAILED
6. swarm.SwarmManager._runs/_tasks 无界增长: 完成的 run 与 asyncio.Task 引用永不清理
   → 长期运行内存泄漏
"""

import ast
import asyncio
import inspect
import textwrap
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestChatPipelineTokenCountPrecedence:
    def _get_total_tokens_expr(self):
        from neurova.agent.chat_pipeline import ChatPipeline

        source = textwrap.dedent(inspect.getsource(ChatPipeline))
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "total_tokens":
                        return node.value
        raise AssertionError("ChatPipeline 中未找到 total_tokens 赋值")

    def test_empty_reply_counts_input_once(self):
        expr = self._get_total_tokens_expr()
        code = compile(ast.Expression(expr), "<total_tokens>", "eval")
        ctx = SimpleNamespace(user_input="abc", reply="")
        value = eval(code, {"__builtins__": {}}, {"ctx": ctx, "len": len})
        assert value == 3, f"reply 为空时 total_tokens 应为 3（输入只计一次），实际 {value}"

    def test_none_reply_counts_input_once(self):
        expr = self._get_total_tokens_expr()
        code = compile(ast.Expression(expr), "<total_tokens>", "eval")
        ctx = SimpleNamespace(user_input="abc", reply=None)
        value = eval(code, {"__builtins__": {}}, {"ctx": ctx, "len": len})
        assert value == 3

    def test_with_reply_counts_both(self):
        expr = self._get_total_tokens_expr()
        code = compile(ast.Expression(expr), "<total_tokens>", "eval")
        ctx = SimpleNamespace(user_input="abc", reply="de")
        value = eval(code, {"__builtins__": {}}, {"ctx": ctx, "len": len})
        assert value == 5


def _make_post_pipeline_fake(deps, config_overrides=None):
    from neurova.post_chat_pipeline import PostChatPipeline

    config = SimpleNamespace(
        enable_tts=False,
        user_id="u1",
        agent_id="a1",
        tts_voice="v1",
        attachment_dir=".",
    )
    for key, value in (config_overrides or {}).items():
        setattr(config, key, value)
    fake = SimpleNamespace(_agt=SimpleNamespace(config=config), _step_results=[])
    fake._get_dependency = lambda name: deps.get(name)
    return fake


class TestTtsEnableContract:
    @pytest.mark.asyncio
    async def test_none_enable_tts_falls_back_to_config(self):
        voice_pipeline = MagicMock()
        voice_pipeline.process_tts = AsyncMock(
            return_value=SimpleNamespace(error=None, audio_data=None)
        )
        fake = _make_post_pipeline_fake(
            {"voice_pipeline": voice_pipeline}, {"enable_tts": True}
        )
        from neurova.post_chat_pipeline import PostChatPipeline

        await PostChatPipeline._step_generate_tts(fake, "reply text", "sess1", None)

        voice_pipeline.process_tts.assert_called_once(), (
            "enable_tts=None 的契约是'使用配置'，config.enable_tts=True 时必须生成 TTS"
        )

    @pytest.mark.asyncio
    async def test_explicit_false_disables_tts(self):
        voice_pipeline = MagicMock()
        voice_pipeline.process_tts = AsyncMock(
            return_value=SimpleNamespace(error=None, audio_data=None)
        )
        fake = _make_post_pipeline_fake(
            {"voice_pipeline": voice_pipeline}, {"enable_tts": True}
        )
        from neurova.post_chat_pipeline import PostChatPipeline

        await PostChatPipeline._step_generate_tts(fake, "reply text", "sess1", False)

        voice_pipeline.process_tts.assert_not_called()

    @pytest.mark.asyncio
    async def test_explicit_true_overrides_config(self):
        voice_pipeline = MagicMock()
        voice_pipeline.process_tts = AsyncMock(
            return_value=SimpleNamespace(error=None, audio_data=None)
        )
        fake = _make_post_pipeline_fake(
            {"voice_pipeline": voice_pipeline}, {"enable_tts": False}
        )
        from neurova.post_chat_pipeline import PostChatPipeline

        await PostChatPipeline._step_generate_tts(fake, "reply text", "sess1", True)

        voice_pipeline.process_tts.assert_called_once(), (
            "显式 enable_tts=True 应覆盖配置（覆盖语义），voice_pipeline 可用时必须执行"
        )


class TestIdentityLoadPath:
    def test_load_identity_reads_from_workspace_memory(self, tmp_path):
        from neurova.agent_core import Agent

        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "soul.md").write_text("我是 Neurova", encoding="utf-8")
        (memory_dir / "personality.md").write_text("温暖而好奇", encoding="utf-8")

        fake = SimpleNamespace(config=SimpleNamespace(workspace_path=tmp_path, name="Test"))
        Agent._load_identity(fake)

        assert fake.soul == "我是 Neurova", (
            "soul.md 位于 workspace/memory/ 下，_load_identity 不得去 workspace/workspace/memory/ 寻找"
        )
        assert fake.personality == "温暖而好奇"


class TestProactiveQuestionContract:
    @pytest.mark.asyncio
    async def test_empty_queue_skips_without_failure(self):
        from neurova.post_chat_pipeline import PostChatPipeline, StepStatus

        # 契约迁移: 主动提问统一接入 QuestionQueueManager（原
        # proactive_question_manager 全仓无实例化，属零调用死路径）
        manager = MagicMock(spec=["get_next_question"])
        manager.get_next_question.return_value = None
        fake = _make_post_pipeline_fake({"question_queue_manager": manager})

        result = await PostChatPipeline._step_proactive_question(fake, "你好", "你好呀")

        assert result is None
        statuses = [r.status for r in fake._step_results]
        assert StepStatus.FAILED not in statuses, (
            "空队列应 SKIPPED，不得打成 FAILED"
        )
        manager.get_next_question.assert_called_once()

    @pytest.mark.asyncio
    async def test_pending_question_is_surfaced_and_marked_asked(self):
        from neurova.post_chat_pipeline import PostChatPipeline, StepStatus

        entry = SimpleNamespace(id="q1", content="你刚才提到的事，能多说说吗？")
        manager = MagicMock(spec=["get_next_question", "mark_asked"])
        manager.get_next_question.return_value = entry
        manager.mark_asked.return_value = True
        fake = _make_post_pipeline_fake({"question_queue_manager": manager})

        result = await PostChatPipeline._step_proactive_question(fake, "你好", "你好呀")

        assert result == "你刚才提到的事，能多说说吗？"
        assert any(r.status == StepStatus.EXECUTED for r in fake._step_results)
        manager.mark_asked.assert_called_once_with("q1"), "弹出的问题必须标记已提问以进入冷却"


class TestConflictDetectionRealApi:
    @pytest.mark.asyncio
    async def test_uses_detect_conflict_and_reports_conflicts(self):
        from neurova.cognitive_layers.memory_layer.conflict import ConflictDetector
        from neurova.post_chat_pipeline import PostChatPipeline, StepStatus

        detector = ConflictDetector(use_semantic=False)
        memory_manager = MagicMock()
        memory_manager.recall.return_value = [
            {"id": "m1", "content": "系统运行正常"},
        ]
        fake = _make_post_pipeline_fake(
            {"conflict_detector": detector, "memory_manager": memory_manager}
        )

        await PostChatPipeline._step_conflict_detection(fake, "系统怎么样", "系统出故障了")

        statuses = [r.status for r in fake._step_results]
        assert StepStatus.FAILED not in statuses, (
            "真实 API 是 detect_conflict()，调用不存在的 check_conflict() 不得把步骤打成 FAILED"
        )
        executed = [r for r in fake._step_results if r.status == StepStatus.EXECUTED]
        assert executed, "冲突检测步骤必须实际执行"
        assert executed[0].data.get("conflicts_count", 0) >= 1, (
            "「正常」与「故障」构成矛盾对，应检出至少 1 处冲突"
        )

    @pytest.mark.asyncio
    async def test_no_conflict_reports_zero(self):
        from neurova.cognitive_layers.memory_layer.conflict import ConflictDetector
        from neurova.post_chat_pipeline import PostChatPipeline, StepStatus

        detector = ConflictDetector(use_semantic=False)
        memory_manager = MagicMock()
        memory_manager.recall.return_value = []
        fake = _make_post_pipeline_fake(
            {"conflict_detector": detector, "memory_manager": memory_manager}
        )

        await PostChatPipeline._step_conflict_detection(fake, "今天天气", "今天天气不错")

        executed = [r for r in fake._step_results if r.status == StepStatus.EXECUTED]
        assert executed and executed[0].data.get("conflicts_count") == 0


def _make_swarm_manager(monkeypatch, max_finished=None):
    from neurova.agent.swarm import SwarmManager

    if max_finished is not None:
        monkeypatch.setattr(SwarmManager, "MAX_FINISHED_RUNS", max_finished, raising=False)
    manager = SwarmManager()
    fake_agent = SimpleNamespace(config=SimpleNamespace(name="sub-agent"))

    async def fake_chat(task, **kwargs):
        return "done"

    fake_agent.chat = fake_chat
    manager._resolve_agent = lambda agent_id: (fake_agent, "default", False)
    return manager


class TestSwarmBoundedMemory:
    @pytest.mark.asyncio
    async def test_finished_runs_evicted_beyond_cap(self, monkeypatch):
        manager = _make_swarm_manager(monkeypatch, max_finished=5)

        for _ in range(12):
            await manager.spawn("task", session_id=None)

        assert len(manager._runs) <= 6, (
            f"完成的 run 必须在超出上限后被逐出，当前累积 {len(manager._runs)} 条"
        )

    @pytest.mark.asyncio
    async def test_active_runs_never_evicted(self, monkeypatch):
        manager = _make_swarm_manager(monkeypatch, max_finished=1)

        gate = asyncio.Event()

        async def hanging_chat(task, **kwargs):
            await gate.wait()
            return "done"

        async def fast_chat(task, **kwargs):
            return "done"

        hanging_agent = SimpleNamespace(config=SimpleNamespace(name="sub"), chat=hanging_chat)
        fast_agent = SimpleNamespace(config=SimpleNamespace(name="sub"), chat=fast_chat)

        manager._resolve_agent = lambda agent_id: (hanging_agent, "default", False)
        bg = await manager.spawn("task", background=True, session_id=None)

        manager._resolve_agent = lambda agent_id: (fast_agent, "default", False)
        await manager.spawn("task", session_id=None)
        await manager.spawn("task", session_id=None)

        active = manager.list_active()
        assert any(r["subagent_id"] == bg["subagent_id"] for r in active), (
            "运行中的 run 不得被逐出"
        )
        gate.set()
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_background_task_ref_removed_after_completion(self, monkeypatch):
        manager = _make_swarm_manager(monkeypatch)

        result = await manager.spawn("task", background=True, session_id=None)
        subagent_id = result["subagent_id"]
        task = manager._tasks.get(subagent_id)
        assert task is not None

        await task
        await asyncio.sleep(0)

        assert subagent_id not in manager._tasks, (
            "后台任务完成后 asyncio.Task 引用必须移除，否则长期运行泄漏"
        )

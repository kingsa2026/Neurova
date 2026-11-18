# -*- coding: utf-8 -*-
"""记忆蒸馏回写（2026-11-18 立项）单元契约。

钉死：
- 开关关（NEUROVA_MEMORY_DISTILL 默认 off）= 零行为：不调 LLM、不碰候选库；
- 开 = 真链路：LLM 归纳 JSON → admission 筛查 → pending_memories 候选
  （proposed_by=distiller），人工 confirm 后进 remember_fn（转正入口）；
- 护栏：LLM 失败/超时/坏 JSON 计连续熔断（3 次后跳过，可复位）；
  窗口过短跳过；敏感内容 enforce 策略下跳过；
- 去重：同内容重复蒸馏只留一条未决候选（store 指纹幂等）；
- 接线：PostChatPipeline 注册 memory_distill 后台步骤。
"""

import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest

from neurova.memory import pending_memory as pending_memory_module
from neurova.memory.pending_memory import get_pending_memory_store

WINDOW_INPUT = "请帮我把这个项目背景记录下来，后续对话请保持口径一致，不要偏离既定结论"
WINDOW_REPLY = "好的，我已理解该项目背景，并会在后续回答中保持同一口径与结论。"


def run(coro):
    return asyncio.run(coro)


class StubLLM:
    """非流式 .chat 桩（与 AgentLLMClient.chat 异步形态一致）。"""

    def __init__(self, content: str = "", error: bool = False, delay: float = 0.0):
        self.content = content
        self.error = error
        self.delay = delay
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append(list(messages))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise RuntimeError("provider down")
        return SimpleNamespace(content=self.content)


def makeAgent(llm, agent_id="agent-d1"):
    return SimpleNamespace(llm_client=llm, config=SimpleNamespace(agent_id=agent_id))


def candidatesJson(*items) -> str:
    return json.dumps(list(items), ensure_ascii=False)


@pytest.fixture
def freshStore(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pending_memory_module, "_process_store", None)
    return get_pending_memory_store()


class TestDistillGate:
    def test_flag_off_zero_behavior(self, freshStore, monkeypatch):
        """开关关（默认）：不调 LLM、不产候选——零行为变化。"""
        monkeypatch.delenv("NEUROVA_MEMORY_DISTILL", raising=False)
        from neurova.memory.distiller import distillTurnMemory

        llm = StubLLM(candidatesJson({"content": "用户偏好简洁回复", "category": "preference"}))
        out = run(distillTurnMemory(
            makeAgent(llm), user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))

        assert out.get("skipped") == "disabled"
        assert llm.calls == [], "开关关闭时不得调用 LLM"
        assert freshStore.list_pending(proposed_by="distiller") == []

    def test_window_too_short_skipped(self, freshStore, monkeypatch):
        monkeypatch.setenv("NEUROVA_MEMORY_DISTILL", "1")
        from neurova.memory.distiller import distillTurnMemory

        llm = StubLLM(candidatesJson())
        out = run(distillTurnMemory(makeAgent(llm), user_input="好的", reply="嗯", session_id="s1"))
        assert out.get("skipped") == "window_too_short"
        assert llm.calls == []


class TestDistillHappyPath:
    def test_flag_on_proposes_into_pending(self, freshStore, monkeypatch):
        monkeypatch.setenv("NEUROVA_MEMORY_DISTILL", "1")
        from neurova.memory.distiller import distillTurnMemory

        llm = StubLLM(candidatesJson(
            {"content": "用户偏好先给结论再展开", "category": "preference"},
            {"content": "用户的项目代号是 Neurova", "category": "project"},
        ))
        agent = makeAgent(llm)
        out = run(distillTurnMemory(
            agent, user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))

        assert out.get("submitted") == 2, out
        pendings = freshStore.list_pending(proposed_by="distiller")
        assert len(pendings) == 2
        contents = {p["content"] for p in pendings}
        assert "用户偏好先给结论再展开" in contents
        assert "用户的项目代号是 Neurova" in contents
        # LLM 收到的是 messages 形态（与 AgentLLMClient.chat 契约一致）
        assert llm.calls and llm.calls[0][0]["role"] == "user"

    def test_duplicate_content_single_pending(self, freshStore, monkeypatch):
        """同内容重复蒸馏：store 指纹幂等，未决候选只留一条。"""
        monkeypatch.setenv("NEUROVA_MEMORY_DISTILL", "1")
        from neurova.memory.distiller import distillTurnMemory

        agent = makeAgent(StubLLM(candidatesJson(
            {"content": "用户偏好先给结论再展开", "category": "preference"})))
        run(distillTurnMemory(agent, user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))
        out2 = run(distillTurnMemory(agent, user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))

        assert len(freshStore.list_pending(proposed_by="distiller")) == 1
        assert out2.get("duplicates") == 1, out2

    def test_confirmed_candidate_reaches_remember_fn(self, freshStore, monkeypatch):
        """D3：蒸馏候选走既有 confirm 机制转正（remember_fn 收到三元组）。"""
        monkeypatch.setenv("NEUROVA_MEMORY_DISTILL", "1")
        from neurova.memory.distiller import distillTurnMemory

        run(distillTurnMemory(
            makeAgent(StubLLM(candidatesJson(
                {"content": "用户的项目代号是 Neurova", "category": "project"}))),
            user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))

        pendings = freshStore.list_pending(proposed_by="distiller")
        assert len(pendings) == 1
        remembered = []

        def remember_fn(content, category, memory_type):
            remembered.append((content, category, memory_type))
            return "mem-1"

        freshStore.confirm(pendings[0]["id"], remember_fn, decided_by="admin")
        assert remembered == [("用户的项目代号是 Neurova", "project", "semantic")]


class TestDistillGuardrails:
    def test_sensitive_content_skipped_under_enforce(self, freshStore, monkeypatch):
        """enforce 策略：命中敏感模式族的候选不得进候选队列。"""
        monkeypatch.setenv("NEUROVA_MEMORY_DISTILL", "1")
        from neurova.memory.distiller import distillTurnMemory
        from neurova.memory_admission import setMemoryAdmissionPolicy

        previous = None
        try:
            llm = StubLLM(candidatesJson(
                {"content": "用户的登录密码：hunter2secret，请记住", "category": "fact"},
                {"content": "用户偏好先给结论再展开", "category": "preference"},
            ))
            out = run(distillTurnMemory(
                makeAgent(llm), user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))

            assert out.get("skipped_sensitive") == 1, out
            contents = {p["content"] for p in freshStore.list_pending(proposed_by="distiller")}
            assert contents == {"用户偏好先给结论再展开"}
        finally:
            if previous is not None:
                setMemoryAdmissionPolicy(previous)

    def test_llm_failure_opens_breaker(self, freshStore, monkeypatch):
        monkeypatch.setenv("NEUROVA_MEMORY_DISTILL", "1")
        from neurova.memory.distiller import distillTurnMemory, resetDistillerBreaker

        agent = makeAgent(StubLLM(error=True))
        try:
            for _ in range(3):
                out = run(distillTurnMemory(
                    agent, user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))
                assert "error" in out, out
            out = run(distillTurnMemory(
                agent, user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))
            assert out.get("skipped") == "breaker", out
            assert freshStore.list_pending(proposed_by="distiller") == []
        finally:
            resetDistillerBreaker("agent-d1")

    def test_llm_timeout_counts_as_failure(self, freshStore, monkeypatch):
        monkeypatch.setenv("NEUROVA_MEMORY_DISTILL", "1")
        from neurova.memory import distiller
        from neurova.memory.distiller import distillTurnMemory

        monkeypatch.setattr(distiller, "_LLM_TIMEOUT_S", 0.05)
        agent = makeAgent(StubLLM(candidatesJson({"content": "x", "category": "fact"}), delay=0.5))
        out = run(distillTurnMemory(
            agent, user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))
        assert "error" in out and "timeout" in out["error"].lower(), out

    def test_malformed_json_counts_as_failure(self, freshStore, monkeypatch):
        monkeypatch.setenv("NEUROVA_MEMORY_DISTILL", "1")
        from neurova.memory.distiller import distillTurnMemory

        agent = makeAgent(StubLLM("我觉得这段对话没什么可记的。"))
        out = run(distillTurnMemory(
            agent, user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))
        assert "error" in out and "parse" in out["error"], out
        assert freshStore.list_pending(proposed_by="distiller") == []

    def test_llm_error_envelope_counts_as_failure(self, freshStore, monkeypatch):
        """AgentLLMClient 失败形态：content 以 [LLM Error] 开头（不抛异常）。"""
        monkeypatch.setenv("NEUROVA_MEMORY_DISTILL", "1")
        from neurova.memory.distiller import distillTurnMemory

        agent = makeAgent(StubLLM("[LLM Error] No client available"))
        out = run(distillTurnMemory(
            agent, user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))
        assert "error" in out, out


class TestPostChatWiring:
    def test_process_registers_memory_distill_step(self):
        """轮末管线必须注册 memory_distill 后台步骤（开关开时才跑，关时零步）。"""
        from neurova import post_chat_pipeline as pcp

        source = inspect.getsource(pcp.PostChatPipeline.process)
        assert "memory_distill" in source, "process 未注册 memory_distill 后台步骤"
        module_source = inspect.getsource(pcp)
        assert "_step_memory_distill" in module_source, "缺少步骤执行体"

    def test_step_respects_flag(self, freshStore, monkeypatch):
        """步骤体在开关关闭时直接返回（双保险：注册面+执行体都认开关）。"""
        monkeypatch.delenv("NEUROVA_MEMORY_DISTILL", raising=False)
        from neurova.memory.distiller import distillTurnMemory

        llm = StubLLM(candidatesJson({"content": "x", "category": "fact"}))
        out = run(distillTurnMemory(
            makeAgent(llm), user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))
        assert out.get("skipped") == "disabled"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestDistillMetrics:
    """D4 观测面：蒸馏计数进既有 /metrics 指标读面。"""

    def test_metrics_counter_declared_and_recorded(self, freshStore, monkeypatch):
        monkeypatch.setenv("NEUROVA_MEMORY_DISTILL", "1")
        from neurova.core.metrics import get_metrics
        from neurova.memory.distiller import distillTurnMemory

        metrics = get_metrics()
        counter = getattr(metrics, "memory_distill_candidates_total", None)
        # 独立 agent_id：熔断计数按 agent 隔离，避免吃到前面用例的失败状态
        agent_id = "agent-metrics"
        assert counter is not None, "metrics 缺 memory_distill_candidates_total 计数器"

        def value(outcome: str) -> float:
            return counter.labels(outcome=outcome)._value.get()

        before_submitted = value("submitted")
        before_failed = value("failed")
        run(distillTurnMemory(
            makeAgent(StubLLM(candidatesJson(
                {"content": "用户偏好先给结论再展开", "category": "preference"})),
                agent_id=agent_id),
            user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))
        assert value("submitted") >= before_submitted + 1, "提交候选未计数"

        run(distillTurnMemory(
            makeAgent(StubLLM("这不是 JSON"), agent_id=agent_id),
            user_input=WINDOW_INPUT, reply=WINDOW_REPLY, session_id="s1"))
        assert value("failed") >= before_failed + 1, "失败轮未计数"

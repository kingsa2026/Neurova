"""G2 per-turn 自动定档（auto effort inference）测试

目标：在既有 `_apply_thinking_effort` / `_effort_of` 接缝上，当调用方未显式选档时，
用保守启发式从查询难度推断 light/deep，回写 metadata["thinking_effort"] 作单一真源，
让"回答模式指令注入"与"reasoning_effort 透传"两路同时受益——纯增强，不新建孤岛。

安全边界（放大视角、不破坏核心对话链）：
- 绝不覆盖调用方显式档位（含 standard）。
- 仅在"强分析信号/超长→deep"或"精确寒暄→light"时填充；歧义一律不注入（保持现状）。
- fail-open：推断异常/依赖缺失不阻断对话。
- kill-switch：NEUROVA_AUTO_EFFORT=off 完全停用。
- 无 LLM 调用、无外部 I/O（避免 per-turn 追加成本/时延）。
"""
from __future__ import annotations

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.agent.effort_inference import auto_effort_enabled, infer_query_effort


# ── 纯启发式分类器（无副作用，单测直连）────────────────────────
class TestInferQueryEffort:
    def test_deep_on_analysis_keywords(self):
        assert infer_query_effort("帮我分析这套系统的并发瓶颈并给出重构方案") == "deep"
        assert infer_query_effort("对比 PostgreSQL 和 MySQL 的取舍") == "deep"

    def test_deep_on_long_text(self):
        assert infer_query_effort("需" * 200) == "deep"

    def test_light_on_exact_greeting(self):
        assert infer_query_effort("你好") == "light"
        assert infer_query_effort("谢谢") == "light"

    def test_ambiguous_returns_empty_keep_default(self):
        # 既非强分析信号、也非纯寒暄 → 不改现状
        assert infer_query_effort("帮我看看这个项目") == ""
        assert infer_query_effort("今天天气不错") == ""

    def test_empty_returns_empty(self):
        assert infer_query_effort("") == ""
        assert infer_query_effort("   ") == ""


class TestAutoEffortEnabled:
    def test_default_on(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_AUTO_EFFORT", raising=False)
        assert auto_effort_enabled() is True

    def test_off_switch(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_AUTO_EFFORT", "off")
        assert auto_effort_enabled() is False


# ── 管线接缝集成（_apply_thinking_effort 早期解析回写）───────────
def _pipeline() -> ChatPipeline:
    # 该方法及其解析辅助不依赖 __init__ 状态，裸实例即可测试
    return object.__new__(ChatPipeline)


def _system_content(ctx: ChatContext) -> str:
    for m in ctx.context:
        if isinstance(m, dict) and m.get("role") == "system":
            return str(m.get("content", ""))
    return ""


class TestApplyThinkingEffortAutoResolve:
    def test_absent_effort_deep_text_fills_and_injects(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_AUTO_EFFORT", raising=False)
        pipe = _pipeline()
        ctx = ChatContext(
            user_input="请评估这两种架构的权衡并论证选型",
            metadata={},
            context=[],
        )
        pipe._apply_thinking_effort(ctx)
        assert ctx.metadata.get("thinking_effort") == "deep"
        assert "深度思考" in _system_content(ctx)

    def test_absent_effort_greeting_fills_light(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_AUTO_EFFORT", raising=False)
        pipe = _pipeline()
        ctx = ChatContext(user_input="你好", metadata={}, context=[])
        pipe._apply_thinking_effort(ctx)
        assert ctx.metadata.get("thinking_effort") == "light"
        assert "简洁速答" in _system_content(ctx)

    def test_explicit_effort_never_overridden(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_AUTO_EFFORT", raising=False)
        pipe = _pipeline()
        ctx = ChatContext(
            user_input="分析并论证这个复杂系统的重构方案",  # 本会判 deep
            metadata={"thinking_effort": "standard"},        # 但用户显式选了 standard
            context=[],
        )
        pipe._apply_thinking_effort(ctx)
        assert ctx.metadata["thinking_effort"] == "standard"
        assert _system_content(ctx) == ""  # standard 不注入，保持默认

    def test_explicit_deep_preserved_and_injects(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_AUTO_EFFORT", raising=False)
        pipe = _pipeline()
        ctx = ChatContext(user_input="随便聊点什么", metadata={"thinking_effort": "deep"}, context=[])
        pipe._apply_thinking_effort(ctx)
        assert ctx.metadata["thinking_effort"] == "deep"
        assert "深度思考" in _system_content(ctx)

    def test_ambiguous_text_stays_uninjected(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_AUTO_EFFORT", raising=False)
        pipe = _pipeline()
        ctx = ChatContext(user_input="帮我看看这个项目", metadata={}, context=[])
        pipe._apply_thinking_effort(ctx)
        assert ctx.metadata.get("thinking_effort") in (None, "")
        assert _system_content(ctx) == ""

    def test_kill_switch_off_no_inference(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_AUTO_EFFORT", "off")
        pipe = _pipeline()
        ctx = ChatContext(user_input="评估并论证这套复杂架构的权衡", metadata={}, context=[])
        pipe._apply_thinking_effort(ctx)
        assert ctx.metadata.get("thinking_effort") in (None, "")
        assert _system_content(ctx) == ""

    def test_effort_of_reflects_resolved_value(self, monkeypatch):
        """_effort_of 与指令注入共用同一解析后的档位（单一真源）。"""
        monkeypatch.delenv("NEUROVA_AUTO_EFFORT", raising=False)
        pipe = _pipeline()
        ctx = ChatContext(user_input="一步步推理并证明这个算法的正确性", metadata={}, context=[])
        pipe._apply_thinking_effort(ctx)
        assert pipe._effort_of(ctx) == "deep"

    def test_none_metadata_does_not_crash(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_AUTO_EFFORT", raising=False)
        pipe = _pipeline()
        ctx = ChatContext(user_input="你好", metadata=None, context=[])
        pipe._apply_thinking_effort(ctx)  # 不得抛异常
        assert isinstance(ctx.metadata, dict) and ctx.metadata.get("thinking_effort") == "light"

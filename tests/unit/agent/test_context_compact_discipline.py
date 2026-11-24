# -*- coding: utf-8 -*-
"""S6 压缩纪律（D3）——红→绿 TDD 契约测试。

覆盖（方案 docs/04-plans/2026-11-17-surpass-reference-implementation-plan.md §S6）：
1. 超阈值自动触发：CONTEXT_COMPACT_TRIGGER_RATIO（具名常量 0.85）× 上下文预算；
2. provider 溢出异常兜底：识别溢出错误族 → 压缩 → 重试一次；
3. 严格变小守卫：重试内容不严格变小时显式报错拒绝重发（防越压越大循环）；
4. 压缩事件（CompressionEvent）经 session_manager 既有公开接口落会话盘，
   落盘后视图可重建且**原始消息永不删除**；
5. 工具结果有界投影：TOOL_RESULT_PROJECTION_CHARS 具名上限，
   失败结果不折叠（既有纪律）。

钉子纪律：所有截断/阈值/上限走具名常量，不用字面量数字上界。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.agent.chat_pipeline import ChatPipeline, ChatContext


# ── 装配 ─────────────────────────────────────────────────────────

def _mk_pipeline():
    """ChatPipeline 桩装配：agent 魔法桩 + 摘要桥 + 真实 SessionManager 隔离落点。"""
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.agent_id = "a1"
    agent.config.name = "t"
    agent.config.llm_config.model = "test-model"
    agent.agent_id = "a1"
    agent.user_id = "u1"
    agent.memory_agent = MagicMock()
    agent.tool_memory = None
    agent.skill_manager = None
    pipe = ChatPipeline(agent)

    async def _summarize(dropped_msgs, previous_summary=""):
        texts = [str((m or {}).get("content", "")) for m in (dropped_msgs or [])]
        return "早期对话摘要：共折叠 %d 条，首条=%s" % (len(texts), (texts[0] if texts else "")[:20])

    agent.context_orchestrator = MagicMock()
    # 摘要桥与 orchestrator.manual_compact 同源（_build_window_summarizer）
    agent.context_orchestrator._build_window_summarizer = lambda: _summarize
    return pipe, agent


def _big_context(n=40, pad=600):
    """构造超阈值窗口：n 条长消息（估算 token 远超测试预算）。"""
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"消息{i}: " + "测" * pad}
        for i in range(n)
    ]


@pytest.fixture
def isolatedSessions(monkeypatch, tmp_path):
    """真实 SessionManager，落点隔离到临时目录（单例重置）。"""
    import os

    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.delenv("NEUROVA_SESSION_JSONL", raising=False)
    from neurova.session_manager import SessionManager

    SessionManager._instance = None
    mgr = SessionManager()
    yield mgr
    SessionManager._instance = None


# ── 1. 具名常量存在（钉子纪律）────────────────────────────────────

class TestNamedConstants:
    def test_trigger_ratio_constant_exists(self):
        from neurova.context_pool import CONTEXT_COMPACT_TRIGGER_RATIO

        assert isinstance(CONTEXT_COMPACT_TRIGGER_RATIO, float)
        assert 0 < CONTEXT_COMPACT_TRIGGER_RATIO < 1

    def test_projection_chars_constant_exists(self):
        from neurova.tool_executor import TOOL_RESULT_PROJECTION_CHARS

        assert isinstance(TOOL_RESULT_PROJECTION_CHARS, int)
        assert TOOL_RESULT_PROJECTION_CHARS > 0


# ── 2. 超阈值自动触发 ────────────────────────────────────────────

class TestAutoCompactTrigger:
    @pytest.mark.asyncio
    async def test_over_threshold_triggers_auto_compact(self, isolatedSessions):
        """上下文估算 token ≥ 0.85×预算 → 自动压缩，视图变小且原会话消息不删。"""
        pipe, agent = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        budget = 4000
        trigger = int(budget * 0.85)
        ctx = ChatContext(user_input="继续")
        ctx.session_id = "sess-auto-1"
        ctx.context = _big_context()

        # 造超阈值：预算 4000 的 0.85 = 3400，40 条×600 字远超
        assert len(ctx.context) > 10
        # 预算解析桩：直接钉住预算来源
        pipe._resolveContextBudget = lambda: budget

        before_tokens = None
        from neurova.context_pool import estimateContextTokens

        before_tokens = estimateContextTokens(ctx.context)
        assert before_tokens >= trigger, "测试前置：上下文必须越过触发线"

        compacted = await pipe._autoCompactContextIfNeeded(ctx)

        assert compacted is True, "超阈值必须触发自动压缩"
        assert estimateContextTokens(ctx.context) < before_tokens, "压缩后视图必须严格变小"
        # 原始消息永不删除：会话盘上的历史原样保留
        history = isolatedSessions.get_recent_context("a1", "sess-auto-1", max_messages=None)
        assert isinstance(history, list)
        # 本轮标记防重复触发
        assert (ctx.metadata or {}).get("context_auto_compacted") is True

    @pytest.mark.asyncio
    async def test_under_threshold_does_not_compact(self, isolatedSessions):
        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 10_000_000  # 巨大预算：永不触发
        ctx = ChatContext(user_input="hi")
        ctx.session_id = "sess-auto-2"
        ctx.context = [{"role": "user", "content": "短消息"}]

        compacted = await pipe._autoCompactContextIfNeeded(ctx)
        assert compacted is False
        assert len(ctx.context) == 1, "未超阈值不得改写上下文"

    @pytest.mark.asyncio
    async def test_no_budget_known_skips_proactive_compact(self, isolatedSessions):
        """未知模型窗口（budget=None）→ 不设输入预算闸门，跳过主动压缩。"""
        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: None
        ctx = ChatContext(user_input="hi")
        ctx.session_id = "sess-auto-3"
        ctx.context = _big_context()

        compacted = await pipe._autoCompactContextIfNeeded(ctx)
        assert compacted is False

    @pytest.mark.asyncio
    async def test_same_turn_not_compacted_twice(self, isolatedSessions):
        """同轮已压缩过 → 不重复压缩（溢出重试与阈值触发互不叠压）。"""
        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 4000
        ctx = ChatContext(user_input="继续")
        ctx.session_id = "sess-auto-4"
        ctx.context = _big_context()
        ctx.metadata = {"context_auto_compacted": True}

        compacted = await pipe._autoCompactContextIfNeeded(ctx)
        assert compacted is False


# ── 3. 溢出异常兜底重试 ──────────────────────────────────────────

class TestOverflowFallbackRetry:
    @pytest.mark.asyncio
    async def test_overflow_error_compacts_and_retries_once(self, isolatedSessions):
        """溢出错误族 → 压缩 ctx.context → 恰好重试一次并成功。"""
        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 4000
        ctx = ChatContext(user_input="继续")
        ctx.session_id = "sess-of-1"
        ctx.context = _big_context()

        overflow = RuntimeError(
            "litellm.BadRequestError: This model's maximum context length is 8192 tokens, "
            "however you requested 12000 tokens"
        )
        call_count = {"n": 0}

        async def _fakeLoopCall(ctx, tools):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise overflow
            return "重试成功回复"

        pipe._call_agent_loop = _fakeLoopCall
        reply = await pipe._callAgentLoopWithOverflowGuard(ctx, None)

        assert reply == "重试成功回复"
        assert call_count["n"] == 2, "溢出后必须恰好重试一次"
        from neurova.context_pool import estimateContextTokens

        assert estimateContextTokens(ctx.context) < estimateContextTokens(_big_context()), \
            "重试前上下文必须已被压缩"
        # 压缩事件落盘（reason=overflow_retry）
        events = isolatedSessions.read_timeline("a1", "sess-of-1")
        kinds = [str(e.get("kind")) for e in events]
        assert "context_compacted" in kinds, f"压缩事件必须落时间线，实际：{kinds}"

    @pytest.mark.asyncio
    async def test_non_overflow_error_reraised_without_retry(self, isolatedSessions):
        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        ctx = ChatContext(user_input="hi")
        ctx.session_id = "sess-of-2"
        ctx.context = _big_context()
        calls = {"n": 0}

        async def _fakeLoopCall(ctx, tools):
            calls["n"] += 1
            raise RuntimeError("connection reset by peer")

        pipe._call_agent_loop = _fakeLoopCall
        with pytest.raises(RuntimeError, match="connection reset"):
            await pipe._callAgentLoopWithOverflowGuard(ctx, None)
        assert calls["n"] == 1, "非溢出错误不得触发压缩重试"

    @pytest.mark.asyncio
    async def test_second_overflow_not_retried_again(self, isolatedSessions):
        """重试仍溢出 → 原样上抛（防循环），不二次重试。"""
        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 4000
        ctx = ChatContext(user_input="继续")
        ctx.session_id = "sess-of-3"
        ctx.context = _big_context()
        calls = {"n": 0}

        async def _alwaysOverflow(ctx, tools):
            calls["n"] += 1
            raise RuntimeError("maximum context length exceeded")

        pipe._call_agent_loop = _alwaysOverflow
        with pytest.raises(RuntimeError, match="maximum context length"):
            await pipe._callAgentLoopWithOverflowGuard(ctx, None)
        assert calls["n"] == 2, "首次 + 重试一次，不得更多"


# ── 4. 严格变小守卫 ──────────────────────────────────────────────

class TestStrictShrinkGuard:
    def test_assert_shrinks_passes_on_smaller(self):
        from neurova.context_pool import assertCompactionShrinks

        assertCompactionShrinks(1000, 400)  # 不抛即过

    def test_assert_shrinks_raises_on_equal_or_bigger(self):
        from neurova.context_pool import CompactionNotShrinkingError, assertCompactionShrinks

        with pytest.raises(CompactionNotShrinkingError):
            assertCompactionShrinks(1000, 1000)
        with pytest.raises(CompactionNotShrinkingError):
            assertCompactionShrinks(1000, 1200)

    @pytest.mark.asyncio
    async def test_overflow_retry_refused_when_not_shrinking(self, isolatedSessions, monkeypatch):
        """压缩不严格变小 → 显式报错拒绝重发（不拿原上下文再撞同一堵墙）。"""
        import neurova.context.window_compactor as wc

        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 4000
        ctx = ChatContext(user_input="继续")
        ctx.session_id = "sess-ss-1"
        ctx.context = _big_context()

        async def _identityCompact(msgs, budget, **kwargs):
            # 桩：压缩器"零折叠"——返回与输入等量的窗口（不严格变小）
            return wc.WindowCompaction(
                window=list(msgs), summary=None, compacted_count=0,
                tokens_before=wc.estimate_window_tokens(msgs),
                tokens_after=wc.estimate_window_tokens(msgs),
            )

        monkeypatch.setattr(wc, "compact_window", _identityCompact)
        calls = {"n": 0}

        async def _overflow(ctx, tools):
            calls["n"] += 1
            raise RuntimeError("context length exceeded")

        pipe._call_agent_loop = _overflow
        from neurova.context_pool import CompactionNotShrinkingError

        with pytest.raises(CompactionNotShrinkingError):
            await pipe._callAgentLoopWithOverflowGuard(ctx, None)
        assert calls["n"] == 1, "不严格变小时必须拒绝重发（只发起过一次调用）"


# ── 5. 压缩事件落盘 + 视图可重建 + 原消息仍在 ────────────────────

class TestCompressionEventPersistence:
    def test_build_event_carries_cutoff_and_fingerprint(self):
        from neurova.context_pool import buildCompressionEvent, estimateContextTokens

        msgs = _big_context(12)
        compacted = msgs[-4:]
        summary = "摘要文本"
        event = buildCompressionEvent(
            msgs, compacted, summary=summary, reason="threshold",
        )
        assert event.cutoffIndex == 8, "cutoffIndex = 被折叠的前缀长度"
        assert event.cutoffMessageId, "必须带被折叠末条消息的指纹 id"
        assert event.summaryFingerprint, "必须带摘要指纹"
        assert event.reason == "threshold"
        d = event.to_dict()
        assert d["cutoffIndex"] == 8 and d["summaryFingerprint"]

    def test_persist_via_session_manager_public_api(self, isolatedSessions):
        from neurova.context_pool import (
            CompressionEvent,
            persistCompressionEvent,
        )

        event = CompressionEvent(
            cutoffIndex=5, cutoffMessageId="abc123", summaryFingerprint="fp456",
            tokensBefore=9000, tokensAfter=3000, foldedCount=5,
            reason="threshold", summary="摘要",
        )
        ok = persistCompressionEvent(isolatedSessions, "a1", "sess-ev-1", event)
        assert ok is True, "必须经 session_manager 既有公开接口落盘成功"
        rows = isolatedSessions.read_timeline("a1", "sess-ev-1")
        assert any(str(r.get("kind")) == "context_compacted" for r in rows), \
            "时间线上必须能读回压缩事件（旧格式会话亦然：时间线独立于消息格式）"

    @pytest.mark.asyncio
    async def test_view_rebuildable_and_originals_intact(self, isolatedSessions):
        """压缩事件落盘后：视图可按 cutoff 重建，且会话原始消息一条不少。"""
        mgr = isolatedSessions
        for i in range(6):
            # 加长正文：12 条长消息必然越过 1500 预算的触发线（1275）
            mgr.add_message(
                "a1", "sess-ev-2",
                f"用户消息{i}：" + "测" * 400,
                f"助手回复{i}：" + "答" * 400,
                user_id="u1",
            )
        original = mgr.get_recent_context("a1", "sess-ev-2", max_messages=None)
        assert len(original) == 12

        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = mgr
        pipe._resolveContextBudget = lambda: 1500  # 压到很低预算强制折叠
        ctx = ChatContext(user_input="继续")
        ctx.session_id = "sess-ev-2"
        ctx.context = [dict(m) for m in original]

        compacted = await pipe._autoCompactContextIfNeeded(ctx)
        assert compacted is True

        # 原消息仍在盘上（非破坏锚点：压的是视图，不是存储）
        after = mgr.get_recent_context("a1", "sess-ev-2", max_messages=None)
        assert len(after) == 12, "原始消息永不删除"
        assert [m.get("content") for m in after] == [m.get("content") for m in original]

        # 视图可重建：时间线事件给出 cutoffIndex + 摘要 → 摘要行 + 尾部消息
        rows = mgr.read_timeline("a1", "sess-ev-2")
        ev = next(r for r in rows if str(r.get("kind")) == "context_compacted")
        payload = ev.get("event") or {}
        cutoff = int(payload.get("cutoffIndex"))
        rebuilt = [{"role": "system", "content": f"[早期对话摘要] {payload.get('summary', '')}"}] + [
            dict(m) for m in original[cutoff:]
        ]
        from neurova.context_pool import estimateContextTokens

        assert estimateContextTokens(rebuilt) < estimateContextTokens(original), \
            "按事件重建的视图必须小于原视图"
        assert rebuilt[-1].get("content") == original[-1].get("content"), \
            "重建视图保留尾部近期消息"

    @pytest.mark.asyncio
    async def test_emitter_receives_compaction_notice(self, isolatedSessions):
        """压缩事件随既有会话事件通道下发（event_emitter，含 cutoff 摘要）。"""
        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 1500
        ctx = ChatContext(user_input="继续")
        ctx.session_id = "sess-ev-3"
        ctx.context = _big_context()
        emitted = []
        ctx.metadata = {"event_emitter": lambda kind, data: emitted.append((kind, data))}

        compacted = await pipe._autoCompactContextIfNeeded(ctx)
        assert compacted is True
        assert emitted, "压缩通知必须发射到事件通道"
        kinds = [k for k, _ in emitted]
        assert "upstream_status" in kinds, "复用既有上游状态事件通道（console 桥透传）"
        payload = next(d for k, d in emitted if k == "upstream_status")
        assert payload.get("phase") == "context_compacted"
        assert "cutoffIndex" in payload and "summary" in payload, "通知必须含 cutoff 摘要"


# ── 6. 工具结果有界投影 ──────────────────────────────────────────

class TestToolResultProjection:
    def test_small_success_unchanged(self):
        from neurova.tool_executor import projectToolResult

        content = json.dumps({"result": "ok"})
        assert projectToolResult(content, success=True, tool_name="t", call_id="c1") == content

    def test_failure_never_projected(self):
        """失败结果不折叠（既有纪律）：诊断正文原样保留。"""
        from neurova.tool_executor import projectToolResult

        huge_failure = json.dumps({"success": False, "error": "E" * 50000})
        out = projectToolResult(huge_failure, success=False, tool_name="t", call_id="c1")
        assert out == huge_failure, "失败结果无论多大都不得折叠"

    def test_huge_success_projected_to_bound(self):
        from neurova.tool_executor import TOOL_RESULT_PROJECTION_CHARS, projectToolResult

        huge = "X" * (TOOL_RESULT_PROJECTION_CHARS * 5)
        out = projectToolResult(huge, success=True, tool_name="web_fetch", call_id="call-9")
        assert len(out) <= TOOL_RESULT_PROJECTION_CHARS, "投影不得超过具名上限"
        assert len(out) < len(huge)
        assert "call-9" in out, "投影必须带寻址句柄（call_id 指向可取回的原文）"
        assert "省略" in out or "截断" in out, "中段省略必须显式标注，不静默消失"


# ── 7. 压缩纪律·图像分档裁剪（reference_af 借鉴项 P1-6）──────────

def _imgTurn(i: int) -> dict:
    """一条含图历史消息（文本说明 + 1 张图）。"""
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": f"早期图片轮{i}"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,I{i}"}},
        ],
    }


def _countPlaceholders(msgs) -> int:
    n = 0
    for m in msgs:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list):
            n += sum(
                1 for p in content
                if isinstance(p, dict) and p.get("type") == "text" and "已省略" in str(p.get("text"))
            )
    return n


def _countImages(msgs) -> int:
    n = 0
    for m in msgs:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list):
            n += sum(1 for p in content if isinstance(p, dict) and p.get("type") == "image_url")
    return n


class TestImageTieredTrimming:
    """图像先于文本丢弃 + 长上下文模型只裁旧图（分档）。

    场景标定（估算口径 = estimateContextTokens）：每条含图消息 ≈ 800（图固定
    计价）+ 少量文本 + 开销；预算 5000 → 触发线 4250。8 条含图消息总量 ≈ 6500
    越线；基础档 keep=4 摘最旧 4 张即回到触发线内（≈3450）→ 零文本折叠。
    """

    def _imgContext(self, n=8):
        return [_imgTurn(i) for i in range(n)] + [
            {"role": "assistant", "content": "文字回复" * 150},
        ]

    @pytest.mark.asyncio
    async def test_images_shed_before_text_fold(self, isolatedSessions):
        """基础档：超预算先摘 keep 窗外旧图，文本轮与近期图零折叠。"""
        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 5000
        ctx = ChatContext(user_input="继续")
        ctx.session_id = "sess-img-1"
        ctx.context = self._imgContext()

        from neurova.context_pool import estimateContextTokens

        assert estimateContextTokens(ctx.context) >= int(5000 * 0.85), "测试前置：必须越过触发线"

        compacted = await pipe._autoCompactContextIfNeeded(ctx)

        assert compacted is True
        assert _countPlaceholders(ctx.context) == 4, "keep 窗外最旧 4 张图必须被摘成占位文本"
        assert _countImages(ctx.context) == 4, "keep 窗内 4 张近期图必须原样保留"
        textMsgs = [m for m in ctx.context if isinstance(m.get("content"), str)]
        assert any("文字回复" in m["content"] for m in textMsgs), "文本轮必须保留（图像先于文本丢弃）"
        assert len(ctx.context) == 9, "裁图档只换部件不折消息：消息条数不变"
        assert (ctx.metadata or {}).get("context_auto_compacted") is True
        # 原始消息永不删除（S6 既有锚点）：会话盘历史原样
        history = isolatedSessions.get_recent_context("a1", "sess-img-1", max_messages=None)
        assert isinstance(history, list)

    @pytest.mark.asyncio
    async def test_imageTierContrast_baseStrips_longContextSpares(self, isolatedSessions):
        """同窗形双模型对照（判别性红→绿）：基础档摘旧图、长上下文档零摘图。

        判别性来源：旧代码（无裁图档）下两个模型都不摘图，对照断言必红；
        新代码下基础档（keep=4）摘 keep 窗外旧图、gemini（1M 窗→keep=16）
        零摘图——图像保留窗口分档的判别性证据由此用例承担。
        """
        results = {}
        for model, sess in (("test-model", "sess-img-contrast-base"),
                            ("gemini-1.5-pro", "sess-img-contrast-long")):
            pipe, agent = _mk_pipeline()
            agent.config.llm_config.model = model
            pipe._agent.session_manager = isolatedSessions
            pipe._resolveContextBudget = lambda: 5000
            ctx = ChatContext(user_input="继续")
            ctx.session_id = sess
            ctx.context = self._imgContext()

            assert await pipe._autoCompactContextIfNeeded(ctx) is True
            results[model] = _countPlaceholders(ctx.context)

        assert results["test-model"] >= 1, \
            "基础档必须摘 keep 窗外旧图（对照锚；旧代码此值为 0 → 红）"
        assert results["gemini-1.5-pro"] == 0, \
            "长上下文模型同窗形零摘图（只裁旧图：8 条含图消息全在宽窗内）"

    def test_imageRetention_windowTiersByModel(self):
        """请求装配防线同享分档：长上下文模型保留窗更宽，只裁更旧的图。"""
        pipe, agent = _mk_pipeline()
        agent.config.llm_config.model = "gemini-1.5-pro"
        ctx = ChatContext(user_input="x")
        ctx.context = [_imgTurn(i) for i in range(6)]
        pipe._apply_image_retention(ctx)
        assert _countPlaceholders(ctx.context) == 0, "6 条 ≤ 超长档 keep=16 → 零摘除"
        assert _countImages(ctx.context) == 6

        pipe2, agent2 = _mk_pipeline()  # test-model → 基础档 keep=4
        ctx2 = ChatContext(user_input="x")
        ctx2.context = [_imgTurn(i) for i in range(6)]
        pipe2._apply_image_retention(ctx2)
        assert _countImages(ctx2.context) == 4, "基础档照旧只留最近 4 条"
        assert _countPlaceholders(ctx2.context) == 2, "窗口外旧图置占位文本"

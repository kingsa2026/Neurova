# -*- coding: utf-8 -*-
"""S15 D3 收尾——压缩失败冷却 + 子代理软目标 契约测试（先红）。

覆盖（方案 docs/04-plans/2026-11-17-surpass-reference-implementation-plan.md §S15）：
1. 失败冷却：压缩失败后进入递增冷却（COMPACTION_FAILURE_COOLDOWN_STEPS=(5,15,30)
   具名常量），冷却期内跳过自动触发（手动 /compact 不受限）；冷却状态随会话
   持久（复用 S5/S6 事件面落时间线），进程重启不丢；
2. 子代理软目标：swarm member 会话上下文逼近 SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS
   （具名常量）时先于硬预算触发压缩，保留近期原文（与 S6 投影/折叠合流）；
3. 冷却/软目标事件随会话事件面可见（复用 S6 context_compacted 通知形态）。

钉子纪律：全部阈值具名常量；冷却机制与 S6 触发/守卫/事件面合流（教义第 6 条，
不新造第二套压缩体系）。
"""

from unittest.mock import MagicMock

import pytest

from neurova.agent.chat_pipeline import ChatPipeline, ChatContext


# ── 装配（与 test_context_compact_discipline 同款）───────────────

def _mk_pipeline():
    """ChatPipeline 桩装配：agent 魔法桩 + 摘要桥 + 隔离落点的真实 SessionManager
    由 isolatedSessions fixture 注入。"""
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


def _mk_ctx(session_id, context=None, metadata=None):
    ctx = ChatContext(user_input="继续")
    ctx.session_id = session_id
    ctx.context = list(context or _big_context())
    if metadata is not None:
        ctx.metadata = dict(metadata)
    return ctx


@pytest.fixture
def isolatedSessions(monkeypatch, tmp_path):
    """真实 SessionManager，落点隔离到临时目录（单例重置）。"""
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.delenv("NEUROVA_SESSION_JSONL", raising=False)
    from neurova.session_manager import SessionManager

    SessionManager._instance = None
    mgr = SessionManager()
    yield mgr
    SessionManager._instance = None


def _cooldownEvents(mgr, agent_id="a1", session_id="sess-cd-1"):
    """读回时间线上的冷却事件（kind=compaction_cooldown）。"""
    rows = mgr.read_timeline(agent_id, session_id)
    return [r for r in rows if str(r.get("kind")) == "compaction_cooldown"]


# ── 1. 具名常量存在（钉子纪律）────────────────────────────────────

class TestNamedConstants:
    def test_cooldown_steps_constant_is_5_15_30(self):
        from neurova.context_pool import COMPACTION_FAILURE_COOLDOWN_STEPS

        assert COMPACTION_FAILURE_COOLDOWN_STEPS == (5, 15, 30), \
            "冷却步长必须是指定具名常量 (5, 15, 30) 秒"

    def test_cooldown_timeline_kind_constant(self):
        from neurova.context_pool import COMPACTION_COOLDOWN_TIMELINE_KIND

        assert isinstance(COMPACTION_COOLDOWN_TIMELINE_KIND, str)
        assert COMPACTION_COOLDOWN_TIMELINE_KIND, "冷却事件必须落时间线（种类标识具名）"

    def test_subagent_soft_target_constant_exists(self):
        from neurova.agent.swarm import SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS

        assert isinstance(SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS, int)
        assert SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS > 0


# ── 2. 冷却状态机（context_pool 纯逻辑单源）──────────────────────

class TestCompactionCooldownState:
    def test_progressive_steps_5_15_30_then_capped(self):
        """连续失败：冷却按 5/15/30 递增，超出步长表后封顶在末位。"""
        from neurova.context_pool import CompactionCooldownState

        state = CompactionCooldownState()
        base = 1_000_000.0
        first = state.enterCooldown(now=base)
        second = state.enterCooldown(now=base + 100)
        third = state.enterCooldown(now=base + 200)
        fourth = state.enterCooldown(now=base + 300)
        assert (first, second, third) == (5, 15, 30), "递增序列必须是 5→15→30"
        assert fourth == 30, "第 4 次失败封顶在末位步长"
        assert state.consecutiveFailures == 4

    def test_cooling_window_semantics(self):
        """冷却期内 isCooling 为真；截止时间过后为假。"""
        from neurova.context_pool import CompactionCooldownState

        state = CompactionCooldownState()
        assert not state.isCooling(now=1_000.0), "初始不在冷却"
        state.enterCooldown(now=1_000.0)
        assert state.isCooling(now=1_002.0), "5s 步长内必须仍在冷却"
        assert not state.isCooling(now=1_006.0), "步长耗尽后冷却解除"

    def test_success_resets_progression(self):
        """压缩成功复位失败计数：再失败从最小步长重新递增。"""
        from neurova.context_pool import CompactionCooldownState

        state = CompactionCooldownState()
        state.enterCooldown(now=0.0)
        state.enterCooldown(now=10.0)
        assert state.nextCooldownSeconds() == 30, "两次失败后下一次应为 30"
        state.resetOnSuccess()
        assert state.consecutiveFailures == 0
        assert not state.isCooling(now=11.0), "成功复位即解除冷却"
        assert state.enterCooldown(now=12.0) == 5, "复位后从最小步长重新递增"


# ── 3. 冷却持久化：时间线重建（重启不丢）─────────────────────────

class TestCooldownRebuildFromTimeline:
    def test_rebuild_from_persisted_event(self):
        """从时间线冷却事件重建：冷却期内 + 失败次数保真。"""
        from datetime import datetime

        from neurova.context_pool import rebuildCompactionCooldown

        now = datetime.now()
        rows = [
            {"kind": "compaction_cooldown", "ts": now.isoformat(),
             "event": {"consecutiveFailures": 2, "cooldownSeconds": 15, "reason": "auto_compact"}},
        ]
        state = rebuildCompactionCooldown(rows)
        assert state.consecutiveFailures == 2
        assert state.isCooling(), "刚落盘的 15s 冷却必须判定在冷却期内"

    def test_success_event_resets_rebuild(self):
        """冷却事件之后有一次成功压缩 → 重建结果为复位态。"""
        from neurova.context_pool import rebuildCompactionCooldown

        rows = [
            {"kind": "compaction_cooldown", "ts": "2026-11-18T10:00:00",
             "event": {"consecutiveFailures": 3, "cooldownSeconds": 30}},
            {"kind": "context_compacted", "ts": "2026-11-18T10:01:00",
             "event": {"cutoffIndex": 4}},
        ]
        state = rebuildCompactionCooldown(rows)
        assert state.consecutiveFailures == 0, "成功压缩必须复位失败计数"
        assert not state.isCooling(now=1_800_000_000.0)

    def test_empty_or_unrelated_timeline_gives_clean_state(self):
        from neurova.context_pool import rebuildCompactionCooldown

        state = rebuildCompactionCooldown([])
        assert state.consecutiveFailures == 0 and not state.isCooling()
        state = rebuildCompactionCooldown([{"kind": "other_kind", "ts": "2026-11-18T10:00:00"}])
        assert state.consecutiveFailures == 0 and not state.isCooling()

    @pytest.mark.asyncio
    async def test_pipeline_rebuilds_cooldown_after_restart(self, isolatedSessions, monkeypatch):
        """重启不丢：新管线实例（同 agent+session）从时间线重建冷却态，
        冷却期内自动压缩被跳过（压缩器零调用）。"""
        import neurova.context.window_compactor as wc

        pipe1, _ = _mk_pipeline()
        pipe1._agent.session_manager = isolatedSessions
        pipe1._resolveContextBudget = lambda: 4000
        ctx1 = _mk_ctx("sess-cd-restart")

        async def _brokenCompact(msgs, budget, **kwargs):
            raise RuntimeError("compactor broken")

        monkeypatch.setattr(wc, "compact_window", _brokenCompact)
        with pytest.raises(RuntimeError, match="compactor broken"):
            await pipe1._autoCompactContextIfNeeded(ctx1)

        # "重启"：全新管线实例（内存冷却表为空），同 agent + 同 session
        pipe2, _ = _mk_pipeline()
        pipe2._agent.session_manager = isolatedSessions
        pipe2._resolveContextBudget = lambda: 4000
        ctx2 = _mk_ctx("sess-cd-restart")
        calls = {"n": 0}

        async def _spyCompact(msgs, budget, **kwargs):
            calls["n"] += 1
            return None

        monkeypatch.setattr(wc, "compact_window", _spyCompact)
        compacted = await pipe2._autoCompactContextIfNeeded(ctx2)
        assert compacted is False, "重启后冷却期内不得自动压缩"
        assert calls["n"] == 0, "冷却期内压缩器不得被调用"


# ── 4. 管线级冷却门控 ────────────────────────────────────────────

class TestCooldownGatesAutoCompact:
    @pytest.mark.asyncio
    async def test_failure_persists_cooldown_event(self, isolatedSessions, monkeypatch):
        """自动压缩失败 → 冷却事件落时间线（含步长/次数/原因），并进入冷却。"""
        import neurova.context.window_compactor as wc

        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 4000
        ctx = _mk_ctx("sess-cd-1")

        async def _brokenCompact(msgs, budget, **kwargs):
            raise RuntimeError("compactor broken")

        monkeypatch.setattr(wc, "compact_window", _brokenCompact)
        with pytest.raises(RuntimeError, match="compactor broken"):
            await pipe._autoCompactContextIfNeeded(ctx)

        events = _cooldownEvents(isolatedSessions, session_id="sess-cd-1")
        assert len(events) == 1, "失败必须落一条冷却事件"
        payload = events[0].get("event") or {}
        assert payload.get("cooldownSeconds") == 5, "首次失败冷却 5s"
        assert payload.get("consecutiveFailures") == 1
        assert payload.get("reason"), "冷却事件必须带失败原因"

        # 冷却期内（5s 未过）：再次自动压缩被跳过且压缩器零调用
        calls = {"n": 0}

        async def _spyCompact(msgs, budget, **kwargs):
            calls["n"] += 1
            return None

        monkeypatch.setattr(wc, "compact_window", _spyCompact)
        compacted = await pipe._autoCompactContextIfNeeded(ctx)
        assert compacted is False, "冷却期内不得自动压缩"
        assert calls["n"] == 0

    @pytest.mark.asyncio
    async def test_progressive_cooldown_across_expiries(self, isolatedSessions, monkeypatch):
        """连续失败（模拟冷却到期后再失败）：时间线上步长按 5/15/30 递增。"""
        import neurova.context.window_compactor as wc

        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 4000
        ctx = _mk_ctx("sess-cd-2")

        async def _brokenCompact(msgs, budget, **kwargs):
            raise RuntimeError("compactor broken")

        monkeypatch.setattr(wc, "compact_window", _brokenCompact)
        for _ in range(3):
            with pytest.raises(RuntimeError, match="compactor broken"):
                await pipe._autoCompactContextIfNeeded(ctx)
            # 模拟冷却到期（时间前进越过步长）：真实状态对象上把截止时间清零
            state = pipe._compactionCooldowns["sess-cd-2"]
            state.cooldownUntil = 0.0

        events = _cooldownEvents(isolatedSessions, session_id="sess-cd-2")
        steps = [int((e.get("event") or {}).get("cooldownSeconds") or 0) for e in events]
        failures = [int((e.get("event") or {}).get("consecutiveFailures") or 0) for e in events]
        assert steps == [5, 15, 30], f"冷却步长必须按 5/15/30 递增，实际 {steps}"
        assert failures == [1, 2, 3], f"连续失败计数必须递增，实际 {failures}"

    @pytest.mark.asyncio
    async def test_success_resets_and_next_failure_starts_at_min_step(
        self, isolatedSessions, monkeypatch
    ):
        """失败两次 → 压缩成功复位 → 再失败从 5s 起算（不从 30 续跑）。"""
        import neurova.context.window_compactor as wc

        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 4000
        ctx = _mk_ctx("sess-cd-3")

        async def _brokenCompact(msgs, budget, **kwargs):
            raise RuntimeError("compactor broken")

        monkeypatch.setattr(wc, "compact_window", _brokenCompact)
        for _ in range(2):
            with pytest.raises(RuntimeError, match="compactor broken"):
                await pipe._autoCompactContextIfNeeded(ctx)
            pipe._compactionCooldowns["sess-cd-3"].cooldownUntil = 0.0

        async def _healthyCompact(msgs, budget, **kwargs):
            from neurova.context.window_compactor import WindowCompaction, estimate_window_tokens

            kept = list(msgs)[-2:]
            summary_line = {"role": "system", "content": f"[早期对话摘要] 折叠 {len(msgs) - len(kept)} 条"}
            window = [summary_line] + kept
            return WindowCompaction(
                window=window, summary="摘要", compacted_count=len(msgs) - len(kept),
                tokens_before=estimate_window_tokens(msgs),
                tokens_after=estimate_window_tokens(window),
            )

        monkeypatch.setattr(wc, "compact_window", _healthyCompact)
        compacted = await pipe._autoCompactContextIfNeeded(ctx)
        assert compacted is True, "冷却到期 + 压缩器恢复 → 必须压缩成功"

        # 复位后再失败：步长回到 5
        async def _brokenAgain(msgs, budget, **kwargs):
            raise RuntimeError("compactor broken")

        monkeypatch.setattr(wc, "compact_window", _brokenAgain)
        ctx2 = _mk_ctx("sess-cd-3")
        ctx2.metadata = {"context_auto_compacted": True}  # 防同轮标记误伤
        ctx2.metadata = {}
        with pytest.raises(RuntimeError, match="compactor broken"):
            await pipe._autoCompactContextIfNeeded(ctx2)
        events = _cooldownEvents(isolatedSessions, session_id="sess-cd-3")
        assert events, "复位后的失败同样要落冷却事件"
        assert int((events[-1].get("event") or {}).get("cooldownSeconds") or 0) == 5, \
            "成功复位后下一次失败必须从最小步长重新递增"

    @pytest.mark.asyncio
    async def test_manual_compact_unaffected_by_cooldown(self, isolatedSessions, monkeypatch):
        """手动 /compact 不受冷却限制：冷却期内命令照常执行。"""
        import neurova.context.window_compactor as wc

        pipe, agent = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 4000
        ctx = _mk_ctx("sess-cd-4")

        async def _brokenCompact(msgs, budget, **kwargs):
            raise RuntimeError("compactor broken")

        monkeypatch.setattr(wc, "compact_window", _brokenCompact)
        with pytest.raises(RuntimeError, match="compactor broken"):
            await pipe._autoCompactContextIfNeeded(ctx)  # 进入冷却

        manualCalled = {"n": 0}

        async def _manualCompact(history):
            manualCalled["n"] += 1
            return {"compacted": True, "folded": 3, "tokens_before": 9000, "tokens_after": 3000}

        agent.context_orchestrator.manual_compact = _manualCompact
        cmdCtx = ChatContext(user_input="/compact")
        cmdCtx.session_id = "sess-cd-4"
        await pipe._check_compact_command(cmdCtx)
        assert manualCalled["n"] == 1, "冷却期内手动 /compact 必须照常执行"
        assert (cmdCtx.metadata or {}).get("command_dispatched") is True
        assert "已压缩" in str(cmdCtx.reply or ""), "手动命令必须正常回复"


# ── 5. 子代理软目标 ──────────────────────────────────────────────

class TestSubagentSoftTarget:
    @pytest.mark.asyncio
    async def test_member_session_compacts_at_soft_target_before_hard_budget(
        self, isolatedSessions, monkeypatch
    ):
        """member 会话（source=swarm）：软目标低于硬触发线时先于硬预算压缩。"""
        import neurova.agent.swarm as swarm_mod
        from neurova.context_pool import estimateContextTokens

        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        huge_budget = 10_000_000  # 硬触发线（0.85×预算）不可达
        pipe._resolveContextBudget = lambda: huge_budget
        monkeypatch.setattr(swarm_mod, "SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS", 300)

        ctx = _mk_ctx("sess-soft-1", metadata={"source": "swarm"})
        before = estimateContextTokens(ctx.context)
        assert before > 300, "测试前置：上下文必须越过软目标"

        compacted = await pipe._autoCompactContextIfNeeded(ctx)
        assert compacted is True, "member 会话过软目标必须先于硬预算触发压缩"
        assert estimateContextTokens(ctx.context) < before, "压缩后视图严格变小"

        rows = isolatedSessions.read_timeline("a1", "sess-soft-1")
        ev = next(r for r in rows if str(r.get("kind")) == "context_compacted")
        assert (ev.get("event") or {}).get("reason") == "soft_target", \
            "软目标触发的压缩事件必须带 reason=soft_target"

    @pytest.mark.asyncio
    async def test_non_member_session_not_gated_by_soft_target(
        self, isolatedSessions, monkeypatch
    ):
        """非 member 会话不受软目标约束：同参数下不触发。"""
        import neurova.agent.swarm as swarm_mod

        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 10_000_000
        monkeypatch.setattr(swarm_mod, "SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS", 300)

        ctx = _mk_ctx("sess-soft-2")  # 无 source=swarm
        compacted = await pipe._autoCompactContextIfNeeded(ctx)
        assert compacted is False, "非 member 会话不得因软目标触发压缩"
        assert len(ctx.context) == 40, "未触发时上下文不得被改写"

    @pytest.mark.asyncio
    async def test_soft_target_never_raises_threshold_above_hard_budget(
        self, isolatedSessions, monkeypatch
    ):
        """软目标高于硬触发线时取硬线（min 语义）：触发原因是 threshold。"""
        import neurova.agent.swarm as swarm_mod

        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 4000  # 硬线 3400
        monkeypatch.setattr(swarm_mod, "SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS", 10_000_000)

        ctx = _mk_ctx("sess-soft-3", metadata={"source": "swarm"})
        compacted = await pipe._autoCompactContextIfNeeded(ctx)
        assert compacted is True, "超硬线仍须触发（软目标不得抬高阈值）"
        rows = isolatedSessions.read_timeline("a1", "sess-soft-3")
        ev = next(r for r in rows if str(r.get("kind")) == "context_compacted")
        assert (ev.get("event") or {}).get("reason") == "threshold", \
            "软目标高于硬线时按硬线触发（reason=threshold）"

    @pytest.mark.asyncio
    async def test_member_compaction_keeps_recent_originals(self, isolatedSessions, monkeypatch):
        """member 压缩保留近期原文：尾部消息原样在视图与会话盘上（非破坏）。"""
        import neurova.agent.swarm as swarm_mod

        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 10_000_000
        monkeypatch.setattr(swarm_mod, "SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS", 300)

        ctx = _mk_ctx("sess-soft-4", metadata={"source": "swarm"})
        original = list(ctx.context)
        compacted = await pipe._autoCompactContextIfNeeded(ctx)
        assert compacted is True

        # 尾部近期消息原样保留（与 S6 折叠尾保留合流）
        tail_before = [m.get("content") for m in original[-2:]]
        tail_after = [m.get("content") for m in ctx.context[-2:]]
        assert tail_after == tail_before, "压缩视图必须保留尾部近期原文"

        # 原始消息永不删除：会话盘原样（构造盘上历史验证——消息数须大于
        # keep_min 下限，否则压缩器物理无解会走失败链而非折叠）
        for i in range(10):
            isolatedSessions.add_message(
                "a1", "sess-soft-4-disk",
                f"用户消息{i}：" + "测" * 300,
                f"助手回复{i}：" + "答" * 300,
                user_id="u1",
            )
        disk_before = isolatedSessions.get_recent_context("a1", "sess-soft-4-disk", max_messages=None)
        ctx_disk = _mk_ctx("sess-soft-4-disk", context=disk_before, metadata={"source": "swarm"})
        await pipe._autoCompactContextIfNeeded(ctx_disk)
        disk_after = isolatedSessions.get_recent_context("a1", "sess-soft-4-disk", max_messages=None)
        assert [m.get("content") for m in disk_after] == [m.get("content") for m in disk_before], \
            "压缩不得改动会话盘上的原始消息"

    @pytest.mark.asyncio
    async def test_soft_target_notice_on_event_stream(self, isolatedSessions, monkeypatch):
        """软目标压缩通知随既有会话事件通道下发（context_compacted 形态）。"""
        import neurova.agent.swarm as swarm_mod

        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 10_000_000
        monkeypatch.setattr(swarm_mod, "SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS", 300)

        ctx = _mk_ctx("sess-soft-5", metadata={"source": "swarm"})
        emitted = []
        ctx.metadata["event_emitter"] = lambda kind, data: emitted.append((kind, data))

        compacted = await pipe._autoCompactContextIfNeeded(ctx)
        assert compacted is True
        payload = next(d for k, d in emitted if k == "upstream_status")
        assert payload.get("phase") == "context_compacted"
        assert payload.get("reason") == "soft_target", "通知必须可区分软目标触发"


# ── 6. 冷却事件面可见（复用 S6 通知形态）─────────────────────────

class TestCooldownEventNotice:
    @pytest.mark.asyncio
    async def test_failure_emits_cooldown_notice(self, isolatedSessions, monkeypatch):
        """失败进入冷却 → emitter 收到 phase=context_compact_cooldown 通知。"""
        import neurova.context.window_compactor as wc

        pipe, _ = _mk_pipeline()
        pipe._agent.session_manager = isolatedSessions
        pipe._resolveContextBudget = lambda: 4000
        ctx = _mk_ctx("sess-cd-5")
        emitted = []
        ctx.metadata = {"event_emitter": lambda kind, data: emitted.append((kind, data))}

        async def _brokenCompact(msgs, budget, **kwargs):
            raise RuntimeError("compactor broken")

        monkeypatch.setattr(wc, "compact_window", _brokenCompact)
        with pytest.raises(RuntimeError, match="compactor broken"):
            await pipe._autoCompactContextIfNeeded(ctx)

        assert emitted, "冷却必须发射事件通道通知"
        kinds = [k for k, _ in emitted]
        assert "upstream_status" in kinds, "复用既有上游状态事件通道"
        payload = next(d for k, d in emitted if k == "upstream_status"
                       and d.get("phase") == "context_compact_cooldown")
        assert payload.get("cooldownSeconds") == 5
        assert payload.get("consecutiveFailures") == 1
        assert payload.get("reason"), "通知必须带失败原因"
